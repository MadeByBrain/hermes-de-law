"""Parse German and EU citation forms: '§ 203 Abs. 1 Nr. 3 StGB', 'Art. 6(1)(f) GDPR',
'Erwägungsgrund 47 DSGVO', 'Anhang III KI-VO', 'StGB § 203', '203 StGB'."""

from __future__ import annotations

import re
from typing import Dict, Optional

_KIND_WORDS = [
    (r"§§?", "section"),
    (r"paragraphen|paragraph|paragraf|para\.", "section"),
    (r"sections?|sec\.", "section"),
    (r"artikel|articles?|art\.?", "article"),
    (r"erwägungsgründe|erwägungsgrund|erwgr\.?|erwg\.?|recitals?", "recital"),
    (r"anhang|annex|anlage", "annex"),
]
_KIND_RE = "|".join(f"(?:{w})" for w, _ in _KIND_WORDS)
_NUM = r"(?:\d+[a-z]{0,2}\b|[ivxlc]+\b)"
_PROV = re.compile(rf"(?<![\w§])(?P<kind>{_KIND_RE})\s*(?P<num>{_NUM})", re.I)
_BARE = re.compile(rf"^\s*(?P<num>\d+[a-z]{{0,2}})\b\s*(?P<rest>.*)$", re.I)

_PIN = [
    ("paragraph", re.compile(r"^\s*(?:abs\.?|absatz|para(?:graph)?\.?|paragraph)\s*(\d+[a-z]?)", re.I)),
    ("paragraph", re.compile(r"^\s*\((\d+[a-z]?)\)")),
    ("subparagraph", re.compile(r"^\s*(?:uabs\.?|unterabsatz|subparagraph|sub-paragraph)\s*(\d+)", re.I)),
    ("sentence", re.compile(r"^\s*(?:s\.|satz|sentence)\s*(\d+)", re.I)),
    ("item", re.compile(r"^\s*(?:nr\.?|nummer|no\.?|number|point)\s*(\d+[a-z]?)", re.I)),
    ("letter", re.compile(r"^\s*(?:lit\.?|litera|buchst\.?|buchstabe|letter)\s*([a-z]{1,2})\b", re.I)),
    ("letter", re.compile(r"^\s*\(([a-z]{1,2})\)", re.I)),
    ("item", re.compile(r"^\s*\((\d+[a-z]?)\)")),
]
_LEAD = re.compile(r"^[\s,;:]*(?:(?:des|der|dem|den|im|in|of|the|zum|zur|vom|from)\s+)*", re.I)
_TRAIL = re.compile(r"[\s,;:.]+$")


def _clean_num(num: str) -> str:
    return re.sub(r"\s+", "", num or "").lower()


def _read_pins(rest: str, out: Dict[str, str]) -> str:
    changed = True
    while changed:
        changed = False
        for key, rx in _PIN:
            m = rx.match(rest)
            if m:
                if key == "paragraph" and "paragraph" in out:  # second "(n)" after a paragraph is an item
                    key = "item" if rx.pattern.startswith(r"^\s*\((\d") else key
                out.setdefault(key, m.group(1).lower())
                rest = rest[m.end():]
                changed = True
                break
    return rest


def parse_citation(text: str) -> Dict[str, str]:
    """Return {'kind','number','paragraph','sentence','item','letter','law'} (keys only when found)."""
    raw = " ".join((text or "").replace("\u00a0", " ").split())
    out: Dict[str, str] = {}
    m = _PROV.search(raw)
    if m:
        word = m.group("kind").lower()
        for pattern, kind in _KIND_WORDS:
            if re.fullmatch(pattern, word, re.I):
                out["kind"] = kind
                break
        num = _clean_num(m.group("num"))
        out["number"] = num.upper() if out.get("kind") == "annex" and re.fullmatch(r"[ivxlc]+", num) else num
        before = raw[:m.start()]
        after = _read_pins(raw[m.end():], out)
        law = after if _LEAD.sub("", after).strip() else before
        if law is after and before.strip() and not after.strip():
            law = before
    else:
        b = _BARE.match(raw)
        if b:
            out["number"] = _clean_num(b.group("num"))
            law = _read_pins(b.group("rest"), out)
        else:
            law = raw
    law = _TRAIL.sub("", _LEAD.sub("", law)).strip()
    if law:
        out["law"] = law
    return out


def split_section(section: Optional[str]) -> Dict[str, str]:
    """A section argument on its own: '203', '§ 203', 'Art. 6', 'Anlage 1', 'recital 47'."""
    if section is None:
        return {}
    if isinstance(section, (int, float)):
        return {"number": str(int(section))}
    parsed = parse_citation(str(section))
    parsed.pop("law", None)
    if "number" not in parsed:
        word = str(section).strip().lower()
        if word:
            parsed["label"] = word
    return parsed


ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}


def roman_to_int(text: str) -> Optional[int]:
    text = (text or "").lower()
    if not text or any(ch not in ROMAN for ch in text):
        return None
    total = 0
    for i, ch in enumerate(text):
        val = ROMAN[ch]
        if i + 1 < len(text) and ROMAN[text[i + 1]] > val:
            total -= val
        else:
            total += val
    return total


def int_to_roman(num: int) -> str:
    pairs = [(100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = ""
    for val, sym in pairs:
        while num >= val:
            out += sym
            num -= val
    return out
