# L1.1 Final Acceptance Report

Дата: 2026-07-17

## Verdict

Технический статус: `READY_FOR_OWNER_ACCEPTANCE`.

Пользовательская приёмка: `AWAITING_OWNER_ACCEPTANCE`.

L1.1 закрывает обязательные операторские пробелы: presets mapping, фильтрацию и CSV-экспорт ошибок, Windows-1251 с подтверждением, download route tests и demo happy path. Полная ручная приёмка не объявляется завершённой до фактического прохода владельцем по `docs/L1_MANUAL_ACCEPTANCE.md`.

## Partial Requirements

| ID | Было | Решение | Новый статус |
|---|---|---|---|
| L1-IMP-08 | CSV не поддерживал Windows-1251 | Добавлено безопасное чтение Windows-1251 с предупреждением и обязательным подтверждением | VERIFIED |
| L1-UI-07 | Ошибки preview нельзя было фильтровать | Добавлены фильтры и ограничение вывода; полный список скачивается CSV | VERIFIED |
| L1-UI-14 | Не было сохранения mapping presets | Добавлена таблица, service methods и UI save/select/delete/suggested preset | VERIFIED |
| L1-IMP-25 | Duplicate DB constraint без schema_version | Оставлено PARTIAL: миграция unique constraint рискованна и не нужна для оператора L1.1 | PARTIAL |
| L1-RUFF-02 | Full Ruff legacy backlog | Оставлено PARTIAL, вынесено в `docs/LEGACY_RUFF_BACKLOG.md` | PARTIAL |

## What Changed

- `ImportMappingPreset` для локальных project-scoped схем сопоставления.
- `header_fingerprint` preview для безопасного suggested preset.
- Windows-1251 CSV decoding с предупреждением.
- Preview business validation для `missing_title` и `invalid_number`.
- Ошибочные строки с нечисловыми числовыми полями не импортируются как корректные товары.
- Numeric stock нормализуется в `in_stock/out_of_stock`; исходный остаток сохраняется в attributes.
- CSV error report endpoint with formula-injection protection.
- Preview UI filters and error counters.
- Demo fixture with 20 synthetic products.
- Manual acceptance script and owner instruction.

## Demo Import Numbers

Fixture: `tests/fixtures/l1_demo_products.csv`.

- rows read: 20;
- import errors: 2;
- products imported: 18;
- exports generated in demo test: CSV;
- report generated in demo test: HTML.

## Automated Verification

| Проверка | Результат |
|---|---|
| `tests/test_l1_1_final_acceptance.py` | 7 passed |
| `tests/test_client_projects.py` | 23 passed |
| Focused P4/P5/P6/L1/L1.1 | 81 passed |
| Full pytest | 537 passed, 24 warnings, 14 subtests passed |
| Ruff new/changed files | All checks passed |
| Full Ruff diagnostic | 267 legacy errors |
| Alembic upgrade -> downgrade -> upgrade | passed on temporary SQLite |
| `git diff --check` | passed |
| Skill validation | passed |
| Secret scan changed files | no matches |
| Demo script | started and printed isolated command |

## Download Tests

Покрыты:

- CSV/JSON/XLSX export artifact response;
- HTML/JSON/CSV report artifact response;
- CSV error report;
- `Content-Disposition`;
- safe filename;
- foreign project denial;
- missing/path traversal denial.

ASGI `FileResponse` не форсируется через зависающий transport: проверяется route helper и фактический файл в workspace.

## UI Availability

Доступно через UI:

- список проектов;
- создание проекта;
- загрузка файла;
- preview;
- mapping;
- save/select/delete preset;
- import result;
- error counters and filters;
- CSV error report download;
- project products;
- Effective Product Card;
- manual edit;
- versions;
- rollback;
- exports;
- reports.

## Manual Acceptance UX Fixes

После ручной приёмки исправлены найденные UX-проблемы:

- добавлены `start_l1_demo.sh` и `start_l1_demo.bat`;
- legacy пункты бокового меню явно помечены как legacy;
- rollback/manual action result больше не показывает сырой dict;
- export/report HTMX actions возвращают русские partial-шаблоны вместо JSON;
- список экспортов обновляется сразу после создания;
- список отчётов проекта отображается на странице и обновляется сразу после создания;
- у созданных export/report сразу есть ссылка скачивания.

Доступно через API и используется UI:

- project import preview/import;
- project exports/reports;
- project rollback;
- artifact downloads.

## Known Limitations

- `ClientProjectFile` DB unique constraint остаётся `project_id + sha256`; `schema_version` хранится в metadata и workflow, но не в unique key.
- Full Ruff backlog остаётся legacy-долгом.
- Межпроектный перенос presets не реализован намеренно: preset другого проекта не применяется автоматически.
- Браузерная приёмка владельцем ещё не выполнена.

## Push

Push не выполнялся.

## Current Acceptance State

- Technical L1.1: ready after local commits.
- Owner browser acceptance: `AWAITING_OWNER_ACCEPTANCE`.
