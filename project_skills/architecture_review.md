# Архитектурный разбор и roadmap skill-system

## Слабые места архитектуры

1. Слишком крупный `parser_agent/app/bot.py`: команды, FSM, natural-language router, генерация карточек, экспорт и аналитика живут в одном файле. Это усложняет тестирование и повторное использование.
2. Дублирование поколений проекта: `parser_agent`, `parser_tg`, `parser_v2`, `tg_bot.py` решают похожие задачи разными способами.
3. Неодинаковая конфигурация: часть проектов использует `.env`, часть `config.yaml`, часть глобальные константы.
4. Нет единого доменного контракта для всех источников: в `parser_agent` есть `ProductData` и `ProductSnapshot`, но updater/database местами используют обычные dict.
5. Selenium прямо не найден; браузерная автоматизация реализована через Playwright. Если Selenium нужен как reusable skill, его стоит добавить отдельным адаптером.
6. Миграции БД ручные и частичные: SQLite columns добавляются кодом, полноценного Alembic-слоя нет.
7. Circuit breaker хранит состояние в памяти: после рестарта история блокировок теряется.
8. Telegram access control простой: `ADMIN_IDS` достаточно для личного бота, но нет ролей/аудита.
9. AI-ответы частично валидируются вручную через JSON extraction; нет общей схемы валидации на Pydantic.
10. Деплой Yandex Cloud Function автоматизирован, но VPS/systemd/cron как полноценные deployment skills почти отсутствуют.

## Потенциальные missing skills

Полный приоритизированный backlog вынесен в `missing_skills_prioritized.yaml`. Короткий порядок работ:

| Priority | Skill | Почему сейчас |
|---|---|---|
| critical | `alembic-async-migrations` | Без миграций любое изменение БД рискованно. |
| critical | `pydantic-domain-schemas` | Нужно убрать смесь dict/dataclass/Pydantic в domain pipeline. |
| high | `bot-feature-modules` | Монолитный `bot.py` уже является главным источником риска. |
| high | `ai-json-schema-task` | AI-ответы надо валидировать схемами, а не только regex/JSON extraction. |
| high | `structured-observability` | Есть telemetry, но нет нормального operational dashboard. |
| high | `persistent-circuit-breaker` | Текущий антиблок забывает состояние после рестарта. |
| medium | `apscheduler-periodic-price-update` | Улучшает UX, но не важнее схем и миграций. |
| medium | `systemd-docker-deploy` | Нужен для VPS, но после стабилизации ядра. |
| medium | `browser-profile-pool` | Усилит Ozon scraping после persistent resilience. |
| medium | `distributed-task-queue` | Нужна при росте нагрузки. |
| medium | `secret-management` | Важно для prod, но не блокирует локальную работу. |
| low | `selenium-driver-factory` | В проекте сейчас Playwright; Selenium нужен только под новое требование. |

## Новые reusable skills

1. Универсальный `MarketplaceAdapter` с методами `fetch_snapshot`, `search`, `normalize_url`, `healthcheck`.
2. `BotFeatureModule` для регистрации Telegram-команд пачками, чтобы вынести команды из монолитного `bot.py`.
3. `ExportPipeline` с единым интерфейсом `collect -> render -> deliver`.
4. `AIJsonTask` для prompt + schema + retry + parse + fallback.
5. `DebugArtifactStore` для HTML, screenshots, snippets, JSONL и ссылок на артефакты.
6. `RateLimitedHttpClient` с marketplace-aware headers/proxy/retry.
7. `CardGenerationPipeline` как отдельный пакет: source parsing, competitor research, profile policy, AI enhancement, exports.

## Самые ценные скиллы проекта

1. `parser-marketplace-router` - расширяемая точка добавления новых маркетплейсов.
2. `ozon-playwright-stealth-fetch` - практический антиблоковый браузерный fetch.
3. `wb-api-cloud-fallback` - гибрид локального API и cloud function.
4. `database-price-history-delta` - хранение истории только при изменениях.
5. `resilience-marketplace-circuit-breaker` - control plane для rate limit и cooldown.
6. `telegram-fsm-batch-workflow` - UX для многошаговых задач в боте.
7. `ozon-card-generation-pipeline` - генерация карточек как отдельная бизнес-ценность.
8. `export-xlsx-reporting` - готовая отдача результатов пользователю.
9. `ai-provider-abstraction` - переключение Grok/Claude без переписывания бизнес-логики.
10. `sandbox-python-execution` - безопасное выполнение кода в агентных сценариях.

## Roadmap развития skill-system

### Этап 1. Нормализация

- Свести дублирующиеся скиллы из `parser_tg`, `parser_v2`, `parser_agent` в одну библиотеку.
- Ввести единый формат skill card в YAML/JSON рядом с Markdown.
- Проставить owner-файл для каждого скилла: source files, tests, maturity, risks.

### Этап 2. Извлечение пакетов

- Вынести `config`, `logging`, `database`, `resilience`, `export`, `ai_client` в reusable modules.
- Разделить `bot.py` на `commands/products.py`, `commands/cards.py`, `commands/analytics.py`, `commands/admin.py`.
- Сделать `MarketplaceAdapter` и перевести Ozon/WB/FunPay на один контракт.

### Этап 3. Production hardening

- Alembic migrations.
- Очередь задач: Dramatiq/Celery/RQ/asyncio queue в зависимости от масштаба.
- Persistent circuit breaker и rate limit в Redis/DB.
- Structured JSON logs и dashboard по scrape attempts.
- systemd/Docker Compose deploy recipes.

### Этап 4. AI skill reuse

- Описать AI-задачи как `prompt + schema + validator + fallback`.
- Добавить тестовые golden cases для карточек, аналитики, natural-language intent.
- Сделать библиотеку промптов с версионированием.

### Этап 5. Каталог и обучение

- Сгенерировать machine-readable `skills.json`.
- Добавить примеры "как собрать новый проект из 5-7 скиллов".
- Добавить maturity levels: prototype, usable, production-ready.
- Для каждого skill добавить минимальный unit-test recipe.
