# P1.5 Report — Product Intelligence Layer

Дата: 2026-07-14
Проект: `MarketMind-AI-Core-main`

## Цель P1.5

Создать первый интеллектуальный слой MarketMind AI — rule-based анализ качества данных товара с рекомендациями по улучшению.

## Product Intelligence Architecture

```
UnifiedProduct → ProductAnalyzer → AnalysisResult
                                     ↓
                          Quality Score (0-100)
                          Findings (проблемы)
                          Recommendations (рекомендации)
                          Tier (excellent/good/fair/poor/critical)
```

### Ключевые компоненты

| Компонент | Модуль | Роль |
|---|---|---|
| ProductAnalyzer | `app/products/analyzer.py` | 20 правил анализа + scoring |
| Finding | `app/products/findings.py` | Проблема товара (rule, field, severity) |
| Recommendation | `app/products/findings.py` | Рекомендация по исправлению |
| AnalysisResult | `app/products/findings.py` | Результат анализа одного товара |
| BatchAnalysisResult | `app/products/findings.py` | Агрегированный результат по списку |

## Правила анализа

### Полнота данных (10 правил)

| Правило | Серьёзность | Проверка |
|---|---|---|
| missing_name | critical | Пустое название |
| missing_source_id | critical | Пустой ID |
| missing_price | critical | Нет цены |
| missing_description | warning | Нет описания |
| missing_brand | warning | Нет бренда |
| missing_category | warning | Нет категории |
| missing_images | warning | Нет фото |
| missing_weight | info | Нет веса |
| missing_dimensions | info | Нет размеров |
| missing_attributes | info | Нет атрибутов |

### Согласованность (6 правил)

| Правило | Серьёзность | Проверка |
|---|---|---|
| price_nonpositive | critical | Цена <= 0 |
| old_price_not_greater | warning | Старая цена <= текущей |
| discount_mismatch | info | Скидка не совпадает |
| price_unreasonably_high | warning | Цена > 10M |
| dimensions_partial | warning | Не все размеры |
| weight_nonpositive | warning | Вес <= 0 |

### Качество (4 правила)

| Правило | Серьёзность | Проверка |
|---|---|---|
| name_too_long | info | Название > 140 символов |
| description_too_short | info | Описание < 50 символов |
| description_too_long | info | Описание > 4000 символов |
| generic_brand | info | Бренд = "Нет бренда" |

## Quality Score

Формула: `100 - sum(penalties)`, clamped [0, 100].

| Штраф | Вес |
|---|---|
| critical finding | -25 |
| warning finding | -10 |
| info finding | -3 |

### Интерпретация

| Диапазон | Уровень | Значение |
|---|---|---|
| 90-100 | Excellent | Готов к публикации |
| 75-89 | Good | Нужны мелкие улучшения |
| 50-74 | Fair | Несколько полей отсутствует |
| 25-49 | Poor | Критические данные отсутствуют |
| 0-24 | Critical | Нельзя опубликовать |

## Findings System

Каждый Finding содержит:
- rule: ID правила
- field: поле товара
- message: описание проблемы на русском
- severity: critical/warning/info
- category: completeness/consistency/quality

## Recommendations System

Каждая Recommendation содержит:
- finding: связанная проблема
- action: действие (add_brand, fix_price, add_images)
- priority: 1 (критично) - 3 (инфо)
- description: описание рекомендации

## Созданные компоненты

| Файл | Строки | Роль |
|---|---|---|
| `app/products/findings.py` | 53 | Dataclasses |
| `app/products/analyzer.py` | 388 | 20 правил + scoring |
| `tests/test_analyzer.py` | 171 | 15 тестов |

## Изменённые файлы

Нет — только новые файлы.

## Тестирование

```
339 passed, 24 warnings, 0 failed
```

- 278 существующих тестов — все проходят
- 46 тестов importers/pipeline — все проходят
- 15 тестов analyzer — все проходят
- 0 regressions

## Готовность к AI Layer

Intelligence Layer готов к интеграции с AI:
- Rule-based анализ работает без AI
- Finding/Recommendation структуры могут передаваться в AI для генерации советов
- Quality Score может использоваться для ранжирования товаров
- BatchAnalysisResult даёт обзор по всему списку товаров

## Субагенты

| Агент | actor_id | Роль |
|---|---|---|
| Architect Agent | `general-64` | Дизайн intelligence layer |
| Developer Agent | `general-65` | Реализация (3 файла) |
| Test Agent | `general-66` | Верификация |
| Reviewer Agent | `general-67` | Ревью — APPROVE |

## Готовность к следующим этапам

P1.5 завершён. Intelligence Layer работает. Рекомендуемые следующие шаги:
- P1.6: Интеграция intelligence layer с pipeline
- P2.1: Telegram /import команда
- P2.2: AI Layer (LLM-based рекомендации)
- P2.3: Inline-клавиатуры для Telegram
