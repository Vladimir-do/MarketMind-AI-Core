# Project Map

This file is a quick navigation map for maintainers.

## Runtime entrypoints

- `app/main.py` — CLI entrypoint (`--telegram`, `--update`, `--metrics`, `--blocks`).
- `app/bot.py` — Telegram command handlers and natural-language routing.

## Marketplace parsing and update loop

- `app/worker.py` — background orchestration for adding URLs and updating prices.
- `app/updater.py` — resilient parsing/update pipeline, retries, anti-block handling.
- `app/parsers/router.py` — parser selection by URL/marketplace.
- `app/parsers/ozon.py` — Ozon parser.
- `app/parsers/wildberries.py` — Wildberries parser.
- `app/searcher.py` — Ozon search + block-state helpers.

## Card generation

- `app/card_filler.py` — Ozon card draft model, enrichment, exports (JSON/XLSX).
- `app/card_research.py` — competitor research report formatting.
- `app/card_profiles.py` — profile loader (`profiles/*.yaml`) and defaults.
- `profiles/default.yaml` — baseline behavior.
- `profiles/electronics.yaml` — example client profile.

## AI and analytics

- `app/ai_client.py` — AI provider access and availability checks.
- `app/agent.py` / `app/ai_analyzer.py` — portfolio analysis, alerts, forecasts.

## Storage and exports

- `app/database.py` — SQLAlchemy models, DB session helpers, scrape/block telemetry.
- `app/exporter.py` — CSV/XLSX exports for tracked items.
- `app/reporter.py` — HTML report generation.

## Tests

- `tests/test_card_filler.py` — card builder behavior and exports.
- `tests/test_card_profiles.py` — profile loading/fallback.
- `tests/test_parsers.py` — parser integration behavior plus updater retry/block scenarios via mocks.

## Operational notes

- Keep browser profile/cache out of git (`.ozon_profile/`, playwright cache).
- Prefer adding new bot features behind explicit command handlers first, then natural-language aliases.
- For card behavior changes, update `test_card_filler.py` in the same commit.
