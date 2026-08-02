# P3.8 Timeline Engine Report

Дата: 2026-07-17

## Что сделано

Выделен канонический Timeline Engine в отдельный пакет `app/timeline/`.

Timeline теперь разделён на слои:

```text
TimelineRepository
↓
ProductHistoryBuilder
↓
TimelineService
↓
API / UI / Versioning
```

Схема БД не менялась. Новая таблица `timeline_events` не добавлялась.

## Новые файлы

- `app/timeline/__init__.py`
- `app/timeline/enums.py`
- `app/timeline/schemas.py`
- `app/timeline/builder.py`
- `app/timeline/repository.py`
- `app/timeline/service.py`
- `tests/test_timeline_engine.py`
- `docs/P3_8_TIMELINE_ENGINE_PLAN.md`
- `docs/P3_8_TIMELINE_ENGINE_REPORT.md`

## Изменённые файлы

- `app/products/history.py`
  - оставлен как backward-compatible re-export из `app.timeline`.

- `app/products/versioning.py`
  - переведён на canonical import `app.timeline.schemas.ProductHistoryEvent`.

- `app/web/routes/product_detail.py`
  - timeline API подключён через `TimelineService` и `TimelineRepository`.

- `app/web/templates/product_history.html`
  - источник события показывает русскую подпись `source_label`.

## Архитектура

`ProductHistoryBuilder` больше не должен знать о FastAPI, SQLAlchemy session или HTML.

`TimelineRepository` отвечает за загрузку:

- `Product`;
- `PriceHistory`;
- `ApprovalRecord`.

`TimelineService` отвечает за:

- нормализацию limit/offset;
- загрузку источников;
- вызов builder;
- формирование `ProductTimeline`;
- pagination metadata;
- warnings.

## Совместимость

Старый импорт сохранён:

```python
from app.products.history import ProductHistoryBuilder, ProductHistoryEvent
```

Он продолжает работать через re-export.

Старый approval-only endpoint:

```text
GET /api/products/{id}/history
```

не менялся на timeline payload.

## Поддерживаемые события P3.8

- импорт товара;
- изменение цены;
- изменение наличия;
- создание AI-рекомендации;
- одобрение AI-рекомендации;
- отклонение AI-рекомендации;
- применение AI-рекомендации;
- откат решения.

## Что осталось ограничением

- Timeline остаётся derived/read-only.
- Нет persisted immutable audit table.
- Нет actor/user для старых событий.
- Нет исторических snapshots description/brand/attributes.
- Для 100k+ событий позже нужна materialized timeline таблица или cursor pagination.

## Тесты

Добавлены focused tests:

- построение import/price/stock events;
- порядок событий с одинаковым timestamp;
- фильтр по source;
- дедупликация по `event_id` с warning.

Проверки:

- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_timeline_engine.py tests/test_product_detail.py tests/test_product_versions.py tests/test_approval_workflow.py -o cache_dir=/tmp/marketmind-timeline-engine-pytest`
  - результат: `40 passed in 31.70s`
- `RUFF_CACHE_DIR=/tmp/marketmind-ai-core-ruff .venv/bin/python -m ruff check app tests --select F821,F401,F841`
  - результат: `All checks passed!`
- `git diff --check`
  - результат: без ошибок
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o cache_dir=/tmp/marketmind-timeline-engine-full-pytest`
  - результат: `487 passed, 24 warnings in 79.08s`

## Итог

Timeline Engine готов быть основой для Product Versioning, Card Editor и будущего Audit Trail на уровне read-model. Для строгого audit trail позже потребуется persisted immutable event store.
