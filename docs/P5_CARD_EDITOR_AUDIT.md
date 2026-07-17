# P5 Card Editor Audit

## Checkpoint

Рабочий корень:

```text
/mnt/steam/Proekt/MarketMind-AI-Core-main
```

HEAD:

```text
ce7dbfd fix: harden timeline domain events and versioning
```

`git status --short --untracked-files=all`: чисто.

`git remote -v`: пусто.

## Alembic

Команды:

```bash
.venv/bin/alembic heads
.venv/bin/alembic history
```

Результат:

```text
e5f6a7b8c9d0 (head)
d4e5f6a7b8c9 -> e5f6a7b8c9d0 (head), add timeline composite indexes
c2475736d3e0 -> d4e5f6a7b8c9, add approval_records
<base> -> c2475736d3e0, initial schema
```

`alembic current` без переопределения `DATABASE_URL` падает:

```text
sqlite3.OperationalError: unable to open database file
```

Причина: `alembic/env.py` читает `DATABASE_URL` из `app.config`, а текущий default указывает на runtime path внутри project data. В sandbox этот путь может быть недоступен для записи. Это не доказывает дефект миграции.

Проверка на временной SQLite-БД:

```bash
DATABASE_URL=sqlite+aiosqlite:////tmp/marketmind_p5_alembic_check.db .venv/bin/alembic upgrade head
DATABASE_URL=sqlite+aiosqlite:////tmp/marketmind_p5_alembic_check.db .venv/bin/alembic downgrade -1
DATABASE_URL=sqlite+aiosqlite:////tmp/marketmind_p5_alembic_check.db .venv/bin/alembic upgrade head
DATABASE_URL=sqlite+aiosqlite:////tmp/marketmind_p5_alembic_check.db .venv/bin/alembic current
```

Результат:

```text
e5f6a7b8c9d0 (head)
```

## Текущая модель данных

### Product

Таблица `products` содержит:

- `id`;
- `url_hash`;
- `url`;
- `name`;
- `image_url`;
- `first_seen`;
- `last_check`.

Это source/product identity модель, а не полноценная редактируемая карточка маркетплейса.

### PriceHistory

Таблица `price_history` содержит:

- `product_id`;
- `price`;
- `availability_status`;
- `recorded_at`.

Это исторический источник цены и наличия, но не full card snapshot.

### ApprovalRecord

Таблица `approval_records` содержит AI proposal lifecycle:

- pending;
- approved;
- rejected;
- applied;
- rolled_back.

Она не должна становиться универсальным audit trail редактора.

## Текущие Domain Events

Сейчас события создаются read-model адаптерами:

- `ProductEventBuilder`;
- `ApprovalEventBuilder`;
- `TimelineEventMapper`.

DomainEvent не persisted. Старые события восстанавливаются из:

- `Product`;
- `PriceHistory`;
- `ApprovalRecord`.

Это правильно для legacy history, но недостаточно для ручных действий пользователя, draft lifecycle и rollback.

## Текущий Timeline

Публичные контракты:

- `GET /api/products/{id}/history` — approval-only JSON;
- `GET /api/products/{id}/timeline` — агрегированный timeline;
- `GET /products/{id}/history` — HTML partial.

Их нельзя ломать.

## Текущий Versioning

Существующий `ProductVersionBuilder` строит derived версии из Timeline. После P4 версии честно маркированы как:

- `is_derived = true`;
- `snapshot_completeness = partial`;
- `quality_score_is_historical = false`.

Для P5 нужны persisted complete snapshots только для новых manual/apply/rollback событий.

## Web UI и безопасность

FastAPI Web UI сейчас не имеет полноценного authentication/session слоя:

- нет login/session middleware для web routes;
- нет CSRF-токенов;
- CORS разрешает `allow_origins=["*"]`;
- forms/actions в текущем UI используют HTMX POST для suggestions.

Для P5 MVP можно использовать системного actor `local_user`, но нужно явно не заявлять production-grade user audit до появления auth/session.

Если в P5 появятся формы применения draft/rollback, нужны:

- CSRF token storage;
- session secret;
- либо ограничение API-only с explicit confirmation и тестами.

## AI Approval Workflow

`DatabaseApprovalQueue.apply_approved()` может применять approved AI suggestions к `Product`, но это существующее поведение. P5 не должен усиливать автоматическое применение AI. AI в Card Editor может только:

- предложить draft changes;
- объяснить diff;
- подготовить proposal.

Применение должно оставаться ручным.

## aiosqlite patch

Patch находится в `app/compat/aiosqlite_patch.py` и применяется при импорте `app.database`.

Свойства:

- idempotent marker `_marketmind_future_poll_patch`;
- polling sleep `0.001`;
- нет feature flag;
- нет feature detection;
- нет способа отключить;
- применяется также при Alembic через import `app.database`.

Удалять patch нельзя без воспроизводимого теста. Для P5 желательно не расширять patch.

## Недостатки для Card Editor

1. Нет editable card модели.
2. Нет draft lifecycle.
3. Нет persisted complete ProductVersion snapshots.
4. Нет persisted DomainEventRepository.
5. Нет audit trail для manual/user actions.
6. Нет optimistic locking.
7. Нет rollback версии как нового snapshot.
8. Нет user/session actor.
9. Нет CSRF для будущих HTML forms.
10. `Product` смешивает source identity и немного display data.

## Вывод

P5 требует persisted tables, но не должен backfill всех legacy событий. Правильный путь:

```text
legacy adapters for old history
        +
persisted events for new editor actions
        +
persisted complete versions for new applied snapshots
```

Можно переходить к реализации после утверждения плана, если миграции будут отдельными, обратимыми и покрыты тестами.
