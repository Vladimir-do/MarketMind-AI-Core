# MarketMind AI

Market automation core with CSV/XLSX import, product validation, enrichment, AI recommendations, and web UI.

## Architecture

Layered: Import → Product Pipeline → Validation → Enrichment → Product Intelligence → AI Recommendation → AI Providers → UI

## Tech Stack

- Python 3.12, FastAPI + Jinja2 + HTMX
- SQLAlchemy async with SQLite
- aiohttp for HTTP
- Ruff for linting, pytest for tests

## Rules

- Never store API keys in source code
- Run focused tests after changes: `pytest tests/ -q`
- Use `pathlib` for cross-platform paths
- Keep backward compatibility unless explicitly told otherwise
- AI suggestions require user approval workflow
