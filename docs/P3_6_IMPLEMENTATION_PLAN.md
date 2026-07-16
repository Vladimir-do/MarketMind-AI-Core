# P3.6 Implementation Plan — Client Reports UI

Дата: 2026-07-16

## Что найдено

В проекте уже есть:

- `StoreAnalyzer` для аналитики каталога;
- DB-backed `ApprovalRecord` для AI suggestions;
- Web UI на FastAPI/Jinja2/HTMX;
- старый `reporter.py` для HTML мониторинга цен;
- `exporter.py` для CSV/XLSX.

Для P3.6 не нужно переписывать старый `reporter.py`. Коммерчески полезнее добавить отдельный UI-отчёт по качеству карточек и AI-рекомендациям.

## Изменяемые файлы

- `app/web/app.py` — подключить reports router.
- `app/web/routes/reports.py` — новый backend route/API.
- `app/web/templates/base.html` — добавить пункт меню.
- `app/web/templates/reports.html` — новая страница отчёта.
- `tests/test_reports_ui.py` — тесты API и HTML.
- `docs/P3_6_REPORT.md` — итоговый отчёт.

## Архитектура

Новый слой Reports UI использует существующие источники:

```text
Database
→ StoreAnalyzer
→ ApprovalRecord summary
→ Report payload
→ HTML/API
```

Новые endpoints:

- `GET /reports` — HTML-страница клиентского отчёта;
- `GET /api/reports/client-summary` — JSON отчёт.

## Риски

- Не делать отдельную систему отчётов, пока нет требований к PDF/branding.
- Не смешивать с экспортом карточек Ozon/WB.
- Не вызывать внешние AI/API.
- Не менять БД.

## Проверка

- API отчёта возвращает summary/top issues/attention/suggestions.
- HTML страница открывается и содержит ключевые блоки.
- Пустая БД обрабатывается без ошибки.
- Полный pytest проходит.
