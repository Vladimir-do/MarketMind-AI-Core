# P6 Client Projects Audit

Дата аудита: 2026-07-17

Этап: P6 MASTER STAGE — проекты заказчиков, Effective Card и экспорт результатов.

## 1. Фактическое состояние

Рабочая директория:

```text
/mnt/steam/Proekt/MarketMind-AI-Core-main
```

Подтверждённый HEAD:

```text
bc4ce19 test: cover card editor lifecycle and audit trail
```

В истории присутствуют требуемые checkpoint commits:

```text
0393647 feat: add product card editor persistence schema
9444513 feat: add product card editor API and timeline integration
bc4ce19 test: cover card editor lifecycle and audit trail
```

Рабочее дерево на момент аудита чистое.

`git remote -v` пустой, remote не настроен, push не выполнялся.

`alembic heads` показывает:

```text
f6a7b8c9d0e1 (head)
```

`alembic current` через shell PATH не запускается, потому что бинарник `alembic` не найден. Через `.venv/bin/alembic current` команда доходит до Alembic, но текущая конфигурация БД в этой среде не открывает SQLite-файл:

```text
sqlite3.OperationalError: unable to open database file
```

Также при импорте конфигурации появляется предупреждение:

```text
File logging disabled: cannot open parser.log ([Errno 30] Read-only file system)
```

Это не меняет вывод P6, но важно для реализации: миграционные проверки нужно выполнять на временной SQLite-БД с явно заданными runtime paths, как это делалось в P5.

## 2. Текущий рабочий процесс

Фактический путь данных сейчас:

```text
Файл заказчика
→ /api/import/file
→ временный файл в tempfile
→ ImportPipeline
→ UnifiedProduct
→ _save_products_to_db()
→ Database.save_product()
→ Product + PriceHistory
→ ProductAnalyzer / AI suggestions / ApprovalRecord
→ ProductCardDraft
→ ProductCardVersion
→ DomainEventRecord
→ Product / PriceHistory обновляются применённым snapshot
→ export_csv/export_excel/export_html_report читают Product + PriceHistory
```

P5 добавил редактор карточек, persisted versions, persisted manual domain events, optimistic locking и rollback. Но P5 сохраняет совместимость через запись применённого snapshot обратно в глобальные `Product` и `PriceHistory`.

Для одиночного каталога это удобно, но для P6 это основной риск: данные разных заказчиков не имеют собственной области.

## 3. Что уже реализовано

### Import

Реализованы:

- CSV importer;
- Excel importer для `.xlsx` и `.xlsm`;
- `ImportPipeline`;
- validation;
- enrichment;
- analysis;
- web import endpoint `/api/import/file`;
- demo import endpoint `/api/import/demo`.

Фактическое ограничение:

- исходный файл не сохраняется как файл заказчика;
- SHA-256 исходника не считается;
- импорт не связан с проектом;
- результат импорта сразу пишется в глобальные `Product` и `PriceHistory`.

### Product Card Editor

Реализованы:

- `ProductCardDraft`;
- `ProductCardVersion`;
- `DomainEventRecord`;
- draft create/list/get/update/discard/validate/apply;
- rollback version;
- audit endpoint;
- UI pages for edit, drafts, versions, compare, audit.

Ограничение:

- draft, version и audit связаны только с `product_id`, без `project_id`;
- `apply_draft()` обновляет глобальный `Product` и добавляет `PriceHistory`;
- actor сейчас `user/local_user`, но для P6 локального инструмента правильнее использовать `actor_type=local_user`, `actor_id=operator` для новых событий.

### Timeline and Versioning

Реализованы:

- legacy approval-only endpoint `GET /api/products/{product_id}/history`;
- aggregated timeline endpoint `GET /api/products/{product_id}/timeline`;
- version list/detail/compare endpoints;
- persisted complete versions для новых manual/rollback actions;
- derived versions для legacy data.

Ограничение:

- все timeline/versioning endpoints работают по глобальному `product_id`;
- persisted Domain Events используют `aggregate_id=str(product_id)`;
- проектная область события отсутствует.

### Reports and Exports

Реализованы:

- `export_csv(db)`;
- `export_excel(db)`;
- `export_html_report(db)`;
- web reports page `/reports`;
- reports API `/api/reports/client-summary`;
- analytics endpoints `/api/analytics/*`;
- batched price-history queries для экспорта.

Ограничение:

- экспорт читает все товары из БД;
- отчёт читает все товары из БД;
- analytics читает все товары из БД;
- CSV не защищён от formula injection;
- файлы экспорта создаются в памяти, но не управляются как артефакты проекта заказчика;
- XLSX есть технически через `openpyxl`, значит его можно рассматривать как реализуемый P6 формат без новой зависимости.

## 4. Структура данных сейчас

Ключевые таблицы:

```text
products
price_history
approval_records
product_card_drafts
product_card_versions
domain_event_records
scrape_attempts
blocked_patterns
subscribers
```

Важные поля:

```text
products.url_hash UNIQUE
products.url
products.name
products.image_url
price_history.product_id
product_card_drafts.product_id
product_card_versions.product_id
domain_event_records.aggregate_type
domain_event_records.aggregate_id
```

Отсутствуют:

```text
client_projects
client_project_files
project_products
project exports
project reports
project_id on drafts/versions/events
effective card read model/service
```

## 5. Где данные могут смешаться

### 5.1 Импорт

`/api/import/file` не принимает проект и сохраняет все товары через `Database.save_product()`.

`Database.save_product()` ищет товар по глобальному `url_hash`. Если два заказчика передали один и тот же URL, второй импорт обновит ту же запись `Product`, а не создаст отдельную рабочую карточку заказа.

Риск: данные заказа B изменят карточку заказа A.

### 5.2 Product list and detail

`/api/products`, `/products`, `/api/products/{id}`, `/products/{id}` читают глобальные товары.

Риск: пользователь в контексте одного заказа видит товары другого заказа.

### 5.3 Editor

`ProductCardEditorService.apply_draft()` применяет snapshot к глобальному `Product` и `PriceHistory`.

Риск: ручная правка карточки для одного заказчика становится текущим значением для всех будущих отчётов и экспортов.

### 5.4 Versions

`ProductCardVersion` хранит `product_id`, но не хранит `project_id`.

Риск: версия ручной карточки не различает заказчика, если один и тот же товар используется в нескольких проектах.

### 5.5 Domain Events and Audit

`DomainEventRecord.aggregate_id` сейчас равен `product_id`.

Риск: audit trail товара не отделяет действия в разных проектах.

### 5.6 Reports, Analytics, Exports

`StoreAnalyzer`, `build_client_report()`, `collect_report_data()` и `get_export_data()` читают весь каталог.

Риск: итоговый отчёт и экспорт заказчику содержат чужие товары.

## 6. Где данные могут потеряться

1. Исходный файл загружается во временный файл и удаляется после импорта.
2. Не сохраняется manifest исходника.
3. Не сохраняется SHA-256 исходника.
4. Не сохраняется исходное имя, размер, формат, количество строк и ошибки импорта как проектный артефакт.
5. Повторный импорт по тому же URL перезаписывает `Product.name` и `Product.image_url`.
6. Ручные изменения сейчас становятся частью глобального Product, поэтому невозможно надёжно отделить marketplace source value от manual override.

## 7. Где используется текущее Product вместо применённой версии

Используют `Product` + последнюю `PriceHistory`:

- `/api/products`;
- `/api/products/{id}`;
- `/api/products/{id}/analysis`;
- `/products/{id}`;
- `/api/dashboard`;
- `/reports`;
- `/api/reports/client-summary`;
- `/api/analytics/*`;
- `export_csv`;
- `export_excel`;
- `export_html_report`;
- Telegram export commands;
- legacy agent analytics.

После P6 эти места нельзя все одномоментно переписать без риска. Безопаснее:

1. добавить проектные сервисы и проектные API;
2. перевести новый project UI/export/report на EffectiveProductCard;
3. оставить старые глобальные endpoints совместимыми;
4. отдельно решить, какие legacy/Telegram paths должны стать project-aware.

## 8. Файлы и модули, затронутые будущей реализацией

Вероятные новые модули:

```text
app/projects/
app/effective_card/
app/exports/
app/reports/
app/workspace/
```

Вероятные изменяемые файлы:

```text
app/database.py
app/web/app.py
app/web/routes/import_.py
app/web/routes/products.py
app/web/routes/product_detail.py
app/web/routes/reports.py
app/web/routes/dashboard.py
app/editor/service.py
app/editor/repository.py
app/products/versioning.py
app/timeline/repository.py
app/timeline/service.py
app/analytics/store_analyzer.py
app/exporter.py
app/reporter.py
app/config.py
alembic/versions/*
tests/*
```

## 9. Безопасность файлов

Текущий импорт:

- использует `tempfile.gettempdir()`;
- строит имя временного файла через UUID;
- удаляет временный файл после обработки;
- не сохраняет оригинал.

Не хватает:

- project workspace;
- canonical safe filenames;
- SHA-256;
- manifest;
- запрет path traversal;
- защита от слишком длинных имён;
- защита от перезаписи;
- валидация расширения и фактического формата;
- хранение ошибок импорта;
- запрет выполнения вложенных файлов.

## 10. CSV/XLSX безопасность

Текущий `make_csv()` напрямую пишет значения через `csv.DictWriter`.

Не хватает защиты от formula injection для значений, начинающихся с:

```text
=
+
-
@
```

Текущий XLSX writer также записывает значения напрямую в cells.

Для P6 экспортов нужен общий sanitizer:

```text
sanitize_spreadsheet_cell(value)
```

Рекомендация: для опасных строк добавлять ведущий апостроф или другой документированный neutralization prefix. В отчёте заказчику это нужно описать как защиту Excel/LibreOffice.

## 11. Поддерживаемые форматы

Фактически реализовано:

- CSV import;
- XLSX/XLSM import;
- CSV export;
- XLSX export;
- HTML report.

JSON export для итоговых карточек P6 пока не реализован как project export, но его можно добавить без новой зависимости.

PDF не реализован и не должен добавляться в P6.

## 12. Вывод аудита

P6 можно начинать, но не через простое добавление `client_project_id` в `Product`.

Причина: `Product.url_hash` уникален глобально, а P5 editor применяет manual changes к глобальному Product. Если один и тот же товар появится в двух проектах, прямой `Product.client_project_id` либо заблокирует повторный импорт, либо смешает ручные изменения.

Безопаснее ввести:

```text
ClientProject
ClientProjectFile
ProjectProduct
EffectiveProductCardService
ProjectExport
ProjectReport
```

`Product` остаётся legacy/source entity. Project-specific работа должна идти через `ProjectProduct` и effective card.

## 13. Главные риски P6

1. Сломать старые API `/api/products/*`, `/api/reports/*`, `/api/analytics/*`.
2. Смешать project-specific manual overrides с глобальным `Product`.
3. Потерять исходные файлы заказчика или перезаписать экспорт.
4. Создать дублирование ProductCardVersion и DomainEventRecord без project context.
5. Экспортировать draft или AI proposal вместо applied/effective values.
6. Допустить CSV/XLSX formula injection.
7. Слишком широко исправлять legacy global flows и сломать Telegram/agent tests.

## 14. Рекомендация

Начинать реализацию можно после утверждения плана, но только фазами:

1. добавить project workspace and schema;
2. добавить project-scoped import;
3. добавить EffectiveProductCardService;
4. перевести project UI/report/export на effective card;
5. оставить legacy endpoints совместимыми;
6. только после тестов решить, какие legacy flows переводить на project-aware APIs.
