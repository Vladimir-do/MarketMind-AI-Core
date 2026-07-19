# L2 Production Mode Plan

Дата: 2026-07-19

## Goal

Prepare MarketMind AI for first real local customer orders.

The owner should run:

```bash
./start_marketmind.sh
```

Then create a project, upload a real file, restart the app or computer, and still see all projects and files.

## Non-Goals

Do not add:

- registration or authentication;
- organizations;
- tariffs or payments;
- Seller API;
- Redis;
- microservices;
- SaaS features.

## Runtime Layout

Use `MARKETMIND_HOME` when set. Otherwise use:

```text
runtime/
  database/
  projects/
  uploads/
  exports/
  reports/
  backups/
  logs/
```

Production launcher will set:

- `DATABASE_URL=sqlite+aiosqlite:///<MARKETMIND_HOME>/database/marketmind.db`;
- `MARKETMIND_DATA_DIR=<MARKETMIND_HOME>`;
- `MARKETMIND_WORKSPACE_DIR=<MARKETMIND_HOME>`;
- `LOG_FILE=<MARKETMIND_HOME>/logs/marketmind.log`;
- `MARKETMIND_MODE=work`.

The current project workspace helper will continue to store project files under `<MARKETMIND_HOME>/projects/<project_id>/...`.

## Launchers

Add:

- `start_marketmind.sh`;
- `start_marketmind.bat`.

Both create directories idempotently and never delete existing runtime files.

Before startup they create a DB backup if the DB file exists.

Keep:

- `start_l1_demo.sh`;
- `start_l1_demo.bat`.

Demo mode must show: `ДЕМОНСТРАЦИОННЫЙ РЕЖИМ. ДАННЫЕ МОГУТ БЫТЬ УДАЛЕНЫ`.

Work mode must show: `РАБОЧИЙ РЕЖИМ. ДАННЫЕ СОХРАНЯЮТСЯ`.

## Services

Add small local services:

1. Runtime settings/status:
   - DB path;
   - workspace path;
   - free space;
   - last backup;
   - schema version;
   - project counts;
   - warnings for `/tmp` and low free space.

2. Backup service:
   - create SQLite DB backup;
   - list backups;
   - checksum each backup;
   - restore only with explicit confirmation;
   - protective backup before restore.

3. Project archive service:
   - export only selected project;
   - include source files, exports, reports, manifest, checksums and project-scoped history;
   - exclude `.env`, tokens, logs and other projects.

## Web UI

Add:

- `/system` status page;
- POST `/system/backups`;
- POST `/system/backups/{backup_name}/restore`;
- project archive button on project detail page;
- project archive download route;
- project archive/backup list in the UI;
- safe project archive action that only marks status `archived`.

Restore form must require explicit confirmation text.

## Tests

Add focused L2 tests:

- repeat startup preserves data;
- work mode does not use `/tmp`;
- backup creates a file;
- backup checksum matches;
- restore works;
- protective backup is created before restore;
- project archive contains only selected project;
- archive excludes secrets;
- other project data is absent from archive;
- low disk warning appears;
- demo and work mode banners differ visually.

## Verification

Run:

- new L2 tests;
- L1/L1.1 tests;
- full pytest;
- Ruff focused on changed files with `F821,F401,F841`;
- `git diff --check`;
- Alembic upgrade/downgrade/upgrade on a copied/temp DB;
- secret scan on changed files;
- manual persistence check after restarting `./start_marketmind.sh`.

## Commit Plan

1. docs audit/plan;
2. runtime launcher/services/UI;
3. L2 tests;
4. final docs/report/checklist.

Use explicit `git add` paths only. Do not push.
