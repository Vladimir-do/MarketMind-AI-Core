# Codex Current State Audit

Дата: 2026-07-14
Проект: `MarketMind-AI-Core-main`

## 1. Что сейчас работает

### Core pipeline

Текущая архитектурная цепочка подтверждена кодом и тестами:

```text
Import Layer
-> UnifiedProduct
-> Validation
-> Enrichment
-> Product Intelligence
-> AI Recommendation Layer
-> AI Providers
-> Web UI
```

Рабочие части:

- CSV/XLSX import layer.
- `UnifiedProduct`.
- Product validation.
- Ozon enrichment strategy.
- Product analyzer / intelligence rules.
- AI recommendation engine.
- AI provider abstraction.
- Approval queue для human-in-the-loop workflow.
- Web UI на FastAPI + Jinja2 + HTMX + Tailwind.

### Web UI

Текущие страницы:

- Dashboard: `/`
- Products: `/products`
- Import: `/import`
- AI Suggestions: `/suggestions`

Текущие API:

- `GET /api/dashboard`
- `GET /api/products`
- `POST /api/import/file`
- `GET /api/suggestions`
- `GET /api/suggestions/{id}`
- `GET /api/suggestions/stats`

AI Suggestions UI уже поддерживает:

- список предложений;
- detail view;
- approve/reject actions через HTMX;
- status: `pending`, `approved`, `rejected`;
- отображение current value, suggested value, reason, confidence.

Важно: UI не вызывает `ApprovalQueue.apply_approved()`, поэтому данные товара не меняются автоматически.

### База данных

Проверка БД выполнена без вывода содержимого строк.

Фактическое состояние:

```text
database_url_type = sqlite
database_exists = true
tables = alembic_version, blocked_patterns, price_history, products, scrape_attempts, subscribers
alembic_version_count = 1
blocked_patterns_count = 12
price_history_count = 0
products_count = 0
scrape_attempts_count = 11
subscribers_count = 0
```

`Database.init()` выполняется успешно.

### Тесты

Focused Web/AI:

```text
48 passed
```

Full test suite:

```text
425 passed, 24 warnings, 14 subtests passed
```

Предупреждения:

- `bs4/lxml` deprecation warning про `strip_cdata`.

## 2. Что исправлено

По текущим отчётам и коду уже исправлено:

- восстановлено рабочее Python-окружение;
- исправлена совместимость `aiogram 3.4.1` и `aiohttp 3.9.5`;
- стабилизирована инициализация SQLite/aiosqlite;
- добавлен Web UI MVP;
- добавлен AI Suggestions UI;
- добавлены canonical endpoints для suggestion detail;
- approve/reject отделены от автоматического применения данных;
- покрытие P3.2 усилено тестами.

## 3. Какие проблемы остались

### Нет git-репозитория

Команда:

```text
git rev-parse --show-toplevel
```

возвращает:

```text
fatal: not a git repository
```

Это опасно для коммерческой разработки: нет нормальной истории изменений, diff, rollback и контрольных точек.

### Ruff отсутствует в `.venv`

Команда:

```text
.venv/bin/python -m ruff --version
```

возвращает:

```text
No module named ruff
```

Тесты проходят, но lint-проверка сейчас не воспроизводится в текущем окружении.

### ApprovalQueue in-memory

AI Suggestions хранятся в `app.state.ai_queue`.

Риски:

- очередь теряется после рестарта web-приложения;
- нет истории решений;
- нет аудита approve/reject;
- нет привязки к пользователю или организации.

### Нет multi-user / auth слоя для Web UI

Сейчас Web UI не имеет:

- login;
- пользователей;
- ролей;
- разграничения доступа;
- изоляции данных.

Для локального MVP это допустимо, но для коммерческого продукта это blocker.

### CORS открыт полностью

В `app/web/app.py` используется:

```text
allow_origins=["*"]
allow_credentials=True
allow_methods=["*"]
allow_headers=["*"]
```

Для локального MVP это удобно, но для production небезопасно.

### Product name в AI Suggestions не связан с БД

`product_name` берётся из `suggestion.metadata["product_name"]`, затем fallback на `product_id`.

Это работает для UI, но не является устойчивой моделью данных.

### База сейчас пустая по товарам

`products_count = 0`.

Это значит, что Web UI технически работает, но на текущей локальной базе нет реальных товаров для пользовательской демонстрации.

## 4. Что опасно менять

Без отдельного плана и подтверждения опасно менять:

- `requirements.txt`: проект чувствителен к связке `aiogram` / `aiohttp`.
- `app/database.py`: storage уже стабилизирован, изменения могут вернуть зависания или сломать тесты.
- `app/pipeline.py`: общий контракт используется import/enrichment/intelligence слоями.
- `app/ai_recommendation/approval.py`: сейчас он гарантирует human-in-the-loop; изменение может случайно включить автоприменение.
- `app/web/app.py`: lifecycle создаёт DB и AI queue; изменение затронет все web tests.
- `app/web/routes/import_.py`: импорт связан с pipeline и DB/UI поведением.
- `app/bot.py` и Telegram runtime: большой blast radius, много существующих команд.

## 5. Что рекомендуется делать дальше

### Рекомендуемый следующий этап: P3.3 persistent approval storage

Цель:

```text
AI Suggestions должны переживать restart приложения и иметь историю решений.
```

Предлагаемый безопасный подход:

1. Сначала спроектировать storage-модель без изменения кода.
2. Решить, где хранить suggestions:
   - SQLite table;
   - JSONL для MVP;
   - отдельный repository layer.
3. Добавить audit fields:
   - created_at;
   - decided_at;
   - status;
   - decision_reason;
   - product_id;
   - field;
   - before;
   - after;
   - confidence.
4. Сохранить правило: approve не применяет данные автоматически.
5. Покрыть тестами restart-like сценарий.

### Альтернативный следующий этап: Reports UI

Если нужен быстрый пользовательский эффект без изменения БД, безопаснее сделать:

- страницу отчётов;
- просмотр existing HTML reports;
- download links;
- status пустого состояния.

Это меньше риск, чем менять storage.

### Инфраструктурный шаг

Перед следующими кодовыми изменениями желательно:

- сделать каталог git-репозиторием или перенести проект в репозиторий;
- добавить `ruff` в dev-зависимости только после отдельного одобрения;
- зафиксировать текущую зелёную точку: `425 passed`.

## Итог

Текущее состояние проекта стабильное для локального MVP:

```text
Full tests: 425 passed
Web/AI tests: 48 passed
DB init: OK
AI Suggestions UI: готов к P3.2-level use
```

Для коммерческого продукта пока не хватает:

- persistent approval storage;
- auth/multi-user модели;
- production CORS/security настройки;
- воспроизводимого lint/dev tooling;
- git-контрольной точки.

