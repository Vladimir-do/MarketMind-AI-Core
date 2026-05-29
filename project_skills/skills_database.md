# Skills Database

## Общая архитектура проекта

Архитектура каталога `D:\LLM` состоит из нескольких родственных Python-проектов вокруг Telegram/AI/marketplace parsing. Самый зрелый центр - `parser_agent`. Его ядро построено как pipeline:

`Telegram/CLI/Cloud/API input -> worker/orchestrator -> parser/search/AI/card/report services -> async DB/files -> Telegram/API/export output`.

Дополнительные проекты дают отдельные рецепты: FastAPI auth/rate-limit и sandbox в `2026-04-23-new-chat`, self-healing agent loop в `agent3_5`, Rich logging и subprocess orchestration в `autonomous-researcher-main`, ранние версии updater/bot в `parser_tg` и `parser_v2`.

## Основные категории скиллов

- `config`, `logging`, `database`, `telegram`, `parser`, `playwright`, `resilience`, `api`, `ai`, `export`, `filesystem`, `deploy`, `architecture`, `testing`.

## Карта зависимостей

- `config-env-loader` нужен почти всем скиллам.
- `rotating-file-logger` используется parser/updater/bot/export/AI.
- `async-sqlalchemy-session` лежит под `price-history-delta`, `subscribers`, `scrape-attempt-telemetry`, `export`.
- `base-parser-contract` питает `marketplace-router`, `ozon-parser`, `wb-parser`, `funpay-parser`.
- `marketplace-resilience-circuit` используется Ozon/WB parsing и worker.
- `ai-provider-router` используется аналитикой, генерацией карточек и research reports.
- `telegram-fsm-workflow` вызывает worker, search, card generation, export, report.
- `card-profile-yaml` и `competitor-search` зависят от `ozon-card-draft`.
- `api-key-rate-limit-middleware` независим и переиспользуем в FastAPI проектах.
- `sandbox-python-executor` и `self-healing-code-loop` связаны в agent prototypes.

## Стиль разработки проекта

Код прагматичный и итерационный: сначала рабочие сценарии, затем устойчивость через retry/fallback/debug. В `parser_agent` заметна модульность; в `bot.py` и некоторых agent-прототипах логика еще монолитна. Асинхронность используется широко и правильно: `async with`, async sessions, aiohttp, Playwright async API. Ошибки часто переводятся в доменные статусы (`blocked`, `deleted`, `out_of_stock`, `AI error`) и пользовательские сообщения.

---

## Skill 01. Загрузка `.env` и обязательных настроек

- ID скилла: `config-env-loader`
- Категория: `config`
- Краткое описание: централизует чтение переменных окружения, дефолты, обязательные ключи и создание служебных директорий.
- Когда использовать: при запуске бота, API, парсера, AI-клиента, БД или cloud deploy.
- Где найден: `parser_agent/app/config.py`, `parser_v2/app/config.py`, `2026-04-23-new-chat/config.py`; функции `_require`, `require_bot_token`, `get_settings`.
- Зависимости: `rotating-file-logger`, `async-sqlalchemy-session`, `ai-provider-router`.
- Входные данные: `.env`, переменные окружения, пути проекта.
- Выходной результат: типизированные константы/Settings и подготовленные директории.
- Пошаговый алгоритм: загрузить `.env`; прочитать переменные; применить дефолты; провалидировать обязательные значения; нормализовать пути; создать директории для БД/кэшей; экспортировать настройки как константы или cached settings.
- Правила качества: не хранить секреты в коде; давать безопасные дефолты; явно падать при отсутствии обязательных токенов; приводить типы сразу; держать `.env.example` только с плейсхолдерами и прогонять его через secret-scan перед публикацией.
- Типичные ошибки: пустой `BOT_TOKEN`; относительный путь SQLite из неправильной рабочей директории; placeholder proxy принят как рабочий.
- Антипаттерны: читать `os.getenv` хаотично в каждом модуле; silently игнорировать обязательные ключи.
- Production рекомендации: Pydantic Settings для всех проектов, secret manager, разные `.env` для dev/prod, валидация URL/proxy.
- Возможность переиспользования: любой Python-сервис, бот, parser worker, FastAPI app.
- Уровень сложности: `beginner`
- Теги: `env`, `settings`, `dotenv`, `pydantic`, `secrets`

## Skill 02. Ротационное логирование

- ID скилла: `logging-rotating-file`
- Категория: `logging`
- Краткое описание: настраивает file + console logging с ротацией логов.
- Когда использовать: в долгоживущих ботах и парсерах, где логи быстро растут.
- Где найден: `parser_agent/app/config.py:setup_logger`, `parser_tg/app/utils.py:setup_logger`, `autonomous-researcher-main/logger.py`.
- Зависимости: `config-env-loader`.
- Входные данные: `LOG_LEVEL`, `LOG_FILE`, имя логгера.
- Выходной результат: готовый `logging.Logger`.
- Пошаговый алгоритм: получить logger; проверить existing handlers; выставить level; создать formatter; добавить `RotatingFileHandler`; добавить `StreamHandler`; вернуть singleton logger.
- Правила качества: не добавлять handlers повторно; использовать UTF-8; задавать backupCount; отделять user-facing Rich output от технического файла.
- Типичные ошибки: дубли логов при повторном импорте; лог-файл в неожиданной папке; отсутствие ротации.
- Антипаттерны: `print` вместо logger в production-пути; писать секреты и полные токены.
- Production рекомендации: JSON logs, correlation id, marketplace/source/status поля, отправка в Loki/ELK.
- Возможность переиспользования: worker, API, CLI, deploy scripts.
- Уровень сложности: `beginner`
- Теги: `logging`, `rotatingfilehandler`, `observability`

## Skill 03. Async SQLAlchemy session layer

- ID скилла: `database-async-sqlalchemy`
- Категория: `database`
- Краткое описание: создает async engine, session factory, ORM-модели и инициализацию таблиц.
- Когда использовать: когда бот/парсер работает асинхронно и не должен блокировать event loop.
- Где найден: `parser_agent/app/database.py`, `parser_v2/app/database.py`; класс `Database`.
- Зависимости: `config-env-loader`, `logging-rotating-file`.
- Входные данные: `DATABASE_URL`, ORM models.
- Выходной результат: async session factory и созданные таблицы.
- Пошаговый алгоритм: создать `create_async_engine`; собрать `async_sessionmaker`; в `init` открыть transaction; вызвать `Base.metadata.create_all`; выполнить легкие миграции; выдавать сессии через `db.session()`.
- Правила качества: `expire_on_commit=False`; `async with db.session()`; индексы на ключевых полях; не держать сессию дольше операции; для экспорта/аналитики по многим товарам сначала batch-load связанные `PriceHistory` через `IN (...)`, затем группировать в памяти, чтобы не создавать N+1 запросы.
- Типичные ошибки: смешение sync и async SQLAlchemy; забытый `await s.commit()`; lazy relationship после закрытия session.
- Антипаттерны: глобальная session; SQL-строки в бизнес-логике без нужды.
- Production рекомендации: Alembic migrations, connection pool tuning, PostgreSQL для многопользовательского режима; для оптимизаций добавлять regression tests с SQLAlchemy `before_cursor_execute` и проверкой верхней границы SELECT-запросов.
- Возможность переиспользования: мониторинг цен, подписки, telemetry, API backend.
- Уровень сложности: `middle`
- Теги: `sqlalchemy`, `async`, `sqlite`, `postgres`

## Skill 04. Дедупликация товара по hash URL

- ID скилла: `database-url-hash-dedupe`
- Категория: `database`
- Краткое описание: превращает URL в стабильный hash и использует его как уникальный ключ товара.
- Когда использовать: при повторном добавлении ссылок из Telegram или batch-файла.
- Где найден: `parser_agent/app/database.py:url_to_hash`, `Database.save_product`; `parser_v2/app/database.py`.
- Зависимости: `database-async-sqlalchemy`.
- Входные данные: URL товара.
- Выходной результат: существующий или новый `Product`.
- Пошаговый алгоритм: нормализовать URL при необходимости; посчитать MD5; найти `Product.url_hash`; если нет - создать; если есть - обновить поля и `last_check`.
- Правила качества: перед hash желательно canonicalize URL; хранить original URL; индексировать `url_hash`.
- Типичные ошибки: разные query params создают дубли; URL с tracking метками; смена canonical URL marketplace.
- Антипаттерны: дедупликация по названию товара; сравнение URL строк без нормализации.
- Production рекомендации: добавить `canonical_url`, marketplace product id, уникальность `(marketplace, external_id)`.
- Возможность переиспользования: любые каталоги ссылок, парсеры, мониторинги.
- Уровень сложности: `junior`
- Теги: `dedupe`, `hash`, `url`, `idempotency`

## Skill 05. История цены только при изменении

- ID скилла: `database-price-history-delta`
- Категория: `database`
- Краткое описание: пишет новую запись истории только если изменилась цена или статус доступности.
- Когда использовать: для экономии БД и чистой аналитики price changes.
- Где найден: `parser_agent/app/database.py:save_product`, модель `PriceHistory`.
- Зависимости: `database-url-hash-dedupe`.
- Входные данные: product URL, parsed data `{price, availability, name, image_url}`.
- Выходной результат: `Product` и флаг `price_changed`.
- Пошаговый алгоритм: найти/создать товар; получить последнюю историю; сравнить `price` и `availability_status`; при изменении добавить `PriceHistory`; commit; вернуть флаг.
- Правила качества: статус хранить отдельно от цены; `None` price трактовать явно; timestamp в UTC.
- Типичные ошибки: писать историю на каждый poll; считать `None` и `0` одинаковыми; терять blocked/deleted различия.
- Антипаттерны: обновлять только текущую цену без истории.
- Production рекомендации: добавить source/status качества парсинга, валюту, old_price, discount, external_id.
- Возможность переиспользования: мониторинг цен, stock tracking, anomaly detection.
- Уровень сложности: `middle`
- Теги: `price-history`, `delta`, `time-series`, `analytics`

## Skill 06. Telemetry scrape attempts

- ID скилла: `observability-scrape-attempts`
- Категория: `logging`
- Краткое описание: записывает каждую попытку парсинга в таблицу и JSONL.
- Когда использовать: для диагностики блокировок, latency, ошибок и источников данных.
- Где найден: `parser_agent/app/database.py:ScrapeAttempt`, `record_scrape_attempt`, `_append_scrape_attempt_jsonl`; вызовы в `app/updater.py`, `app/parsers/wildberries.py`.
- Зависимости: `database-async-sqlalchemy`, `logging-rotating-file`.
- Входные данные: url, marketplace, source, status, latency, error/http status.
- Выходной результат: запись в БД и optional JSONL.
- Пошаговый алгоритм: измерить latency; классифицировать status/source; обрезать длинный error text; сохранить ORM object; append JSONL для внешней обработки.
- Правила качества: статус должен быть из ограниченного словаря; error text truncation; не падать из-за JSONL.
- Типичные ошибки: telemetry ломает основной parsing flow; слишком длинные HTML ошибки в БД.
- Антипаттерны: диагностировать только по текстовым логам.
- Production рекомендации: метрики Prometheus, dashboard по `marketplace/source/status`, correlation id/job id.
- Возможность переиспользования: любой scraper/API worker.
- Уровень сложности: `middle`
- Теги: `telemetry`, `jsonl`, `metrics`, `scraping`
- Learning telemetry update: every scrape attempt should persist the agent learning fields `site`, `task_type`, `parser_used`, `success`, `errors`, `warnings`, `confidence`, and `next_best_strategy` in both DB and JSONL. Derive safe defaults from URL, marketplace, status, source and error text so older parser call sites keep recording useful learning signals.

## Skill 07. Подписки и broadcast изменений

- ID скилла: `telegram-subscriber-broadcast`
- Категория: `telegram`
- Краткое описание: хранит подписчиков и рассылает уведомления после изменения цен.
- Когда использовать: когда пользователь хочет получать алерты после `/update`.
- Где найден: `parser_agent/app/database.py:Subscriber`, `add_subscriber`, `remove_subscriber`; `parser_agent/app/bot.py:_broadcast_changes`, `cmd_subscribe`.
- Зависимости: `database-price-history-delta`, `telegram-access-control`.
- Входные данные: Telegram user id, список измененных товаров.
- Выходной результат: сохраненная подписка и отправленные сообщения.
- Пошаговый алгоритм: по команде добавить user id; после update собрать changed products; получить subscribers; отправить каждому сообщение; обработать ошибки отправки.
- Правила качества: не дублировать подписчиков; graceful error handling; ограничивать длину сообщений.
- Типичные ошибки: падение всей рассылки из-за одного chat id; отправка слишком длинного текста.
- Антипаттерны: хранить подписчиков в памяти.
- Production рекомендации: unsubscribe на 403, очередь рассылки, rate-limit Telegram API.
- Возможность переиспользования: уведомления о событиях, мониторинги, алерты.
- Уровень сложности: `junior`
- Теги: `telegram`, `broadcast`, `subscriptions`, `alerts`

## Skill 08. Telegram access control через ADMIN_IDS

- ID скилла: `telegram-admin-allowlist`
- Категория: `telegram`
- Краткое описание: ограничивает команды бота списком разрешенных Telegram user id.
- Когда использовать: для приватных парсеров и admin-only инструментов.
- Где найден: `parser_agent/app/bot.py:allowed`, `ensure_allowed`; `parser_v2/app/bot.py:allowed`.
- Зависимости: `config-env-loader`.
- Входные данные: `ADMIN_IDS`, `message.from_user.id`.
- Выходной результат: разрешение или отказ.
- Пошаговый алгоритм: загрузить ids из `.env`; если список пуст - выбрать политику; при каждом handler проверить id; при отказе отправить короткое сообщение и не запускать действие.
- Правила качества: проверять в начале handler; логировать отказ; не раскрывать внутренние команды.
- Типичные ошибки: пустой `ADMIN_IDS` случайно открывает бота; callback handlers забыты.
- Антипаттерны: проверять username вместо stable id.
- Production рекомендации: роли, audit log, per-command permissions.
- Возможность переиспользования: admin bots, internal tools.
- Уровень сложности: `beginner`
- Теги: `telegram`, `security`, `allowlist`, `admin`

## Skill 09. FSM-диалог для многошаговой команды

- ID скилла: `telegram-aiogram-fsm`
- Категория: `telegram`
- Краткое описание: переводит чат в состояние ожидания URL, search query, выбора товара или карточки.
- Когда использовать: когда команда требует второго сообщения или файла.
- Где найден: `parser_agent/app/bot.py:Form`, handlers `cmd_add`, `handle_urls`, `cmd_search`, `handle_search`, `cmd_ozon_card`; `parser_v2/app/bot.py`.
- Зависимости: `telegram-admin-allowlist`, `background-worker-progress`.
- Входные данные: команда Telegram, FSMContext, следующее сообщение пользователя.
- Выходной результат: корректно продолженный workflow.
- Пошаговый алгоритм: объявить `StatesGroup`; в команде поставить state; в handler state прочитать данные; запустить действие; очистить state; обработать cancel/ошибки.
- Правила качества: чистить state после завершения; валидировать вход; давать понятный next prompt.
- Типичные ошибки: state остается после exception; разные команды конфликтуют в одном чате.
- Антипаттерны: хранить промежуточное состояние в глобальных переменных.
- Production рекомендации: RedisStorage вместо MemoryStorage для рестартов и нескольких процессов.
- Возможность переиспользования: анкеты, batch imports, генерация карточек, support bots.
- Уровень сложности: `middle`
- Maturity: `usable`
- Теги: `aiogram`, `fsm`, `conversation`, `state`
- Startup resilience note: pass only the configured `TELEGRAM_API_PROXY`/`TELEGRAM_PROXY` (falling back to explicit `COMMON_PROXY`, then direct mode) into `AiohttpSession(proxy=...)`; do not use parser-only `PROXY`/`PARSER_PROXY` for Telegram. Catch startup `TelegramNetworkError` around initial Telegram API calls such as `delete_webhook`, close `bot.session` in `finally`, and retry with watchdog backoff instead of leaking an aiohttp session or stopping the process.
- Startup observability note: log an explicit `Telegram polling started` marker after webhook cleanup and before `start_polling`; if this marker is absent, debug network/proxy/token startup before investigating message handlers.
- Auth resilience note: catch `TelegramUnauthorizedError` separately and tell the operator to refresh `BOT_TOKEN` from @BotFather; do not print the token value.
- Regression note: if a command starts a two-step FSM flow, preserve the two-step path but also accept inline payloads like `/search query` or `/add https://...`; parse `/command@bot payload` explicitly and cover it with helper tests so typed requests are not silently ignored.
- Pending updates note: avoid hardcoded `drop_pending_updates=True` on startup; make it an explicit config flag so messages queued during network/VPN downtime are not silently discarded.
- Lock safety note: after `await parser_lock.acquire()`, put every awaited operation inside the `try/finally` that releases the lock, including preflight AI advice and Telegram replies; add a regression test that raises before the main worker call and asserts the lock is released.
- Local proxy recovery note: if `Test-NetConnection api.telegram.org -Port 443` fails but a local SOCKS port such as `127.0.0.1:10808` is open, set `TELEGRAM_API_PROXY=socks5://127.0.0.1:10808` or `TELEGRAM_PROXY=socks5://127.0.0.1:10808` in `.env` and verify startup reaches `Telegram polling started`.
- Telegram polling resilience update: split proxy config into `TELEGRAM_PROXY`/`TELEGRAM_API_PROXY`, `PARSER_PROXY`, and `COMMON_PROXY`; legacy `PROXY` is parser-only and must not silently route Telegram. `start_bot()` should treat `Unauthorized` as fatal, but handle `TelegramNetworkError`, `ConnectionResetError`, `WinError 64`, timeouts and transport `OSError`s with watchdog retry/backoff `1,2,5,10,30,60`. If a configured Telegram proxy fails, log a warning, switch to direct mode, and keep the process alive. Startup/polling logs should include `Telegram connected`, `Telegram network error`, `Retry in X seconds`, `Switched to direct mode`, and `Polling restarted`.
- Telegram runtime extraction note: keep `app.bot.start_bot()` as the public CLI/import wrapper, but move network session creation, proxy fallback, retry/backoff and active bot lifecycle into a small runtime module such as `app.telegram_runtime`. Pass `db`, `dp`, command list and a `set_active_bot` callback into the runtime so handlers can keep using the module-level active bot while startup behavior remains independently testable.
- Telegram message extraction note: when reducing `app.bot.py`, prefer moving pure Telegram HTML/message formatting and command payload parsing into a side-effect-free module such as `app.telegram_messages` while leaving aiogram decorators and DB/FSM orchestration in `app.bot.py`. Cover shared parsers like `/command@bot limit` with helper tests before extracting heavier routers.
- Telegram command service extraction note: for export/report/AI commands, keep aiogram decorators and access checks in `app.bot.py`, but move document delivery and report-building into narrowly named modules such as `app.telegram_exports` and `app.telegram_ai_reports`. Test those service modules with mocked bot/export/analyzer dependencies before running the full suite.
- Telegram card extraction note: when card workflows are too coupled to FSM/parser locks to move wholesale, first extract pure task builders (`product/url -> card task`) and small services such as card research into modules like `app.telegram_card_tasks` and `app.telegram_card_research`. Keep old `app.bot` aliases during the transition so existing helper tests and natural-routing callers keep their import contract.
- Telegram lazy import performance note: after extracting command service modules, keep heavy optional dependencies lazy inside the function that needs them. `app.bot` should not import `openpyxl`, report generation, AI analyzer, generic scraper or universal HTML parser during plain startup; measure with `python -X importtime -c "import app.bot"` and keep patch points such as `bot.fetch_html` when tests rely on them.
- Command menu note: keep `HELP_TEXT` and Telegram `set_my_commands(...)` backed by one explicit command list when adding operational commands; expose read-only diagnostics such as `/metrics`, `/blocks`, and `/health` in both places, and regression-test that adaptive diagnostics appear in the help/menu.

Пример кода:

```python
class Form(StatesGroup):
    waiting_urls = State()

@router.message(Command("add"))
async def cmd_add(message: types.Message, state: FSMContext):
    await state.set_state(Form.waiting_urls)
    await message.answer("Пришлите ссылки, по одной на строку")

@router.message(Form.waiting_urls)
async def handle_urls(message: types.Message, state: FSMContext):
    urls = [x.strip() for x in message.text.splitlines() if x.strip()]
    await worker_add_urls(db, urls, notify=message.answer)
    await state.clear()
```

## Skill 10. Фоновый worker с progress callback

- ID скилла: `background-worker-progress`
- Категория: `async`
- Краткое описание: запускает добавление/обновление товаров в отдельной async-функции и сообщает прогресс в чат.
- Когда использовать: долгие операции парсинга, чтобы handler не молчал.
- Где найден: `parser_agent/app/worker.py:worker_add_urls`, `worker_update_all`; `parser_tg/app/worker.py`; `parser_v2/app/worker.py`.
- Зависимости: `marketplace-router`, `database-price-history-delta`, `telegram-subscriber-broadcast`.
- Входные данные: список URL, Database, callback notify.
- Выходной результат: добавленные/обновленные товары, progress messages.
- Пошаговый алгоритм: сгруппировать URL; создать updater/parser; обработать каждый URL; сохранять результат; вызывать notify; вернуть список changes/errors.
- Правила качества: не блокировать event loop; ловить ошибку на уровне одного URL; ограничивать частоту progress messages.
- Типичные ошибки: один exception прерывает весь batch; слишком много сообщений Telegram.
- Антипаттерны: выполнять тяжелый parsing прямо в command handler без progress.
- Production рекомендации: очередь задач, retries с backoff, persistent job table.
- Возможность переиспользования: imports, reports, crawling, batch card generation.
- Уровень сложности: `middle`
- Теги: `worker`, `async`, `progress`, `batch`

## Skill 11. Базовый контракт парсера

- ID скилла: `parser-base-contract`
- Категория: `architecture`
- Краткое описание: задает `BaseParser` и `ProductData` как единый интерфейс для всех маркетплейсов.
- Когда использовать: при добавлении нового marketplace parser.
- Где найден: `parser_agent/app/parsers/base.py`; классы `ProductData`, `BaseParser`.
- Зависимости: нет.
- Входные данные: URL или query.
- Выходной результат: `ProductData` или список `ProductData`.
- Пошаговый алгоритм: определить dataclass полей; объявить abstract `can_handle`, `fetch_product`, `search`; каждый marketplace реализует контракт; downstream код работает с `to_dict()`.
- Правила качества: поля должны покрывать общие потребности; marketplace-specific детали держать optional; избегать dict в новых парсерах.
- Типичные ошибки: разные парсеры возвращают разные ключи; статус availability без словаря.
- Антипаттерны: if/else по marketplace во всей бизнес-логике.
- Production рекомендации: Pydantic model, enum статусы, versioned schema.
- Возможность переиспользования: любой multi-source parser.
- Уровень сложности: `middle`
- Теги: `contract`, `interface`, `dataclass`, `parser`

## Skill 12. Роутинг парсера по marketplace

- ID скилла: `parser-marketplace-router`
- Категория: `parser`
- Краткое описание: определяет маркетплейс по URL и выбирает нужный parser class.
- Когда использовать: `/add` принимает смешанные ссылки Ozon/WB/FunPay.
- Где найден: `parser_agent/app/parsers/router.py`, `parser_tg/app/marketplaces.py`; функции `detect_marketplace`, `get_parser_class`, `fetch_product_auto`.
- Зависимости: `parser-base-contract`, marketplace parsers.
- Входные данные: URL, query.
- Выходной результат: выбранный parser или нормализованный marketplace id.
- Пошаговый алгоритм: проверить домен/паттерны; вернуть enum/string marketplace; подобрать parser class; вызвать `fetch_product` или `search`.
- Правила качества: централизовать список доменов; покрыть tests; логировать unsupported URL.
- Типичные ошибки: короткие ссылки/redirect не распознаны; мобильные домены забыты.
- Антипаттерны: копировать detection logic в bot, worker, updater.
- Production рекомендации: URL canonicalizer, plugin registry for parsers.
- Возможность переиспользования: агрегаторы, price monitors, catalog importers.
- Уровень сложности: `junior`
- Теги: `router`, `marketplace`, `url-detection`

## Skill 13. Playwright stealth fetch для Ozon

- ID скилла: `playwright-ozon-stealth-fetch`
- Категория: `playwright`
- Краткое описание: открывает Ozon через Playwright с user-agent rotation, viewport, stealth script, human delay/scroll/mouse.
- Когда использовать: когда обычный HTTP получает блокировку или пустой HTML.
- Где найден: `parser_agent/app/updater.py:OzonUpdater`, `parser_agent/app/parsers/ozon.py`; методы `_ensure_browser`, `_fetch`, `_human_scroll`, `_move_mouse_randomly`, `_warm_visible_assets`.
- Зависимости: `config-env-loader`, `marketplace-resilience-circuit`, `proxy-reachability-check`.
- Входные данные: URL товара/search, proxy, UA/viewport configs.
- Выходной результат: HTML или parsed product data.
- Пошаговый алгоритм: запустить browser/context; применить stealth JS; выбрать UA/viewport; открыть страницу; подождать network/selector; сделать scroll/mouse; получить content; закрыть page/context.
- Правила качества: всегда закрывать browser в `__aexit__`; разделять blocked/deleted; сохранять debug HTML при failure.
- Типичные ошибки: browser leak; слишком агрессивные delays; Playwright cache/profile в git.
- Антипаттерны: один hardcoded UA; headless без stealth на защищенных страницах.
- Production рекомендации: profile pool, proxy rotation, screenshot artifacts, browser healthcheck.
- Возможность переиспользования: любые сайты с JS/rendering и антиботом.
- Уровень сложности: `senior`
- Теги: `playwright`, `stealth`, `ozon`, `anti-block`

## Skill 14. Парсинг Ozon HTML/API JSON

- ID скилла: `parser-ozon-product-extraction`
- Категория: `parser`
- Краткое описание: извлекает цену, наличие, название и изображение из HTML/API JSON Ozon.
- Когда использовать: после успешной загрузки страницы/API ответа.
- Где найден: `parser_agent/app/updater.py:_parse_price`, `parse_ozon_api_json`, `parse_ozon_html`, `_detect_ozon_html_availability`.
- Зависимости: `playwright-ozon-stealth-fetch`.
- Входные данные: HTML или JSON ответа.
- Выходной результат: dict/ProductData с price/name/image/availability.
- Пошаговый алгоритм: проверить blocked/deleted markers; пройти JSON values рекурсивно; найти price/name/image; fallback на BeautifulSoup selectors; нормализовать цену в int; вернуть availability.
- Правила качества: отделять `blocked` от `deleted`; не падать на изменении DOM; тестировать fixtures.
- Типичные ошибки: цена с пробелами/символами; Ozon меняет структуру JSON; blocked page принят за отсутствие товара.
- Антипаттерны: один CSS selector без fallback.
- Production рекомендации: snapshot tests HTML, multiple extraction strategies, confidence score.
- Возможность переиспользования: marketplace scraping, product intelligence.
- Уровень сложности: `senior`
- Теги: `ozon`, `html`, `json`, `beautifulsoup`

## Skill 15. Детекция блокировки и debug artifacts

- ID скилла: `parser-block-debug-dump`
- Категория: `resilience`
- Краткое описание: определяет anti-bot/blocked страницы и сохраняет HTML/debug информацию.
- Когда использовать: при пустом парсинге, captcha, 403/429, неожиданных структурах.
- Где найден: `parser_agent/app/updater.py:_is_ozon_blocked_text`, `_extract_ozon_incident_id`, `_dump_debug`; `app/utils/error_research.py`.
- Зависимости: `observability-scrape-attempts`.
- Входные данные: HTML/text, URL, exception.
- Выходной результат: статус `blocked`, debug file, scrape attempt.
- Пошаговый алгоритм: проверить маркеры блокировки; извлечь incident id; записать HTML/snippet; создать search hints; сохранить telemetry.
- Правила качества: не сохранять секреты/cookies; ограничивать размер артефактов; включать URL и timestamp.
- Типичные ошибки: debug dump отключен в самый нужный момент; incident id теряется.
- Антипаттерны: считать все ошибки `deleted`.
- Production рекомендации: централизованный artifact store, retention policy.
- Возможность переиспользования: все web scrapers.
- Уровень сложности: `middle`
- Теги: `debug`, `blocked`, `artifact`, `anti-bot`

## Skill 16. Wildberries API parser с basket candidates

- ID скилла: `parser-wb-api-basket`
- Категория: `parser`
- Краткое описание: извлекает WB product id, строит basket hosts/candidates и получает карточку без браузера.
- Когда использовать: WB обычно доступен через публичные JSON endpoints быстрее, чем через browser.
- Где найден: `parser_agent/app/parsers/wildberries.py`; функции `_extract_wb_id`, `_get_basket_host`, `_wbbasket_candidates`, `_build_wb_image_url`, `_fetch_via_wbbasket_card_json`.
- Зависимости: `parser-base-contract`, `proxy-reachability-check`, `observability-scrape-attempts`.
- Входные данные: WB URL или nm id.
- Выходной результат: `ProductData` с ценой, скидкой, рейтингом, отзывами, брендом, image_url.
- Пошаговый алгоритм: достать nm id; рассчитать basket host/path; попробовать candidates/endpoints; распарсить JSON; получить reviews/search fallback; собрать ProductData.
- Правила качества: несколько endpoints; timeout; fallback search; корректная цена в рублях.
- Типичные ошибки: неверный basket shard; price units в копейках; региональные отличия.
- Антипаттерны: открывать WB браузером без нужды.
- Production рекомендации: кешировать basket mapping, добавить регион/warehouse params.
- Возможность переиспользования: WB catalog import, мониторинг скидок.
- Уровень сложности: `senior`
- Теги: `wildberries`, `api`, `basket`, `json`

## Skill 17. Cloud Function fallback для WB

- ID скилла: `parser-wb-cloud-fallback`
- Категория: `deploy`
- Краткое описание: выносит WB fetch в Yandex Cloud Function и использует локальный fallback.
- Когда использовать: если локальный IP блокируется или нужен публичный serverless endpoint.
- Где найден: `parser_agent/cloud_wb_function.py`, `parser_agent/deploy_cloud.py`, `app/parsers/wildberries.py:_fetch_via_cloud_function`.
- Зависимости: `parser-wb-api-basket`, `config-env-loader`.
- Входные данные: WB product id/URL, `WB_CLOUD_FUNCTION_URL`, Yandex Cloud CLI.
- Выходной результат: JSON payload карточки или fallback к локальному парсеру.
- Пошаговый алгоритм: собрать zip функции; создать/найти cloud function; загрузить версию; сделать public invoke; записать URL в `.env`; в parser сначала вызвать cloud endpoint; при ошибке перейти к local.
- Правила качества: таймауты; логировать source=cloud/local; не считать cloud failure фатальным.
- Типичные ошибки: не установлен `yc`; публичный доступ не выдан; URL не записан в `.env`.
- Антипаттерны: зависеть только от cloud без local fallback.
- Production рекомендации: auth token, monitoring cloud errors, regional retries.
- Возможность переиспользования: serverless scraping, IP diversification.
- Уровень сложности: `middle`
- Теги: `yandex-cloud`, `serverless`, `fallback`, `wb`

## Skill 18. FunPay offer parser

- ID скилла: `parser-funpay-offer`
- Категория: `parser`
- Краткое описание: распознает ссылку FunPay, парсит HTML оффера и форматирует summary.
- Когда использовать: для анализа игровых/цифровых предложений из FunPay.
- Где найден: `parser_agent/app/parsers/funpay.py`; `is_funpay_offer_url`, `fetch_funpay_offer`, `parse_funpay_offer_html`, `format_funpay_offer_summary`.
- Зависимости: `ai-provider-router` optional.
- Входные данные: URL оффера или HTML.
- Выходной результат: `FunPayOffer` и текстовое summary.
- Пошаговый алгоритм: проверить URL; загрузить HTML через aiohttp; извлечь title/price/seller/duration; очистить шум; сформировать безопасный текст.
- Правила качества: escape HTML для Telegram; timeout; устойчивые selectors.
- Типичные ошибки: HTML-разметка изменилась; price не распознан; лишний шум в title.
- Антипаттерны: отдавать raw HTML пользователю.
- Production рекомендации: schema validation, snapshot tests.
- Возможность переиспользования: classifieds/offer parsers.
- Уровень сложности: `junior`
- Теги: `funpay`, `offer`, `html`, `aiohttp`

## Skill 19. Marketplace rate limit + circuit breaker

- ID скилла: `resilience-marketplace-circuit`
- Категория: `resilience`
- Краткое описание: задает случайные окна rate-limit и открывает cooldown после серии блокировок.
- Когда использовать: Ozon/WB scraping с риском anti-bot blocks.
- Где найден: `parser_agent/app/resilience.py:MarketplaceResilience`.
- Зависимости: `config-env-loader`.
- Входные данные: marketplace id, block/success events.
- Выходной результат: задержки, open/closed state, cooldown seconds.
- Пошаговый алгоритм: перед запросом `wait_rate_limit`; при success сбросить счетчик; при block увеличить счетчик; если threshold достигнут - открыть cooldown; при open пропускать/сообщать пользователю.
- Правила качества: отдельные состояния по marketplace; jitter; alert only once per open window.
- Типичные ошибки: global sleep блокирует все источники; cooldown не сбрасывается после success.
- Антипаттерны: бесконечно retry без пауз.
- Production рекомендации: Redis persistence, adaptive thresholds, per-proxy buckets.
- Возможность переиспользования: crawlers, API clients, notification senders.
- Уровень сложности: `senior`
- Maturity: `usable`
- Теги: `rate-limit`, `circuit-breaker`, `cooldown`, `anti-block`

Пример кода:

```python
resilience = MarketplaceResilience()

async def guarded_fetch(marketplace: str, fetch):
    if resilience.is_open(marketplace):
        return {"status": "cooldown", "retry_after": resilience.cooldown_remaining(marketplace)}

    await resilience.wait_rate_limit(marketplace)
    result = await fetch()

    if result.get("status") == "blocked":
        cooldown = resilience.mark_block(marketplace)
        return {"status": "blocked", "cooldown": cooldown}

    resilience.mark_success(marketplace)
    return result
```

## Skill 20. Проверка доступности proxy

- ID скилла: `network-proxy-reachability`
- Категория: `network`
- Краткое описание: валидирует proxy URL и проверяет TCP-доступность host:port.
- Когда использовать: перед Playwright/aiohttp запросами через proxy.
- Где найден: `parser_agent/app/config.py:_normalize_proxy`, `parser_agent/app/utils/proxy.py:proxy_is_reachable`.
- Зависимости: `config-env-loader`.
- Входные данные: proxy URL.
- Выходной результат: normalized proxy или false.
- Пошаговый алгоритм: parse URL; отсеять placeholders; проверить host/port; открыть socket timeout; вернуть bool.
- Правила качества: короткий timeout; не логировать credentials; поддержать http/socks при необходимости.
- Типичные ошибки: placeholder `ip:port` принят за proxy; ValueError на invalid port.
- Антипаттерны: падать при недоступном proxy вместо fallback direct.
- Production рекомендации: proxy pool healthcheck, rotation, failure counters.
- Возможность переиспользования: scrapers, API clients.
- Уровень сложности: `junior`
- Теги: `proxy`, `socket`, `network`, `validation`
- Telegram diagnostics note: add `/net_diag` command in bot layer that reports masked proxy values plus DNS/TCP/HTTPS probes to `api.telegram.org`, so operators can localize failures (proxy config vs DNS vs outbound TLS) without reading raw logs. Keep reusable helpers such as proxy masking and DNS/TCP/HTTPS probes in a separate diagnostics module so handlers stay UI-only and startup/runtime code can share the same safe proxy masking.
- Runtime lesson: aiogram/aiohttp_socks may raise `python_socks.ProxyConnectionError` directly when `TELEGRAM_API_PROXY`/`TELEGRAM_PROXY` points to a closed local port such as `127.0.0.1:10808`; `start_bot()` should catch it, close the session, log a masked warning, switch to direct mode, and keep polling alive instead of returning `False`.
- Launcher lesson: when `start_bot()` has already handled and logged a configuration/network startup failure, `app.main --telegram` should return cleanly instead of `sys.exit(1)`, so `START_AGENT.bat` returns to the menu without presenting an expected operator-fixable state as a process crash.

## Skill 21. CSV export для Telegram

- ID скилла: `export-csv-telegram-file`
- Категория: `export`
- Краткое описание: собирает данные мониторинга и возвращает CSV в `BytesIO` для отправки файлом.
- Когда использовать: `/export_csv`.
- Где найден: `parser_agent/app/exporter.py:get_export_data`, `make_csv`, `export_csv`; `tg_bot.py:_send_file`.
- Зависимости: `database-price-history-delta`.
- Входные данные: Database, период выгрузки.
- Выходной результат: `BytesIO` с `.name`, encoded `utf-8-sig`.
- Пошаговый алгоритм: получить товары; собрать последнюю цену и историю; сформировать list[dict]; записать DictWriter в StringIO; encode `utf-8-sig`; задать filename.
- Правила качества: `utf-8-sig` для Excel; stable headers; empty data branch.
- Типичные ошибки: кириллица ломается в Excel; `BytesIO` не перемотан на начало.
- Антипаттерны: писать временный файл без нужды.
- Production рекомендации: stream response for API, large exports pagination.
- Возможность переиспользования: любые Telegram/API exports.
- Уровень сложности: `junior`
- Теги: `csv`, `bytesio`, `telegram`, `excel-compatible`

## Skill 22. Styled Excel export

- ID скилла: `export-xlsx-styled`
- Категория: `export`
- Краткое описание: формирует XLSX с форматированием, frozen panes, ширинами колонок и цветами статусов.
- Когда использовать: `/export_excel`, batch Ozon cards.
- Где найден: `parser_agent/app/exporter.py:make_excel`, `app/card_filler.py:export_ozon_card_xlsx`, `export_ozon_cards_batch_xlsx`.
- Зависимости: `database-price-history-delta`, `ozon-card-draft-builder`.
- Входные данные: list[dict] или OzonCardDraft items.
- Выходной результат: `BytesIO` XLSX.
- Пошаговый алгоритм: создать workbook; добавить sheets; записать headers; применить fonts/fills/borders; записать rows; настроить widths/freeze panes; сохранить в BytesIO.
- Правила качества: wrap_text для длинных полей; number_format для цен; named sheets; filename.
- Типичные ошибки: merged cells мешают последующей записи; слишком узкие колонки; забытый `seek(0)`.
- Антипаттерны: генерировать CSV, когда пользователь ожидает редактируемый Excel.
- Production рекомендации: templates, streaming write-only mode for large datasets.
- Возможность переиспользования: отчеты, импорты маркетплейсов, backoffice.
- Уровень сложности: `middle`
- Теги: `xlsx`, `openpyxl`, `formatting`, `report`

## Skill 23. HTML отчет с embedded images

- ID скилла: `export-html-dashboard`
- Категория: `export`
- Краткое описание: собирает данные мониторинга и рендерит самостоятельный HTML-отчет.
- Когда использовать: `/report` или CLI `--report`.
- Где найден: `parser_agent/app/reporter.py`; функции `collect_report_data`, `generate_html_report`, `embed_report_images`, `export_html_report`.
- Зависимости: `database-price-history-delta`, `price-analytics-forecast`.
- Входные данные: Database, история цен, изображения товаров.
- Выходной результат: HTML-файл/BytesIO с карточками, графиками, distribution blocks.
- Пошаговый алгоритм: собрать товары/историю; рассчитать статистики; загрузить/встроить изображения как data URL; сгенерировать HTML sections; сохранить/отправить файл.
- Правила качества: escape HTML; fallback для картинок; не блокировать отчет из-за image failure; при embed большого числа картинок использовать bounded concurrency (`asyncio.Semaphore`) и один `aiohttp.ClientSession`, чтобы отчет не шел строго последовательно и не открывал слишком много соединений.
- Типичные ошибки: внешние картинки не открываются у пользователя; HTML injection через product name.
- Антипаттерны: строить отчет только строковой конкатенацией без escaping.
- Production рекомендации: Jinja2 templates, CSP, static assets, PDF export.
- Возможность переиспользования: мониторинги, аналитические боты, dashboards.
- Уровень сложности: `middle`
- Теги: `html`, `report`, `dashboard`, `images`

## Skill 24. AI provider abstraction

- ID скилла: `ai-provider-router`
- Категория: `ai`
- Краткое описание: выбирает Grok или Claude по настройкам и предоставляет единый `ask_ai`.
- Когда использовать: AI-анализ, карточки, research, fallback между провайдерами.
- Где найден: `parser_agent/app/ai_client.py`; `autonomous-researcher-main/agent.py` и `orchestrator.py` как похожий паттерн.
- Зависимости: `config-env-loader`, `logging-rotating-file`.
- Входные данные: prompt, system prompt, max_tokens, API keys.
- Выходной результат: text response или human-readable AI error.
- Пошаговый алгоритм: определить provider; проверить ключ; собрать payload; вызвать provider SDK/HTTP; обработать error response; вернуть content.
- Правила качества: единый интерфейс; timeout; temperature controlled; не бросать secrets в logs.
- Типичные ошибки: provider выбран, но ключ пустой; структура ответа изменилась; нет timeout.
- Антипаттерны: вызывать API напрямую из каждого business module.
- Production рекомендации: retry/backoff, token accounting, schema validation, tracing.
- Возможность переиспользования: любые AI-enabled services.
- Уровень сложности: `middle`
- Maturity: `usable`
- Теги: `ai`, `grok`, `claude`, `provider`

Пример кода:

```python
async def ask_ai(prompt: str, *, system: str, max_tokens: int = 800) -> str:
    provider = AI_PROVIDER.lower()
    if provider == "grok" and GROK_API_KEY:
        return await _ask_grok(prompt, system=system, max_tokens=max_tokens)
    if provider == "claude" and ANTHROPIC_API_KEY:
        return await _ask_claude(prompt, system=system, max_tokens=max_tokens)
    if GROK_API_KEY:
        return await _ask_grok(prompt, system=system, max_tokens=max_tokens)
    if ANTHROPIC_API_KEY:
        return await _ask_claude(prompt, system=system, max_tokens=max_tokens)
    return "AI недоступен: задайте ключ провайдера в .env"
```

## Skill 25. Извлечение JSON из AI-ответа

- ID скилла: `ai-json-extraction`
- Категория: `ai`
- Краткое описание: вытаскивает JSON object из ответа LLM, даже если он обернут в markdown.
- Когда использовать: AI генерирует карточку или structured analysis.
- Где найден: `parser_agent/app/card_filler.py:_extract_json_object`, `_clean_ai_string`, `_clean_string_list`, `_clean_string_dict`.
- Зависимости: `ai-provider-router`.
- Входные данные: raw LLM text.
- Выходной результат: dict или None.
- Пошаговый алгоритм: trim; убрать ```json fences; найти первую `{` и последнюю `}`; `json.loads`; проверить тип; очистить строки/списки/словарь.
- Правила качества: логировать parse failure; ограничивать длины; fallback к локальному draft.
- Типичные ошибки: LLM вернул несколько JSON объектов; комментарии в JSON; markdown вокруг.
- Антипаттерны: `eval` для парсинга AI JSON.
- Production рекомендации: Pydantic validation, JSON schema mode/function calling where available, retry with repair prompt.
- Возможность переиспользования: AI agents, генераторы конфигов, structured extraction.
- Уровень сложности: `junior`
- Теги: `llm`, `json`, `validation`, `prompt`

## Skill 26. Аналитика цен: stats, forecast, anomalies

- ID скилла: `price-analytics-forecast`
- Категория: `ai`
- Краткое описание: считает статистику цен, простые прогнозы, паттерны и аномалии.
- Когда использовать: `/forecast`, `/alerts`, `/anomalies`, `/deals`, `/deep_analyze`.
- Где найден: `parser_agent/app/ai_analyzer.py:calc_price_stats`, `simple_forecast`, `detect_pattern`, `DeepAnalyzer`; `app/agent.py:PriceAgent`.
- Зависимости: `database-price-history-delta`, `ai-provider-router`.
- Входные данные: history of `PriceHistory`.
- Выходной результат: trend labels, forecast, alerts, AI commentary.
- Пошаговый алгоритм: взять цены за период; посчитать min/max/avg/volatility; определить rising/falling/stable/volatile; построить простой forecast; найти скачки > порога и новые минимумы; optionally отправить в AI.
- Правила качества: проверять размер выборки; не обещать точность прогноза; отделять deterministic stats от AI advice.
- Типичные ошибки: прогноз по 1-2 точкам; деление на ноль; timezone issues.
- Антипаттерны: скрывать низкую надежность данных.
- Production рекомендации: confidence score, сезонность, robust statistics, anomaly model.
- Возможность переиспользования: finance, inventory, monitoring.
- Уровень сложности: `middle`
- Теги: `analytics`, `forecast`, `anomaly`, `prices`

## Skill 27. Черновик карточки Ozon из текста

- ID скилла: `ozon-card-draft-builder`
- Категория: `export`
- Краткое описание: извлекает из свободного текста поля карточки Ozon: title, brand, price, dimensions, images, keywords, checklist.
- Когда использовать: `/ozon_card`, batch cards, natural-language task.
- Где найден: `parser_agent/app/card_filler.py:OzonCardDraft`, `build_ozon_card_draft`.
- Зависимости: `export-xlsx-styled`.
- Входные данные: свободный текст, URL, price/dimensions hints.
- Выходной результат: `OzonCardDraft`.
- Пошаговый алгоритм: очистить текст; извлечь URLs/price/brand/category; распарсить dimensions/weight; построить title/description; собрать attributes/keywords/selling_points/checklist; создать offer_id.
- Правила качества: не выдумывать факты; missing fields в checklist; stable offer_id.
- Типичные ошибки: неправильная категория; dimensions в разных единицах; SEO keywords из URL мусора.
- Антипаттерны: отправлять в AI пустой prompt без локального draft.
- Production рекомендации: Ozon category/type id lookup, attribute dictionary, validation against Seller API.
- Возможность переиспользования: генераторы карточек WB/Ozon/Yandex Market.
- Уровень сложности: `middle`
- Теги: `ozon`, `card`, `draft`, `seo`

## Skill 28. AI-enhanced карточка с конкурентами

- ID скилла: `ozon-card-ai-enhancement`
- Категория: `ai`
- Краткое описание: улучшает локальный draft карточки через AI и контекст конкурентов.
- Когда использовать: если доступен AI provider и есть competitor search.
- Где найден: `parser_agent/app/card_filler.py:build_enhanced_ozon_card_draft`, `_build_ai_card_prompt`, `_apply_competitor_context`.
- Зависимости: `ozon-card-draft-builder`, `ai-provider-router`, `ai-json-extraction`, `card-profile-yaml`.
- Входные данные: OzonCardDraft, competitors, profile.
- Выходной результат: обогащенный draft с AI notes.
- Пошаговый алгоритм: создать local draft; применить profile; добавить competitor keywords/prices; если AI доступен - отправить prompt со схемой JSON; распарсить ответ; обновить поля; повторно применить profile.
- Правила качества: competitor data использовать только для SEO/ориентиров, не копировать названия; запретить неподтвержденные обещания.
- Типичные ошибки: AI hallucination; невалидный JSON; forbidden words возвращаются после AI.
- Антипаттерны: доверять AI без checklist и schema.
- Production рекомендации: strict schema, moderation/compliance rules, diff view до/после.
- Возможность переиспользования: content enrichment, catalog copywriting.
- Уровень сложности: `senior`
- Maturity: `usable`
- Теги: `ai`, `card`, `competitors`, `json`

Пример кода:

```python
async def build_enhanced_card(task: str, competitors: list[dict], profile: dict):
    draft = build_ozon_card_draft(task)
    apply_card_profile(draft, profile)
    _apply_competitor_context(draft, competitors)

    raw = await ask_ai(_build_ai_card_prompt(draft, competitors, profile), system=AI_CARD_SYSTEM_PROMPT)
    data = _extract_json_object(raw)
    if not data:
        draft.ai_notes = raw[:1200]
        return draft

    draft.name = data.get("name") or draft.name
    draft.description = data.get("description") or draft.description
    draft.attributes.update(data.get("attributes") or {})
    return apply_card_profile(draft, profile)
```

## Skill 29. YAML-профили карточек

- ID скилла: `card-profile-yaml`
- Категория: `config`
- Краткое описание: загружает профиль тона, ограничений и обязательных атрибутов из `profiles/*.yaml`.
- Когда использовать: разные клиенты/категории требуют разного стиля карточки.
- Где найден: `parser_agent/app/card_profiles.py`, `profiles/default.yaml`, `profiles/electronics.yaml`; `bot.py:cmd_profile`.
- Зависимости: `ozon-card-draft-builder`.
- Входные данные: имя профиля, YAML file.
- Выходной результат: `CardProfile`/dict constraints.
- Пошаговый алгоритм: обеспечить папку profiles; перечислить YAML; загрузить выбранный файл; при отсутствии fallback default; применить forbidden words, max_length, required_attributes.
- Правила качества: безопасный yaml loader; defaults; проверка типов.
- Типичные ошибки: битая YAML-структура; профиль выбран в одном чате и влияет на другой.
- Антипаттерны: hardcode всех правил в prompt.
- Production рекомендации: profile schema, per-user persistence, UI для редактирования.
- Возможность переиспользования: prompt profiles, client-specific content policies.
- Уровень сложности: `junior`
- Теги: `yaml`, `profiles`, `content-policy`, `ozon`

## Skill 30. Batch cards из текста или файла

- ID скилла: `telegram-batch-card-files`
- Категория: `telegram`
- Краткое описание: принимает много строк или `.txt/.csv`, генерирует пакет карточек и возвращает batch XLSX/JSON.
- Когда использовать: массовая подготовка карточек Ozon.
- Где найден: `parser_agent/app/bot.py:cmd_ozon_batch_cards`, `handle_batch_card_file`, `_read_text_document`, `generate_ozon_batch_card_files`; `card_filler.py:OzonCardBatchItem`.
- Зависимости: `telegram-aiogram-fsm`, `ozon-card-ai-enhancement`, `export-xlsx-styled`.
- Входные данные: multiline text или uploaded document.
- Выходной результат: batch XLSX и JSON.
- Пошаговый алгоритм: принять команду/caption/file; прочитать текст; split lines; для каждой строки собрать task; сгенерировать draft; собрать statuses; экспортировать batch files; отправить документы.
- Правила качества: ограничить размер файла/количество строк; поэлементные ошибки; summary counts.
- Типичные ошибки: файл не UTF-8; пустые строки; один bad item ломает batch.
- Антипаттерны: требовать ручного запуска по одной карточке.
- Production рекомендации: background jobs, progress per N items, persistent batch id.
- Возможность переиспользования: массовые импорты и генерация контента.
- Уровень сложности: `middle`
- Теги: `batch`, `telegram-file`, `xlsx`, `json`

## Skill 31. Natural-language intent router в Telegram

- ID скилла: `telegram-natural-intent-router`
- Категория: `telegram`
- Краткое описание: пытается понять свободный текст пользователя и направить его в add/search/card/unhandled workflow.
- Когда использовать: бот должен принимать не только slash-команды.
- Где найден: `parser_agent/app/bot.py:parse_natural_request`, `split_natural_tasks`, `dispatch_natural_intent`, `handle_unhandled_message`.
- Зависимости: `task-intent-engine`, `parser-marketplace-router`, `telegram-batch-card-files`, `ozon-card-draft-builder`.
- Входные данные: текст сообщения.
- Выходной результат: выбранный handler или unhandled response.
- Пошаговый алгоритм: извлечь URL; распознать упоминания карточки/поиска/цен; разделить комбинированные задачи; проверить vague reference; вызвать соответствующий handler.
- Правила качества: deterministic rules before AI; понятный fallback; не запускать дорогое действие по неясному тексту.
- Типичные ошибки: false positive на обычный вопрос; комбинированный текст режется неправильно.
- Антипаттерны: все свободные сообщения отправлять в LLM без правил.
- Production рекомендации: intent classifier tests, analytics false positives, confirmation step для дорогих задач.
- Возможность переиспользования: conversational bots, command aliases.
- Уровень сложности: `senior`
- Теги: `nlp`, `intent`, `telegram`, `routing`
- Regression note: multiline text with a URL and a field/schema or requirements list (for example `title`, `price`, `availability`, `rating`, `product_url`, or lines starting with `-`, `1.`, `2.`) is one technical task; do not split schema or requirement lines into independent search/card tasks.
- Architecture note: prefer routing through `task-intent-engine` structured task objects before mapping to legacy Telegram handlers.
- Context follow-up note: when the active `ContextSession.current_task` is scraping and the next Telegram message contains field-like lines (`UPC`, `tax`, `number_of_reviews`, `description`), dispatch the contextual `scraping_task` before calling `split_natural_tasks`; words like "карточка книги" are product-page scope, not Ozon card generation, when field additions are present.

## Skill 32. CLI entrypoint с режимами

- ID скилла: `cli-argparse-modes`
- Категория: `architecture`
- Краткое описание: один `main.py` запускает разные режимы: Telegram, update, metrics, report, deploy.
- Когда использовать: проекту нужен единый вход для cron/manual/debug.
- Где найден: `parser_agent/app/main.py`, `parser_v2/app/main.py`, `autonomous-researcher-main/main.py`.
- Зависимости: `config-env-loader`, domain services.
- Входные данные: command-line flags.
- Выходной результат: запущенный режим.
- Пошаговый алгоритм: определить argparse flags; создать Database/init; в зависимости от флага вызвать service; `asyncio.run` для async операций; вернуть exit code.
- Правила качества: режимы взаимоисключающие; help text; no side effects on import.
- Типичные ошибки: импорт запускает bot; несколько flags конфликтуют; рабочая директория ломает пути.
- Антипаттерны: отдельный скрипт на каждое действие без общей инициализации.
- Production рекомендации: Typer/Click, structured exit codes, cron-safe logs.
- Возможность переиспользования: любые service apps.
- Уровень сложности: `junior`
- Теги: `cli`, `argparse`, `entrypoint`, `asyncio`

## Skill 33. Yandex Cloud Function deploy script

- ID скилла: `deploy-yandex-cloud-function`
- Категория: `deploy`
- Краткое описание: пакует cloud function, создает версию, открывает доступ и обновляет `.env`.
- Когда использовать: для serverless WB parser endpoint.
- Где найден: `parser_agent/deploy_cloud.py`, `parser_tg/deploy_cloud.py`.
- Зависимости: `parser-wb-cloud-fallback`, `config-env-loader`.
- Входные данные: `yc` CLI, source file, env path.
- Выходной результат: публичный function URL в `.env`.
- Пошаговый алгоритм: проверить/создать функцию; собрать zip во временной папке; создать version; allow public invoke; получить id/url; записать env var.
- Правила качества: temp cleanup; проверять subprocess return code; идемпотентность.
- Типичные ошибки: cloud CLI не авторизован; zip содержит лишние файлы; env не обновился.
- Антипаттерны: ручной deploy без script и воспроизводимости.
- Production рекомендации: IaC Terraform, CI deploy, non-public auth, secrets через cloud.
- Возможность переиспользования: любые Python cloud functions.
- Уровень сложности: `middle`
- Теги: `deploy`, `yandex-cloud`, `zip`, `serverless`

## Skill 34. FastAPI API-key middleware + rate limit

- ID скилла: `api-key-rate-limit-middleware`
- Категория: `api`
- Краткое описание: проверяет `X-API-KEY` и ограничивает количество запросов в минуту.
- Когда использовать: простой private API без OAuth.
- Где найден: `2026-04-23-new-chat/api/middleware.py:APIKeyMiddleware`, `check_rate_limit`.
- Зависимости: `config-env-loader`.
- Входные данные: HTTP request, `API_KEY`, `RATE_LIMIT_PER_MINUTE`.
- Выходной результат: pass-through или JSON 401/429.
- Пошаговый алгоритм: пропустить публичные GET paths; прочитать header; сравнить с settings; очистить deque старше 60 сек; проверить лимит; вызвать next middleware.
- Правила качества: одинаковый формат ошибок; `retry_after`; не защищать static/docs при необходимости.
- Типичные ошибки: in-memory лимит не работает на несколько процессов; API key в query string.
- Антипаттерны: проверять ключ внутри каждого route.
- Production рекомендации: Redis rate limit, per-client keys, key rotation, HTTPS only.
- Возможность переиспользования: internal tools, local agents, admin APIs.
- Уровень сложности: `middle`
- Maturity: `usable`
- Теги: `fastapi`, `middleware`, `auth`, `rate-limit`

Пример кода:

```python
class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        api_key = request.headers.get("X-API-KEY")
        if api_key != get_settings().api_key:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})

        check_rate_limit(api_key)
        return await call_next(request)
```

## Skill 35. Sandbox execution Python code

- ID скилла: `sandbox-python-executor`
- Категория: `filesystem`
- Краткое описание: выполняет короткий Python-код во временном файле с timeout и простым blocklist.
- Когда использовать: agent tools, self-healing code, безопасные вычисления пользователя.
- Где найден: `2026-04-23-new-chat/sandbox/python_executor.py:execute_python`, `sandbox/Dockerfile`.
- Зависимости: нет.
- Входные данные: code string, timeout.
- Выходной результат: stdout/stderr/returncode/time или blocked/timeout.
- Пошаговый алгоритм: проверить запрещенные tokens; записать temp `.py`; запустить subprocess с timeout; вернуть output; удалить temp file.
- Правила качества: timeout обязателен; temp cleanup в finally; stdout/stderr capture.
- Типичные ошибки: blocklist легко обходится; subprocess может писать куда угодно; нет resource limits.
- Антипаттерны: `exec` пользовательского кода в процессе бота/API.
- Production рекомендации: Docker/firejail, seccomp, read-only FS, CPU/memory limits, allowlist AST.
- Возможность переиспользования: coding agents, education sandboxes, validators.
- Уровень сложности: `senior`
- Maturity: `prototype`
- Теги: `sandbox`, `subprocess`, `timeout`, `security`

Пример кода:

```python
def execute_python(code: str, timeout: int = 5) -> dict:
    if any(token in code for token in BLOCKED_TOKENS):
        return {"error": "blocked"}

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code)
        path = Path(f.name)

    try:
        result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, timeout=timeout)
        return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}
    finally:
        path.unlink(missing_ok=True)
```

## Skill 36. SQLite/JSONL memory для чата

- ID скилла: `memory-chat-history`
- Категория: `database`
- Краткое описание: сохраняет историю сообщений по session/chat id и возвращает контекст.
- Когда использовать: Telegram/LLM-agent должен помнить диалог.
- Где найден: `2026-04-23-new-chat/memory.py`, `agent3_5/memory/storage.py`, `agent3_5/memory.py`.
- Зависимости: `config-env-loader`.
- Входные данные: chat_id/session_id, role, content.
- Выходной результат: сохраненная и загруженная история.
- Пошаговый алгоритм: инициализировать SQLite/JSONL; при сообщении append; при ответе append; при запросе load последние N; при clear удалить session.
- Правила качества: ограничивать историю; хранить timestamps; разделять sessions.
- Типичные ошибки: контекст растет бесконечно; разные пользователи смешиваются.
- Антипаттерны: глобальный список сообщений.
- Production рекомендации: summarization, vector memory, retention policy, encryption.
- Возможность переиспользования: чат-боты, agents, support assistants.
- Уровень сложности: `junior`
- Теги: `memory`, `sqlite`, `jsonl`, `chat-history`

## Skill 37. Voice transcription в Telegram agent

- ID скилла: `telegram-voice-whisper`
- Категория: `telegram`
- Краткое описание: скачивает голосовое сообщение, транскрибирует Whisper и передает текст в LLM.
- Когда использовать: бот должен принимать voice input.
- Где найден: `2026-04-23-new-chat/agent.py:transcribe_voice`, `handle`.
- Зависимости: `memory-chat-history`, `ai-provider-router` analog.
- Входные данные: Telegram voice file.
- Выходной результат: text transcription.
- Пошаговый алгоритм: получить file object; скачать во временный файл; загрузить/использовать Whisper model; transcribe; удалить temp; передать текст дальше.
- Правила качества: показывать ChatAction; ограничить размер/длину; fallback если torch/whisper недоступны.
- Типичные ошибки: модель грузится на каждый запрос; temp files остаются; нет GPU/CPU контроля.
- Антипаттерны: отправлять raw audio в LLM без transcription layer.
- Production рекомендации: model singleton, queue, streaming transcription, external ASR.
- Возможность переиспользования: voice bots, call summaries.
- Уровень сложности: `middle`
- Теги: `voice`, `whisper`, `telegram`, `asr`

## Skill 38. Self-healing code loop

- ID скилла: `agent-self-healing-code`
- Категория: `ai`
- Краткое описание: LLM генерирует код, sandbox выполняет, ошибки возвращаются LLM для исправления до N попыток.
- Когда использовать: агент должен писать и проверять маленькие Python-скрипты.
- Где найден: `agent3_5/core/agent.py:self_heal`, `2026-04-23-new-chat/tests/test_self_correction.py`.
- Зависимости: `sandbox-python-executor`, `ai-provider-router`.
- Входные данные: task prompt.
- Выходной результат: успешный stdout или сообщение о провале после попыток.
- Пошаговый алгоритм: попросить LLM вернуть только код; выполнить в sandbox; если ok - вернуть результат; если ошибка - отправить код+ошибку в repair prompt; повторить до лимита.
- Правила качества: лимит попыток; код без markdown; sandbox isolation; сохранять trace для debug.
- Типичные ошибки: LLM возвращает объяснения; sandbox небезопасен; бесконечный repair loop.
- Антипаттерны: исправлять код без запуска теста.
- Production рекомендации: AST validation, unit-test harness, diff-based repair, resource limits.
- Возможность переиспользования: coding assistants, data tasks, auto-fix pipelines.
- Уровень сложности: `senior`
- Maturity: `prototype`
- Теги: `agent`, `self-heal`, `sandbox`, `llm`

Пример кода:

```python
async def self_heal(task: str):
    code = await llm("Return only Python code:\n" + task)
    for _ in range(3):
        result = execute_python(code)
        if result.get("returncode") == 0:
            return result["stdout"]
        code = await llm(f"Fix this code:\n{code}\n\nError:\n{result}")
    return "Не удалось исправить код после 3 попыток"
```
## Skill 40. Yandex Market HTML/JSON-LD parser

- ID скилла: `parser-yandex-market-html-jsonld`
- РљР°С‚РµРіРѕСЂРёСЏ: `parser`
- РљСЂР°С‚РєРѕРµ РѕРїРёСЃР°РЅРёРµ: adds a marketplace parser for Yandex Market pages using normal HTTP, JSON-LD, OpenGraph/meta tags, fallback text price extraction and scrape-attempt telemetry.
- РљРѕРіРґР° РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ: when adding a marketplace whose product page exposes structured data in HTML and should fit the existing `BaseParser -> ProductData -> worker -> DB` pipeline.
- Р“РґРµ РЅР°Р№РґРµРЅ: `parser_agent/app/parsers/yandex_market.py`, `parser_agent/app/parsers/router.py`, `parser_agent/app/worker.py`, `parser_agent/app/bot.py`.
- Р—Р°РІРёСЃРёРјРѕСЃС‚Рё: `parser-base-contract`, `observability-scrape-attempts`.
- Р’С…РѕРґРЅС‹Рµ РґР°РЅРЅС‹Рµ: product URL from `market.yandex.*` or compatible mirror/integration URL.
- Р’С‹С…РѕРґРЅРѕР№ СЂРµР·СѓР»СЊС‚Р°С‚: `ProductData` with `marketplace="yandex_market"`, price, availability, brand, rating, reviews count and image URL when available.
- РџРѕС€Р°РіРѕРІС‹Р№ Р°Р»РіРѕСЂРёС‚Рј: detect Yandex Market host; fetch HTML with browser-like headers; parse `application/ld+json`; fall back to `og:title`, `og:image`, `h1` and visible price text; classify availability from schema.org offers and price; record `source=html`, `status=ok/blocked/parse_error/http_error/error`, `http_status`, `latency_ms`.
- РџСЂР°РІРёР»Р° РєР°С‡РµСЃС‚РІР°: try product extraction before declaring antibot, because normal Yandex HTML may contain service words like `isRobot:false` or `captcha` in scripts; blocked status should mean extraction failed and blocking markers are relevant.
- РўРёРїРёС‡РЅС‹Рµ РѕС€РёР±РєРё: false-positive blocked detection from JS payload; assuming JSON-LD always exists; treating search pages as product pages; forgetting to add the new marketplace to Telegram URL validation and update worker.
- РђРЅС‚РёРїР°С‚С‚РµСЂРЅС‹: adding marketplace-specific dicts outside `ProductData`; returning `None` without telemetry; parsing price only from one CSS class.
- Production СЂРµРєРѕРјРµРЅРґР°С†РёРё: add canonical product id extraction, seller fields, richer offer parsing, optional browser fallback only after measurable HTTP parse failure.
- Р’РѕР·РјРѕР¶РЅРѕСЃС‚СЊ РїРµСЂРµРёСЃРїРѕР»СЊР·РѕРІР°РЅРёСЏ: other marketplace pages that expose schema.org Product JSON-LD.
- РЈСЂРѕРІРµРЅСЊ СЃР»РѕР¶РЅРѕСЃС‚Рё: `middle`
- Maturity: `usable`
- РўРµРіРё: `yandex-market`, `json-ld`, `marketplace`, `telemetry`, `aiohttp`

## Skill 41. Verified BRD/XLSX enrichment workflow

- ID скилла: `batch-brd-verified-xlsx-enrichment`
- РљР°С‚РµРіРѕСЂРёСЏ: `export`
- РљСЂР°С‚РєРѕРµ РѕРїРёСЃР°РЅРёРµ: fills BRD product spreadsheets from web sources with strict article verification, checkpointed resume, image download and service columns for audit.
- РљРѕРіРґР° РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ: when a заказ/table task requires filling product names, descriptions, characteristics, categories and images from internet sources without inventing unverified data.
- Р“РґРµ РЅР°Р№РґРµРЅ: `parser_agent/app/brd_enricher.py`, `parser_agent/app/batch_enricher.py`, `parser_agent/app/main.py`, `parser_agent/tests/test_brd_enricher.py`.
- Р—Р°РІРёСЃРёРјРѕСЃС‚Рё: `cli-argparse-modes`, `export-xlsx-styled`.
- Р’С…РѕРґРЅС‹Рµ РґР°РЅРЅС‹Рµ: source XLSX, output XLSX, optional categories DOCX, `--limit`, `--resume`, `--online`, image directory and per-row delay.
- Р’С‹С…РѕРґРЅРѕР№ СЂРµР·СѓР»СЊС‚Р°С‚: completed XLSX with original columns filled when sources pass verification, `img/` files, checkpoint JSON and audit columns such as search query, status, sources, confidence and note.
- РџРѕС€Р°РіРѕРІС‹Р№ Р°Р»РіРѕСЂРёС‚Рј: load workbook and categories; ensure service columns; normalize article; build search query; fetch candidate URLs; accept only sources where article evidence appears at least twice across title, URL and body; generate clean HTML; choose category only from provided list; save image; checkpoint each processed article.
- РџСЂР°РІРёР»Р° РєР°С‡РµСЃС‚РІР°: never silently invent product data; if sources are not verified, keep row for review with `not_found` or `needs_online_research`; add regression tests when a live row exposes a wrong category or bad source heuristic.
- РўРёРїРёС‡РЅС‹Рµ РѕС€РёР±РєРё: too-strict body-only article match misses valid pages where the article is in URL/title; keyword category rules can overmatch generic words such as `spills`; PowerShell stdin encoding can corrupt Cyrillic path literals, so inspect XLSX by glob and print `unicode_escape` when needed.
- РђРЅС‚РёРїР°С‚С‚РµСЂРЅС‹: overwriting user-filled cells without checking; hiding source URLs; one huge run without checkpoint; relying on one source; putting raw scraper noise into description/specs.
- Production СЂРµРєРѕРјРµРЅРґР°С†РёРё: add per-row source snapshots, human review filters, quality report, retry queue and configurable source search providers.
- Р’РѕР·РјРѕР¶РЅРѕСЃС‚СЊ РїРµСЂРµРёСЃРїРѕР»СЊР·РѕРІР°РЅРёСЏ: catalog enrichment jobs, supplier price lists, marketplace card preparation.
- РЈСЂРѕРІРµРЅСЊ СЃР»РѕР¶РЅРѕСЃС‚Рё: `senior`
- Maturity: `usable`
- РўРµРіРё: `xlsx`, `batch`, `enrichment`, `checkpoint`, `brd`, `web-research`

## Skill 42. Skillpack-first agent workflow

- ID скилла: `agent-skillpack-operational-loop`
- РљР°С‚РµРіРѕСЂРёСЏ: `architecture`
- РљСЂР°С‚РєРѕРµ РѕРїРёСЃР°РЅРёРµ: makes the local skillpack a mandatory operating loop for future agents: read relevant skills before work, verify with measurable signals, and update the knowledge base at session close.
- РљРѕРіРґР° РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ: for any substantial project change, especially parsers, Telegram workflows, CLI modes, reports, database, metrics, batch jobs or architecture decisions.
- Р“РґРµ РЅР°Р№РґРµРЅ: `parser_agent/AGENTS.md`, `parser_agent/project_skills/SKILLPACK.md`, `parser_agent/project_skills/SESSION_UPDATE_PROTOCOL.md`, `parser_agent/project_skills/SKILL_TRIGGERS.md`.
- Р—Р°РІРёСЃРёРјРѕСЃС‚Рё: none.
- Р’С…РѕРґРЅС‹Рµ РґР°РЅРЅС‹Рµ: user request, changed files, trigger keywords, existing skill IDs and session outcomes.
- Р’С‹С…РѕРґРЅРѕР№ СЂРµР·СѓР»СЊС‚Р°С‚: implementation that follows existing recipes, explicit verification signals, and an updated or explicitly unchanged skillpack.
- РџРѕС€Р°РіРѕРІС‹Р№ Р°Р»РіРѕСЂРёС‚Рј: detect active `.skillscheck`; read `SKILLPACK.md` and triggers; select skills from `skills_index.json`; read detailed cards; implement using those contracts; run focused/full tests and live smoke checks when appropriate; close the session by updating `skills_database.md` and `skills_index.json` or creating a pending proposal; run `validate_skills.py` after skill edits.
- РџСЂР°РІРёР»Р° РєР°С‡РµСЃС‚РІР°: do not treat skillpack as documentation only; every reusable lesson should become a skill, an update, or a pending proposal; final responses should mention what happened to the skillpack.
- РўРёРїРёС‡РЅС‹Рµ РѕС€РёР±РєРё: implementing from memory while ignoring local recipes; adding a skill to Markdown but not JSON; skipping validation; keeping live bug lessons only in chat history.
- РђРЅС‚РёРїР°С‚С‚РµСЂРЅС‹: one-off undocumented fixes; “final answer only” workflow with no project memory; broad architecture edits without dependency impact analysis.
- Production СЂРµРєРѕРјРµРЅРґР°С†РёРё: add `AGENTS.md` to every project using this skillpack, keep `.skillscheck` active, require validator success in CI for skillpack edits, and add a non-destructive project defrag audit for long-lived repos to measure large modules, duplicate virtualenvs, runtime/cache directories and loose generated artifacts before cleanup or refactor passes. For full cleanup passes, remove duplicate `venv`, browser profiles, debug dumps, scrape exports, caches, logs and loose generated artifacts only after resolving paths under the workspace; keep `.env`, the active `.venv`, and operator databases such as `app/data/parser.db` unless the user explicitly asks to rebuild them.
- Р’РѕР·РјРѕР¶РЅРѕСЃС‚СЊ РїРµСЂРµРёСЃРїРѕР»СЊР·РѕРІР°РЅРёСЏ: any long-lived agent-maintained repository.
- РЈСЂРѕРІРµРЅСЊ СЃР»РѕР¶РЅРѕСЃС‚Рё: `middle`
- Maturity: `usable`
- РўРµРіРё: `skillpack`, `agents`, `workflow`, `knowledge-base`, `validation`

## Skill 43. Task Intent Engine

- ID скилла: `task-intent-engine`
- Категория: `architecture`
- Краткое описание: переводит свободный текст в `StructuredTask` перед выбором executor.
- Когда использовать: когда бот/агент должен понимать контекстные задачи, а не резать вход по строкам.
- Где найден: `parser_agent/app/task_intents.py`, интеграция в `parser_agent/app/bot.py`, тесты `parser_agent/tests/test_task_intents.py`.
- Зависимости: `parser-marketplace-router`.
- Входные данные: raw text, optional `ContextSession`.
- Выходной результат: `StructuredTask(type, target_url, fields, output, requirements, payload, plan)`.
- Пошаговый алгоритм: извлечь URL; распознать высокий intent (`scraping_task`, `marketplace_search`, `card_generation`, `update_task`, `analytics_task`, `batch_task`); собрать поля/требования/вывод; применить текущий контекст; построить план; только потом выбирать executor.
- Правила качества: context-first для многострочных technical specs; requirements не должны попадать в fields; unsupported executors отвечают планом и не запускаются молча.
- Типичные ошибки: строка `title` после scraping prompt превращается в marketplace search; bullet requirements смешиваются с полями; старые handlers вызываются до intent detection.
- Антипаттерны: `строка = задача`, ad hoc regex dispatch без task object.
- Production рекомендации: добавить persistent context storage, расширить `task-planner-skill-registry` реальными executors и telemetry по false positives.
- Возможность переиспользования: conversational agents, Telegram bots, CLI agents, task planners.
- Уровень сложности: `senior`
- Maturity: `prototype`
- Теги: `intent`, `task-object`, `context-memory`, `planner`, `agent-architecture`

- Context handoff rule: if the active task is `page_classification_training` and the next message is URL-only, continue with `classify_page_before_parsing`; if the next message contains an explicit execution command such as scrape/collect/find prices/export/save/CSV, clear the training context and redetect intent from scratch.
- Restaurant menu intent rule: food delivery prompts that mention Chibbis, restaurant/menu/delivery, shashlik/meat/grill/kebab/mangal plus a URL should normalize to a scraping task with `restaurant_menu` parameters, dish entities, price/title fields, focus terms, and browser as the likely next strategy when static HTML lacks structure.
- Output-format lesson: do not treat every `HTML` token in a scraping prompt as `output=html`. Mentions such as "protect from crashes when HTML changes" are engineering requirements, not export requests. Only set `html` output when it appears near explicit output/save/export/result/file wording; standalone `CSV/XLSX/JSON` may remain accepted as compact output shorthand.
- Repair routing lesson: short bug reports such as "агент ошибся" must route to `repair_task`, not marketplace/Ozon search. If a `ContextSession.current_task` exists, inherit its target URL and previous task type, reclassify unknown repair after scraping as `failure_area=parser`, recompute `verification_scope`, `safety_gates`, `requires_full_tests`, and `requires_live_smoke`, then show the repair plan instead of launching search fallback.
- LastFailureMemory lesson: `ContextSession` should persist the latest failed task with `last_error_text`, `last_error_type`, `last_result_metrics`, `last_created_files`, and `last_validation_warnings`. `handle_scraping_task` must record `ScrapingError` validation warnings and clear the failure after a successful scrape. Follow-up repair prompts inherit this evidence so the repair plan explains the actual last failure, not just a generic "agent failed" report.
- Repair executor lesson: route `repair_task` to a dedicated handler that emits both the structured repair plan and a diagnostic report. The report should include target URL, last error type/text, validation warnings, evidence/severity/blast radius, safety gates, verification scope, and suggested focused tests derived from `failure_area`; do not fall back to marketplace search or rerun scraping automatically.

## Skill 44. Task Planner Skill Registry

- ID скилла: `task-planner-skill-registry`
- Категория: `architecture`
- Краткое описание: выбирает skill pipeline для `StructuredTask` и отделяет доступные executors от planned/missing.
- Когда использовать: когда агент должен сначала построить план и проверить исполнимость, а не сразу вызывать handler.
- Где найден: `parser_agent/app/task_planner.py`, интеграция в `parser_agent/app/bot.py`, тесты `parser_agent/tests/test_task_planner.py`.
- Зависимости: `task-intent-engine`.
- Входные данные: `StructuredTask`.
- Выходной результат: `TaskPlan(steps, executable, missing_skills, self_critic)`.
- Пошаговый алгоритм: зарегистрировать `SkillSpec`; выбрать skills по task type, output и requirements; превратить их в ordered `PlanStep`; добавить self-critic checklist; если есть missing/planned skill, не запускать pipeline молча.
- Правила качества: каждый step имеет `skill_id`, action и status; existing handlers помечаются `available`; будущие generic executors помечаются `missing/planned`; user-facing ответ показывает, почему pipeline не исполнен.
- Типичные ошибки: считать planned skill готовым executor; смешивать planner с Telegram handler кодом; скрывать missing skills от пользователя.
- Антипаттерны: hardcoded if/else execution без registry; запуск scraping без self-check и без сохранения контекста.
- Production рекомендации: вынести registry в YAML/JSON, добавить реальные executor adapters, telemetry по выбранным skills и автоматическое создание pending skill proposals для missing skills.
- Возможность переиспользования: agent routers, CLI planners, multi-step data pipelines.
- Уровень сложности: `senior`
- Maturity: `prototype`
- Теги: `planner`, `skill-registry`, `pipeline`, `self-critic`, `executor`

## Skill 45. Skill Manifest Graph and Execution FSM

- ID скилла: `skill-manifest-graph-execution-fsm`
- Категория: `architecture`
- Краткое описание: описывает agent skills как YAML-манифесты с dependencies, fallbacks, scoring policies, runtime telemetry, visual graph export, failure patterns и переводит планирование в graph resolution перед execution state machine.
- Когда использовать: когда agent должен выбирать не линейный список действий, а зависимый pipeline с fallback/recovery и проверяемыми состояниями выполнения.
- Где найден: `parser_agent/app/skill_manifest.py`, `parser_agent/app/skill_telemetry.py`, `parser_agent/app/execution_state.py`, `parser_agent/app/task_planner.py`, `parser_agent/app/bot.py`, `parser_agent/project_skills/skill_manifests/*.yaml`, `parser_agent/tests/test_skill_manifest.py`, `parser_agent/tests/test_skill_telemetry.py`, `parser_agent/tests/test_execution_state.py`.
- Зависимости: `task-intent-engine`, `task-planner-skill-registry`.
- Входные данные: `StructuredTask`, skill manifest YAML, scoring policy, quality metrics, JSONL runtime telemetry, failure patterns.
- Выходной результат: resolved skill graph, ordered plan steps, selected fallbacks, executable/missing status, Mermaid graph, execution run lifecycle, telemetry summary.
- Пошаговый алгоритм: load YAML manifests; build `SkillGraph`; resolve dependencies depth-first; if primary skill is unavailable, choose the available fallback with the highest policy-specific score (`balanced`, `fast`, `cheap`, `stable`, `production_safe`); convert manifests into planner steps; render Mermaid graph for inspection; record skill run metrics in JSONL; execute through states `PLANNING -> PREPARING -> EXECUTING -> VALIDATING -> FINISHED` or `RECOVERING/FAILED`.
- Правила качества: dependencies must appear before dependents; fallback selection must be explicit (`selected_for`); quality score is policy-specific and advisory, not a substitute for status; invalid state transitions raise errors; failure patterns capture trigger/recovery/cooldown without storing secrets; telemetry writes must close files and summarize measurable signals.
- Типичные ошибки: hiding a fallback as if it were the primary skill; treating `planned` as executable; allowing arbitrary state jumps; adding YAML manifests without tests; changing scoring weights without a regression that proves policy choice changes.
- Антипаттерны: hardcoded linear planner only; recovery handled by scattered `except Exception`; skill metadata split between code and docs without a machine-readable manifest.
- Production рекомендации: persist execution runs, record per-step latency/status/retries/token usage, feed telemetry back into `success_rate`, expose `/skills_graph` or CLI graph export for debugging, and generate pending skill proposals from repeated missing/failure patterns.
- Возможность переиспользования: conversational agents, scraping pipelines, marketplace workers, CLI agents and autonomous code agents.
- Уровень сложности: `senior`
- Maturity: `prototype`
- Теги: `skill-graph`, `manifest`, `execution-fsm`, `fallback`, `quality-score`, `failure-memory`

- Agent loop source update: `parser_agent/app/agent_loop.py` and `parser_agent/tests/test_agent_loop.py` add the explicit classify/strategy/execute/confidence/fallback/experience loop to this skill's implementation surface.
- Agent loop lesson: execution must follow an explicit reusable loop: classify page/task first, choose strategy, execute, evaluate confidence, enter fallback on error or confidence below threshold, save measured experience, and reuse that experience before future strategy choice. Keep page-classification training as `classification_only`: it may classify and save the lesson, but must not run scraping/export/product extraction.

## Skill 46. Adaptive Block Memory and Strategy Selector

- ID скилла: `adaptive-block-memory-strategy`
- Категория: `resilience`
- Краткое описание: сохраняет измеренные anti-bot/network блокировки в долговременную память и выбирает следующую стратегию scraping перед дорогими попытками.
- Когда использовать: когда marketplace parser получает `403/429`, `abt-challenge`, `fab_chlg`, `fab_nmk`, captcha, `WinError 64`, reset/timeout/proxy ошибки или повторные browser-blocks.
- Где найден: `parser_agent/app/database.py`, `parser_agent/app/updater.py`, `parser_agent/app/worker.py`, `parser_agent/app/main.py`, тесты `parser_agent/tests/test_database.py`, `parser_agent/tests/test_parsers.py`, `parser_agent/tests/test_worker.py`, `parser_agent/tests/test_cli.py`.
- Зависимости: `observability-scrape-attempts`, `resilience-marketplace-circuit`, `background-worker-progress`, `parser-block-debug-dump`.
- Входные данные: URL, marketplace, source (`api/browser/strategy`), status, HTTP status, latency, error class/text, proxy, browser profile, recent block history and adaptive env thresholds.
- Выходной результат: запись `BlockedPattern` в БД и JSONL, strategy dict (`normal`, `defer_same_url`, `api_only_browser_cooldown`, `network_cooldown`), CLI report через `--blocks`.
- Пошаговый алгоритм: классифицировать trigger из явного статуса, HTTP-кода или текста ошибки; записать block pattern рядом со scrape attempt; перед новой попыткой собрать recent patterns по marketplace/window; если тот же URL недавно заблокирован browser/strategy, отложить URL; если browser blocks превышают порог, временно отключить browser fallback; если network failures превышают порог, поставить network cooldown; в updater/worker применять решение до дорогих API/browser вызовов и записывать adaptive skip как измеряемое событие.
- Правила качества: selector failure должен возвращать `normal`, а не ломать scraping; skip разрешен только на основе сохраненных измеримых событий; не писать секреты proxy/cookies, обрезать `error_text`; каждое новое adaptive правило покрывать regression test; CLI diagnostics должны показывать trigger/source/status/strategy/cooldown без догадок.
- Типичные ошибки: линейно долбить один и тот же заблокированный URL; смешивать transient network error и anti-bot без trigger; хранить block memory только в логах; включать browser fallback при уже известном browser cooldown; делать skip без telemetry.
- Антипаттерны: hardcoded sleep вместо strategy decision; ad hoc блокировки в parser code без общей памяти; потеря proxy/profile контекста; повтор retries по товарам с низкой вероятностью успеха.
- Production рекомендации: добавить отдельные browser profile IDs, proxy health score, per-strategy success rate, priority/cost model, dashboard по `blocked_patterns`, периодическую очистку старых rows и live smoke checks по безопасным marketplace URL.
- Возможность переиспользования: scraping agents, marketplace workers, distributed crawlers and resilient batch enrichers.
- Уровень сложности: `senior`
- Maturity: `usable`
- Теги: `anti-bot`, `block-memory`, `strategy-selector`, `cooldown`, `network-resilience`, `telemetry`
- Runtime scoring update: persist `proxy`, `browser_profile`, and `strategy` on successful scrape attempts too, not only on block events; compute `marketplace_heat_score`, dynamic cooldown steps, source strategy scores, browser/profile reputation and proxy reputation from the same measurement window. Let `recommend_scrape_strategy` return `skip_api`, `skip_browser`, `heat_score`, `source_scores`, `preferred_browser_profile`, and `preferred_proxy`, while keeping selector failure safe by falling back to `normal`.
- Self-healing update: when recent API/html blocks exceed the configured threshold, return `self_heal_disable_api` so API-only marketplace workers can pause that route and record `adaptive_api_cooldown`; when heat exceeds the predictive threshold, return `predictive_heat_cooldown` to avoid browser attempts before burning another block.
- Browser learning rule: if `source=browser` has three non-successful attempts in the last hour (`blocked`, `error`, `parse_error`, `http_error`, etc.; exclude `ok` and `skipped`), `recommend_scrape_strategy` must return `api_only_browser_cooldown` with `skip_browser=True` and `next_best_strategy=api_or_structured_source_only`. This rule is based on scrape attempts, not only blocked-pattern rows.
- Page classification lesson: `EMPTY` means no useful body content, not "prices were not found". Detect page structure before price extraction: repeated product/card/item blocks, detail links, category headings, grids/lists and pagination can classify a page as catalog even with zero prices. Useful but structurally ambiguous static HTML should become `UNKNOWN_JS` with `next_strategy=browser`.

## Skill 47. Parser Agent Training Playbook

- ID скилла: `parser-agent-training-playbook`
- Категория: `architecture`
- Краткое описание: defines a practical project-local training loop for improving agent behavior without model fine-tuning: intent normalization, skill planning, explicit missing executors, measurable verification and skillpack feedback.
- Когда использовать: when the user asks to teach, train, fine-tune, improve or make the parser agent work more correctly.
- Где найден: `parser_agent/docs/AGENT_TRAINING_PLAYBOOK.md`, `parser_agent/AGENTS.md`.
- Зависимости: `agent-skillpack-operational-loop`, `task-intent-engine`, `task-planner-skill-registry`, `skill-manifest-graph-execution-fsm`.
- Входные данные: user behavior request, failed prompts, good prompts, parser failures, marketplace telemetry, expected files and current skill IDs.
- Выходной результат: updated agent operating rules, tests, explicit missing skills or executors, measurable verification signals and skillpack updates.
- Пошаговый алгоритм: collect examples; add intent regressions; add planner regressions; implement the smallest safe executor through existing contracts; verify with focused/full tests and live smoke checks when safe; feed reusable lessons into the skillpack.
- Правила качества: do not present documentation as training unless it changes future behavior; missing executors must be visible; parser work must preserve `ProductData`; worker work must preserve progress/resume semantics; live marketplace changes must write telemetry.
- Типичные ошибки: trying to fine-tune blindly before defining examples; executing low-confidence intents; hiding planned skills as available; keeping repeated failures only in chat history; adding new Russian user-facing text without checking readability.
- Антипаттерны: keyword-only handler dispatch; one-off prompts without tests; skillpack edits without validator; silent fallback from user-specified URL to marketplace search.
- Production рекомендации: add persistent execution telemetry, generate pending skill proposals from repeated missing skills, and add a text-integrity check for Russian bot/docs strings.
- Возможность переиспользования: parser agents, Telegram task agents, scraping pipelines and skillpack-maintained repositories.
- Уровень сложности: `middle`
- Maturity: `usable`
- Теги: `training`, `agent-behavior`, `skillpack`, `intent`, `planner`, `verification`
## Skill 48. Parsing Craft Playbook

- ID скилла: `parsing-craft-playbook`
- Категория: `parser`
- Краткое описание: defines the high-quality parsing standard for Parser Agent: structured sources first, layered extraction, explicit fallbacks, normalization, telemetry and regression tests.
- Когда использовать: when adding, fixing, reviewing or training marketplace parsers and scraping workflows.
- Где найден: `parser_agent/docs/PARSING_CRAFT_PLAYBOOK.md`, `parser_agent/AGENTS.md`.
- Зависимости: `parser-base-contract`, `parser-marketplace-router`, `observability-scrape-attempts`, `parser-block-debug-dump`, `adaptive-block-memory-strategy`, `parser-agent-training-playbook`.
- Входные данные: marketplace URL or payload, parser failure, HTML/API fixture, target fields, telemetry status and expected `ProductData`.
- Выходной результат: robust parser implementation or review plan with normalized `ProductData`, explicit source/status, fallback behavior, block classification and focused tests.
- Пошаговый алгоритм: route marketplace centrally; prefer API/embedded JSON/JSON-LD before visual selectors; extract product id/title/price/availability/image in layers; normalize values; classify failures; record scrape attempts; add regression tests and safe live smoke checks when needed.
- Правила качества: fallbacks must be visible; parser failure must not become fake product data; browser fallback is not the default fast path; anti-bot/network errors must be classified separately; each live bug should become a measurable test or pending skill proposal.
- Типичные ошибки: selector soup; raw dicts leaking out of parsers; broad exception handling without telemetry; saving guessed data; confusing out-of-stock with parse failure; retrying blocked URLs without adaptive cooldown.
- Антипаттерны: hardcoded sleeps instead of strategy decisions; marketplace if/else outside router; one CSS class as the only extraction path; declaring blocked before trying real product extraction.
- Production рекомендации: keep minimal fixtures per marketplace, track source-specific success rate, add parser contract tests for every marketplace and run live smoke checks against safe URLs before release.
- Возможность переиспользования: marketplace parsers, generic scraping pipelines, batch enrichers and parser code reviews.
- Уровень сложности: `senior`
- Maturity: `usable`
- Теги: `parser`, `scraping`, `craft`, `telemetry`, `fallback`, `productdata`, `regression`
- Regression lesson: Russian scraping prompts often mix service commands (`задача`, `собери с первой страницы`) and requirements (`добавить логирование`, `добавить обработку ошибок`) with desired fields. Intent normalization must map real field aliases such as `название книги`, `цену`, `наличие`, `рейтинг`, `ссылку на карточку` to canonical fields and keep service commands/requirements out of `StructuredTask.fields`.
- Detail-page scraping lesson: generic catalog scrapers should separate listing fields from product detail fields. Collect listing cards first, then enrich requested detail-only fields (`upc`, `product_type`, `tax`, `number_of_reviews`, `description`) from `product_url` pages with a shared HTTP session, bounded concurrency, delay/retry controls, and regression tests for both intent routing and detail HTML extraction.
- Page-classification context lesson: if `ContextSession.active_intent` is `page_classification_training` and the session is waiting for a page URL, a follow-up message containing only a URL must continue that task through `classify_page_before_parsing(url)` instead of starting a scraping pipeline, export, product extraction, or marketplace add flow. Cover this with a regression named like `test_context_url_continues_page_classification_training`.
- Page-structure classification lesson: `EMPTY` means the fetched HTML/body has no useful content, not that price extraction failed. Detect `CATALOG` before price-dependent entity extraction using repeated cards (`article.product_pod`, product/card/item classes), repeated detail links, category/title signals and pagination/next links; BooksToScrape category pages such as `/catalogue/category/books/travel_2/index.html` should classify as `universal_catalog` / `CATALOG` with confidence >= 0.85.
- Telegram Russian UX lesson: user-facing bot responses should use Russian labels (`Намерение`, `Действие`, `Статус`, `Предупреждения`, `План выполнения`, `Самопроверка`) while preserving technical field names such as `task_type`, `page_structure`, and `confidence` only when they are explicitly part of a training/debug protocol. Add regression checks that prevent English service labels like `Pipeline`, `Self-check`, or `executor` from leaking into natural Telegram replies.
- Natural-task splitting lesson: multiline training prompts containing block markers such as `Сначала определи:`, `Верни:`, `Проверь:`, `Требования:`, `Поля:`, or `Задача:` must remain one task; bullet lines inside that block must not become separate tasks or Ozon search queries. Standalone protocol fragments such as `- task_type`, `- page_structure`, `- confidence`, or `- warnings` should resolve to `unknown`, not `marketplace_search`, unless a real product query or supported marketplace URL is present.
- Scraping preflight lesson: generic scraping handlers must classify the target HTML before product extraction. Allow extraction for `CATALOG`, `SINGLE`, or `MIXED`; block `ARTICLE`, `EMPTY`, `UNKNOWN`, and `UNKNOWN_JS` with a visible `Scraping preflight` diagnostic, `next_strategy`, and `ContextSession.last_failure` entry instead of running a product scraper that will emit all-empty fields. A bare `scrape this` URL on a freelance/project/article page should stop at `page_structure=article`, while JS-only pages should point to browser rendering.
- Browser fallback lesson: when preflight returns `UNKNOWN_JS` or a loading shell with `next_strategy=browser`, the scraping handler must set an explicit `browser_fallback`/`next_strategy=browser` parameter and the generic scraper must use a rendered HTML fetcher for page sequence, discovered links and detail enrichment. Do not merely print "browser fallback" while repeating the same static HTTP request; cover the switch with network-free tests by patching `fetch_html_browser`.
- Domain task-type lesson: keep executor-level `TaskType.SCRAPING` separate from domain-level `parameters["task_type"]`. URL scraping prompts should classify the domain schema before execution: BooksToScrape -> `product_catalog`, Chibbis/food delivery -> `restaurant_menu`, FL project pages -> `freelance_project`, article/news/blog URLs -> `article`, JSONPlaceholder/API endpoints -> `api_source`, otherwise `universal_page`. Preflight and repair diagnostics should display this domain type so the agent chooses the right schema instead of forcing every URL into product fields.
- BooksToScrape full-catalog lesson: prompts like "collect data for all books" must set `scope=all_pages` and `pagination=True`; report instructions ("after completion write how many books/files/problems/improvements") and engineering requirements ("logging", "error handling", "delay", "normal function structure", "HTML-change protection") must not become extraction fields or focus filters. Generic BooksToScrape CSV smoke should collect 1000 records across 50 pages with fields `title,price,availability,rating,product_url`.
- Confidence scoring lesson: price-only extraction is weak evidence (`350 ₽` without a reliable title should score around `0.30` and emit a low-confidence warning). Title + price without a detail link is medium confidence around `0.75`; title + price + detail link is high confidence (`>=0.85`). If any data was produced or enriched through an AI/LLM parser chain, include a warning telling the user to verify the result.
- Recovery lesson: empty or loading-only HTML such as `<div>Загрузка...</div>` is not a parser panic. Return a normal `ParseResult(success=False, page_structure=EMPTY, warnings=["no entities found"], next_strategy="browser")` so the agent can recover through a rendered/browser strategy instead of raising or inventing data.
- Live-smoke hygiene lesson: scripts that call real marketplace APIs must be opt-in and must not expose pytest-collected names like `test_*`; name the coroutine/entry point `smoke_*` or move it outside test discovery so the full local suite stays deterministic and network-independent.

## Skill 49. Project Self-Healing Repair Loop

- ID скилла: `project-self-healing-repair-loop`
- Категория: `architecture`
- Краткое описание: turns parser-agent failures into a professional regression-first repair workflow with evidence, severity, blast-radius, safety gates, verification scope and skillpack feedback.
- Когда использовать: when the user reports that the agent, parser, context session, page classifier, planner, exporter, tests, or marketplace workflow behaved incorrectly and asks to fix or teach the agent to recover.
- Где найден: `parser_agent/docs/SELF_HEALING_PLAYBOOK.md`, `parser_agent/app/task_intents.py`, `parser_agent/app/task_planner.py`, `parser_agent/app/agent_loop.py`, `parser_agent/project_skills/skill_manifests/core.yaml`, `parser_agent/tests/test_task_intents.py`, `parser_agent/tests/test_task_planner.py`, `parser_agent/tests/test_agent_loop.py`.
- Зависимости: `agent-skillpack-operational-loop`, `task-intent-engine`, `task-planner-skill-registry`, `skill-manifest-graph-execution-fsm`, `parser-agent-training-playbook`, `parsing-craft-playbook`, `adaptive-block-memory-strategy`.
- Входные данные: user failure report, optional URL, logs/errors, wrong task/plan/result, failed test or live smoke signal.
- Выходной результат: `StructuredTask(type=repair_task)` with `failure_area`, `severity`, `evidence_types`, `blast_radius`, `verification_scope`, `safety_gates`, executable repair plan, regression-first `AgentLoopPlan`, focused/full/smoke verification decision, and updated skillpack or pending session update.
- Пошаговый алгоритм: detect repair intent before normal scraping/search; set `repair_mode=regression_first`; classify `failure_area`; assign `severity` from evidence and production/security risk; estimate `blast_radius`; check safety gates; plan `repair.reproduce -> repair.classify -> repair.regression_test -> repair.implement_fix -> repair.verify -> repair.skillpack_update -> quality.self_critic`; run the agent loop as `regression_first_repair`; save reusable lessons through the session update protocol.
- Правила качества: do not guess that a bug is fixed; do not hide missing executors; do not invent scraped data; protect every live bug with a measurable regression or smoke signal; run full tests when `blast_radius=shared`; require safe target or approval for network smoke; do not revert unrelated user changes.
- Типичные ошибки: treating a bug report as a fresh scraping task; fixing only prompt text without tests; skipping skillpack feedback; calling a planned step executable; losing the original failure signal.
- Production рекомендации: persist repair outcomes and repeated failure patterns, generate pending skill proposals from recurring repair areas, and expose repair plans in Telegram/CLI debug output.
- Возможность переиспользования: parser agents, autonomous code assistants, scraping pipelines and skillpack-maintained repositories.
- Уровень сложности: `senior`
- Maturity: `usable`
- Теги: `self-healing`, `repair`, `regression`, `agent-loop`, `skillpack`, `verification`
