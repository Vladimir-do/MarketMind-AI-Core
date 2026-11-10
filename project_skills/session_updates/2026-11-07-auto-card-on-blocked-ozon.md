# Automatic Ozon card generation after blocked parsing (2026-11-07)

## Change
- Added `_auto_generate_blocked_ozon_cards()` in `app/bot.py`.
- The regular `/add` flow (`Form.waiting_urls`) and natural-language add flow now call it after URL ingestion.
- It checks each Ozon URL's saved product row and latest `PriceHistory.availability_status`; only `blocked` products are sent to card generation. Successful Ozon parses and other marketplaces are not duplicated.
- Generates XLSX + JSON through the existing `generate_ozon_card_files()` flow, including competitor lookup and quality report.
- Task prompt explicitly warns that Ozon blocked the source and forbids inventing price, photos, brand, composition, dose, characteristics, availability, or reviews.
- Per-item exception handling keeps a failed draft from aborting other URLs and leaves `/make_card_last` as a retry path.

## Important implementation detail
- `Product` model has no `availability` attribute. Block status is stored in the latest `PriceHistory.availability_status`; the helper correctly reads that source.

## Safety fix
- Supplement factual-claim filtering now runs for AI success, AI unavailable, AI 503/error, and invalid AI output local fallbacks. This removes unsupported generic claims such as "Информация предоставлена производителем" from local supplement drafts too.

## Tests and runtime
- Added tests: blocked Ozon product triggers one card generation; successfully parsed product is skipped; supplement local fallback strips unsupported claims.
- Focused test suite: 128 passed, 3 warnings (existing BeautifulSoup deprecation and aiohttp HTTPS proxy runtime warning).
- compileall and git diff --check passed.
- Full pytest suite was started but intentionally stopped after ~38% because it was running for several minutes; do not report it as passing.
- `marketmind-bot.service` restarted successfully and is active.
- AI_HTTP_PROXY remains `http://127.0.0.1:10808`.

## Manual verification
- Next test: send a new Ozon product URL through `/add` or the ordinary add flow. If Ozon saves it with `blocked`, bot should automatically send progress, quality report, preview, XLSX and JSON without `/make_card_last`.
