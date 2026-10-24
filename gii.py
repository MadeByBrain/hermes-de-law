"""German federal law from gesetze-im-internet.de (Bundesamt für Justiz)."""

from __future__ import annotations

import io
import re
import time
import unicodedata
import zipfile
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

from .client import LawError, Response, Store
from .textutil import xml_to_text

BASE = "https://www.gesetze-im-internet.de"
TOC_URL = f"{BASE}/gii-toc.xml"
MAX_ZIP_MEMBER = 40 * 1024 * 1024
_LETTERS = [str(d) for d in range(1, 10)] + [chr(c) for c in range(ord("A"), ord("Z") + 1)]


# ---------------------------------------------------------------- index

def _parse_toc(body: bytes, _resp: Response) -> List[List[str]]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as err:
        raise LawError("bad_response", f"gii-toc.xml could not be read: {err}") from err
    items = []
    for item in root.iter("item"):
        title = " ".join((item.findtext("title") or "").split())
        link = item.findtext("link") or ""
        m = re.search(r"gesetze-im-internet\.de/([^/]+)/xml\.zip", link)
        if m:
            items.append([m.group(1), title])
    if not items:
        raise LawError("bad_response", "gii-toc.xml contained no laws.")
    return items


def _parse_letter(body: bytes, _resp: Response) -> List[List[str]]:
    text = body.decode("cp1252", errors="replace")
    rows = re.findall(r'<a href="\./([^/"]+)/index\.html"><abbr title="([^"]*)">\s*(.*?)\s*</abbr>', text, re.S)
    import html as _html
    return [[slug, " ".join(_html.unescape(title).split()), " ".join(_html.unescape(abbr).split())]
            for slug, title, abbr in rows]


def fold(text: str) -> str:
    """Case- and accent-insensitive form used for matching (ä -> a, ß -> ss)."""
    text = (text or "").replace("ß", "ss").lower()
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _letter_for(abbr: str) -> Optional[str]:
    first = fold(abbr.strip())[:1].upper()
    return first if first in _LETTERS else None


class GermanLaw:
    def __init__(self, store: Store):
        self.store = store

    # -- index -------------------------------------------------------------
    def toc(self):
        return self.store.fetch("gii-toc", TOC_URL, _parse_toc)

    def letter(self, letter: str):
        # The abbreviation lists change rarely; refresh at most weekly.
        age = max(self.store.max_age_s(), 7 * 24 * 3600)
        return self.store.fetch(f"gii-letter-{letter}", f"{BASE}/Teilliste_{letter}.html", _parse_letter,
                                max_age_s=age)

    def resolve(self, name: str) -> Tuple[str, str, Optional[str]]:
        """Return (slug, title, abbreviation) for a law name, abbreviation or folder name."""
        query = " ".join((name or "").split())
        if not query:
            raise LawError("bad_argument", "No law given.", "Pass the law, e.g. 'StGB' or 'Bürgerliches Gesetzbuch'.")
        toc = self.toc().data
        by_slug = {slug: title for slug, title in toc}
        q = fold(query)
        letter = _letter_for(query) if len(query) <= 30 else None
        rows: List[List[str]] = []
        if letter:
            try:
                rows = self.letter(letter).data
            except LawError:
                rows = []  # the abbreviation list is a convenience; fall back to folder names
        if rows:
            hits = [r for r in rows if fold(r[2]) == q]
            if not hits:
                compact = re.sub(r"[\s.-]", "", q)
                hits = [r for r in rows if re.sub(r"[\s.-]", "", fold(r[2])) == compact]
            if len(hits) == 1:
                return hits[0][0], hits[0][1], hits[0][2]
            if len(hits) > 1:
                raise LawError("ambiguous_law", f"'{query}' is the abbreviation of several laws.",
                               "Pass one of the listed folder names as law.",
                               {"candidates": [{"law": r[0], "abbreviation": r[2], "title": r[1]} for r in hits[:10]]})
        if q in by_slug:
            return q, by_slug[q], None
        exact = [(s, t) for s, t in toc if fold(t) == q]
        if len(exact) == 1:
            return exact[0][0], exact[0][1], None
        ranked = rank_titles(toc, query)
        if ranked and (len(ranked) == 1 or ranked[0][0] > ranked[1][0]):
            slug, title = ranked[0][1], ranked[0][2]
            return slug, title, None
        if ranked:
            raise LawError("ambiguous_law", f"'{query}' matches several laws.",
                           "Pass one of the listed folder names as law, or a longer name.",
                           {"candidates": [{"law": s, "title": t} for _, s, t in ranked[:10]]})
        raise LawError("law_not_found", f"No federal law found for '{query}'.",
                       "Call de_law_search with a shorter name or a keyword from the title. "
                       "State (Land) law is not covered.")

    def search(self, query: str, limit: int) -> List[Dict[str, str]]:
        toc = self.toc().data
        q = fold(query.strip())
        results: List[Dict[str, str]] = []
        seen = set()
        letter = _letter_for(query)
        if letter and len(q) <= 20:
            try:
                rows = self.letter(letter).data
            except LawError:
                rows = []
            for slug, title, abbr in rows:
                if fold(abbr) == q or fold(abbr).startswith(q) and len(q) >= 2:
                    if slug not in seen:
                        seen.add(slug)
                        results.append({"law": slug, "abbreviation": abbr, "title": title,
                                        "match": "abbreviation"})
        for _, slug, title in rank_titles(toc, query):
            if slug not in seen:
                seen.add(slug)
                results.append({"law": slug, "title": title, "match": "title"})
        exact_first = sorted(results, key=lambda r: (0 if fold(r.get("abbreviation", "")) == q else 1))
        return exact_first[:limit]

    # -- one law -----------------------------------------------------------
    def load(self, slug: str):
        return self.store.fetch(f"gii-law-{slug}", f"{BASE}/{slug}/xml.zip", _parse_law_zip)


def _stem(word: str) -> str:
    return word if len(word) <= 5 else word[:max(5, len(word) - 3)]


def rank_titles(toc: List[List[str]], query: str) -> List[Tuple[float, str, str]]:
    words = [w for w in re.findall(r"[0-9a-z]+", fold(query)) if len(w) > 1]
    if not words:
        return []
    stems = [_stem(w) for w in words]
    scored = []
    for slug, title in toc:
        tw = re.findall(r"[0-9a-z]+", fold(title))
        hits = sum(1 for s in stems if any(t.startswith(s) or (len(s) >= 6 and s in t) for t in tw))
        if hits == len(stems):
            # Whole-word hits beat stem hits; shorter titles and titles that start with the query rank first.
            whole = sum(1 for w in words if any(t.startswith(w) for t in tw))
            score = 10.0 + 2.0 * whole + (3.0 if fold(title).startswith(fold(query)[:12]) else 0.0) - len(title) / 200.0
            if slug == fold(query):
                score += 20
            scored.append((score, slug, title))
    scored.sort(key=lambda x: -x[0])
    return scored


def _parse_law_zip(body: bytes, resp: Response) -> Dict[str, Any]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile as err:
        raise LawError("bad_response", f"{resp.url} is not a valid ZIP file.") from err
    members = [i for i in zf.infolist() if i.filename.lower().endswith(".xml")]
    if not members:
        raise LawError("bad_response", f"{resp.url} holds no XML file.")
    info = members[0]
    if info.file_size > MAX_ZIP_MEMBER:
        raise LawError("too_large", "The law's XML is larger than 40 MB.")
    with zf.open(info) as fh:
        xml = fh.read(MAX_ZIP_MEMBER + 1)
    return parse_law_xml(xml)


def _date(builddate: str) -> str:
    m = re.match(r"(\d{4})(\d{2})(\d{2})", builddate or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


def parse_law_xml(xml: bytes) -> Dict[str, Any]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as err:
        raise LawError("bad_response", f"The law's XML could not be read: {err}") from err
    norms = root.findall("norm")
    if not norms:
        raise LawError("bad_response", "The law's XML contains no norms.")
    head = norms[0].find("metadaten")
    meta: Dict[str, Any] = {
        "jurabk": (head.findtext("jurabk") or "").strip() if head is not None else "",
        "amtabk": (head.findtext("amtabk") or "").strip() if head is not None else "",
        "title": " ".join((head.findtext("langue") or "").split()) if head is not None else "",
        "short_title": " ".join((head.findtext("kurzue") or "").split()) if head is not None else "",
        "enacted": (head.findtext("ausfertigung-datum") or "").strip() if head is not None else "",
        "gazette": [], "status": [],
        "data_built": _date(root.get("builddate", "")),
    }
    if head is not None:
        for fs in head.findall("fundstelle"):
            per = (fs.findtext("periodikum") or "").strip()
            zit = (fs.findtext("zitstelle") or "").strip()
            if per or zit:
                meta["gazette"].append(f"{per} {zit}".strip())
        for st in head.findall("standangabe"):
            typ = (st.findtext("standtyp") or "").strip()
            com = " ".join((st.findtext("standkommentar") or "").split())
            if com:
                meta["status"].append({"type": typ, "text": com})
        meta["footnote"] = xml_to_text(norms[0].find("textdaten/fussnoten"))[:3000]
    builds = []
    path: List[Tuple[str, str]] = []
    out = []
    for norm in norms[1:]:
        md = norm.find("metadaten")
        if md is None:
            continue
        b = norm.get("builddate", "")
        if b:
            builds.append(b)
        g = md.find("gliederungseinheit")
        enbez = " ".join((md.findtext("enbez") or "").split())
        if g is not None and not enbez:
            code = (g.findtext("gliederungskennzahl") or "").strip()
            label = " ".join(x for x in [(g.findtext("gliederungsbez") or "").strip(),
                                          " ".join((g.findtext("gliederungstitel") or "").split())] if x)
            depth = max(1, len(code) // 3)
            path = [p for p in path if len(p[0]) // 3 < depth]
            path.append((code, label))
            continue
        if not enbez:
            continue
        titel_el = md.find("titel")
        titel = " ".join(xml_to_text(titel_el).split()) if titel_el is not None else ""
        text = xml_to_text(norm.find("textdaten/text"))
        notes = xml_to_text(norm.find("textdaten/fussnoten"))
        entry = {"id": enbez, "title": titel, "text": text, "path": [p[1] for p in path]}
        if notes:
            entry["notes"] = notes[:4000]
        out.append(entry)
    if builds:
        meta["data_built"] = _date(max(builds)) or meta["data_built"]
    return {"meta": meta, "norms": out}


# ---------------------------------------------------------------- sections

_RANGE = re.compile(r"(?:\(XXXX\)\s*)?(§§|Art)\s*(\d+)([a-z]*)\s+(bis|und)\s+(\d+)([a-z]*)", re.I)


def norm_key(enbez: str) -> Tuple[str, str]:
    """('section'|'article'|'other', number) for an enbez like '§ 203', 'Art 1', 'Anlage 2'."""
    e = re.sub(r"^\(XXXX\)\s*", "", enbez or "").strip()
    m = re.match(r"^(§|Art\.?|Artikel)\s*(\d+[a-z]*)$", e, re.I)
    if m:
        return ("section" if m.group(1) == "§" else "article", m.group(2).lower())
    m = re.match(r"^(Anlage|Anhang)\s*(\S+)?$", e, re.I)
    if m:
        return ("annex", (m.group(2) or "").lower())
    return ("other", fold(e))


def _num_tuple(num: str, suffix: str) -> Tuple[int, str]:
    return (int(num), suffix.lower())


def find_norm(law: Dict[str, Any], kind: Optional[str], number: Optional[str],
              label: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], str]:
    """Return (norm, how) where how is 'exact', 'range' or 'label'."""
    norms = law["norms"]
    if number:
        number = number.lower()
        wanted_kinds = [kind] if kind in ("section", "article", "annex") else ["section", "article"]
        for want in wanted_kinds + ["section", "article"]:
            for n in norms:
                k, num = norm_key(n["id"])
                if k == want and num == number:
                    return n, "exact"
        m = re.match(r"^(\d+)([a-z]*)$", number)
        if m:
            target = _num_tuple(m.group(1), m.group(2))
            for n in norms:
                r = _RANGE.search(n["id"])
                if not r:
                    continue
                lo, hi = _num_tuple(r.group(2), r.group(3)), _num_tuple(r.group(5), r.group(6))
                if (r.group(4).lower() == "bis" and lo <= target <= hi) or target in (lo, hi):
                    return n, "range"
    if label:
        f = fold(label)
        for n in norms:
            if fold(n["id"]) == f or fold(n["id"]).startswith(f):
                return n, "label"
    return None, ""


def norm_url(slug: str, enbez: str) -> str:
    k, num = norm_key(enbez)
    if k == "section" and num:
        return f"{BASE}/{slug}/__{num}.html"
    if k == "article" and num:
        return f"{BASE}/{slug}/art_{num}.html"
    return f"{BASE}/{slug}/index.html"


def law_url(slug: str) -> str:
    return f"{BASE}/{slug}/index.html"


def cite_label(enbez: str, abbr: str) -> str:
    e = re.sub(r"^\(XXXX\)\s*", "", enbez).strip()
    e = re.sub(r"^Art\b\.?", "Art.", e)
    return f"{e} {abbr}".strip()


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
