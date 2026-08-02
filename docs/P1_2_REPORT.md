# P1.2 Report — Alembic Migrations

Дата: 2026-07-14
Проект: `MarketMind-AI-Core-main`

## Старая схема работы БД

- `Base.metadata.create_all()` в `Database.init()` — создание таблиц при старте
- Ручные PRAGMA миграции в `_migrate_scrape_attempts()` — добавление колонок
- Нет версионирования схемы
- Нет возможности отката

## Новая схема миграций

- Alembic управляет версионированием схемы
- `alembic upgrade head` — применение миграций
- `alembic revision --autogenerate -m "description"` — создание новых миграций
- `alembic downgrade -1` — откат миграции
- CLI: `python -m app.main --migrate`

## Изменённые файлы

| Файл | Действие |
|---|---|
| `requirements.txt` | Добавлен `alembic>=1.13.0,<2` |
| `alembic.ini` | Создан — конфигурация Alembic |
| `alembic/env.py` | Создан — async engine, поддержка SQLite/PostgreSQL |
| `alembic/script.py.mako` | Создан — шаблон миграций |
| `alembic/versions/c2475736d3e0_initial_schema.py` | Создан — полная DDL для 5 таблиц |
| `app/main.py` | Добавлен флаг `--migrate` |
| `app/database.py` | Добавлены комментарии о замене create_all на Alembic |

## Тесты

```
278 passed, 24 warnings, 0 failed
```

## Субагенты

| Агент | actor_id | Роль |
|---|---|---|
| Architect Agent | `general-46` | Анализ текущей схемы |
| Developer Agent | `general-47` | Реализация Alembic |
| Test Agent | `general-48` | Верификация |
| Reviewer Agent | `general-49` | Ревью — REQUEST CHANGES (пустой migration) |
| Developer Agent (fix) | `general-50` | Исправление migration |
| Reviewer Agent (re-review) | `general-51` | Повторное ревью — APPROVE |

## Риски

| Риск | Серьёзность | Митигация |
|---|---|---|
| Существующие БД не проставлены в Alembic | MEDIUM | `alembic stamp head` для существующих БД |
| create_all всё ещё используется | LOW | Замена на Alembic upgrade head в будущем |
| PostgreSQL миграции требуют asyncpg | LOW | Добавить при необходимости |

## Готовность к следующим этапам

P1.2 завершён. Alembic настроен, миграции работают. Рекомендуемые следующие шаги:
- P1.3: Объединение OzonParser и OzonUpdater
- P1.4: Извлечение общих утилит
- P1.5: Тесты для resilience.py, updater.py, agent.py
