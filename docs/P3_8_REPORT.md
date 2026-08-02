# P3.8 Report — Версионность карточки товара

Дата: 2026-07-17

## Что сделано

Добавлена read-only версионность карточки товара без редактирования, миграций и новой таблицы БД.

Пользователь теперь может:

- открыть список версий товара;
- посмотреть конкретную версию через API;
- сравнить две версии;
- увидеть, какие поля изменились.

Редактирование карточки не добавлялось. AI по-прежнему ничего не применяет автоматически.

## Архитектура

```text
Product
PriceHistory
ApprovalRecord
Timeline
        ↓
ProductVersionBuilder
        ↓
ProductVersion
        ↓
VersionCompare
        ↓
API / UI
```

Версии строятся из уже существующих данных и timeline-событий. `ProductVersion` не сохраняется в БД.

## Новые файлы

- `app/products/versioning.py` — read-only модели версий, builder и compare.
- `app/web/templates/product_versions.html` — таблица версий.
- `app/web/templates/product_version_compare.html` — экран сравнения.
- `tests/test_product_versions.py` — тесты API/UI версий.
- `docs/P3_8_IMPLEMENTATION_PLAN.md` — план этапа.
- `docs/P3_8_REPORT.md` — отчёт этапа.

## Изменённые файлы

- `app/web/routes/product_detail.py`
  - добавлены API endpoints версий;
  - добавлены HTML routes версий и сравнения;
  - существующие timeline/history endpoints не удалялись.

- `app/web/templates/product_detail.html`
  - добавлена ссылка `Посмотреть версии карточки`.

## API

Добавлено:

```text
GET /api/products/{id}/versions
GET /api/products/{id}/versions/{version}
GET /api/products/{id}/compare?from=1&to=2
```

HTML:

```text
GET /products/{id}/versions
GET /products/{id}/compare?from=1&to=2
```

## Что считается версией

Версия создаётся только из события, которое меняет или потенциально меняет состояние карточки:

- импорт товара;
- изменение цены;
- изменение наличия;
- применённая AI-рекомендация;
- откат применённого решения.

Создание, одобрение и отклонение AI-рекомендации остаются timeline-событиями, но не считаются новой версией карточки, пока карточка не меняется.

## Ограничения

- Описание, бренд и характеристики исторически не сохраняются в `Product`.
- Quality Score во времени не сохраняется как snapshot.
- Старые значения `name` и `image_url` при обычном импорте нельзя полностью восстановить, если они не проходили через approval snapshots.
- Версии являются derived/read-only, а не юридически строгим audit trail.
- Для 10k+ версий позже понадобится persisted `ProductVersion` или периодические snapshots.

## Тесты

Focused:

```text
tests/test_product_versions.py tests/test_product_detail.py tests/test_approval_workflow.py: 36 passed
```

Проверено:

- список версий;
- пагинация;
- конкретная версия;
- compare API;
- HTML-страница версий;
- HTML-страница сравнения;
- неизвестный product id;
- неизвестная версия;
- сохранение P3.7 timeline/history behavior.

## Итоговая оценка

P3.8 реализован как безопасное read-only расширение поверх P3.7 Timeline. Архитектура не переписана, БД не менялась, существующие данные не дублируются.
