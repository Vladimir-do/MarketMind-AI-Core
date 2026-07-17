# P3.9 Domain Event Contracts Report

Дата: 2026-07-17

## Что сделано

Добавлен первый безопасный слой Domain Event Platform без изменения публичных API и без миграции БД.

Реализованы:

- базовый `DomainEvent`;
- `EventActor`;
- enum-контракты для aggregate/source/actor;
- protocol-интерфейсы `EventBuilder`, `EventRepository`, `EventSerializer`, `EventPublisher`, `EventReader`;
- JSON-сериализация событий;
- защита сериализации от чувствительных ключей в payload/metadata;
- read-model builders из существующих `Product`, `PriceHistory`, `ApprovalRecord`;
- in-memory `ReadModelEventReader` для фильтрации, сортировки и дедупликации событий.

## Архитектура

```text
Product / PriceHistory / ApprovalRecord
        ↓
ProductEventBuilder / ApprovalEventBuilder
        ↓
DomainEvent
        ↓
ReadModelEventReader
        ↓
Future consumers:
Timeline / Versioning / Rollback / Audit / Notifications / Analytics
```

На этом этапе Timeline и Versioning не переведены на `DomainEvent` напрямую. Это сделано намеренно, чтобы не ломать уже работающий read-only Timeline Engine.

## Новые файлы

- `app/domain/__init__.py`
- `app/domain/events/__init__.py`
- `app/domain/events/models.py`
- `app/domain/events/interfaces.py`
- `app/domain/events/serializer.py`
- `app/domain/events/builders.py`
- `app/domain/events/reader.py`
- `tests/test_domain_events.py`
- `docs/P3_8_DOMAIN_EVENTS_PLAN.md`
- `docs/P3_9_DOMAIN_EVENTS_REPORT.md`

## Что не менялось

- Схема БД не менялась.
- Таблица `domain_events` не добавлялась.
- Публичные API не менялись.
- UI не менялся.
- Timeline endpoint не менялся.
- Product Versioning не переписывался.

## Почему без таблицы `domain_events`

Для текущих сценариев достаточно read-model поверх существующих таблиц:

- `Product`;
- `PriceHistory`;
- `ApprovalRecord`.

Persisted event store понадобится позже, когда появятся ручное редактирование карточки, полноценный audit trail, notifications/outbox и фоновые задачи с гарантированной доставкой событий.

## Тесты

Focused:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_domain_events.py tests/test_timeline_engine.py tests/test_product_versions.py tests/test_product_detail.py -o cache_dir=/tmp/marketmind-domain-events-pytest
```

Результат:

```text
35 passed in 24.46s
```

Ruff:

```text
RUFF_CACHE_DIR=/tmp/marketmind-ai-core-ruff .venv/bin/python -m ruff check app tests --select F821,F401,F841
```

Результат:

```text
All checks passed!
```

Whitespace:

```text
git diff --check
```

Результат: без ошибок.

Full pytest:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o cache_dir=/tmp/marketmind-domain-events-full-pytest
```

Результат:

```text
493 passed, 24 warnings in 76.49s
```

## Возможные проблемы

- `DomainEvent` пока не используется как источник Timeline, чтобы не делать рискованный переход в одном шаге.
- Нет persisted event store, поэтому это пока контракт и read-model слой.
- Перед следующим этапом нужно зафиксировать или явно принять текущий набор незакоммиченных P3.7/P3.8/P3.9 файлов.

## Рекомендуемый следующий шаг

P4.0 или отдельный P3.10:

1. Добавить mapper `DomainEvent -> ProductHistoryEvent`.
2. Перевести Timeline Builder на чтение доменных событий через adapter.
3. Сохранить текущий JSON-контракт `/api/products/{id}/timeline`.
4. Только после этого проектировать persisted `domain_events` для Card Editor.

## Итоговая оценка

Domain Event Platform получила безопасный фундамент: стабильный контракт событий, сериализацию, builders и reader. Изменение не ломает существующую архитектуру и готовит проект к Product Versioning, Card Editor, Rollback, Audit Trail, Notifications и Background Jobs.
