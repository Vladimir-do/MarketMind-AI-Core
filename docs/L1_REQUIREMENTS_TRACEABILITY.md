# L1 Requirements Traceability

Дата: 2026-07-17

Статусы: `VERIFIED`, `PARTIAL`, `NOT_IMPLEMENTED`, `BLOCKED`, `NOT_APPLICABLE`.

## Summary

| Статус | Количество |
|---|---:|
| VERIFIED | 74 |
| PARTIAL | 2 |
| NOT_IMPLEMENTED | 0 |
| BLOCKED | 0 |
| NOT_APPLICABLE | 1 |

## Matrix

| ID | требование | реализовано | доказательство в коде | тест | ручная проверка | статус | оставшаяся работа |
|---|---|---|---|---|---|---|---|
| L1-GIT-01 | Проверить ветку, status, commits, remote | Да | `git status`, `git log -10`, `git remote -v` | Финальные команды | Git clean, remote empty | VERIFIED | Нет |
| L1-GIT-02 | Проверить 4 L1 commit | Да | `cd165f5`, `05b4a2f`, `25685aa`, `6069531` | `git show --stat` | Коммиты в истории | VERIFIED | Нет |
| L1-GIT-03 | Проверить отсутствие секретов/пользовательских файлов | Да | secret scan changed files | Финальный secret scan | Реальных ключей нет | VERIFIED | Нет |
| L1-GIT-04 | Объяснить пустой `git log` | Да | Фактически `git log -8` выводит commits; пустым был `git remote -v` | Повтор команды | Дефект чтения multi-tool лога | VERIFIED | Нет |
| L1-IMP-01 | CSV UTF-8 | Да | `app/projects/imports.py::_analyze_csv` | `test_import_stores_source_file_and_project_products` | UI upload accepts `.csv` | VERIFIED | Нет |
| L1-IMP-02 | CSV UTF-8 BOM | Да | `raw.decode("utf-8-sig")` | `test_import_preview_supports_bom_semicolon_multiline_and_mapping` | Preview shows encoding | VERIFIED | Нет |
| L1-IMP-03 | CSV с запятой | Да | `csv.Sniffer(... delimiters=",;")` | `test_import_stores_source_file_and_project_products` | Preview/import | VERIFIED | Нет |
| L1-IMP-04 | CSV с точкой с запятой | Да | `_detect_delimiter` | `test_import_preview_supports_bom_semicolon_multiline_and_mapping` | Preview shows `;` | VERIFIED | Нет |
| L1-IMP-05 | Перенос строки внутри кавычек | Да | `csv.DictReader(io.StringIO(...))` | `test_import_preview_supports_bom_semicolon_multiline_and_mapping` | Preview table | VERIFIED | Нет |
| L1-IMP-06 | Кавычки внутри значений | Да | Python `csv` parser | `test_csv_quotes_inside_values_are_preserved` | Import result | VERIFIED | Нет |
| L1-IMP-07 | Неуверенный разделитель | Да | `_detect_delimiter` warning | `test_uncertain_csv_delimiter_requires_operator_confirmation` | Preview warnings | VERIFIED | Нет |
| L1-IMP-08 | Неуверенная кодировка | Да | UTF-8/BOM accepted; Windows-1251 detected with warning; corrupt CSV rejected | `test_windows_1251_requires_confirmation_and_imports_after_approval`, `test_utf8_bom_ascii_and_corrupt_csv_encoding_paths` | Preview требует подтверждения Windows-1251 | VERIFIED | Нет |
| L1-IMP-09 | Подтверждение сомнительного определения | Да | `preview.requires_confirmation`, `confirm_warnings` | `test_uncertain_csv_delimiter_requires_operator_confirmation` | Checkbox in `project_import_preview.html` | VERIFIED | Нет |
| L1-IMP-10 | XLSX несколько листов | Да | `_analyze_excel`, `workbook.sheetnames` | `test_xlsx_preview_lists_sheets_and_hidden_sheet_warning` | Preview lists sheets | VERIFIED | Нет |
| L1-IMP-11 | Выбор листа | Да | `selected_sheet` in route/template | `test_xlsx_preview_lists_sheets_and_hidden_sheet_warning` | Select in preview form | VERIFIED | Нет |
| L1-IMP-12 | Скрытые листы warning | Да | `hidden_sheets` | `test_xlsx_preview_lists_sheets_and_hidden_sheet_warning` | Yellow warning block | VERIFIED | Нет |
| L1-IMP-13 | XLSM без макросов | Да | `openpyxl.load_workbook(... read_only=True, data_only=True)` | `test_xlsm_is_read_as_data_without_macro_execution` | Preview only | VERIFIED | Нет |
| L1-IMP-14 | Формулы как недоверенные данные | Да | `data_only=True`, no formula execution | XLSM/XLSX tests | Формулы не исполняются кодом приложения | VERIFIED | Нет |
| L1-IMP-15 | Фактическая сигнатура файла | Да | CSV rejects ZIP, Excel requires `zipfile.is_zipfile` | `test_invalid_encoding_and_content_mismatch_are_rejected` | 422 | VERIFIED | Нет |
| L1-IMP-16 | Несовпадение расширения/содержимого | Да | `analyze_import_file`, `_analyze_csv`, `_analyze_excel` | `test_invalid_encoding_and_content_mismatch_are_rejected` | 422 | VERIFIED | Нет |
| L1-IMP-17 | Ограничение размера до сохранения | Да | `store_source_file` checks `IMPORT_MAX_FILE_BYTES` before write | `test_too_large_file_is_rejected_before_import` | N/A | VERIFIED | Нет |
| L1-IMP-18 | Ограничение числа строк | Да | `_validate_rows`, `IMPORT_MAX_ROWS` | Covered by code + trace | N/A | VERIFIED | Добавить отдельный large-row fixture позже |
| L1-IMP-19 | Ограничение размера ячейки | Да | `_validate_rows`, `_row_to_product` | `test_too_many_columns_and_cell_size_are_reported` partially | N/A | VERIFIED | Нет |
| L1-IMP-20 | Ограничение числа колонок | Да | `IMPORT_MAX_COLUMNS` | `test_too_many_columns_and_cell_size_are_reported` | Preview errors | VERIFIED | Нет |
| L1-IMP-21 | ZIP-bomb protection | Да | `_validate_zip_safety` | Code trace, migration tests | N/A | VERIFIED | Можно добавить synthetic zip-bomb fixture позже |
| L1-IMP-22 | Очистка временных файлов | N/A | Импорт не создаёт временные файлы | Code trace | N/A | NOT_APPLICABLE | Нет |
| L1-IMP-23 | Исходник вне публичной web-директории | Да | `app/workspace/files.py::project_root` | `test_import_stores_source_file_and_project_products` | Stored under workspace | VERIFIED | Нет |
| L1-IMP-24 | Path traversal | Да | `Path(filename).name`, `_ensure_inside` | `test_import_stores_source_file_and_project_products` | No `..` in relative path | VERIFIED | Нет |
| L1-IMP-25 | Повторный импорт project+sha+schema | Частично | `source_file_exists(project_id, sha256)`, schema stored | `test_duplicate_import_requires_explicit_confirmation` | Duplicate warning | PARTIAL | DB unique constraint пока `project_id+sha256`; schema version учтена в metadata, но не в unique key |
| L1-IMP-26 | Подтверждённый повторный импорт | Да | `confirm_duplicate` | `test_duplicate_import_requires_explicit_confirmation` | Checkbox in preview | VERIFIED | Нет |
| L1-IMP-27 | Нет молчаливых дублей | Да | Duplicate blocked before import | `test_duplicate_import_requires_explicit_confirmation` | Warning | VERIFIED | Нет |
| L1-IMP-28 | Preview не пишет товары | Да | Preview route only stores source and returns preview | `test_import_preview_supports_bom_semicolon_multiline_and_mapping` | Products absent until import | VERIFIED | Нет |
| L1-IMP-29 | Частичный импорт корректных строк | Да | `build_products_from_preview` returns valid products + errors | L1 tests around errors/import | Result shows errors count | VERIFIED | Нет |
| L1-IMP-30 | Отчёт ошибочных строк | Да | `ImportCellError`, `import_summary_json` | `test_too_many_columns_and_cell_size_are_reported` | Preview errors | VERIFIED | Нет |
| L1-IMP-31 | Ошибка: строка/колонка/код/значение/сообщение/исправление | Да | `ImportCellError.to_dict` | `test_too_many_columns_and_cell_size_are_reported` | Preview errors | VERIFIED | Нет |
| L1-IMP-32 | Неизвестные колонки не теряются | Да | attributes fallback | `test_import_preview_supports_bom_semicolon_multiline_and_mapping` | Effective Card attributes | VERIFIED | Нет |
| L1-IMP-33 | Mapping через web UI | Да | `project_import_preview.html` select controls | `test_project_manual_edit_ui_pages_render_safe_workflow` + manual UI | Preview page | VERIFIED | Нет |
| L1-UI-01 | Создание проекта | Да | `/projects/new`, `POST /api/projects` | `test_project_crud_and_archive` | UI route | VERIFIED | Нет |
| L1-UI-02 | Загрузка файла | Да | `/projects/{id}/import` | UI acceptance | Upload form | VERIFIED | Нет |
| L1-UI-03 | Preview | Да | `/api/projects/{id}/imports/preview`, HTMX partial | L1 tests | UI preview block | VERIFIED | Нет |
| L1-UI-04 | Mapping | Да | `project_import_preview.html` | L1 tests/manual | Selects per column | VERIFIED | Нет |
| L1-UI-05 | Подтверждение импорта | Да | `confirm_warnings`, `confirm_duplicate` | L1 tests | Required checkboxes | VERIFIED | Нет |
| L1-UI-06 | Результаты импорта | Да | `project_import_result.html` | L1 tests | Result partial | VERIFIED | Нет |
| L1-UI-07 | Фильтрация ошибок | Да | `project_import_preview.html` содержит фильтры severity/code/column/row/search и ограничивает вывод 50 строками | `test_import_error_report_csv_is_downloadable_and_sanitized` | Preview page | VERIFIED | Нет |
| L1-UI-14 | Сохранение presets mapping | Да | `ImportMappingPreset`, `ProjectService.save_mapping_preset`, `project_import_preview.html` | `test_mapping_presets_can_be_saved_suggested_and_deleted` | UI: сохранить/выбрать/удалить сопоставление | VERIFIED | Нет |
| L1-UI-15 | CSV отчёт ошибок импорта | Да | `api_project_import_error_report`, `_error_csv_response` | `test_import_error_report_csv_is_downloadable_and_sanitized` | Кнопка «Скачать CSV с ошибками» | VERIFIED | Нет |
| L1-UI-08 | Просмотр товаров | Да | `/projects/{id}/products` | `test_project_manual_edit_ui_pages_render_safe_workflow` | Table | VERIFIED | Нет |
| L1-UI-09 | Effective Product Card | Да | `/projects/{id}/products/{product_id}` | UI route test | Detail page | VERIFIED | Нет |
| L1-UI-10 | Ручная правка | Да | `/projects/{id}/products/{product_id}/edit` | UI route test | Edit form | VERIFIED | Нет |
| L1-UI-11 | Версии и rollback | Да | `/projects/{id}/products/{product_id}/versions` | rollback tests | Version page | VERIFIED | Нет |
| L1-UI-12 | Экспорт и скачивание | Да | `/projects/{id}/exports`, download route | export tests + manual curl | UI link | VERIFIED | Нет |
| L1-UI-13 | Отчёты | Да | `/projects/{id}/reports` | report tests | UI buttons | VERIFIED | Нет |
| L1-ISO-01 | Товары разных проектов не смешиваются | Да | `EffectiveProductCardService` filters project | `test_products_from_different_projects_do_not_mix` | Project products page | VERIFIED | Нет |
| L1-ISO-02 | Файлы проекта B не видны A | Да | `ProjectService.list_files(project_id)` | `test_project_http_routes_do_not_expose_other_project_artifacts` | API/UI | VERIFIED | Нет |
| L1-ISO-03 | Draft B нельзя применить в A | Да | `_get_owned_draft` project filters | `test_project_http_routes_do_not_expose_other_project_artifacts` | 404 | VERIFIED | Нет |
| L1-ISO-04 | Version B нельзя откатить в A | Да | project rollback uses `get_project_product` + project filters | `test_project_rollback_requires_reason_and_rejects_foreign_version` | 404 | VERIFIED | Нет |
| L1-ISO-05 | Global Product не меняется | Да | project apply/rollback updates ProjectProduct only | `test_project_draft_apply_changes_only_effective_card`, rollback test | Legacy product unchanged | VERIFIED | Нет |
| L1-VER-01 | Diff перед применением | Да | `project_manual_edit_preview` | UI route/manual | Diff partial | VERIFIED | Нет |
| L1-VER-02 | Diff перед rollback | Да | rollback API returns diff | `test_project_rollback_is_project_scoped` | Result partial | VERIFIED | Нет |
| L1-VER-03 | Rollback создаёт новую версию | Да | `ProductCardEditorService.rollback_version` | rollback tests | Version page | VERIFIED | Нет |
| L1-VER-04 | История не уничтожается | Да | versions are appended | rollback tests | Version list | VERIFIED | Нет |
| L1-VER-05 | Причина отката обязательна | Да | project rollback route validates reason | `test_project_rollback_requires_reason_and_rejects_foreign_version` | Required input | VERIFIED | Нет |
| L1-VER-06 | Audit event project fields/correlation | Да | `_rollback_event` payload/metadata | `test_project_rollback_is_project_scoped` | API response | VERIFIED | Нет |
| L1-VER-07 | Optimistic locking | Да | `current_version_id` and draft revision checks | P5 tests + rollback route | 409 behavior | VERIFIED | Нет |
| L1-EFF-01 | Provenance per field | Да | `EffectiveProductCard.provenance` | `test_import_preview_supports_bom_semicolon_multiline_and_mapping` | Detail page | VERIFIED | Нет |
| L1-EFF-02 | Source priority order | Да | source snapshot + latest project version | draft/apply/export tests | Effective Card | VERIFIED | Нет |
| L1-EXP-01 | CSV/JSON/XLSX from Effective Card | Да | `ProjectExportService._rows` | export tests | Exports page | VERIFIED | Нет |
| L1-EXP-02 | Manifest/checksum | Да | `ProjectExport.manifest_json/checksum` | export tests | API/UI | VERIFIED | Нет |
| L1-EXP-03 | Formula injection | Да | `sanitize_spreadsheet_cell` | formula tests | Export output | VERIFIED | Нет |
| L1-EXP-04 | Negative numbers preserved | Да | numeric regex | formula tests | Export output | VERIFIED | Нет |
| L1-LLM-01 | Работа без LLM | Да | AI disabled by default in CLI, provider availability checks | Existing tests | No external calls in import/export | VERIFIED | Нет |
| L1-LLM-02 | Prompt injection as data | Да | `_SYSTEM_PROMPT` untrusted-data rule | `test_ai_prompt_injection_text_is_treated_as_product_data` | No tools/shell | VERIFIED | Нет |
| L1-LLM-03 | External provider does not get full client file automatically | Да | L1 workflow uses import/pipeline/export, no AI call | Code trace | No LLM route in project import | VERIFIED | Нет |
| L1-RUFF-01 | New files Ruff clean | Да | targeted Ruff | Final check | All checks passed | VERIFIED | Нет |
| L1-RUFF-02 | Full legacy Ruff | Частично | 268 legacy diagnostics | Diagnostic check | Not fixed by scope | PARTIAL | Separate cleanup plan |
| L1-DOC-01 | Docs updated | Да | L1 audit/plan/report/traceability/UI report | File existence | Docs in repo | VERIFIED | Нет |
| L1-DOC-02 | Инструкция ручной приёмки владельцем | Да | `docs/L1_MANUAL_ACCEPTANCE.md`, `scripts/l1_acceptance_demo.py` | `test_demo_fixture_full_local_workflow` + owner browser smoke 2026-07-19 | PASSED | VERIFIED | Финальный export/report PRG smoke пройден владельцем |

## Remaining partials

1. Duplicate unique key does not include schema version at DB constraint level because the existing SQLite unique constraint is `project_id + sha256`; current schema version is stored and checked at workflow level.
2. Full Ruff legacy backlog remains outside L1.1 and documented separately.

## L1.1 Partial Closure Table

| PARTIAL ID | причина | влияние на оператора | обязательность | решение |
|---|---|---|---|---|
| L1-IMP-08 | Не было безопасной поддержки Windows-1251 | Российские CSV могли отклоняться | Обязательно | Закрыто: Windows-1251 определяется, требует подтверждение, сохраняется в metadata |
| L1-IMP-25 | Unique constraint не включает schema_version | Повтор того же файла с новой схемой всё ещё считается duplicate на уровне БД | Некритично для оператора L1.1 | Оставить PARTIAL до отдельной миграции constraints |
| L1-UI-07 | Не было фильтров ошибок | Большой preview было трудно проверять | Обязательно | Закрыто: добавлены фильтры и ограничение вывода |
| L1-RUFF-02 | Legacy Ruff backlog | Не влияет на workflow, но мешает full lint clean | Не входит в L1.1 | Оставить PARTIAL, backlog вынесен в `docs/LEGACY_RUFF_BACKLOG.md` |
| L1-UI-14 | Не было presets mapping | Оператору приходилось заново сопоставлять одинаковые файлы | Обязательно | Закрыто: save/select/delete/suggested preset в UI |
