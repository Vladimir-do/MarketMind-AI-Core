# URL Routing Review — 2026-11-20

Static source review only. No network testing or exploitation.

## U-01 — Ozon parser class uses substring URL matching (confirmed code-level inconsistency; potentially security-relevant)
File: app/parsers/ozon.py — `OzonParser.can_handle` returns `"ozon.ru" in url`.
The shared helpers in `app/utils/urls.py` correctly parse hostname and accept only exact domains/proper subdomains, but this parser method does not use them. `get_parser_class` in `app/parsers/router.py` iterates parser classes and invokes `can_handle`; thus lookalike URL strings containing ozon.ru may be classified by the Ozon parser in this selection path. The direct router path `detect_marketplace` uses stricter helper functions, so paths differ.
Recommended: make `OzonParser.can_handle` delegate to `is_ozon_url`; add regression cases for attacker-controlled hosts, credentials, ports and malformed URLs. Test all parser class-selection paths.

## U-02 — Wildcard UniversalParser
`UniversalParser.can_handle` returns True for every URL. This may be intentional as a fallback. Review the caller boundaries and ensure arbitrary URL fetches are constrained by scheme, hostname/IP validation, redirects and network policy. This observation alone is not an SSRF finding.

## U-03 — URL-classification consistency
Dashboard/product display helper functions use substring marketplace labels, while shared URL utility functions implement exact host/subdomain matching. Consolidate classification onto shared helpers to avoid misleading labels and reduce duplicate logic.

## Evidence and limits
These observations are based on the source code inspected in this audit branch; no dynamic tests were run. U-01 should be fixed and regression-tested before being treated as confirmed network exploitability.
