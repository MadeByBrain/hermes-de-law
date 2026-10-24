"""EU law from the Publications Office of the European Union (CELLAR).

Text: content negotiation on https://publications.europa.eu/resource/celex/<CELEX>
(Accept: application/xhtml+xml, Accept-Language: deu|eng). Consolidated versions
are listed with one SPARQL query on the Publications Office endpoint.
EUR-Lex itself is not contacted (it answers automated clients with HTTP 202).
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from .citations import int_to_roman, roman_to_int
from .client import LawError, Response, Store
from .gii import fold
from .textutil import html_to_text, parse_html

CELLAR = "https://publications.europa.eu/resource/celex/"
SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
LANG_CODES = {"de": "deu", "en": "eng"}

# Well-known acts. Each CELEX number was checked against CELLAR (title and ELI-structured XHTML)
# when this list was made; older acts without ELI markup (e.g. 2002/58/EC) are not listed.
KNOWN_ACTS: List[Dict[str, Any]] = [
    {"celex": "32016R0679", "de": "DSGVO", "en": "GDPR", "aliases": ["DS-GVO", "Datenschutz-Grundverordnung", "General Data Protection Regulation"]},
    {"celex": "32024R1689", "de": "KI-VO", "en": "AI Act", "aliases": ["KI-Verordnung", "AIA", "Artificial Intelligence Act", "EU AI Act", "Verordnung über künstliche Intelligenz"]},
    {"celex": "32022R2065", "de": "DSA", "en": "DSA", "aliases": ["Digital Services Act", "Gesetz über digitale Dienste"]},
    {"celex": "32022R1925", "de": "DMA", "en": "DMA", "aliases": ["Digital Markets Act", "Gesetz über digitale Märkte"]},
    {"celex": "32022L2555", "de": "NIS-2-Richtlinie", "en": "NIS2", "aliases": ["NIS 2", "NIS-2", "NIS2-Richtlinie", "NIS2 Directive"]},
    {"celex": "32022R2554", "de": "DORA", "en": "DORA", "aliases": ["Digital Operational Resilience Act"]},
    {"celex": "32023R2854", "de": "Data Act", "en": "Data Act", "aliases": ["Datenverordnung", "EU Data Act"]},
    {"celex": "32022R0868", "de": "DGA", "en": "DGA", "aliases": ["Data Governance Act", "Daten-Governance-Rechtsakt"]},
    {"celex": "32014R0910", "de": "eIDAS-VO", "en": "eIDAS", "aliases": ["eIDAS", "eIDAS-Verordnung"]},
    {"celex": "32023R1114", "de": "MiCA", "en": "MiCA", "aliases": ["MiCAR", "Markets in Crypto-Assets"]},
    {"celex": "32024R2847", "de": "CRA", "en": "CRA", "aliases": ["Cyber Resilience Act", "Cyberresilienz-Verordnung"]},
    {"celex": "32019L1937", "de": "Whistleblower-RL", "en": "Whistleblower Directive", "aliases": ["Hinweisgeberrichtlinie", "HinSch-RL"]},
    {"celex": "32022L2464", "de": "CSRD", "en": "CSRD", "aliases": ["Corporate Sustainability Reporting Directive"]},
    {"celex": "32024L1760", "de": "CSDDD", "en": "CSDDD", "aliases": ["CS3D", "Lieferkettenrichtlinie", "Corporate Sustainability Due Diligence Directive"]},
    {"celex": "32008R0593", "de": "Rom I", "en": "Rome I", "aliases": ["Rom-I-VO", "Rome I Regulation"]},
    {"celex": "32012R1215", "de": "Brüssel Ia", "en": "Brussels Ia", "aliases": ["EuGVVO", "Brüssel-Ia-VO", "Brussels I bis"]},
    {"celex": "32019L0882", "de": "EAA", "en": "European Accessibility Act", "aliases": ["Barrierefreiheitsrichtlinie", "European Accessibility Act"]},
    {"celex": "32024L2853", "de": "ProdHaft-RL", "en": "Product Liability Directive", "aliases": ["Produkthaftungsrichtlinie", "PLD"]},
]


def _known_index() -> Dict[str, Dict[str, Any]]:
    idx: Dict[str, Dict[str, Any]] = {}
    for act in KNOWN_ACTS:
        for name in [act["de"], act["en"], act["celex"], *act["aliases"]]:
            idx[_key(name)] = act
    return idx


def _key(name: str) -> str:
    return re.sub(r"[\s._()-]+", "", fold(name))


_KNOWN = _known_index()

_CELEX = re.compile(r"^(?:celex[:\s]*)?([0-9])(\d{4})([A-Z]{1,2})(\d{4})(?:-(\d{8}))?$", re.I)
_NUMBERED = re.compile(r"(verordnung|vo|regulation|richtlinie|rl|directive|beschluss|decision)\s*\((eu|eg|ewg|eu,\s*euratom|ec|eec)\)\s*(?:nr\.?|no\.?)?\s*(\d+)/(\d+)", re.I)
_OLD_DIR = re.compile(r"(richtlinie|rl|directive)\s*(\d{2,4})/(\d+)/(eg|ewg|ec|eec|eu)", re.I)
_TYPE = {"verordnung": "R", "vo": "R", "regulation": "R", "richtlinie": "L", "rl": "L", "directive": "L",
         "beschluss": "D", "decision": "D"}


def _year4(y: str) -> str:
    if len(y) == 4:
        return y
    n = int(y)
    return str(1900 + n if n > 50 else 2000 + n)


def match_eu(name: str) -> Optional[Dict[str, Any]]:
    """Recognise an EU act: alias (DSGVO, GDPR, AI Act), CELEX, or 'Verordnung (EU) 2016/679'."""
    if not name:
        return None
    raw = " ".join(name.split())
    act = _KNOWN.get(_key(raw))
    if act:
        return dict(act)
    m = _CELEX.match(raw.replace(" ", ""))
    if m and m.group(1) == "3":
        celex = f"3{m.group(2)}{m.group(3).upper()}{m.group(4)}"
        return dict(_KNOWN.get(_key(celex)) or {"celex": celex, "de": celex, "en": celex, "aliases": []})
    for rx, kind in ((_NUMBERED, "numbered"), (_OLD_DIR, "olddir")):
        m = rx.search(raw)
        if not m:
            continue
        if kind == "numbered":
            typ, a, b = _TYPE[m.group(1).lower()], m.group(3), m.group(4)
            # Since 2015 acts are "(EU) yyyy/n"; before, regulations were "No n/yyyy" (or n/yy).
            if len(a) == 4 and 1950 <= int(a) <= 2100 and not (typ == "R" and len(b) == 4 and int(b) < 2015):
                year, num = a, b
            else:
                year, num = _year4(b), a
        else:
            typ, year, num = "L", _year4(m.group(2)), m.group(3)
        celex = f"3{year}{typ}{int(num):04d}"
        return dict(_KNOWN.get(_key(celex)) or {"celex": celex, "de": raw, "en": raw, "aliases": []})
    return None


def search_known(query: str) -> List[Dict[str, Any]]:
    q = fold(query)
    out = []
    for act in KNOWN_ACTS:
        names = [act["de"], act["en"], *act["aliases"], act["celex"]]
        if any(q and (q in fold(n) or fold(n) == q) for n in names):
            out.append(act)
    m = match_eu(query)
    if m and all(a["celex"] != m["celex"] for a in out):
        out.insert(0, m)
    return out


# ---------------------------------------------------------------- fetching

def _parse_sparql(body: bytes, _resp: Response) -> List[str]:
    try:
        data = json.loads(body.decode("utf-8"))
        return [b["celex"]["value"] for b in data["results"]["bindings"]]
    except (ValueError, KeyError, TypeError) as err:
        raise LawError("bad_response", f"The EU version list could not be read: {err}") from err


def _parse_doc(body: bytes, resp: Response) -> Dict[str, Any]:
    ctype = resp.headers.get("content-type", "")
    if "html" not in ctype:
        raise LawError("bad_response", f"The Publications Office sent {ctype or 'no content type'} instead of XHTML.")
    text = body.decode("utf-8", errors="replace")
    root, ids = parse_html(text)
    units: Dict[str, Dict[str, str]] = {}
    for uid, node in ids.items():
        m = re.fullmatch(r"(art|rct|anx)_([0-9]+[a-z]*|[IVXLC]+[a-z]*)", uid)
        if not m:
            continue
        units[uid] = {"text": _strip_markers(html_to_text(node))}
    head = html_to_text(root)
    cut = head.find("\n▼B")
    facts = header_facts(head[:cut if cut > 0 else 6000][:12000])
    return {"units": units, "facts": facts, "cellar_url": resp.url}


_MARKERS = re.compile(r"\s*[►▼◄]\s*(?:[A-Z]\d*\b)?")
_CLOSE_BEFORE_PUNCT = re.compile(r"\s*◄\s*(?=[;,.:)\]])")


def _strip_markers(text: str) -> str:
    """Remove the consolidation markers (►B, ▼M1, ◄) without touching the words."""
    text = _CLOSE_BEFORE_PUNCT.sub("", text)
    text = _MARKERS.sub(" ", text)
    return "\n".join(" ".join(line.split()) if not line.startswith(" ") else line.rstrip()
                     for line in text.split("\n")).strip()


class EuLaw:
    def __init__(self, store: Store):
        self.store = store

    def versions(self, celex: str) -> List[str]:
        base = celex[1:]  # 32016R0679 -> 2016R0679
        query = ("PREFIX cdm: <http://publications.europa.eu/ontology/cdm#> "
                 "SELECT DISTINCT ?celex WHERE { ?w cdm:resource_legal_id_celex ?celex . "
                 f"FILTER(STRSTARTS(STR(?celex), \"0{base}-\")) }} ORDER BY DESC(?celex) LIMIT 50")
        url = SPARQL + "?" + urllib.parse.urlencode({"query": query, "format": "application/sparql-results+json"})
        last: Optional[LawError] = None
        for _ in range(2):  # the endpoint answers 502 now and then
            try:
                got = self.store.fetch(f"eu-versions-{celex}", url, _parse_sparql,
                                       headers={"Accept": "application/sparql-results+json"},
                                       max_bytes=2 * 1024 * 1024)
                return [c for c in got.data if re.fullmatch(r"0\d{4}[A-Z]{1,2}\d{4}-\d{8}", c)]
            except LawError as err:
                last = err
                if err.kind != "upstream":
                    break
        raise last or LawError("upstream", "The EU version list is unavailable.")

    def pick_version(self, celex: str) -> Tuple[str, Optional[str], Optional[str]]:
        """(document id, consolidated date or None, note). Latest consolidation not in the future."""
        try:
            versions = self.versions(celex)
        except LawError as err:
            return celex, None, f"Consolidated versions could not be listed ({err.message}); original text used."
        today = time.strftime("%Y%m%d")
        valid = sorted(v for v in versions if v[-8:] <= today)
        if not valid:
            return celex, None, "No consolidated version exists; this is the text as published in the Official Journal."
        best = valid[-1]
        return best, f"{best[-8:-4]}-{best[-4:-2]}-{best[-2:]}", None

    def document(self, doc_id: str, lang: str):
        return self.store.fetch(
            f"eu-doc-{doc_id}-{lang}", CELLAR + doc_id, _parse_doc,
            headers={"Accept": "application/xhtml+xml", "Accept-Language": LANG_CODES.get(lang, "deu")},
            immutable=True)


def unit_id(kind: str, number: str) -> Optional[str]:
    if kind == "recital":
        return f"rct_{int(number)}" if number.isdigit() else None
    if kind == "annex":
        n = number.upper()
        if n.isdigit():
            n = int_to_roman(int(n))
        return f"anx_{n}" if roman_to_int(n) else None
    return f"art_{number.lower()}"


def human_url(doc_id: str, lang: str) -> str:
    return f"https://eur-lex.europa.eu/legal-content/{'DE' if lang == 'de' else 'EN'}/TXT/?uri=CELEX:{doc_id}"


def header_facts(raw: str) -> Dict[str, Any]:
    """Title, Official Journal reference, amendments and corrigenda from the document head.
    ``raw`` still carries the consolidation markers (►B, ►M1, ►C1)."""
    facts: Dict[str, Any] = {}
    lines = [ln.strip() for ln in raw.split("\n")]
    for ln in lines:
        if ln.startswith("Dieser Text dient lediglich") or ln.startswith("This text is meant purely"):
            facts["legal_effect"] = ln
            break
    base = next((ln for ln in lines if re.match(r"^►B\s*\|", ln)), "")
    if base:
        body = base.split("|", 1)[1].strip()
        m = re.search(r"\((ABl\.|OJ)\s+L[^()]*\)\s*$", body)
        if m:
            facts["official_journal"] = m.group(0).strip()[1:-1]
            body = body[:m.start()].strip()
        facts["title"] = body
    else:
        first = lines[0] if lines else ""
        cells = [c.strip() for c in first.split("|")]
        if len(cells) == 4 and re.match(r"^L\s", cells[3]):
            facts["official_journal"] = f"{cells[2]} {cells[3]}, {cells[0]}".strip()
        i = next((k for k, ln in enumerate(lines) if re.match(r"^(VERORDNUNG|RICHTLINIE|BESCHLUSS|REGULATION|DIRECTIVE|DECISION)\b", ln)), None)
        if i is not None:
            facts["title"] = " ".join(lines[i:i + 3])
    amended = [ln for ln in lines if re.match(r"^►M\d+\s*\|", ln)]
    corrected = [ln for ln in lines if re.match(r"^►C\d+\s*\|", ln)]
    if amended:
        facts["amended_by"] = [_row(ln) for ln in amended[:20]]
    if corrected:
        facts["corrected_by"] = [_row(ln) for ln in corrected[:20]]
    return facts


def _row(line: str) -> str:
    cells = [c.strip() for c in line.lstrip("►").split("|")]
    return f"{cells[0]}: " + ", ".join(c for c in cells[1:] if c)
