# Pending Skill Proposal: local production runtime

Status: `pending`

## What Was Discovered

L2 added a reusable single-operator production runtime pattern for a local FastAPI/SQLite project:

- explicit `MARKETMIND_HOME`;
- stable runtime layout outside `/tmp`;
- idempotent Linux/Windows launchers;
- startup backup before DB initialization or migration risk;
- UI-visible runtime mode banner;
- system status page with DB/workspace paths, free space, schema version and project counts;
- backup list with size/checksum;
- restore requiring explicit confirmation and protective backup;
- project-scoped archive zip with manifest/checksums/history.

## Why It Is Reusable

This pattern applies to local-first customer workflow tools that need to move from demo mode to real work without SaaS infrastructure.

It is especially useful when:

- SQLite remains the intended first production database;
- customer files must remain local;
- no authentication/multitenancy is desired yet;
- data loss from `/tmp` or silent runtime fallback is the main risk.

## Candidate Skill

ID candidate: `local-production-runtime`

Category: `deploy` or `filesystem`

Potential source paths:

- `start_marketmind.sh`
- `start_marketmind.bat`
- `app/runtime_paths.py`
- `app/runtime_cli.py`
- `app/backups/service.py`
- `app/projects/archive.py`
- `app/web/routes/system.py`
- `tests/test_l2_production_mode.py`

## Notes Before Promoting To Skill

- Observe first real-order usage.
- Decide whether this belongs under `deploy`, `filesystem`, or `operations`.
- Add a checklist for SQLite WAL backup/restore behavior before generalizing.
