## Parser Agent — next architecture step (адаптация Enterprise ТЗ)

Этот репозиторий уже умеет:
- Telegram-бот (aiogram)
- Ozon (Playwright “ninja”) + WB (API/basket fallback)
- История цен в SQLite через SQLAlchemy async
- Экспорт CSV/Excel + HTML отчёт
- AI-аналитика (опционально)

Ниже — план “как перейти на enterprise-архитектуру” без переписывания с нуля.

### 1) Доменные модели и статусы (СДЕЛАНО частично)
- `app/core/enums.py`: Marketplace / AvailabilityStatus / FetchStatus
- `app/core/errors.py`: типизированные ошибки (blocked/not_found/parse/network)
- `app/core/models.py`: `ProductSnapshot` (Pydantic) — будущий единый формат результата

### 2) Unified adapter interface (следующий шаг)
Цель: каждый маркетплейс возвращает единый `ProductSnapshot`:
- `marketplace`
- `fetch_status` (ok/blocked/not_found/parse_error/timeout/…)
- `availability` (in_stock/out_of_stock/unknown)
- `name/price/image_url`

Миграция без боли:
- сначала добавить функцию-обёртку, которая конвертирует существующие dict/Dataclass в `ProductSnapshot`
- затем постепенно перевести `OzonUpdater` и `WildberriesParser` на возврат `ProductSnapshot`

### 3) Jobs & Attempts (следующий шаг)
Добавить таблицы:
- `scrape_jobs` (id, type, created_by, created_at, status, progress)
- `scrape_attempts` (job_id, product_id/url, fetch_status, http_status, latency_ms, error_class, error_text)

Это даст:
- нормальные отчёты о блокировках/ошибках
- повторные попытки по правилам
- основу для API и веб-панели

### 4) Observability (следующий шаг)
- structured logging: в каждом логе `job_id`, `marketplace`, `url_hash`, `fetch_status`
- метрики (Prometheus): requests_total, blocked_total, parse_error_total, latency_histogram

### 5) Queue + Scheduler (Phase B)
Варианты:
- **Celery + Redis/RabbitMQ** (проще “в прод”)
- **ARQ** (полностью async)

MVP:
- APScheduler внутри процесса бота для авто-обновления раз в N минут
Переход:
- вынести обновление в worker-процесс (очередь задач)

### 6) API (Phase B)
FastAPI:
- запуск задач
- список товаров + история
- экспорт
- алерты

### 7) Масштабирование (Phase C)
- Postgres + Alembic migrations
- Redis cache/locks
- browser pool (playwright contexts) + proxy rotation
- self-healing selectors (LLM-assisted) как отдельный модуль

