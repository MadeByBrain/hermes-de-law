"""Tool schemas: what the model reads to decide which tool to call and how.

The first sentence of each description is what Hermes shows in the Tool Search
listing (about 60 characters), so it names the domain and the action."""

_LAW = {
    "type": "string",
    "description": (
        "The law, written any way a person would: official abbreviation (StGB, BGB, BRAO, GG, BDSG, AO, HGB), "
        "title (Strafgesetzbuch, Bürgerliches Gesetzbuch), folder name from de_law_search (bdsg_2018), or an EU act "
        "(DSGVO/GDPR, KI-VO/AI Act, DSA, DMA, NIS2, DORA, Data Act, a CELEX number like 32016R0679, or "
        "'Verordnung (EU) 2016/679')."
    ),
}

GET = {
    "name": "de_law_get",
    "description": (
        "German and EU law: read one section or article verbatim. "
        "Read-only. Returns the text of one provision of a German federal statute (Bundesgesetz, Verordnung) "
        "from Gesetze im Internet, or of an EU regulation or directive (GDPR/DSGVO, AI Act) from the Publications "
        "Office of the EU, with the law's Stand (version status), gazette reference, source URL and an "
        "attribution line. Pass citation exactly as the user wrote it, e.g. '§ 203 StGB', '§ 43e Abs. 3 BRAO', "
        "'Art. 6 Abs. 1 lit. f DSGVO', 'Art. 50 AI Act', 'Erwägungsgrund 47 DSGVO', 'Anhang III KI-VO'. "
        "If you did not call this tool, say so and do not write a provision from memory. "
        "Show source.attribution with any text you quote. It returns statute text, not legal advice."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "citation": {
                "type": "string",
                "description": "Full citation in German or English form: '§ 823 BGB', 'Art. 1 GG', 'Art. 6(1)(f) GDPR'.",
            },
            "law": _LAW,
            "section": {
                "type": "string",
                "description": "Section or article number when law is passed separately: '203', '§ 312g', 'Art. 6', "
                               "'Anlage 1', 'recital 47', 'Annex III'.",
            },
            "paragraph": {
                "type": "string",
                "description": "Optional Absatz/paragraph number to return only that paragraph, e.g. '1' or '2a'.",
            },
            "language": {
                "type": "string",
                "enum": ["de", "en"],
                "description": "EU acts only: text language (default from the plugin setting eu_language, usually de). "
                               "German federal law exists in German only.",
            },
            "max_chars": {
                "type": "integer", "minimum": 500, "maximum": 30000, "default": 6000,
                "description": "Cut the text after this many characters (default 6000). Cut results say truncated=true.",
            },
        },
        "required": [],
    },
}

SEARCH = {
    "name": "de_law_search",
    "description": (
        "German and EU law: find a statute by name or abbreviation. "
        "Read-only. Searches the index of all German federal laws and ordinances (Gesetze im Internet, about "
        "6,100 entries) by abbreviation or title words, plus well-known EU acts (GDPR, AI Act, DSA, NIS2, DORA). "
        "Use it when the user names a topic or an unknown abbreviation; when they already gave a citation like "
        "'§ 203 StGB', call de_law_get directly. Search words never leave the computer (the index is cached)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Abbreviation or title words: 'BDSG', 'Kündigungsschutz', 'Mindestlohn', 'AI Act'."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
        },
        "required": ["query"],
    },
}

TOC = {
    "name": "de_law_toc",
    "description": (
        "German and EU law: list a statute's sections or search it. "
        "Read-only. Returns the table of contents (§ or Art. numbers with headings and the part they belong to) "
        "of one German federal law or EU act, optionally filtered by a word found in a heading or in the text, "
        "with a short snippet. Use it to find which section covers a topic inside a known law, then read it with "
        "de_law_get. The search runs locally on the cached law."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "law": _LAW,
            "query": {"type": "string", "description": "Optional word or phrase to find in headings or text, e.g. 'Widerruf'."},
            "language": {"type": "string", "enum": ["de", "en"], "description": "EU acts only: language of headings."},
            "offset": {"type": "integer", "minimum": 0, "default": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
        },
        "required": ["law"],
    },
}

CASE_SEARCH = {
    "name": "de_case_search",
    "description": (
        "German federal courts: find decisions by file number. "
        "Read-only. Searches the index of Rechtsprechung im Internet (decisions of BVerfG, BGH, BVerwG, BFH, BAG, "
        "BSG, BPatG published by the federal government) by Aktenzeichen (file number), court and date range. "
        "Returns doc_id, court, date and file number; read one with de_case_get. Lower courts are not covered."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "file_number": {"type": "string", "description": "Aktenzeichen or part of it, e.g. 'VI ZR 135/13', '1 BvR 16/13'."},
            "court": {"type": "string", "description": "Court prefix: BVerfG, BGH, BVerwG, BFH, BAG, BSG, BPatG, or 'BGH 6. Zivilsenat'."},
            "date_from": {"type": "string", "description": "Earliest decision date, YYYY-MM-DD (or YYYY-MM, YYYY)."},
            "date_to": {"type": "string", "description": "Latest decision date, YYYY-MM-DD (or YYYY-MM, YYYY)."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
        },
        "required": [],
    },
}

CASE_GET = {
    "name": "de_case_get",
    "description": (
        "German federal courts: read one decision (Leitsatz, Tenor). "
        "Read-only. Returns court, date, file number, ECLI, cited norms, and the requested parts of one published "
        "decision: headnote (Leitsatz), operative_part (Tenor), facts, reasons, grounds, dissent. Default parts: "
        "headnote and operative_part. Pass doc_id from de_case_search, or a file_number (with court when it is "
        "ambiguous). Show source.attribution with any text you quote. It returns the court's text, not legal advice."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "doc_id": {"type": "string", "description": "Document id from de_case_search, e.g. 'JURE100055033'."},
            "file_number": {"type": "string", "description": "Aktenzeichen, used when doc_id is not known."},
            "court": {"type": "string", "description": "Court prefix to pick between decisions with the same file number."},
            "parts": {
                "type": "array",
                "items": {"type": "string", "enum": ["headnote", "other_headnote", "operative_part", "facts",
                                                     "reasons", "grounds", "dissent", "other", "all"]},
                "description": "Which parts to return (default headnote and operative_part; 'all' for everything).",
            },
            "max_chars": {"type": "integer", "minimum": 500, "maximum": 60000, "default": 6000,
                          "description": "Total characters across all returned parts (default 6000)."},
        },
        "required": [],
    },
}

ALL_SCHEMAS = [GET, SEARCH, TOC, CASE_SEARCH, CASE_GET]
