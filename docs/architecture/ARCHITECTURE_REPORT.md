# ARCHITECTURE_REPORT.md — Полный архитектурный отчёт MarketMind AI

> Дата отчёта: 2026-07-12
> Проект: MarketMind-AI-Core-main
> Тип: Marketplace automation core (Telegram bot + CLI)

---

## 1. Executive Summary

**MarketMind AI** — Python-ядро автоматизации маркетплейсов. Система предоставляет:
- Telegram-бот с 35 командами и NL-маршрутизацией
- CLI для массовых операций
- Парсинг Ozon (Playwright), Wildberries (API), Yandex Market (HTML), FunPay
- Генерацию карточек Ozon с AI-улучшением
- Аналитику: прогнозы, аномалии, алерты, обзор рынка
- Экспорт: CSV, XLSX, HTML-отчёты
- Агентную архитектуру: intent → planner → skills → execution → telemetry → recovery

**Текущий статус:** Рабочее ядро с Telegram-интерфейсом. SaaS/API/Dashboard — в планах.

---

## 2. Архитектурные слои

### 2.1 Входные интерфейсы
```
Пользователь → Telegram Bot (aiogram 3) / CLI (app/main.py)
```

### 2.2 Слой намерений
```
Свободный текст → detect_task_intent() → StructuredTask
```
- `task_intents.py`: 12 типов задач (SCRAPING, MARKETPLACE_SEARCH, CARD_GENERATION, ADD_URLS, UPDATE, ANALYTICS, BATCH, REPAIR, PAGE_CLASSIFICATION_TRAINING, STATUS, LIST, UNKNOWN)
- Контекстные сессии: `CHAT_PROFILES`, `CHAT_CONTEXTS`

### 2.3 Слой планирования
```
StructuredTask → TaskPlanner → TaskPlan → ordered steps
```
- `task_planner.py`: реестр навыков, генерация плана
- `skill_manifest.py`: YAML-манифесты с зависимостями, fallback, scoring
- `skills_index.json`: машинный каталог навыков

### 2.4 Агентный цикл (Agent Loop FSM)
```
ClassifyPage → ChooseStrategy → Execute → EvaluateConfidence → FallbackOnError → SaveExperience
```
- 6 стратегий: classify_then_scrape, catalog_paginated_scraping, marketplace_search, marketplace_url_monitoring, regression_first_repair, classification_only
- `execution_state.py`: FSM PLANNING → EXECUTING → VALIDATING → FINISHED

### 2.5 Слой парсеров
```
URL → Router → Ozon/WB/YandexMarket/FunPay/Universal → ProductData
```

| Парсер | Технология | Модуль |
|---|---|---|
| Ozon | Playwright headless + stealth | `parsers/ozon.py` |
| Wildberries | API + basket candidates | `parsers/wildberries.py` |
| Yandex Market | HTML + JSON-LD | `parsers/yandex_market.py` |
| FunPay | HTML parsing | `parsers/funpay.py` |
| Universal | Page classification + DOM analysis | `parsers/universal.py` |

Единый контракт: `ProductData` (name, price, availability, url, image_url, raw_snapshot)

### 2.6 Слой адаптеров API
```
Adapters → Ozon Seller API / Wildberries API
```
- `adapters/ozon.py`: Ozon Seller API adapter
- `adapters/wb.py`: Wildberries API adapter

**Отличие от парсеров:** Адаптеры работают с официальными API, парсеры — с HTML/внутренними API.

### 2.7 Universal Parsing Core
```
Page → PageStructure classification → UniversalHTML parser → NormalizedEntity
```
- Классификация страниц: catalog, single, article, empty, unknown, mixed, unknown_js
- Схемы: PageStructure, ParseResult, NormalizedEntity

### 2.8 Генерация карточек Ozon
```
Ввод (текст/URL) → Card Filler → OzonCardDraft → AI Enhancement → Export (JSON/XLSX)
```
- YAML-профили: tone, required attributes, content restrictions
- AI: заголовок, описание, атрибуты, ключевые слова, заметки
- Batch: до 300 карточек за раз

### 2.9 AI и аналитика
```
Данные → AI Client (Grok/Claude/Gemini) → Price Agent / AI Analyzer → Reports
```
- `ai_client.py`: абстракция провайдеров
- `agent.py`: анализ портфеля, алерты, прогнозы
- `ai_analyzer.py`: статистика, паттерны, аномалии, обзор рынка

### 2.10 Хранилище
```
AsyncAlchemy (SQLite/PostgreSQL) + JSONL logs + Файловая система
```
- Таблицы: products, price_history, scrape_attempts, blocked_patterns, subscribers
- Дедупликация: MD5(url) как уникальный ключ
- Телеметрия: scrape_attempts с source, status, http_status, latency_ms

### 2.11 Устойчивость (Resilience)
```
Circuit Breaker → Adaptive Cooldown → Block Memory → Strategy Recommendation
```
- `resilience.py`: rate limit + circuit breaker
- `database.py`: adaptive cooldown (экспоненциальный рост), marketplace health, strategy recommendation

### 2.12 Экспорт
```
Данные → CSV / XLSX / HTML Report / AI Reports
```
- `exporter.py`: CSV (utf-8-sig), XLSX (openpyxl с форматированием)
- `reporter.py`: HTML с Chart.js
- `telegram_exports.py`: отправка файлов в Telegram
- `telegram_ai_reports.py`: AI-отчёты (прогнозы, алерты, обзор рынка)

---

## 3. Модели данных

### 3.1 Таблицы БД

| Таблица | Описание |
|---|---|
| `products` | Товары: id, url_hash (MD5), url, name, image_url, first_seen, last_check |
| `price_history` | История цен: product_id, price, availability_status, recorded_at |
| `scrape_attempts` | Попытки парсинга: 25+ полей (marketplace, source, status, latency, errors, ...) |
| `blocked_patterns` | Память блокировок: trigger, cooldown_sec, strategy, ... |
| `subscribers` | Подписчики: user_id |

### 3.2 Единый формат данных

**ProductData** (parsers/base.py):
- name, price, availability, url, image_url, raw_snapshot

**ProductSnapshot** (core/models.py):
- marketplace, fetch_status, availability, name, price, image_url

**OzonCardDraft** (card_filler.py):
- offer_id, name, description, category_hint, brand, price, old_price, vat, weight_g, dimensions, images, attributes, keywords, checklist, ai_notes, competitor_summary, selling_points

---

## 4. API

### 4.1 Текущие API
- **Telegram Bot:** 35 команд
- **CLI:** --telegram, --update, --metrics, --blocks, --enrich, --report, --deploy-wb

### 4.2 Планируемый FastAPI
| Endpoint | Метод | Описание |
|---|---|---|
| `/api/tasks` | POST | Создание задачи |
| `/api/tasks/{id}` | GET | Статус задачи |
| `/api/products` | GET | Список товаров |
| `/api/products/{id}/history` | GET | История цен |
| `/api/export/{format}` | GET | Экспорт |
| `/api/health` | GET | Health-метрики |
| `/api/cards/generate` | POST | Генерация карточки |
| `/api/alerts` | GET | Алерты |

---

## 5. Инфраструктура

| Компонент | Текущее | Планируется |
|---|---|---|
| БД | SQLite (aiosqlite) | PostgreSQL (asyncpg) |
| Очередь | Нет | Celery + Redis или ARQ |
| Кэш | Нет | Redis |
| Мониторинг | JSONL logs | Prometheus + Grafana |
| Деплой | Docker Compose (bot + postgres) | Kubernetes |
| CI/CD | GitHub Actions | + staging/production |

---

## 6. Безопасность

| Аспект | Реализация |
|---|---|
| Секреты | .env файлы, never commit |
| Access control | ADMIN_IDS для Telegram |
| SQL injection | SQLAlchemy ORM (параметризованные запросы) |
| URL validation | is_supported_marketplace_url() |
| Rate limiting | Кастомный circuit breaker + adaptive cooldown |
| Playwright | Persistent profile для cookies (вне git) |
| Прокси | Поддержка SOCKS5/HTTP proxy |

---

## 7. Зависимости модулей

```
bot.py ──────────┬── task_intents.py ── task_planner.py ── skill_manifest.py
                 │
                 ├── worker.py ── updater.py ── parsers/router.py ── parsers/*.py
                 │                        │
                 │                        └── resilience.py ── database.py
                 │
                 ├── card_filler.py ── ai_client.py ── card_profiles.py
                 │
                 ├── telegram_*.py ── exporter.py / reporter.py
                 │
                 └── agent.py ── ai_analyzer.py ── ai_client.py
```

---

## 8. Тестовое покрытие

| Область | Тесты |
|---|---|
| Agent loop | test_agent_loop.py |
| Intent/planner | test_task_intents.py, test_task_planner.py |
| Skill manifests | test_skill_manifest.py, test_skill_telemetry.py, test_execution_state.py |
| Cards | test_card_filler.py, test_card_profiles.py, test_card_research.py |
| Parsers | test_parsers.py, test_funpay_parser.py, test_parser_universal.py, test_universal_html_parser.py |
| Exports | test_exports.py, test_telegram_exports.py |
| CLI/worker/DB | test_cli.py, test_worker.py, test_database.py |
| Telegram | test_bot_helpers.py, test_bot_startup.py, test_telegram_*.py |
| Misc | test_config.py, test_generic_scraper.py, test_searcher.py, test_brd_enricher.py, test_batch_enricher.py, test_wb_deals.py |

---

## 9. Позиционирование

> MarketMind AI — это рабочее Python-ядро автоматизации маркетплейсов с генерацией карточек Ozon, парсерами маркетплейсов, экспортом, телеметрией и архитектурой навыков/планировщика.

**Что это НЕ является:**
- Не просто парсер WB/Ozon
- Не просто Telegram-бот
- Не законченный SaaS-продукт
- Не полностью автономная self-healing AI платформа
- Не замена marketplace Seller API

---

## 10. Roadmap (объединённый)

### Фаза 1: Stabilization (Q3 2026)
- Unified adapter interface (ProductSnapshot)
- Тесты всех парсеров
- Structured logging
- Исправление багов парсинга

### Фаза 2: API & Auth (Q4 2026)
- FastAPI каркас
- REST API: задачи, товары, история, экспорты
- JWT-авторизация
- PostgreSQL + Alembic
- Очередь задач (Celery/ARQ)

### Фаза 3: Intelligence (Q1 2027)
- Prometheus метрики
- Browser pool + proxy rotation
- Self-healing selectors (LLM-assisted)
- Seller API валидация для Ozon

### Фаза 4: Scale (Q2 2027)
- Redis cache / distributed locks
- Multi-region deployment
- Dashboard (React/Next.js)
- Marketplace expansions (AliExpress, Kufar, Beru)
- White-label для агентств
- SaaS (мультитенантность, биллинг)

---

## 11. Открытые вопросы

| # | Вопрос | Варианты |
|---|---|---|
| 1 | Очередь задач | Celery + Redis vs ARQ |
| 2 | Dashboard | React + Next.js vs htmx + Jinja2 |
| 3 | SaaS billing | Stripe vs self-hosted |
| 4 | parsers/ vs adapters/ | Объединить или разделить контракты |
| 5 | pyproject.toml | Заменить на актуальный или разделить проекты |
| 6 | Единый roadmap | Объединить docs/ROADMAP.md и SPECIFICATION.md §11 |

---

## 12. Рекомендации

1. **Объединить roadmap:** Создать один актуальный roadmap, переместив в `docs/ROADMAP.md`
2. **Заменить pyproject.toml:** Актуализировать под реальные зависимости проекта
3. **Обновить ARCHITECTURE_NEXT.md:** Отразить текущее состояние (Unified adapter реализован,部分)
4. **Документировать parsers/ vs adapters/:** Явно описать разницу в контрактах
5. **Создать CHANGELOG:** Фиксировать изменения по версиям
6. **Разделить проекты:** Если это два разных продукта — разделить в разные репозитории
