# P3.3 — Approval Workflow: Техническое задание

Дата: 2026-07-14
Статус: ПЛАН (ожидает подтверждения)

## 1. Цель Approval Workflow

Создать постоянный workflow для обработки AI-рекомендаций: хранение, история, применение одобренных изменений.

## 2. Текущий процесс

```
AI генерирует → ApprovalQueue (in-memory) → User approve/reject → Queue обновляется
```

**Проблемы:**
- ApprovalQueue хранится в памяти (dict)
- Теряется при перезапуске приложения
- Нет истории операций
- Нет возможности применить одобренные изменения к товарам

## 3. Новый процесс

```
AI генерирует → ApprovalQueue → User review → Approve/Reject → Apply к товарам → History
```

### Этапы:

1. **AI генерирует** — AISuggestion попадает в ApprovalQueue
2. **Review** — пользователь просматривает в UI
3. **Approve/Reject** — пользователь принимает решение
4. **Apply** — одобренные изменения применяются к UnifiedProduct
5. **History** — все операции записываются в БД

## 4. Данные для хранения

### Что хранить:

| Данные | Описание |
|---|---|
| suggestion | AISuggestion (field, before, after, reason, confidence) |
| product_id | ID товара |
| status | pending / approved / rejected |
| reject_reason | Причина отклонения |
| created_at | Время создания |
| reviewed_at | Время.review |
| applied_at | Время применения |
| applied_by | Кто применил (user_id) |

### Не хранить:

- Сырой AI-ответ (токены, latency) — это метаданные, не данные товара
- Промежуточные состояния pipeline

## 5. Перенос ApprovalQueue из памяти в БД

**Да, нужен.** Текущий in-memory подход ненадёжный.

### Обоснование:

| Критерий | In-memory | Database |
|---|---|---|
| Перезапуск | Теряются данные | Сохраняются |
| Масштабирование | Один процесс | Несколько процессов |
| История | Нет | Есть |
| Откат | Невозможен | Возможен |
| Аудит | Невозможен | Возможен |

### Рекомендация:

Создать SQLAlchemy модель `ApprovalRecord` и адаптировать `ApprovalQueue` для работы с БД.

## 6. Таблицы БД

### Таблица: `approval_records`

```sql
CREATE TABLE approval_records (
    id              INTEGER PRIMARY KEY,
    approval_id     VARCHAR(32) NOT NULL UNIQUE,
    product_id      VARCHAR(128) NOT NULL,
    field           VARCHAR(64) NOT NULL,
    suggestion_type VARCHAR(32) NOT NULL,
    before_value    TEXT,
    after_value     TEXT NOT NULL,
    reason          TEXT NOT NULL,
    confidence      REAL NOT NULL,
    source_finding  VARCHAR(128),
    status          VARCHAR(16) NOT NULL DEFAULT 'pending',
    reject_reason   TEXT,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at     DATETIME,
    applied_at      DATETIME,
    applied_by      VARCHAR(128)
);

CREATE INDEX ix_approval_records_status ON approval_records(status);
CREATE INDEX ix_approval_records_product_id ON approval_records(product_id);
CREATE INDEX ix_approval_records_created_at ON approval_records(created_at);
```

### Связи:

```
approval_records.product_id → products.id (виртуальная, не FK — product_id строковый)
```

## 7. API Endpoints

### Существующие (обновить):

| Метод | Путь | Изменение |
|---|---|---|
| GET | `/api/suggestions` | Читать из БД вместо in-memory |
| POST | `/suggestions/{id}/approve` | Писать в БД + apply |
| POST | `/suggestions/{id}/reject` | Писать в БД |

### Новые:

| Метод | Путь | Описание |
|---|---|---|
| POST | `/api/suggestions/apply-all` | Применить все одобренные |
| GET | `/api/suggestions/history` | История операций |
| GET | `/api/suggestions/{id}/history` | История конкретного предложения |

## 8. UI Изменения

### Существующие страницы (обновить):

| Страница | Изменение |
|---|---|
| `/suggestions` | Данные из БД, кнопка "Применить все" |
| `/suggestions/{id}` | Показать историю |

### Новые элементы:

- Кнопка "Применить все одобренные" (после approve)
- Индикатор "Применено" после apply
- Раздел "История" на странице предложения

## 9. Изменения в коде

### Новые файлы:

| Файл | Описание |
|---|---|
| `app/database.py` | Добавить модель `ApprovalRecord` |
| `app/ai_recommendation/approval.py` | Адаптировать для работы с БД |
| `alembic/versions/...` | Миграция для `approval_records` |

### Изменённые файлы:

| Файл | Изменение |
|---|---|
| `app/web/routes/suggestions.py` | Читать/писать в БД |
| `app/web/app.py` | Инициализация DB-backed queue |
| `app/ai_recommendation/layer.py` | Использовать DB-backed queue |
| `tests/test_suggestions_ui.py` | Обновить для DB-backed queue |

## 10. Тесты

| Тест | Покрытие |
|---|---|
| `test_approval_record_created_on_add` | Запись создаётся в БД |
| `test_approval_record_updated_on_approve` | Статус меняется на approved |
| `test_approval_record_updated_on_reject` | Статус меняется на rejected + reason |
| `test_apply_approved_updates_product` | Одобренные изменения применяются |
| `test_history_records_all_operations` | Все операции записываются |
| `test_queue_survives_restart` | Данные сохраняются после перезапуска |
| `test_concurrent_approve_reject` | Конкурентный доступ |

## 11. Риски

| Риск | Серьёзность | Митигация |
|---|---|---|
| Миграция БД сломает существующие данные | Medium | Alembic downgrade, тесты на пустой БД |
| Apply не откатывается | High | Транзакция + backup перед apply |
| Конкурентный доступ к записи | Medium | Optimistic locking |
| Сложность изменений | Medium | Инкрементально: сначала хранение, потом apply |

## 12. Требование отката (Rollback)

### Snapshot перед Apply

Перед применением AI-изменения нужно сохранить текущее состояние товара:

```python
@dataclass
class ProductSnapshot:
    product_id: str
    field: str
    value_before: str  # текущее значение поля
    timestamp: datetime
```

### Связь с ApprovalRecord

```sql
CREATE TABLE approval_records (
    ...
    snapshot_before TEXT,  -- JSON: текущее значение поля ДО apply
    snapshot_after TEXT,   -- JSON: значение поля ПОСЛЕ apply
    ...
);
```

### Rollback процесс

1. User нажимает "Откатить"
2. Читаем `snapshot_before` из ApprovalRecord
3. Восстанавливаем значение поля в товаре
4. Обновляем статус записи на "rolled_back"

### Тест отката

```python
test_rollback_restores_original_value:
    - Создать товар с полем "name" = "Старое название"
    - AI предлагает "name" = "Новое название"
    - Approve + Apply → товар = "Новое название"
    - Rollback → товар = "Старое название"
```

## 13. Критерии готовности

- [ ] ApprovalRecord модель создана
- [ ] Миграция применена
- [ ] ApprovalQueue работает с БД
- [ ] Approve/Reject пишут в БД
- [ ] Apply применяет изменения к товарам
- [ ] History записывает все операции
- [ ] UI показывает историю
- [ ] Данные сохраняются после перезапуска
- [ ] Все тесты проходят
- [ ] Reviewer Agent: APPROVE
