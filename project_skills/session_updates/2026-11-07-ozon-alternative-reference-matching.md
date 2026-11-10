# Ozon alternative reference matching — 2026-11-07

## What changed
- Added `find_ozon_alternative_candidates()` in `app/parsers/alt_sources.py`.
- Uses the existing public Yandex Market search parser and real product offers (not synthetic search-page products).
- Extracts the Ozon slug and searches by its product identity.
- Added conservative match checks for brand (Immunit), magnesium, B-vitamin complex, effervescent form, and pack count (20).
- Cross-marketplace results are explicitly `reference_offer` records. No Yandex price, image, or availability is written into the original Ozon product row.
- Candidate records include source marketplace, source URL, per-field provenance, verification timestamp, match basis, and confidence.
- Because no common SKU/barcode was verified, the candidate is labelled a strong match (0.90), never an exact match.
- When an Ozon URL is saved as a provisional draft, the bot now performs one public Yandex Market search and, only for a strong match, sends a separate reference offer with its own price and link. The message explicitly says it is not an Ozon price and does not alter the original product data.
- Telegram HTML values are escaped before sending.

## Live check
For Ozon article 823223431, the public Yandex Market search returned 9 real offers. One strong match:
- Магний В6, B6 Immunit, шипучие таблетки 20 штук
- Observed Yandex Market offer price during this run: 299 RUB
- URL: https://market.yandex.ru/card/magniy-v6--v1-v2-v9-v5-v12-kompleks-shipuchiye-tabletki-20-shtuk-immunit-vitaminy-i-mineraly-dlya-nervnoy-sistemy-pri-sudorogakh/103262834418
- Other similar offers were rejected because brand, ingredient, form, or pack count did not match.

## Validation
- `tests/test_ozon_alternative_matching.py`, `tests/test_parsers.py`, `tests/test_worker.py`, `tests/test_yandex_market_search.py`: 59 passed, 17 warnings.
- Final targeted worker/matching check: 7 passed, 2 warnings.
- `git diff --check`: passed.
- `python -m compileall -q app tests`: passed.
- `marketmind-bot.service`: active after restart.

## Safety boundary
This does not bypass Ozon anti-bot protection. It searches public Yandex Market offers and keeps cross-marketplace reference data separate from the Ozon source record. No health or treatment claims are inferred.
