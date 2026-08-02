# P3.8 Timeline Engine Plan

Дата: 2026-07-17

## Статус

Документ описывает проектирование полноценного Timeline Engine. Реализация не начинается до отдельного подтверждения пользователя словом `ОДОБРЯЮ`.

Важно: на момент аудита в рабочем дереве уже присутствуют незакоммиченные изменения P3.7/P3.8 из предыдущих шагов. Этот документ не изменяет код и не откатывает эти изменения.

## Цель Timeline Engine

Timeline Engine должен стать единым источником истории товара для UI, API и будущих функций:

- Product Versioning;
- Card Editor;
- Rollback;
- Audit Trail;
- User Activity;
- AI Activity.

Timeline отвечает на вопрос:

```text
Что произошло с товаром, когда, откуда пришло событие, что было и что стало?
```

Версии товара отвечают на другой вопрос:

```text
Как выглядела карточка после выбранного события?
```

Поэтому Timeline Engine должен быть самостоятельным слоем, но не должен подменять Product Versioning.

## Текущие источники данных

### Product

Поля:

- `id`;
- `url_hash`;
- `url`;
- `name`;
- `image_url`;
- `first_seen`;
- `last_check`.

Использование в timeline:

- событие импорта товара;
- базовый контекст карточки;
- источник текущих `name` и `image_url`.

Ограничения:

- нет `description`;
- нет `brand`;
- нет `attributes`;
- нет нескольких изображений;
- нет actor/source/comment.

### PriceHistory

Поля:

- `product_id`;
- `price`;
- `availability_status`;
- `recorded_at`.

Использование в timeline:

- изменение цены;
- изменение наличия/остатка в виде статуса.

Ограничения:

- нет количественного остатка;
- нет валюты;
- нет source;
- первая запись одновременно похожа на импорт и состояние цены, поэтому требует дедупликации.

### ApprovalRecord

Поля:

- `approval_id`;
- `product_id`;
- `field`;
- `suggestion_type`;
- `before_value`;
- `after_value`;
- `reason`;
- `confidence`;
- `status`;
- `reject_reason`;
- `snapshot_before`;
- `snapshot_after`;
- `created_at`;
- `reviewed_at`;
- `applied_at`;
- `rolled_back_at`.

Использование в timeline:

- создание AI-рекомендации;
- одобрение;
- отклонение;
- применение;
- откат.

Ограничения:

- `approved` не всегда означает `applied`;
- snapshot может отсутствовать;
- `product_id` строковый;
- нет user id;
- нет общего audit metadata.

## Нужен ли отдельный модуль `app/history/` или `app/timeline/`

Рекомендация: создать отдельный пакет `app/timeline/`.

Обоснование:

1. `history` в проекте уже используется в разных смыслах: price history, import history, approval history.
2. `timeline` точнее обозначает агрегированную ленту событий из разных источников.
3. Timeline станет общей основой для версий, редактора, аудита, AI activity и user activity.
4. Отдельный пакет не смешает timeline с `app/products/`, где сейчас лежат schema/analyzer/validator.
5. В будущем в `app/timeline/` можно добавить repository, service, schemas, adapters и tests без разрастания `product_detail.py`.

Предлагаемая структура:

```text
app/timeline/
├── __init__.py
├── enums.py
├── schemas.py
├── builder.py
├── repository.py
└── service.py
```

Минимальный P3.8 вариант:

```text
app/timeline/
├── __init__.py
├── schemas.py
└── builder.py
```

Repository/service можно добавить сразу как интерфейсы, но реализацию держать простой.

## ProductHistoryBuilder

### Назначение

`ProductHistoryBuilder` превращает записи из `Product`, `PriceHistory`, `ApprovalRecord` в нормализованные `ProductHistoryEvent`.

Он не должен:

- ходить в БД напрямую;
- знать про FastAPI;
- рендерить HTML;
- применять AI-рекомендации;
- менять товар.

### Публичный API

```python
class ProductHistoryBuilder:
    def build(
        self,
        *,
        product: Product,
        price_history: list[PriceHistory],
        approval_records: list[ApprovalRecord],
        filters: ProductHistoryFilter | None = None,
        pagination: TimelinePagination | None = None,
        sort: TimelineSort = TimelineSort.NEWEST_FIRST,
    ) -> ProductTimeline:
        ...
```

Возврат:

```python
ProductTimeline(
    product_id=int,
    items=list[ProductHistoryEvent],
    pagination=TimelinePageInfo,
    warnings=list[str],
)
```

### Внутренние методы

```python
_build_import_event(product) -> list[ProductHistoryEvent]
_build_price_events(product, price_history) -> list[ProductHistoryEvent]
_build_stock_events(product, price_history) -> list[ProductHistoryEvent]
_build_ai_events(product, approval_records) -> list[ProductHistoryEvent]
_filter_events(events, filters) -> list[ProductHistoryEvent]
_sort_events(events, sort) -> list[ProductHistoryEvent]
_paginate_events(events, pagination) -> list[ProductHistoryEvent]
_deduplicate_events(events) -> list[ProductHistoryEvent]
```

### Зависимости

Builder зависит только от:

- domain/db models как input DTO;
- timeline schemas/enums;
- стандартных типов Python.

Не зависит от:

- FastAPI;
- Jinja2;
- SQLAlchemy session;
- filesystem;
- AI provider;
- Telegram.

## ProductHistoryEvent

### Обязательные поля

```text
event_id
product_id
event_type
event_type_label
source
source_label
occurred_at
status
status_label
```

### Необязательные поля

```text
field
field_label
old_value
new_value
reason
comment
confidence
actor_id
actor_label
related_entity_type
related_entity_id
metadata
```

### Enum типов событий

```text
PRODUCT_IMPORTED
PRODUCT_SYNCED
PRICE_CHANGED
STOCK_CHANGED
QUALITY_SCORE_CHANGED
AI_SUGGESTION_CREATED
AI_SUGGESTION_APPROVED
AI_SUGGESTION_REJECTED
AI_SUGGESTION_APPLIED
AI_SUGGESTION_ROLLED_BACK
MANUAL_FIELD_CHANGED
CARD_VERSION_CREATED
EXPORT_CREATED
VALIDATION_ISSUE_FOUND
VALIDATION_ISSUE_RESOLVED
```

P3.8 реально поддерживает:

```text
PRODUCT_IMPORTED
PRICE_CHANGED
STOCK_CHANGED
AI_SUGGESTION_CREATED
AI_SUGGESTION_APPROVED
AI_SUGGESTION_REJECTED
AI_SUGGESTION_APPLIED
AI_SUGGESTION_ROLLED_BACK
```

Остальные нужны для совместимости будущей архитектуры.

### Enum источников событий

```text
IMPORT
SYNC
AI
USER
SYSTEM
VALIDATION
EXPORT
ROLLBACK
UNKNOWN
```

### Статусы события

```text
RECORDED
PENDING
APPROVED
REJECTED
APPLIED
ROLLED_BACK
FAILED
SKIPPED
```

## Жизненный цикл события

### PriceHistory

```text
PriceHistory row
↓
TimelineRepository.load_price_history(product_id, filters)
↓
ProductHistoryBuilder._build_price_events()
↓
ProductHistoryEvent(type=PRICE_CHANGED)
↓
ProductTimeline
↓
API / UI / ProductVersionBuilder
```

### ApprovalRecord

```text
ApprovalRecord row
↓
TimelineRepository.load_approval_records(product_id, filters)
↓
ProductHistoryBuilder._build_ai_events()
↓
ProductHistoryEvent(type=AI_*)
↓
ProductTimeline
↓
API / UI / Versioning / Audit
```

### Product

```text
Product row
↓
TimelineRepository.load_product(product_id)
↓
ProductHistoryBuilder._build_import_event()
↓
ProductHistoryEvent(type=PRODUCT_IMPORTED)
↓
ProductTimeline
↓
API / UI
```

## Правила сортировки

Основная сортировка:

```text
occurred_at DESC
```

Для одинакового timestamp использовать стабильный порядок:

```text
occurred_at DESC,
event_priority ASC,
event_id ASC
```

Priority:

| Event type | Priority |
|---|---:|
| `AI_SUGGESTION_ROLLED_BACK` | 10 |
| `AI_SUGGESTION_APPLIED` | 20 |
| `AI_SUGGESTION_APPROVED` | 30 |
| `AI_SUGGESTION_REJECTED` | 30 |
| `AI_SUGGESTION_CREATED` | 40 |
| `PRICE_CHANGED` | 50 |
| `STOCK_CHANGED` | 60 |
| `QUALITY_SCORE_CHANGED` | 70 |
| `MANUAL_FIELD_CHANGED` | 80 |
| `PRODUCT_IMPORTED` | 90 |
| unknown | 100 |

Обоснование:

- действия пользователя и rollback важнее пассивных событий;
- AI lifecycle должен идти логически выше price/stock, если timestamp совпал;
- импорт в одинаковый timestamp должен быть ниже, чтобы не маскировать конкретное изменение.

## Правила дедупликации

### Импорт

Импорт создаётся один раз:

```text
event_id = product:{product.id}:import
```

Первая запись `PriceHistory` не должна создавать отдельное событие `PRICE_CHANGED`, если она совпадает с `Product.first_seen` и является начальным состоянием товара.

### Цена и наличие

Для последовательных `PriceHistory`:

- если изменилась только цена — одно событие `PRICE_CHANGED`;
- если изменилось только наличие — одно событие `STOCK_CHANGED`;
- если одновременно изменились цена и наличие — два разных события.

Event IDs:

```text
price:{price_history.id}:price
price:{price_history.id}:stock
```

### AI

AI lifecycle не схлопывается в одно событие:

```text
approval:{approval_id}:created
approval:{approval_id}:approved
approval:{approval_id}:rejected
approval:{approval_id}:applied
approval:{approval_id}:rolled_back
```

Но builder не должен создавать:

- approve/reject без `reviewed_at`;
- apply без `applied_at`;
- rollback без `rolled_back_at`;
- approve и reject одновременно, если статус один.

### Общая дедупликация

После сборки применить уникальность по `event_id`.

Если обнаружены два события с одинаковым `event_id`, оставить первое и добавить warning в `ProductTimeline.warnings`.

## API

Предлагаемый endpoint:

```text
GET /api/products/{id}/timeline
```

Параметры:

```text
limit=50
offset=0
event_type=all|import|price|stock|ai|decision|manual|quality|system
source=all|import|sync|ai|user|system|validation
date_from=<ISO datetime>
date_to=<ISO datetime>
sort=newest_first|oldest_first
```

Ограничения:

```text
default limit = 50
max limit = 200
default sort = newest_first
```

Ответ:

```json
{
  "product_id": 123,
  "items": [],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "next_offset": null,
    "total_returned": 0,
    "has_more": false,
    "sort": "newest_first"
  },
  "warnings": []
}
```

Старый endpoint `GET /api/products/{id}/history` не менять, если он уже используется как approval-only история.

## Производительность

### 100 событий

Подход:

- 1 запрос к `Product`;
- 1 запрос к `PriceHistory`;
- 1 запрос к `ApprovalRecord`;
- сборка и сортировка в памяти.

Это безопасно.

### 1 000 событий

Подход остаётся рабочим, но обязательно:

- `limit`;
- `offset`;
- фильтрация по датам в SQL;
- не рендерить все события в HTML.

Риск:

- Python sorting допустим;
- HTML может стать тяжёлым.

### 10 000 событий

Требуется:

- SQL filtering;
- ограниченные окна выборки;
- composite indexes;
- lazy loading в UI;
- отдельная repository-функция для каждого источника.

Offset ещё допустим, но может замедляться на больших смещениях.

### 100 000 событий

Нельзя строить timeline целиком в памяти.

Нужно:

- cursor pagination;
- persisted `event_history` или materialized timeline;
- индексы по `(product_id, occurred_at)`;
- фоновая нормализация событий;
- кеширование последних страниц timeline;
- возможно отдельная таблица `timeline_events`.

## Индексы

Сейчас есть:

- `PriceHistory.product_id`;
- `PriceHistory.recorded_at`;
- `ApprovalRecord.product_id`;
- `ApprovalRecord.created_at`;
- `Product.url_hash`.

Желательные индексы:

```text
PriceHistory(product_id, recorded_at)
ApprovalRecord(product_id, created_at)
```

Если появится persisted timeline:

```text
TimelineEvent(product_id, occurred_at)
TimelineEvent(product_id, event_type, occurred_at)
TimelineEvent(product_id, source, occurred_at)
TimelineEvent(related_entity_type, related_entity_id)
```

## Lazy loading

UI должен загружать timeline частями:

1. На странице товара показывать первые 50 событий.
2. Кнопка `Показать ещё`.
3. HTMX-запрос с `offset`.
4. Не строить графики/таблицы по всей истории без явного действия пользователя.

## Кеширование

На P3.8 кеширование не обязательно.

Когда появятся большие истории:

- кешировать первую страницу timeline на короткое время;
- инвалидировать при новом `PriceHistory` или `ApprovalRecord`;
- не кешировать per-user данные, пока нет user activity и permissions.

## Будущая совместимость

### Product Versioning

Timeline должен отдавать стабильные `event_id`, `event_type`, `old_value`, `new_value`, `occurred_at`.

Version Builder сможет строить версии из событий:

```text
Timeline Event → ProductVersion
```

### Card Editor

Редактор должен создавать события:

```text
MANUAL_FIELD_CHANGED
```

Для этого уже сейчас нужно предусмотреть:

- `actor_id`;
- `actor_label`;
- `comment`;
- `field`;
- `old_value`;
- `new_value`.

### Rollback

Rollback должен ссылаться на исходное событие:

```text
related_entity_type = "approval"
related_entity_id = approval_id
```

Для будущего rollback к версии нужен `timeline_event_ids`.

### Audit Trail

Timeline read-model не является полноценным audit trail, пока события собираются из разных таблиц.

Для строгого аудита позже нужна persisted immutable table.

### User Activity

Нужно предусмотреть source `USER` и поля actor.

### AI Activity

AI-события должны различать:

- suggestion created;
- approved;
- rejected;
- applied;
- rolled back.

Нельзя считать AI suggestion фактическим изменением карточки.

## Timeline Service

Нужен, но можно вводить поэтапно.

Рекомендуемая ответственность:

```text
TimelineService
- validate filters
- call repository
- call builder
- apply pagination
- return ProductTimeline
```

На первом шаге часть этой логики может жить в route helper, но целевое состояние — service layer.

## Repository слой

Repository слой желателен.

Причины:

- убрать SQL из route;
- централизовать фильтрацию по датам;
- подготовиться к persisted `timeline_events`;
- упростить тестирование builder отдельно от БД.

Минимальный интерфейс:

```python
class TimelineRepository:
    async def get_product(product_id: int) -> Product | None: ...
    async def get_price_history(product_id: int, filters) -> list[PriceHistory]: ...
    async def get_approval_records(product_id: int, filters) -> list[ApprovalRecord]: ...
```

На P3.8 можно начать без repository, но если Timeline должен стать фундаментом для Versioning и Audit, repository лучше заложить сразу.

## Предполагаемые изменения файлов после `ОДОБРЯЮ`

Минимальная архитектурная реализация:

```text
app/timeline/__init__.py
app/timeline/enums.py
app/timeline/schemas.py
app/timeline/builder.py
app/timeline/repository.py
app/timeline/service.py
app/web/routes/product_detail.py
app/web/templates/product_history.html
tests/test_timeline_engine.py
docs/P3_8_TIMELINE_ENGINE_REPORT.md
```

Если сохранять текущий малый scope:

```text
app/products/history.py
app/web/routes/product_detail.py
app/web/templates/product_history.html
tests/test_product_detail.py
docs/P3_8_TIMELINE_ENGINE_REPORT.md
```

Рекомендация: выбрать `app/timeline/`, потому что Timeline должен стать основой для нескольких подсистем, а не только detail page.

## Риски

1. Если оставить timeline внутри `product_detail.py`, route станет слишком тяжёлым.
2. Если сразу добавить persisted `timeline_events`, появится миграция и риск дублирования.
3. Если не сохранить старый `/history` контракт, можно сломать существующих потребителей.
4. Если не добавить pagination, большие истории будут тормозить.
5. Если не различать `approved` и `applied`, Versioning будет строить ложные версии.
6. Если не предусмотреть actor/source сейчас, Card Editor и Audit Trail придётся переделывать.

## Ответы на ключевые вопросы

### Готов ли Timeline стать основой для Versioning?

Да, если:

- события имеют стабильный `event_id`;
- есть `event_type`, `source`, `occurred_at`, `old_value`, `new_value`;
- AI approved не считается изменением без applied;
- import/price/stock/rollback не дублируются.

Ограничение: без snapshots Timeline не восстановит полную старую карточку.

### Какие ограничения останутся?

- нет исторических description/brand/attributes;
- нет quantity stock;
- нет user actor;
- нет persisted immutable audit table;
- Quality Score не сохраняется во времени.

### Нужен ли отдельный Timeline Service?

Да, целевым состоянием должен быть `TimelineService`. На первом шаге можно сделать builder + route helpers, но для Versioning/Card Editor/Audit лучше выделить service.

### Нужен ли Repository слой?

Да, если Timeline Engine становится фундаментом продукта. Repository отделит SQL от builder/service и позволит позже заменить derived timeline на persisted timeline.

### Можно ли переходить к реализации?

Да, после подтверждения пользователя. Рекомендуемый первый implementation scope:

1. Создать `app/timeline/`.
2. Перенести/оформить `ProductHistoryEvent` и `ProductHistoryBuilder`.
3. Добавить repository/service без миграции.
4. Сохранить `/api/products/{id}/history` без изменения.
5. Добавить/закрепить `/api/products/{id}/timeline`.
6. Покрыть tests: sorting, deduplication, filters, pagination, same timestamp order.
