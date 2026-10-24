"""Decisions of the German federal courts from rechtsprechung-im-internet.de."""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

from .client import LawError, Response, Store
from .gii import fold
from .textutil import xml_to_text

BASE = "https://www.rechtsprechung-im-internet.de"
TOC_URL = f"{BASE}/rii-toc.xml"
COURTS = ["BVerfG", "BGH", "BVerwG", "BFH", "BAG", "BSG", "BPatG", "GmS-OGB"]
_DOC = re.compile(r"/jb-([A-Z0-9]+)\.zip$")


def _parse_toc(body: bytes, _resp: Response) -> List[List[str]]:
    items: List[List[str]] = []
    try:
        for _event, el in ET.iterparse(io.BytesIO(body), events=("end",)):
            if el.tag != "item":
                continue
            link = el.findtext("link") or ""
            m = _DOC.search(link)
            if m:
                d = (el.findtext("entsch-datum") or "").strip()
                date = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if re.fullmatch(r"\d{8}", d) else d
                items.append([m.group(1), " ".join((el.findtext("gericht") or "").split()), date,
                              " ".join((el.findtext("aktenzeichen") or "").split()),
                              (el.findtext("modified") or "").strip()[:10]])
            el.clear()
    except ET.ParseError as err:
        raise LawError("bad_response", f"rii-toc.xml could not be read: {err}") from err
    if not items:
        raise LawError("bad_response", "rii-toc.xml contained no decisions.")
    return items


def norm_file_number(text: str) -> str:
    return re.sub(r"\s+", "", fold(text or ""))


_FIELDS = [
    ("headnote", "leitsatz"), ("other_headnote", "sonstosatz"), ("operative_part", "tenor"),
    ("facts", "tatbestand"), ("reasons", "entscheidungsgruende"), ("grounds", "gruende"),
    ("dissent", "abwmeinung"), ("other", "sonstlt"),
]
PARTS = [k for k, _ in _FIELDS]


def _parse_decision_zip(body: bytes, resp: Response) -> Dict[str, Any]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile as err:
        raise LawError("bad_response", f"{resp.url} is not a valid ZIP file.") from err
    members = [i for i in zf.infolist() if i.filename.lower().endswith(".xml")]
    if not members or members[0].file_size > 20 * 1024 * 1024:
        raise LawError("bad_response", f"{resp.url} holds no readable XML file.")
    with zf.open(members[0]) as fh:
        xml = fh.read(20 * 1024 * 1024 + 1)
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as err:
        raise LawError("bad_response", f"The decision's XML could not be read: {err}") from err

    def t(tag: str) -> str:
        return " ".join((root.findtext(tag) or "").split())

    d = t("entsch-datum")
    out: Dict[str, Any] = {
        "doc_id": t("doknr"), "ecli": t("ecli"), "court": " ".join(x for x in [t("gertyp"), t("gerort")] if x),
        "chamber": t("spruchkoerper"), "date": f"{d[:4]}-{d[4:6]}-{d[6:8]}" if re.fullmatch(r"\d{8}", d) else d,
        "file_number": t("aktenzeichen"), "type": t("doktyp"),
        "norms": xml_to_text(root.find("norm")).replace("\n", "; "),
        "lower_court": xml_to_text(root.find("vorinstanz")),
        "title": xml_to_text(root.find("titelzeile")),
        "url": t("identifier").replace("http://", "https://", 1),
        "publisher": t("publisher"), "access_rights": t("accessRights"),
    }
    for key, tag in _FIELDS:
        text = xml_to_text(root.find(tag))
        if text:
            out[key] = text
    return out


class CaseLaw:
    def __init__(self, store: Store):
        self.store = store

    def toc(self):
        return self.store.fetch("rii-toc", TOC_URL, _parse_toc, max_bytes=80 * 1024 * 1024)

    def search(self, file_number: Optional[str] = None, court: Optional[str] = None,
               date_from: Optional[str] = None, date_to: Optional[str] = None) -> List[List[str]]:
        items = self.toc().data
        fn = norm_file_number(file_number) if file_number else ""
        c = fold(court or "").strip()
        out = []
        for doc_id, gericht, date, az, _mod in items:
            if fn and fn not in norm_file_number(az):
                continue
            if c and not fold(gericht).startswith(c):
                continue
            if date_from and date < date_from:
                continue
            if date_to and date > date_to:
                continue
            out.append([doc_id, gericht, date, az])
        if fn:
            exact = [r for r in out if norm_file_number(r[3]) == fn]
            rest = sorted([r for r in out if norm_file_number(r[3]) != fn], key=lambda r: r[2], reverse=True)
            return sorted(exact, key=lambda r: r[2], reverse=True) + rest
        return sorted(out, key=lambda r: r[2], reverse=True)

    def decision(self, doc_id: str):
        if not re.fullmatch(r"[A-Z0-9]{6,30}", doc_id or ""):
            raise LawError("bad_argument", f"'{doc_id}' is not a document id.",
                           "Use the doc_id from de_case_search, e.g. JURE100055033 or KORE312312016.")
        return self.store.fetch(f"rii-doc-{doc_id}", f"{BASE}/jportal/docs/bsjrs/jb-{doc_id}.zip",
                                _parse_decision_zip, max_age_s=30 * 24 * 3600)


def decision_url(doc_id: str) -> str:
    return f"{BASE}/jportal/?quelle=jlink&docid=jb-{doc_id}&psml=bsjrsprod.psml&max=true"
