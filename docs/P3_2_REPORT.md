# P3.2 Report — AI Suggestions UI

Дата: 2026-07-14
Проект: `MarketMind-AI-Core-main`

## Цель P3.2

Создать пользовательский интерфейс для работы с AI-рекомендациями: просмотр, фильтрация, approve/reject.

## AI Suggestions UI Architecture

```
AIRecommendationEngine
    ↓
AIRecommendationLayer
    ↓
ApprovalQueue (singleton on app.state)
    ↓
Web UI (suggestions.html)
    ↓
User: Approve / Reject / Edit
```

## Пользовательский сценарий

```
1. Пользователь открывает AI Предложения
   → видит список предложений с фильтрами

2. Пользователь фильтрует
   → Ожидают / Одобрены / Отклонены / Все

3. Пользователь просматривает детали
   → Before/After сравнение, причина, confidence

4. Пользователь принимает решение
   → Approve (принять) / Reject (отклонить с причиной)
```

## Approval Flow

```
AI рекомендует → ApprovalQueue → Пользователь видит → Approve/Reject → Статус обновляется
```

**Важно:** AI НЕ применяет изменения автоматически. Только человек подтверждает.

## Новые страницы

| Страница | URL | Описание |
|---|---|---|
| AI Предложения | `/suggestions` | Список с фильтрами и статистикой |
| Детали | `/suggestions/{id}/detail` | Модальное окно с Before/After |
| API | `/api/suggestions` | JSON список |
| Статистика | `/api/suggestions/stats` | Статистика по статусам |

## API Endpoints

| Метод | Путь | Описание |
|---|---|---|
| GET | `/suggestions` | Страница (HTML) |
| GET | `/suggestions/list?status=` | HTMX фрагмент таблицы |
| GET | `/suggestions/{id}/detail` | HTMX модальное окно |
| GET | `/api/suggestions?status=` | JSON список |
| GET | `/api/suggestions/stats` | JSON статистика |
| POST | `/suggestions/{id}/approve` | Одобрить |
| POST | `/suggestions/{id}/reject` | Отклонить с причиной |

## Фильтры

| Фильтр | Описание |
|---|---|
| Все | Все предложения |
| Ожидают | approved is None |
| Одобрены | approved is True |
| Отклонены | approved is False |

## HTMX Interactions

- Фильтры: `hx-get → #suggestions-table` (замена таблицы)
- Детали: `hx-get → #detail-content` (модальное окно)
- Approve/Reject: `hx-post` с `hx-swap="outerHTML"` (замена строки)

## Изменённые файлы

| Файл | Действие |
|---|---|
| `app/ai_recommendation/approval.py` | Добавлен get_all() |
| `app/web/routes/suggestions.py` | Создан — 8 endpoints |
| `app/web/templates/suggestions.html` | Создан — страница |
| `app/web/templates/suggestions_table.html` | Создан — HTMX фрагмент |
| `app/web/templates/suggestions_row.html` | Создан — строка для swap |
| `app/web/templates/suggestions_detail.html` | Создан — модальное окно |
| `app/web/app.py` | Изменён — добавлен router + ai_queue |
| `app/web/schemas.py` | Изменён — добавлены модели |
| `app/web/templates/base.html` | Изменён — добавлена навигация |
| `tests/test_suggestions_ui.py` | Создан — 5 тестов |

## Тестирование

```
422 passed, 24 warnings, 0 failed
```

- 417 существующих тестов — все проходят
- 5 тестов suggestions UI — все проходят
- 0 regressions

## Готовность к Approval Workflow

AI Suggestions UI готов:
- Просмотр предложений работает
- Фильтрация работает
- Approve/Reject работает через HTMX
- Human approval сохранён (нет auto-apply)
- Архитектура расширяемая

## Субагенты

| Агент | actor_id | Роль |
|---|---|---|
| Architect Agent | `general-90` | Дизайн UI |
| Developer Agent | `general-91` | Реализация (5 новых + 4 изменённых) |
| Test Agent | `general-92` | Верификация |
| Reviewer Agent | `general-93` | Ревью — APPROVE |

## Готовность к следующим этапам

P3.2 завершён. AI Suggestions UI работает. Рекомендуемые следующие шаги:
- P3.3: Product Detail страница с историей цен
- P3.4: Reports generation из UI
- P3.5: Health/Diagnostics страница
