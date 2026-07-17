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
- Добавлено сопоставление колонок через web-интерфейс.
- CSV preview определяет UTF-8 BOM и разделитель `,`/`;`.
- CSV корректно читает quoted multiline values через стандартный `csv`.
- Excel preview показывает листы, выбранный лист и предупреждает о hidden sheets.
- XLSX/XLSM читаются только как данные через `openpyxl(data_only=True)`, макросы не выполняются.
- Повторный импорт по `project_id + sha256` не проходит молча: требуется `confirm_duplicate`.
- Unknown columns сохраняются в `attributes`.
- Добавлены structured row errors с русскими сообщениями.
- Добавлен project-aware rollback endpoint.
- Добавлены project-aware страницы карточки, ручной правки и версий.
- Effective Card возвращает per-field provenance.
- Export manifest и checksum сохраняются в `ProjectExport`.
- Formula injection защита сохраняет отрицательные числа как числа.
- Ограничение размера файла применяется до записи в workspace.
- Добавлена защита от ZIP-bomb и слишком большого числа колонок.
- Добавлены безопасные download routes для экспортов и отчётов.
- AI prompt теперь явно маркирует данные товара как недоверенный клиентский текст.
- L1.1: добавлены presets сопоставления колонок.
- L1.1: добавлена безопасная поддержка Windows-1251 с обязательным подтверждением.
- L1.1: preview показывает фильтры ошибок и CSV-отчёт ошибок.
- L1.1: строки с нечисловыми числовыми полями не импортируются как корректные товары.
- L1.1: числовой остаток нормализуется в `in_stock/out_of_stock`, исходное число остаётся характеристикой.
- L1.1: добавлен воспроизводимый demo fixture и script для ручной приёмки владельцем.

## Изменённые файлы

- `app/config.py`
- `app/database.py`
- `app/projects/imports.py`
- `app/projects/service.py`
- `alembic/versions/c3d4e5f6a7b8_add_import_mapping_presets.py`
- `app/workspace/files.py`
- `app/effective_card/service.py`
- `app/exports/safety.py`
- `app/exports/service.py`
- `app/web/routes/projects.py`
- `app/web/templates/project_import.html`
- `app/web/templates/project_import_preview.html`
- `app/web/templates/project_import_result.html`
- `app/web/templates/project_product_detail.html`
- `app/web/templates/project_product_edit.html`
- `app/web/templates/project_manual_edit_preview.html`
- `app/web/templates/project_action_result.html`
- `app/web/templates/project_product_versions.html`
- `app/web/templates/project_exports.html`
- `app/web/templates/project_reports.html`
- `tests/test_client_projects.py`
- `tests/test_l1_1_final_acceptance.py`
- `tests/fixtures/l1_demo_products.csv`
- `tests/helpers.py`
- `scripts/l1_acceptance_demo.py`
- `app/ai_recommendation/engine.py`
- `docs/L1_LOCAL_WORKFLOW_AUDIT.md`
- `docs/L1_LOCAL_WORKFLOW_IMPLEMENTATION_PLAN.md`
- `docs/L1_LOCAL_WORKFLOW_REPORT.md`
- `docs/L1_REQUIREMENTS_TRACEABILITY.md`
- `docs/L1_UI_ACCEPTANCE_REPORT.md`
- `docs/L1_MANUAL_ACCEPTANCE.md`
- `docs/LEGACY_RUFF_BACKLOG.md`
- `docs/L1_1_FINAL_ACCEPTANCE_REPORT.md`

## Миграции

Добавлена миграция:

- `alembic/versions/b2c3d4e5f6a7_add_l1_workflow_metadata.py`
- `alembic/versions/c3d4e5f6a7b8_add_import_mapping_presets.py`

Она расширяет:

- `client_project_files`;
- `project_exports`.

L1.1 создаёт локальную таблицу `import_mapping_presets` для project-scoped presets сопоставления колонок.

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
| Focused P4/P5/P6/L1 после gap fixes | 72 passed |
| Focused P4/P5/P6/L1/L1.1 после final acceptance fixes | 81 passed |
| `tests/test_client_projects.py` | 23 passed |
| Full pytest после gap fixes | 530 passed, 24 warnings, 14 subtests passed |
| Full pytest после L1.1 | 537 passed, 24 warnings, 14 subtests passed |
| Ruff по новым/изменённым L1/P6 файлам | All checks passed |
| Full Ruff diagnostic | 267 legacy errors |
| `git diff --check` | passed |
| Alembic upgrade -> downgrade -> upgrade на временной SQLite | passed |
| Skill validation | passed |
| UI TCP smoke | BLOCKED by execution namespace; ASGI route workflow passed |
| L1.1 focused tests | 7 passed |
| `tests/test_client_projects.py` после L1.1 | 23 passed |

## Happy path

Покрыт тестами:

1. создать проект;
2. загрузить CSV/XLSX/XLSM;
3. получить preview;
4. выбрать mapping в UI;
5. подтвердить warnings/duplicate;
6. импортировать товар;
7. открыть Effective Card;
8. открыть ручной редактор;
9. увидеть diff перед применением;
10. применить правку;
11. открыть версии;
12. выполнить project-aware rollback;
13. экспортировать CSV/JSON/XLSX;
14. получить export manifest/checksum;
15. сформировать отчёт.

## Известные ограничения

- Presets mapping сохраняются локально в рамках проекта. Межпроектный перенос preset намеренно не автоматизирован.
- Фильтры ошибок реализованы на preview-странице; полная ручная браузерная приёмка владельцем ожидается.
- Официальные шаблоны Ozon/Wildberries/Яндекс Маркет не реализованы. Текущие профили являются подготовительными.
- Full Ruff backlog остаётся legacy-долгом и не исправлялся массово.
- Внешний LLM не получает файл автоматически; prompt-injection строка проверена как недоверенный текст товара.
- Полноценный TCP/browser smoke из Codex окружения ограничен; подготовлен `scripts/l1_acceptance_demo.py` и инструкция `docs/L1_MANUAL_ACCEPTANCE.md`.

## Что специально не делалось

- Не добавлялись логин, роли, SaaS, billing, Redis, Celery, Seller API sync.
- Не менялась архитектура на микросервисы.
- Не удалялись legacy endpoints.
- Не выполнялся push.

## Следующие действия

1. Добавить сохранение presets mapping между импортами.
2. Добавить интерактивный фильтр ошибок/предупреждений в большом preview.
3. Завести отдельный этап официальных marketplace export adapters.
4. Разобрать legacy Ruff backlog отдельным планом.

## Commits

- `cd165f5 feat: add local workflow metadata schema`
- `05b4a2f feat: strengthen local project import and exports`
- `25685aa test: cover local workflow import and rollback`
- `60b195d feat: close local workflow UI and safety gaps`
- `2bf3dca test: verify local workflow requirement gaps`
- `2a5f6f2 docs: add L1 traceability and UI acceptance`
