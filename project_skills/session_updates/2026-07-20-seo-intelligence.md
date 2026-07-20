# Pending Skill Proposal: Marketplace SEO Intelligence

Status: ready for promotion

## What Changed

Добавлен `docs/SEO_OPTIMIZATION_ROADMAP.md` и детерминированный SEO-аудит модуль `app/seo_intelligence.py`.

### Фаза 1: SEO-аудит и UI
- `/api/products/{product_id}/seo`
- product detail SEO block в `app/web/templates/product_detail.html`
- marketplace-neutral `audit_unified_product_seo(...)`
- `/api/projects/{project_id}/products/{product_id}/seo`
- project-scoped effective/source SEO payloads
- project product detail SEO block в `app/web/templates/project_product_detail.html`

### Фаза 2: SEO в Export Preview
- В export-preview: `seo_score`, `seo_tier`, `seo_ready`, `seo_recommendations`, `seo_critical_issues`, `seo_warning_issues`

### Фаза 3: SEO в XLSX/CSV Export
- XLSX: `seo_score`, `seo_level`, `seo_ready`, `seo_recommendations`, `seo_critical_issues`, `seo_warning_issues`
- CSV: `seo_score`, `seo_tier`, `seo_ready`, `seo_recommendations`
- Защита от formula injection через `sanitize_export_row`

### Фаза 4: SEO Report
- `seo_summary` в report-preview: average_score, distribution, worst_cards, top_problems
- semantic summary в report-preview: average_coverage_score, average_junk_ratio, cards_without_primary_terms, top_terms

### Фаза 5: SEO Suggestions через Approval Workflow
- `seo_suggestions()` в `EffectiveProductCardService`
- `GET /api/projects/{project_id}/products/{product_id}/seo-suggestions` как немутирующий draft preview
- `POST /api/projects/{project_id}/products/{product_id}/seo-suggestions` ставит реальные pending-записи в `DatabaseApprovalQueue`
- `AISuggestion` формат для title, description, tags
- Confidence 0.3--0.7, автоматическое применение НЕ происходит
- SEO suggestions не должны выдумывать факты о товаре. Если `after` нельзя построить из текущей карточки, import snapshot или атрибутов, finding остается рекомендацией аудита, но не превращается в applyable suggestion.

### Фаза 6: Semantic Core
- `app/semantic_core.py` -- детерминированный extractor семантического ядра
- Классификация: primary, secondary, long_tail, brand, attribute, category, forbidden, noisy
- SEO-аудит автоматически строит semantic core и добавляет findings
- Endpoints: `GET /api/products/{id}/semantic-core`, `GET /api/projects/{id}/products/{id}/semantic-core`
- Coverage score и junk ratio для клиента
- Не выдумывает факты -- только извлекает из существующих данных

### Фаза 7: Источники ключевых слов
- `app/keyword_sources.py` -- протокол KeywordSource, ManualCSVSource, CompetitorSource
- `POST /api/projects/{project_id}/keywords/import` -- парсинг CSV без мутирования БД
- merge_keyword_sources -- объединение с приоритетом

### Фаза 8: Measurement Loop
- `app/seo_history.py` -- in-memory трекер SEO-снимков
- Read-only SEO endpoints не должны автоматически писать history; запись снимка должна быть явным measurement action.
- Score trend для графиков

### Regression Lessons
- HTMX-кнопки должны указывать на реально зарегистрированный route. Если API route возвращает JSON, для HTMX-запроса нужен HTML response или отдельный HTML endpoint.
- `GET`/read endpoints не должны писать audit history. Даже optional injected services не должны превращать read path в mutation.
- CSV-импорт пользовательских keyword frequency должен быть tolerant: невалидная частота не должна валить весь импорт.

## Why It Is Reusable

Marketplace card workflows need SEO scoring that is independent from AI providers and does not auto-apply changes. A deterministic audit can run in Telegram, web UI, batch exports and approval workflows.

## Candidate Skill

- ID: `marketplace-seo-intelligence`
- Category: `seo` or `analytics`
- Dependencies: `ozon-card-draft-builder`, `ozon-card-ai-enhancement`, `card-profile-yaml`, `effective-card-service`, `approval-workflow`
- Source paths: `app/seo_intelligence.py`, `app/effective_card/service.py`, `app/exports/service.py`, `app/reports/service.py`, `app/web/routes/product_detail.py`, `app/web/routes/projects.py`, `app/web/templates/product_detail.html`, `app/web/templates/project_product_detail.html`, `app/web/templates/project_products.html`, `tests/test_seo_intelligence.py`, `tests/test_product_detail.py`, `tests/test_client_projects.py`, `docs/SEO_OPTIMIZATION_ROADMAP.md`

## Notes

Готов к продвижению в полноценный skill. SEO/semantic fixes проверены: 682 passed, 24 warnings, 14 subtests passed; Ruff clean.
