# MarketMind AI — конкурентный поиск и аналитика (2026-11-07)

## Исправлено
- Yandex Market search previously called fetch_product() on a search URL and returned one synthetic ProductData with the search URL as product URL.
- Added parse_yandex_market_search_html(): reads Schema.org Product JSON-LD from ItemList, deduplicates repeated Product nodes, returns actual product URLs, prices, images, stock, ratings/review counts, brand/category where present.
- YandexMarketParser.search() now fetches the search page and returns up to max_results real ProductData offers; records blocked/error/parse statuses.
- build_ozon_card_search_query() now searches the core explicit product name without the user's own brand or color. This surfaces competing brands and avoids over-specific zero-result queries.
- Competitor relevance filter handles common product synonyms (headphones/headsets/TWS, cable, cases) and deduplicates identical product URLs.
- Competitor summary reports counts per marketplace, price min/max/median, and common words. Marketplace labels are human-readable.
- Competitor metadata includes old price, discount, rating, reviews, availability, seller, product URL, and reference image URL.
- AI prompt receives marketplace, price, old price, discount, rating, review count and availability for competitor context.
- Single-card XLSX and batch XLSX include a separate “Конкуренты” sheet. Product and image URLs are clickable; competitor images are explicitly marked reference-only and are never assigned as the user's own product photos.
- Telegram card preview includes escaped competitor analytics; readiness score wording clarified. Telegram notification identifies marketplaces and notes Ozon anti-bot cooldown.
- Fixed product brief routing and wireless-headphones-vs-cable misclassification in previous work; AI HTTP proxy config for Gemini/Claude already added.

## Live validation (user's Linux Mint PC)
- Actual query generated from the user's brief: “Беспроводные наушники” (generic category, not brand-restricted).
- Yandex Market returned 8 real product offers with actual /card/... URLs, prices and image URLs.
- Results included Xiaomi Redmi Buds, Hoco, Pods and other wireless headphone listings from competing brands.
- Observed price range in this sample: 638–1963 RUB; median 963 RUB. Values are volatile and only a search snapshot.
- Ozon currently returns an anti-bot challenge and is put into cooldown; Wildberries returned no offers in the combined run. Do not claim those sources returned results.
- The over-restrictive query with color and brand returned zero; generic category query returned 8. Query builder was changed and live-verified.

## Tests and runtime
- Latest focused suite after latest code changes: 33 passed, 2 warnings.
- Earlier combined focused suite (before latest prompt/UI refinements): 117 passed, 3 warnings.
- `python -m compileall -q app tests` passed; `git diff --check` passed.
- Telegram service restarted after latest code changes; service active, Telegram connected, polling started.
- A full `pytest -q` run was stopped before completion to avoid leaving a long-running CPU-heavy test process. Do not report the full suite as passed.
