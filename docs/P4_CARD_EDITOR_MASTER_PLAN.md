# P4 Card Editor Master Plan

## Цель

Подготовить будущий редактор карточки товара без реализации редактирования в P4.

Редактор должен позволить пользователю вручную менять карточку, видеть draft, валидировать изменения, подтверждать сохранение и получать audit trail.

## Draft Model

Рекомендуемая модель:

```text
ProductCardDraft
- draft_id
- product_id
- base_version_id
- created_at
- updated_at
- actor_id
- status
- fields
- validation_result
- comment
```

Статусы:

- `draft`;
- `validated`;
- `approved`;
- `applied`;
- `discarded`;
- `conflicted`.

## Validation

Перед применением draft:

- обязательные поля;
- длины значений;
- запрещенные формулировки;
- категории и характеристики;
- marketplace-specific правила;
- проверка, что `base_version_id` еще актуален.

## Human Approval

AI не применяет изменения автоматически.

Поток:

```text
Draft
  -> Validation
  -> Preview
  -> Human confirmation
  -> Transactional apply
  -> DomainEvent
  -> Timeline / Versioning / Audit
```

## Snapshots

Для редактора нужны полные snapshots, потому что read-model версии P3/P4 частично восстановлены.

Рекомендуемый подход:

- хранить полный snapshot карточки при применении ручного изменения;
- хранить delta для отображения diff;
- связывать snapshot с DomainEvent.

## Manual Changes

Каждое ручное изменение должно иметь:

- actor;
- comment;
- old value;
- new value;
- field path;
- source `user`;
- timestamp UTC;
- affected marketplace rules.

## Audit Trail

Audit Trail должен использовать Domain Events как источник фактов.

Минимальные события:

- `product.draft_created`;
- `product.draft_validated`;
- `product.manual_change_applied`;
- `product.manual_change_rejected`;
- `product.rollback_requested`;
- `product.rollback_applied`;
- `product.conflict_detected`.

## Persisted Domain Events

Для Card Editor persisted event store станет объективно нужен, потому что:

- действия пользователя нельзя восстановить из `Product`, `PriceHistory` и `ApprovalRecord`;
- нужны actor/comment/reason;
- нужен rollback и аудит;
- нужна надежная история после рестарта;
- нужны notifications/background jobs.

Рекомендуемая таблица:

```text
domain_events
- event_id primary key
- aggregate_type
- aggregate_id
- event_type
- source
- actor_type
- actor_id
- occurred_at
- payload_json
- metadata_json
- schema_version
- correlation_id
- causation_id
```

## Transactional Outbox

Если появятся уведомления и фоновые задачи:

- сохранять DomainEvent и outbox row в одной транзакции;
- worker читает outbox;
- retries/idempotency по `event_id`.

## Rollback

Rollback должен:

- требовать подтверждения;
- проверять conflict по `base_version_id`;
- создавать новый event, а не удалять старую историю;
- показывать diff до применения;
- не использовать частично восстановленную версию как полный источник правды.

## Optimistic Locking

Для карточки нужен `version_number` или `updated_at`.

Если пользователь редактирует старую версию:

- показать конфликт;
- предложить пересобрать draft поверх текущей версии;
- не перезаписывать изменения молча.

## API

Предлагаемые endpoints:

```text
GET  /api/products/{product_id}/editor
POST /api/products/{product_id}/drafts
GET  /api/products/{product_id}/drafts/{draft_id}
POST /api/products/{product_id}/drafts/{draft_id}/validate
POST /api/products/{product_id}/drafts/{draft_id}/apply
POST /api/products/{product_id}/drafts/{draft_id}/discard
GET  /api/products/{product_id}/drafts/{draft_id}/diff
```

## UI

На странице товара:

- вкладка «Редактор»;
- режим draft;
- предпросмотр;
- diff «Было / Стало»;
- ошибки валидации простым русским языком;
- кнопки «Сохранить черновик», «Проверить», «Применить», «Отменить».

## Permissions

До полноценных пользователей можно использовать системного actor.

После добавления пользователей:

- viewer: только просмотр;
- editor: draft/validate;
- owner/admin: apply/rollback.

## Миграции

Вероятно потребуются:

- `product_card_drafts`;
- `product_card_snapshots`;
- `domain_events`;
- `outbox_events`.

Миграции должны быть отдельными и обратимыми.

## Риски

- преждевременный persisted event store усложнит проект;
- rollback без полного snapshot небезопасен;
- без optimistic locking возможна потеря ручных изменений;
- без actor/comment audit trail будет неполным.

## Рекомендуемый порядок

1. P4.1: persisted Domain Events только для новых manual editor actions.
2. P4.2: draft model and validation.
3. P4.3: editor UI draft-only.
4. P4.4: transactional apply with snapshots.
5. P4.5: rollback as new event.
6. P4.6: notifications/outbox.

## Итог

Card Editor можно проектировать поверх P4 foundation, но полноценную реализацию нельзя начинать без отдельного подтверждения и миграционного плана.
