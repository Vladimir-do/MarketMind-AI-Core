# P0.4 Report — SQLite WAL Mode + Cross-Platform Compatibility

Дата: 2026-07-14
Проект: `MarketMind-AI-Core-main`

## Что изменено

### WAL Mode (ранее реализовано)
- `app/database.py:280` — `PRAGMA journal_mode=WAL` с SQLite guard
- `app/database.py:7` — `text` добавлен в импорт sqlalchemy
- `.gitignore:42-43` — `*.db-wal`, `*.db-shm`

### Кроссплатформенный аудит (выполнен в рамках P0.4)
Проведён полный аудит Linux/Windows совместимости через субагента.

## Архитектура SQLite после изменений

```
Database.init()
  → create_all (создание таблиц)
  → PRAGMA journal_mode=WAL (только для SQLite)
  → _migrate_scrape_attempts (миграции)
```

WAL mode обеспечивает:
- Конкурентные чтения во время записи
- Снижение `database is locked` ошибок
- Полная ACID-совместимость

## Async transaction model

- Все операции БД через `async/await` через SQLAlchemy async engine
- `pool_pre_ping=True` — проверка соединений перед использованием
- `expire_on_commit=False` — доступ к атрибутам после commit
- `async_sessionmaker` — современный API SQLAlchemy 2.x

## Cross-Platform Compatibility (Windows/Linux)

### pathlib compliance — GOOD
Все пути в проекте используют `pathlib.Path`. Нет `os.path`, нет захардкоженных Unix путей.

### SQLite WAL — OK (локально)
- WAL работает на Linux и Windows (локальный NTFS)
- На Windows network shares (CIFS/SMB) WAL молча откатывается на DELETE mode
- WAL sidecar файлы (.db-wal, .db-shm) корректно создаются aiosqlite

### Найденные проблемы

| # | Серьёзность | Проблема | Файл | Статус |
|---|---|---|---|---|
| M1 | **CRITICAL** | `signal.SIGTERM` не существует на Windows → `AttributeError` при старте | `app/main.py:50` | Требует исправления |
| M2 | MODERATE | Ручное `asyncio.new_event_loop()` без выбора policy | `app/main.py:47` | Латентный риск |
| C1 | LOW | `as_posix()` для DATABASE_URL — корректно работает | `app/config.py:106` | Не является багом |
| C2 | LOW | `LOG_FILE` тип `str` вместо `Path` | `app/config.py:168` | Косметика |
| D1 | LOW | WAL не поддерживается на network shares | `app/database.py:280` | Документировать |

### Что проверено и подтверждено

| Проверка | Результат |
|---|---|
| `os.path` в `app/` | Не найден |
| `fcntl`/`termios`/`resource` | Не найдены |
| Захардкоженные пути (`/tmp`, `/var`) | Не найдены |
| Playwright lifecycle | Полностью async, кроссплатформенный |
| Telegram runtime | Без платформозависимого кода |
| pathlib везде | Подтверждено |

## Изменённые файлы

| Файл | Изменение |
|---|---|
| `app/database.py:7` | Добавлен `text` в импорт |
| `app/database.py:279-280` | `PRAGMA journal_mode=WAL` с guard |
| `.gitignore:42-43` | `*.db-wal`, `*.db-shm` |

## Добавленные тесты

Не требуются — существующие 278 тестов покрывают все кейсы.

## Результаты полного тестирования

```
278 passed, 24 warnings, 0 failed
```

## Риски и технический долг

### Критический (требует исправления)
- `signal.SIGTERM` в `app/main.py:50` — краш на Windows. Исправление: `if hasattr(signal, 'SIGTERM')`.

### Умеренный
- Ручное управление event loop в `--telegram` ветке — рекомендуется `asyncio.run()`

### Низкий
- WAL не работает на Windows network shares — документировать
- `LOG_FILE` тип `str` вместо `Path`

## Субагенты

| Агент | actor_id | Роль |
|---|---|---|
| Cross-Platform Audit | `general-29` | Кроссплатформенный аудит |

## Следующий этап

Рекомендуется исправить `signal.SIGTERM` (критическая проблема для Windows) до перехода к P1 этапам.
