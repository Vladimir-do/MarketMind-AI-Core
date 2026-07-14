# Agent Instructions

## Quick Start

```bash
# Install
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium && playwright install-deps chromium
cp .env.example .env  # fill BOT_TOKEN and ADMIN_IDS minimum

# Run
python -m app.main --telegram     # Telegram bot
python -m app.main --update       # one-shot price update
python -m app.main --metrics 20   # last scrape attempts
python -m app.main --blocks 20    # block/timeout diagnostics
python -m app.main --report --embed-images  # HTML report
```

## Test, Lint, Typecheck

```bash
# Tests (unittest-based, run via pytest)
pytest tests/ -v
pytest tests/ -v -m "not slow"    # skip integration/slow tests
pytest tests/ --cov=app --cov-report=term-missing

# Lint + format (Ruff, line-length=120, Python 3.11)
ruff check .
ruff format --check .   # CI checks format without writing
ruff format .           # auto-fix

# Typecheck (mypy, non-strict — disallow_untyped_defs=false)
mypy app/
```

CI order: lint and test run in parallel; Docker build depends on both passing.

## Architecture

**MarketMind AI** — Python 3.11+ marketplace automation: parsers (Ozon/WB/Yandex), Ozon card generation, Telegram bot (35 commands), agent loop with skill registry, telemetry-backed recovery.

### Entrypoints

| File | Role |
|---|---|
| `app/main.py` | CLI: `--telegram`, `--update`, `--metrics`, `--blocks`, `--enrich`, `--report`, `--deploy-wb`, `--ozon-login` |
| `app/bot.py` | Telegram commands and natural-language routing |
| `app/config.py` | All env vars, proxy normalization, runtime path resolution |
| `app/database.py` | SQLAlchemy async models (Product, PriceHistory, ScrapeAttempt) |
| `cloud_wb_function.py` | Wildberries cloud fallback (Yandex Cloud Functions) |

### Key Modules

| Directory | Purpose |
|---|---|
| `app/parsers/` | Ozon, Wildberries, Yandex Market, FunPay parsers. Contract: return `ProductData` |
| `app/adapters/` | Marketplace API adapters (higher-level than parsers) |
| `app/universal_parsing_core/` | Generic page classification/extraction |
| `app/card_filler.py` | Ozon card draft + AI enhancement + JSON/XLSX export |
| `app/card_profiles.py` | YAML card generation profiles in `profiles/` |
| `app/task_intents.py` | Natural-language intent → `StructuredTask` |
| `app/task_planner.py` | `StructuredTask` → `TaskPlan` via skill registry |
| `app/agent_loop.py` | classify → strategy → execute → evaluate → recover |
| `app/skill_manifest.py` | Skill graph, dependency resolution |
| `app/worker.py` | Background add/update orchestration |
| `app/updater.py` | Marketplace update pipeline with retries |
| `app/resilience.py` | Rate limiter + circuit breaker |
| `app/exporter.py` | CSV/XLSX exports |

### Runtime Data

`MARKETMIND_DATA_DIR` (default `app/data`, fallback `/tmp/marketmind`) holds: SQLite DB, logs, scrape attempts JSONL, block patterns JSONL, Ozon browser profile, reports, debug output. Override individual paths via `DATABASE_URL`, `LOG_FILE`, `SCRAPE_ATTEMPTS_JSONL`, etc.

### Proxy Hierarchy

`COMMON_PROXY` → `PARSER_PROXY` (or legacy `PROXY`) for parsers; `COMMON_PROXY` → `TELEGRAM_API_PROXY` (or `TELEGRAM_PROXY`) for Telegram. Each can be http or socks5.

## Dependency Pinning Gotchas

- **aiogram 3.4.1 requires aiohttp~=3.9.0** — do not upgrade aiohttp independently
- aiohttp-socks==0.8.4 is pinned to avoid pulling a newer aiohttp
- playwright==1.42.0 — Playwright chromium version must match
- anthropic, openpyxl, pandas, PyYAML have upper bounds — check requirements.txt before updating

## Testing Quirks

- Tests use `unittest.TestCase`, not pytest fixtures/async. Run via `pytest` (not `python -m unittest`).
- `tests/helpers.py` has `reload_app_modules(database_url)` — reloads `app.config` and `app.database` to inject a test-specific DATABASE_URL. Use this when you need DB isolation.
- Integration/parser tests that hit real marketplaces should be marked `@pytest.mark.slow`.
- Tests mock external calls (HTTP, Telegram API, Playwright) — they should be deterministic with no network.
- `pytest cache_dir` is `/tmp/marketmind_pytest_cache` (configured in pyproject.toml).

## Skillpack

This project uses an active local skillpack at `project_skills/`. Before writing code, reading code, or reviewing:

1. Read `project_skills/SKILLPACK.md` and `project_skills/SKILL_TRIGGERS.md`
2. Search `project_skills/skills_index.json` for relevant skills
3. Prefer existing skill patterns over inventing new ones
4. If a file contains `@skills:`, read those skill IDs before editing

After each session, follow `project_skills/SESSION_UPDATE_PROTOCOL.md`. Run `python project_skills/validate_skills.py` after skill changes.

## graphify

Knowledge graph at `graphify-out/`. When the user types `/graphify`:

- `graphify query "<question>"` for codebase questions (scoped subgraph)
- `graphify path "<A>" "<B>"` for relationships
- `graphify explain "<concept>"` for focused concepts
- `graphify update .` after code changes (AST-only, no API cost)
- Use `graphify-out/wiki/index.md` for broad navigation

## Code Style

- Python 3.11+ (match/case, type hints, walrus operator)
- `snake_case` variables/functions, `PascalCase` classes, `UPPER_SNAKE_CASE` constants
- Ruff enforces: E, F, W, I, N, UP, B, A, C4, SIM, TCH (line-length=120, E501 ignored)
- Imports grouped: stdlib → third-party → `app.*` (Ruff sorts automatically)
- Conventional Commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`

## Verification Protocol

Before final response after code changes:

1. Run focused tests for the changed area
2. Run full test suite when blast radius touches shared routing, workers, database, Telegram, parser contracts, CLI, exports, or skillpack
3. Report exact verification signal: e.g. `102 tests OK`, `status=ok`, `ruff: no issues`
