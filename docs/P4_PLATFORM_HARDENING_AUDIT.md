# P4 Platform Hardening Audit

Дата: 2026-07-17

## Scope

Аудит выполнен для checkpoint:

```text
4355959 feat: add product timeline and domain events foundation
```

Команды состояния:

```text
pwd: /mnt/steam/Proekt/MarketMind-AI-Core-main
git root: /mnt/steam/Proekt/MarketMind-AI-Core-main
git status --short --untracked-files=all: clean
remote: не настроен
```

Код проекта на этой фазе не изменялся. Этот документ фиксирует доказательства и плановые дефекты перед реализацией.

## Проверенные файлы

- `AGENTS.md`
- `pyproject.toml`
- `app/database.py`
- `app/products/history.py`
- `app/products/versioning.py`
- `app/timeline/builder.py`
- `app/timeline/repository.py`
- `app/timeline/service.py`
- `app/domain/events/**`
- `app/web/routes/product_detail.py`
- `app/ai_recommendation/db_approval.py`
- `app/compat/aiosqlite_patch.py`
- `alembic/versions/*`
- `tests/test_domain_events.py`
- `tests/test_timeline_engine.py`
- `tests/test_product_versions.py`
- `tests/test_product_detail.py`
- отчёты P3.7, P3.8, P3.9.

## Текущее состояние архитектуры

Фактический pipeline P3:

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

Параллельно существует слой Domain Events:

```text
Product / PriceHistory / ApprovalRecord
        ↓
ProductEventBuilder / ApprovalEventBuilder
        ↓
DomainEvent
        ↓
ReadModelEventReader
```

Ключевой вывод: Domain Events пока не являются источником Timeline. Это было безопасно для P3.9, но для P4 создаёт риск рассинхронизации правил.

## Finding 1 — Domain Events не подключены к Timeline

Severity: HIGH

Доказательства:

- `app/domain/events/builders.py:11-210` создаёт `DomainEvent` из `Product`, `PriceHistory`, `ApprovalRecord`.
- `app/timeline/builder.py:71-96` строит `ProductHistoryEvent` напрямую из тех же ORM-моделей.
- `app/products/versioning.py:134-189` строит версии из `ProductHistoryEvent`, а не из `DomainEvent`.
- `app/web/routes/product_detail.py:391-420` отдаёт `/api/products/{product_id}/timeline` через `TimelineService`, который использует `ProductHistoryBuilder`.

Риск:

- параллельные `event_id`;
- параллельные source/status правила;
- разные actor semantics;
- разная обработка lifecycle событий;
- разные timestamp rules.

Минимальная рекомендация:

Добавить adapter:

```text
DomainEvent -> ProductHistoryEvent
```

и перевести `ProductHistoryBuilder` на использование Domain Event builders, сохранив JSON `/timeline`.

## Finding 2 — Timeline pagination некорректна на больших offset

Severity: HIGH

Доказательства:

- `TimelineService` вычисляет `source_limit = max(200, min(safe_offset + safe_limit + 50, 1_000))` в `app/timeline/service.py:39-42`.
- Затем оба источника читаются с этим limit в `app/timeline/service.py:44-55`.
- Глобальная pagination применяется после merge в `app/timeline/builder.py:292-299`.

Проблема:

Если `offset=5000`, `source_limit` остаётся `1000`. Глобальное окно после merge физически не может быть корректным, потому что данные после первых 1000 строк каждого источника не загружены.

Дополнительный риск:

При смешивании источников события одного источника могут вытеснить события другого до merge, если у одного источника высокая плотность событий.

Минимальная рекомендация:

- добавить тесты `offset=0,50,500,950,1000,5000`;
- для offset pagination временно грузить достаточный read window или явно ограничивать offset;
- добавить backward-compatible cursor extension для будущего масштабирования.

## Finding 3 — Approval lifecycle фильтруется по `created_at`, а не по дате события

Severity: HIGH

Доказательства:

- `TimelineRepository.get_approval_records()` фильтрует только `ApprovalRecord.created_at` в `app/timeline/repository.py:41-58`.
- `ProductHistoryBuilder._approval_events()` создаёт события по `created_at`, `reviewed_at`, `applied_at`, `rolled_back_at` в `app/timeline/builder.py:168-256`.

Проблема:

Запись с `created_at` вне диапазона, но `reviewed_at/applied_at/rolled_back_at` внутри диапазона, не попадёт в builder вообще.

Минимальная рекомендация:

В репозитории для approval source читать строки, где любой lifecycle timestamp пересекает диапазон:

```text
created_at OR reviewed_at OR applied_at OR rolled_back_at
```

Финальная фильтрация должна оставаться по `ProductHistoryEvent.occurred_at`.

## Finding 4 — PriceHistory теряет predecessor на границе `date_from`

Severity: HIGH

Доказательства:

- `TimelineRepository.get_price_history()` применяет `PriceHistory.recorded_at >= date_from` в `app/timeline/repository.py:22-39`.
- `ProductHistoryBuilder._price_and_stock_events()` пропускает первую запись как baseline в `app/timeline/builder.py:121-130`.

Проблема:

Если первая запись внутри диапазона уже является изменением относительно предыдущей записи до `date_from`, событие изменения не будет создано.

Минимальная рекомендация:

Загружать одну predecessor row до `date_from` для вычисления `old_value`, но не показывать predecessor как отдельное событие.

## Finding 5 — Timezone semantics небезопасны

Severity: HIGH

Доказательства:

- `app/timeline/builder.py:367-371` удаляет `tzinfo` через `replace(tzinfo=None)`.
- `app/products/versioning.py:275-279` делает то же самое.
- `app/domain/events/reader.py:60-64` делает то же самое.
- `DomainEvent.to_dict()` нормализует aware datetime в UTC и legacy naive как UTC в `app/domain/events/models.py:89-102`.

Проблема:

`replace(tzinfo=None)` меняет смысл момента времени при сравнении `2026-07-17T10:00:00+03:00` и `2026-07-17T07:00:00+00:00`.

Минимальная рекомендация:

Ввести общий helper:

```text
normalize_event_datetime(value) -> UTC-aware datetime
```

Правила:

- aware datetime -> `astimezone(timezone.utc)`;
- legacy naive datetime -> считать UTC и помечать как legacy в metadata/warnings, если нужно;
- API сериализует ISO 8601 с timezone.

## Finding 6 — Versioning snapshot не маркирует полноту

Severity: MEDIUM

Доказательства:

- `ProductVersionSnapshot` содержит поля карточки, но не содержит полноту/known/unknown metadata в `app/products/versioning.py:55-70`.
- `ProductVersion.to_dict()` не отдаёт `is_derived`, `snapshot_completeness`, `known_fields`, `unknown_fields`, `quality_score_is_historical` в `app/products/versioning.py:92-108`.
- `ProductVersionBuilder` инициализирует snapshot текущими `product.name` и `product.image_url` в `app/products/versioning.py:152-157`.
- Compare предупреждает о неполноте только строкой warnings в `app/products/versioning.py:219-221`.

Проблема:

Пользователь может принять частично восстановленную версию за исторически полную.

Минимальная рекомендация:

Добавить metadata:

- `is_derived`;
- `snapshot_completeness`;
- `known_fields`;
- `unknown_fields`;
- `source_event_ids`;
- `quality_score_is_historical`.

UI должен показывать: `Частично восстановленная версия`.

## Finding 7 — API compatibility частично защищена, но edge cases не покрыты

Severity: MEDIUM

Доказательства:

- `/api/products/{id}/history` защищён тестом `test_product_detail_history`: проверяет approval-only payload и отсутствие `event_type`.
- `/api/products/{id}/timeline` проверяется базово, но нет контрактных тестов для `date_from/date_to`, `source`, validation `422`, больших offset.
- Versioning endpoints проверяются в `tests/test_product_versions.py`, но без completeness metadata и timezone cases.

Минимальная рекомендация:

Добавить контрактные тесты до исправлений, чтобы показать текущие дефекты и защитить старые API.

## Finding 8 — aiosqlite compatibility patch нужен, но требует управления

Severity: MEDIUM

Доказательства:

- patch применяется при импорте `app.database` через `apply_aiosqlite_future_poll_patch()`.
- patch идемпотентен через `_marketmind_future_poll_patch`.
- `_await_future_poll()` использует polling `await asyncio.sleep(0.001)` в `app/compat/aiosqlite_patch.py:29-32`.
- Нет feature flag для отключения.
- Нет runtime feature detection, что проблема реально воспроизводится.

Риск:

Patch глобально меняет internals `aiosqlite.core.Connection` во всех средах, включая production-like запуск.

Минимальная рекомендация:

Не удалять patch без доказательств. Добавить документированный env flag/feature detection только после теста, который воспроизводит поведение без patch.

## Индексы и миграции

Текущие индексы:

- `PriceHistory.product_id`;
- `PriceHistory.recorded_at`;
- `ApprovalRecord.product_id`;
- `ApprovalRecord.created_at`;
- `ScrapeAttempt(marketplace, recorded_at)`;
- `BlockedPattern(marketplace, recorded_at)`.

Потенциально полезные composite indexes:

```text
PriceHistory(product_id, recorded_at)
ApprovalRecord(product_id, created_at)
```

Но добавлять миграцию на этапе планирования нельзя. Нужен `EXPLAIN QUERY PLAN` после фиксирующих тестов.

## Вывод

P4 реализация нужна. Наиболее опасные дефекты:

1. Timeline и Domain Events имеют параллельные правила.
2. Date filters теряют approval lifecycle events.
3. PriceHistory теряет old_value на `date_from`.
4. Pagination не корректна для больших offset.
5. Timezone сравнение удаляет `tzinfo`.

Persisted `domain_events` пока не доказан как необходимый для исправления этих дефектов.
