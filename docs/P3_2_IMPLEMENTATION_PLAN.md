# P3.2 — AI Suggestions UI: Техническое задание

Дата: 2026-07-14
Статус: РЕАЛИЗОВАНО (APPROVE от Reviewer Agent)

## 1. Цель P3.2

Создать пользовательский интерфейс для работы с AI-рекомендациями: просмотр предложений, фильтрация по статусу, approve/reject через HTMX.

## 2. Пользовательский сценарий

```
1. Пользователь открывает "AI Предложения" в навигации
   → видит список всех предложений с фильтрами

2. Пользователь фильтрует по статусу
   → Ожидают / Одобрены / Отклонены / Все

3. Пользователь просматривает детали предложения
   → Before/After сравнение, причина, confidence

4. Пользователь принимает решение
   → Approve (принять) / Reject (отклонить с причиной)
```

**Важно:** AI НЕ применяет изменения автоматически. Только человек подтверждает.

## 3. Архитектура страницы

```
AIRecommendationEngine
    ↓
AIRecommendationLayer
    ↓
ApprovalQueue (singleton на app.state)
    ↓
Web UI (suggestions.html)
    ↓
User: Approve / Reject
```

### ApprovalQueue

- Хранится как `app.state.ai_queue` (singleton)
- Инициализируется в lifespan FastAPI
- Пустой при старте
- Заполняется через `AIRecommendationLayer.post_process()` или напрямую из UI

## 4. Backend Routes

| Метод | Путь | Описание |
|---|---|---|
| GET | `/suggestions` | Страница (HTML) |
| GET | `/suggestions/list?status=` | HTMX фрагмент таблицы |
| GET | `/suggestions/{id}/detail` | HTMX модальное окно |
| GET | `/api/suggestions?status=` | JSON список |
| GET | `/api/suggestions/stats` | JSON статистика |
| POST | `/suggestions/{id}/approve` | Одобрить |
| POST | `/suggestions/{id}/reject` | Отклонить с причиной |

### Query Parameters

- `status`: `all` | `pending` | `approved` | `rejected`

### HTMX Interactions

- Фильтры: `hx-get → #suggestions-table` (замена таблицы)
- Детали: `hx-get → #detail-content` (модальное окно)
- Approve/Reject: `hx-post` с `hx-swap="outerHTML"` (замена строки)

## 5. UI Templates

| Файл | Назначение |
|---|---|
| `suggestions.html` | Основная страница: stats cards + фильтры + таблица + модалка |
| `suggestions_table.html` | HTMX фрагмент таблицы |
| `suggestions_row.html` | Строка для замены через HTMX |
| `suggestions_detail.html` | Модальное окно с деталями |

### suggestions.html

- Stats cards: Всего / Ожидают / Одобрено / Отклонено
- Filter tabs: Все / Ожидают / Одобрено / Отклонено
- Таблица с колонками: Товар, Проблема, Предложение, Уверенность, Статус, Действия
- Модальное окно (скрытое по умолчанию)

### suggestions_detail.html

- Товар (название + ID)
- Проблема (поле + тип)
- Было → Новое (сравнение)
- Причина
- Confidence bar (цветовой)
- Кнопки Approve / Reject

## 6. Модели данных

### SuggestionItem (Pydantic)

```python
class SuggestionItem(BaseModel):
    approval_id: str
    product_id: str
    product_name: str
    field: str
    suggestion_type: str
    before: str
    after: str
    reason: str
    confidence: float
    status: str  # pending | approved | rejected
```

### SuggestionStats (Pydantic)

```python
class SuggestionStats(BaseModel):
    total: int
    pending: int
    approved: int
    rejected: int
```

### RejectRequest (Pydantic)

```python
class RejectRequest(BaseModel):
    reason: str = ""
```

## 7. Изменённые файлы

| Файл | Действие |
|---|---|
| `app/ai_recommendation/approval.py` | Добавлен `get_all()` |
| `app/web/routes/suggestions.py` | Создан — 8 endpoints |
| `app/web/templates/suggestions.html` | Создан |
| `app/web/templates/suggestions_table.html` | Создан |
| `app/web/templates/suggestions_row.html` | Создан |
| `app/web/templates/suggestions_detail.html` | Создан |
| `app/web/app.py` | Добавлен router + ai_queue |
| `app/web/schemas.py` | Добавлены модели |
| `app/web/templates/base.html` | Добавлена навигация |

## 8. Тесты

| Тест | Покрытие |
|---|---|
| `test_suggestions_page` | Страница открывается, stats отображаются |
| `test_suggestions_api_empty` | API возвращает пустой список |
| `test_approve_suggestion` | Approve меняет статус |
| `test_reject_suggestion` | Reject меняет статус с причиной |
| `test_filter_by_status` | Фильтрация по pending/approved/rejected |

## 9. Риски

| Риск | Митигация |
|---|---|
| ApprovalQueue in-memory (теряется при перезапуске) | Принято для MVP; в будущем — SQLite таблица |
| HTMX зависимости от CDN | CDN доступен; fallback — plain HTML |
| Конкурентный доступ к queue | FastAPI single-process; нет проблем |

## 10. Критерии готовности

- [x] Страница `/suggestions` открывается
- [x] Stats cards отображают корректные данные
- [x] Фильтры работают через HTMX
- [x] Approve меняет статус на "approved"
- [x] Reject меняет статус на "rejected" с причиной
- [x] Модальное окно показывает Before/After
- [x] UI на русском языке
- [x] Все тесты проходят (422/422)
- [x] Reviewer Agent: APPROVE
