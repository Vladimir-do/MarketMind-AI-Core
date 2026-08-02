# Project Audit — MarketMind AI Core

Дата аудита: 2026-07-14  
Корень проекта: `/mnt/steam/Proekt/MarketMind-AI-Core-main`

## 1. Назначение текущего проекта

Текущий репозиторий содержит рабочее Python-ядро автоматизации маркетплейсов. Это не SaaS-продукт и не пользовательский веб-сервис. Основная ценность уже сейчас сосредоточена в:

- Telegram-боте для операторских команд;
- CLI для запуска основных сценариев;
- парсерах Ozon, Wildberries, Yandex Market, FunPay;
- генерации черновиков карточек Ozon;
- экспортах CSV/XLSX/HTML;
- телеметрии попыток парсинга и памяти блокировок;
- skillpack/agent workflow для планирования и восстановления.

Проект можно использовать как сильный внутренний core или как основу для будущего продукта, но он ещё не оформлен как удобное решение для обычного пользователя без технического сопровождения.

## 2. Структура проекта

### Основные каталоги

- `app/` — код ядра, парсеры, Telegram, карточки, БД, экспорт, AI, resilience.
- `tests/` — unit/integration-style проверки core-модулей.
- `docs/` — описание архитектуры, workflows, playbooks, roadmap, due diligence.
- `profiles/` — YAML-профили для генерации карточек.
- `project_skills/` — активный skillpack, индекс навыков и manifests.
- `templates/` — шаблоны HTML-отчётов.
- `graphify-out/` — сгенерированный граф зависимостей.
- `app/data/` — runtime-данные, база SQLite, отчёты, debug-артефакты, Ozon profile.

### Ключевые entrypoints

- `app/main.py` — CLI.
- `app/bot.py` — Telegram-бот.
- `app/worker.py` — оркестрация добавления и обновления.
- `app/updater.py` — Ozon update pipeline.
- `app/reporter.py` — HTML report.
- `app/exporter.py` — CSV/XLSX export.

### Ключевые доменные узлы

- `app/task_intents.py`
- `app/task_planner.py`
- `app/skill_manifest.py`
- `app/agent_loop.py`
- `app/execution_state.py`
- `app/database.py`
- `app/card_filler.py`
- `app/generic_scraper.py`
- `app/universal_parsing_core/`

## 3. Уже готовые функции

### То, что реально работает по коду и тестам

- CLI entrypoint с режимами:
  - Telegram polling;
  - update tracked products;
  - metrics / blocks;
  - Ozon browser login helper;
  - HTML report;
  - BRD/XLSX enrichment;
  - WB cloud deploy hook.
- Telegram бот с большим набором команд и natural-language routing.
- Нормализация свободного текста в `StructuredTask`.
- Task planner и skill registry с зависимостями, fallback и scoring.
- Agent loop FSM: classify → strategy → execute → evaluate → fallback → save experience.
- Парсинг:
  - Ozon через Playwright/HTML/API fallback;
  - Wildberries через API/basket candidates;
  - Yandex Market через HTML/JSON-LD;
  - FunPay;
  - universal parser / page classification.
- Хранилище:
  - `Product`;
  - `PriceHistory`;
  - `ScrapeAttempt`;
  - `BlockedPattern`;
  - `Subscriber`.
- Телеметрия попыток, source/status/http/latency/error.
- Resilience:
  - adaptive cooldown;
  - circuit breaker;
  - block memory;
  - strategy recommendation.
- Ozon card generation:
  - черновик;
  - profile-based rules;
  - AI enhancement;
  - JSON/XLSX export;
  - batch export.
- Табличный импорт/обогащение:
  - Excel/CSV import;
  - BRD document-to-sheet workflow.
- HTML отчёты и Telegram-доставка файлов.

### Что подтверждено тестами

- `tests/test_config.py`
- `tests/test_parsers.py`
- `tests/test_card_filler.py`
- `tests/test_worker.py`
- `tests/test_task_intents.py`
- `tests/test_task_planner.py`
- `tests/test_searcher.py`
- `tests/test_brd_enricher.py`
- `tests/test_batch_enricher.py`
- `tests/test_cli.py`
- `tests/test_bot_startup.py`
- `tests/test_bot_helpers.py`
- `tests/test_telegram_exports.py`
- `tests/test_telegram_ai_reports.py`
- `tests/test_telegram_card_tasks.py`
- `tests/test_telegram_card_research.py`

В системной среде эти группы тестов проходят. Набор без БД дал `107 passed`, Telegram/CLI-набор дал `85 passed`.

## 9. Stage 1 stabilization results

Что было исправлено на первом безопасном этапе:

- сломанное `.venv` сохранено в `.venv_broken_backup`, затем создано новое окружение;
- зависимости установлены в новом venv;
- `requirements.txt` приведён к совместимой связке `aiogram 3.4.1` + `aiohttp 3.9.5`;
- `.gitignore` дополнен явными правилами для runtime-artifacts и графа;
- Telegram startup fallback переведён на переиспользование session-объекта без лишнего пересоздания;
- `tests/test_database.py`, core tests, Telegram/CLI tests и полный `pytest` проходят в чистом окружении.

Что подтвердилось по диагностике:

- `aiosqlite.connect(':memory:')` в новом окружении работает с таймаутом;
- `Database.init()` в новом окружении создаёт таблицы в временной БД;
- `app.main` импортируется без ошибки;
- CLI `--help` отвечает корректно;
- секреты в терминал и отчёты не выводились.

## 10. P0 fix batch status

| Задача | Статус | Дата | Тесты |
|---|---|---|---|
| P0.1 — `allowed()` vulnerability | ✅ APPROVE | 2026-07-14 | 274 passed |
| P0.2 — atomic `record_scrape_attempt` | ✅ APPROVE | 2026-07-14 | 274 passed |
| P0.3 — proxy credential masking | ✅ APPROVE | 2026-07-14 | 278 passed |
| P0.4 — SQLite WAL mode + cross-platform audit | ✅ APPROVE | 2026-07-14 | 278 passed |
| P0.5 — signal.SIGTERM Windows fix | ✅ APPROVE | 2026-07-14 | 278 passed |
| P0.6 — reporter.py Playwright-per-image | ⏳ pending | — | — |

## 11. P1 architectural improvements

| Задача | Статус | Дата | Тесты |
|---|---|---|---|
| P1.1 — bot.py module split | ✅ APPROVE | 2026-07-14 | 278 passed |
| P1.1.5 — Architecture review & freeze | ✅ APPROVE | 2026-07-14 | 278 passed |
| P1.2 — Alembic migrations | ✅ APPROVE | 2026-07-14 | 278 passed |
| P1.3 — Universal Data Import Layer | ✅ APPROVE | 2026-07-14 | 289 passed |
| P1.4 — Import Pipeline + Batch Enrichment | ✅ APPROVE | 2026-07-14 | 324 passed |
| P1.5 — Product Intelligence Layer | ✅ APPROVE | 2026-07-14 | 339 passed |
| P1.6 — Intelligence Layer Integration | ✅ APPROVE | 2026-07-14 | 350 passed |
| P2.1 — AI Recommendation Layer | ✅ APPROVE | 2026-07-14 | 372 passed |
| P2.2 — AI Layer Integration with Pipeline | ✅ APPROVE | 2026-07-14 | 383 passed |
| P2.4 — Real AI Providers | ✅ APPROVE | 2026-07-14 | 410 passed |
| P3 — User Interface Layer (MVP) | ✅ APPROVE | 2026-07-14 | 417 passed |
| P3.2 — AI Suggestions UI | ✅ APPROVE | 2026-07-14 | 422 passed |
| P3.3 — Approval Workflow with Rollback | ✅ APPROVE | 2026-07-14 | 436 passed |
| P3.4 — Product Detail (Карточка товара) | ✅ APPROVE | 2026-07-14 | 443 passed |
| P3.5 — Store Analytics (Анализ магазина) | ✅ APPROVE | 2026-07-14 | 451 passed |

## 4. Неработающие и незавершённые функции

### Неработающие или незавершённые по факту текущего состояния

- Полноценный GUI для обычного пользователя отсутствует.
- FastAPI API отсутствует.
- Авторизация, пользователи, роли, multi-tenant изоляция отсутствуют.
- Нет нормального SaaS/onboarding/billing слоя.
- Нет полноценного проекта/магазина как сущности верхнего уровня.
- Нет безопасного пользовательского workflow вида:
  - создать проект;
  - загрузить файлы;
  - проверить данные;
  - отредактировать;
  - предпросмотр;
  - экспорт.

### Проблемы, которые проявились в аудите

- `python3 -m pytest` в системной среде запускается, но полный suite зависает на `tests/test_database.py`.
- `Database.init()` зависает на открытии async SQLAlchemy engine с `sqlite+aiosqlite`.
- Локальный `.venv` в корне проекта сломан:
  - нет `pip`;
  - нет установленных зависимостей;
  - `python -m pytest` в нём не работает.

## 5. Критические ошибки

1. Реальные секреты лежат в `.env` рядом с исходниками.
   - Там присутствуют:
     - `BOT_TOKEN`;
     - `GEMINI_API_KEY`;
     - `ADMIN_IDS`.
   - Это не должно попадать в committed state.

2. `.venv` в проекте не пригоден для нормального запуска:
   - `python -m pip` внутри него не работает;
   - `pytest` отсутствует;
   - это ломает воспроизводимость локальной среды.

3. `Database.init()` зависает при открытии async engine.
   - Это блокирует весь `tests/test_database.py`.
   - Без исправления нельзя считать storage layer устойчивым.

4. Документация местами описывает будущий SaaS как будто он уже готов.
   - Это вводит в заблуждение относительно готовности продукта.

5. В репозитории много runtime-артефактов:
   - `app/data/parser.db`;
   - `app/data/debug/`;
   - `app/data/reports/`;
   - `.pytest_cache/`;
   - `parser.log`;
   - `graphify-out/`.

## 6. Архитектурные проблемы

- Слишком много логики сосредоточено в больших модулях:
  - `app/bot.py`;
  - `app/card_filler.py`;
  - `app/task_intents.py`;
  - `app/updater.py`;
  - `app/database.py`.
- Нет отдельного слоя для:
  - импортов;
  - редактирования карточек;
  - валидации;
  - preview/экспорта как пользовательского workflow;
  - истории версий карточек.
- Парсеры, адаптеры, отчёты, Telegram-обвязка и storage связаны сильнее, чем хотелось бы для дальнейшего роста.
- `app/__init__.py` пустой, что делает некоторые формы monkeypatch/patch менее удобными.
- Документация расползлась на несколько источников истины:
  - `README.md`;
  - `SPECIFICATION.md`;
  - `docs/ARCHITECTURE_OVERVIEW.md`;
  - `docs/ROADMAP.md`;
  - `docs/TECHNICAL_DUE_DILIGENCE.md`;
  - `docs/architecture/ARCHITECTURE_REPORT.md`;
  - `docs/architecture/ARCHITECTURE_CONFLICTS.md`.

## 7. Проблемы интерфейса

- Интерфейс ориентирован на оператора/разработчика, а не на обычного продавца.
- Нет пошагового сценария:
  - проект → загрузка файлов → анализ → сопоставление фото → генерация → проверка → редактирование → предпросмотр → экспорт.
- Ошибки пока чаще выражаются техническими терминами, а не простым языком.
- Нет экранов для:
  - выбора магазина/проекта;
  - ручного исправления данных;
  - просмотра предупреждений и неподтверждённых полей;
  - предварительного результата перед сохранением.

## 8. Проблемы безопасности

- `.env` содержит реальные токены и ключи.
- Нет централизованного secret management.
- Нет отдельной модели пользователей/ролей/организаций.
- Нет JWT/auth boundary для будущего web/API слоя.
- AI-клиенты и Telegram зависят от токенов из окружения без надёжного fail-fast слоя.
- `BOT_TOKEN` и API keys легко утечь через:
  - `.env`;
  - неправильное логирование;
  - ошибочный dump окружения.

## 9. Недостающие функции

- Проект/магазин как сущность верхнего уровня.
- Импорт товаров через удобный мастер.
- Редактор карточек.
- Проверка качества данных перед экспортом.
- История версий карточек.
- Preview-before-save.
- Безопасный экспорт в маркетплейс-формат.
- Пользовательские аккаунты и storage для истории.
- API/интеграционный слой.
- Нормальный browser/profile management для end-user.

## 10. Рекомендуемая архитектура

Для дальнейшего развития лучше разделить систему на явные слои:

1. `io/` или `ingestion/` — импорты Excel/CSV/PDF/фото/ссылок.
2. `domain/` — сущности товара, проекта, карточки, версии, замечания.
3. `validation/` — полнота данных, противоречия, запрещённые формулировки.
4. `generation/` — текст карточки, SEO, атрибуты, подсказки.
5. `media/` — проверка изображений, дубликаты, качество, связь с товаром.
6. `export/` — Ozon/WB payloads, таблицы, архивы.
7. `history/` — версии карточек и аудиторский след.
8. `ui/` — простой русский интерфейс для не-технического пользователя.
9. `integrations/` — marketplaces API adapters later, not first.

Главный поток:

```text
Import -> Normalize -> Validate -> Enrich -> Preview -> Manual fix -> Export -> History
```

## 11. План развития по этапам

### Этап 1. Привести текущий прототип в рабочее состояние

- восстановить воспроизводимую среду;
- починить запуск БД;
- убрать runtime clutter из рабочих путей;
- стабилизировать тестовый прогон;
- зафиксировать настоящие ограничения.

### Этап 2. Удобный импорт товаров

- мастер импорта Excel/CSV/PDF/ссылок;
- разбор заголовков и базовых атрибутов;
- первичная валидация и подсказки по недостающим полям.

### Этап 3. Редактор карточек

- ручное исправление названия/описания/атрибутов;
- предпросмотр результата;
- сохранение черновиков.

### Этап 4. Проверка качества данных

- пустые/противоречивые поля;
- запрещённые формулировки;
- невалидные категории;
- слишком длинные тексты.

### Этап 5. Генерация текстов и характеристик

- шаблоны и rule-based генерация;
- optional AI-слой;
- безопасные подсказки без выдумывания фактов.

### Этап 6. Изображения

- проверка форматов/размера;
- поиск дубликатов;
- привязка фото к товарам;
- предупреждения о низком качестве.

### Этап 7. Экспорт для маркетплейсов

- Ozon payload;
- Wildberries payload;
- таблицы для массовой загрузки;
- архивирование результатов.

### Этап 8. История, проекты и пользователи

- проекты;
- версии карточек;
- аудит изменений;
- пользовательские сессии.

### Этап 9. Интеграции с API маркетплейсов

- Ozon / WB / Yandex Market API adapters;
- безопасное хранение ключей;
- фоновые синхронизации;
- отчётность.

## 12. Какие файлы необходимо изменить на первом этапе

Приоритет первого этапа:

- `app/database.py` — исправить блокировку startup/init и сделать инициализацию предсказуемой.
- `app/config.py` — отделить runtime paths и улучшить контроль окружения.
- `app/main.py` — минимизировать количество сценариев, завязанных на неготовые зависимости.
- `tests/test_database.py` — зафиксировать regression на инициализацию БД.
- `tests/helpers.py` — если потребуется, сделать reload helper безопаснее для окружения.
- `README.md` — убрать завышенные claims и честно описать текущий статус.
- `docs/ARCHITECTURE_OVERVIEW.md`
- `docs/TECHNICAL_DUE_DILIGENCE.md`
- `docs/ROADMAP.md`
- `.gitignore` — runtime artefacts, cache, database, logs, browser profiles.

## 13. Краткий вывод

Проект уже содержит сильное ядро автоматизации маркетплейсов: Telegram, CLI, парсинг, карточки, экспорт, telemetry и skill-based planning. Но он ещё не является удобным продуктом для обычного пользователя и не готов как SaaS. Главный технический blocker на текущем шаге — нестабильная инициализация базы через async engine, а главный организационный риск — реальные секреты и runtime-артефакты в рабочем дереве.
