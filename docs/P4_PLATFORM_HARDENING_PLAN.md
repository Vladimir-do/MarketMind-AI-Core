# P4 Platform Hardening Plan

Дата: 2026-07-17

## Статус

План подготовлен после аудита checkpoint:

```text
4355959 feat: add product timeline and domain events foundation
```

Реализация не начата. Код менять только после отдельного подтверждения `ОДОБРЯЮ`.

## Фактическая архитектура до P4

```text
Product / PriceHistory / ApprovalRecord
        ↓
TimelineRepository
        ↓
ProductHistoryBuilder
        ↓
ProductHistoryEvent
        ↓
Timeline API / UI
        ↓
ProductVersionBuilder
```

Параллельно:

```text
Product / PriceHistory / ApprovalRecord
        ↓
ProductEventBuilder / ApprovalEventBuilder
        ↓
DomainEvent
        ↓
ReadModelEventReader
```

## Целевая архитектура P4

```text
Product / PriceHistory / ApprovalRecord
                  ↓
        Domain Event adapters
                  ↓
             DomainEvent[]
                  ↓
     Timeline presentation mapper
                  ↓
       ProductHistoryEvent[]
                  ↓
       ProductVersionBuilder
```

Разделение ответственности:

- `DomainEvent` — machine-readable бизнес-факт;
- `ProductHistoryEvent` — presentation/read-model для Timeline;
- `ProductVersion` — derived version read-model;
- русские подписи только в presentation layer.

## Найденные дефекты

| ID | Severity | Дефект | Доказательство | Исправление |
|---|---|---|---|---|
| P4-1 | HIGH | Domain Events не подключены к Timeline | `ProductHistoryBuilder` и `ProductEventBuilder` строят события параллельно | Добавить `DomainEvent -> ProductHistoryEvent` mapper и использовать domain adapters в Timeline |
| P4-2 | HIGH | Pagination неверна для больших offset | `source_limit` capped at `1000` до merge | Тесты offset и новый merge pagination алгоритм |
| P4-3 | HIGH | Approval lifecycle теряется при date filters | Repository фильтрует только `created_at` | Читать approval rows по OR всех lifecycle timestamps |
| P4-4 | HIGH | Price old_value теряется на `date_from` | первая запись диапазона становится baseline | Загружать predecessor row до `date_from` |
| P4-5 | HIGH | Timezone теряется через `replace(tzinfo=None)` | Timeline/Versioning/EventReader | Ввести UTC-aware helper |
| P4-6 | MEDIUM | Versioning не маркирует полноту | нет completeness metadata | Добавить completeness metadata и UI label |
| P4-7 | MEDIUM | API edge cases не защищены | мало контрактных тестов | Добавить тесты history/timeline/versions |
| P4-8 | MEDIUM | aiosqlite patch глобальный | patch применяется без flag/detection | Пока не менять; спланировать feature flag после доказательства |

## Сохраняемые API-контракты

Обязательно сохранить:

```text
GET /api/products/{product_id}/history
```

Approval-only payload остаётся списком:

```json
[
  {
    "approval_id": "...",
    "field": "...",
    "suggestion_type": "...",
    "before_value": "...",
    "after_value": "...",
    "reason": "...",
    "confidence": 0.9,
    "status": "pending",
    "reject_reason": null,
    "created_at": "...",
    "reviewed_at": null,
    "applied_at": null
  }
]
```

Обязательно сохранить:

```text
GET /api/products/{product_id}/timeline
GET /api/products/{product_id}/versions
GET /api/products/{product_id}/versions/{version_number}
GET /api/products/{product_id}/compare?from=1&to=2
```

Допускаются только обратно совместимые расширения:

- новые optional поля;
- `cursor` как дополнительный параметр;
- warnings/completeness metadata.

## Минимальный набор исправлений

### Step 1 — Зафиксировать дефекты тестами

Добавить failing-focused tests:

- approval lifecycle event inside date range when `created_at` is outside;
- price change at first row inside `date_from` with predecessor before range;
- offset `0, 50, 500, 950, 1000, 5000`;
- timezone equivalent instants;
- history contract unchanged;
- version completeness metadata absent/present after fix.

Коммит:

```text
test: expose timeline and versioning edge cases
```

### Step 2 — Timestamp rules

Добавить shared helper, например:

```text
app/domain/events/time.py
```

Правила:

- внутреннее время UTC-aware;
- aware datetime -> `astimezone(timezone.utc)`;
- legacy naive datetime -> считать UTC;
- не использовать `replace(tzinfo=None)` для сравнения;
- API отдаёт ISO 8601.

Коммит:

```text
fix: normalize event timestamps
```

### Step 3 — Domain Event adapters + Timeline mapper

Добавить:

```text
app/timeline/mapper.py
```

Функции:

```text
DomainEvent -> ProductHistoryEvent
```

Timeline Builder должен получать domain events, но public `ProductHistoryEvent` JSON оставить прежним.

Коммит:

```text
refactor: connect domain events through timeline adapters
```

### Step 4 — Timeline data loading correctness

Изменить `TimelineRepository`:

- approval rows фильтровать по OR:
  - `created_at`;
  - `reviewed_at`;
  - `applied_at`;
  - `rolled_back_at`;
- price rows загружать с predecessor до `date_from`;
- добавить метод для global merge window.

Коммит:

```text
fix: correct timeline filtering and pagination
```

### Step 5 — Pagination algorithm

Текущий offset API сохранить.

Алгоритм:

1. Нормализовать `limit <= 200`.
2. Для каждого источника загрузить window, достаточный для `offset + limit + 1`, но с documented max.
3. Merge all candidate events.
4. Sort globally by:
   - UTC occurred_at;
   - event priority;
   - event_id.
5. Slice global `[offset:offset+limit]`.
6. `has_more = len(sorted_events) > offset + limit`, если read window полный.
7. Для больших offset, где корректность дорогая, добавить warning и cursor extension.

Backwards-compatible extension:

```text
GET /api/products/{id}/timeline?cursor=<opaque>
```

Cursor не обязателен на первом P4 commit, но планировать его нужно.

### Step 6 — Version completeness metadata

Добавить в `ProductVersion`:

- `is_derived: bool`;
- `snapshot_completeness: "partial" | "complete"`;
- `known_fields: list[str]`;
- `unknown_fields: list[str]`;
- `source_event_ids: list[str]`;
- `quality_score_is_historical: bool`.

Для текущего read-model:

```text
is_derived = true
snapshot_completeness = "partial"
quality_score_is_historical = false
```

UI:

```text
Частично восстановленная версия
```

Коммит:

```text
feat: expose version completeness metadata
```

### Step 7 — Performance / query plan

Добавить lightweight test helpers или benchmark script:

```text
scripts/bench_timeline.py
```

Обычный pytest не должен гонять 100k тяжёлых событий.

Проверить:

- 10 events;
- 1 000 events;
- 10 000 events;
- optional 100 000 synthetic outside normal pytest.

SQLite:

```text
EXPLAIN QUERY PLAN
```

Проверить пользу:

```text
PriceHistory(product_id, recorded_at)
ApprovalRecord(product_id, created_at)
```

Миграцию создавать только если query plan докажет пользу.

## Нужна ли миграция

Сейчас: нет.

Причина:

- P4 defects можно исправить через builders/repository/mapper/tests;
- persisted `domain_events` пока не нужен;
- composite indexes требуют query plan доказательства.

Миграция может понадобиться только для индексов после `EXPLAIN QUERY PLAN`.

## Изменяемые файлы после `ОДОБРЯЮ`

Ожидаемые:

- `app/domain/events/models.py`
- `app/domain/events/builders.py`
- `app/domain/events/reader.py`
- `app/domain/events/time.py` new
- `app/timeline/builder.py`
- `app/timeline/repository.py`
- `app/timeline/service.py`
- `app/timeline/mapper.py` new
- `app/products/versioning.py`
- `app/web/routes/product_detail.py`
- `app/web/templates/product_versions.html`
- `app/web/templates/product_version_compare.html`
- `tests/test_domain_events.py`
- `tests/test_timeline_engine.py`
- `tests/test_product_versions.py`
- `tests/test_product_detail.py`
- `docs/P4_PLATFORM_HARDENING_REPORT.md`

Возможные:

- `alembic/versions/*.py`, только если индексы доказаны query plan.
- `scripts/bench_timeline.py`, если нужен lightweight benchmark.

## План тестирования

Focused:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  tests/test_domain_events.py \
  tests/test_timeline_engine.py \
  tests/test_product_versions.py \
  tests/test_product_detail.py \
  tests/test_approval_workflow.py \
  -o cache_dir=/tmp/marketmind-p4-focused
```

Full:

```bash
RUFF_CACHE_DIR=/tmp/marketmind-ai-core-ruff .venv/bin/python -m ruff check app tests
git diff --check
.venv/bin/python project_skills/validate_skills.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o cache_dir=/tmp/marketmind-p4-full
```

Если full Ruff показывает legacy backlog:

1. Отделить новые/изменённые файлы.
2. Исправить только P4 scope.
3. Зафиксировать legacy baseline в отчёте.
4. Не делать массовый `ruff --fix`.

## Query plan / benchmark

Проверить через SQLite:

```sql
EXPLAIN QUERY PLAN
SELECT *
FROM price_history
WHERE product_id = ?
ORDER BY recorded_at DESC
LIMIT ?;
```

И approval:

```sql
EXPLAIN QUERY PLAN
SELECT *
FROM approval_records
WHERE product_id = ?
  AND (
    created_at BETWEEN ? AND ?
    OR reviewed_at BETWEEN ? AND ?
    OR applied_at BETWEEN ? AND ?
    OR rolled_back_at BETWEEN ? AND ?
  )
ORDER BY created_at DESC
LIMIT ?;
```

## Критерии приёмки P4 hardening

- `DomainEvent` становится источником Timeline через mapper.
- `/history` approval-only контракт сохранён.
- `/timeline` контракт сохранён или расширен обратно совместимо.
- date filters учитывают дату каждого lifecycle события.
- PriceHistory получает predecessor на `date_from`.
- timezone сравнение UTC-aware.
- pagination возвращает корректное глобальное окно или честный warning/cursor extension.
- Versioning отдаёт completeness metadata.
- AI не применяет изменения автоматически.
- Focused pytest проходит.
- Full pytest проходит.
- Ruff по P4 scope чистый; full Ruff либо чистый, либо legacy baseline documented.
- `git diff --check` чистый.
- `project_skills/validate_skills.py` проходит.

## Что нельзя решить без persisted event store

- Полный immutable audit trail.
- Надёжный outbox для notifications/background jobs.
- Исторические full snapshots карточки.
- Точный actor для старых событий.
- Гарантированный rollback любой ручной правки.
- История удаления/отмены событий.

Эти пункты должны перейти в `docs/P4_CARD_EDITOR_MASTER_PLAN.md` после укрепления платформы.

## План commit

После реализации:

```text
test: expose timeline and versioning edge cases
fix: normalize event timestamps
refactor: connect domain events through timeline adapters
fix: correct timeline filtering and pagination
feat: expose version completeness metadata
docs: add P4 platform hardening report
```

Push не выполнять.

## Решение

Можно переходить к реализации после отдельного сообщения:

```text
ОДОБРЯЮ
```
