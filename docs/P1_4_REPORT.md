# P1.4 Report — Import Pipeline + Batch Enrichment

Дата: 2026-07-14
Проект: `MarketMind-AI-Core-main`

## Цель P1.4

Создать первый рабочий конвейер MarketMind AI: Input → Import → Validate → Enrich → Result.

## Новый Pipeline обработки товаров

```
CSV/Excel File
    ↓
ImportPipeline.run_file()
    ↓
Importer (CSV/Excel)
    ↓
UnifiedProduct[]
    ↓
ProductValidator
    ↓
Valid Products[] + Errors[]
    ↓
EnrichmentStrategy (OzonEnrichmentStrategy)
    ↓
EnrichedProduct[] (с черновиками карточек)
    ↓
PipelineResult
```

## Архитектура Import → Enrich

| Этап | Модуль | Роль |
|---|---|---|
| Import | `app/importers/registry.py` | Маршрутизация по типу файла |
| Validate | `app/products/validator.py` | 10 правил проверки (error/warning) |
| Enrich | `app/enrichers/ozon_enricher.py` | Генерация черновика карточки + оценка качества |
| Pipeline | `app/pipeline.py` | Оркестратор всех этапов |

### Проверки валидатора

| Правило | Поле | Тип |
|---|---|---|
| required_name | name | error |
| required_source_id | source_id | error |
| price_positive | price | error |
| price_range | price | warning |
| old_price_gt_price | old_price | warning |
| url_valid | source_url | error |
| dimensions_complete | width/height/depth | error |
| weight_positive | weight_g | error |
| name_length | name | warning |
| description_length | description | warning |

### EnrichmentStrategy

Плагинная архитектура — обогащение не привязано к Ozon:
- `EnrichmentStrategy` Protocol в `app/enrichers/__init__.py`
- `OzonEnrichmentStrategy` — конкретная реализация
- `strategy=None` — пропуск обогащения

## Созданные компоненты

| Файл | Роль |
|---|---|
| `app/products/validator.py` | ProductValidator с 10 правилами |
| `app/pipeline.py` | ImportPipeline (import → validate → enrich) |
| `app/enrichers/__init__.py` | EnrichmentStrategy Protocol |
| `app/enrichers/ozon_enricher.py` | OzonEnrichmentStrategy |
| `tests/test_pipeline.py` | 9 тестов pipeline |
| `tests/test_pipeline_enrichment.py` | 26 тестов enrichment |

## Изменённые файлы

| Файл | Изменение |
|---|---|
| `app/pipeline.py` | Убрана прямая привязка к Ozon, добавлен strategy parameter |

## Тестирование

```
324 passed, 24 warnings, 0 failed
```

- 278 существующих тестов — все проходят
- 11 тестов importers — все проходят
- 9 тестов pipeline — все проходят
- 26 тестов enrichment — все проходят
- 0 regressions

## Риски

| Риск | Серьёзность | Митигация |
|---|---|---|
| Default strategy создаёт compile-time dependency на Ozon | LOW | Lazy import или explicit injection в будущем |
| Нет тестов для PDF/image импортёров | LOW | Планируется в P1.5+ |

## Готовность к AI Engine

Pipeline готов к интеграции с AI:
- `EnrichmentStrategy` может включать AI-обогащение
- `UnifiedProduct.to_card_task()` Produces текст для AI
- `build_enhanced_ozon_card_draft()` уже поддерживает AI
- Pipeline изолирован от AI — можно добавить AI-стратегию без изменения pipeline

## Субагенты

| Агент | actor_id | Роль |
|---|---|---|
| Architect Agent | `general-58` | Дизайн pipeline |
| Developer Agent | `general-59` | Реализация |
| Test Agent | `general-60` | Верификация |
| Reviewer Agent | `general-61` | Ревью — REQUEST CHANGES |
| Developer Agent (fix) | `general-62` | Исправление coupling + тесты |
| Reviewer Agent (re-review) | `general-63` | Повторное ревью — APPROVE |

## Готовность к следующим этапам

P1.4 завершён. Pipeline работает. Рекомендуемые следующие шаги:
- P1.5: Telegram /import команда
- P1.6: PDF/OCR импорт
- P2.1: Inline-клавиатуры для Telegram
- P2.2: AI Engine интеграция
