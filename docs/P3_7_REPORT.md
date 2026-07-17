# P3.7 Report — История изменений товара

Дата: 2026-07-17

## Что сделано

Добавлена единая read-only история событий товара без новой таблицы БД.

История собирается из уже существующих источников:

- `Product` — событие импорта товара;
- `PriceHistory` — изменения цены и наличия;
- `ApprovalRecord` — создание AI-рекомендаций, одобрение, отклонение, применение и откат.

AI по-прежнему ничего не применяет автоматически. Все события approval workflow отражают уже существующую human-in-the-loop модель.

## Архитектура

```text
Product
PriceHistory
ApprovalRecord
        ↓
ProductHistoryBuilder
        ↓
ProductHistoryEvent[]
        ↓
GET /api/products/{id}/timeline
GET /products/{id}/history
        ↓
product_detail.html
```

Новая таблица `event_history` не добавлялась, чтобы не дублировать `price_history` и `approval_records`.

Старый endpoint `GET /api/products/{id}/history` сохранён как approval-only API для обратной совместимости.

## Новые файлы

- `app/products/history.py` — нормализация событий товара.
- `app/web/templates/product_history.html` — HTMX partial истории.
- `docs/P3_7_IMPLEMENTATION_PLAN.md` — план этапа.
- `docs/P3_7_REPORT.md` — отчёт этапа.

## Изменённые файлы

- `app/web/routes/product_detail.py`
  - подключён `ProductHistoryBuilder`;
  - `/api/products/{id}/history` сохранён в старом approval-only формате;
  - добавлен `/api/products/{id}/timeline` для единой истории;
  - добавлен HTML partial route `/products/{id}/history`;
  - добавлены фильтры истории.

- `app/web/templates/product_detail.html`
  - старый approval-only блок заменён на единый блок `История изменений`.

- `tests/test_product_detail.py`
  - добавлены проверки импорта, цены, наличия, AI-событий, rollback, фильтров, сортировки, 404 и отсутствия дублей.

## Поддерживаемые события

| Тип | Источник |
|---|---|
| Импорт товара | `Product.first_seen` |
| Изменение цены | `PriceHistory.price` |
| Изменение наличия | `PriceHistory.availability_status` |
| Создание AI-рекомендации | `ApprovalRecord.created_at` |
| Одобрение AI-рекомендации | `ApprovalRecord.reviewed_at` |
| Отклонение AI-рекомендации | `ApprovalRecord.reviewed_at`, `reject_reason` |
| Применение AI-рекомендации | `ApprovalRecord.applied_at` |
| Откат решения | `ApprovalRecord.rolled_back_at` |

## Ограничения

- Изменение Quality Score пока не сохраняется как исторический снимок.
- Ручные правки товара пока не фиксируются, потому что полноценного редактора карточки с сохранением версий ещё нет.
- Количественные остатки не отображаются, потому что текущая модель хранит только `availability_status`.

Эти ограничения требуют отдельного источника событий или будущей таблицы audit/event history.

## Тесты

Focused:

```text
tests/test_product_detail.py tests/test_approval_workflow.py: 26 passed
```

Проверено:

- пустые и непустые списки истории;
- обратная совместимость `/api/products/{id}/history`;
- история одного товара;
- пагинация timeline;
- сортировка по времени;
- фильтрация по типу события;
- старое и новое значение цены;
- старое и новое значение наличия;
- AI approve/reject;
- rollback;
- неизвестный `product_id`;
- отсутствие дублирующихся `event_id`;
- HTML partial для HTMX.

## Возможные проблемы

- `GET /api/products/{id}/timeline` агрегирует события из нескольких таблиц, поэтому точный `total_count` пока не возвращается.
- При очень больших историях позже понадобятся composite indexes и cursor pagination.

## Итоговая оценка

P3.7 реализован как безопасное расширение текущей архитектуры. Схема БД не менялась, существующие журналы не дублируются, UI получил единый блок истории с фильтрами, а старый approval-only API контракт сохранён.
