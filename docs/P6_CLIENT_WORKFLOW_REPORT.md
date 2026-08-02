# P6 Client Workflow Report

Дата: 2026-07-17

Этап: P6 MASTER STAGE — проекты заказчиков, Effective Card и экспорт результатов.

## Что сделано

Добавлена локальная проектная область для выполнения заказов:

- `ClientProject`;
- `ClientProjectFile`;
- `ProjectProduct`;
- `ProjectExport`;
- `ProjectReport`;
- безопасный workspace проекта;
- project-scoped import;
- project-scoped Effective Product Card;
- project-scoped export preview/export;
- project-scoped client report;
- минимальный русский UI для проектов.

Старые API не удалялись и не переименовывались:

```text
/api/products/{id}/history
/api/products/{id}/timeline
/api/products/{id}/versions
/api/products/{id}/drafts
/api/products/{id}/audit
```

## Архитектура

Новый поток данных:

```text
ClientProject
→ ClientProjectFile
→ ProjectProduct
→ Product / source data
→ ProductCardDraft
→ ProductCardVersion в проектном контексте
→ EffectiveProductCard
→ ProjectExport
→ ProjectReport
```

`Product` остаётся legacy/source entity. Рабочий контекст заказа создаётся через `ProjectProduct`, чтобы один и тот же глобальный товар мог использоваться в разных проектах без смешивания ручных правок.

## Effective Product Card

Effective card строится по правилу:

```text
latest source snapshot
+
latest applied ProductCardVersion in project
=
effective snapshot
```

Черновик и AI-предложение не являются effective card.

Проектный apply draft создаёт версию и Domain Event в проектном контексте, но не перезаписывает глобальный `Product`. Legacy editor endpoints сохраняют прежнее поведение для обратной совместимости.

## Workspace

Добавлен safe workspace:

```text
workspace/
  projects/
    <project_id>/
      source/
      exports/
      reports/
```

Исходные файлы:

- сохраняются с серверным безопасным именем;
- получают SHA-256;
- не используют пользовательское имя как путь;
- не могут выйти за пределы директории проекта;
- поддерживают CSV, XLSX, XLSM.

## Экспорт

Добавлены project exports:

- CSV;
- JSON;
- XLSX.

Экспорт использует только `EffectiveProductCard`.

Добавлена защита CSV/XLSX от formula injection для строк, начинающихся с:

```text
=
+
-
@
```

Профили экспорта называются подготовительными, не официальными шаблонами маркетплейсов.

## Итоговый отчёт

Добавлен client delivery report:

- HTML;
- JSON;
- CSV summary.

PDF не добавлялся.

Отчёт показывает:

- проект;
- заказчика;
- исходный файл;
- количество товаров;
- Quality Score до и после;
- изменённые карточки;
- основные проблемы;
- выполненные исправления;
- карточки, требующие проверки.

## API

Добавлены project-aware endpoints:

```text
POST   /api/projects
GET    /api/projects
GET    /api/projects/{project_id}
PATCH  /api/projects/{project_id}
POST   /api/projects/{project_id}/archive

POST   /api/projects/{project_id}/imports
GET    /api/projects/{project_id}/imports

GET    /api/projects/{project_id}/products
GET    /api/projects/{project_id}/products/{product_id}
GET    /api/projects/{project_id}/products/{product_id}/effective-card
GET    /api/projects/{project_id}/products/{product_id}/quality

POST   /api/projects/{project_id}/products/{product_id}/drafts
POST   /api/projects/{project_id}/products/{product_id}/drafts/{draft_id}/apply
POST   /api/projects/{project_id}/products/{product_id}/drafts/{draft_id}/quality-preview

GET    /api/projects/{project_id}/export-preview
POST   /api/projects/{project_id}/exports
GET    /api/projects/{project_id}/exports

GET    /api/projects/{project_id}/report-preview
POST   /api/projects/{project_id}/reports
GET    /api/projects/{project_id}/reports
```

## UI

Добавлены страницы:

```text
/projects
/projects/new
/projects/{project_id}
/projects/{project_id}/import
/projects/{project_id}/products
/projects/{project_id}/reports
/projects/{project_id}/exports
```

Экран входа не добавлялся.

## Миграция

Добавлена миграция:

```text
alembic/versions/a1b2c3d4e5f6_add_client_projects.py
```

Проверено:

```text
upgrade head
downgrade -1
upgrade head
```

на временной SQLite-БД.

## Тесты

Добавлен focused test file:

```text
tests/test_client_projects.py
```

Покрыто:

- создание проекта;
- изменение проекта;
- архивирование;
- импорт CSV;
- сохранение SHA-256 файла;
- безопасное имя файла;
- project product isolation;
- project-specific effective card;
- draft apply без изменения другого проекта;
- export preview;
- CSV formula injection sanitization;
- client report;
- unsupported import format.

## Проверки

Focused P6/P5/P4:

```text
56 passed
```

Полный pytest:

```text
514 passed, 24 warnings, 14 subtests passed
```

Ruff по новым и изменённым P6-файлам:

```text
All checks passed
```

Skillpack validation:

```text
Validation passed: 48 indexed skill(s), 48 markdown skill(s), 0 warning(s).
```

Whitespace:

```text
git diff --check passed
```

## Оставшиеся ограничения

1. Старые глобальные endpoints остаются legacy-compatible и всё ещё показывают глобальный каталог.
2. Telegram/agent exports пока используют старый глобальный экспорт.
3. Project UI минимальный и требует дальнейшей полировки.
4. Project-aware rollback endpoint пока не вынесен в отдельный route.
5. Полный Ruff по всему проекту всё ещё содержит legacy backlog, как было до P6.
6. XLSX export реализован через уже существующий `openpyxl`, без официальных marketplace templates.

## Push

Push не выполнялся.
