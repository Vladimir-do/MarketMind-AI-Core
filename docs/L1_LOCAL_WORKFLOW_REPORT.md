# L1 Local Workflow Report

Дата: 2026-07-17

## Исходное состояние

Репозиторий был чистым. Подтверждены локальные P6-коммиты:

- `85ed488 feat: add local client project foundation`
- `81c56d0 feat: add project workflow exports and reports`
- `63d42f2 test: cover client project workflow`

Remote не настроен, push не выполнялся.

## Найденные проблемы

1. Импорт сразу создавал товары без отдельного preview и mapping.
2. Метаданные импортированного файла были неполными: не хранились schema version, encoding, delimiter, selected sheet, counts и structured summary.
3. Project-aware rollback существовал в сервисе, но не был доступен через project API.
4. Effective Card не раскрывала provenance по полям.
5. Экспорт не хранил manifest и checksum.
6. Formula protection экранировала отрицательные числовые строки вроде `-10`.
7. Полный Ruff содержит legacy backlog вне L1 scope.

## Что исправлено

- Добавлен безопасный import preview для CSV/XLSX/XLSM.
- Добавлено сопоставление колонок через JSON mapping.
- CSV preview определяет UTF-8 BOM и разделитель `,`/`;`.
- CSV корректно читает quoted multiline values через стандартный `csv`.
- Excel preview показывает листы, выбранный лист и предупреждает о hidden sheets.
- XLSX/XLSM читаются только как данные через `openpyxl(data_only=True)`, макросы не выполняются.
- Повторный импорт по `project_id + sha256` не проходит молча: требуется `confirm_duplicate`.
- Unknown columns сохраняются в `attributes`.
- Добавлены structured row errors с русскими сообщениями.
- Добавлен project-aware rollback endpoint.
- Effective Card возвращает per-field provenance.
- Export manifest и checksum сохраняются в `ProjectExport`.
- Formula injection защита сохраняет отрицательные числа как числа.
- Ограничение размера файла применяется до записи в workspace.

## Изменённые файлы

- `app/config.py`
- `app/database.py`
- `app/projects/imports.py`
- `app/projects/service.py`
- `app/workspace/files.py`
- `app/effective_card/service.py`
- `app/exports/safety.py`
- `app/exports/service.py`
- `app/web/routes/projects.py`
- `app/web/templates/project_import.html`
- `tests/test_client_projects.py`
- `docs/L1_LOCAL_WORKFLOW_AUDIT.md`
- `docs/L1_LOCAL_WORKFLOW_IMPLEMENTATION_PLAN.md`
- `docs/L1_LOCAL_WORKFLOW_REPORT.md`

## Миграции

Добавлена миграция:

- `alembic/versions/b2c3d4e5f6a7_add_l1_workflow_metadata.py`

Она расширяет:

- `client_project_files`;
- `project_exports`.

Новые таблицы не создавались.

## Архитектурные решения

1. `Product.client_project_id` не добавлялся. Изоляция остаётся через `ProjectProduct`.
2. Preview не создаёт товары и не меняет карточки.
3. Effective Card остаётся вычисляемой read-model.
4. Export строится только из Effective Card.
5. Manifest хранится в `ProjectExport`, а не в отдельной таблице.
6. Legacy global endpoints не удалялись, но project UI работает через project-aware routes.

## Результаты проверок

| Проверка | Результат |
|---|---|
| Baseline full pytest до правок | 514 passed, 24 warnings, 14 subtests passed |
| Focused P4/P5/P6 после правок | 60 passed |
| `tests/test_client_projects.py` | 11 passed |
| Full pytest после правок | 518 passed, 24 warnings, 14 subtests passed |
| Ruff по новым/изменённым L1/P6 файлам | All checks passed |
| Full Ruff diagnostic | 268 legacy errors |
| `git diff --check` | passed |
| Alembic upgrade -> downgrade -> upgrade на временной SQLite | passed |
| Skill validation | passed |

## Happy path

Покрыт тестами:

1. создать проект;
2. загрузить CSV;
3. получить preview;
4. применить mapping;
5. импортировать товар;
6. открыть Effective Card;
7. создать и применить черновик;
8. выполнить project-aware rollback;
9. экспортировать результат;
10. получить export manifest;
11. сформировать отчёт.

## Известные ограничения

- UI mapping пока минимальный: подробное интерактивное сопоставление колонок доступно через JSON API, а HTML-страница показывает preview и быстрый импорт.
- Официальные шаблоны Ozon/Wildberries/Яндекс Маркет не реализованы. Текущие профили являются подготовительными.
- Full Ruff backlog остаётся legacy-долгом и не исправлялся массово.
- Внешний LLM не получает файл автоматически; отдельный расширенный тест prompt injection оставлен для следующего AI-safety этапа.

## Что специально не делалось

- Не добавлялись логин, роли, SaaS, billing, Redis, Celery, Seller API sync.
- Не менялась архитектура на микросервисы.
- Не удалялись legacy endpoints.
- Не выполнялся push.

## Следующие действия

1. Сделать полноценную HTML-форму mapping колонок без JSON-ручного ввода.
2. Добавить экран детального результата импорта с row-level errors.
3. Завести отдельный этап официальных marketplace export adapters.
4. Разобрать legacy Ruff backlog отдельным планом.

## Commits

- `cd165f5 feat: add local workflow metadata schema`
- `05b4a2f feat: strengthen local project import and exports`
- `25685aa test: cover local workflow import and rollback`
