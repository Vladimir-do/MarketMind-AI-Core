# P5 Card Editor Implementation Plan

## Рекомендуемая модель данных

P5 должен разделить marketplace source data и editable overlay:

```text
Marketplace source snapshot
        +
User editable overlay
        =
Effective product card
```

Старый `Product` остается source identity моделью. Его нельзя резко превращать в полноценную карточку, потому что парсинг/импорт продолжит обновлять `Product.name`, `Product.image_url`, `PriceHistory`.

## Каноническая editable card

| Поле | Тип | Обязательность | Max | Нормализация | Валидация | Редактируемо | Источник текущего значения | Quality Score |
|---|---|---:|---:|---|---|---:|---|---:|
| `title` | string | да | 255 | trim, collapse spaces | не пусто, без запрещенных слов | да | `Product.name` + overlay | да |
| `description` | string | нет | 5000 | trim, normalize newlines | длина, запрещенные утверждения | да | overlay | да |
| `brand` | string | нет | 120 | trim | printable text | да | overlay/import attrs | да |
| `price` | integer/null | нет | n/a | int >= 0 | >= 0 | да | latest `PriceHistory.price` + overlay | да |
| `availability` | enum | нет | n/a | known enum | `in_stock/out_of_stock/deleted/blocked/unknown` | да | latest `PriceHistory.availability_status` + overlay | да |
| `image_urls` | list[string] | нет | 50 urls | dedupe, trim | URL-like, no secret params | да | `Product.image_url` + overlay | да |
| `attributes` | object[string,string] | нет | 200 keys | trim keys/values | key/value length | да | overlay/import | да |
| `marketplace` | string | да | 64 | lower enum | known marketplace or `unknown` | нет MVP | URL detector | нет |
| `external_product_id` | string/null | нет | 128 | trim | safe string | нет MVP | parser/import | нет |

Не добавлять фиктивные значения в старые derived versions.

## Таблицы и миграции

### `product_card_drafts`

```text
draft_id TEXT primary key
product_id INTEGER not null references products(id)
base_version_id TEXT null
status VARCHAR(32) not null
payload_json TEXT not null
validation_json TEXT null
created_by TEXT null
created_at DATETIME not null
updated_at DATETIME not null
revision INTEGER not null
comment TEXT null
```

Индексы:

- `(product_id, status, updated_at)`;
- unique active draft optional только если MVP решит "один draft на товар".

Статусы:

- `draft`;
- `ready_for_review`;
- `applied`;
- `discarded`;
- `conflicted`.

Рекомендация MVP: разрешить несколько черновиков, но UI по умолчанию показывает последний active draft. Это снижает риск потери работы пользователя.

### `product_card_versions`

```text
version_id TEXT primary key
product_id INTEGER not null references products(id)
version_number INTEGER not null
snapshot_json TEXT not null
snapshot_schema_version INTEGER not null
source VARCHAR(32) not null
actor_type VARCHAR(32) not null
actor_id TEXT null
comment TEXT null
created_at DATETIME not null
base_version_id TEXT null
trigger_event_id TEXT null
checksum VARCHAR(64) not null
```

Constraints:

- unique `(product_id, version_number)`;
- unique `(product_id, checksum)` только если нужно запрещать duplicate snapshot полностью. Рекомендация: не делать strict unique на checksum в MVP, а проверять в service, потому что rollback к одинаковому snapshot может быть осмысленным событием.

Индексы:

- `(product_id, version_number)`;
- `(product_id, created_at)`;
- `(trigger_event_id)`.

### `domain_event_records`

Только для новых невосстановимых событий:

```text
event_id TEXT primary key
aggregate_type VARCHAR(64) not null
aggregate_id TEXT not null
event_type VARCHAR(128) not null
source VARCHAR(32) not null
actor_type VARCHAR(32) not null
actor_id TEXT null
occurred_at DATETIME not null
payload_json TEXT not null
metadata_json TEXT not null
schema_version INTEGER not null
correlation_id TEXT null
causation_id TEXT null
created_at DATETIME not null
```

Индексы:

- `(aggregate_type, aggregate_id, occurred_at)`;
- `(event_type, occurred_at)`;
- `(correlation_id)`.

Правила:

- `event_id` deterministic/idempotent для retry;
- payload max 64 KB на MVP;
- serializer запрещает secret/token/password keys;
- schema version обязательна;
- запись events, version и draft status происходит в одной транзакции.

### Transactional outbox

Не добавлять в MVP P5. Нужен позже для notifications/background jobs. DomainEvent table уже даст базу для outbox.

## Draft lifecycle

```text
create draft
  -> patch draft
  -> validate
  -> ready_for_review
  -> apply transaction
  -> applied
```

Удаление:

- API `DELETE` помечает `discarded`, физически не удаляет.

Autosave:

- не включать в первый P5 UI без throttling.

Срок жизни:

- не удалять автоматически в MVP.

Кто применяет:

- до auth слоя: actor `local_user`;
- после auth: текущий пользователь.

## Version lifecycle

```text
effective card
  -> canonical JSON snapshot
  -> checksum
  -> ProductCardVersion complete snapshot
```

Правила:

- snapshot immutable;
- `version_number = max(product_id) + 1` внутри transaction;
- old derived versions остаются доступными;
- new persisted versions имеют `is_derived=false`, `snapshot_completeness=complete`;
- duplicate snapshot без причины не создает новую version.

## Domain Event lifecycle

```text
Draft action / Apply / Rollback
        |
        v
DomainEvent
        |
        v
DomainEventRecord
        |
        v
Unified EventReader
        |
        v
Timeline / Versioning / Audit
```

Legacy source adapters остаются:

- Product;
- PriceHistory;
- ApprovalRecord.

Persisted DomainEventRepository добавляется только для новых editor/manual/rollback actions.

## Unified EventReader

Новая архитектура чтения:

```text
Legacy source adapters
        +
Persisted DomainEventRepository
        |
        v
UnifiedEventReader
        |
        v
TimelineEventMapper
        |
        v
ProductHistoryEvent[]
```

`ProductHistoryBuilder` не удалять. Его можно расширить зависимостью на persisted events или оставить как orchestrator.

## Transaction boundary

Apply draft должен быть атомарным:

```text
validate draft
check base version
build effective snapshot
create ProductCardVersion
create DomainEventRecord
mark draft applied
commit
```

Если любой шаг падает, rollback всей transaction.

## Optimistic locking

MVP механизм:

- `base_version_id` на draft;
- `revision` на draft;
- `If-Match` позже для API clients.

При apply:

- получить latest persisted version или latest derived version id;
- сравнить с `draft.base_version_id`;
- если не совпадает, вернуть `409 Conflict`.

Response 409:

```json
{
  "detail": "Карточка была изменена после создания черновика",
  "conflict": {
    "base_version_id": "...",
    "current_version_id": "...",
    "diff": []
  }
}
```

## Rollback

Rollback не удаляет версии.

Поток:

```text
select target version
check current version
create new snapshot equal to target snapshot
create event product.version_rolled_back
create new ProductCardVersion
commit
```

Rollback требует reason/comment и actor.

## AI

AI может:

- создать proposal;
- заполнить draft;
- показать diff;
- объяснить изменение.

AI не может:

- применить draft;
- rollback;
- менять persisted version;
- скрывать actor пользователя.

## Audit Trail

Audit читает DomainEventRecord + legacy events.

Поля:

- actor;
- occurred_at;
- event_type;
- product_id;
- old/new;
- comment;
- correlation_id;
- result status.

IP/user-agent не хранить в MVP, потому что нет политики хранения персональных данных.

## API

### Drafts

`POST /api/products/{id}/drafts`

Request:

```json
{
  "base_version_id": "version:1:0003",
  "payload": {},
  "comment": "Комментарий"
}
```

Response: `201`, draft object.

`GET /api/products/{id}/drafts`

- `limit`, `offset`, `status`;
- `200`.

`GET /api/products/{id}/drafts/{draft_id}`

- `200`;
- `404`.

`PATCH /api/products/{id}/drafts/{draft_id}`

- request `payload`, `revision`, `comment`;
- `200`;
- `409` если revision устарел.

`DELETE /api/products/{id}/drafts/{draft_id}`

- soft discard;
- `204` или `200`.

`POST /api/products/{id}/drafts/{draft_id}/validate`

- `200` with validation result;
- `422` invalid payload.

`POST /api/products/{id}/drafts/{draft_id}/apply`

- request `revision`, `comment`;
- `200` with new version;
- `409` conflict;
- `422` validation errors.

### Persisted versions

Existing endpoints stay:

- `GET /api/products/{id}/versions`;
- `GET /api/products/{id}/versions/{version}`;
- `GET /api/products/{id}/compare`.

Add:

`POST /api/products/{id}/versions/{version}/rollback`

Request:

```json
{
  "current_version_id": "...",
  "reason": "Причина отката"
}
```

Response:

- `200` new version;
- `409` conflict;
- `404` version not found.

### Audit

`GET /api/products/{id}/audit`

Parameters:

- `limit` default 50 max 200;
- `cursor` preferred;
- `event_type`;
- `date_from`;
- `date_to`;
- `actor`.

## UI

Screens:

- `/products/{id}/edit`;
- `/products/{id}/drafts`;
- `/products/{id}/versions`;
- `/products/{id}/compare`;
- `/products/{id}/audit`.

Editor UI must show:

- исходное значение маркетплейса;
- текущее effective значение;
- новое значение черновика;
- AI-предложение отдельно;
- diff;
- Quality Score до/после;
- ошибки валидации;
- конфликт версии;
- кнопки «Сохранить черновик», «Отправить на проверку», «Применить».

Не использовать кнопку «Сохранить», которая сразу меняет карточку.

## CSRF и auth

Текущий Web UI не имеет session auth. Поэтому есть два безопасных варианта:

1. MVP API-only apply endpoints с явным confirmation payload.
2. Перед HTML forms добавить session middleware + CSRF token.

Рекомендация: для P5 UI добавить минимальный CSRF helper только для mutating HTML forms/HTMX actions, если forms будут реализованы. Если P5 ограничится API tests, CSRF можно отложить.

## Производительность

### 100 versions/events

SQLite JSON TEXT приемлем. Offset pagination достаточно.

### 1 000 versions/events

Нужны индексы `(product_id, created_at/version_number)`. JSON snapshots грузить лениво для list endpoint.

### 10 000 versions/events

List endpoint не должен возвращать `snapshot_json`; только metadata. Detail endpoint грузит snapshot.

### 100 000 events

Нужна cursor pagination по `(occurred_at, event_id)`. Offset станет дорогим. Compression пока не включать без benchmark.

## Snapshot storage

MVP:

- canonical JSON;
- `sort_keys=True`;
- compact separators;
- checksum SHA-256;
- no compression.

Compression отложить до доказательства размера.

## Изменяемые файлы после одобрения

Ожидаемые новые файлы:

- `app/editor/__init__.py`;
- `app/editor/schemas.py`;
- `app/editor/service.py`;
- `app/editor/repository.py`;
- `app/editor/validation.py`;
- `app/domain/events/repository.py`;
- `app/domain/events/unified_reader.py`;
- `app/web/routes/editor.py`;
- `app/web/templates/product_edit.html`;
- `app/web/templates/product_drafts.html`;
- `app/web/templates/product_audit.html`;
- `tests/test_card_editor.py`;
- `tests/test_product_drafts.py`;
- `tests/test_persisted_versions.py`;
- `tests/test_persisted_domain_events.py`;
- `tests/test_product_audit.py`;
- Alembic migration for P5 tables;
- `docs/P5_CARD_EDITOR_REPORT.md`.

Ожидаемые изменяемые файлы:

- `app/database.py`;
- `app/domain/events/models.py`;
- `app/domain/events/serializer.py`;
- `app/timeline/repository.py`;
- `app/timeline/service.py`;
- `app/products/versioning.py`;
- `app/web/routes/product_detail.py`;
- `app/web/app.py`;
- versioning/templates.

## mypy

`pyproject.toml` содержит `[tool.mypy]`, но пакет `mypy` отсутствует в `.venv`.

Решение:

- не добавлять `mypy` в P5 без отдельного dependency approval;
- в P5 держать строгие type hints на новых модулях;
- позже добавить dev dependency `mypy` отдельным tooling этапом.

## aiosqlite patch

Patch оставить как есть. В P5 не расширять и не удалять.

Риск: patch применяется глобально при import `app.database` и не имеет feature flag. Это отдельный infrastructure hardening task, не часть Card Editor.

## План логических commits после одобрения

1. `feat: add editable product card schema`
2. `feat: add product drafts`
3. `feat: persist product versions`
4. `feat: persist manual domain events`
5. `feat: add draft validation and apply transaction`
6. `feat: add optimistic locking`
7. `feat: add version rollback`
8. `feat: add card editor API`
9. `feat: add card editor UI`
10. `feat: add product audit trail`
11. `test: cover editor transactions and conflicts`
12. `docs: add P5 card editor report`

## Критерии готовности

- старые API-контракты сохранены;
- draft apply атомарен;
- persisted complete version создается только для новых изменений;
- persisted DomainEvent создается только для невосстановимых новых действий;
- AI не применяет изменения автоматически;
- rollback создает новую версию;
- conflicts возвращают 409;
- full pytest проходит;
- P5 changed files Ruff clean;
- `git diff --check` clean;
- skillpack validation проходит;
- push не выполняется.

## Можно ли начинать кодирование

Да, после отдельного подтверждения `ОДОБРЯЮ`.

Persisted event store нужен уже сейчас, но только для новых P5 actions. Backfill legacy событий в `domain_event_records` не нужен и вреден на этом этапе.
