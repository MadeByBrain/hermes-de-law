"""Tool handlers. Every handler returns a JSON string and never raises: bad arguments,
source outages and bugs come back as {"ok": false, "error", "error_type", "next_step"}."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional

from . import eu as eu_mod
from . import gii, rii
from .citations import parse_citation, split_section
from .client import LawError, Store

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHARS = 6000
_PARA = re.compile(r"^\s*\((\d+[a-z]?)\)\s")


# ---------------------------------------------------------------- helpers

def _dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _error(kind: str, message: str, hint: str = "", details: Optional[dict] = None) -> str:
    payload: Dict[str, Any] = {"ok": False, "error": message, "error_type": kind}
    for key, value in (details or {}).items():
        if value not in (None, "", []):
            payload[key] = value
    if hint:
        payload["next_step"] = hint
    return _dump(payload)


def _int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        num = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, num))


def _day(lang: str, ts: float) -> str:
    """Date the text was fetched from (or last confirmed by) the source."""
    return time.strftime("%d.%m.%Y" if lang == "de" else "%Y-%m-%d", time.gmtime(ts or time.time()))


def _de_date(iso: str) -> str:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})$", iso or "")
    return f"{m.group(3)}.{m.group(2)}.{m.group(1)}" if m else (iso or "")


def _cut(text: str, max_chars: int) -> Dict[str, Any]:
    if len(text) <= max_chars:
        return {"text": text, "truncated": False}
    cut = text.rfind("\n", max_chars // 2, max_chars)
    cut = cut if cut > 0 else max_chars
    return {"text": text[:cut].rstrip(), "truncated": True, "total_chars": len(text)}


_PARA_DOT = re.compile(r"^(\d+[a-z]?)\.\s")


def split_paragraphs(text: str, dotted: bool = False) -> List[tuple]:
    """[(number, text)] for '(1) ...' blocks; lines before the first marker are dropped.
    ``dotted``: also accept '1. ...' paragraphs (English EU texts) when no '(1)' marker exists."""
    rx = _PARA
    if dotted and not any(_PARA.match(line) for line in text.split("\n")):
        rx = _PARA_DOT
    out: List[tuple] = []
    for line in text.split("\n"):
        m = rx.match(line)
        if m:
            out.append([m.group(1), [line]])
        elif out:
            out[-1][1].append(line)
    return [(n, "\n".join(lines).strip()) for n, lines in out]


def _iso_ts(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)) if ts else ""


class Tools:
    def __init__(self, store: Optional[Store] = None):
        self.store = store or Store()
        self.de = gii.GermanLaw(self.store)
        self.eu = eu_mod.EuLaw(self.store)
        self.cases = rii.CaseLaw(self.store)

    # -- settings ----------------------------------------------------------
    def _lang(self, source_lang: str) -> str:
        pref = str(self.store.setting("language", "auto") or "auto").lower()
        return pref if pref in ("de", "en") else source_lang

    def _flag(self, key: str) -> bool:
        value = self.store.setting(key, True)
        if isinstance(value, str):
            return value.strip().lower() not in ("false", "0", "no", "off")
        return bool(value)

    def _eu_lang(self, requested: Any) -> str:
        lang = str(requested or self.store.setting("eu_language", "de") or "de").lower()[:2]
        return lang if lang in ("de", "en") else "de"

    # -- sources -----------------------------------------------------------
    def _source_de(self, url: str, data_built: str, cached) -> Dict[str, Any]:
        lang = self._lang("de")
        built = _de_date(data_built) if lang == "de" else data_built
        if lang == "de":
            attribution = (f"Quelle: Gesetze im Internet (www.gesetze-im-internet.de), Bundesministerium der Justiz "
                           f"und für Verbraucherschutz, Redaktion Bundesamt für Justiz. Konsolidierte Fassung, "
                           f"Datenstand {built}, abgerufen am {_day(lang, cached.fetched_at)}, Auszug erstellt mit hermes-de-law. "
                           f"Verbindlich ist allein die im Bundesgesetzblatt verkündete Fassung.")
        else:
            attribution = (f"Source: Gesetze im Internet (www.gesetze-im-internet.de), German Federal Ministry of "
                           f"Justice, edited by the Federal Office of Justice. Consolidated text, data as of {built}, "
                           f"retrieved {_day(lang, cached.fetched_at)}, excerpt made with hermes-de-law. Only the version promulgated "
                           f"in the Bundesgesetzblatt (Federal Law Gazette) is legally binding.")
        return {"name": "Gesetze im Internet", "url": url, "data_as_of": data_built,
                "retrieved_at": _iso_ts(cached.fetched_at), "cache": cached.state,
                "attribution": attribution}

    def _source_eu(self, doc_id: str, consolidated: Optional[str], text_lang: str, cached) -> Dict[str, Any]:
        lang = self._lang(text_lang)
        if lang == "de":
            version = (f"Konsolidierte Fassung vom {_de_date(consolidated)}" if consolidated
                       else "Fassung wie im Amtsblatt veröffentlicht")
            attribution = (f"Quelle: Amt für Veröffentlichungen der Europäischen Union (publications.europa.eu, "
                           f"EUR-Lex-Daten), © Europäische Union, CC BY 4.0. {version} (CELEX {doc_id}), abgerufen "
                           f"am {_day(lang, cached.fetched_at)}; Auszug und Textformat erstellt mit hermes-de-law. Verbindlich ist "
                           f"allein die im Amtsblatt der Europäischen Union veröffentlichte Fassung.")
        else:
            version = (f"Consolidated version of {consolidated}" if consolidated
                       else "Text as published in the Official Journal")
            attribution = (f"Source: Publications Office of the European Union (publications.europa.eu, EUR-Lex "
                           f"data), © European Union, CC BY 4.0. {version} (CELEX {doc_id}), retrieved "
                           f"{_day(lang, cached.fetched_at)}; excerpt and plain-text formatting by hermes-de-law. Only the Official "
                           f"Journal of the European Union is authentic.")
        return {"name": "Publications Office of the EU (CELLAR)", "url": eu_mod.human_url(doc_id, text_lang),
                "data_url": eu_mod.CELLAR + doc_id, "retrieved_at": _iso_ts(cached.fetched_at),
                "cache": cached.state, "license": "CC BY 4.0", "attribution": attribution}

    def _source_case(self, doc: Dict[str, Any], cached) -> Dict[str, Any]:
        lang = self._lang("de")
        if lang == "de":
            attribution = (f"Quelle: Rechtsprechung im Internet (www.rechtsprechung-im-internet.de), Bundesministerium "
                           f"der Justiz und für Verbraucherschutz, Bundesamt für Justiz; Dokument {doc.get('doc_id')}, "
                           f"abgerufen am {_day(lang, cached.fetched_at)}, Auszug erstellt mit hermes-de-law.")
        else:
            attribution = (f"Source: Rechtsprechung im Internet (www.rechtsprechung-im-internet.de), German Federal "
                           f"Ministry of Justice, Federal Office of Justice; document {doc.get('doc_id')}, retrieved "
                           f"{_day(lang, cached.fetched_at)}, excerpt made with hermes-de-law.")
        return {"name": "Rechtsprechung im Internet", "url": doc.get("url") or rii.decision_url(doc.get("doc_id", "")),
                "retrieved_at": _iso_ts(cached.fetched_at), "cache": cached.state, "attribution": attribution}

    @staticmethod
    def _stale_note(cached) -> Optional[str]:
        if cached.state == "stale":
            return (f"The source could not be reached; this is the copy cached on {_iso_ts(cached.fetched_at)}. "
                    "Say so when you quote it.")
        return None

    # ------------------------------------------------------------- de_law_get
    def law_get(self, args: Dict[str, Any]) -> Dict[str, Any]:
        citation = str(args.get("citation") or "").strip()
        parsed = parse_citation(citation) if citation else {}
        if args.get("law"):
            parsed["law"] = str(args["law"]).strip()
        if args.get("section") not in (None, ""):
            sec = split_section(args["section"])
            parsed.update({k: v for k, v in sec.items() if v})
        if args.get("paragraph") not in (None, ""):
            parsed["paragraph"] = str(args["paragraph"]).strip().strip("()").lower()
        law = parsed.get("law")
        if not law:
            raise LawError("bad_argument", "No law given.",
                           "Pass citation like '§ 203 StGB' or 'Art. 6 DSGVO', or law plus section.")
        if not parsed.get("number") and not parsed.get("label"):
            raise LawError("bad_argument", f"No section or article given for {law}.",
                           "Add the number (e.g. '§ 1', 'Art. 6'), or call de_law_toc to list the sections.")
        max_chars = _int(args.get("max_chars"), DEFAULT_MAX_CHARS, 500, 30000)
        act = eu_mod.match_eu(law)
        if act:
            return self._eu_get(act, parsed, self._eu_lang(args.get("language")), max_chars)
        return self._de_get(law, parsed, max_chars)

    def _pinpoint(self, text: str, parsed: Dict[str, Any], result: Dict[str, Any], dotted: bool = False) -> str:
        para = parsed.get("paragraph")
        if para:
            parts = split_paragraphs(text, dotted)
            hit = next((t for n, t in parts if n == para), None)
            if hit is None:
                if not parts and para == "1":
                    result["paragraph_note"] = "This provision has no numbered paragraphs; the whole text is returned."
                    hit = text
                else:
                    raise LawError("paragraph_not_found", f"Paragraph ({para}) does not exist in this provision.",
                                   f"It has {len(parts)} numbered paragraphs. Read it without paragraph.",
                                   {"paragraphs": [n for n, _ in parts]})
            text = hit
            result["paragraph"] = para
        pins = {k: parsed[k] for k in ("subparagraph", "sentence", "item", "letter") if parsed.get(k)}
        if pins:
            result["pinpoint"] = pins
            result["pinpoint_note"] = ("The text returned is the whole paragraph; the sentence, number or letter "
                                       "asked for is inside it. Quote it from this text.")
        return text

    def _de_get(self, law: str, parsed: Dict[str, Any], max_chars: int) -> Dict[str, Any]:
        slug, title, abbr = self.de.resolve(law)
        cached = self.de.load(slug)
        data = cached.data
        meta = data["meta"]
        norm, how = gii.find_norm(data, parsed.get("kind"), parsed.get("number"), parsed.get("label"))
        abbr = meta.get("amtabk") or meta.get("jurabk") or abbr or slug
        if norm is None:
            num = parsed.get("number") or parsed.get("label")
            digits = re.sub(r"\D", "", str(num or ""))
            # Same base number with another letter (asked 312z, law has 312 to 312k); never neighbours.
            nearby = [n["id"] for n in data["norms"]
                      if digits and gii.norm_key(n["id"])[1].rstrip("abcdefghijklmnopqrstuvwxyz") == digits][:8]
            raise LawError("section_not_found", f"{abbr} has no provision '{num}'.",
                           "Do not guess a nearby number. Call de_law_toc to list the sections of this law.",
                           {"law": slug, "same_number_other_letter": nearby})
        result: Dict[str, Any] = {"ok": True, "jurisdiction": "DE"}
        text = self._pinpoint(norm["text"], parsed, result)
        cut = _cut(text, max_chars)
        label = gii.cite_label(norm["id"], "")
        if result.get("paragraph"):
            label += f" Abs. {result['paragraph']}"
        provision = {
            "citation": f"{label} {abbr}", "id": norm["id"], "title": norm.get("title", ""),
            "structure": norm.get("path", []), **cut,
        }
        if how == "range":
            provision["note"] = (f"'{parsed.get('number')}' is part of the grouped entry '{norm['id']}'"
                                 f"{' ' + norm.get('title') if norm.get('title') else ''}.")
        if gii.fold(norm.get("title", "")).strip("() ") == "weggefallen":
            provision["repealed"] = True
            provision["note"] = (provision.get("note", "") + " This provision is repealed (weggefallen).").strip()
        elif not norm["text"].strip():
            provision["note"] = provision.get("note") or "This entry has a heading but no text in the source."
        if cut["truncated"]:
            provision["next_step"] = f"Text cut at {max_chars} characters; call again with max_chars up to 30000."
        if norm.get("notes"):
            provision["footnotes"] = norm["notes"][:2000]
        result.update({
            "law": {"abbreviation": abbr, "title": meta.get("title") or title, "id": slug,
                    "enacted": meta.get("enacted", ""), "gazette": meta.get("gazette", []),
                    "url": gii.law_url(slug)},
            "provision": provision,
            "version": {"status": meta.get("status", []), "data_as_of": meta.get("data_built", ""),
                        "note": "The status line (Stand) belongs to the whole law, not only to this provision."},
            "source": self._source_de(gii.norm_url(slug, norm["id"]), meta.get("data_built", ""), cached),
        })
        stale = self._stale_note(cached)
        if stale:
            result["stale"] = True
            result["stale_note"] = stale
        return result

    def _eu_get(self, act: Dict[str, Any], parsed: Dict[str, Any], lang: str, max_chars: int) -> Dict[str, Any]:
        if not self._flag("eu_law"):
            raise LawError("disabled", "EU law lookups are switched off in this plugin's settings (eu_law).")
        celex = act["celex"]
        kind = parsed.get("kind") or "article"
        if kind == "section":
            kind = "article"
        number = parsed.get("number") or ""
        uid = eu_mod.unit_id(kind, number)
        if not uid:
            raise LawError("bad_argument", f"'{number}' is not a valid {kind} number.")
        cached, doc_id, consolidated, note = self._eu_doc(act, lang, original=kind == "recital")
        units = cached.data["units"]
        unit = units.get(uid)
        if unit is None and kind == "annex" and not number.isdigit():
            unit = units.get(uid.upper())
        if unit is None:
            have = sum(1 for k in units if k.startswith(uid.split("_")[0] + "_"))
            raise LawError("article_not_found", f"{act.get(lang) or celex} has no {kind} {number} in {doc_id}.",
                           f"The document has {have} {kind} units. Do not guess; call de_law_toc for the list.",
                           {"celex": celex})
        result: Dict[str, Any] = {"ok": True, "jurisdiction": "EU"}
        text = unit["text"]
        lines = text.split("\n")
        heading = []
        if kind == "article" and lines and re.match(r"^(Artikel|Article)\s+\d", lines[0]):
            heading = lines[:2] if len(lines) > 1 and not _PARA.match(lines[1]) else lines[:1]
        if heading:
            text = "\n".join(lines[len(heading):]).strip()
        text = self._pinpoint(text, parsed, result, dotted=kind == "article")
        cut = _cut(text, max_chars)
        facts = cached.data.get("facts", {})
        label = {"article": "Art.", "recital": "Erwägungsgrund" if lang == "de" else "Recital",
                 "annex": "Anhang" if lang == "de" else "Annex"}[kind]
        short = act.get(lang) or act.get("de") or celex
        cite = f"{label} {number}"
        if result.get("paragraph"):
            cite += f" Abs. {result['paragraph']}" if lang == "de" else f"({result['paragraph']})"
        provision = {"citation": f"{cite} {short}", "id": uid,
                     "title": heading[1] if len(heading) > 1 else "", **cut}
        if cut["truncated"]:
            provision["next_step"] = f"Text cut at {max_chars} characters; call again with max_chars up to 30000."
        version: Dict[str, Any] = {"document": doc_id, "consolidated_as_of": consolidated,
                                   "language": lang}
        for key in ("official_journal", "amended_by", "corrected_by", "legal_effect"):
            if facts.get(key):
                version[key] = facts[key]
        if note:
            version["note"] = note
        result.update({
            "law": {"abbreviation": short, "title": facts.get("title", ""), "celex": celex},
            "provision": provision, "version": version,
            "source": self._source_eu(doc_id, consolidated, lang, cached),
        })
        stale = self._stale_note(cached)
        if stale:
            result["stale"] = True
            result["stale_note"] = stale
        return result

    def _eu_doc(self, act: Dict[str, Any], lang: str, original: bool = False):
        """(cached document, document id, consolidated date, note). Recitals come from the original
        Official Journal text because consolidated texts omit them."""
        celex = act["celex"]
        note = None
        if original:
            doc_id, consolidated = celex, None
        else:
            doc_id, consolidated, note = self.eu.pick_version(celex)
        try:
            cached = self.eu.document(doc_id, lang)
        except LawError as err:
            if err.kind != "not_found" or doc_id == celex:
                if err.kind == "not_found":
                    raise self._not_covered(act, lang) from err
                raise
            note = f"The consolidated text {doc_id} is not available as structured text; original text used."
            doc_id, consolidated = celex, None
            try:
                cached = self.eu.document(doc_id, lang)
            except LawError as err2:
                if err2.kind == "not_found":
                    raise self._not_covered(act, lang) from err2
                raise
        if not cached.data.get("units"):
            raise self._not_covered(act, lang)
        if original:
            note = "Recitals are read from the original Official Journal text (consolidated texts omit them)."
        return cached, doc_id, consolidated, note

    @staticmethod
    def _not_covered(act: Dict[str, Any], lang: str) -> LawError:
        return LawError("not_covered",
                        f"CELEX {act['celex']} is not available as structured (ELI) text from the Publications Office. "
                        "Older acts and the EU treaties are not covered.",
                        f"Do not quote it from memory; give the user the EUR-Lex page "
                        f"{eu_mod.human_url(act['celex'], lang)}.")

    # ---------------------------------------------------------- de_law_search
    def law_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        query = str(args.get("query") or args.get("law") or "").strip()
        if not query:
            raise LawError("bad_argument", "No search words given.", "Pass a law name, abbreviation or title word.")
        limit = _int(args.get("limit"), 10, 1, 50)
        results: List[Dict[str, Any]] = []
        if self._flag("eu_law"):
            for act in eu_mod.search_known(query):
                results.append({"jurisdiction": "EU", "law": act["de"] if act["de"] != act["celex"] else act["celex"],
                                "abbreviation": f"{act['de']} / {act['en']}" if act["de"] != act["en"] else act["de"],
                                "celex": act["celex"], "match": "EU act"})
        de = self.de.search(query, limit)
        for row in de:
            results.append({"jurisdiction": "DE", **row})
        cached = self.de.toc()
        payload: Dict[str, Any] = {"ok": True, "query": query, "total_matches": len(results),
                                   "results": results[:limit],
                                   "source": {"name": "Gesetze im Internet (index) and the plugin's EU act list",
                                              "url": gii.TOC_URL, "retrieved_at": _iso_ts(cached.fetched_at),
                                              "cache": cached.state}}
        if not results:
            payload["message"] = "No federal law or known EU act matches."
            payload["next_step"] = ("Try a shorter title word or the official abbreviation. State (Land) law and EU "
                                    "treaties are not covered; an EU act can be named by its CELEX number.")
        else:
            payload["next_step"] = "Read a provision with de_law_get (law = the 'law' value, section = the number)."
        return payload

    # ------------------------------------------------------------- de_law_toc
    def law_toc(self, args: Dict[str, Any]) -> Dict[str, Any]:
        law = str(args.get("law") or "").strip()
        if not law:
            raise LawError("bad_argument", "No law given.", "Pass a law, e.g. 'BGB' or 'DSGVO'.")
        query = str(args.get("query") or "").strip()
        offset = _int(args.get("offset"), 0, 0, 100000)
        limit = _int(args.get("limit"), 50, 1, 200)
        act = eu_mod.match_eu(law)
        if act:
            entries, head, source = self._eu_toc(act, self._eu_lang(args.get("language")))
        else:
            entries, head, source = self._de_toc(law)
        if query:
            q = gii.fold(query)
            hits = []
            for e in entries:
                text = e.pop("_text", "")
                where = gii.fold(e.get("title", "")).find(q)
                if where >= 0:
                    e["match"] = "heading"
                    hits.append(e)
                    continue
                pos = gii.fold(text).find(q)
                if pos >= 0:
                    start = max(0, pos - 80)
                    e["match"] = "text"
                    e["snippet"] = ("…" if start else "") + " ".join(text[start:pos + len(query) + 120].split()) + "…"
                    hits.append(e)
            entries = hits
        else:
            for e in entries:
                e.pop("_text", None)
        page = entries[offset:offset + limit]
        payload = {"ok": True, **head, "query": query or None, "total": len(entries), "offset": offset,
                   "entries": page, "source": source}
        if offset + limit < len(entries):
            payload["next_step"] = f"More entries: call again with offset={offset + limit}."
        if query and not entries:
            payload["message"] = f"No heading or text in this law contains '{query}'."
        return payload

    def _de_toc(self, law: str):
        slug, title, abbr = self.de.resolve(law)
        cached = self.de.load(slug)
        meta = cached.data["meta"]
        entries = []
        for n in cached.data["norms"]:
            if n["id"] == "Inhaltsübersicht":
                continue
            entries.append({"id": n["id"], "title": n.get("title", ""),
                            "part": n["path"][-1] if n.get("path") else "", "_text": n.get("text", "")})
        head = {"jurisdiction": "DE", "law": {"abbreviation": meta.get("amtabk") or meta.get("jurabk") or abbr or slug, "id": slug,
                                             "title": meta.get("title") or title, "url": gii.law_url(slug)},
                "version": {"status": meta.get("status", []), "data_as_of": meta.get("data_built", "")}}
        return entries, head, self._source_de(gii.law_url(slug), meta.get("data_built", ""), cached)

    def _eu_toc(self, act: Dict[str, Any], lang: str):
        if not self._flag("eu_law"):
            raise LawError("disabled", "EU law lookups are switched off in this plugin's settings (eu_law).")
        cached, doc_id, consolidated, note = self._eu_doc(act, lang)
        entries = []
        for uid, unit in cached.data["units"].items():
            lines = unit["text"].split("\n")
            kind = uid.split("_")[0]
            title = lines[1] if len(lines) > 1 and not _PARA.match(lines[1]) else ""
            label = {"art": "Art.", "anx": "Anhang" if lang == "de" else "Annex",
                     "rct": "Erwägungsgrund" if lang == "de" else "Recital"}[kind]
            entries.append({"id": f"{label} {uid.split('_', 1)[1]}", "title": title if kind != "rct" else "",
                            "_text": unit["text"]})
        facts = cached.data.get("facts", {})
        head = {"jurisdiction": "EU", "law": {"abbreviation": act.get(lang) or act["celex"], "celex": act["celex"],
                                             "title": facts.get("title", "")},
                "version": {"document": doc_id, "consolidated_as_of": consolidated, "note": note}}
        return entries, head, self._source_eu(doc_id, consolidated, lang, cached)

    # --------------------------------------------------------- de_case_search
    def case_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if not self._flag("case_law"):
            raise LawError("disabled", "Case-law lookups are switched off in this plugin's settings (case_law).")
        fn = str(args.get("file_number") or "").strip()
        court = str(args.get("court") or "").strip()
        dfrom = str(args.get("date_from") or "").strip()
        dto = str(args.get("date_to") or "").strip()
        for d in (dfrom, dto):
            if d and not re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", d):
                raise LawError("bad_argument", f"'{d}' is not a date.", "Use YYYY-MM-DD, YYYY-MM or YYYY.")
        if not (fn or court or dfrom or dto):
            raise LawError("bad_argument", "Give at least a file number, a court or a date range.",
                           "Example: file_number='VI ZR 135/13' or court='BVerfG' with date_from='2026-10-01'.")
        if dto and len(dto) < 10:
            dto = dto + "-99"
        limit = _int(args.get("limit"), 10, 1, 50)
        rows = self.cases.search(fn or None, court or None, dfrom or None, dto or None)
        cached = self.cases.toc()
        items = [{"doc_id": r[0], "court": r[1], "date": r[2], "file_number": r[3]} for r in rows[:limit]]
        payload: Dict[str, Any] = {"ok": True, "total_matches": len(rows), "results": items,
                                   "covers": "Federal courts only: " + ", ".join(rii.COURTS) + ". Not every "
                                             "decision is published there; lower courts are not included.",
                                   "source": {"name": "Rechtsprechung im Internet (index)", "url": rii.TOC_URL,
                                              "retrieved_at": _iso_ts(cached.fetched_at), "cache": cached.state}}
        if not rows:
            payload["message"] = "No published federal decision matches."
        else:
            payload["next_step"] = "Read one with de_case_get(doc_id=...)."
        return payload

    # ------------------------------------------------------------ de_case_get
    def case_get(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if not self._flag("case_law"):
            raise LawError("disabled", "Case-law lookups are switched off in this plugin's settings (case_law).")
        doc_id = str(args.get("doc_id") or "").strip().upper()
        doc_id = re.sub(r"^JB-", "", doc_id)
        if not doc_id:
            fn = str(args.get("file_number") or "").strip()
            if not fn:
                raise LawError("bad_argument", "Pass doc_id or file_number.")
            rows = self.cases.search(fn, str(args.get("court") or "") or None)
            exact = [r for r in rows if rii.norm_file_number(r[3]) == rii.norm_file_number(fn)]
            if len(exact) == 1:
                doc_id = exact[0][0]
            elif not rows:
                raise LawError("case_not_found", f"No published federal decision with file number '{fn}'.",
                               "Check the file number; only federal courts are covered.")
            else:
                cands = exact or rows
                raise LawError("ambiguous_case", f"{len(cands)} decisions match '{fn}'.",
                               "Pick one doc_id from candidates (same file number can have several decisions).",
                               {"candidates": [{"doc_id": r[0], "court": r[1], "date": r[2], "file_number": r[3]}
                                               for r in cands[:10]]})
        cached = self.cases.decision(doc_id)
        doc = cached.data
        want = args.get("parts") or ["headnote", "operative_part"]
        if isinstance(want, str):
            want = [w.strip() for w in want.split(",")]
        if "all" in want:
            want = list(rii.PARTS)
        budget = _int(args.get("max_chars"), DEFAULT_MAX_CHARS, 500, 60000)
        parts: Dict[str, Any] = {}
        truncated = False
        for key in rii.PARTS:
            if key not in want or not doc.get(key):
                continue
            cut = _cut(doc[key], max(200, budget))
            parts[key] = cut["text"]
            budget -= len(cut["text"])
            truncated = truncated or cut["truncated"]
            if budget <= 200:
                truncated = truncated or any(doc.get(k) for k in rii.PARTS[rii.PARTS.index(key) + 1:] if k in want)
                break
        available = [k for k in rii.PARTS if doc.get(k)]
        result = {"ok": True, "decision": {k: doc.get(k, "") for k in
                                           ("doc_id", "ecli", "court", "chamber", "date", "file_number", "type",
                                            "norms", "lower_court", "title")},
                  "parts": parts, "available_parts": available, "truncated": truncated,
                  "source": self._source_case(doc, cached)}
        if not parts:
            result["message"] = "None of the requested parts exist in this decision."
        if truncated or set(available) - set(parts):
            result["next_step"] = ("More text: call again with parts=['grounds'] or ['reasons'] (see available_parts)"
                                   " and a larger max_chars.")
        return result


def _as_handler(fn: Callable[[Dict[str, Any]], Dict[str, Any]], name: str) -> Callable:
    def handler(args: Optional[dict] = None, **_kwargs) -> str:
        try:
            if not isinstance(args, dict):
                args = {}
            return _dump(fn(dict(args)))
        except LawError as err:
            return _error(err.kind, err.message, err.hint, err.details)
        except Exception as err:  # never let a tool call break the agent loop
            logger.exception("de-law tool %s failed", name)
            return _error("internal", f"Unexpected error in the de-law plugin: {type(err).__name__}: {err}",
                          "Retry once. If it repeats, tell the user the lookup failed and link the source site.")
    handler.__name__ = name
    return handler


def make_handlers(tools: Optional[Tools] = None) -> Dict[str, Callable]:
    t = tools or Tools()
    return {
        "de_law_get": _as_handler(t.law_get, "de_law_get"),
        "de_law_search": _as_handler(t.law_search, "de_law_search"),
        "de_law_toc": _as_handler(t.law_toc, "de_law_toc"),
        "de_case_search": _as_handler(t.case_search, "de_case_search"),
        "de_case_get": _as_handler(t.case_get, "de_case_get"),
    }
