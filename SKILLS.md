# Карта навыков — MarketMind AI

> Последнее обновление: 09.07.2026
> Строк кода: 15 000+ | Модулей: 40+ | Команд бота: 35 | Зависимостей: 19

---

## Реализовано

### Парсинг и обход защит

| Навык | Файл | Описание |
|---|---|---|
| **Ninja Ozon Parser** | `app/updater.py` | Playwright, случайный UA из 7 вариантов, скролл страницы, движение мыши, stealth JS (скрытие webdriver, plugins, languages), задержки как у человека |
| **Wildberries API Parser** | `app/parsers/wildberries.py` | Без браузера — через API. 3 версии эндпоинта с автофоллбэком, поиск по ID. Получает: цену, старую цену, скидку, рейтинг, кол-во отзывов, бренд, изображение |
| **WB Deals** | `app/wb_deals.py` | Поиск скидок и горячих предложений на Wildberries |
| **Yandex Market Parser** | `app/parsers/yandex_market.py` | HTML/JSON-LD парсинг Yandex Market с телеметрией |
| **FunPay Parser** | `app/parsers/funpay.py` | Парсинг офферов FunPay (игровые/цифровые товары) |
| **Generic Scraper** | `app/generic_scraper.py` | Универсальный скрапер для произвольных страниц |
| **Marketplace Router** | `app/parsers/router.py` | Автоопределяет Ozon / Wildberries / Yandex Market / FunPay по URL |
| **Unified ProductData** | `app/parsers/base.py` | Единая структура данных для всех маркетплейсов |
| **Universal Parsing Core** | `app/universal_parsing_core/` | Алгоритмы классификации страниц, экстракции данных, роутинга парсеров |
| **Retry механизм** | `app/parsers/wildberries.py` | 3 попытки с разными API эндпоинтами, фоллбэк на поисковый API |
| **Определение блокировки** | `app/updater.py` | Детектирует страницы-заглушки Озона, ставит статус `blocked` вместо `deleted` |

---

### База данных

| Навык | Файл | Описание |
|---|---|---|
| **SQLAlchemy Async ORM** | `app/database.py` | Полностью асинхронная БД. SQLite по умолчанию, PostgreSQL — одна строка в `.env` |
| **Core Models** | `app/core/models.py` | Базовые ORM-модели и перечисления |
| **Core Enums** | `app/core/enums.py` | Статусы товаров, маркетплейсов, источников парсинга |
| **Core Errors** | `app/core/errors.py` | Доменные ошибки и исключения |
| **История цен** | `app/database.py` | Таблица `price_history`. Новая запись только при изменении цены или статуса |
| **Дедупликация товаров** | `app/database.py` | MD5-хеш URL как уникальный ключ |
| **Статусы товаров** | `app/database.py` | `in_stock` / `out_of_stock` / `blocked` / `deleted` |

---

### AI и аналитика

| Навык | Файл | Описание |
|---|---|---|
| **AI Provider Router** | `app/ai_client.py` | Единый абстрактный интерфейс к Grok (xAI) и Claude (Anthropic) |
| **Grok API (xAI)** | `app/ai_client.py` | Основной AI провайдер. Настраивается через `GROK_API_KEY` в `.env` |
| **Claude API (запасной)** | `app/ai_client.py` | Автофоллбэк на Claude если нет GROK_API_KEY |
| **Price Agent** | `app/agent.py` | AI-агент: анализ, прогнозы, аномалии, сравнение маркетплейсов |
| **AI Analyzer** | `app/ai_analyzer.py` | Статистика цен, паттерны, прогнозы, аномалии, обзор рынка |
| **Agent Loop** | `app/agent_loop.py` | Цикл: классификация -> стратегия -> выполнение -> оценка -> fallback -> опыт |
| **Task Intents** | `app/task_intents.py` | Нормализация свободного текста в StructuredTask |
| **Task Planner** | `app/task_planner.py` | Планирование pipeline из registry скиллов |
| **Skill Manifest** | `app/skill_manifest.py` | YAML-манифесты скиллов с зависимостями и fallback |
| **Skill Telemetry** | `app/skill_telemetry.py` | JSONL-телеметрия выполнения скиллов |
| **Execution State** | `app/execution_state.py` | FSM выполнения: PLANNING -> EXECUTING -> VALIDATING -> FINISHED |

---

### Экспорт и отчёты

| Навык | Файл | Описание |
|---|---|---|
| **HTML отчёт** | `app/reporter.py` | Интерактивный отчёт с Chart.js |
| **Excel экспорт** | `app/exporter.py` | openpyxl: цветовое форматирование, заморозка строк |
| **CSV экспорт** | `app/exporter.py` | utf-8-sig кодировка для Excel |
| **BRD Enricher** | `app/brd_enricher.py` | Заполнение BRD-таблиц из веб-источников с верификацией |
| **Batch Enricher** | `app/batch_enricher.py` | Массовое обогащение XLSX/CSV таблиц |

---

### Telegram бот

| Навык | Файл | Описание |
|---|---|---|
| **35 команд бота** | `app/bot.py` | Полный список ниже |
| **FSM диалоги** | `app/bot.py` | aiogram 3 FSM: URL, поиск, сравнение, карточки |
| **Фоновый запуск** | `app/worker.py` | Парсер в фоне, прогресс в чат |
| **Telegram Runtime** | `app/telegram_runtime.py` | Жизненный цикл polling, reconnect, proxy fallback |
| **Telegram Messages** | `app/telegram_messages.py` | Форматирование сообщений, диаграммы, команды |
| **Telegram Exports** | `app/telegram_exports.py` | Отправка файлов экспорта и отчётов |
| **Telegram AI Reports** | `app/telegram_ai_reports.py` | AI-отчёты: прогнозы, алерты, обзор рынка |
| **Telegram Card Tasks** | `app/telegram_card_tasks.py` | Построение задач генерации карточек |
| **Telegram Card Research** | `app/telegram_card_research.py` | Исследование конкурентов для карточек |
| **Telegram Diagnostics** | `app/telegram_diagnostics.py` | Диагностика сети, proxy, DNS/TCP/HTTPS |
| **Подписки** | `app/bot.py` | `/subscribe` — рассылка об изменении цен |
| **Защита доступа** | `app/bot.py` | `ADMIN_IDS` в `.env` |

#### Полный список команд бота

| Команда | Описание |
|---|---|
| `/start`, `/help` | Справка по всем командам |
| `/add` | Добавить товар(ы) по ссылке — Ozon/WB/Yandex/FunPay автоматически |
| `/wb` | Добавить товар с Wildberries |
| `/update` | Обновить цены всех товаров |
| `/list` | Список отслеживаемых товаров с текущими ценами |
| `/status` | Статистика базы данных |
| `/search` | Найти товары по названию на Ozon |
| `/compare` | Сравнить цены между маркетплейсами |
| `/analyze` | AI обзор всего портфеля |
| `/deep_analyze` | Глубокий AI анализ рынка |
| `/deals` | Лучшие сделки (минимум цены за 30 дней) |
| `/wb_deals` | Поиск скидок и горячих предложений на WB |
| `/anomalies` | Подозрительные изменения цен + AI комментарий |
| `/forecast` | Прогноз цен на 7 дней |
| `/alerts` | Активные алерты (новые минимумы, скачки) |
| `/reviews` | AI анализ отзывов товара |
| `/ozon_card` | Подготовить карточку Ozon |
| `/ozon_batch_cards` | Пачка карточек Ozon |
| `/card_research` | Исследование конкурентов для карточки |
| `/make_card_last` | Карточка по последнему добавленному товару |
| `/profile` | Профиль карточек (выбор/просмотр) |
| `/export_csv` | Экспорт в CSV |
| `/export_excel` | Экспорт в Excel |
| `/report` | HTML отчёт с графиками |
| `/metrics` | Последние попытки парсинга |
| `/blocks` | Anti-bot и block memory диагностика |
| `/health` | Состояние маркетплейсов и cooldown |
| `/net_diag` | Диагностика сети и proxy |
| `/skill_note` | Создать pending skill proposal |
| `/skill_lesson` | Записать урок в pending proposal |
| `/skill_pending` | Показать pending proposals |
| `/skills_graph` | Mermaid-граф навыков агента |
| `/subscribe` | Подписаться на уведомления об изменении цен |
| `/unsubscribe` | Отписаться |

---

### Инфраструктура

| Навык | Файл | Описание |
|---|---|---|
| **Adapters** | `app/adapters/ozon.py`, `app/adapters/wb.py` | Адаптеры интеграции с Ozon и WB API |
| **.env конфигурация** | `.env`, `.env.example`, `app/config.py` | Все настройки в `.env` |
| **Поддержка прокси** | `app/config.py`, `app/updater.py` | `PROXY` и `TELEGRAM_PROXY` в `.env` |
| **Логирование** | `app/config.py` | RotatingFileHandler — `parser.log` |
| **Resilience** | `app/resilience.py` | Rate limit + circuit breaker для маркетплейсов |

---

## Частично реализовано

| Навык | Проблема | Что сделать |
|---|---|---|
| **Статус `deleted`** | Ставится при любой ошибке загрузки, не только при 404 | Исправить в `updater.py`: `deleted` только при HTTP 404 |

---

## Запланировано (не реализовано)

| Навык | Приоритет | Описание |
|---|---|---|
| **APScheduler** | высокий | Автообновление цен каждые N часов |
| **AliExpress Parser** | средний | Заготовка в `parsers/base.py` есть |
| **Деплой на VPS** | средний | Ubuntu сервер готов, нужны скрипты установки |
| **pytest тесты** | низкий | Реализованы для основных модулей |
| **График цен картинкой** | низкий | PNG график прямо в Telegram |

---

## Зависимости

```
aiogram==3.4.1              # Telegram бот
sqlalchemy==2.0.28          # ORM база данных
aiosqlite==0.19.0           # Async SQLite драйвер
aiohttp==3.9.3              # HTTP клиент
aiohttp-socks==0.8.4        # SOCKS proxy для aiohttp
beautifulsoup4==4.12.3      # Парсинг HTML
httpx>=0.27.0               # HTTP клиент (для AI API)
lxml==5.1.0                 # HTML парсер (быстрый)
python-dotenv==1.0.1        # Загрузка .env
tenacity==8.2.3             # Retry механизм
certifi>=2024.2.2           # SSL сертификаты
playwright==1.42.0          # Браузерная автоматизация
anthropic>=0.25.0           # Claude API
openpyxl>=3.1.0             # Excel экспорт
pandas>=2.0.0               # Обработка данных
PyYAML>=6.0.0               # YAML профили карточек
fake-useragent>=2.2.0       # Случайные User-Agent
```

---

## Структура проекта

```
MarketMind-AI-Core-main/
├── .env                    ← токены и настройки (не в git!)
├── .env.example            ← шаблон настроек
├── requirements.txt        ← зависимости
├── run.sh                  ← быстрый запуск
├── README.md               ← документация
├── SKILLS.md               ← этот файл
├── AGENTS.md               ← инструкции для агентов
├── app/
│   ├── __init__.py
│   ├── main.py             ← точка входа (--telegram / --update / --metrics / --blocks)
│   ├── bot.py              ← Telegram бот, 35 команд
│   ├── config.py           ← загрузка .env
│   ├── database.py         ← модели Product, PriceHistory, telemetry
│   ├── updater.py          ← Ozon ninja парсер (Playwright)
│   ├── worker.py           ← фоновый запуск из бота
│   ├── agent.py            ← AI агент (Grok / Claude)
│   ├── ai_analyzer.py      ← статистика, прогноз, алерты
│   ├── ai_client.py        ← AI provider abstraction
│   ├── agent_loop.py       ← classify/strategy/execute/recover loop
│   ├── task_intents.py     ← StructuredTask normalization
│   ├── task_planner.py     ← TaskPlan и skill registry
│   ├── skill_manifest.py   ← Skill graph и manifest support
│   ├── skill_telemetry.py  ← JSONL runtime telemetry
│   ├── skill_notes.py      ← Pending skill proposals
│   ├── execution_state.py  ← Execution lifecycle FSM
│   ├── resilience.py       ← Rate limit + circuit breaker
│   ├── exporter.py         ← CSV и Excel экспорт
│   ├── reporter.py         ← HTML отчёт
│   ├── searcher.py         ← поиск товаров на Ozon
│   ├── card_filler.py      ← Ozon card draft + AI enhancement
│   ├── card_profiles.py    ← YAML профили карточек
│   ├── card_research.py    ← Исследование конкурентов
│   ├── brd_enricher.py     ← BRD XLSX enrichment
│   ├── batch_enricher.py   ← Batch XLSX/CSV enrichment
│   ├── generic_scraper.py  ← Универсальный скрапер
│   ├── wb_deals.py         ← WB скидки и горячие предложения
│   ├── core/
│   │   ├── __init__.py
│   │   ├── enums.py        ← Статусы, маркетплейсы, источники
│   │   ├── errors.py       ← Доменные ошибки
│   │   └── models.py       ← Базовые ORM-модели
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── ozon.py         ← Ozon API adapter
│   │   └── wb.py           ← WB API adapter
│   ├── parsers/
│   │   ├── base.py         ← BaseParser + ProductData
│   │   ├── ozon.py         ← Ozon через Playwright
│   │   ├── wildberries.py  ← WB через API
│   │   ├── yandex_market.py ← Yandex Market HTML/JSON-LD
│   │   ├── funpay.py       ← FunPay offer parser
│   │   └── router.py       ← автовыбор парсера по URL
│   ├── universal_parsing_core/
│   │   ├── __init__.py
│   │   ├── router.py       ← Universal parser router
│   │   ├── algorithms/     ← Классификация страниц, экстракция
│   │   ├── exporters/      ← Экспорт данных
│   │   ├── parsers/        ← Универсальные парсеры
│   │   └── schemas/        ← Схемы данных
│   ├── telegram_runtime.py ← Telegram polling lifecycle
│   ├── telegram_messages.py ← Форматирование сообщений
│   ├── telegram_exports.py ← Отправка файлов экспорта
│   ├── telegram_ai_reports.py ← AI-отчёты в Telegram
│   ├── telegram_card_tasks.py ← Задачи генерации карточек
│   ├── telegram_card_research.py ← Исследование конкурентов
│   ├── telegram_diagnostics.py ← Диагностика сети/proxy
│   └── utils/
│       ├── __init__.py
│       └── error_research.py ← Исследование ошибок
├── profiles/
│   ├── default.yaml        ← базовый профиль карточек
│   └── electronics.yaml    ← профиль для электроники
├── tests/
│   ├── test_card_filler.py
│   ├── test_card_profiles.py
│   ├── test_parsers.py
│   ├── test_database.py
│   ├── test_worker.py
│   ├── test_cli.py
│   ├── test_task_intents.py
│   ├── test_task_planner.py
│   ├── test_skill_manifest.py
│   ├── test_skill_telemetry.py
│   ├── test_execution_state.py
│   ├── test_agent_loop.py
│   └── test_brd_enricher.py
├── docs/
│   ├── ARCHITECTURE_OVERVIEW.md
│   ├── BOT_WORKFLOWS.md
│   ├── CODING_STANDARDS.md
│   ├── DEMO_SCENARIOS.md
│   ├── PROJECT_MAP.md
│   └── ...
└── project_skills/
    ├── SKILLPACK.md
    ├── SESSION_UPDATE_PROTOCOL.md
    ├── SKILL_TRIGGERS.md
    ├── skills_database.md
    ├── skills_index.json
    └── ...
```
