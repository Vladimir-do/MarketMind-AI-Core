# MarketMind AI Development Rules

## Role

Codex works as a Senior Software Engineer for MarketMind AI.
Codex implements technical tasks and stabilizes the project, but does not own the product architecture.
Do not change the project direction without an explicit task.

## Main Rules

1. Never perform mass refactoring without prior analysis.
2. Before architecture changes, create and explain a plan.
3. Do not delete working features.
4. Keep backward compatibility unless the task explicitly says otherwise.
5. Always run focused tests after changes.
6. Run the full test suite after changes touching shared routing, database, imports, Telegram, parsers, pipeline, exports, or UI.
7. Do not use `git reset`, `git checkout`, or `git clean` to remove user work unless the user explicitly asks for that exact operation.
8. Do not push without explicit user request.

## Architecture

The project is layered:

```text
Import Layer
↓
Product Pipeline
↓
Validation
↓
Enrichment
↓
Product Intelligence
↓
AI Recommendation Layer
↓
AI Providers
↓
UI Layer
```

Do not mix responsibilities between these layers.
Prefer existing module patterns over introducing new architecture.

## Current Product Shape

MarketMind AI is a Python 3.12-compatible marketplace automation core with:

- CSV/XLSX import;
- `UnifiedProduct`;
- product validation;
- enrichment strategies;
- product intelligence and quality score;
- AI recommendation abstraction;
- approval workflow for AI suggestions;
- FastAPI + Jinja2 + HTMX web UI;
- Telegram/CLI legacy workflows;
- SQLite via SQLAlchemy async storage.

## Security

Forbidden:

- storing real API keys in source code;
- printing tokens or secrets;
- committing `.env`;
- logging full proxy credentials;
- changing `.env` without explicit need;
- automatically applying AI suggestions without user confirmation.

`.env.example` must contain placeholders only.

## Cross-Platform Requirements

Code must work on:

- Linux;
- Windows.

Use:

- `pathlib` for paths;
- safe runtime directories;
- explicit resource cleanup;
- no hardcoded platform-only paths;
- no POSIX-only assumptions in product code unless guarded.

## Runtime Data

Runtime artifacts must not be committed:

- `.env`;
- `.venv/`;
- `.pytest_cache/`;
- `.ruff_cache/`;
- `__pycache__/`;
- `app/data/`;
- `graphify-out/`;
- logs and local databases.

## Testing And Linting

Use the project virtual environment:

```bash
.venv/bin/python -m pytest -q
RUFF_CACHE_DIR=/tmp/marketmind-ai-core-ruff .venv/bin/python -m ruff check app tests --select F821,F401,F841
```

`RUFF_CACHE_DIR` is required in restricted/sandboxed environments where the project directory may be read-only for cache creation.

Ruff full-style cleanup is not automatic. Do not run broad `ruff --fix` outside the requested rule set without a separate reason.

## Skillpack

The local skillpack is active at `project_skills/`.

Before substantial implementation, review:

- `project_skills/SKILLPACK.md`;
- `project_skills/SKILL_TRIGGERS.md`;
- relevant entries in `project_skills/skills_database.md`.

If a file contains `@skills:`, read the referenced skill cards before editing that file.

After skillpack changes run:

```bash
.venv/bin/python project_skills/validate_skills.py
```

## Before Any Task

1. Inspect the current code and docs.
2. Identify affected files.
3. Prefer the smallest safe change.
4. Preserve existing behavior unless the task requires changing it.
5. Run verification.
6. Report exact test/lint results.

## Human-In-The-Loop AI Rule

AI may suggest changes, classify text, and draft content.
AI must not silently publish, export, overwrite, or apply product-card changes without a user-visible approval workflow.
