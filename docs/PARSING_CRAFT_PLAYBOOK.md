# Parsing Craft Playbook

This playbook defines the standard for clean, robust and maintainable parsing in
Parser Agent. A good parser is not a pile of selectors. It is a small measured
pipeline with contracts, fallbacks, telemetry and regression examples.

## Principles

1. Preserve the source contract
   - Product parsers return `ProductData`.
   - Marketplace routing stays centralized in `app/parsers/router.py`.
   - Worker code reports progress and keeps resumable behavior.

2. Prefer structured data first
   - Use marketplace APIs, embedded JSON, JSON-LD, `__NEXT_DATA__` or other
     structured payloads before fragile visual selectors.
   - Parse visible HTML as a fallback, not as the only truth when richer data is
     available.

3. Build layered extraction
   - Canonical URL and product id.
   - Title, brand and image.
   - Price and currency.
   - Availability.
   - Rating, reviews and optional marketplace-specific fields.
   - Validation and normalization.

4. Make every fallback explicit
   - Name the source: `api`, `html`, `json_ld`, `browser`, `strategy`.
   - Record why the primary path failed.
   - Do not hide browser fallback as a normal fast path.

5. Treat anti-bot signals as data
   - Classify `403`, `429`, captcha, `abt-challenge`, reset, timeout and proxy
     failures separately.
   - Record scrape attempts and blocked patterns.
   - Let adaptive strategy decide cooldowns and skips.

6. Validate before saving
   - Do not save a product with an empty title and guessed price.
   - Normalize prices from minor units, formatted strings and currency symbols.
   - Keep old image when a later update has no image.
   - Distinguish `out_of_stock`, `unknown` and parser failure.

7. Classify before generic scraping
   - Run a page-structure preflight before a generic product scraper.
   - Preserve a domain-level task type (`product_catalog`, `restaurant_menu`,
     `freelance_project`, `article`, `api_source`, `universal_page`) separately
     from the executor-level `TaskType.SCRAPING`.
   - Continue extraction only for `CATALOG`, `SINGLE`, or `MIXED`.
   - Stop `ARTICLE`, `EMPTY`, `UNKNOWN`, and `UNKNOWN_JS` with a visible
     diagnostic, `next_strategy`, and saved failure memory.
   - Do not turn a freelance brief, article, homepage or JS shell into an
     all-empty product CSV attempt.
   - If `UNKNOWN_JS` or a loading shell returns `next_strategy=browser`, switch
     the generic scraper to a rendered HTML fetcher explicitly; the second
     extraction pass must use the rendered source, not silently repeat the same
     static HTTP fetch.

## Parser Shape

Use this order when adding or fixing a parser:

1. Identify the marketplace and URL patterns in the router.
2. Add a small parser entrypoint that returns `ProductData`.
3. Add pure extraction helpers for payloads or HTML fragments.
4. Add tests with saved minimal fixtures or inline fragments.
5. Add scrape telemetry fields: source, status, HTTP status, latency and error.
6. Add block classification and debug artifacts when extraction fails.
7. Add a live smoke check only when it is safe and needed.

## Beautiful Extraction

Beautiful parsing code has these traits:

- narrow helpers with names like `extract_price`, `extract_json_ld_product`,
  `classify_availability`;
- one normalization path for money, URLs and availability;
- no marketplace-specific dicts leaking outside parser boundaries;
- no hardcoded sleeps where adaptive strategy should decide;
- no broad `except Exception` without status and telemetry;
- tests that prove the parser ignores false block markers when real product
  data is present;
- graceful partial data only when the contract allows it.

## Test Matrix

For each marketplace parser, keep focused tests for:

- a normal product page or API payload;
- missing price;
- out-of-stock product;
- lazy or protocol-relative image URL;
- false-positive block words inside normal scripts;
- real block or HTTP failure classification;
- router detection;
- worker behavior when the parser returns blocked/error.

## Review Checklist

Before calling parsing work done:

- `ProductData` fields are normalized.
- The router knows the URL pattern.
- The worker can report progress and errors.
- Scrape attempts produce measurable telemetry.
- Blocked pages do not poison product history.
- Fallbacks are visible in status/source.
- Tests cover the bug or marketplace behavior that motivated the change.
- Skillpack receives any reusable lesson.

## Anti-Patterns

- Selector soup in one long function.
- Parsing only by CSS classes copied from devtools.
- Returning raw dicts from a new parser.
- Retrying the same blocked URL without cooldown.
- Treating network errors as anti-bot without a trigger.
- Marking a product unavailable just because parsing failed.
- Saving invented data to satisfy a required field.
- Adding browser automation before trying structured sources.
