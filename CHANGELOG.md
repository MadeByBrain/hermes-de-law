# Changelog

## v1.0.0

First release.

- `de_law_get`: one section or article of a German federal law or an EU regulation or directive, optionally one paragraph, with Stand, gazette reference, source URL and attribution line. German and English citation forms (`§ 203 Abs. 1 Nr. 3 StGB`, `Art. 6(1)(f) GDPR`, recitals, annexes).
- `de_law_search`: find a law by abbreviation or title words (Gesetze im Internet index plus well-known EU acts).
- `de_law_toc`: table of contents of one law, filtered by a word in headings or text.
- `de_case_search` and `de_case_get`: decisions of the German federal courts from Rechtsprechung im Internet.
- Local cache under `HERMES_HOME/plugin-data/de-law/cache/` with ETag rechecks and a stale fallback when a source is down.
- Settings: `language`, `eu_language`, `max_age_hours`, `cache_max_mb`, `case_law`, `eu_law`.
- Skill `de-law:read-law` so the model finds the tools through Tool Search and quotes the source line.
