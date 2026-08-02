# Codex P3.2 Plan — AI Suggestions UI

Дата: 2026-07-14

## Что найдено

- `docs/PROJECT_STATE.md` отсутствует в проекте. Аудит выполнен по фактическим файлам `docs/P3_REPORT.md`, `docs/P2_4_REPORT.md`, `docs/P2_2_REPORT.md` и коду.
- Web UI уже существует на FastAPI + Jinja2 + HTMX + Tailwind:
  - `app/web/app.py`
  - `app/web/routes/dashboard.py`
  - `app/web/routes/products.py`
  - `app/web/routes/import_.py`
  - `app/web/routes/suggestions.py`
  - `app/web/templates/*.html`
- Раздел AI Suggestions уже частично реализован:
  - HTML page: `/suggestions`
  - partial list: `/suggestions/list`
  - API list: `/api/suggestions`
  - stats: `/api/suggestions/stats`
  - approve/reject через HTMX.
- AI layer уже содержит:
  - `AIRecommendationEngine`
  - `AISuggestion`
  - `ApprovalQueue`
  - `PendingApproval`
- Существующие проблемы P3.2:
  - `GET /suggestions/{id}` из ТЗ отсутствует; есть только `/suggestions/{id}/detail`.
  - `suggestions_page()` включает `suggestions_table.html`, но не передаёт `items`, из-за этого первый HTML может показывать пустой список.
  - API item не содержит человекочитаемое имя товара, только `product_id`.
  - Нет отдельного JSON endpoint для одной рекомендации.
  - Ошибки неправильного ID возвращаются plain text `Not found`, без единого безопасного ответа.
  - Reject endpoint принимает Pydantic body, но HTMX form чаще отправляет form-encoded данные.
  - Тесты покрывают happy path, но слабо проверяют detail, wrong ID, пустой HTML state и отсутствие автоприменения.

## Какие файлы будут изменены

- `app/web/routes/suggestions.py`
- `app/web/schemas.py`
- `app/web/templates/suggestions.html`
- `app/web/templates/suggestions_table.html`
- `app/web/templates/suggestions_row.html`
- `app/web/templates/suggestions_detail.html`
- `tests/test_suggestions_ui.py`
- `docs/CODEX_P3_2_REPORT.md`

## Архитектурный план

1. Не создавать новый AI engine и не дублировать бизнес-логику.
2. Использовать существующий `ApprovalQueue` как источник состояния UI.
3. Добавить helper-функции в route module:
   - безопасное получение очереди из `request.app.state`;
   - поиск `PendingApproval` по ID;
   - фильтрация по статусу;
   - преобразование в `SuggestionItem`.
4. Расширить `SuggestionItem`:
   - добавить `product_name`, вычисляемое из `suggestion.metadata["product_name"]` или fallback на `product_id`.
5. Добавить canonical endpoints:
   - `GET /suggestions/{id}` — HTML detail;
   - `GET /api/suggestions/{id}` — JSON detail;
   - оставить `/suggestions/{id}/detail` как backward-compatible alias для HTMX.
6. Обновить templates:
   - список сразу показывает реальные `items`;
   - карточка показывает товар, проблему, текущее значение, предложение AI, причину, confidence, статус;
   - approve/reject остаются HTMX actions без автоприменения данных продукта.
7. Обновить tests:
   - страница открывается и отображает предложения;
   - API list/detail;
   - approve/reject;
   - wrong ID;
   - empty queue;
   - подтверждение, что approve меняет только статус, а не данные товара.

## Риски

- `ApprovalQueue` сейчас in-memory. После рестарта web app предложения теряются. Это допустимо для MVP, но требует будущего persistent storage.
- В проекте нет полноценной связи suggestion → Product entity в web state, поэтому `product_name` пока берётся из metadata или fallback `product_id`.
- Текущая reject-причина мутирует `suggestion.reason`; это поведение уже есть в `ApprovalQueue` и не меняется в P3.2.
- Нет auth/multi-user модели для web UI. P3.2 не решает разграничение доступа.

