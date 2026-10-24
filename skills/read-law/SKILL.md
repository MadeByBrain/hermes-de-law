---
name: read-law
description: "German or EU law question (§, Art., StGB, BGB, DSGVO/GDPR, AI Act, BGH, BVerfG)? Before web_search, use tool_search for the de-law tools and quote source.attribution."
---

When the user asks about a German federal law, an EU regulation or directive, or a decision of a German federal court, read the source text with the de-law tools before you answer. If they are not in your tool list, call `tool_search` with an English query such as "German law section" or "German federal court decision", then `tool_call`.

- A citation like `§ 203 StGB`, `Art. 6 Abs. 1 lit. f DSGVO` or `Art. 50 AI Act`: call `de_law_get` with `citation` exactly as written.
- A topic inside a known law ("Widerruf im BGB"): `de_law_toc` with `law` and `query`, then `de_law_get`.
- An unknown law or abbreviation: `de_law_search`.
- A court decision by file number (Aktenzeichen): `de_case_search`, then `de_case_get`.

When you quote a provision or a decision, add `source.attribution` and `source.url`, and the version: `version.status` (Stand) and `version.data_as_of` for German law, `version.consolidated_as_of` for EU law. If `stale` is true, say the source could not be reached and give the cache date.

If you did not call a de-law tool, say you did not fetch the text. Do not write a provision from memory and do not say it came from Gesetze im Internet or EUR-Lex. Never guess a nearby section number after `section_not_found`.

The texts are consolidated versions from the official databases. Only the Bundesgesetzblatt and the Official Journal of the EU are legally binding. The plugin returns legal texts, not legal advice; for a decision about a real case, the user needs a lawyer.

Auf Deutsch: Bei Fragen zu Bundesgesetzen, EU-Recht oder Bundesgerichten zuerst den Wortlaut mit den de-law-Werkzeugen holen (sonst per `tool_search` finden), `source.attribution` und den Stand mit angeben, nichts aus dem Gedächtnis zitieren. Das Plugin liefert Gesetzestexte, keine Rechtsberatung.
