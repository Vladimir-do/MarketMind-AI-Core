# Project Defragmentation

This project has two recurring kinds of fragmentation:

- runtime/file clutter from browser profiles, debug dumps, logs, databases and scrape exports;
- code concentration in large modules that mix Telegram routing, orchestration and service logic.

Run the audit without deleting anything:

```bash
python tools/defrag_audit.py --limit 15
```

Machine-readable output:

```bash
python tools/defrag_audit.py --json
```

## Current Hotspots

Measured on this workspace:

- runtime clutter was cleaned: duplicate `venv`, `.ozon_profile`, pytest caches, debug dumps, scrape exports, loose generated HTML and logs were removed.
- `app/data` is down to the retained working database plus `.gitkeep` (about 368 KB).
- largest source module: `app/bot.py`, about 2107 lines after extracting Telegram startup/polling into `app/telegram_runtime.py`, network diagnostics into `app/telegram_diagnostics.py`, read-only Telegram message formatting into `app/telegram_messages.py`, document delivery into `app/telegram_exports.py`, AI report builders into `app/telegram_ai_reports.py`, and card helpers/research into `app/telegram_card_tasks.py` and `app/telegram_card_research.py`.
- cold `import app.bot` was reduced from about 7.26s to about 5.59s by making export/report/AI/card research/generic scraper dependencies lazy.
- root `test_wb.py` is a manual live smoke script; it must not be collected as a pytest unit test.

## Cleanup Rules

- Keep source, tests, docs, profiles, templates and skillpack files.
- Treat `.ozon_profile`, `app/data/debug`, logs, local DB files and scrape exports as generated runtime artifacts.
- Do not remove `.env` or the working `app/data/parser.db` automatically; they can contain active operator state.
- Keep live marketplace smoke checks opt-in, because they depend on external network/API behavior.
- Prefer moving Telegram command families out of `app/bot.py` gradually, with focused tests per extracted handler group.

## Refactor Order

1. Continue with remaining marketplace/card generation workflows from `app/bot.py`, especially batch Ozon card file assembly.
2. Keep parser contracts stable: parsers return `ProductData`, workers report progress, scrape attempts write telemetry.
3. Move shared DB aggregation queries into small service helpers before changing UI handlers.
4. Keep heavy optional dependencies lazy: `openpyxl`, report generation, AI analyzer, generic scraper and universal parser should not load on a plain `import app.bot`.
5. After each extraction, run focused bot tests and then the full test suite.
