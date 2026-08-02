# L1 Local Workflow Implementation Plan

## Goal

Довести локальный путь оператора до рабочего состояния без превращения проекта в SaaS:

Файл заказчика -> preview -> mapping -> частичный импорт -> project effective card -> ручная правка/rollback -> export -> отчёт.

## Scope

В реализации меняются только существующие локальные project-workflow слои:

- `app/config.py`
- `app/database.py`
- `app/importers/*`
- `app/projects/*`
- `app/workspace/*`
- `app/effective_card/*`
- `app/exports/*`
- `app/reports/*`
- `app/web/routes/projects.py`
- `app/web/templates/project_*.html`
- Alembic migrations
- P6/L1 tests
- L1 docs

Не делается:

- регистрация;
- авторизация;
- роли;
- SaaS;
- Seller API sync;
- Redis/Celery;
- официальный экспорт в маркетплейсы;
- автоматическое применение AI.

## Implementation phases

### 1. Schema and settings

Add safe import/export metadata:

- import schema version;
- encoding;
- CSV delimiter;
- selected sheet;
- successful/warning/error row counts;
- structured import summary;
- export schema version;
- export manifest JSON;
- export file checksum.

Use a reversible Alembic migration. Existing rows must remain valid.

### 2. Import preview and mapping

Create a small project import analysis layer:

- CSV dialect sniffing for comma/semicolon;
- UTF-8 and UTF-8 BOM;
- quoted newlines through Python csv module;
- Excel workbook metadata with hidden sheet warnings;
- XLSM read-only/data-only handling;
- extension/content mismatch checks;
- safe limits from config;
- preview rows;
- guessed column mapping;
- unknown columns retained as extra attributes or explicitly reported.

Add API:

- `POST /api/projects/{project_id}/imports/preview`
- enhance `POST /api/projects/{project_id}/imports` to accept mapping/sheet/confirm flags.

Preview writes only the source file to workspace and a `pending_preview` file record; it does not create products.

### 3. Partial import policy

Import applies only valid rows by default. Invalid rows remain in file record summary with row/column/code/message/recommendation. Duplicate file import is blocked unless the request explicitly confirms it.

### 4. Project isolation and rollback

Add project-aware rollback API:

- `POST /api/projects/{project_id}/products/{product_id}/versions/{version_number}/rollback`

It must call existing `ProductCardEditorService.rollback_version` with `project_id` and `project_product_id`.

### 5. Effective Card provenance

Extend `EffectiveProductCard.to_dict()` with per-field provenance:

- source type;
- project file id;
- source row;
- source column where known;
- original value;
- normalized/effective value;
- version id;
- changed timestamp;
- reason/actor where known.

This remains computed, not a duplicated table.

### 6. Export manifest and formula safety

Export continues to use only Effective Card.

Add manifest:

- project id;
- export id;
- format;
- schema version;
- generated_at;
- source file hashes;
- product count;
- warnings/errors;
- effective version ids;
- output checksum.

Fix formula protection so text formulas are escaped but numeric negative values are preserved.

### 7. UI

Keep existing FastAPI/Jinja/HTMX UI. Add minimal Russian screens/blocks:

- file preview;
- column mapping;
- import result;
- rollback action;
- export manifest visibility.

Do not redesign the frontend.

### 8. Tests

Add focused tests for:

- CSV UTF-8 BOM;
- semicolon delimiter;
- quoted multiline;
- unknown columns into attributes;
- Excel multi-sheet and XLSM read-only import;
- invalid extension/content mismatch;
- duplicate SHA;
- partial import;
- project-aware rollback and forbidden cross-project rollback;
- Effective Card provenance;
- export manifest;
- negative numbers not escaped;
- formula strings escaped;
- happy path.

All tests use temporary files and temporary SQLite DB.

## Risks

1. Import preview may require storing uploaded file before DB product write. This is acceptable because source files already live in project workspace and are not public.
2. Excel formula values cannot be trusted. `openpyxl(data_only=True)` returns cached values only; formulas are never executed.
3. Full legacy Ruff backlog remains outside scope. New/changed files must be clean.
4. Legacy global endpoints remain global; project UI must not call them.

## Acceptance criteria

- Baseline behavior remains green.
- Preview does not create products.
- Mapping import creates project products.
- Duplicate import does not silently create duplicates.
- Effective Card includes provenance.
- Project rollback creates a new project version and does not mutate global Product.
- Export uses Effective Card and writes manifest/checksum.
- Formula injection is blocked without corrupting negative numeric values.
- Reports/docs match implementation.
