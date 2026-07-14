# ARCHITECTURE_CONFLICTS.md — Противоречия и несоответствия в документации

> Дата анализа: 2026-07-12
> Источники: SPECIFICATION.md, README.md, ARCHITECTURE_NEXT.md, docs/ROADMAP.md, SKILLS.md, AGENTS.md

---

## 1. Два разных ROADMAP

### Конфликт
Существует **два** разных roadmap-документа с разными фазами и сроками:

| Документ | Фазы | Временной горизонт |
|---|---|---|
| `docs/ROADMAP.md` | 5 фаз (Ядро → API → Хранилище → Dashboard → SaaS) | Q3 2026 — Q2 2027 |
| `SPECIFICATION.md` §11 | 4 фазы (Stabilization → API & Auth → Intelligence → Scale) | Q3 2026 — Q2 2027 |

### Различия

**docs/ROADMAP.md:**
- Фаза 1: Ядро (Unified adapter, тесты, багфиксы)
- Фаза 2: API / Авторизация (FastAPI, JWT, Rate limiting)
- Фаза 3: Хранилище / Очереди (Postgres, Redis, Celery/ARQ, Browser pool)
- Фаза 4: Dashboard / UI (React/Next.js, RBAC)
- Фаза 5: SaaS (Мультитенантность, биллинг, white-label)

**SPECIFICATION.md §11:**
- Phase 1: Stabilization (ProductSnapshot, scrape_jobs, structured logging)
- Phase 2: API & Auth (FastAPI, JWT, Postgres, Celery, Web panel)
- Phase 3: Intelligence (Prometheus, Browser pool, Self-healing, Seller API)
- Phase 4: Scale (Redis, Multi-region, Dashboard, AliExpress/Kufar/Beru, White-label)

### Статус: ТРЕБУЕТ РЕШЕНИЯ
Нужно объединить в один актуальный roadmap или явно указать, какой документ является основным.

---

## 2. Несоответствие в依赖ностях

### Конфликт
`requirements.txt` и `SPECIFICATION.md` §10.2 содержат разные версии зависимостей:

| Пакет | requirements.txt | SPECIFICATION.md |
|---|---|---|
| aiogram | (не указан) | 3.4.1 |
| sqlalchemy | (не указан) | 2.0.28 |
| playwright | (не указан) | 1.42.0 |

При этом `pyproject.toml` содержит совсем другой набор зависимостей (fastapi, uvicorn, alembic, redis, celery, openai, cryptography, python-jose, passlib) — это из другого проекта (MarketMind AI Marketplace Manager).

### Статус: КРИТИЧНО
`pyproject.toml` содержит зависимости проекта "MarketMind AI Marketplace Manager" (SaaS-платформа), а не "MarketMind AI Core" (Telegram-бот). Это два разных проекта в одном репозитории.

---

## 3. pyproject.toml не принадлежит этому проекту

### Конфликт
Файл `pyproject.toml` описывает проект "marketmind-ai" версии 0.1.0 с зависимостями:
- FastAPI, uvicorn, pydantic
- SQLAlchemy async, asyncpg, alembic
- Redis, Celery
- httpx, tenacity
- python-jose, passlib
- aiogram, openai
- streamlit

Но реальный проект использует:
- aiogram (Telegram bot)
- aiohttp (HTTP client)
- playwright (Browser automation)
- beautifulsoup4, lxml (HTML parsing)
- openpyxl (Excel export)
- anthropic (Claude API)

### Статус: КРИТИЧНО
Нужно решить: это монорепозиторий с двумя проектами, или `pyproject.toml` нужно заменить на актуальный.

---

## 4. Дублирование архитектурных документов

### Конфликт
Существует несколько документов, описывающих архитектуру:

| Документ | Объём | Фокус |
|---|---|---|
| `ARCHITECTURE_NEXT.md` | 64 строки | План перехода на enterprise |
| `docs/ARCHITECTURE_OVERVIEW.md` | 135 строк | Текущая архитектура |
| `SPECIFICATION.md` §2 | ~150 строк | Полное ТЗ архитектуры |
| `SKILLS.md` | 290 строк | Карта навыков |
| `docs/PROJECT_MAP.md` | 119 строк | Навигационная карта |

### Проблема
- `ARCHITECTURE_NEXT.md` описывает "следующий шаг" (Unified adapter, Jobs & Attempts), но не обновлён после реализации этих шагов.
- `docs/ARCHITECTURE_OVERVIEW.md` описывает текущее состояние, но не упоминает universal_parsing_core, wb_deals, batch_enricher.
- `SPECIFICATION.md`是最全面的, но содержит информацию о будущем (FastAPI, Postgres) как о существующем.

### Статус: ТРЕБУЕТ РЕШЕНИЯ
Нужно определить единственный источник правды для архитектуры.

---

## 5. Несоответствие в описании парсеров

### Конфликт
В `SPECIFICATION.md` §5.1 описаны парсеры:
- Ozon: Playwright
- Wildberries: API + basket candidates
- Yandex Market: HTML/JSON-LD
- Universal: Page classification

В `SKILLS.md` добавлены:
- FunPay Parser
- WB Deals
- Generic Scraper
- Universal Parsing Core

В `docs/PROJECT_MAP.md` добавлены:
- `app/adapters/ozon.py` и `app/adapters/wb.py` (адаптеры API, не парсеры)

### Проблема
Непонятно, чем `parsers/wildberries.py` отличается от `adapters/wb.py`. Это два разных модуля с разными контрактами.

### Статус: ТРЕБУЕТ РЕШЕНИЯ
Нужно документировать различие между парсерами и адаптерами.

---

## 6. Статус SaaS

### Конфликт
- `README.md`: "Not a finished SaaS product"
- `ARCHITECTURE_NEXT.md`: описывает план SaaS
- `docs/ROADMAP.md`: Фаза 5 = SaaS
- `SPECIFICATION.md`: Phase 4 = Scale (включая white-label)

Но при этом:
- В корне проекта нет `marketmind/` директории (она была в предыдущем проекте)
- Нет Streamlit UI
- Нет FastAPI
- Нет PostgreSQL миграций

### Статус: ЯСНО
SaaS — это план, не текущее состояние. Все документы согласны в этом.

---

## 7. Тестирование

### Конфликт
- `CONTRIBUTING.md`: "pytest tests/ -v" и "unittest" упоминаются как варианты
- `SPECIFICATION.md`: "unittest (текущий), возможен переход на pytest"
- `README.md`: "python3 -m pytest tests/ -v"
- `requirements.txt`: нет pytest в зависимостях

### Проблема
Непонятно, какой фреймворк тестирования является основным. В `tests/` используются pytest-декораторы (`@pytest.mark.asyncio`), значит pytest уже используется.

### Статус: МИОР
Нужно обновить SPECIFICATION.md и CONTRIBUTING.md, указав pytest как основной.

---

## 8. CLI команды

### Конфликт
В `SPECIFICATION.md` §4.1 описаны CLI команды с префиксом `py -3.11`:
```
py -3.11 -m app.main --telegram
py -3.11 -m app.main --update
```

В `README.md`:
```
python3 -m app.main --telegram
python3 -m app.main --update
```

### Статус: МИОР
`py -3.11` — это Windows-специфичный вызов. Нужно унифицировать.

---

## 9. Конфликт проектов в корне

### Конфликт
В корне проекта `MarketMind-AI-Core-main` находятся файлы из проекта "MarketMind AI Marketplace Manager":
- `pyproject.toml` (с fastapi, streamlit, alembic)
- `ARCHITECTURE.md` (в корне, но нет в ls — видимо был удалён)
- `ROADMAP.md` (в корне, но нет в ls — видимо был удалён)

При этом основной проект — это Telegram-бот с парсерами.

### Статус: КРИТИЧНО
Нужно определить: это один проект или два? Если два — нужно разделить.

---

## 10. Отсутствие docs/architecture/ в основном проекте

### Конфликт
Папка `docs/architecture/` не существовала до начала этой сессии. Все архитектурные документы разбросаны по корню и `docs/`.

### Статус: ИСПРАВЛЯЕТСЯ
Создаётся в рамках этой задачи.

---

## Резюме противоречий

| # | Противоречие | Критичность | Требует решения |
|---|---|---|---|
| 1 | Два разных ROADMAP | Высокая | Да |
| 2 | pyproject.toml из другого проекта | Критическая | Да |
| 3 | Дублирование архитектурных документов | Средняя | Да |
| 4 | parsers/ vs adapters/ — непонятная разница | Средняя | Да |
| 5 | Два проекта в одном репозитории | Критическая | Да |
| 6 | CLI команды Windows vs Linux | Низкая | Да |
| 7 | pytest vs unittest в документации | Низкая | Да |
| 8 | ARCHITECTURE_NEXT.md не обновлён | Средняя | Да |
