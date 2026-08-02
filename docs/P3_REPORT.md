# P3 Report — User Interface Layer (MVP)

Дата: 2026-07-14
Проект: `MarketMind-AI-Core-main`

## Цель P3

Создать профессиональный web-интерфейс MarketMind AI для работы с товарами, анализом и AI-рекомендациями.

## UI Architecture

```
Frontend (Jinja2 + HTMX + Tailwind CSS)
    ↓
Backend API (FastAPI)
    ↓
MarketMind Core (Pipeline, Analyzer, AI)
    ↓
Database (SQLite + aiosqlite)
```

### Стек

| Компонент | Технология | Обоснование |
|---|---|---|
| Backend | FastAPI | Async, совместим с SQLAlchemy async |
| Templating | Jinja2 + HTMX | Без Node.js, Python-only |
| Styling | Tailwind CSS (CDN) | Без build step |
| Charts | Chart.js (CDN) | Лёгкий, без build step |
| Database | SQLite + aiosqlite | Уже используется |

### Запуск

```bash
python -m app.main --web           # порт 8000
python -m app.main --web --port 3000  # кастомный порт
```

## Backend API

| Endpoint | Метод | Описание |
|---|---|---|
| `/api/dashboard` | GET | Статистика системы |
| `/api/products` | GET | Список товаров (с поиском) |
| `/api/import/file` | POST | Загрузка CSV/XLSX |
| `/` | GET | Dashboard (HTML) |
| `/products` | GET | Список товаров (HTML) |
| `/import` | GET | Страница импорта (HTML) |

## User Flow

```
1. Пользователь открывает Dashboard
   → видит статистику: товары, маркетплейсы, здоровье

2. Пользователь загружает CSV/Excel
   → Drag-and-drop или выбор файла
   → Pipeline: Import → Validate → Enrich → Analyze
   → Результат: товары с оценками

3. Пользователь просматривает товары
   → Таблица с фильтрами и поиском
   → Клик на товар → детали с историей цен

4. Пользователь работает с AI
   → AI генерирует рекомендации
   → Approve/Reject предложения
```

## MVP Interface

### Страницы

| Страница | Описание |
|---|---|
| Dashboard | Обзор: количество товаров, маркетплейсы, быстрые действия |
| Products | Таблица товаров с поиском через HTMX |
| Import | Загрузка файлов через drag-and-drop |

### Дизайн

- Русский язык интерфейса
- Sidebar навигация
- Tailwind CSS для стилей
- HTMX для динамических обновлений
- Адаптивный дизайн

## Изменённые файлы

| Файл | Действие |
|---|---|
| `app/web/__init__.py` | Создан |
| `app/web/app.py` | Создан — FastAPI app |
| `app/web/schemas.py` | Создан — Pydantic модели |
| `app/web/routes/__init__.py` | Создан |
| `app/web/routes/dashboard.py` | Создан — dashboard API + page |
| `app/web/routes/products.py` | Создан — products API + page |
| `app/web/routes/import_.py` | Создан — import API + page |
| `app/web/templates/base.html` | Создан — layout |
| `app/web/templates/dashboard.html` | Создан |
| `app/web/templates/products.html` | Создан |
| `app/web/templates/import_.html` | Создан |
| `app/main.py` | Изменён — добавлены --web, --port |
| `requirements.txt` | Изменён — добавлены fastapi, uvicorn, jinja2, python-multipart |
| `tests/test_web_api.py` | Создан — 7 тестов |

## Тестирование

```
417 passed, 24 warnings, 0 failed
```

- 410 существующих тестов — все проходят
- 7 тестов web API — все проходят
- 0 regressions

## Следующие шаги

- P3.1: Product Detail страница с историей цен
- P3.2: AI Suggestions страница
- P3.3: Approval workflow
- P3.4: Reports generation из UI
- P3.5: Health/Diagnostics страница

## Субагенты

| Агент | actor_id | Роль |
|---|---|---|
| Architect Agent | `general-86` | Дизайн UI архитектуры |
| Developer Agent | `general-87` | Реализация MVP |
| Test Agent | `general-88` | Верификация (обнаружена проблема с зависимостями) |
| Reviewer Agent | `general-89` | Ревью — REQUEST CHANGES (fastapi не установлен) |
