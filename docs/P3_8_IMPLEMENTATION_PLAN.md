# P3.8 Implementation Plan — Версионность карточки товара

Дата: 2026-07-17

## Статус

Этап P3.8 находится в режиме аудита и проектирования. Реализация не начинается до отдельного подтверждения пользователя словом `ОДОБРЯЮ`.

Важное замечание по рабочему дереву: на момент аудита в рабочем дереве уже есть незакоммиченные изменения P3.7 (`ProductHistoryBuilder`, timeline UI/API, тесты и отчёты). Этот план рассматривает P3.8 поверх текущего P3.7 состояния, но не меняет код.

## Цель P3.8

Добавить просмотр версий карточки товара во времени.

На P3.8 пользователь только:

- видит список версий;
- открывает конкретную версию;
- сравнивает две версии;
- понимает, какие поля изменились.

Редактирование карточки и сохранение ручных правок остаются за пределами P3.8 и должны появиться позже, в P4.

## Что уже есть

### Product

`Product` хранит:

- `id`;
- `url_hash`;
- `url`;
- `name`;
- `image_url`;
- `first_seen`;
- `last_check`.

Этого достаточно для базового текущего состояния товара и первой версии импорта, но недостаточно для полноценного восстановления старых версий названия/изображения, если они менялись без отдельного snapshot.

### PriceHistory

`PriceHistory` хранит:

- `product_id`;
- `price`;
- `availability_status`;
- `recorded_at`.

Этого достаточно для версий, связанных с ценой и наличием.

### ApprovalRecord

`ApprovalRecord` хранит:

- `field`;
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

Этого достаточно для версий, связанных с AI-рекомендациями и решениями пользователя, но только по полям, которые проходили через approval workflow.

### ProductHistoryBuilder / Timeline

P3.7 добавляет read-only timeline из:

- `Product`;
- `PriceHistory`;
- `ApprovalRecord`.

Timeline уже умеет показывать события, но не является моделью версий. Событие отвечает на вопрос `что произошло`, а версия должна отвечать на вопрос `как выглядела карточка после этого`.

## Какие данные уже позволяют восстановить версии

| Часть карточки | Можно восстановить сейчас | Источник | Ограничение |
|---|---|---|---|
| Дата первой версии | Да | `Product.first_seen` | Нет явного source кроме факта импорта |
| Текущие `name`, `url`, `image_url` | Да | `Product` | Старые значения не сохраняются полностью |
| Цена | Да | `PriceHistory` | Только цена, без валюты/скидок |
| Наличие | Да | `PriceHistory` | Только статус, не количественный остаток |
| AI-рекомендации | Да | `ApprovalRecord` | Это предложения, не обязательно фактическое состояние карточки |
| Одобренные AI-изменения | Частично | `ApprovalRecord.applied_at`, snapshots | Нужно проверить, применялось ли поле к реальному `Product` |
| Rollback | Частично | `ApprovalRecord.rolled_back_at`, snapshots | Есть событие отката, но не всегда есть полный snapshot карточки |

## Каких данных не хватает

| Данные | Почему не хватает |
|---|---|
| Описание | В текущей `Product` модели нет поля `description` |
| Бренд | В `Product` нет поля `brand` |
| Характеристики | В `Product` нет JSON/dict поля attributes |
| Несколько изображений | Есть только `image_url`, нет `image_urls` |
| Старые значения `name` и `image_url` при обычном импорте | `save_product()` обновляет `Product`, но не пишет snapshot старого значения |
| Quality Score во времени | Score вычисляется динамически, snapshots не сохраняются |
| Ручные правки | Редактора и audit событий ручных правок пока нет |
| Кто изменил | Нет user/actor в текущих таблицах |
| Комментарий версии | Нет общего comment/source для версии |

## Можно ли построить версии полностью из Timeline

Полностью — нет.

Timeline может быть входом для построения псевдоверсий, но не содержит полных snapshots карточки. Он содержит события:

- импорт;
- цена;
- наличие;
- AI-рекомендации;
- решения по AI.

Для P3.8 можно построить read-only derived versions:

- версия импорта;
- версии изменения цены/наличия;
- версии AI lifecycle;
- сравнительный diff по известным полям.

Но нельзя честно восстановить полную старую карточку с описанием, брендом, характеристиками и score, потому что эти данные не сохранялись.

## Что считать новой версией

Рекомендуемое правило P3.8:

Версия создаётся не для каждого события подряд, а для события, которое меняет или потенциально меняет состояние карточки.

| Событие timeline | Новая версия? | Причина |
|---|---|---|
| `product_imported` | Да | Начальное состояние карточки |
| `price_changed` | Да | Видимое состояние товара изменилось |
| `stock_changed` | Да | Наличие изменилось |
| `ai_suggestion_created` | Нет | Это предложение, не изменение карточки |
| `ai_suggestion_approved` | Нет | Само одобрение ещё не гарантирует изменение карточки |
| `ai_suggestion_rejected` | Нет | Карточка не меняется |
| `ai_suggestion_applied` | Да | Применённое изменение меняет карточку |
| `ai_suggestion_rolled_back` | Да | Состояние возвращено назад |
| ручное изменение | Да, позже | P4, когда появится редактор и audit |
| Quality Score changed | Да, позже | Когда появятся score snapshots |

Цена и наличие считаются частью версии товара в текущем продукте, потому что пользователь видит их на странице карточки и в отчётах.

## Нужна ли отдельная Version Builder

Да.

Рекомендуемый компонент:

```text
Product
PriceHistory
ApprovalRecord
ProductHistoryBuilder
        ↓
ProductVersionBuilder
        ↓
ProductVersion[]
        ↓
VersionCompare
        ↓
UI/API
```

Почему отдельный builder нужен:

- timeline events и versions имеют разные задачи;
- timeline показывает события;
- version показывает состояние карточки после значимого события;
- compare должен работать с snapshots версий, а не с сырыми event records;
- builder позволит не менять `ProductHistoryBuilder` и не ломать P3.7.

## Нужна ли таблица ProductVersion

Для P3.8 — не обязательна.

Рекомендация: начать с read-only `ProductVersionBuilder`, который строит derived versions из текущих таблиц и timeline. Это соответствует правилу не дублировать существующие данные.

Таблица `ProductVersion` станет нужна, когда появятся:

- ручной редактор карточки;
- сохранение описания, бренда, характеристик, нескольких изображений;
- Quality Score snapshots;
- необходимость хранить неизменяемые historical snapshots;
- быстрый просмотр 10k+ версий без реконструкции из событий;
- откат к конкретной версии.

## Почему Version Builder лучше прямого хранения ProductVersion на P3.8

Version Builder лучше на P3.8, потому что:

1. Уже есть `Product`, `PriceHistory`, `ApprovalRecord` и timeline.
2. Редактирования карточки ещё нет.
3. Полноценный snapshot всё равно будет неполным из-за отсутствующих полей карточки.
4. Таблица `ProductVersion` сейчас будет либо дублировать цену/approval events, либо хранить неполные версии.
5. Без ручного редактора и score snapshots persisted version table создаст ложное ощущение полной историчности.

Прямое хранение `ProductVersion` станет правильнее на P4, когда появится реальное сохранение изменений карточки.

## Version Model для P3.8

Read-only модель:

```text
ProductVersion
- version_id: str
- product_id: int
- version_number: int
- created_at: datetime
- created_by: str | None
- source: str
- version_type: str
- title: str
- changes: list[ProductVersionChange]
- snapshot: ProductVersionSnapshot
- quality_score: int | None
- comment: str | None
- timeline_event_ids: list[str]
```

```text
ProductVersionChange
- field: str
- field_label: str
- old_value: str | None
- new_value: str | None
```

```text
ProductVersionSnapshot
- name: str | None
- description: str | None
- brand: str | None
- price: int | None
- availability: str | None
- image_url: str | None
- image_urls: list[str]
- attributes: dict[str, str]
- ai_status: str | None
```

Для P3.8 часть snapshot полей будет `null` или пустой коллекцией, если данных нет. UI должен честно показывать `Нет данных`, а не придумывать значения.

## Snapshot: полная копия или delta

### Полная копия

Плюсы:

- быстро открыть любую версию;
- просто сравнивать две версии;
- проще будущий rollback;
- меньше зависимость от старых event records.

Минусы:

- больше места в БД;
- нужен schema/versioning для snapshot формата;
- при изменении модели карточки нужны миграции или совместимость snapshot.

Стоимость хранения:

- для 100 версий приемлемо;
- для 1 000 версий приемлемо при компактном JSON;
- для 10 000 версий может стать заметной, особенно с характеристиками и изображениями.

Скорость восстановления:

- высокая, `O(1)` на чтение версии.

### Delta

Плюсы:

- меньше места;
- хорошо отражает реальные изменения;
- удобно хранить как changeset.

Минусы:

- восстановление версии требует проигрывания цепочки изменений;
- сложнее сравнивать дальние версии;
- сложнее rollback;
- ошибки в одном delta могут ломать последующие версии.

Стоимость хранения:

- низкая.

Скорость восстановления:

- зависит от длины цепочки, может стать `O(n)`.

### Рекомендация

Для P3.8 без новой таблицы использовать runtime snapshot, собранный builder-ом из доступных данных.

Для будущей persisted `ProductVersion` лучше использовать гибрид:

- полная копия snapshot ключевых полей карточки;
- delta/changes рядом для быстрого отображения diff;
- JSON schema version в snapshot.

## Как сравнивать версии

`VersionCompare` должен принимать две версии и возвращать список изменённых полей:

```text
Version 15 → Version 16

Название:
Было: ...
Стало: ...

Цена:
Было: ...
Стало: ...

Наличие:
Было: ...
Стало: ...
```

Поля сравнения P3.8:

- название;
- цена;
- наличие;
- изображение;
- AI status/AI field change;
- Quality Score, если доступен.

Поля будущих этапов:

- описание;
- бренд;
- характеристики;
- несколько изображений;
- SEO-фразы;
- warning/validation findings.

## Предлагаемый UI

На странице `/products/{id}` добавить вкладку или блок:

```text
Версии
```

Новый экран:

```text
GET /products/{id}/versions
```

Содержимое:

- таблица версий;
- номер версии;
- дата;
- источник;
- тип версии;
- Quality Score;
- краткое описание изменений;
- кнопка `Сравнить`.

Экран сравнения:

```text
GET /products/{id}/compare?from=12&to=18
```

Содержимое:

- версия A;
- версия B;
- таблица полей `Было` / `Стало`;
- пояснение, если поле недоступно исторически.

Все пользовательские надписи — на русском языке.

## Предлагаемый API

### Список версий

```text
GET /api/products/{id}/versions
```

Параметры:

```text
limit=50
offset=0
version_type=all|import|price|stock|ai_applied|rollback|manual|quality
sort=newest_first|oldest_first
```

Ответ:

```json
{
  "product_id": 123,
  "items": [
    {
      "version_id": "version:123:0004",
      "version_number": 4,
      "created_at": "2026-07-17T10:00:00",
      "source": "Синхронизация",
      "version_type": "price",
      "title": "Изменилась цена товара",
      "quality_score": null,
      "changes": [
        {
          "field": "price",
          "field_label": "Цена",
          "old_value": "1500 ₽",
          "new_value": "1750 ₽"
        }
      ],
      "timeline_event_ids": ["price:456:price"]
    }
  ],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "has_more": false,
    "next_offset": null
  }
}
```

### Конкретная версия

```text
GET /api/products/{id}/versions/{version}
```

`version` может быть `version_number` или `version_id`. Для P3.8 проще начать с `version_number`.

### Сравнение версий

```text
GET /api/products/{id}/compare?from=12&to=18
```

Ответ:

```json
{
  "product_id": 123,
  "from_version": 12,
  "to_version": 18,
  "changes": [
    {
      "field": "price",
      "field_label": "Цена",
      "old_value": "1500 ₽",
      "new_value": "1750 ₽"
    }
  ],
  "warnings": [
    "Описание исторически не сохранялось, сравнение недоступно"
  ]
}
```

## Производительность

### 100 версий

Read-only builder достаточен:

- можно собрать versions из timeline в памяти;
- пагинация нужна для UI, но не критична;
- отдельная таблица не нужна.

### 1 000 версий

Read-only builder ещё возможен, но нужно:

- SQL limit/offset;
- не строить все versions для HTML;
- использовать pagination;
- не считать полный `total_count` без необходимости.

### 10 000 версий

Read-only builder становится рискованным:

- восстановление snapshot из timeline может быть дорогим;
- сравнение дальних версий может требовать проигрывания большого числа событий;
- потребуется persisted `ProductVersion` или периодические full snapshots.

## Индексы и хранение

На P3.8 без новой таблицы новые индексы не обязательны.

При росте данных полезны индексы:

```text
PriceHistory(product_id, recorded_at)
ApprovalRecord(product_id, created_at)
```

Если появится таблица `product_versions`, ей нужны:

```text
product_versions(product_id, version_number)
product_versions(product_id, created_at)
product_versions(product_id, version_type)
```

## Нужны ли миграции

Для P3.8 audit/read-only версии: миграция не нужна.

Для будущего persisted versioning потребуется новая таблица:

```text
product_versions
- id
- product_id
- version_number
- created_at
- created_by
- source
- version_type
- snapshot_json
- changes_json
- quality_score
- comment
- timeline_event_ids_json
```

Но добавлять её на P3.8 преждевременно.

## Риски

1. Нельзя обещать полное восстановление старых карточек: часть полей исторически не сохранялась.
2. Версии, построенные из timeline, будут derived/read-only, а не юридически строгим audit trail.
3. AI-рекомендация не всегда равна изменению карточки.
4. Approval `approved` не обязательно означает `applied`.
5. Сравнение описания, бренда и характеристик пока будет показывать `Нет данных`.
6. На больших историях builder без persisted snapshots может стать медленным.
7. Нельзя ломать P3.7 timeline endpoints.

## Предполагаемые изменения файлов после `ОДОБРЯЮ`

Минимальный набор:

| Файл | Изменение |
|---|---|
| `app/products/versioning.py` | `ProductVersionBuilder`, модели версии и сравнения |
| `app/web/routes/product_detail.py` | Подключить versions API и HTML routes рядом с product detail |
| `app/web/templates/product_versions.html` | Таблица версий |
| `app/web/templates/product_version_compare.html` | Сравнение версий |
| `app/web/templates/product_detail.html` | Добавить ссылку/блок `Версии` |
| `tests/test_product_detail.py` или `tests/test_product_versions.py` | Тесты версий и compare |
| `docs/P3_8_REPORT.md` | Итоговый отчёт |

Опционально позже:

| Файл | Изменение |
|---|---|
| `app/database.py` | Таблица `ProductVersion`, если будет принято persisted хранение |
| migrations | Миграция для `product_versions` |

## Тестирование после реализации

Focused:

```bash
.venv/bin/python -m pytest tests/test_product_detail.py tests/test_approval_workflow.py
```

Если будет отдельный файл:

```bash
.venv/bin/python -m pytest tests/test_product_versions.py
```

Проверки:

1. Список версий пустого/минимального товара.
2. Версия импорта.
3. Версия изменения цены.
4. Версия изменения наличия.
5. Версия применённой AI-рекомендации.
6. Версия rollback.
7. Сравнение соседних версий.
8. Сравнение дальних версий.
9. Неизвестный `product_id`.
10. Неизвестный `version`.
11. Пагинация.
12. Русские UI-надписи.
13. Timeline P3.7 не сломан.

Общие проверки:

```bash
RUFF_CACHE_DIR=/tmp/marketmind-ai-core-ruff .venv/bin/python -m ruff check app tests --select F821,F401,F841
.venv/bin/python -m pytest
git diff --check
```

## Рекомендация

Для P3.8 реализовать read-only `ProductVersionBuilder` без новой таблицы БД.

Добавить:

- `GET /api/products/{id}/versions`;
- `GET /api/products/{id}/versions/{version}`;
- `GET /api/products/{id}/compare?from=12&to=18`;
- `GET /products/{id}/versions`;
- `GET /products/{id}/compare?from=12&to=18`.

Не добавлять:

- редактирование карточки;
- сохранение ручных правок;
- `ProductVersion` таблицу;
- миграции.

К реализации можно переходить после подтверждения, но UI должен явно показывать ограничения: некоторые поля исторически недоступны.
