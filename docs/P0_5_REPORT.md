# P0.5 Report — signal.SIGTERM Windows Compatibility Fix

Дата: 2026-07-14
Проект: `MarketMind-AI-Core-main`

## Проблема

`app/main.py:50` использовал `signal.signal(signal.SIGTERM, _shutdown_handler)` без проверки наличия атрибута. На Windows `signal.SIGTERM` не существует → `AttributeError` при запуске `python -m app.main --telegram`.

## Причина

`signal.SIGTERM` — Linux/Unix-only сигнал. Windows поддерживает только `SIGINT` (Ctrl+C) и `SIGBREAK`. Использование `signal.SIGTERM` без guard — типичная кроссплатформенная ошибка Python.

## Исправление

Однострочная проверка `hasattr(signal, 'SIGTERM')` перед регистрацией обработчика:

**Было:**
```python
signal.signal(signal.SIGTERM, _shutdown_handler)
signal.signal(signal.SIGINT, _shutdown_handler)
```

**Стало:**
```python
signal.signal(signal.SIGINT, _shutdown_handler)
if hasattr(signal, "SIGTERM"):
    signal.signal(signal.SIGTERM, _shutdown_handler)
```

## Изменённые файлы

| Файл | Изменение |
|---|---|
| `app/main.py:50-52` | SIGINT зарегистрирован первым, SIGTERM только если доступен |

## Тесты

Существующие тесты покрывают CLI и startup:
- `tests/test_cli.py` — 3/3 passed
- `tests/test_bot_startup.py` — 8/8 passed
- Полный набор — 278/278 passed

## Результат проверки Windows/Linux

| Платформа | До исправления | После исправления |
|---|---|---|
| **Linux** | SIGTERM + SIGINT работают | SIGTERM + SIGINT работают — без изменений |
| **Windows** | `AttributeError` при старте | Только SIGINT (Ctrl+C) — краша нет, завершение работает |

## Субагенты

| Агент | actor_id | Роль |
|---|---|---|
| Architect Agent | `general-30` | Анализ проблемы |
| Developer Agent | `general-31` | Исправление |
| Test Agent | `general-32` | Верификация |
| Reviewer Agent | `general-33` | Ревью — APPROVE |

## Статус P0 серии

| Задача | Статус | Тесты |
|---|---|---|
| P0.1 — `allowed()` vulnerability | ✅ APPROVE | 274 passed |
| P0.2 — atomic `record_scrape_attempt` | ✅ APPROVE | 274 passed |
| P0.3 — proxy credential masking | ✅ APPROVE | 278 passed |
| P0.4 — SQLite WAL mode | ✅ APPROVE | 278 passed |
| P0.5 — signal.SIGTERM Windows fix | ✅ APPROVE | 278 passed |

**Все P0 задачи завершены.**

## Рекомендуемый следующий этап

Переход к P1 — архитектурные улучшения:
- P1.1: Разделение `bot.py` (2984 строки) по ответственности
- P1.2: Alembic миграции
- P1.3: Объединение OzonParser и OzonUpdater
