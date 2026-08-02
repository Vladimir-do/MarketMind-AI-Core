# P4 Platform Hardening Report

## Итог

P4 укрепил Timeline, Product Versioning и Domain Events без изменения публичных контрактов:

- старый `GET /api/products/{product_id}/history` сохранен как approval-only контракт;
- агрегированный `GET /api/products/{product_id}/timeline` сохранен и расширен внутренне через Domain Events;
- Versioning endpoints сохранены;
- persisted event store и таблица `domain_events` не добавлялись;
- AI-рекомендации не применяются автоматически.

## Найденные дефекты

1. Timeline и Domain Events имели параллельные правила формирования событий.
   Доказательство: `ProductHistoryBuilder` строил UI-события напрямую из `Product`, `PriceHistory`, `ApprovalRecord`, а `app/domain/events/` существовал отдельно.

2. Фильтр дат для `ApprovalRecord` зависел от `created_at`, хотя lifecycle-события имеют собственные даты `reviewed_at`, `applied_at`, `rolled_back_at`.

3. `PriceHistory` на границе `date_from` не имел predecessor row, поэтому `old_value` для первой записи диапазона терялся.

4. Времена сравнивались как naive datetime в нескольких местах read-model слоя.

5. Product Versioning подставлял текущие значения товара в derived snapshot без явной маркировки неполноты исторических данных.

6. Offset pagination могла возвращать некорректное глобальное окно при искусственном ограничении `source_limit`.

## Архитектура до

```text
Product / PriceHistory / ApprovalRecord
        |
        v
ProductHistoryBuilder
        |
        v
ProductHistoryEvent[]
        |
        v
Timeline UI / ProductVersionBuilder

DomainEvent существовал отдельно и не был источником Timeline.
```

## Архитектура после

```text
Product / PriceHistory / ApprovalRecord
        |
        v
Domain Event builders
        |
        v
DomainEvent[]
        |
        v
TimelineEventMapper
        |
        v
ProductHistoryEvent[]
        |
        v
Timeline UI / ProductVersionBuilder
```

DomainEvent остается машинным событием без русских UI-подписей. Русские подписи формируются presentation-слоем.

## Сохраненные API

- `GET /api/products/{product_id}/history`
- `GET /api/products/{product_id}/timeline`
- `GET /products/{product_id}/timeline`
- `GET /api/products/{product_id}/versions`
- `GET /api/products/{product_id}/versions/{version}`
- `GET /api/products/{product_id}/versions/compare`
- HTML-страницы версий и сравнения

## Pagination

Текущий endpoint сохраняет `limit`, `offset`, `sort`.

Правила:

- `limit` нормализуется в диапазон `1..200`;
- `offset` не может быть меньше `0`;
- сортировка по умолчанию `newest_first`;
- глобальное окно считается после merge всех источников, фильтрации и сортировки;
- `has_more` считается через запрос `limit + 1`.

Ограничение: read-model approach для больших offset требует загрузить все source rows товара. Это корректно, но не оптимально для 100k+ событий. Для будущего persisted event store нужен cursor-based API.

## Время

Внутренний стандарт P4:

- DomainEvent хранит UTC-aware `occurred_at`;
- legacy naive datetime из SQLite трактуется как UTC;
- aware datetime конвертируется в тот же момент UTC;
- сериализация API использует ISO 8601;
- сравнение выполняется через единый helper `event_sort_key`.

## Version Completeness

ProductVersion теперь явно сообщает:

- `is_derived`;
- `snapshot_completeness`;
- `known_fields`;
- `unknown_fields`;
- `source_event_ids`;
- `quality_score_is_historical`.

UI показывает «Частично восстановленная версия», если snapshot неполный. Старые версии больше не выглядят как полностью исторические snapshots.

## Индексы и миграция

Добавлена Alembic migration:

`alembic/versions/e5f6a7b8c9d0_add_timeline_composite_indexes.py`

Индексы:

- `ix_price_history_product_recorded` на `price_history(product_id, recorded_at)`;
- `ix_approval_records_product_created` на `approval_records(product_id, created_at)`.

Query plan до composite index:

```text
price_history: SEARCH price_history USING INDEX ix_price_history_product_id + USE TEMP B-TREE FOR ORDER BY
approval_records: SEARCH approval_records USING INDEX ix_approval_records_product_id + USE TEMP B-TREE FOR ORDER BY
```

Query plan после composite index:

```text
price_history: SEARCH price_history USING INDEX ix_price_history_product_recorded
approval_records: SEARCH approval_records USING INDEX ix_approval_records_product_created
```

## Benchmark

Команда:

```bash
.venv/bin/python scripts/bench_timeline.py
```

Результат:

```text
10 rows:    19 events, 1.37 ms, 29.27 KB peak
1000 rows:  50 events, 197.31 ms, 2823.55 KB peak
10000 rows: 50 events, 1918.14 ms, 29428.33 KB peak
```

Предупреждение `parser.log` связано с read-only sandbox mount и не меняет результат benchmark.

## Тесты

Focused:

```text
51 passed in 48.17s
```

Full pytest:

```text
498 passed, 24 warnings in 96.19s
```

Skillpack validation:

```text
Validation passed: 48 indexed skill(s), 48 markdown skill(s), 0 warning(s).
```

`git diff --check`: clean.

## Ruff

P4 changed scope:

```text
All checks passed
```

Full Ruff baseline:

```text
RUFF_CACHE_DIR=/tmp/marketmind-ai-core-ruff .venv/bin/python -m ruff check app tests
Found 289 errors.
```

Это legacy backlog вне P4. Массовый `ruff --fix` не выполнялся.

## Type Checking

В `pyproject.toml` есть секция `tool.mypy`, но пакет `mypy` отсутствует в текущем `.venv`:

```text
No module named mypy
```

Зависимости не менялись.

## Оставшиеся ограничения

- Для 100k+ событий read-model Timeline корректен, но дорог по памяти и времени.
- Cursor pagination поверх persisted event store потребуется позже.
- Полные исторические snapshots нельзя честно восстановить из текущих source tables.
- Rollback к версии не реализован.
- Card Editor не реализован.
- Persisted `domain_events` пока не добавлен.

## Готовность к Card Editor

Фундамент готов для проектирования Card Editor. Реализация редактора требует отдельного этапа: persisted snapshots/events, optimistic locking, conflict detection, user actor/comment и transactional audit trail.
