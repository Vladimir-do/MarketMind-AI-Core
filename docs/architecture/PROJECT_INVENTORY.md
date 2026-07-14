# PROJECT_INVENTORY.md — Полная инвентаризация проекта MarketMind AI

> Дата инвентаризации: 2026-07-12
> Проект: MarketMind-AI-Core-main
> Статус: Telegram-бот + CLI ядро автоматизации маркетплейсов

---

## 1. Идентификация проекта

| Параметр | Значение |
|---|---|
| Название | MarketMind AI |
| Язык | Python 3.11+ |
| Тип | Marketplace automation core |
| Входные интерфейсы | Telegram bot (aiogram 3), CLI |
| AI-провайдеры | Grok (xAI), Claude (Anthropic), Gemini (Google) |
| База данных | SQLite (текущее), PostgreSQL (планируется) |
| ORM | SQLAlchemy 2 async |
| Telegram | aiogram 3.4.1 |
| Браузерный парсинг | Playwright (Chromium) |

---

## 2. Все документационные файлы (.md)

### Корень проекта
| Файл | Назначение | Статус |
|---|---|---|
| `README.md` | Основная документация, quick start, команды | Актуален |
| `AGENTS.md` | Инструкции для AI-агентов (skillpack protocol) | Актуален |
| `ARCHITECTURE_NEXT.md` | План перехода на enterprise-архитектуру | Актуален |
| `SPECIFICATION.md` | Полное ТЗ проекта (918 строк) | Актуален, исчерпывающий |
| `SECURITY.md` | Правила безопасности | Актуален |
| `CONTRIBUTING.md` | Гайд для контрибьюторов | Актуален |
| `SKILLS.md` | Карта навыков проекта | Актуален |
| `SKILL_TRIGGERS.md` | Триггеры навыков | Актуален |
| `CLAUDE.md` | Инструкции для Claude Code | Актуален |

### docs/
| Файл | Назначение |
|---|---|
| `docs/ARCHITECTURE_OVERVIEW.md` | Обзор архитектуры с Mermaid-диаграммами |
| `docs/ROADMAP.md` | Дорожная карта (5 фаз) |
| `docs/PROJECT_MAP.md` | Навигационная карта для разработчиков |
| `docs/BOT_WORKFLOWS.md` | Рабочие процессы бота |
| `docs/CODING_STANDARDS.md` | Стандарты кода |
| `docs/DEMO_SCENARIOS.md` | Демо-сценарии |
| `docs/BUYER_PITCH.md` | Презентация для покупателей |
| `docs/TECHNICAL_DUE_DILIGENCE.md` | Технический аудит |
| `docs/PARSING_CRAFT_PLAYBOOK.md` | Правила парсинга |
| `docs/SELF_HEALING_PLAYBOOK.md` | Self-healing workflow |
| `docs/AGENT_TRAINING_PLAYBOOK.md` | Обучение агентов |
| `docs/TASK_INTERPRETATION_RULES.md` | Правила интерпретации задач |
| `docs/PROJECT_DEFRAG.md` | Дефрагментация проекта |

### project_skills/
| Файл | Назначение |
|---|---|
| `SKILLPACK.md` | Описание skillpack |
| `SESSION_UPDATE_PROTOCOL.md` | Протокол обновлений сессий |
| `skills_database.md` | База знаний навыков |
| `skills_index.json` | Машинный индекс навыков |
| `skill_manifests/core.yaml` | Манифест core навыков |
| `skill_manifests/marketplace.yaml` | Манифест marketplace навыков |
| `missing_skills_prioritized.yaml` | Недостающие навыки |

### graphify-out/
| Файл | Назначение |
|---|---|
| `GRAPH_REPORT.md` | Отчёт графа знаний |
| `graph.json` | Граф знаний |

---

## 3. Все Python-модули (app/)

### Ядро (core/)
| Модуль | Назначение | Статус |
|---|---|---|
| `app/core/__init__.py` | Пакет core | Рабочий |
| `app/core/enums.py` | Перечисления: Marketplace, AvailabilityStatus, FetchStatus, TaskType | Рабочий |
| `app/core/errors.py` | Доменные ошибки: blocked, not_found, parse, network | Рабочий |
| `app/core/models.py` | ProductSnapshot (Pydantic) — единый формат результата | Рабочий |

### Входные точки
| Модуль | Назначение | Статус |
|---|---|---|
| `app/main.py` | CLI entrypoint (--telegram, --update, --metrics, --blocks, --enrich, --report) | Рабочий |
| `app/bot.py` | Telegram команды (35), FSM диалоги, NL routing | Рабочий |
| `app/config.py` | Загрузка .env, настройки, логирование, прокси | Рабочий |

### Парсеры (parsers/)
| Модуль | Назначение | Статус |
|---|---|---|
| `app/parsers/base.py` | BaseParser + ProductData (единый контракт) | Рабочий |
| `app/parsers/router.py` | Автовыбор парсера по URL | Рабочий |
| `app/parsers/ozon.py` | Ozon через Playwright (ninja-режим) | Рабочий |
| `app/parsers/wildberries.py` | WB через API/basket candidates | Рабочий |
| `app/parsers/yandex_market.py` | Yandex Market HTML/JSON-LD | Рабочий |
| `app/parsers/funpay.py` | FunPay offer parser | Рабочий |
| `app/parsers/alt_sources.py` | Альтернативные источники | Рабочий |
| `app/parsers/universal.py` | Универсальный парсер | Рабочий |

### Адаптеры API
| Модуль | Назначение | Статус |
|---|---|---|
| `app/adapters/__init__.py` | Пакет adapters | Рабочий |
| `app/adapters/ozon.py` | Ozon Seller API adapter | Рабочий |
| `app/adapters/wb.py` | Wildberries API adapter | Рабочий |

### Universal Parsing Core
| Модуль | Назначение | Статус |
|---|---|---|
| `app/universal_parsing_core/parsers/base.py` | Базовый universal парсер | Рабочий |
| `app/universal_parsing_core/parsers/universal_html.py` | HTML universal парсер | Рабочий |
| `app/universal_parsing_core/schemas/page_structure.py` | PageStructure schema | Рабочий |
| `app/universal_parsing_core/schemas/parse_result.py` | ParseResult schema | Рабочий |
| `app/universal_parsing_core/schemas/normalized_entity.py` | NormalizedEntity schema | Рабочий |
| `app/universal_parsing_core/exporters/records.py` | Экспорт records | Рабочий |

### Агентный цикл и планирование
| Модуль | Назначение | Статус |
|---|---|---|
| `app/task_intents.py` | StructuredTask normalization | Прототип/рабочий |
| `app/task_planner.py` | TaskPlan + skill registry | Прототип |
| `app/agent_loop.py` | Agent FSM: classify→strategy→execute→evaluate→fallback | Прототип/рабочий |
| `app/execution_state.py` | Execution lifecycle FSM | Прототип |
| `app/skill_manifest.py` | Skill graph + manifests | Прототип |
| `app/skill_telemetry.py` | JSONL runtime telemetry | Рабочий |
| `app/skill_notes.py` | Pending skill proposals | Рабочий |
| `app/skill_manifest.py` | Skill graph, dependencies, fallback, scoring | Прототип |

### AI и аналитика
| Модуль | Назначение | Статус |
|---|---|---|
| `app/ai_client.py` | AI provider abstraction (Grok/Claude/Gemini) | Рабочий |
| `app/agent.py` | PriceAgent: анализ портфеля, алерты, прогнозы | Рабочий |
| `app/ai_analyzer.py` | Статистика, прогнозы, аномалии, обзор рынка | Рабочий |

### Генерация карточек
| Модуль | Назначение | Статус |
|---|---|---|
| `app/card_filler.py` | Ozon card draft + AI enhancement + exports | Рабочий |
| `app/card_profiles.py` | YAML profile loading | Рабочий |
| `app/card_research.py` | Competitor research formatting | Рабочий |

### Рабочие процессы
| Модуль | Назначение | Статус |
|---|---|---|
| `app/worker.py` | Background add/update orchestration | Рабочий |
| `app/updater.py` | Marketplace update pipeline + retries | Рабочий |
| `app/searcher.py` | Ozon search + block helpers | Рабочий |
| `app/generic_scraper.py` | Universal HTML fetcher | Рабочий |
| `app/wb_deals.py` | WB deals and hot offers | Рабочий |

### Хранилище и экспорт
| Модуль | Назначение | Статус |
|---|---|---|
| `app/database.py` | AsyncAlchemy models, CRUD, telemetry, block memory | Рабочий |
| `app/exporter.py` | CSV/XLSX export | Рабочий |
| `app/reporter.py` | HTML report with Chart.js | Рабочий |
| `app/brd_enricher.py` | BRD XLSX enrichment | Рабочий |
| `app/batch_enricher.py` | Batch XLSX/CSV enrichment | Рабочий |
| `app/resilience.py` | Rate limit + circuit breaker | Рабочий |

### Telegram-модули
| Модуль | Назначение | Статус |
|---|---|---|
| `app/telegram_runtime.py` | Telegram polling lifecycle | Рабочий |
| `app/telegram_messages.py` | Message formatting, diagrams, commands | Рабочий |
| `app/telegram_exports.py` | File delivery | Рабочий |
| `app/telegram_ai_reports.py` | AI reports (forecasts, alerts, market overview) | Рабочий |
| `app/telegram_card_tasks.py` | Card task builders | Рабочий |
| `app/telegram_card_research.py` | Competitor research | Рабочий |
| `app/telegram_diagnostics.py` | Network/proxy diagnostics | Рабочий |

### Прочее
| Модуль | Назначение | Статус |
|---|---|---|
| `app/telegram_humanize.py` | Человекообразное форматирование | Рабочий |
| `cloud_wb_function.py` | WB cloud fallback function | Рабочий |
| `deploy_cloud.py` | Cloud deployment script | Рабочий |
| `test_wb.py` | WB smoke test | Рабочий |

---

## 4. Тесты

| Тест | Покрытие |
|---|---|
| `tests/test_agent_loop.py` | Agent loop FSM |
| `tests/test_task_intents.py` | Task intent normalization |
| `tests/test_task_planner.py` | Task planner |
| `tests/test_skill_manifest.py` | Skill manifest graph |
| `tests/test_skill_telemetry.py` | Skill telemetry |
| `tests/test_execution_state.py` | Execution FSM |
| `tests/test_card_filler.py` | Card builder + export |
| `tests/test_card_profiles.py` | Profile loading |
| `tests/test_card_research.py` | Competitor research |
| `tests/test_parsers.py` | Parser integration |
| `tests/test_funpay_parser.py` | FunPay parser |
| `tests/test_parser_universal.py` | Universal parser |
| `tests/test_universal_html_parser.py` | Universal HTML parser |
| `tests/test_database.py` | DB models + telemetry |
| `tests/test_worker.py` | Background worker |
| `tests/test_cli.py` | CLI entrypoint |
| `tests/test_exports.py` | CSV/XLSX exports |
| `tests/test_telegram_exports.py` | Telegram file delivery |
| `tests/test_telegram_ai_reports.py` | Telegram AI reports |
| `tests/test_telegram_card_tasks.py` | Telegram card tasks |
| `tests/test_telegram_card_research.py` | Telegram card research |
| `tests/test_bot_helpers.py` | Bot helper functions |
| `tests/test_bot_startup.py` | Bot startup |
| `tests/test_config.py` | Config loading |
| `tests/test_generic_scraper.py` | Generic scraper |
| `tests/test_searcher.py` | Ozon searcher |
| `tests/test_brd_enricher.py` | BRD enrichment |
| `tests/test_batch_enricher.py` | Batch enrichment |
| `tests/test_skill_notes.py` | Skill notes |
| `tests/test_defrag_audit.py` | Defrag audit |
| `tests/test_wb_deals.py` | WB deals |

---

## 5. Конфигурация

| Файл | Назначение |
|---|---|
| `.env.example` | Шаблон переменных окружения |
| `.env` | Реальные настройки (не в git) |
| `pyproject.toml` | Конфигурация проекта (ruff, mypy, pytest) |
| `requirements.txt` | Зависимости |
| `docker-compose.yml` | Docker: bot + PostgreSQL |
| `Dockerfile` | Docker image build |
| `.github/workflows/ci.yml` | GitHub Actions CI |
| `profiles/default.yaml` | Дефолтный профиль карточек |
| `profiles/electronics.yaml` | Профиль для электроники |

---

## 6. Ключевые зависимости

| Пакет | Версия | Назначение |
|---|---|---|
| aiogram | 3.4.1 | Telegram bot |
| sqlalchemy[asyncio] | 2.0.28 | Async ORM |
| aiosqlite | 0.19.0 | Async SQLite |
| aiohttp | 3.9.3 | HTTP client |
| aiohttp-socks | 0.8.4 | SOCKS proxy |
| playwright | 1.42.0 | Browser automation |
| beautifulsoup4 | 4.12.3 | HTML parsing |
| lxml | 5.1.0 | Fast HTML parser |
| httpx | >=0.27.0 | HTTP client (AI API) |
| anthropic | >=0.25.0 | Claude API |
| openpyxl | >=3.1.0 | Excel export |
| pandas | >=2.0.0 | Data processing |
| PyYAML | >=6.0.0 | YAML profiles |
| tenacity | 8.2.3 | Retry mechanism |
| python-dotenv | 1.0.1 | .env loading |
| fake-useragent | >=2.2.0 | Random User-Agent |

---

## 7. Telegram команды (35)

| Команда | Категория | FSM State |
|---|---|---|
| `/start`, `/help` | Система | — |
| `/add` | Парсинг | `waiting_urls` |
| `/wb` | Парсинг | `waiting_urls` |
| `/update` | Парсинг | — |
| `/list` | Просмотр | — |
| `/status` | Система | — |
| `/search` | Поиск | `waiting_search` |
| `/compare` | Аналитика | `waiting_compare` |
| `/analyze` | AI | — |
| `/deep_analyze` | AI | — |
| `/deals` | AI | — |
| `/wb_deals` | Парсинг | — |
| `/anomalies` | AI | — |
| `/forecast` | AI | — |
| `/alerts` | AI | — |
| `/reviews` | AI | `waiting_reviews` |
| `/ozon_card` | Карточки | `waiting_ozon_card` |
| `/ozon_batch_cards` | Карточки | `waiting_ozon_batch` |
| `/card_research` | Карточки | `waiting_card_research` |
| `/make_card_last` | Карточки | — |
| `/profile` | Карточки | — |
| `/export_csv` | Экспорт | — |
| `/export_excel` | Экспорт | — |
| `/report` | Экспорт | — |
| `/metrics` | Диагностика | — |
| `/blocks` | Диагностика | — |
| `/health` | Диагностика | — |
| `/net_diag` | Диагностика | — |
| `/skill_note` | Skillpack | — |
| `/skill_lesson` | Skillpack | — |
| `/skill_pending` | Skillpack | — |
| `/skills_graph` | Skillpack | — |
| `/subscribe` | Уведомления | — |
| `/unsubscribe` | Уведомления | — |

---

## 8. Модели базы данных

| Таблица | Назначение |
|---|---|
| `products` | Товары (url_hash, url, name, image_url, first_seen, last_check) |
| `price_history` | История цен (product_id, price, availability_status, recorded_at) |
| `scrape_attempts` | Попытки парсинга (marketplace, source, status, http_status, latency_ms, ...) |
| `blocked_patterns` | Память блокировок (trigger, cooldown_sec, strategy, ...) |
| `subscribers` | Подписчики Telegram (user_id) |

---

## 9. Конфигурация .env

| Переменная | Назначение |
|---|---|
| `BOT_TOKEN` | Telegram bot token |
| `ADMIN_IDS` | Telegram user IDs для доступа |
| `AI_PROVIDER` | grok / claude / gemini |
| `GROK_API_KEY` | xAI API key |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `GEMINI_API_KEY` | Google Gemini API key |
| `DATABASE_URL` | SQLite/PostgreSQL URL |
| `MARKETMIND_DATA_DIR` | Каталог данных |
| `COMMON_PROXY` | Общий прокси |
| `PARSER_PROXY` | Прокси для парсинга |
| `TELEGRAM_PROXY` | Прокси для Telegram |
| `RATE_LIMIT_WB_*` | Rate limiting для WB |
| `RATE_LIMIT_OZON_*` | Rate limiting для Ozon |
| `CIRCUIT_BLOCK_THRESHOLD` | Порог circuit breaker |
| `OZON_HEADLESS` | Headless режим Playwright |
| `WB_CLOUD_FUNCTION_URL` | WB cloud fallback URL |
