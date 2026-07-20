# Pending Skill Proposal: Runtime Stack Readiness Checks

Status: pending

## What Changed

Added a runtime stack/readiness helper in `app/stack_status.py` and exposed it through `app.runtime_paths.system_status()` and the `/system` UI.

The same hardening pass also added explicit Alembic runtime helpers in `app/db_migrations.py` and CLI commands in `app/runtime_cli.py`:

- `python -m app.runtime_cli db-status`
- `python -m app.runtime_cli db-upgrade`

## Why It Is Reusable

Marketplace automation projects need a low-risk way to show which runtime stack is active and which production hardening steps are still missing. This avoids undocumented assumptions about SQLite/PostgreSQL, AI enablement, background jobs and observability.

The migration helpers are reusable because they give local scripts and deployment wrappers a stable app-level contract around Alembic without silently running migrations during ordinary `Database.init()`.

The durable-job pass added `job_records` as a persistent database contract for future background execution. Existing async workers are unchanged, but imports/parsers/exports can now record job lifecycle state before a Redis/RQ/Arq/Celery executor is introduced.

## Candidate Skill

- ID: `runtime-stack-readiness`
- Category: `deploy` or `observability`
- Dependencies: `config-env-loader`, `database-async-sqlalchemy`, `logging-rotating-file`
- Source paths: `app/stack_status.py`, `app/runtime_paths.py`, `app/web/templates/system.html`
- Related source paths: `app/db_migrations.py`, `app/runtime_cli.py`, `tests/test_db_migrations.py`
- Durable job source paths: `app/database.py`, `alembic/versions/d5e6f7a8b9c0_add_job_records.py`, `tests/test_database.py`

## Notes

This should become a full skill after the readiness checks are used by at least one more deployment or runtime-hardening task.
