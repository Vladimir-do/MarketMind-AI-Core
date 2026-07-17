# P6 Client Workflow Implementation Plan

Этап: P6 MASTER STAGE — проекты заказчиков, Effective Card и экспорт результатов.

Статус: планирование. Код, БД, routes и templates ещё не изменялись.

## 1. Цель P6

Сделать MarketMind AI локальным рабочим инструментом для выполнения заказов:

```text
Заказчик передаёт файлы
→ пользователь создаёт проект
→ импортирует товары
→ анализирует карточки
→ получает AI-рекомендации
→ вручную редактирует карточки
→ проверяет effective result
→ формирует export files и client report
→ передаёт материалы заказчику
```

На P6 не добавляются:

- регистрация;
- логин;
- роли;
- SaaS;
- кабинет заказчика;
- автоматическая публикация на маркетплейсы;
- email delivery;
- PDF.

Для audit trail новых действий:

```text
actor_type = local_user
actor_id = operator
```

## 2. Рекомендуемая модель данных

### 2.1 ClientProject

```text
client_projects
- project_id TEXT primary key
- name TEXT not null
- client_name TEXT
- marketplace TEXT not null
- status TEXT not null
- description TEXT
- source_filename TEXT
- source_file_hash TEXT
- source_imported_at DATETIME
- created_at DATETIME not null
- updated_at DATETIME not null
- completed_at DATETIME
- notes TEXT
- export_directory TEXT
```

UI labels:

```text
Проект
Заказчик
Новый
В работе
Готов к проверке
Завершён
Архив
```

Statuses:

```text
new
in_progress
ready_for_review
completed
archived
```

Russian labels are presentation-layer values, not database enum values.

### 2.2 ClientProjectFile

```text
client_project_files
- file_id TEXT primary key
- project_id TEXT not null
- original_filename TEXT not null
- stored_filename TEXT not null
- relative_path TEXT not null
- sha256 TEXT not null
- size_bytes INTEGER not null
- file_format TEXT not null
- row_count INTEGER
- import_status TEXT not null
- import_errors_json TEXT
- imported_at DATETIME
- created_at DATETIME not null
```

Unique recommendation:

```text
UNIQUE(project_id, sha256)
```

Повторный импорт того же файла должен явно сообщать, что файл уже был импортирован, и предлагать действие пользователю.

### 2.3 ProjectProduct

Не рекомендуется ограничиваться `Product.client_project_id`.

Причина: `Product.url_hash` сейчас глобально уникален. Один и тот же URL у двух заказчиков должен иметь независимый рабочий контекст, иначе ручные правки и отчёты смешаются.

Рекомендуемая таблица:

```text
project_products
- project_product_id TEXT primary key
- project_id TEXT not null
- product_id INTEGER not null
- source_file_id TEXT
- source_row_index INTEGER
- source_snapshot_json TEXT not null
- source_snapshot_hash TEXT not null
- latest_source_snapshot_json TEXT not null
- latest_source_snapshot_hash TEXT not null
- status TEXT not null
- created_at DATETIME not null
- updated_at DATETIME not null
- source_updated_at DATETIME
- effective_updated_at DATETIME
```

Unique recommendation:

```text
UNIQUE(project_id, product_id)
```

Это сохраняет существующий `Product` как source/catalog identity и добавляет рабочую область заказа.

### 2.4 Project artifacts

```text
project_exports
- export_id TEXT primary key
- project_id TEXT not null
- export_type TEXT not null
- marketplace_profile TEXT not null
- file_format TEXT not null
- relative_path TEXT not null
- product_count INTEGER not null
- status TEXT not null
- warnings_json TEXT
- created_at DATETIME not null

project_reports
- report_id TEXT primary key
- project_id TEXT not null
- report_type TEXT not null
- file_format TEXT not null
- relative_path TEXT not null
- summary_json TEXT not null
- status TEXT not null
- created_at DATETIME not null
```

## 3. Связь проекта с существующими сущностями

### Product

`Product` остаётся глобальной source entity для обратной совместимости.

Новый P6 UI должен работать с:

```text
ClientProject
→ ProjectProduct
→ Product
```

### PriceHistory

`PriceHistory` остаётся source price history. Для effective card price после ручной правки источник должен определяться через latest applied `ProductCardVersion` в контексте project.

### ProductCardDraft

Текущая таблица содержит `product_id`, но не содержит `project_id`.

Для P6 нужно добавить project context:

```text
project_id TEXT
project_product_id TEXT
```

Новые draft operations должны проверять принадлежность товара проекту.

### ProductCardVersion

Текущая таблица содержит `product_id`, но не содержит `project_id`.

Для P6 нужно добавить:

```text
project_id TEXT
project_product_id TEXT
```

Это позволит иметь independent applied versions for the same global Product in different client projects.

### DomainEventRecord

Для новых P6 событий:

```text
aggregate_type = "project_product"
aggregate_id = project_product_id
metadata.project_id = project_id
payload.product_id = product_id
```

Старые P5 события `aggregate_type=product`, `aggregate_id=product_id` остаются legacy-compatible.

Timeline для project product должен читать:

```text
legacy product events
+
project product persisted events
```

Но старые `/api/products/{id}/timeline` не меняют контракт.

## 4. Workspace structure

Рекомендуемый root:

```text
MARKETMIND_WORKSPACE_DIR
```

Default:

```text
app/data/workspace
```

Структура:

```text
workspace/
  projects/
    <project_id>/
      source/
      working/
      exports/
      reports/
      manifest.json
```

Правила:

1. Все пути строятся через `pathlib`.
2. Пользовательское имя файла не используется напрямую как путь.
3. Сервер генерирует безопасное `stored_filename`.
4. Оригинальное имя хранится только как metadata.
5. Исходный файл сохраняется без изменений.
6. Для обработки создаётся рабочая копия только при необходимости.
7. Экспорт создаётся только внутри `workspace/projects/<project_id>/exports/`.
8. Отчёты создаются только внутри `workspace/projects/<project_id>/reports/`.
9. Файлы не удаляются и не перезаписываются без явного действия пользователя.

## 5. Safe file rules

Для входных файлов:

- разрешать только фактически поддержанные форматы: CSV, XLSX, XLSM;
- вычислять SHA-256;
- сохранять размер;
- сохранять row count;
- сохранять import errors;
- блокировать path traversal;
- очищать опасные имена;
- ограничивать длину имени;
- не запускать вложенные файлы;
- не доверять расширению без проверки importer capability;
- не принимать путь от пользователя как destination path.

## 6. Effective Product Card

### 6.1 Определение

```text
Marketplace source data
        +
latest applied ProductCardVersion within project
        =
Effective Product Card
```

Не являются effective card:

- draft;
- AI proposal;
- pending approval;
- rejected approval;
- unapplied recommendation.

### 6.2 EffectiveProductCard model

```text
EffectiveProductCard
- product_id
- project_id
- project_product_id
- source_snapshot
- applied_snapshot
- effective_snapshot
- latest_version_id
- latest_version_number
- overridden_fields
- is_manually_modified
- source_updated_at
- effective_updated_at
- warnings
```

### 6.3 EffectiveProductCardService

Новый service:

```text
app/effective_card/service.py
```

Public API:

```text
get_effective_card(project_id, product_id)
list_effective_cards(project_id, limit, offset, filters)
build_source_card(project_product)
build_effective_card(project_product)
build_draft_preview(project_id, product_id, draft_id)
diff_source_effective(project_id, product_id)
clear_override(project_id, product_id, field)
```

Используется:

- Project Product Detail;
- Reports;
- Quality Score;
- Versioning;
- Export;
- preview card;
- client delivery report.

Бизнес-логика effective card не размещается в HTML templates.

## 7. Повторный импорт

Сценарий:

```text
Source title:
Телефон X

Manual title:
Смартфон X 128 ГБ

New source title after reimport:
Телефон X New
```

Правила:

1. Manual applied value remains effective.
2. New source value updates `ProjectProduct.latest_source_snapshot_json`.
3. Effective card shows warning:

```text
Исходное значение изменилось. Ручная версия сохранена.
```

4. Пользователь может:

- оставить ручное значение;
- принять новое исходное значение;
- открыть diff;
- снять ручное переопределение;
- создать новый черновик на основе нового source value.

5. Reimport creates Domain Event only when source snapshot hash changes.
6. Reimport must not create duplicate ProductCardVersion if effective card did not change.

## 8. Quality Score flow

Нужно поддержать три режима:

```text
Source Quality Score
Effective Quality Score
Draft Preview Quality Score
```

API options:

```text
GET /api/projects/{project_id}/products/{product_id}/quality
POST /api/projects/{project_id}/products/{product_id}/drafts/{draft_id}/quality-preview
```

Response:

```json
{
  "project_id": "...",
  "product_id": 1,
  "source": {"score": 62, "tier": "fair", "findings": []},
  "effective": {"score": 81, "tier": "good", "findings": []},
  "draft_preview": null,
  "warnings": []
}
```

Quality score itself must not create a new version unless the card snapshot changes.

## 9. Export formats

P6 exports must use only Effective Product Card.

Do not export:

- unapplied draft;
- pending AI recommendation;
- internal Domain Event payload;
- actor metadata;
- database technical fields;
- secrets or tokens.

### 9.1 ExportProductCard

```text
ExportProductCard
- project_id
- product_id
- project_product_id
- marketplace
- external_product_id
- title
- description
- brand
- price
- availability
- image_urls
- attributes
- source_quality_score
- effective_quality_score
- latest_version_id
- warnings
```

### 9.2 Formats

Implement:

- Universal CSV;
- JSON;
- XLSX, because `openpyxl` is already present.

Do not call marketplace profiles official templates.

Use:

```text
Подготовительный профиль экспорта
```

Profiles:

- Ozon-oriented;
- Wildberries-oriented;
- Yandex Market-oriented.

## 10. CSV/XLSX security

Add shared sanitizer:

```text
app/exports/safety.py
```

Rules:

- values starting with `=`, `+`, `-`, `@` are neutralized;
- quotes and newlines are preserved safely through CSV/XLSX writers;
- Unicode and Russian text are preserved;
- HTML/script text is exported as text, not executed;
- long fields are either limited with warning or exported according to documented maximum;
- empty fields remain empty;
- duplicate attributes produce warnings;
- file names are server-generated and sanitized;
- exports cannot escape project export directory.

Recommended generated filename:

```text
<project_slug>_<marketplace>_<date>_<short_id>.csv
```

## 11. Итоговый отчёт заказчику

Formats:

- HTML;
- JSON;
- CSV summary.

No PDF in P6.

Report fields:

- project name;
- client name;
- processing date;
- source file;
- total products;
- successfully processed products;
- products with errors;
- average source Quality Score;
- average effective Quality Score;
- changed cards count;
- top problems found;
- applied fixes;
- products requiring manual review;
- created export files;
- warnings and limitations.

## 12. API design

### 12.1 Projects

```text
POST   /api/projects
GET    /api/projects
GET    /api/projects/{project_id}
PATCH  /api/projects/{project_id}
POST   /api/projects/{project_id}/archive
```

Rules:

- no auth;
- local single-user context;
- archived projects hidden from default list unless `include_archived=true`;
- physical delete is not part of MVP.

### 12.2 Import

```text
POST /api/projects/{project_id}/imports
GET  /api/projects/{project_id}/imports
GET  /api/projects/{project_id}/imports/{import_id}
```

Rules:

- project must exist and not be archived;
- import stores original file and manifest;
- import creates or links ProjectProduct rows;
- import returns row count, saved count, errors and duplicate file status.

### 12.3 Products

```text
GET /api/projects/{project_id}/products
GET /api/projects/{project_id}/products/{product_id}
GET /api/projects/{project_id}/products/{product_id}/effective-card
GET /api/projects/{project_id}/products/{product_id}/quality
```

Rules:

- product must belong to project;
- unknown or foreign product returns 404;
- lists use pagination;
- effective-card response never includes draft or pending AI proposal as final value.

### 12.4 Drafts

Keep existing legacy endpoints:

```text
/api/products/{product_id}/drafts
```

Add project-aware equivalents:

```text
POST   /api/projects/{project_id}/products/{product_id}/drafts
GET    /api/projects/{project_id}/products/{product_id}/drafts
GET    /api/projects/{project_id}/products/{product_id}/drafts/{draft_id}
PATCH  /api/projects/{project_id}/products/{product_id}/drafts/{draft_id}
DELETE /api/projects/{project_id}/products/{product_id}/drafts/{draft_id}
POST   /api/projects/{project_id}/products/{product_id}/drafts/{draft_id}/validate
POST   /api/projects/{project_id}/products/{product_id}/drafts/{draft_id}/apply
POST   /api/projects/{project_id}/products/{product_id}/drafts/{draft_id}/quality-preview
```

Rules:

- draft must belong to same project product;
- optimistic locking remains;
- apply is atomic;
- applying creates project-scoped version and domain event.

### 12.5 Export

```text
GET  /api/projects/{project_id}/export-preview
POST /api/projects/{project_id}/exports
GET  /api/projects/{project_id}/exports
GET  /api/projects/{project_id}/exports/{export_id}
```

Rules:

- maximum batch size default 500, configurable later;
- export reads EffectiveProductCard only;
- export stores file inside project workspace;
- response returns metadata and download path/route, not arbitrary filesystem path.

### 12.6 Report

```text
GET  /api/projects/{project_id}/report-preview
POST /api/projects/{project_id}/reports
GET  /api/projects/{project_id}/reports
```

Rules:

- report reads project products only;
- report uses source/effective score comparison;
- report stores generated artifact inside project workspace.

## 13. UI design

New pages:

```text
/projects
/projects/new
/projects/{project_id}
/projects/{project_id}/import
/projects/{project_id}/products
/projects/{project_id}/reports
/projects/{project_id}/exports
```

Project dashboard shows:

- заказчик;
- статус;
- исходные файлы;
- количество товаров;
- прогресс;
- проблемные товары;
- средний score до и после;
- последние изменения;
- созданные экспорты;
- кнопка «Продолжить работу»;
- кнопка «Сформировать результат».

No login screen.

## 14. Backward compatibility

Must keep:

```text
GET /api/products/{id}/history
GET /api/products/{id}/timeline
GET /api/products/{id}/versions
draft endpoints
audit endpoints
```

Strategy:

1. Keep existing global endpoints unchanged.
2. Add project-aware endpoints in parallel.
3. Project UI uses new endpoints.
4. Existing tests continue to pass.
5. Legacy Telegram/agent flows remain global until a separate compatibility phase.

## 15. Migrations

Required:

1. create `client_projects`;
2. create `client_project_files`;
3. create `project_products`;
4. create `project_exports`;
5. create `project_reports`;
6. add nullable `project_id` and `project_product_id` to `product_card_drafts`;
7. add nullable `project_id` and `project_product_id` to `product_card_versions`;
8. optionally add project context columns to `domain_event_records`, or store project context in metadata for compatibility.

Recommendation:

- use nullable columns for existing P5 data;
- backfill is not required in MVP;
- old records remain legacy/global;
- project-aware writes always fill project context.

Indexes:

```text
client_projects(status, updated_at)
client_project_files(project_id, sha256)
project_products(project_id, product_id)
project_products(project_id, updated_at)
project_exports(project_id, created_at)
project_reports(project_id, created_at)
product_card_drafts(project_id, project_product_id, status, updated_at)
product_card_versions(project_id, project_product_id, version_number)
```

## 16. Implementation phases

### Commit 1 — Client projects schema

```text
feat: add local client projects
```

Files:

```text
app/database.py
alembic/versions/*
app/projects/
tests/test_client_projects.py
```

Criteria:

- create/list/update/archive project;
- migrations upgrade/downgrade pass;
- legacy tests still pass.

### Commit 2 — Safe workspace and source files

```text
feat: add safe source file workspace
```

Files:

```text
app/workspace/
app/projects/files.py
app/config.py
tests/test_project_files.py
```

Criteria:

- source file copied safely;
- SHA-256 stored;
- path traversal rejected;
- duplicate import detected.

### Commit 3 — Project-scoped import

```text
feat: isolate products by client project
```

Files:

```text
app/web/routes/projects.py
app/web/routes/import_.py
app/projects/imports.py
tests/test_project_imports.py
```

Criteria:

- import requires project;
- project_products created;
- products from project A do not appear in project B.

### Commit 4 — Effective card

```text
feat: add effective product card service
```

Files:

```text
app/effective_card/
app/editor/service.py
app/editor/repository.py
app/products/versioning.py
tests/test_effective_card.py
```

Criteria:

- no persisted version -> source card;
- applied version -> effective card;
- draft/AI proposal does not affect effective card;
- same Product in two projects can have different effective cards.

### Commit 5 — Reimport and overrides

```text
feat: preserve manual overrides on reimport
```

Files:

```text
app/projects/imports.py
app/effective_card/service.py
app/domain/events/
tests/test_project_reimport.py
```

Criteria:

- source update detected;
- manual override preserved;
- duplicate version not created if effective card unchanged.

### Commit 6 — Quality comparison

```text
feat: add project quality comparison
```

Files:

```text
app/projects/quality.py
app/analytics/store_analyzer.py
app/web/routes/projects.py
tests/test_project_quality.py
```

Criteria:

- source score;
- effective score;
- draft preview score.

### Commit 7 — Safe exports

```text
feat: add safe product exports
```

Files:

```text
app/exports/
app/exporter.py
app/web/routes/projects.py
tests/test_project_exports.py
```

Criteria:

- CSV;
- JSON;
- XLSX;
- formula injection neutralized;
- export path stays inside project workspace.

### Commit 8 — Client delivery report

```text
feat: add client delivery report
```

Files:

```text
app/reports/
app/reporter.py
app/web/routes/projects.py
tests/test_client_delivery_report.py
```

Criteria:

- HTML report;
- JSON report;
- CSV summary;
- report contains project-only data.

### Commit 9 — Project workflow UI

```text
feat: add project workflow UI
```

Files:

```text
app/web/routes/projects.py
app/web/templates/projects.html
app/web/templates/project_detail.html
app/web/templates/project_import.html
app/web/templates/project_products.html
app/web/templates/project_reports.html
app/web/templates/project_exports.html
app/web/templates/base.html
tests/test_projects_ui.py
```

Criteria:

- Russian UI;
- project dashboard;
- no login;
- no SaaS concepts.

### Commit 10 — Docs and report

```text
docs: add P6 client workflow report
```

Files:

```text
docs/P6_CLIENT_WORKFLOW_REPORT.md
docs/DEVELOPMENT_PLAN.md
docs/PROJECT_AUDIT.md
```

## 17. Test plan

Focused tests:

```text
tests/test_client_projects.py
tests/test_project_files.py
tests/test_project_imports.py
tests/test_effective_card.py
tests/test_project_reimport.py
tests/test_project_quality.py
tests/test_project_exports.py
tests/test_client_delivery_report.py
tests/test_projects_ui.py
tests/test_card_editor.py
tests/test_product_detail.py
tests/test_product_versions.py
tests/test_timeline_engine.py
tests/test_domain_events.py
```

Full checks:

```text
.venv/bin/python -m pytest
RUFF_CACHE_DIR=/tmp/marketmind-ai-core-ruff .venv/bin/python -m ruff check <new/changed P6 files>
git diff --check
.venv/bin/python project_skills/validate_skills.py
```

If migration is added:

```text
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

Use a temporary SQLite DB, not user data.

## 18. Risks

### High

Project context can be bypassed if legacy helpers like `get_all_products()` are reused in project routes.

Mitigation: introduce project repositories and forbid project routes from using global catalog helpers directly.

### High

Manual overrides can leak across projects if editor keeps applying snapshots to global `Product`.

Mitigation: project-aware editor path must write project-scoped versions and effective cards. Legacy editor endpoints remain for compatibility, but project UI uses project-aware endpoints.

### Medium

One global `Product` can be linked to multiple projects through `ProjectProduct`, but legacy Product Detail pages remain global.

Mitigation: project UI links to `/projects/{project_id}/products/{product_id}`.

### Medium

CSV/XLSX formula injection.

Mitigation: shared sanitizer and explicit tests.

### Medium

Workspace paths could be unsafe if user-provided filenames are used.

Mitigation: server-generated filenames, path containment checks, manifest.

### Low

Full Ruff legacy backlog remains.

Mitigation: P6 files must be clean; legacy backlog remains documented.

## 19. What not to do in P6

Do not implement:

- auth;
- roles;
- customer accounts;
- payments;
- subscriptions;
- marketplace publishing;
- email;
- SaaS CSRF/session layer;
- transactional outbox.

Do not mass-refactor:

- Telegram;
- worker;
- agent analytics;
- old global routes.

## 20. Can implementation start?

Yes, after explicit approval.

Implementation is safe if it follows these constraints:

1. new project features are added alongside old APIs;
2. `ProjectProduct` is used instead of only `Product.client_project_id`;
3. EffectiveProductCardService becomes the source for project export/report/detail;
4. old global endpoints stay compatible;
5. migration is additive and nullable for existing rows;
6. tests prove project isolation and export safety.
