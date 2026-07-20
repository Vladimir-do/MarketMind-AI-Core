# Tech Stack Integration Plan

MarketMind AI should stay a modular Python marketplace automation core. The goal is to harden the existing stack before adding heavier infrastructure.

## Phase 1. Runtime Visibility And Config Safety

Status: started.

- Expose the active runtime stack in the system UI.
- Add production-readiness checks for Python, database backend, migrations, runtime paths, AI, jobs and observability.
- Keep empty `DATABASE_URL=` compatible with the documented SQLite default.
- Preserve local SQLite mode while making PostgreSQL configuration explicit.

## Phase 2. PostgreSQL-Ready Storage

Status: started.

- Keep SQLite for local/dev mode.
- Use `postgresql+asyncpg://...` for production deployments.
- Move schema evolution toward Alembic-first migrations.
- Add tests for PostgreSQL URL handling and non-SQLite runtime status paths.
- Use `python -m app.runtime_cli db-status` and `python -m app.runtime_cli db-upgrade` for explicit schema checks and upgrades.

## Phase 3. Durable Background Jobs

Status: started.

- Keep existing async workers as the local execution path.
- Introduce a small job abstraction before choosing Redis/RQ, Arq or Celery.
- Persist job status, progress, error class and retry metadata.
- Keep Telegram and web routes as clients of the job layer, not owners of long-running work.
- Use `job_records` as the stable database contract before adding a Redis-backed executor.

## Phase 4. Structured Observability

Status: planned.

- Add correlation IDs for import, parser, AI and export workflows.
- Keep scrape attempt telemetry as the source of marketplace diagnostics.
- Add structured log fields for job id, project id, marketplace, parser and status.
- Prepare optional Sentry/OpenTelemetry integration after the log contract is stable.

## Phase 5. API And UI Hardening

Status: planned.

- Add API auth/rate limiting before exposing non-local deployments.
- Keep Jinja2 + HTMX for operational UI until client-side state becomes a real need.
- Add Pydantic contracts around external API payloads, imports, AI suggestions and exports.

## Phase 6. Optional Scale Features

Status: deferred.

- React/Vue only if the UI becomes a state-heavy SPA.
- Kubernetes only after there is production load that requires orchestration.
- Vector search only when product history, competitor data or reports need semantic search.
