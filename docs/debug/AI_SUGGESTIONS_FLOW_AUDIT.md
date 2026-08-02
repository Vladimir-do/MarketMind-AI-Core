# AI Suggestions Flow Audit

Дата: 2026-07-21
Проект: `MarketMind-AI-Core-main`

## Scope

Аудит сквозного сценария:

```text
Кнопка "В очередь"
→ frontend-обработчик
→ HTTP/HTMX request
→ backend endpoint
→ create job record
→ queue / worker
→ AI / LLM service
→ save result
→ API for AI suggestions
→ suggestions tab
→ suggestion card
→ approve / reject
```

## Фактическая цепочка

### 1. Кнопка "В очередь" на карточке проекта

- Файл: `app/web/templates/project_product_detail.html`
- Элемент: `button`
- Frontend-механизм: HTMX
- Атрибуты:
  - `hx-post="/api/projects/{{ project.project_id }}/products/{{ card.product_id }}/seo-suggestions"`
  - `hx-vals='{"action": "{{ recommendation.action }}"}'`
  - `hx-target="closest div"`
  - `hx-swap="outerHTML"`
- Входные данные:
  - `project.project_id`
  - `card.product_id`
  - `recommendation.action`
- Выход:
  - HTMX request на backend
  - после успешного ответа блок рекомендации заменяется HTML-ответом
- Возможный сбой:
  - HTMX request не отправлен
  - неверный `project_id` / `product_id`
  - backend вернул 4xx/5xx
  - ответ не HTML для HTMX

### 2. Backend endpoint для SEO-очереди

- Файл: `app/web/routes/projects.py`
- Функция: `api_queue_project_seo_suggestions`
- Endpoint: `POST /api/projects/{project_id}/products/{product_id}/seo-suggestions`
- HTTP-метод: `POST`
- Входные данные:
  - `project_id: str`
  - `product_id: int`
  - `action: str` из `request.form()`
  - `Request`
- Что делает:
  1. создаёт запись задачи в `job_records`
  2. читает `action` из кнопки и кладёт его в payload задачи
  3. строит prompt на основе SEO-audit и выбранной рекомендации
  4. вызывает configured AI provider через `app.ai_client.ask_ai`
  5. парсит JSON-ответ в `AISuggestion`
  6. кладёт их в `approval_records` через `DatabaseApprovalQueue.add(...)`
  7. завершает job через `finish_job(...)`
- Выход:
  - HTMX: HTML-фрагмент с текстом о постановке в согласование
  - JSON: `success`, `task_id`, `status`, `model_used`, `queued`, `items`
- Таблицы БД:
  - `job_records`
  - `approval_records`
- Статусы:
  - job: `queued` → `succeeded`
  - approval: `pending`
- Возможные места сбоя:
  - нет `client_projects` / `project_products`
  - `action` не прочитан из формы
  - `ask_ai(...)` возвращает timeout / provider error
  - `AIRecommendationEngine._parse_suggestions(...)` не может разобрать JSON
  - `DatabaseApprovalQueue.add(...)` не коммитит
  - `finish_job(...)` не вызывается

### 3. Формирование SEO-рекомендаций

- Файл: `app/effective_card/service.py`
- Метод: `_finding_to_suggestion(...)` и `seo_suggestions(...)`
- Назначение:
  - строит предложения из SEO findings
  - добавляет metadata:
    - `source: "seo_audit"`
    - `project_id`
    - `project_product_id`
    - `product_name`
- Вход:
  - effective card товара проекта
- Выход:
  - список `AISuggestion`
- Таблицы БД:
  - напрямую не пишет
- Возможный сбой:
  - найденные поля отсутствуют
  - карточка проекта не найдена
  - `_finding_to_suggestion(...)` может отфильтровать рекомендации без safe replacement

### 4. Сохранение предложений

- Файл: `app/ai_recommendation/db_approval.py`
- Класс: `DatabaseApprovalQueue`
- Метод: `add(...)`
- Таблица: `approval_records`
- Что пишет:
  - `approval_id`
  - `product_id`
  - `field`
  - `suggestion_type`
  - `before_value`
  - `after_value`
  - `reason`
  - `confidence`
  - `source_finding`
  - `metadata_json`
  - `status="pending"`
- Выход:
  - список `PendingApproval`
- Возможный сбой:
  - commit не выполнен
  - `product_id` или metadata не совпадают по типу

### 5. Завершение job

- Файл: `app/database.py`
- Методы:
  - `create_job(...)`
  - `start_job(...)`
  - `finish_job(...)`
  - `fail_job(...)`
  - `get_recent_jobs(...)`
- Таблица: `job_records`
- Статусы:
  - `queued`
  - `running`
  - `succeeded`
  - `failed`
- Поля:
  - `job_id`
  - `job_type`
  - `status`
  - `payload_json`
  - `result_json`
  - `error_class`
  - `error_text`
  - `progress`
- Возможный сбой:
  - job создан, но `finish_job(...)` не вызван
  - job создан в другой БД / другом app.state

### 6. Отображение вкладки "Предложения AI"

- Файл: `app/web/routes/suggestions.py`
- Функция: `suggestions_page`
- Endpoint: `GET /suggestions`
- HTTP-метод: `GET`
- Вход:
  - `Request`
- Что делает:
  - читает pending/approved/rejected через `DatabaseApprovalQueue.get_all()`
  - читает последние job records через `_recent_jobs(...)`
  - передаёт `stats`, `items`, `jobs` в шаблон
- Таблицы БД:
  - `approval_records`
  - `job_records`
- Возможный сбой:
  - `app.state.db` отсутствует
  - `app.state.ai_queue` отсутствует
  - фильтрация скрывает текущий статус

### 7. Рендер вкладки

- Файл: `app/web/templates/suggestions.html`
- Что видно:
  - блок статистики
  - блок `AI-задачи`
  - таблица предложений
- Если предложений нет:
  - `suggestions_table.html` показывает `Нет предложений`
  - jobs block показывает `Задач пока нет`

### 8. Кнопки согласования

- Файл: `app/web/templates/suggestions_table.html`
- Кнопки:
  - `hx-post="/suggestions/{{ item.approval_id }}/approve"`
  - `hx-post="/suggestions/{{ item.approval_id }}/reject"`
- Backend:
  - `POST /suggestions/{approval_id}/approve`
  - `POST /suggestions/{approval_id}/reject`
- Таблица:
  - `approval_records`
- Статусы:
  - `pending`
  - `approved`
  - `rejected`
- Возможный сбой:
  - `approval_id` не найден
  - apply path не может создать draft / version

## Отдельная AI-ветка проекта

Для общего AI-генератора карточек существует отдельный поток:

```text
POST /api/products/{product_id}/ai-suggestions
→ process_product_ai_suggestion_job(...)
→ provider / LLM
→ approval_records
→ GET /api/ai-suggestions
```

Он живёт в:

- `app/web/routes/product_detail.py`
- `app/ai_recommendation/job_queue.py`
- `app/ai_recommendation/engine.py`

Это отдельная ветка от SEO-аудита, но обе используют одну approval-модель и один экран `Предложения AI`.

## Реальные проверки

### Контролируемый success run

Проверен реальный POST на действующем проекте:

- `project_id`: `project_55badff214f2`
- `product_id`: `58`
- `action`: `Расширить описание: назначение, сценарии, преимущества, характеристики.`
- endpoint: `POST /api/projects/project_55badff214f2/products/58/seo-suggestions`

Результат:

- `task_id`: `14162ff9e115405ab9fb86c2d1c4057e`
- `job_records.status`: `succeeded`
- `model_used`: `gemini-2.0-flash`
- `approval_ids`: `daaec7e525e1`, `1a496feec018`
- `approval_records.status`: `pending`

### Реальный provider error

Без подмены ответа AI исторически наблюдался симптом:

- `AI error: TimeoutError`

Позднейшая изолированная проверка показала, что реальный Gemini доступен и отвечает `HTTP 429 quota exceeded`, поэтому `TimeoutError` не является стабильной текущей причиной.

Job после этого переходит в:

- `job_records.status = failed`
- `job_records.error_text = AI error: Gemini API недоступен: ... (HTTP 429)` или исторически `AI error: TimeoutError`

> **Замечание**: quota для текущего ключа имеет `limit: 0`. Реальный успешный HTTP 200 от Gemini в этой среде пока не получен, поэтому Gemini нельзя считать полностью проверенным в успешном режиме. Контролируемый success run выше использовал подмену внешнего AI response.
