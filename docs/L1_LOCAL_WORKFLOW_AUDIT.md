# L1 Local Workflow Audit

Дата аудита: 2026-07-17

## Executive summary

Репозиторий соответствует заявленному P6-состоянию: локальные проекты заказчиков, project-aware effective card, импорт CSV/XLSX/XLSM, экспорт CSV/JSON/XLSX, отчёты и P6-тесты присутствуют. Рабочее дерево на старте было чистым, remote не настроен, push не выполнялся.

До коммерчески удобного локального сценария остаются пробелы: импорт сразу пишет данные в БД без preview/mapping, метаданные импорта неполные, project-aware rollback есть в сервисе, но не выведен в project API, экспорт не хранит manifest/checksum, а защита formula injection экранирует отрицательные числа как текстовые формулы.

## Baseline checks

| Проверка | Результат |
|---|---|
| Полный pytest | 514 passed, 24 warnings, 14 subtests passed |
| Focused P4/P5/P6 pytest | 56 passed |
| Ruff по P6-файлам | All checks passed |
| Полный Ruff diagnostic | 268 legacy errors |
| git diff --check | passed |
| Alembic SQLite upgrade -> downgrade -> upgrade | passed |
| Skill validation | 48 indexed skills, 48 markdown skills, 0 warnings |
| Git status на старте | clean |
| Remote | не настроен |

## Requirement matrix

| Требование | Фактическое состояние | Доказательство | Проблема | Риск | Исправление | Приоритет |
|---|---|---|---|---|---|---|
| Использовать существующий репозиторий | Выполнено | git root `/mnt/steam/Proekt/MarketMind-AI-Core-main` | Нет | Нет | Не создавать новый проект | P0 |
| P6 commits присутствуют | Выполнено | `85ed488`, `81c56d0`, `63d42f2` в `git log -15` | Нет | Нет | Продолжать поверх текущей истории | P0 |
| ClientProject | Есть | `app/database.py` | Нет | Низкий | Сохранить модель | P0 |
| ProjectFile | Есть как `ClientProjectFile` | `app/database.py` | Метаданные импорта неполные | Повторный импорт и аудит файла недостаточно прозрачны | Добавить schema/encoding/delimiter/sheet/count/status details | P1 |
| ProjectProduct | Есть | `app/database.py`, `app/projects/service.py` | Нет | Низкий | Не добавлять `Product.client_project_id` | P0 |
| EffectiveProductCardService | Есть | `app/effective_card/service.py` | Provenance по полям не раскрыт | Оператор не видит источник итогового значения | Добавить вычисляемый provenance в response | P1 |
| Project-aware draft apply | Есть | `ProductCardEditorService.apply_draft(... project_id, project_product_id)` | Нет | Низкий | Защитить тестами | P0 |
| Project-aware rollback | Частично | Сервис поддерживает project args | Нет project route | Оператор может использовать только legacy/global rollback endpoint | Добавить project-aware API route и тесты | P1 |
| Project routes/templates | Есть | `app/web/routes/projects.py`, `app/web/templates/project_*.html` | UI минимальный | Полный заказ без терминала неочевиден | Добавить preview/mapping/result в существующий UI | P1 |
| Импорт CSV | Есть | `app/importers/csv_importer.py` | Нет sniff delimiter/preview/mapping | Ошибки импорта видны поздно, semicolon CSV может читаться неверно | Добавить analysis/preview и mapping слой | P1 |
| Импорт XLSX/XLSM | Есть | `app/importers/excel_importer.py` | Только active sheet, нет предупреждений hidden sheets | Неверный лист может импортироваться молча | Добавить sheet metadata и выбор листа | P1 |
| Неподдерживаемые форматы | Есть | `store_source_file` | Проверка по расширению, не по фактическому типу | Mismatch extension/content может дать непонятную ошибку | Добавить lightweight content signature validation | P1 |
| Повторный импорт | Частично | unique `project_id + sha256` | Возвращает duplicate после сохранения файла, нет preview warning | Оператор не понимает последствия | Показывать duplicate в preview и требовать explicit confirm | P1 |
| Изоляция проектов | Есть в project routes | `ProjectService.get_project_product`, P6 tests | Legacy endpoints остаются глобальными | Старые UI/API могут показать глобальный каталог | Документировать legacy и не использовать в project UI | P2 |
| Один Product в нескольких проектах | Поддерживается | P6 test `products_from_different_projects_do_not_mix` | Нет | Низкий | Сохранить `ProjectProduct` overlay | P0 |
| Экспорт Effective Card | Есть | `ProjectExportService._rows` | Нет manifest/checksum | Сложнее доказать, что передано заказчику | Добавить manifest и checksum | P1 |
| Formula injection | Есть | `app/exports/safety.py` | `-10` экранируется как формула | Портится корректное отрицательное число | Различать числовые отрицательные значения и текстовые формулы | P1 |
| Итоговый отчёт | Есть | `app/reports/service.py` | Не включает import warnings/errors детально | Заказчику не хватает объяснения пропусков | Дополнить report preview импортной статистикой | P2 |
| LLM safety | Частично архитектурно | AI layer отделён, AI не apply автоматически | Нет L1-тестов на prompt injection payload | Риск будущего расширения | Добавить тест/документированное правило no auto external send | P2 |
| Логи без клиентских файлов | В основном выполняется | Нет полного content logging в project import | Ошибки могут содержать raw row в будущем | Убедиться, что ошибки хранят безопасный value preview | P1 |

## Architecture risks

1. Project import route currently combines upload, persistence, pipeline run and DB write in one HTTP action. This prevents safe preview and mapping.
2. Existing global product routes remain useful for legacy screens but are not project-safe. New local workflow must stay under `/projects/{project_id}` and `/api/projects/{project_id}`.
3. Effective Card is computed correctly from project source + latest project version, but per-field provenance is not visible.
4. Export uses Effective Card, but lacks manifest/checksum evidence.
5. Project rollback is implemented in service but not exposed through project API.

## Decision

Состояние не расходится критически с предыдущим логом. Можно переходить к реализации, но только точечно: усилить импорт, project isolation guard rails, Effective Card provenance, rollback route, export manifest и тесты. Полный legacy Ruff backlog не исправлять в этом этапе.
