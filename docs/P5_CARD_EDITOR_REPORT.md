# P5 Card Editor Report

## Что сделано

Реализован первый промышленный слой Product Card Editor:

- черновики карточки товара;
- валидация черновика;
- атомарное применение черновика;
- persisted complete product versions для новых ручных изменений;
- persisted Domain Events только для новых невосстановимых действий;
- optimistic locking через `base_version_id` и `revision`;
- rollback версии как новая версия и новое событие;
- audit trail для editor events;
- Timeline показывает ручные изменения;
- Versioning показывает persisted complete и legacy derived versions;
- AI-рекомендации не применяются автоматически.

## Новые таблицы

Alembic migration:

```text
alembic/versions/f6a7b8c9d0e1_add_card_editor_tables.py
```

Таблицы:

- `product_card_drafts`;
- `product_card_versions`;
- `domain_event_records`.

Legacy таблицы `products`, `price_history`, `approval_records` не удалялись и не backfill-ились в event store.

## API

Добавлено:

```text
POST   /api/products/{id}/drafts
GET    /api/products/{id}/drafts
GET    /api/products/{id}/drafts/{draft_id}
PATCH  /api/products/{id}/drafts/{draft_id}
DELETE /api/products/{id}/drafts/{draft_id}
POST   /api/products/{id}/drafts/{draft_id}/validate
POST   /api/products/{id}/drafts/{draft_id}/apply
POST   /api/products/{id}/versions/{version}/rollback
GET    /api/products/{id}/audit
```

Сохранены:

- `GET /api/products/{id}/history`;
- `GET /api/products/{id}/timeline`;
- существующие Versioning endpoints.

## UI

Добавлены страницы:

- `/products/{id}/edit`;
- `/products/{id}/drafts`;
- `/products/{id}/audit`.

Страница товара получила ссылки на редактор и журнал действий.

## Transaction boundary

Apply draft выполняется в одной транзакции:

```text
validate draft
check base version
build effective snapshot
create ProductCardVersion
create DomainEventRecord
update effective Product/PriceHistory
mark draft applied
commit
```

Тест `test_transaction_rolls_back_when_event_write_fails` проверяет, что при ошибке записи события версия не сохраняется.

## Optimistic locking

Используются:

- `draft.revision` для PATCH/apply;
- `draft.base_version_id` против текущей версии товара.

При конфликте API возвращает `409`.

## Rollback

Rollback:

- не удаляет старые версии;
- создает новый complete snapshot;
- создает `product.version_rolled_back`;
- требует текущий version id, если клиент его передал.

## Security

- DomainEvent JSON serializer запрещает sensitive keys (`token`, `secret`, `password`, etc.).
- P5 не добавляет настоящую auth/session модель.
- CSRF для HTML mutating forms не внедрен, потому что текущий Web UI не имеет session authentication. Mutating операции реализованы как API endpoints и покрыты тестами.
- `actor_id` пока `local_user`; production-grade user audit требует отдельного auth этапа.

## Проверки

Focused P5:

```text
60 passed in 69.82s
```

Full pytest:

```text
507 passed, 24 warnings in 133.59s
```

P5 touched-file Ruff:

```text
All checks passed
```

Full Ruff baseline:

```text
Found 268 errors.
```

Это legacy backlog вне P5. Массовый `ruff --fix` не выполнялся.

Skillpack validation:

```text
Validation passed: 48 indexed skill(s), 48 markdown skill(s), 0 warning(s).
```

Migration check on temporary SQLite DB:

```text
upgrade head -> downgrade -1 -> upgrade head -> f6a7b8c9d0e1 (head)
```

## Изменённые области

- `app/database.py`;
- `app/editor/`;
- `app/domain/events/repository.py`;
- `app/timeline/`;
- `app/products/versioning.py`;
- `app/web/routes/`;
- `app/web/templates/`;
- `tests/test_card_editor.py`;
- `docs/`;
- Alembic migration.

## Ограничения

- Нет production auth/session actor.
- Нет CSRF для HTML forms, потому что session layer отсутствует.
- Нет transactional outbox.
- Нет cursor pagination для 100k+ persisted events.
- Product effective update пока синхронизирует `Product.name`, `Product.image_url` и `PriceHistory` для совместимости существующего UI/API.
- Full Ruff legacy backlog остается отдельным maintenance этапом.

## Итог

P5 реализован как совместимый слой поверх P4 foundation. Старые read-only API сохранены, новые ручные действия имеют persisted versions, persisted Domain Events и audit trail.
