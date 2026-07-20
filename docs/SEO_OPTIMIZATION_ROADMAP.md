# SEO Optimization Roadmap

MarketMind AI уже имеет генерацию карточек Ozon, ключевые слова, контекст конкурентов и AI-рекомендации. Следующая цель -- превратить эти возможности в чёткий SEO intelligence layer без автоматического применения изменений.

## Фаза 1. Локальный SEO-аудит карточки

Статус: реализовано.

- Добавлен детерминированный SEO-скоринг для карточек товаров.
- Проверяются: длина title, наличие типа товара, покрытие ключевыми словами, глубина описания, преимущества, характеристики, изображения, категория.
- Возвращаются рекомендации, но ничего не применяется автоматически.
- Аудит независим от Telegram, экспорта и AI-провайдеров.
- SEO-аудит доступен на странице товара и через `/api/products/{product_id}/seo`.
- Project-scoped SEO-аудит для Effective Product Card: `/api/projects/{project_id}/products/{product_id}/seo`.

## Фаза 2. SEO в Export Preview

Статус: реализовано.

- В export-preview для каждой карточки добавлены: `seo_score`, `seo_tier`, `seo_ready`, `seo_recommendations`, `seo_critical_issues`, `seo_warning_issues`.
- Используется `audit_unified_product_seo` из `app/seo_intelligence.py`.

## Фаза 3. SEO в XLSX/CSV Export

Статус: реализовано.

- XLSX-экспорт содержит колонки: `seo_score`, `seo_level`, `seo_ready`, `seo_recommendations`, `seo_critical_issues`, `seo_warning_issues`.
- CSV-экспорт содержит: `seo_score`, `seo_tier`, `seo_ready`, `seo_recommendations`.
- Все значения проходят через `sanitize_export_row` для защиты от formula injection.

## Фаза 4. SEO Report

Статус: реализовано.

- В report-preview добавлена `seo_summary`:
  - `average_score` -- средний SEO-балл по проекту.
  - `distribution` -- распределение по tier (strong/usable/needs_work/weak).
  - `worst_cards` -- топ-10 карточек с худшим SEO.
  - `top_problems` -- топ повторяющихся проблем по rule.

## Фаза 5. SEO Suggestions через Approval Workflow

Статус: реализовано.

- SEO-рекомендации конвертируются в `AISuggestion`-совместимый формат для полей: title, description, tags.
- Добавлен метод `seo_suggestions()` в `EffectiveProductCardService`.
- Добавлен API: `GET /api/projects/{project_id}/products/{product_id}/seo-suggestions`.
- Confidence 0.3--0.7 (SEO-рекомендации менее уверены чем AI).
- Автоматическое применение НЕ происходит -- suggestions только для approval workflow.

## Фаза 6. Правила для маркетплейсов

Статус: запланировано.

- Сохранить первые правила marketplace-agnostic для любого маркетплейса.
- Добавить Ozon-specific limits и best practices как первый опциональный профиль.
- Добавить Wildberries/Yandex Market профили только после стабилизации Ozon правил.
- Версионировать правила чтобы exports и отчёты показывали какой стандарт использовался.

## Фаза 7. Конкурентное семантическое ядро

Статус: реализовано (Semantic Core).

- Добавлен модуль `app/semantic_core.py` с детерминированным extractor'ом.
- Классификация ключевых слов: primary, secondary, long_tail, brand, attribute, category, forbidden, noisy.
- SEO-аудит автоматически строит semantic core и добавляет findings.
- Endpoints: `GET /api/products/{id}/semantic-core`, `GET /api/projects/{id}/products/{id}/semantic-core`.
- Coverage score и junk ratio доступны клиенту.
- Не выдумывает факты -- только извлекает из существующих данных карточки.

- Использовать имена/описания конкурентов для извлечения повторяющихся фраз.
- Отделять термины типа товара, термины свойств, термины бренда и шум.
- Сравнивать ключевые слова карточки с фразами конкурентов.
- Добавлять рекомендации по недостающим фразам с confidence и source count.

## Фаза 8. Данные о поисковом спросе

Статус: реализовано (базовый уровень).

- Добавлен модуль `app/keyword_sources.py` с протоколом KeywordSource.
- ManualCSVSource -- импорт CSV с колонками keyword, frequency, marketplace, category.
- CompetitorSource -- извлечение из карточек конкурентов через extract_competitor_terms.
- merge_keyword_sources -- объединение источников с приоритетом и лимитом.
- Endpoint: `POST /api/projects/{project_id}/keywords/import` -- парсинг CSV без мутирования БД.
- Платные/внешние источники (Ozon Seller analytics, MPStats, Moneyplace, Wordstat) -- запланированы как следующий шаг.

- Добавить опциональные коннекторы для источников частотности.
- Кандидаты: Ozon Seller analytics, MPStats, Moneyplace, Wordstat или ручной CSV-импорт.
- Все внешние данные считать advisory; пользовательское подтверждение обязательно перед применением.

## Фаза 9. Цикл измерений

Статус: реализовано (базовый уровень).

- Добавлен модуль `app/seo_history.py` с SEOAuditSnapshot и SEOHistoryService.
- Хранение in-memory (лимит 1000 снимков на продукт).
- Автоматическая запись при каждом SEO-аудите через effective_card/service.py.
- Endpoints: `GET /api/products/{id}/seo-history`, `GET /api/projects/{id}/products/{id}/seo-history`.
- Score trend для графиков.
- До/после сравнение source vs effective.

- Сохранять снимки SEO-аудита по версиям продукта/карточки.
- Отслеживать изменения балла во времени.
- Позже добавить метрики ранжирования/CTR/конверсии когда появятся аналитические данные маркетплейса.
