# AI Suggestions Fix Report

Дата: 2026-07-21
Проект: `MarketMind-AI-Core-main`

## 1. Первопричина

Сбой был в проектной SEO-цепочке:

- существующая кнопка `В очередь` отправляла `action`, но backend его игнорировал;
- POST путь опирался на детерминированную SEO-ветку и мог завершаться с `queued=0`;
- первый вариант AI-job ещё и падал на неправильном обращении к `SEORecommendation.description`, хотя в реальной модели есть только `reason`;
- ранее наблюдался симптом `AI error: TimeoutError`, а последующая изолированная проверка показала, что Gemini отвечает `HTTP 429 quota exceeded`; ошибка раньше не показывалась пользователю понятным образом.

Из-за этого пользователь видел либо пустую вкладку, либо “тишину” без task state и без понятного сообщения о провале AI.

## 2. Точка разрыва

Конкретный разрыв был в цепочке:

- `app/web/templates/project_product_detail.html`
  - существующий HTMX button `В очередь`
- `app/web/routes/projects.py`
  - `api_queue_project_seo_suggestions(...)`
- `app/ai_recommendation/job_queue.py`
  - `process_project_seo_suggestion_job(...)`
- `app/ai_client.py`
  - `_ask_gemini(...)`

До исправления backend не использовал выбранную пользователем recommendation action. После этого job мог не создать approvals, а затем AI provider в этой среде таймаутился без нормального текста ошибки.

## 3. Дополнительные найденные проблемы

1. `suggestions_page` зависел от `request.app.state.db`.
   - Исправлен fallback: если `db` отсутствует, jobs block рендерится пустым, но страница не падает.

2. `app.ai_client` возвращал пустой текст при некоторых исключениях.
   - Теперь он возвращает понятную ошибку Gemini по HTTP-статусу, а не сводит любой provider failure к `TimeoutError`.

3. `_recent_jobs(...)` раньше не показывал SEO job state вообще.
   - Теперь вкладка `Предложения AI` показывает job lifecycle.

4. В проектной SEO-ветке был скрытый mismatch между audit model и prompt builder.
   - `SEORecommendation` не имеет `description`; нужно использовать `reason`.

## 4. Исправленные файлы

### `app/web/routes/projects.py`

Что изменено:

- `POST /api/projects/{project_id}/products/{product_id}/seo-suggestions` теперь читает `action` из формы HTMX button;
- job payload теперь сохраняет `action`;
- POST запускает project SEO AI job;
- при успехе возвращает `task_id`, `status`, `model_used`, `queued`, `items`;
- при провале возвращает понятный HTML/JSON с ошибкой, а job остаётся `failed`.

Зачем:

- чтобы выбранная пользователем рекомендация не терялась;
- чтобы POST не завершался “тихо”;
- чтобы результаты попадали в `approval_records` и в вкладку `Предложения AI`.

### `app/ai_recommendation/job_queue.py`

Что изменено:

- добавлен `process_project_seo_suggestion_job(...)`;
- prompt строится из SEO-audit и `action` из кнопки;
- используется реальный configured AI provider через `app.ai_client.ask_ai`;
- JSON-ответ парсится в `AISuggestion`;
- результат сохраняется в `approval_records`;
- job сохраняется в `job_records` как `succeeded` или `failed`;
- логирование включает `task_id`, `project_id`, `product_id`, `model_used`.

Зачем:

- чтобы SEO-кнопка запускала реальный AI flow;
- чтобы в случае provider error пользователь видел не пустой экран, а `failed` job.

### `app/ai_client.py`

Что изменено:

- ошибки Claude/Grok/Gemini теперь возвращают текст с типом исключения;
- Gemini HTTP 429 теперь классифицируется как quota/rate-limit error, а не как timeout;
- настоящие timeout-ошибки отдельно сохраняют timeout-класс.

Зачем:

- чтобы provider failure был виден в job и в UI.

### `app/web/routes/suggestions.py`

Что изменено:

- добавлен `_recent_jobs(...)`;
- страница `Предложения AI` теперь показывает `AI-задачи`;
- добавлены JSON API для jobs/stats;
- fallback на отсутствие `db` не роняет страницу.

### `app/web/templates/suggestions.html`

Что изменено:

- добавлен блок `AI-задачи` над таблицей approvals.

### `tests/test_client_projects.py`

Что изменено:

- добавлен сквозной тест `test_seo_suggestions_page_shows_jobs_and_approvals`;
- для suite AI-call подменяется только в тестах, чтобы не ходить в интернет.

## 5. Проверка базы данных

Жизненный цикл job:

1. `job_records`
   - создаётся запись со статусом `queued`;
   - затем `succeeded` или `failed`.

2. `approval_records`
   - создаются записи со статусом `pending`;
   - после approve/reject меняют статус на `approved` / `rejected`.

Проверенный success run:

- `task_id = 14162ff9e115405ab9fb86c2d1c4057e`
- `project_id = project_55badff214f2`
- `product_id = 58`
- `model_used = gemini-2.0-flash`
- `job_records.status = succeeded`
- `approval_ids = daaec7e525e1, 1a496feec018`
- `approval_records.status = pending`

Проверенный provider error run:

- `task_id = fb32c91b9cbf4cc7a0c9c9369a23c470`
- `job_records.status = failed`
- `job_records.error_text = AI error: Gemini API недоступен: ... (HTTP 429)`

> **Замечание**: quota для текущего ключа имеет `limit: 0`. Реальный успешный HTTP 200 от Gemini в этой среде пока не получен, поэтому Gemini нельзя считать полностью проверенным в успешном режиме.

## 6. Проверка API

Проверенный POST:

```text
POST /api/projects/project_55badff214f2/products/58/seo-suggestions
```

Фактические параметры формы:

```json
{"action": "Расширить описание: назначение, сценарии, преимущества, характеристики."}
```

Success response:

```json
{
  "success": true,
  "task_id": "14162ff9e115405ab9fb86c2d1c4057e",
  "status": "succeeded",
  "model_used": "gemini-2.0-flash",
  "queued": 2,
  "items": [...]
}
```

Failure response:

```json
{
  "success": false,
  "task_id": "fb32c91b9cbf4cc7a0c9c9369a23c470",
  "status": "failed",
  "error": "AI error: Gemini API недоступен: ... (HTTP 429)",
  "queued": 0,
  "items": []
}
```

## 7. Проверка интерфейса

Подтверждено:

- `GET /suggestions` показывает блок `AI-задачи`;
- после successful run там видны `succeeded` job и pending approvals;
- у pending approvals отображаются кнопки `Принять` и `Отклонить`;
- при provider failure job показывается как `failed` с ошибкой `Gemini API недоступен ... (HTTP 429)`.

## 8. Тесты

Новый сквозной тест:

- `tests/test_client_projects.py::test_seo_suggestions_page_shows_jobs_and_approvals`

Почему он ловит исходную ошибку:

- вызывает тот же POST endpoint, что и существующая кнопка;
- проверяет реальную запись job;
- проверяет появление approvals;
- проверяет появление блока `AI-задачи` на вкладке `Предложения AI`.

Выполненные команды:

```bash
.venv/bin/python -m pytest -q tests/test_client_projects.py tests/test_suggestions_ui.py
RUFF_CACHE_DIR=/tmp/marketmind-ai-core-ruff .venv/bin/python -m ruff check app/ai_client.py app/ai_recommendation/job_queue.py app/web/routes/projects.py tests/test_client_projects.py --select F821,F401,F841
```

Результаты:

```text
71 passed in 143.30s
All checks passed!
```

## 9. Команда запуска

Основная команда запуска:

```bash
.venv/bin/python -m app.main --web --port 8000
```

## 10. Ограничения

1. Живой браузерный клик в этой сессии не выполнялся.
   - Проверка сделана через реальные HTTP handlers на ASGI app и через запросы к реальной БД.

2. В этой среде реальный Gemini call не таймаутится стабильно: изолированный запрос показал `HTTP 429 quota exceeded`.
   - Это подтверждено direct call и live POST без подмены ответа.

3. Контролируемый success run использовал только подмену внешнего AI response.
   - БД, route и approval workflow при этом были реальными.
