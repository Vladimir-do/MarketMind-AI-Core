# L2 Production Mode Audit

Дата: 2026-07-19

## Scope

Read-only audit before adding a persistent real-order operating mode.

L1.1 demo remains accepted. L2 must keep demo separate and add a simple local production mode for real client files without SaaS features.

## Current Launch Modes

- `./start_l1_demo.sh` calls `START_L1_DEMO.py`.
- `start_l1_demo.bat` does the same on Windows.
- `START_L1_DEMO.py` stores demo data under the OS temp directory:
  - `/tmp/marketmind_l1_acceptance_demo/data`;
  - `/tmp/marketmind_l1_acceptance_demo/workspace`;
  - `/tmp/marketmind_l1_acceptance_demo/marketmind_l1_demo.db`.
- `app/main.py --web` can start FastAPI but does not define a real-order runtime layout.

## Runtime Paths

`app/config.py` currently derives:

- `RUNTIME_DATA_DIR` from `MARKETMIND_DATA_DIR`, defaulting to `app/data`, with fallback to `/tmp/marketmind` if the preferred directory is not writable;
- `DATABASE_URL` from `RUNTIME_DATA_DIR / parser.db`;
- `MARKETMIND_WORKSPACE_DIR` from `RUNTIME_DATA_DIR / workspace`;
- logs from `RUNTIME_DATA_DIR / logs / parser.log`.

This is safe for tests and legacy operation, but it is not explicit enough for first real orders because fallback to `/tmp` can silently create ephemeral state.

## Workspace And Artifacts

Project files live under:

```text
MARKETMIND_WORKSPACE_DIR/
  projects/
    <project_id>/
      source/
      exports/
      reports/
```

`app/workspace/files.py` already uses safe project paths and checks that generated files stay inside the selected project root.

Exports and reports are project-scoped:

- `ProjectExportService` writes CSV/JSON/XLSX to the project `exports/` directory and stores checksums.
- `ClientDeliveryReportService` writes HTML/JSON/CSV to the project `reports/` directory.
- Download routes validate project ownership before returning files.

## Database And Migrations

`app/database.py::Database.init()` still calls `Base.metadata.create_all` and a small SQLite compatibility migration for `scrape_attempts`.

Alembic exists and is used by audit checks, but no launcher currently creates a DB backup before initialization or migration.

## Backups

No project-level or system-level backup UI exists yet.

Missing:

- create DB backup;
- list backups with date, size and checksum;
- restore only after explicit confirmation;
- protective backup before restore.

## Project Archiving

`ProjectService.archive_project()` marks a project as `archived`; it does not delete files. There is no UI button dedicated to safe archiving and no full project archive export.

Missing project archive export:

- source files;
- effective card export data;
- generated exports;
- generated reports;
- manifest and checksums;
- project-scoped change history.

## UI Status

`base.html` has no global operating-mode banner. Demo and real working mode are not visually distinguished.

There is no system status page showing DB path, workspace path, free space, backup state, schema version, project counts or `/tmp` warning.

## Risks For Real Orders

1. Demo mode uses `/tmp`; a user can mistake it for real work.
2. Persistent launcher is absent.
3. Backup/restore is absent.
4. Restore protection is absent.
5. System state is not visible to the operator.
6. Full project handoff archive is absent.

## L2 Direction

Add a local single-operator working mode, not SaaS:

- explicit `runtime/` directory or `MARKETMIND_HOME`;
- no silent deletion or overwrite on restart;
- automatic DB backup before DB init/migration in production launcher;
- UI backup/restore/status/project archive tools;
- visual distinction between demo and work mode.
