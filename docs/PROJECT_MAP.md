# Project Map

Навигационная карта для разработчиков MarketMind AI.

## Runtime entrypoints

- `app/main.py` — CLI entrypoint (`--telegram`, `--update`, `--metrics`, `--blocks`, `--enrich`, `--report`).
- `app/bot.py` — Telegram команды и natural-language routing (35 команд).

## Core (ядро)

- `app/core/__init__.py` — пакет core.
- `app/core/enums.py` — перечисления: статусы товаров, маркетплейсы, источники парсинга, типы задач.
- `app/core/errors.py` — доменные ошибки и исключения проекта.
- `app/core/models.py` — базовые ORM-модели и переиспользуемые компоненты.

## Adapters (адаптеры API)

- `app/adapters/ozon.py` — адаптер интеграции с Ozon Seller API.
- `app/adapters/wb.py` — адаптер интеграции с Wildberries API.

## Marketplace parsing and update loop

- `app/worker.py` — фоновая оркестрация добавления URL и обновления цен.
- `app/updater.py` — устойчивый pipeline парсинга/обновления, retry, anti-block.
- `app/parsers/router.py` — выбор парсера по URL/маркетплейсу.
- `app/parsers/base.py` — `BaseParser` + `ProductData` (единый контракт).
- `app/parsers/ozon.py` — парсер Ozon через Playwright.
- `app/parsers/wildberries.py` — парсер Wildberries через API/basket candidates.
- `app/parsers/yandex_market.py` — парсер Yandex Market через HTML/JSON-LD.
- `app/parsers/funpay.py` — парсер офферов FunPay.
- `app/searcher.py` — поиск товаров на Ozon + helpers блокировок.
- `app/generic_scraper.py` — универсальный скрапер для произвольных страниц.
- `app/wb_deals.py` — поиск скидок и горячих предложений на Wildberries.

## Universal Parsing Core

- `app/universal_parsing_core/__init__.py` — пакет universal parsing.
- `app/universal_parsing_core/router.py` — универсальный роутер парсеров.
- `app/universal_parsing_core/algorithms/` — алгоритмы классификации страниц и экстракции данных.
- `app/universal_parsing_core/exporters/` — экспорт данных из universal parsing.
- `app/universal_parsing_core/parsers/` — универсальные парсеры для произвольных страниц.
- `app/universal_parsing_core/schemas/` — схемы данных (PageStructure и др.).

## Card generation (генерация карточек)

- `app/card_filler.py` — черновик карточки Ozon, AI-обогащение, экспорт (JSON/XLSX).
- `app/card_research.py` — форматирование отчёта по конкурентам.
- `app/card_profiles.py` — загрузка YAML-профилей (`profiles/*.yaml`).
- `profiles/default.yaml` — базовый профиль.
- `profiles/electronics.yaml` — профиль для электроники.

## AI and analytics

- `app/ai_client.py` — AI provider abstraction (Grok/Claude).
- `app/agent.py` — AI-агент: анализ портфеля, алерты, прогнозы, сравнение.
- `app/ai_analyzer.py` — статистика цен, прогнозы, паттерны, аномалии, обзор рынка.
- `app/agent_loop.py` — цикл: классификация -> стратегия -> выполнение -> оценка -> fallback -> опыт.

## Task planning and skill system

- `app/task_intents.py` — нормализация свободного текста в `StructuredTask`.
- `app/task_planner.py` — планирование pipeline из registry скиллов, `TaskPlan`.
- `app/skill_manifest.py` — YAML-манифесты скиллов с зависимостями, fallback, scoring.
- `app/skill_telemetry.py` — JSONL-телеметрия выполнения скиллов.
- `app/skill_notes.py` — создание и просмотр pending skill proposals.
- `app/execution_state.py` — FSM выполнения: PLANNING -> EXECUTING -> VALIDATING -> FINISHED.

## Storage and exports

- `app/database.py` — SQLAlchemy async модели, сессии, telemetry, block memory.
- `app/exporter.py` — CSV/XLSX экспорт отслеживаемых товаров.
- `app/reporter.py` — HTML отчёт с Chart.js графиками.
- `app/brd_enricher.py` — заполнение BRD-таблиц из веб-источников с верификацией артикулов.
- `app/batch_enricher.py` — массовое обогащение XLSX/CSV таблиц.
- `app/resilience.py` — rate limit + circuit breaker для маркетплейсов.

## Telegram modules

- `app/bot.py` — команды бота, FSM диалоги, natural-language routing.
- `app/telegram_runtime.py` — жизненный цикл polling, reconnect, proxy fallback.
- `app/telegram_messages.py` — форматирование сообщений, диаграммы, команды.
- `app/telegram_exports.py` — отправка файлов экспорта и HTML-отчётов.
- `app/telegram_ai_reports.py` — AI-отчёты: прогнозы, алерты, обзор рынка.
- `app/telegram_card_tasks.py` — построение задач генерации карточек.
- `app/telegram_card_research.py` — исследование конкурентов для карточек.
- `app/telegram_diagnostics.py` — диагностика сети, proxy, DNS/TCP/HTTPS пробы.

## Utils

- `app/utils/error_research.py` — исследование ошибок парсинга.

## Config

- `app/config.py` — загрузка `.env`, настройки, логирование, прокси.

## Tests

- `tests/test_card_filler.py` — поведение card builder и экспорт.
- `tests/test_card_profiles.py` — загрузка/fallback профилей.
- `tests/test_parsers.py` — интеграционные тесты парсеров + сценарии retry/block через mock.
- `tests/test_database.py` — тесты модели БД и telemetry.
- `tests/test_worker.py` — тесты фонового worker.
- `tests/test_cli.py` — тесты CLI entrypoint.
- `tests/test_task_intents.py` — тесты нормализации задач.
- `tests/test_task_planner.py` — тесты планировщика.
- `tests/test_skill_manifest.py` — тесты skill graph и manifest.
- `tests/test_skill_telemetry.py` — тесты telemetry скиллов.
- `tests/test_execution_state.py` — тесты execution FSM.
- `tests/test_agent_loop.py` — тесты agent loop.
- `tests/test_brd_enricher.py` — тесты BRD enrichment.

## Operational notes

- Держать browser profile/cache вне git (`.ozon_profile/`, playwright cache).
- Новые фичи бота — через command handlers, затем natural-language aliases.
- При изменениях карточек — обновлять `test_card_filler.py` в том же коммите.
- `.env` содержит секреты — никогда не коммитить.
- Активный `.venv` и БД (`app/data/parser.db`) не удалять без явного запроса.
