# L2 Production Mode Report

Дата: 2026-07-19

## Status

Статус: `PASSED`

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

Final results:

```text
tests/test_l2_production_mode.py: 6 passed
tests/test_client_projects.py tests/test_l1_1_final_acceptance.py: 32 passed
full pytest: 545 passed, 24 warnings, 14 subtests passed
Ruff changed files: All checks passed
git diff --check: passed
Alembic upgrade -> downgrade -1 -> upgrade head: passed on temporary SQLite
Secret scan changed files: no matches
```

## Manual Persistence Check

Проверено 2026-07-19:

1. Запущено `./start_marketmind.sh`.
2. UI показал `РАБОЧИЙ РЕЖИМ. ДАННЫЕ СОХРАНЯЮТСЯ`.
3. Через API создан проект `project_216924a7caa8` с названием `L2 persistence check`.
4. Сервер остановлен через Ctrl+C.
5. `./start_marketmind.sh` запущен повторно.
6. При повторном запуске автоматически создан backup:
   `runtime/backups/marketmind_20260719_191424_startup.db`.
7. Страница `/projects/project_216924a7caa8` открылась и показала сохранённый проект.

Результат: `PASSED`.

## Current Operator Command

```bash
cd /mnt/steam/Proekt/MarketMind-AI-Core-main
./start_marketmind.sh
```
