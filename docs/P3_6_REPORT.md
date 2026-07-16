# P3.6 Report — Client Reports UI

Дата: 2026-07-16

## Что сделано

Добавлен раздел Web UI `Отчёты` для клиентской сводки по каталогу.

Новые endpoints:

- `GET /reports` — HTML-страница отчёта;
- `GET /api/reports/client-summary` — JSON payload отчёта.

## Архитектура

Отчёт не дублирует бизнес-логику. Он собирается из существующих компонентов:

```text
Database
→ StoreAnalyzer
→ ApprovalRecord status summary
→ client report payload
→ Jinja2 / JSON API
```

## Новые файлы

- `app/web/routes/reports.py`
- `app/web/templates/reports.html`
- `tests/test_reports_ui.py`
- `docs/P3_6_IMPLEMENTATION_PLAN.md`
- `docs/P3_6_REPORT.md`

## Изменённые файлы

- `app/web/app.py` — подключён reports router.
- `app/web/templates/base.html` — добавлен пункт меню `Отчёты`.

## Возможности отчёта

- общее количество товаров;
- средний Quality Score;
- количество товаров ниже порога;
- summary AI-предложений;
- топ проблем;
- рекомендуемые действия;
- товары, требующие внимания;
- сравнение маркетплейсов.

## Тесты

Focused:

```text
tests/test_reports_ui.py: 5 passed
```

Проверяется:

- HTML-страница открывается на пустой БД;
- JSON API работает на пустой БД;
- JSON API работает с товарами;
- HTML показывает ключевые блоки;
- меню содержит ссылку на отчёты.

## Ограничения

- PDF/export отчёта пока не добавлен.
- Branding/white-label пока не добавлен.
- Отчёт локальный, без пользователей и проектов.

## Следующий шаг

P3.7 или P3.8:

- экспорт отчёта в HTML/PDF/XLSX;
- или редактор карточки товара с ручным сохранением версий.
