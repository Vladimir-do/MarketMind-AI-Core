# Pending Skill Proposal: HTMX Approval UI

Дата: 2026-07-14
Статус: pending

## Что обнаружено

P3.2 добавил reusable pattern для web-интерфейса подтверждения AI-предложений:

```text
ApprovalQueue -> route schema -> Jinja2 table/detail partials -> HTMX approve/reject actions
```

## Почему это reusable

Паттерн подходит для:

- AI-рекомендаций;
- модерации импортированных данных;
- подтверждения изменений карточек;
- review queue перед экспортом или публикацией.

## Где найдено

- `app/web/routes/suggestions.py`
- `app/web/templates/suggestions.html`
- `app/web/templates/suggestions_table.html`
- `app/web/templates/suggestions_row.html`
- `app/web/templates/suggestions_detail.html`
- `tests/test_suggestions_ui.py`

## Возможный будущий skill

ID: `web-htmx-approval-queue`

Категория: `web`

Суть: строить human-in-the-loop approval UI поверх очереди предложений без автоматического применения изменений.

