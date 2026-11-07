# MarketMind AI — Ozon blocked-link fallback (2026-11-07)

## Problem observed
- User sent an Ozon product URL ending in product ID 823223431.
- Ozon returned HTTP 403 / abt-challenge; browser fallback also hit a challenge.
- Telegram previously reported “Добавлено: 0 товаров”; no product row was retained, so the subsequent card flow had to reconstruct everything from the URL.
- Telegram link-preview title is not part of the message text delivered to the bot; do not assume the bot can read the preview title.

## Changes made
- Added extract_ozon_product_identity(url): extracts a conservative slug-derived title and numeric Ozon product ID from `/product/<slug>-<id>/`.
- build_card_task_from_url now includes `артикул Ozon: <id>` and explicit warning that the name is URL-derived and must be verified.
- build_card_task_from_product adds the same article ID and marks a slug-derived title as unverified when there is no price or image. It avoids that warning when a previously parsed product name differs from the URL slug.
- worker_add_urls now saves a provisional Ozon record after a failed scrape when a usable product slug exists: URL, slug-derived name, price=None, image_url=None, availability=blocked. It separately reports that this is a draft from URL data, not a successful scrape.
- This preserves the product URL in the DB so the card-generation flow can find it by URL hash and continue creating an explicitly incomplete draft.
- No guessed price, image, weight, dimensions, or medical claims are created.

## Validation
- Added regression tests for Ozon ID extraction, unverified slug labels, and DB persistence after blocked Ozon fetch.
- Focused test suite: 125 passed, 1 warning.
- `git diff --check` passed.
- `python -m compileall -q app tests` passed.
- Restarted user service marketmind-bot.service; active, Telegram connected, polling started.

## Known limitation
- The slug is transliterated/URL-derived (e.g. `Kompleks vitaminov...`), not the verified display title. Price and image remain unknown when Ozon and alternate sources block access. User should manually verify title/brand/attributes until an authorized accessible product-data source is available.
