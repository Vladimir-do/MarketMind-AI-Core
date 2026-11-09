# P3.8 Domain Event Platform Plan

Дата: 2026-07-17

## Статус документа

Это документ аудита и проектирования. Код проекта, схема БД, маршруты и тесты на этом этапе не изменяются.

Фактическое состояние рабочего дерева во время аудита: в `git status` присутствуют незакоммиченные файлы P3.7/P3.8 Timeline/Versioning. Это не блокирует проектирование Domain Events, но перед реализацией нужно создать контрольную точку или явно подтвердить состав незакоммиченных изменений.

## Цель

Спроектировать единую платформу Domain Events, чтобы история товара была не отдельной функцией, а одним из потребителей общего событийного слоя.

Платформа должна в будущем поддержать:

- Timeline;
- Product Versioning;
- Card Editor;
- Rollback;
- Audit Trail;
- User Activity;
- AI Activity;
- Notifications;
- Background Jobs;
- Analytics.

## Что найдено в текущей системе

Сейчас проект уже имеет несколько источников событий, но они не представлены единым интерфейсом:

- `Product` фиксирует появление товара через `first_seen` и обновление через `last_check`.
- `PriceHistory` фиксирует изменения цены и статуса наличия.
- `ApprovalRecord` фиксирует жизненный цикл AI-предложения: создание, одобрение, отклонение, применение, откат.
- `ScrapeAttempt` и `BlockedPattern` фиксируют события парсинга, ошибок, блокировок и стратегий.
- `Subscriber` фиксирует подписчиков уведомлений.
- `ProductHistoryBuilder` уже преобразует `Product`, `PriceHistory`, `ApprovalRecord` в read-only timeline events.
- `ProductVersionBuilder` уже строит версии карточки на основе timeline events.
- Worker и web routes выполняют действия, которые логически являются domain events, но пока не публикуют их явно.

## Категории существующих событий

### Product Events

| Событие | Текущий источник | Комментарий |
|---|---|---|
| `product.imported` | `Product.first_seen` | Товар впервые сохранён |
| `product.checked` | `Product.last_check` | Товар проверен или обновлён |
| `product.price_changed` | `PriceHistory.price` | Восстанавливается сравнением соседних записей |
| `product.stock_changed` | `PriceHistory.availability_status` | Сейчас есть только статус, не количественный остаток |
| `product.image_changed` | `Product.image_url` | Явной истории пока нет |
| `product.field_changed` | отсутствует | Понадобится для Card Editor |
| `product.quality_score_changed` | вычисляется динамически | Исторический снимок пока не сохраняется |

### AI Events

| Событие | Текущий источник | Комментарий |
|---|---|---|
| `ai.suggestion_created` | `ApprovalRecord.created_at` | Есть field, before/after, confidence, reason |
| `ai.response_parsed` | AI layer logs/tests | Не хранится как persisted event |
| `ai.provider_failed` | logs | Нужен позже для диагностики и стоимости AI |
| `ai.batch_completed` | AI recommendation layer | Сейчас агрегируется в runtime objects |

### Approval Events

| Событие | Текущий источник | Комментарий |
|---|---|---|
| `approval.created` | `ApprovalRecord.created_at` | Создание предложения на проверку |
| `approval.approved` | `ApprovalRecord.reviewed_at`, `status=approved` | Решение пользователя |
| `approval.rejected` | `ApprovalRecord.reviewed_at`, `status=rejected` | Есть `reject_reason` |
| `approval.applied` | `ApprovalRecord.applied_at` | Применение к объекту |
| `approval.rolled_back` | `ApprovalRecord.rolled_back_at` | Откат по snapshot |

### Parser Events

| Событие | Текущий источник | Комментарий |
|---|---|---|
| `parser.fetch_started` | worker/updater runtime | Не хранится как event |
| `parser.fetch_succeeded` | `ScrapeAttempt.success` | Есть latency, status, parser |
| `parser.fetch_failed` | `ScrapeAttempt.error_class/error_text` | Есть диагностика ошибки |
| `parser.block_detected` | `BlockedPattern` | Есть marketplace, trigger, strategy |
| `parser.strategy_skipped` | `BlockedPattern.status=skipped` | Используется adaptive skip |

### System Events

| Событие | Текущий источник | Комментарий |
|---|---|---|
| `notification.subscribed` | `Subscriber.created_at` | Подписка пользователя |
| `notification.unsubscribed` | delete `Subscriber` | История удаления не хранится |
| `job.started` | worker runtime | Нет единой таблицы jobs |
| `job.completed` | worker runtime | Нет persisted status |
| `job.failed` | logs / error research | Нужно для Background Jobs |
| `export.created` | export routes/files | Нужен позже для Audit Trail |

## Единый интерфейс DomainEvent

Рекомендуемая доменная модель:

```python
@dataclass(frozen=True)
class DomainEvent:
    event_id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    source: str
    actor: EventActor | None
    occurred_at: datetime
    payload: dict[str, Any]
    metadata: dict[str, Any]
    version: int
```

### Поля

| Поле | Обязательность | Назначение |
|---|---|---|
| `event_id` | обязательно | Стабильный id события для дедупликации, idempotency, ссылок из Timeline/Versioning |
| `aggregate_type` | обязательно | Тип сущности: `product`, `approval`, `parser_attempt`, `job`, `user` |
| `aggregate_id` | обязательно | Id конкретной сущности, вокруг которой произошло событие |
| `event_type` | обязательно | Machine-readable тип: `product.price_changed`, `approval.approved` |
| `source` | обязательно | Источник: `import`, `parser`, `ai`, `user`, `system`, `worker`, `api` |
| `actor` | опционально | Кто инициировал событие: пользователь, AI, worker, system |
| `occurred_at` | обязательно | Время фактического события, а не время чтения из БД |
| `payload` | обязательно | Доменная полезная нагрузка: old/new values, field, reason, confidence |
| `metadata` | обязательно | Технический контекст: correlation_id, request_id, parser, provider, warnings |
| `version` | обязательно | Версия схемы события для долгосрочной совместимости |

### EventActor

```python
@dataclass(frozen=True)
class EventActor:
    actor_type: str  # user | ai | worker | system | parser
    actor_id: str | None
    display_name: str | None
```

`actor` нельзя смешивать с `source`: source отвечает за канал происхождения, actor отвечает за инициатора.

## Жизненный цикл события

Базовый жизненный цикл:

```text
Action / Source table
        ↓
EventBuilder
        ↓
DomainEvent
        ↓
EventRepository or read-model stream
        ↓
EventReader
        ↓
Consumers
```

Пример для парсинга:

```text
Parser
↓
Database.save_product()
↓
product.price_changed / product.stock_changed
↓
Timeline
↓
ProductVersionBuilder
↓
Notification
↓
Analytics
```

Пример для AI approval:

```text
AIRecommendationEngine
↓
DatabaseApprovalQueue.add()
↓
ai.suggestion_created
↓
User approve/reject
↓
approval.approved / approval.rejected
↓
Timeline
↓
Version Builder
↓
Audit Trail
```

## Версионирование событий

Рекомендация: каждое событие должно иметь `version` или `schema_version`.

Минимальные правила:

1. `event_type` не менять задним числом.
2. Новые поля добавлять только как optional.
3. Удаление или переименование поля требует новой версии события.
4. Consumers должны игнорировать неизвестные поля в `payload` и `metadata`.
5. Для persisted events нужна функция upcast:

```text
DomainEvent v1
↓
EventUpcaster
↓
DomainEvent текущей версии
```

Для P3.8 достаточно `version=1` в проектном контракте. Реальный upcaster понадобится при появлении persisted `domain_events`.

## Сериализация

### Рекомендация для MVP

Использовать JSON.

Причины:

- уже используется в `ApprovalRecord.metadata_json`, `snapshot_before`, `snapshot_after`;
- читаем человеком при отладке SQLite;
- переносим между Linux/Windows;
- хорошо подходит для API и отчётов;
- не требует новых зависимостей.

### MessagePack

Не рекомендуется сейчас.

Плюсы:

- компактнее JSON;
- быстрее на больших объёмах.

Минусы:

- хуже ручная диагностика;
- новая зависимость;
- не нужна для текущего масштаба.

### SQLite

SQLite остаётся storage engine для текущего проекта. Для persisted events можно хранить:

```text
event_id TEXT PRIMARY KEY
aggregate_type TEXT NOT NULL
aggregate_id TEXT NOT NULL
event_type TEXT NOT NULL
source TEXT NOT NULL
actor_type TEXT
actor_id TEXT
occurred_at DATETIME NOT NULL
payload_json TEXT NOT NULL
metadata_json TEXT NOT NULL
schema_version INTEGER NOT NULL
created_at DATETIME NOT NULL
```

JSON хранится в `TEXT`, потому что это совместимо с текущей SQLAlchemy/SQLite моделью и не требует завязки на PostgreSQL JSONB.

## Место в архитектуре

Рекомендуемый путь:

```text
app/domain/events/
```

Обоснование:

- события описывают бизнес-факты, а не инфраструктуру;
- ими будут пользоваться UI, worker, analytics, notifications и AI;
- `app/core/events/` звучит как технический event bus, а нам нужен доменный контракт;
- `app/timeline/` слишком узкий слой, timeline должен быть consumer, а не владелец событий.

Предлагаемая структура на этапе реализации:

```text
app/domain/events/
    __init__.py
    models.py          # DomainEvent, EventActor, enums
    builders.py        # builders from Product, PriceHistory, ApprovalRecord
    serializer.py      # JSON serialization/deserialization
    reader.py          # read-model event streams
    repository.py      # persisted storage позже, не обязательно сразу
    publisher.py       # sync in-process publisher позже
```

Timeline остаётся в:

```text
app/timeline/
```

Но должен читать `DomainEvent`, а не напрямую владеть всеми доменными событиями.

## Интерфейсы

### EventBuilder

Назначение: превращать существующие модели или действия в `DomainEvent`.

```python
class EventBuilder(Protocol):
    def build(self, source: object) -> list[DomainEvent]: ...
```

Практические builder'ы:

- `ProductEventBuilder`;
- `PriceHistoryEventBuilder`;
- `ApprovalEventBuilder`;
- `ParserEventBuilder`;
- `SystemEventBuilder`.

### EventRepository

Назначение: хранить и читать persisted events, когда появится таблица `domain_events`.

```python
class EventRepository(Protocol):
    async def append(self, event: DomainEvent) -> None: ...

    async def append_many(self, events: list[DomainEvent]) -> None: ...

    async def list_by_aggregate(
        self,
        aggregate_type: str,
        aggregate_id: str,
        *,
        limit: int,
        offset: int,
    ) -> list[DomainEvent]: ...
```

На первом этапе repository может быть read-only adapter над существующими таблицами.

### EventSerializer

Назначение: стабильная JSON-сериализация.

```python
class EventSerializer(Protocol):
    def dumps(self, event: DomainEvent) -> str: ...

    def loads(self, raw: str) -> DomainEvent: ...
```

Правила:

- datetime в ISO 8601;
- `payload` и `metadata` только JSON-compatible;
- неизвестные поля не должны ломать чтение;
- секреты и токены не допускаются в payload/metadata.

### EventPublisher

Назначение: доставлять событие consumers.

```python
class EventPublisher(Protocol):
    async def publish(self, event: DomainEvent) -> None: ...

    async def publish_many(self, events: list[DomainEvent]) -> None: ...
```

MVP-вариант: in-process publisher без очереди.

Будущий вариант: publisher может отправлять события в background jobs, notifications, analytics.

### EventReader

Назначение: собирать поток событий для потребителей.

```python
class EventReader(Protocol):
    async def stream_for_product(
        self,
        product_id: int,
        *,
        limit: int,
        offset: int,
        event_type: str | None = None,
    ) -> list[DomainEvent]: ...
```

Для P3.8/P3.9 `EventReader` может читать `Product`, `PriceHistory`, `ApprovalRecord` и строить events on demand.

## Нужна ли отдельная таблица DomainEvents

Короткий ответ: не сразу.

### Сейчас можно работать через read-model

Для Timeline и текущего Product Versioning достаточно read-model:

```text
Product + PriceHistory + ApprovalRecord
↓
EventBuilder
↓
DomainEvent[]
↓
Timeline / Versioning
```

Плюсы:

- нет миграции;
- нет дублирования `PriceHistory` и `ApprovalRecord`;
- меньше риск рассинхронизации;
- проще сохранить текущие тесты.

### Когда таблица действительно понадобится

Persisted `domain_events` нужна, когда появятся:

- Card Editor с ручными изменениями;
- неизменяемый audit trail;
- user activity;
- notifications с гарантией доставки;
- background jobs с outbox-паттерном;
- rollback не только AI approval, но любой правки;
- требования «кто, когда и почему изменил поле»;
- внешняя интеграция, где событие нужно отправить ровно один раз.

### Риск раннего добавления таблицы

Если добавить `domain_events` сейчас без write-side дисциплины, появятся:

- дубли цены в `PriceHistory` и `domain_events`;
- дубли approvals в `ApprovalRecord` и `domain_events`;
- вопросы backfill старых данных;
- сложность синхронизации при rollback;
- риск, что Timeline начнёт читать часть событий из одной таблицы, часть из другой.

Рекомендация: сначала ввести доменный контракт и builders, затем persisted table только для новых write-side действий.

## Как избежать дублирования данных

Правила:

1. События, которые уже имеют authoritative source table, не копировать в persisted events на первом этапе.
2. Read-model events должны иметь deterministic `event_id`.
3. Persisted events должны хранить только факты, для которых нет другого устойчивого источника, или события outbox/audit.
4. Если позже выполняется backfill, событие должно иметь `metadata.origin = "backfill"`.
5. Timeline должен объединять источники через `EventReader`, а не напрямую смешивать SQL-запросы в UI.
6. Нельзя использовать event table как кэш без стратегии invalidation.

## Отношение к текущему Timeline Engine

Текущий `ProductHistoryEvent` является UI/read-model событием, а не универсальным domain event.

Разделение:

```text
DomainEvent
    ↓
TimelineEventMapper
    ↓
ProductHistoryEvent
```

`ProductHistoryEvent` может содержать русские labels и UI-friendly поля.

`DomainEvent` должен оставаться machine-readable и стабильным:

- без русских labels в базовом контракте;
- без HTML/UI полей;
- с versioned payload;
- с actor/source/correlation metadata.

## Будущие сценарии использования

### Timeline

Timeline читает события через `EventReader`, мапит их в `ProductHistoryEvent`, применяет фильтры, сортировку и пагинацию.

### Product Versioning

Version Builder получает доменные события карточки и строит версии:

- import;
- price changed;
- stock changed;
- manual field changed;
- AI applied;
- rollback.

### Card Editor

Каждое сохранение поля создаёт `product.field_changed`:

```json
{
  "field": "description",
  "old_value": "старый текст",
  "new_value": "новый текст",
  "reason": "ручное редактирование"
}
```

### Rollback

Rollback создаёт отдельное событие:

```text
product.field_rolled_back
```

Оно должно ссылаться на исходное событие через `metadata.related_event_id`.

### Audit Trail

Audit Trail читает persisted `domain_events`, фильтрует по actor, source, aggregate, event_type.

### User Activity

User Activity строится по `actor.actor_type=user` и `actor.actor_id`.

### AI Activity

AI Activity строится по `source=ai` и AI-specific metadata:

- provider;
- model;
- confidence;
- cost;
- prompt/version;
- result count.

### Notifications

Notification worker подписывается на event types:

- `product.price_changed`;
- `product.stock_changed`;
- `approval.created`;
- `job.failed`;
- `parser.block_detected`.

### Background Jobs

Jobs публикуют:

- `job.started`;
- `job.progress`;
- `job.completed`;
- `job.failed`.

## Дорожная карта

### P3.9 — Domain Event Contracts

Цель: ввести модели и builders без изменения БД.

Файлы:

- `app/domain/events/models.py`;
- `app/domain/events/builders.py`;
- `app/domain/events/serializer.py`;
- tests для deterministic event_id, JSON serialization, builders.

Критерий:

- Timeline может строиться через domain event adapters;
- старый timeline API не меняется;
- новая таблица не добавлена.

### P4 — Card Editor + Persisted Manual Events

Цель: ручные изменения карточки должны создавать persisted domain events.

Файлы:

- routes/editor;
- forms/templates;
- `domain_events` migration;
- `EventRepository`.

Критерий:

- каждое ручное изменение имеет actor, old/new values, reason;
- можно показать его в Timeline и Versioning;
- AI ничего не применяет без подтверждения.

### P5 — Notifications, Jobs, Audit

Цель: consumers используют domain events.

Файлы:

- notification consumer;
- job event publisher;
- audit views;
- analytics event projections.

Критерий:

- notification не зависит напрямую от `PriceHistory` или `ApprovalRecord`;
- jobs имеют статусы на основе событий;
- audit trail читает persisted events.

## Риски

1. Слишком раннее введение event table приведёт к дублированию и рассинхронизации.
2. Слишком позднее введение event table усложнит Card Editor и Audit Trail.
3. Если смешать DomainEvent и UI TimelineEvent, контракт быстро станет нестабильным.
4. Без schema version старые события будет трудно читать через год развития.
5. Без deterministic `event_id` будет сложно дедуплицировать read-model events.
6. Без actor/correlation metadata нельзя будет построить качественный audit trail.
7. Без запрета секретов в payload можно случайно сохранить токены/API keys.
8. Нынешнее рабочее дерево не чистое; перед реализацией нужно зафиксировать или явно принять текущие изменения P3.7/P3.8.

## Рекомендуемая архитектурная схема

```text
Product / PriceHistory / ApprovalRecord / ScrapeAttempt / Worker Actions
        ↓
Domain Event Builders
        ↓
DomainEvent
        ↓
EventReader / EventPublisher
        ↓
Consumers
        ├─ Timeline
        ├─ Product Versioning
        ├─ Rollback
        ├─ Audit Trail
        ├─ User Activity
        ├─ AI Activity
        ├─ Notifications
        └─ Background Jobs / Analytics
```

## Итоговая рекомендация

1. Создать `app/domain/events/` как отдельный доменный слой, но только после подтверждения реализации.
2. На первом шаге не добавлять таблицу `domain_events`.
3. Ввести `DomainEvent`, `EventActor`, serializer и builders как read-model adapters.
4. Оставить `ProductHistoryEvent` UI-моделью Timeline, а не превращать её в универсальное событие.
5. Persisted `domain_events` добавить позже, когда появится Card Editor, ручные изменения и audit trail.
6. Перед реализацией привести рабочее дерево к явной контрольной точке, потому что сейчас есть незакоммиченные P3.7/P3.8 изменения.

## Можно ли переходить к реализации

Да, но только после отдельного подтверждения `ОДОБРЯЮ` и после решения по текущему незакоммиченному состоянию рабочего дерева.

Безопасный первый implementation step:

```text
P3.9 — Domain Event Contracts, без миграции БД
```

Он должен добавить только модели, serializer, builders и тесты, не меняя публичные API и схему БД.
