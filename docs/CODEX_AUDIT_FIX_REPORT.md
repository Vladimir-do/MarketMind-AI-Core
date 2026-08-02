# Codex Audit Fix Report

Дата: 2026-07-16
Проект: `MarketMind-AI-Core-main`

## Что исправлено

Исправлено зависание тестов и инициализации БД, которое проявлялось на минимальном сценарии:

```text
await aiosqlite.connect(':memory:')
```

До исправления процесс зависал и завершался только по `timeout`.

## Первопричина

В текущей среде Python 3.12 после выполнения `sqlite3` в background thread callback через `loop.call_soon_threadsafe()` выполнялся, но ожидающая корутина не возобновлялась. `aiosqlite` зависит именно от этого механизма, поэтому `Database.init()` и DB-тесты зависали.

Проверено:

- обычный `sqlite3` работает;
- обычный `asyncio` работает;
- обычные threads работают;
- зависание появляется на связке `sqlite3` в worker thread + ожидание asyncio Future.

## Изменения

Добавлен compatibility patch:

- `app/compat/__init__.py`
- `app/compat/aiosqlite_patch.py`

Подключение patch добавлено в:

- `app/database.py`

Обновлены зависимости:

- `requirements.txt`: `aiosqlite>=0.22.1,<1`
- `requirements.txt`: `ruff>=0.15,<1`

## Что делает patch

Patch не меняет публичный API `aiosqlite` и не переписывает storage layer.

Он заменяет внутреннее ожидание `Future` в `aiosqlite.Connection` на короткое polling-ожидание через `asyncio.sleep(0.001)` для операций:

- `_connect`
- `_execute`
- `close`

Это обходит зависание event loop в текущем Python 3.12 runtime.

## Проверки

Минимальная проверка `aiosqlite`:

```text
(1,)
```

Минимальная проверка `Database.init()`:

```text
db-ok
```

Целевые тесты:

```text
tests/test_approval_workflow.py: 11 passed
tests/test_store_analyzer.py: 8 passed
tests/test_product_detail.py: 7 passed
tests/test_suggestions_ui.py: 8 passed
```

Полный тестовый набор:

```text
460 passed, 24 warnings, 14 subtests passed in 58.55s
```

Skillpack validation:

```text
Validation passed: 48 indexed skill(s), 48 markdown skill(s), 0 warning(s).
```

Ruff:

```text
ruff 0.15.21
app tests --select F821,F401,F841: All checks passed
```

Дополнительно восстановлены обратносуместимые helper re-export в `app.bot`, которые используются тестами и старыми вызовами.

## Оставшиеся проблемы

1. В рабочем дереве остаётся большой незакоммиченный слой P3.3-P3.5.
2. В этой sandbox-сессии `/mnt/steam/...` частично read-only для runtime cache/log paths, поэтому Ruff нужно запускать с `RUFF_CACHE_DIR=/tmp/...`.
3. Старые отчёты в `docs/` местами противоречат текущему фактическому состоянию.

## Рекомендуемый следующий шаг

Не начинать новый функционал. Сначала создать отдельный безопасный checkpoint для P3.3-P3.5 и нового DB-stability fix после ручного просмотра списка файлов.
