# P3.3 Report — Approval Workflow with Rollback

Дата: 2026-07-14
Проект: `MarketMind-AI-Core-main`

## Цель P3.3

Создать постоянный workflow для обработки AI-рекомендаций с хранением в БД, историей, apply и rollback.

## Что изменено

### ApprovalRecord модель

Добавлена в `app/database.py`:

| Поле | Тип | Описание |
|---|---|---|
| approval_id | VARCHAR(32) | Уникальный ID |
| product_id | VARCHAR(128) | ID товара |
| field | VARCHAR(64) | Поле товара |
| before_value | TEXT | Значение до AI |
| after_value | TEXT | Значение после AI |
| status | VARCHAR(16) | pending/approved/rejected/rolled_back |
| snapshot_before | TEXT | JSON: значение ДО apply |
| snapshot_after | TEXT | JSON: значение ПОСЛЕ apply |
| created_at | DATETIME | Время создания |
| reviewed_at | DATETIME | Время.review |
| applied_at | DATETIME | Время применения |
| rolled_back_at | DATETIME | Время отката |

### DatabaseApprovalQueue

Новый класс в `app/ai_recommendation/db_approval.py`:
- add() → сохраняет в БД
- approve() → обновляет статус + snapshot
- reject() → обновляет статус + reason
- rollback() → восстанавливает значение + статус "rolled_back"
- apply_approved() → применяет изменения + сохраняет snapshots
- get_all() / get_pending() → читает из БД

### Alembic миграция

`alembic/versions/d4e5f6a7b8c9_add_approval_records.py` — создание таблицы `approval_records`.

## Новый процесс

```
AI генерирует → ApprovalQueue (DB) → User review → Approve/Reject → Apply → History
                                                                     ↓
                                                              Rollback (если нужно)
```

### Rollback

1. Сохраняет snapshot_before перед apply
2. При откате: читает snapshot_before → восстанавливает значение поля
3. Статус: "rolled_back"

## Изменённые файлы

| Файл | Действие |
|---|---|
| `app/database.py` | Добавлена ApprovalRecord модель |
| `app/ai_recommendation/db_approval.py` | Создан — DatabaseApprovalQueue |
| `alembic/versions/d4e5f6a7b8c9_add_approval_records.py` | Создан — миграция |
| `app/web/app.py` | Изменён — DatabaseApprovalQueue вместо in-memory |
| `app/web/routes/suggestions.py` | Изменён — async, DB-backed, rollback endpoint |
| `tests/test_approval_workflow.py` | Создан — 11 тестов |
| `tests/test_suggestions_ui.py` | Изменён — DB-backed queue |

## Тестирование

```
436 passed, 24 warnings, 0 failed
```

- 11 тестов approval workflow — все проходят
- 8 тестов suggestions UI — все проходят
- 417 существующих тестов — все проходят
- 0 regressions

## Субагенты

| Агент | actor_id | Роль |
|---|---|---|
| Developer Agent | `general-94` | Реализация P3.3 |
| Test Agent | `general-95` | Верификация |
| Reviewer Agent | `general-96` | Ревью — REQUEST CHANGES (rollback) |
| Developer Agent (fix) | `general-97` | Исправление rollback |
| Reviewer Agent (re-review) | `general-98` | Повторное ревью — APPROVE |

## Готовность к следующим этапам

P3.3 завершён. Approval Workflow с rollback работает. Рекомендуемые следующие шаги:
- P3.4: Product Detail страница с историей цен
- P3.5: Health/Diagnostics страница
- P3.6: Reports generation из UI
