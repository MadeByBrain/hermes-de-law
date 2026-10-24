"""Offline tests for de-law. No network: every request goes to a fake transport.

Run:  python -m unittest discover -s tests -v      (from the plugin folder; Python 3.11+)
"""

from __future__ import annotations

import atexit
import importlib.util
import io
import json
import re
import shutil
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("de_law_plugin", ROOT / "__init__.py",
                                               submodule_search_locations=[str(ROOT)])
pkg = importlib.util.module_from_spec(_spec)
sys.modules["de_law_plugin"] = pkg
_spec.loader.exec_module(pkg)

from de_law_plugin import citations, client, eu, gii, rii, schemas, tools  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="de-law-test-"))
atexit.register(shutil.rmtree, TMP, True)

# ------------------------------------------------------------------ fixtures

GII_TOC = """<?xml version="1.0" encoding="UTF-8" ?><items>
<item><title>Strafgesetzbuch</title><link>http://www.gesetze-im-internet.de/stgb/xml.zip</link></item>
<item><title>Gesetz über den Ausgleich der Arbeitgeberaufwendungen für Entgeltfortzahlung</title><link>http://www.gesetze-im-internet.de/aufag/xml.zip</link></item>
<item><title>Grundgesetz für die Bundesrepublik Deutschland</title><link>http://www.gesetze-im-internet.de/gg/xml.zip</link></item>
<item><title>Gesetz zur Regelung eines allgemeinen Mindestlohns</title><link>http://www.gesetze-im-internet.de/milog/xml.zip</link></item>
<item><title>Verordnung zur Aufhebung der Zucker-Mindestlagerabgaben-Verordnung</title><link>http://www.gesetze-im-internet.de/zuckv/xml.zip</link></item>
</items>"""

LETTER_S = ('<html><head><meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1" /></head><body>'
            '<p><a href="./stgb/index.html"><abbr title="Strafgesetzbuch"> StGB </abbr></a><br />Strafgesetzbuch</p>'
            '</body></html>').encode("cp1252")
LETTER_A = ('<p><a href="./aufag/index.html"><abbr title="Gesetz über den Ausgleich der Arbeitgeberaufwendungen '
            'für Entgeltfortzahlung"> AAG </abbr></a></p>').encode("cp1252")
LETTER_G = '<p><a href="./gg/index.html"><abbr title="Grundgesetz für die Bundesrepublik Deutschland"> GG </abbr></a></p>'.encode("cp1252")

STGB_XML = """<?xml version="1.0" encoding="UTF-8" ?><dokumente builddate="20260928220002" doknr="BJNR001270871">
<norm builddate="20260928220002" doknr="BJNR001270871"><metadaten><jurabk>StGB</jurabk><amtabk>StGB</amtabk>
<ausfertigung-datum manuell="ja">1871-05-15</ausfertigung-datum><fundstelle typ="amtlich"><periodikum>RGBl</periodikum><zitstelle>1871, 127</zitstelle></fundstelle>
<langue>Strafgesetzbuch</langue><standangabe checked="ja"><standtyp>Neuf</standtyp><standkommentar>Neugefasst durch Bek. v. 13.11.1998 I 3322;</standkommentar></standangabe>
<standangabe checked="ja"><standtyp>Stand</standtyp><standkommentar>zuletzt geändert durch Art. 1 G v. 20.3.2026 I Nr. 95</standkommentar></standangabe></metadaten>
<textdaten><fussnoten><Content><P>(+++ Textnachweis Geltung ab: 1.4.1985 +++)</P></Content></fussnoten></textdaten></norm>
<norm builddate="20260928220003" doknr="X1"><metadaten><jurabk>StGB</jurabk><gliederungseinheit><gliederungskennzahl>020</gliederungskennzahl><gliederungsbez>Besonderer Teil</gliederungsbez></gliederungseinheit></metadaten><textdaten><text format="XML"><Content><P/></Content></text></textdaten></norm>
<norm builddate="20260928220003" doknr="X2"><metadaten><jurabk>StGB</jurabk><gliederungseinheit><gliederungskennzahl>020150</gliederungskennzahl><gliederungsbez>Fünfzehnter Abschnitt</gliederungsbez><gliederungstitel>Verletzung des persönlichen Lebens- und Geheimbereichs</gliederungstitel></gliederungseinheit></metadaten><textdaten><text format="XML"><Content><P/></Content></text></textdaten></norm>
<norm builddate="20260928220003" doknr="X3"><metadaten><jurabk>StGB</jurabk><enbez>§ 203</enbez><titel format="XML">Verletzung von Privatgeheimnissen</titel></metadaten>
<textdaten><text format="XML"><Content><P>(1) Wer unbefugt ein fremdes Geheimnis offenbart, das ihm als <DL Font="normal" Type="arabic"><DT>1.</DT><DD Font="normal"><LA Size="normal">Arzt,</LA></DD><DT>3.</DT><DD Font="normal"><LA Size="normal">Rechtsanwalt,</LA></DD></DL>anvertraut worden ist, wird bestraft.</P><P>(2) Ebenso wird bestraft, wer<BR/>unbefugt offenbart.</P></Content></text><fussnoten/></textdaten></norm>
<norm builddate="20260928220003" doknr="X4"><metadaten><jurabk>StGB</jurabk><enbez>(XXXX) §§ 207 bis 210</enbez><titel format="XML">(weggefallen)</titel></metadaten><textdaten><text format="XML"><Content><P/></Content></text></textdaten></norm>
<norm builddate="20260928220004" doknr="X5"><metadaten><jurabk>StGB</jurabk><enbez>§ 211</enbez><titel format="XML">Mord</titel></metadaten><textdaten><text format="XML"><Content><P>(1) Der Mörder wird mit lebenslanger Freiheitsstrafe bestraft.</P><table><tgroup cols="2"><tbody><row><entry>A</entry><entry>B</entry></row></tbody></tgroup></table></Content></text></textdaten></norm>
</dokumente>"""

GG_XML = """<?xml version="1.0" encoding="UTF-8" ?><dokumente builddate="20260506000000" doknr="BJNR000010949">
<norm doknr="BJNR000010949"><metadaten><jurabk>GG</jurabk><langue>Grundgesetz für die Bundesrepublik Deutschland</langue><standangabe><standtyp>Stand</standtyp><standkommentar>Zuletzt geändert durch Art. 1 G v. 22.3.2025 I Nr. 94</standkommentar></standangabe></metadaten></norm>
<norm builddate="20260506000000" doknr="G1"><metadaten><jurabk>GG</jurabk><enbez>Art 1</enbez></metadaten><textdaten><text format="XML"><Content><P>(1) Die Würde des Menschen ist unantastbar.</P><P>(2) Das Deutsche Volk bekennt sich darum zu unverletzlichen Menschenrechten.</P></Content></text></textdaten></norm>
</dokumente>"""


def _zip(name: str, payload: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, payload)
    return buf.getvalue()


EU_CONSOLIDATED = """<?xml version="1.0" encoding="UTF-8"?><html xmlns="http://www.w3.org/1999/xhtml"><body>
<p>02016R0679 DE 04.05.2016 000.003</p>
<p>Dieser Text dient lediglich zu Informationszwecken und hat keine Rechtswirkung.</p>
<table><tr><td>►B</td><td>VERORDNUNG (EU) 2016/679 DES EUROPÄISCHEN PARLAMENTS UND DES RATES vom 27. April 2016 (Datenschutz-Grundverordnung) (ABl. L 119 vom 4.5.2016, S. 1)</td></tr></table>
<p>Berichtigt durch:</p>
<table><tr><td>►C1</td><td>Berichtigung, ABl. L 314 vom 22.11.2016, S. 72 (2016/679)</td></tr></table>
<p>▼B</p>
<div class="eli-subdivision" id="art_6"><p class="title-article-norm">Artikel 6</p>
<div class="eli-title" id="art_6.tit_1"><p class="stitle-article-norm">Rechtmäßigkeit der Verarbeitung</p></div>
<div class="norm"><span class="no-parag">(1)  </span><div class="norm inline-element"><p class="norm inline-element">Die Verarbeitung ist nur rechtmäßig, wenn:</p>
<div class="grid-container grid-list"><div class="list grid-list-column-1"><span>a) </span></div><div class="grid-list-column-2"><p class="norm">Einwilligung ▼C1 gegeben ◄;</p></div></div>
<div class="grid-container grid-list"><div class="list grid-list-column-1"><span>f) </span></div><div class="grid-list-column-2"><p class="norm">berechtigte Interessen.</p></div></div></div></div>
<div class="norm"><span class="no-parag">(2)  </span><div class="norm inline-element"><p>Die Mitgliedstaaten können spezifischere Bestimmungen beibehalten.</p></div></div>
</div>
<div id="anx_I"><p class="title-annex-1">ANHANG I</p><p>Liste</p></div>
</body></html>"""

EU_ORIGINAL = """<?xml version="1.0" encoding="UTF-8"?><html xmlns="http://www.w3.org/1999/xhtml"><body>
<table><tr><td><p>4.5.2016</p></td><td><p>DE</p></td><td><p>Amtsblatt der Europäischen Union</p></td><td><p>L 119/1</p></td></tr></table>
<p>VERORDNUNG (EU) 2016/679 DES EUROPÄISCHEN PARLAMENTS UND DES RATES</p><p>vom 27. April 2016</p>
<div class="eli-subdivision" id="rct_47"><table><tr><td><p>(47)</p></td><td><p>Die Rechtmäßigkeit der Verarbeitung kann durch die berechtigten Interessen begründet sein.</p></td></tr></table></div>
<div class="eli-subdivision" id="art_6"><p>Artikel 6</p><p>Rechtmäßigkeit der Verarbeitung</p><p>(1) Original.</p></div>
</body></html>"""

SPARQL_JSON = json.dumps({"results": {"bindings": [{"celex": {"value": "02016R0679-20160504"}},
                                                   {"celex": {"value": "02016R0679-29990101"}}]}})

RII_TOC = """<?xml version='1.0' encoding='UTF-8'?><items>
<item><gericht>BGH 6. Zivilsenat</gericht><entsch-datum>20141028</entsch-datum><aktenzeichen>VI ZR 135/13</aktenzeichen><link>http://www.rechtsprechung-im-internet.de/jportal/docs/bsjrs/jb-KORE311772014.zip</link><modified>2025-06-23T21:55:54.378Z</modified></item>
<item><gericht>BGH 6. Zivilsenat</gericht><entsch-datum>20170516</entsch-datum><aktenzeichen>VI ZR 135/13</aktenzeichen><link>http://www.rechtsprechung-im-internet.de/jportal/docs/bsjrs/jb-KORE313332017.zip</link><modified>2025-06-23T21:55:54.378Z</modified></item>
<item><gericht>BVerfG 2. Senat</gericht><entsch-datum>20261014</entsch-datum><aktenzeichen>2 BvE 5/26</aktenzeichen><link>http://www.rechtsprechung-im-internet.de/jportal/docs/bsjrs/jb-KVRE467122601.zip</link><modified>2026-10-20T00:00:00.000Z</modified></item>
</items>"""

DECISION = """<?xml version="1.0" encoding="UTF-8"?><dokument><doknr>KVRE467122601</doknr><ecli>ECLI:DE:BVerfG:2026:es20261014.2bve000526</ecli>
<gertyp>BVerfG</gertyp><gerort/><spruchkoerper>2. Senat</spruchkoerper><entsch-datum>20261014</entsch-datum><aktenzeichen>2 BvE 5/26</aktenzeichen>
<doktyp>Einstweilige Anordnung</doktyp><norm>Art 21 Abs 1 S 1 GG</norm><vorinstanz/><titelzeile><p>Erfolgreicher Eilantrag</p></titelzeile><leitsatz/>
<tenor><div><dl class="RspDL"><dt/><dd><p>Der Antragsgegnerin wird aufgegeben, das Video zu entfernen.</p></dd></dl></div></tenor>
<gruende><div><dl class="RspDL"><dt><a name="rd_1">1</a></dt><dd><p>Die Antragstellerin sieht sich verletzt.</p></dd></dl>
<dl class="RspDL"><dt><a name="rd_2">2</a></dt><dd><p>""" + ("Begründung. " * 400) + """</p></dd></dl></div></gruende>
<identifier>http://www.rechtsprechung-im-internet.de/jportal/?quelle=jlink&amp;docid=jb-KVRE467122601&amp;psml=bsjrsprod.psml&amp;max=true</identifier>
<publisher>BMJV</publisher><accessRights>public</accessRights></dokument>"""


class FakeWeb:
    """Maps URL patterns to (status, body, headers). Records every request."""

    def __init__(self):
        self.calls = []
        self.down = False
        self.routes = []
        self.add(r"gesetze-im-internet\.de/gii-toc\.xml$", GII_TOC.encode(), {"etag": '"toc1"'})
        self.add(r"Teilliste_S\.html$", LETTER_S)
        self.add(r"Teilliste_A\.html$", LETTER_A)
        self.add(r"Teilliste_G\.html$", LETTER_G)
        self.add(r"/stgb/xml\.zip$", _zip("BJNR001270871.xml", STGB_XML), {"etag": '"stgb1"', "last-modified": "Mon, 28 Sep 2026 20:00:05 GMT"})
        self.add(r"/gg/xml\.zip$", _zip("BJNR000010949.xml", GG_XML))
        self.add(r"/webapi/rdf/sparql\?", b'{"results": {"bindings": []}}')
        self.add(r"/webapi/rdf/sparql\?.*2016R0679", SPARQL_JSON.encode(), {"content-type": "application/sparql-results+json"})
        self.add(r"/resource/celex/02016R0679-20160504$", EU_CONSOLIDATED.encode(), {"content-type": "application/xhtml+xml;charset=UTF-8"})
        self.add(r"/resource/celex/32016R0679$", EU_ORIGINAL.encode(), {"content-type": "application/xhtml+xml;charset=UTF-8"})
        self.add(r"rii-toc\.xml$", RII_TOC.encode())
        self.add(r"jb-KVRE467122601\.zip$", _zip("jb-KVRE467122601.xml", DECISION))

    def add(self, pattern, body, headers=None, status=200):
        self.routes.insert(0, (re.compile(pattern), status, body, headers or {}))

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        if self.down:
            raise OSError("network unreachable")
        for rx, status, body, hdrs in self.routes:
            if rx.search(url):
                if headers.get("If-None-Match") and headers.get("If-None-Match") == hdrs.get("etag"):
                    return client.Response(304, b"", {}, url)
                return client.Response(status, body, {k.lower(): v for k, v in hdrs.items()}, url)
        return client.Response(404, b"not found", {}, url)


def make(settings=None, root=None):
    web = FakeWeb()
    http = client.Http(transport=web)
    client.MIN_INTERVAL_S = 0.0
    store = client.Store(http=http, cache=client.Cache(root or Path(tempfile.mkdtemp(dir=TMP))),
                         settings=lambda k, d=None: (settings or {}).get(k, d))
    t = tools.Tools(store)
    return t, tools.make_handlers(t), web


def call(handlers, name, **args):
    return json.loads(handlers[name](args))


# ------------------------------------------------------------------ tests

class CitationTests(unittest.TestCase):
    def test_forms(self):
        p = citations.parse_citation
        self.assertEqual(p("§ 203 StGB"), {"kind": "section", "number": "203", "law": "StGB"})
        self.assertEqual(p("StGB § 203")["law"], "StGB")
        self.assertEqual(p("§203 Abs. 1 Nr. 3 StGB"),
                         {"kind": "section", "number": "203", "paragraph": "1", "item": "3", "law": "StGB"})
        self.assertEqual(p("Art. 6 Abs. 1 lit. f DSGVO")["letter"], "f")
        g = p("Art. 6(1)(f) GDPR")
        self.assertEqual((g["number"], g["paragraph"], g["letter"], g["law"]), ("6", "1", "f", "GDPR"))
        self.assertEqual(p("Erwägungsgrund 47 DSGVO")["kind"], "recital")
        self.assertEqual(p("Annex III AI Act"), {"kind": "annex", "number": "III", "law": "AI Act"})
        self.assertEqual(p("§ 5 AO"), {"kind": "section", "number": "5", "law": "AO"})
        self.assertEqual(p("§ 312g BGB")["number"], "312g")
        self.assertEqual(p("203 StGB"), {"number": "203", "law": "StGB"})
        self.assertEqual(p("article 5(1)(a) of the GDPR")["law"], "GDPR")
        self.assertEqual(p("§ 1 des Bürgerlichen Gesetzbuchs")["law"], "Bürgerlichen Gesetzbuchs")

    def test_roman(self):
        self.assertEqual(citations.roman_to_int("XIV"), 14)
        self.assertEqual(citations.int_to_roman(14), "XIV")
        self.assertIsNone(citations.roman_to_int("ABC"))


class EuMatchTests(unittest.TestCase):
    def test_aliases_and_numbers(self):
        self.assertEqual(eu.match_eu("DSGVO")["celex"], "32016R0679")
        self.assertEqual(eu.match_eu("GDPR")["celex"], "32016R0679")
        self.assertEqual(eu.match_eu("AI Act")["celex"], "32024R1689")
        self.assertEqual(eu.match_eu("KI-VO")["celex"], "32024R1689")
        self.assertEqual(eu.match_eu("Verordnung (EU) 2016/679")["celex"], "32016R0679")
        self.assertEqual(eu.match_eu("Verordnung (EU) Nr. 910/2014")["celex"], "32014R0910")
        self.assertEqual(eu.match_eu("Regulation (EC) No 593/2008")["celex"], "32008R0593")
        self.assertEqual(eu.match_eu("Richtlinie 95/46/EG")["celex"], "31995L0046")
        self.assertEqual(eu.match_eu("Directive (EU) 2022/2555")["celex"], "32022L2555")
        self.assertEqual(eu.match_eu("32023R2854")["celex"], "32023R2854")
        self.assertIsNone(eu.match_eu("StGB"))
        self.assertIsNone(eu.match_eu("BGB"))


class TextTests(unittest.TestCase):
    def test_law_xml(self):
        law = gii.parse_law_xml(STGB_XML.encode())
        self.assertEqual(law["meta"]["jurabk"], "StGB")
        self.assertEqual(law["meta"]["data_built"], "2026-09-28")
        self.assertEqual(law["meta"]["gazette"], ["RGBl 1871, 127"])
        n203 = next(n for n in law["norms"] if n["id"] == "§ 203")
        self.assertIn("1. Arzt,", n203["text"])
        self.assertIn("(2) Ebenso wird bestraft, wer\nunbefugt offenbart.", n203["text"])
        self.assertEqual(n203["path"], ["Besonderer Teil",
                                        "Fünfzehnter Abschnitt Verletzung des persönlichen Lebens- und Geheimbereichs"])
        n211 = next(n for n in law["norms"] if n["id"] == "§ 211")
        self.assertIn("A | B", n211["text"])

    def test_find_norm(self):
        law = gii.parse_law_xml(STGB_XML.encode())
        self.assertEqual(gii.find_norm(law, "section", "203")[1], "exact")
        n, how = gii.find_norm(law, "section", "208")
        self.assertEqual((n["id"], how), ("(XXXX) §§ 207 bis 210", "range"))
        self.assertEqual(gii.find_norm(law, "section", "999"), (None, ""))

    def test_urls(self):
        self.assertEqual(gii.norm_url("stgb", "§ 203"), "https://www.gesetze-im-internet.de/stgb/__203.html")
        self.assertEqual(gii.norm_url("gg", "Art 1"), "https://www.gesetze-im-internet.de/gg/art_1.html")
        self.assertEqual(gii.norm_url("brao", "Anlage 1"), "https://www.gesetze-im-internet.de/brao/index.html")


class GermanLawTests(unittest.TestCase):
    def test_get_section_with_source(self):
        _, h, web = make()
        r = call(h, "de_law_get", citation="§ 203 StGB")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["provision"]["citation"], "§ 203 StGB")
        self.assertEqual(r["law"]["title"], "Strafgesetzbuch")
        self.assertEqual(r["version"]["status"][1]["text"], "zuletzt geändert durch Art. 1 G v. 20.3.2026 I Nr. 95")
        self.assertEqual(r["source"]["url"], "https://www.gesetze-im-internet.de/stgb/__203.html")
        self.assertIn("Verbindlich ist allein die im Bundesgesetzblatt", r["source"]["attribution"])
        self.assertEqual(r["source"]["cache"], "fresh")
        # The section number never leaves the machine: only the whole law is requested.
        self.assertFalse(any("203" in url for url, _ in web.calls))

    def test_paragraph_and_pinpoint(self):
        _, h, _ = make()
        r = call(h, "de_law_get", citation="§ 203 Abs. 2 StGB")
        self.assertEqual(r["provision"]["text"], "(2) Ebenso wird bestraft, wer\nunbefugt offenbart.")
        self.assertEqual(r["provision"]["citation"], "§ 203 Abs. 2 StGB")
        r = call(h, "de_law_get", citation="§ 203 Abs. 1 Nr. 3 StGB")
        self.assertEqual(r["pinpoint"], {"item": "3"})
        r = call(h, "de_law_get", law="StGB", section="203", paragraph="9")
        self.assertEqual(r["error_type"], "paragraph_not_found")
        self.assertEqual(r["paragraphs"], ["1", "2"])

    def test_abbreviation_differs_from_folder(self):
        _, h, web = make()
        web.add(r"/aufag/xml\.zip$", _zip("a.xml", STGB_XML.replace("StGB", "AAG")))
        r = call(h, "de_law_get", citation="§ 203 AAG")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["law"]["id"], "aufag")

    def test_article_law_and_title_lookup(self):
        _, h, _ = make()
        r = call(h, "de_law_get", citation="Art. 1 Abs. 1 GG")
        self.assertEqual(r["provision"]["text"], "(1) Die Würde des Menschen ist unantastbar.")
        self.assertEqual(r["source"]["url"], "https://www.gesetze-im-internet.de/gg/art_1.html")
        r = call(h, "de_law_get", law="Grundgesetz", section="1")
        self.assertTrue(r["ok"], r)

    def test_repealed_range_and_missing(self):
        _, h, _ = make()
        r = call(h, "de_law_get", citation="§ 208 StGB")
        self.assertTrue(r["provision"]["repealed"])
        self.assertIn("weggefallen", r["provision"]["note"])
        r = call(h, "de_law_get", citation="§ 9999 StGB")
        self.assertEqual(r["error_type"], "section_not_found")
        self.assertIn("Do not guess", r["next_step"])
        r = call(h, "de_law_get", citation="§ 1 Unbekanntes Gesetz XYZ")
        self.assertEqual(r["error_type"], "law_not_found")

    def test_truncation(self):
        _, h, _ = make()
        r = call(h, "de_law_get", citation="§ 203 StGB", max_chars=500)
        self.assertFalse(r["provision"]["truncated"])  # short text fits
        long = STGB_XML.replace("Der Mörder wird", "Der Mörder wird " + "sehr " * 400)
        t, h2, web = make()
        web.add(r"/stgb/xml\.zip$", _zip("x.xml", long))
        r = call(h2, "de_law_get", citation="§ 211 StGB", max_chars=500)
        self.assertTrue(r["provision"]["truncated"])
        self.assertLessEqual(len(r["provision"]["text"]), 500)

    def test_cache_states(self):
        root = Path(tempfile.mkdtemp(dir=TMP))
        _, h, web = make(root=root)
        self.assertEqual(call(h, "de_law_get", citation="§ 203 StGB")["source"]["cache"], "fresh")
        n = len(web.calls)
        self.assertEqual(call(h, "de_law_get", citation="§ 211 StGB")["source"]["cache"], "cached")
        self.assertEqual(len(web.calls), n)  # no request at all
        _, h2, web2 = make(settings={"max_age_hours": 0}, root=root)
        self.assertEqual(call(h2, "de_law_get", citation="§ 203 StGB")["source"]["cache"], "revalidated")
        self.assertTrue(any(hd.get("If-None-Match") == '"stgb1"' for _, hd in web2.calls))
        web2.down = True
        r = call(h2, "de_law_get", citation="§ 203 StGB")
        self.assertTrue(r["stale"])
        self.assertEqual(r["source"]["cache"], "stale")

    def test_offline_without_cache(self):
        _, h, web = make()
        web.down = True
        r = call(h, "de_law_get", citation="§ 203 StGB")
        self.assertEqual(r["error_type"], "network")

    def test_search_and_toc(self):
        _, h, _ = make()
        r = call(h, "de_law_search", query="StGB")
        self.assertEqual(r["results"][0]["law"], "stgb")
        r = call(h, "de_law_search", query="Mindestlohn")
        self.assertEqual(r["results"][0]["law"], "milog")
        r = call(h, "de_law_search", query="DSGVO")
        self.assertEqual(r["results"][0]["jurisdiction"], "EU")
        r = call(h, "de_law_toc", law="StGB")
        self.assertEqual([e["id"] for e in r["entries"]], ["§ 203", "(XXXX) §§ 207 bis 210", "§ 211"])
        r = call(h, "de_law_toc", law="StGB", query="lebenslanger")
        self.assertEqual(r["entries"][0]["id"], "§ 211")
        self.assertIn("lebenslanger", r["entries"][0]["snippet"])

    def test_language_setting(self):
        _, h, _ = make(settings={"language": "en"})
        r = call(h, "de_law_get", citation="§ 203 StGB")
        self.assertTrue(r["source"]["attribution"].startswith("Source: Gesetze im Internet"))


class EuLawTests(unittest.TestCase):
    def test_article_consolidated(self):
        _, h, web = make()
        r = call(h, "de_law_get", citation="Art. 6 Abs. 1 lit. f DSGVO")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["version"]["document"], "02016R0679-20160504")  # the 2999 version is in the future
        self.assertEqual(r["version"]["consolidated_as_of"], "2016-05-04")
        self.assertEqual(r["version"]["official_journal"], "ABl. L 119 vom 4.5.2016, S. 1")
        self.assertEqual(r["version"]["corrected_by"], ["C1: Berichtigung, ABl. L 314 vom 22.11.2016, S. 72 (2016/679)"])
        self.assertIn("keine Rechtswirkung", r["version"]["legal_effect"])
        text = r["provision"]["text"]
        self.assertTrue(text.startswith("(1) Die Verarbeitung"), text)
        self.assertIn("a) Einwilligung gegeben;", text)  # markers removed
        self.assertNotIn("►", text + "▼◄")
        self.assertNotIn("(2)", text)
        self.assertEqual(r["provision"]["title"], "Rechtmäßigkeit der Verarbeitung")
        self.assertIn("CC BY 4.0", r["source"]["attribution"])
        self.assertTrue(all("eur-lex.europa.eu" not in url for url, _ in web.calls))

    def test_recital_from_original_and_annex(self):
        _, h, _ = make()
        r = call(h, "de_law_get", citation="Erwägungsgrund 47 DSGVO")
        self.assertEqual(r["version"]["document"], "32016R0679")
        self.assertTrue(r["provision"]["text"].startswith("(47) Die Rechtmäßigkeit"))
        r = call(h, "de_law_get", citation="Anhang 1 DSGVO")
        self.assertEqual(r["provision"]["id"], "anx_I")

    def test_not_covered_and_missing(self):
        _, h, web = make()
        r = call(h, "de_law_get", citation="Art. 5 Richtlinie 2002/58/EG")
        self.assertEqual(r["error_type"], "not_covered")
        self.assertIn("eur-lex.europa.eu", r["next_step"])
        r = call(h, "de_law_get", citation="Art. 120 DSGVO")
        self.assertEqual(r["error_type"], "article_not_found")

    def test_sparql_outage_falls_back_to_original(self):
        _, h, web = make()
        web.add(r"/webapi/rdf/sparql\?", b"bad gateway", status=502)
        r = call(h, "de_law_get", citation="Art. 6 DSGVO")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["version"]["document"], "32016R0679")
        self.assertIn("original text used", r["version"]["note"])

    def test_eu_switch(self):
        _, h, _ = make(settings={"eu_law": False})
        self.assertEqual(call(h, "de_law_get", citation="Art. 6 DSGVO")["error_type"], "disabled")

    def test_toc(self):
        _, h, _ = make()
        r = call(h, "de_law_toc", law="GDPR")
        self.assertEqual([e["id"] for e in r["entries"]], ["Art. 6", "Anhang I"])


class CaseLawTests(unittest.TestCase):
    def test_search(self):
        _, h, _ = make()
        r = call(h, "de_case_search", file_number="vi zr 135/13")
        self.assertEqual([x["doc_id"] for x in r["results"]], ["KORE313332017", "KORE311772014"])
        r = call(h, "de_case_search", court="BVerfG", date_from="2026-10")
        self.assertEqual(r["results"][0]["file_number"], "2 BvE 5/26")
        self.assertEqual(call(h, "de_case_search")["error_type"], "bad_argument")
        self.assertEqual(call(h, "de_case_search", date_from="gestern")["error_type"], "bad_argument")

    def test_get(self):
        _, h, _ = make()
        r = call(h, "de_case_get", file_number="VI ZR 135/13")
        self.assertEqual(r["error_type"], "ambiguous_case")
        self.assertEqual(len(r["candidates"]), 2)
        r = call(h, "de_case_get", file_number="2 BvE 5/26")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["decision"]["ecli"], "ECLI:DE:BVerfG:2026:es20261014.2bve000526")
        self.assertEqual(list(r["parts"]), ["operative_part"])
        self.assertIn("grounds", r["available_parts"])
        self.assertTrue(r["source"]["url"].startswith("https://www.rechtsprechung-im-internet.de/jportal/"))
        r = call(h, "de_case_get", doc_id="KVRE467122601", parts=["grounds"], max_chars=800)
        self.assertTrue(r["parts"]["grounds"].startswith("1 Die Antragstellerin"))
        self.assertTrue(r["truncated"])
        self.assertLessEqual(len(r["parts"]["grounds"]), 800)
        self.assertEqual(call(h, "de_case_get", doc_id="../etc")["error_type"], "bad_argument")

    def test_switch(self):
        _, h, _ = make(settings={"case_law": False})
        self.assertEqual(call(h, "de_case_search", court="BGH")["error_type"], "disabled")


class SafetyTests(unittest.TestCase):
    def test_hosts(self):
        http = client.Http(transport=lambda url, hd: client.Response(200, b"x", {}, url))
        with self.assertRaises(client.LawError):
            http.get("https://example.com/x")
        with self.assertRaises(client.LawError):
            http.get("ftp://www.gesetze-im-internet.de/x")
        self.assertTrue(http.get("http://www.gesetze-im-internet.de/x").url.startswith("https://"))

    def test_redirect_to_foreign_host_refused(self):
        def transport(url, hd):
            return client.Response(302, b"", {"location": "https://evil.example/x"}, url)
        with self.assertRaises(client.LawError) as ctx:
            client.Http(transport=transport).get("https://publications.europa.eu/resource/celex/1")
        self.assertEqual(ctx.exception.kind, "network")

    def test_redirect_http_is_upgraded(self):
        seen = []

        def transport(url, hd):
            seen.append(url)
            if len(seen) == 1:
                return client.Response(303, b"", {"location": "http://publications.europa.eu/resource/cellar/abc"}, url)
            return client.Response(200, b"ok", {}, url)
        client.Http(transport=transport).get("https://publications.europa.eu/resource/celex/1")
        self.assertEqual(seen[1], "https://publications.europa.eu/resource/cellar/abc")

    def test_size_cap(self):
        http = client.Http(transport=lambda url, hd: client.Response(200, b"x" * 2000, {}, url))
        with self.assertRaises(client.LawError) as ctx:
            http.get("https://www.gesetze-im-internet.de/x", max_bytes=1000)
        self.assertEqual(ctx.exception.kind, "too_large")

    def test_handlers_never_raise(self):
        t, h, _ = make()
        for name in h:
            out = json.loads(h[name](None))
            self.assertIn("ok", out)
            out = json.loads(h[name]({"citation": 5, "law": ["x"], "max_chars": "lots"}))
            self.assertIn("ok", out)
        t.law_get = lambda args: 1 / 0
        boom = tools.make_handlers(t)["de_law_get"]({})
        self.assertEqual(json.loads(boom)["error_type"], "internal")

    def test_prune(self):
        cache = client.Cache(Path(tempfile.mkdtemp(dir=TMP)))
        for i in range(5):
            cache.write(f"k{i}", "x" * 10000, {"used_at": i})
        removed = cache.prune(25000, keep=("k0",))
        self.assertGreaterEqual(removed, 2)
        self.assertIsNotNone(cache.read("k0")[0])
        self.assertIsNotNone(cache.read("k4")[0])
        self.assertLessEqual(cache.size_bytes(), 25000)

    def test_cache_keys_are_safe(self):
        cache = client.Cache(Path(tempfile.mkdtemp(dir=TMP)))
        cache.write("../../evil key", {"a": 1}, {})
        self.assertEqual(len(list(cache.root.iterdir())), 2)
        self.assertTrue(all(p.parent == cache.root for p in cache.root.iterdir()))


class ManifestTests(unittest.TestCase):
    def test_registration_matches_manifest(self):
        manifest = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
        declared = re.findall(r"^\s+- (de_\w+)$", manifest, re.M)

        class Ctx:
            def __init__(self):
                self.tools, self.skills = [], []

            def register_tool(self, name, toolset, schema, handler, **kw):
                self.tools.append((name, toolset, schema, handler))

            def register_skill(self, name, path, description=""):
                self.skills.append((name, Path(path).exists(), description))

            def get_config(self, key, default=None):
                return default

        ctx = Ctx()
        pkg.register(ctx)
        self.assertEqual(sorted(t[0] for t in ctx.tools), sorted(declared))
        self.assertEqual({t[1] for t in ctx.tools}, {"de_law"})
        self.assertEqual(ctx.skills[0][:2], ("read-law", True))
        self.assertIn("version: " + __import__("de_law_plugin.version", fromlist=["x"]).__version__, manifest)

    def test_listing_sentences(self):
        """Tool Search shows the first sentence (about 60 chars): it must name the domain."""
        for schema in schemas.ALL_SCHEMAS:
            first = re.split(r"(?<=[.!?])\s", schema["description"], maxsplit=1)[0]
            self.assertLessEqual(len(first), 60, first)
            self.assertRegex(first, r"^(German and EU law|German federal courts): ")

    def test_no_dashes_in_texts(self):
        bad = []
        for path in ROOT.rglob("*"):
            if path.is_file() and path.suffix in (".py", ".md", ".yaml", ".json") and ".git" not in path.parts:
                text = path.read_text(encoding="utf-8")
                for i, line in enumerate(text.splitlines(), 1):
                    if "\u2014" in line or "\u2013" in line:
                        bad.append(f"{path.name}:{i}")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
