# P3.7 Implementation Plan — История изменений товара

Дата: 2026-07-16

## Цель

Создать единый журнал событий по каждому товару, чтобы пользователь на странице товара видел, что происходило с карточкой во времени: импорт, изменения цены и наличия, изменения оценки качества, AI-предложения, решения пользователя, откаты и ручные правки.

Этап P3.7 пока находится в режиме аудита и планирования. Реализация начнётся только после отдельного подтверждения пользователя словом `ОДОБРЯЮ`.

## Что найдено в текущем проекте

### Уже существующие источники истории

1. `Product`
   - `first_seen` фиксирует первичное появление товара.
   - `last_check` фиксирует последнюю проверку/обновление товара.
   - `url`, `name`, `image_url` позволяют восстановить базовый контекст события импорта.

2. `PriceHistory`
   - хранит `product_id`, `price`, `availability_status`, `recorded_at`;
   - уже позволяет восстановить историю цены и остатков/наличия;
   - создаётся в `Database.save_product()` только при изменении цены или статуса наличия.

3. `ApprovalRecord`
   - хранит AI-предложения;
   - содержит `before_value`, `after_value`, `reason`, `confidence`, `status`;
   - фиксирует `created_at`, `reviewed_at`, `applied_at`, `rolled_back_at`;
   - содержит `reject_reason`, `snapshot_before`, `snapshot_after`;
   - уже покрывает создание AI-рекомендации, принятие, отклонение, применение и откат решения.

4. Текущий UI `/products/{id}`
   - уже показывает блок `История изменений`;
   - сейчас этот блок отображает только записи `ApprovalRecord`;
   - отдельно показывает график `История цены`.

5. Текущий API `/api/products/{product_id}/history`
   - уже существует;
   - сейчас возвращает только approval history;
   - его нельзя просто продублировать новым endpoint без сохранения обратной совместимости.

### Какие события уже можно восстановить из существующих данных

| Событие | Источник | Полнота |
|---|---|---|
| Импорт товара | `Product.first_seen` + первая запись `PriceHistory` | Частично: есть дата и товар, но нет явного источника импорта |
| Изменение цены | Последовательные записи `PriceHistory` | Хорошо: можно сравнить предыдущую и новую цену |
| Изменение наличия/остатков | Последовательные записи `PriceHistory.availability_status` | Частично: есть статус наличия, но нет количественного остатка |
| Создание AI-рекомендации | `ApprovalRecord.created_at` | Хорошо |
| Одобрение AI-рекомендации | `ApprovalRecord.reviewed_at`, `status=approved` | Хорошо |
| Отклонение AI-рекомендации | `ApprovalRecord.reviewed_at`, `status=rejected`, `reject_reason` | Хорошо |
| Откат решения | `ApprovalRecord.rolled_back_at`, `status=rolled_back`, `snapshot_before` | Хорошо |
| Применение одобренного предложения | `ApprovalRecord.applied_at`, snapshots | Частично: запись есть, но фактическое сохранение product field сейчас требует аккуратной проверки |

### Каких событий сейчас не хватает

| Событие | Почему не хватает |
|---|---|
| Изменение Quality Score | Score вычисляется динамически через `ProductAnalyzer`, снимок результата не сохраняется |
| Ручное изменение данных товара | Нет отдельного редактора карточки и нет audit/event записи ручной правки |
| Источник события для всех типов | `PriceHistory` и `Product` не хранят `source` в явном виде |
| Комментарий пользователя | Есть `reject_reason` для AI reject, но нет общего `comment` |
| Старое значение для первого импорта | Можно показывать `—`, но оно не хранится как отдельное поле |
| Количественный остаток | Текущая модель хранит `availability_status`, а не число остатков |

## Нужна ли новая таблица `event_history`

Рекомендация: новую таблицу не вводить как обязательную основу P3.7.

Причина: большая часть требуемой истории уже восстанавливается из `Product`, `PriceHistory` и `ApprovalRecord`. Если сразу добавить `event_history`, появится риск дублирования событий и рассинхронизации с существующими таблицами.

Предлагаемый подход для P3.7:

1. Создать read-model/агрегатор истории, который собирает события из существующих таблиц.
2. Не менять схему БД на первом шаге.
3. Сохранить текущий endpoint `/api/products/{id}/history`, но изменить его payload на единый список событий только после обновления тестов и UI.
4. Для будущих ручных правок и score snapshots запланировать отдельную таблицу только когда появится реальный источник таких событий.

Когда таблица `event_history` станет объективно нужна:

- появится редактор карточки с ручным сохранением;
- потребуется пользовательский комментарий к правке;
- потребуется неизменяемый audit trail;
- потребуется сохранять Quality Score во времени, а не пересчитывать его на лету;
- потребуется источник события, actor/user и correlation id.

## Предлагаемая архитектура P3.7

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
product_detail.html / product_history.html
```

### Новый read-model

Создать Pydantic/dataclass-модель события:

```text
ProductHistoryEvent
- event_id
- product_id
- event_type
- event_group
- source
- occurred_at
- field
- old_value
- new_value
- status
- reason
- comment
- confidence
- related_id
```

Все пользовательские подписи и статусы в UI должны быть на русском языке. В API можно оставить стабильные machine-readable значения и добавить русские display-поля.

### Группы фильтрации

| Фильтр UI | Источники |
|---|---|
| Все события | Все источники |
| Импорт | `Product.first_seen` |
| Цена | `PriceHistory.price` |
| Остатки | `PriceHistory.availability_status` |
| AI-рекомендации | `ApprovalRecord.created_at` |
| Одобрения и отклонения | `ApprovalRecord.reviewed_at`, `rolled_back_at`, `applied_at` |
| Ручные изменения | Пока пустая группа с корректным текстом `Событий нет` |

## Какие файлы потребуется изменить после одобрения

Минимальный набор:

| Файл | Изменение |
|---|---|
| `app/web/routes/product_detail.py` | Подключить агрегатор истории, сохранить старый `/api/products/{id}/history`, добавить `/api/products/{id}/timeline` и HTML partial `/products/{id}/history` |
| `app/web/templates/product_detail.html` | Заменить текущий approval-only блок истории на единый блок с фильтрами |
| `tests/test_product_detail.py` | Добавить проверки единой истории, фильтров, 404 и отсутствия дублей |
| `docs/P3_7_REPORT.md` | Итоговый отчёт после реализации |

Желательный отдельный модуль:

| Файл | Назначение |
|---|---|
| `app/products/history.py` | `ProductHistoryBuilder`, нормализация событий из `Product`, `PriceHistory`, `ApprovalRecord` |

Опционально:

| Файл | Назначение |
|---|---|
| `app/web/templates/product_history.html` | HTMX partial для фильтрации истории без полной перезагрузки |
| `app/web/locales/ru.json` | Добавить недостающие русские подписи, если текущего шаблона локализации достаточно |

## Текущий API-контракт

Текущий стабильный endpoint в `HEAD`:

```text
GET /api/products/{product_id}/history
```

Он не возвращает общую историю товара. Он возвращает только список `ApprovalRecord` для товара, отсортированный по `ApprovalRecord.created_at DESC`, максимум 50 записей.

Текущий JSON-контракт:

```json
[
  {
    "approval_id": "string",
    "field": "string",
    "suggestion_type": "string",
    "before_value": "string | null",
    "after_value": "string",
    "reason": "string",
    "confidence": 0.9,
    "status": "pending | approved | rejected | rolled_back",
    "reject_reason": "string | null",
    "created_at": "ISO datetime | null",
    "reviewed_at": "ISO datetime | null",
    "applied_at": "ISO datetime | null"
  }
]
```

Особенности текущего контракта:

- поле `product_id` в ответе отсутствует;
- поле `rolled_back_at` через этот endpoint в текущем `HEAD` не возвращается;
- события цены, импорта и наличия не возвращаются;
- endpoint проверяет существование товара через `_get_product()`;
- неизвестный `product_id` возвращает `404`.

Зависимости от текущего контракта:

| Место | Зависимость |
|---|---|
| `tests/test_product_detail.py::test_product_detail_history` | Проверяет только, что ответ `list`; контракт почти не защищён |
| `product_detail.html` | Не вызывает `/api/products/{id}/history`; использует `approval_records` из server-side context |
| `app/web/routes/suggestions.py` | Имеет отдельный `/api/suggestions/history`, не зависит от product history endpoint |
| Другие модули | По `rg` явной зависимости от JSON-полей `/api/products/{id}/history` не найдено |

Вывод: формальных потребителей мало, но endpoint уже публичный. Менять payload на агрегированную историю рискованно, потому что название `/history` уже занято approval-only контрактом.

## Стратегия обратной совместимости

Рекомендация: не менять контракт `GET /api/products/{product_id}/history` в P3.7.

Правила:

1. Оставить `/api/products/{product_id}/history` как approval-only endpoint.
2. Добавить отдельный агрегированный endpoint `GET /api/products/{product_id}/timeline`.
3. UI блока `История изменений` использовать новый timeline endpoint/partial.
4. Для старого endpoint добавить тест, который явно защищает поля `approval_id`, `field`, `suggestion_type`, `before_value`, `after_value`, `reason`, `confidence`, `status`, `reject_reason`, `created_at`, `reviewed_at`, `applied_at`.
5. Не объявлять deprecation для `/api/products/{id}/history` на P3.7, потому что он всё ещё полезен как история AI approvals.

Deprecation понадобится только если позже будет API v2 с полной заменой:

```text
GET /api/v2/products/{product_id}/history
```

На P3.7 deprecation не нужна.

## Новый API-контракт

Новый endpoint:

```text
GET /api/products/{product_id}/timeline
```

Назначение: единая агрегированная история товара из `Product`, `PriceHistory`, `ApprovalRecord`.

Ответ:

```json
{
  "product_id": 123,
  "items": [
    {
      "event_id": "price:456:price",
      "product_id": 123,
      "event_type": "price_changed",
      "event_type_label": "Изменение цены",
      "event_group": "price",
      "event_group_label": "Цена",
      "source": "Синхронизация",
      "occurred_at": "2026-07-17T10:00:00",
      "field": "price",
      "old_value": "1500 ₽",
      "new_value": "1750 ₽",
      "status": "recorded",
      "status_label": "Зафиксировано",
      "reason": "Изменилась цена товара",
      "comment": null,
      "confidence": null,
      "related_id": "456"
    }
  ],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "next_offset": null,
    "total_returned": 1,
    "has_more": false,
    "sort": "newest_first"
  }
}
```

HTML partial:

```text
GET /products/{product_id}/history
```

Назначение: вернуть HTML-фрагмент timeline для HTMX-фильтров. Это не JSON API и не конфликтует со старым `/api/products/{id}/history`.

## Пагинация и фильтрация

Рекомендуемые параметры для `GET /api/products/{product_id}/timeline` и HTML partial:

| Параметр | Значения | По умолчанию | Обоснование |
|---|---|---|---|
| `limit` | `1..200` | `50` | 50 достаточно для UI первого экрана; 200 ограничивает память и HTML payload |
| `offset` | `0..N` | `0` | Простая пагинация подходит для SQLite и текущего UI |
| `event_type` | `all`, `import`, `price`, `stock`, `ai`, `decision`, `manual` | `all` | Соответствует фильтрам UI |
| `date_from` | ISO datetime | `null` | Позволяет ограничить длинную историю |
| `date_to` | ISO datetime | `null` | Позволяет смотреть период |
| `sort` | `newest_first`, `oldest_first` | `newest_first` | Пользователь обычно хочет видеть последние изменения |

Почему не cursor pagination на P3.7:

- источники событий разные (`Product`, `PriceHistory`, `ApprovalRecord`);
- единого persisted cursor/event id пока нет;
- при лимите 50/200 offset проще и достаточно безопасен для MVP.

Cursor pagination стоит добавить позже, если появится реальная таблица `event_history` или истории по 100k+ событий станут нормой.

## Производительность

### 10 событий

Ожидаемое поведение:

- 1 запрос на товар через primary key;
- 1 запрос на `PriceHistory` по `product_id`;
- 1 запрос на `ApprovalRecord` по `product_id`;
- агрегация и сортировка в памяти.

Это безопасно.

### 1 000 событий

Риск умеренный:

- загрузка всех 1 000 строк в память допустима;
- сортировка Python `O(n log n)` приемлема;
- HTML rendering может стать тяжёлым без `limit`.

Требование: применять `limit`, `offset`, фильтрацию и SQL date bounds до построения событий.

### 100 000 событий

Загрузка всей истории в память недопустима.

Риски:

- большой memory footprint;
- медленная Python-сортировка;
- тяжёлый HTML response;
- SQLite может долго сортировать без индексов;
- offset на больших смещениях становится дорогим.

Для такого объёма P3.7 read-model должен:

1. Фильтровать на уровне SQL по `product_id` и датам.
2. Запрашивать ограниченное окно строк.
3. Не строить весь timeline целиком.
4. Возвращать `has_more`.
5. Рассмотреть cursor pagination в следующем этапе.

## Индексы

Существующие индексы:

- `ix_price_history_product_id` по `PriceHistory.product_id`;
- `PriceHistory.recorded_at` index;
- `ix_approval_records_product_id` по `ApprovalRecord.product_id`;
- `ix_approval_records_created_at` по `ApprovalRecord.created_at`;
- `ix_products_url_hash`.

Для P3.7 миграция не обязательна.

Желательные будущие composite индексы при росте данных:

```text
PriceHistory(product_id, recorded_at)
ApprovalRecord(product_id, created_at)
```

Обоснование:

- текущие запросы фильтруют по `product_id` и сортируют/ограничивают по времени;
- composite index уменьшит стоимость выборки timeline для одного товара.

На P3.7 новые индексы можно не добавлять, если остаётся `limit <= 200` и история тестового/раннего продукта невелика.

## Правила дедупликации

События не должны дублировать persisted rows. `ProductHistoryBuilder` создаёт deterministic `event_id`:

| Источник | event_id |
|---|---|
| Импорт товара | `product:{product.id}:import` |
| Цена | `price:{price_history.id}:price` |
| Наличие | `price:{price_history.id}:stock` |
| Создание AI-рекомендации | `approval:{approval_id}:created` |
| Одобрение | `approval:{approval_id}:approved` |
| Отклонение | `approval:{approval_id}:rejected` |
| Применение | `approval:{approval_id}:applied` |
| Откат | `approval:{approval_id}:rolled_back` |

Правила:

1. Импорт товара создаётся один раз из `Product.first_seen`.
2. Первая запись `PriceHistory` не создаёт отдельное событие цены, чтобы не дублировать импорт.
3. Изменение цены создаётся только если `previous.price != current.price`.
4. Изменение наличия создаётся только если `previous.availability_status != current.availability_status`.
5. Если цена и наличие изменились в одной записи `PriceHistory`, создаются два события с разными `event_id`.
6. AI created/approved/rejected/applied/rolled_back — разные lifecycle events, не дублируют друг друга.
7. Если `reviewed_at` отсутствует, approve/reject event не создаётся.
8. Если `applied_at` отсутствует, apply event не создаётся.
9. Если `rolled_back_at` отсутствует, rollback event не создаётся.

## Правила сортировки

Основная сортировка:

```text
occurred_at DESC
```

Tie-breaker для одинакового времени:

```text
occurred_at DESC,
event_priority ASC,
event_id ASC
```

Рекомендуемый priority:

| Событие | priority |
|---|---:|
| `ai_suggestion_rolled_back` | 10 |
| `ai_suggestion_applied` | 20 |
| `ai_suggestion_approved` / `ai_suggestion_rejected` | 30 |
| `ai_suggestion_created` | 40 |
| `price_changed` | 50 |
| `stock_changed` | 60 |
| `product_imported` | 90 |

Правила отображения значений:

- отсутствующий `old_value` показывать как `—`;
- отсутствующий `new_value` показывать как `—`;
- rollback показывать как переход от `after_value` обратно к `before_value`;
- цену форматировать как `<число> ₽`;
- machine-readable API поля не локализовать полностью, но добавить русские `*_label` поля.

## Матрица событий

| Event type | Group | Source table | Time field | Old value | New value | Status |
|---|---|---|---|---|---|---|
| `product_imported` | `import` | `Product` | `first_seen` | `null` | `name или url` | `recorded` |
| `price_changed` | `price` | `PriceHistory` | `recorded_at` | previous `price` | current `price` | `recorded` |
| `stock_changed` | `stock` | `PriceHistory` | `recorded_at` | previous `availability_status` | current `availability_status` | `recorded` |
| `ai_suggestion_created` | `ai` | `ApprovalRecord` | `created_at` | `before_value` | `after_value` | `pending` |
| `ai_suggestion_approved` | `decision` | `ApprovalRecord` | `reviewed_at` | `before_value` | `after_value` | `approved` |
| `ai_suggestion_rejected` | `decision` | `ApprovalRecord` | `reviewed_at` | `before_value` | `after_value` | `rejected` |
| `ai_suggestion_applied` | `decision` | `ApprovalRecord` | `applied_at` | snapshot/current before | `after_value` | `applied` |
| `ai_suggestion_rolled_back` | `decision` | `ApprovalRecord` | `rolled_back_at` | `after_value` | snapshot/before | `rolled_back` |

## Риски масштабирования

1. При 100k+ записей нельзя загружать всю историю перед фильтрацией.
2. Offset pagination может стать дорогой на больших смещениях.
3. Без composite индексов сортировка по времени после фильтра `product_id` может замедлиться.
4. Агрегация из нескольких таблиц усложняет точный `total_count`.
5. HTML partial с большим количеством событий может стать медленным даже при быстрых SQL-запросах.
6. Если позже появится `event_history`, потребуется backfill и строгие правила недублирования.

## Какие API и UI маршруты будут добавлены или изменены

### Существующий API

`GET /api/products/{product_id}/history`

Предлагается сохранить путь и текущий approval-only JSON-контракт.

### Новый агрегированный API

`GET /api/products/{product_id}/timeline`

Параметры:

```text
event_type=all|import|price|stock|ai|decision|manual
limit=50
offset=0
date_from=<ISO datetime>
date_to=<ISO datetime>
sort=newest_first|oldest_first
```

### Новый HTML partial

`GET /products/{product_id}/history`

Назначение: вернуть HTML-фрагмент истории для HTMX-фильтров.

### Страница товара

`GET /products/{product_id}`

На странице добавить блок `История изменений` с фильтрами. Для пустой истории показывать понятный текст, а не скрывать блок полностью.

## Риски миграции БД

На рекомендуемом первом шаге миграция БД не нужна.

Риски при добавлении `event_history`, если оно потребуется позже:

- дублирование событий из `PriceHistory` и `ApprovalRecord`;
- необходимость backfill старых данных;
- риск несоответствия между source tables и event table;
- усложнение rollback/approval workflow;
- миграция SQLite должна оставаться безопасной для Windows/Linux.

## Как сохранить обратную совместимость

1. Не удалять `ApprovalRecord`.
2. Не менять `PriceHistory`.
3. Не менять сигнатуру `Database.save_product()`.
4. Не менять существующие approve/reject/rollback endpoints.
5. Сохранить путь `/api/products/{id}/history`.
6. Если старым потребителям нужен approval-only список, оставить `/api/suggestions/history?product_id=...`.
7. В UI не применять AI-изменения автоматически.

## Тестирование после одобрения реализации

Focused tests:

```bash
.venv/bin/python -m pytest tests/test_product_detail.py tests/test_approval_workflow.py
```

Проверки:

1. Пустая история.
2. История одного товара.
3. Сортировка по времени по убыванию.
4. Фильтрация по типу события.
5. Старое и новое значение для цены.
6. Старое и новое значение для наличия.
7. AI-рекомендация появляется как событие.
8. Approve/reject отображаются как события решений.
9. Rollback отображается как событие отката.
10. Неизвестный `product_id` возвращает 404.
11. Нет дублирующихся событий.
12. UI-страница содержит блок `История изменений`.

Общие проверки:

```bash
RUFF_CACHE_DIR=/tmp/marketmind-ai-core-ruff .venv/bin/python -m ruff check app tests --select F821,F401,F841
.venv/bin/python -m pytest
git diff --check
```

## Альтернативы

### Альтернатива 1: сразу добавить `event_history`

Плюсы:

- единый источник для всех будущих событий;
- проще добавлять ручные комментарии и actor/source.

Минусы:

- дублирует `PriceHistory` и `ApprovalRecord`;
- требует миграции и backfill;
- повышает риск рассинхронизации.

Вердикт: преждевременно для P3.7.

### Альтернатива 2: оставить текущую историю только по AI

Плюсы:

- минимальный риск;
- ничего не нужно менять.

Минусы:

- не выполняет цель P3.7;
- пользователь не видит импорт, цену и наличие в единой ленте.

Вердикт: недостаточно.

### Альтернатива 3: сделать только UI-объединение в шаблоне

Плюсы:

- быстро;
- почти без новых модулей.

Минусы:

- логика смешается с UI;
- API останется неполным;
- тестировать сортировку и фильтрацию будет хуже.

Вердикт: не рекомендуется.

## Рекомендуемый безопасный план реализации после `ОДОБРЯЮ`

1. Создать `app/products/history.py` с read-only агрегатором событий.
2. Покрыть агрегатор unit-тестами через существующие `Product`, `PriceHistory`, `ApprovalRecord`.
3. Сохранить `/api/products/{id}/history` как approval-only endpoint и добавить тест его контракта.
4. Добавить `/api/products/{id}/timeline` для агрегированной истории.
5. Добавить HTML partial `/products/{id}/history`.
6. Обновить блок истории на `product_detail.html`.
7. Добавить фильтры HTMX.
8. Запустить focused tests.
9. Запустить Ruff и полный pytest.
10. Создать `docs/P3_7_REPORT.md`.

## Итоговая рекомендация

P3.7 лучше реализовать без новой таблицы БД на первом шаге. Текущих источников достаточно для единой read-only истории по импорту, цене, наличию и AI lifecycle. Новую таблицу событий следует вводить позже, когда появятся ручные правки, сохранение Quality Score snapshots или требования к неизменяемому audit trail.

Чёткое решение перед реализацией:

- оставить `GET /api/products/{product_id}/history` без изменения payload;
- добавить новый endpoint `GET /api/products/{product_id}/timeline`;
- добавить HTML partial `GET /products/{product_id}/history`;
- миграция БД на P3.7 не нужна;
- новые индексы на P3.7 не обязательны, но при росте данных стоит добавить composite indexes `PriceHistory(product_id, recorded_at)` и `ApprovalRecord(product_id, created_at)`;
- к реализации можно переходить после подтверждения, но реализация должна учитывать совместимость: не заменять старый `/history` контракт агрегированным payload.
