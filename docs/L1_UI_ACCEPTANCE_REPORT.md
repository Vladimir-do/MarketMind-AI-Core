# L1 UI Acceptance Report

Дата: 2026-07-19

## Scope

Проверялся локальный single-operator workflow:

Проект -> файл -> preview -> mapping -> импорт -> карточка -> правка -> версии -> откат -> экспорт -> отчёт.

## UI routes

| Шаг | Route | Статус | Доказательство |
|---|---|---|---|
| Список проектов | `/projects` | VERIFIED | `projects_page`, template `projects.html` |
| Создание проекта | `/projects/new` + `POST /api/projects` | VERIFIED | `test_project_crud_and_archive` |
| Карточка проекта | `/projects/{project_id}` | VERIFIED | `project_detail_page` |
| Загрузка файла | `/projects/{project_id}/import` | VERIFIED | `project_import.html` |
| Preview файла | `POST /api/projects/{project_id}/imports/preview` | VERIFIED | `project_import_preview.html` |
| Mapping колонок | HTMX partial selects | VERIFIED | `project_import_preview.html` |
| Presets mapping | Save/select/delete controls | VERIFIED | `test_mapping_presets_can_be_saved_suggested_and_deleted` |
| Подтверждение warnings/duplicate | Required checkboxes | VERIFIED | `test_uncertain_csv_delimiter_requires_operator_confirmation`, `test_duplicate_import_requires_explicit_confirmation` |
| Фильтрация ошибок | Preview filters + CSV report | VERIFIED | `test_import_error_report_csv_is_downloadable_and_sanitized` |
| Результат импорта | `project_import_result.html` | VERIFIED | HTMX target |
| Список товаров | `/projects/{project_id}/products` | VERIFIED | `test_project_manual_edit_ui_pages_render_safe_workflow` |
| Effective Card | `/projects/{project_id}/products/{product_id}` | VERIFIED | `project_product_detail.html` |
| Ручной редактор | `/projects/{project_id}/products/{product_id}/edit` | VERIFIED | `project_product_edit.html` |
| Diff перед применением | `POST /projects/{project_id}/products/{product_id}/manual-edit/preview` | VERIFIED | `project_manual_edit_preview.html` |
| Применение правки | `POST /projects/{project_id}/products/{product_id}/manual-edit/apply` | VERIFIED | service apply transaction |
| Версии | `/projects/{project_id}/products/{product_id}/versions` | VERIFIED | `project_product_versions.html` |
| Project-aware rollback | `POST /api/projects/{project_id}/products/{product_id}/versions/{version}/rollback` | VERIFIED | rollback tests |
| Экспорт | `/projects/{project_id}/exports` | VERIFIED | CSV/JSON/XLSX buttons |
| Скачивание экспорта | `/projects/{project_id}/exports/{export_id}/download` | VERIFIED | route ownership check |
| Отчёты | `/projects/{project_id}/reports` | VERIFIED | HTML/JSON/CSV buttons |
| Скачивание отчёта | `/projects/{project_id}/reports/{report_id}/download` | VERIFIED | route ownership check |

## Findings fixed after gap audit

1. Старый прямой импорт был виден как основной путь. Теперь UI ведёт через preview/mapping.
2. Mapping был доступен только через JSON API. Теперь есть HTML select per column.
3. Не было project-aware product detail/edit/version pages. Добавлены страницы проекта.
4. Не было download route для export/report artifacts. Добавлены безопасные project-owned routes.
5. Rollback reason не был обязательным на route level. Добавлена проверка.

## Manual acceptance

План проверки локальным FastAPI сервером и HTTP-запросами к HTML/API:

1. `/projects` открывается.
2. `/projects/new` открывается.
3. После создания проекта открывается `/projects/{id}`.
4. `/projects/{id}/import` содержит только preview-first путь.
5. HTMX preview возвращает форму mapping.
6. После import товар появляется в `/projects/{id}/products`.
7. `/projects/{id}/products/{product_id}` показывает Effective Card и provenance.
8. `/projects/{id}/products/{product_id}/edit` показывает форму ручной правки.
9. Manual edit preview показывает diff до применения.
10. `/projects/{id}/products/{product_id}/versions` показывает версии и форму rollback.
11. `/projects/{id}/exports` создаёт CSV/JSON/XLSX.
12. `/projects/{id}/reports` создаёт HTML/JSON/CSV отчёт.

## Execution result

- FastAPI/Uvicorn успешно стартовал на временной SQLite-БД.
- Порты `8765` и `8766` в окружении заняты служебными Codex/WebSocket процессами.
- Порт `18080` был поднят Uvicorn, но отдельный `exec` namespace не смог подключиться к серверу (`curl: Couldn't connect to server`), то есть полноценный TCP smoke заблокирован средой выполнения.
- Эквивалентный маршрутный workflow проверен через ASGI/HTTP tests:
  - `tests/test_client_projects.py::test_project_manual_edit_ui_pages_render_safe_workflow`;
  - import preview/mapping tests;
  - project rollback tests;
  - export/report tests.

## Final browser PRG check

После исправления project export/report forms demo-сервер был перезапущен из commit `95f6245` через `./start_l1_demo.sh` на `http://127.0.0.1:18080`.

Владелец подтвердил в реальном браузере:

- CSV export создаётся;
- CSV export скачивается;
- HTML-отчёт создаётся;
- HTML-отчёт скачивается.

Результат: `PASSED`.

## L1.1 update

- Добавлено сохранение, выбор и удаление presets сопоставления колонок.
- Добавлен suggested preset по fingerprint заголовков.
- Добавлены фильтры ошибок: все, ошибки, предупреждения, код, колонка, строка, текстовый поиск.
- Добавлена выгрузка CSV отчёта ошибок с защитой от formula injection.
- Добавлен demo-сценарий `scripts/l1_acceptance_demo.py`.
- Добавлена инструкция владельца `docs/L1_MANUAL_ACCEPTANCE.md`.

## Remaining UI limitations

- Полная пользовательская проверка финального export/report PRG smoke выполнена владельцем: `PASSED`.
- Download route проверен route-level, artifact-level и финальным браузерным smoke для CSV export и HTML report.
