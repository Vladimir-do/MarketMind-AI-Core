# L2 Production Mode Report

Дата: 2026-07-19

## Status

Статус: `IMPLEMENTED_PENDING_FINAL_VERIFICATION`

L2 добавляет локальный постоянный рабочий режим для первых реальных заказов без SaaS-функций.

## Added

- Linux launcher: `./start_marketmind.sh`.
- Windows launcher: `start_marketmind.bat`.
- Persistent runtime layout under `runtime/` or custom `MARKETMIND_HOME`.
- Runtime directories:
  - `database/`;
  - `projects/`;
  - `uploads/`;
  - `exports/`;
  - `reports/`;
  - `backups/`;
  - `logs/`.
- Automatic startup DB backup when an existing SQLite DB is present.
- System status UI at `/system`.
- Manual DB backup creation.
- Backup list with date, size and checksum.
- Restore with explicit confirmation `ВОССТАНОВИТЬ`.
- Protective backup before restore.
- Work/demo mode banner.
- Safe project archive action.
- Full project archive zip with manifest, checksums, source files, exports, reports and project-scoped history.
- Real order checklist.

## Safety Boundaries

Not added:

- registration;
- authorization;
- tariffs;
- payments;
- organizations;
- Seller API;
- Redis;
- microservices;
- SaaS features.

## Data Persistence

Production launcher sets:

```text
MARKETMIND_HOME=<repo>/runtime
MARKETMIND_MODE=work
MARKETMIND_DATA_DIR=<repo>/runtime
MARKETMIND_WORKSPACE_DIR=<repo>/runtime
DATABASE_URL=sqlite+aiosqlite:///<repo>/runtime/database/marketmind.db
LOG_FILE=<repo>/runtime/logs/marketmind.log
```

Repeated startup does not delete or overwrite runtime data.

## Demo Mode

L1 demo launchers remain separate.

Demo UI shows:

```text
ДЕМОНСТРАЦИОННЫЙ РЕЖИМ. ДАННЫЕ МОГУТ БЫТЬ УДАЛЕНЫ
```

Work UI shows:

```text
РАБОЧИЙ РЕЖИМ. ДАННЫЕ СОХРАНЯЮТСЯ
```

## Verification

Initial focused result:

```text
tests/test_l2_production_mode.py: 6 passed
```

Final verification commands and manual persistence check must be recorded before marking L2 as fully passed.

## Current Operator Command

```bash
cd /mnt/steam/Proekt/MarketMind-AI-Core-main
./start_marketmind.sh
```
