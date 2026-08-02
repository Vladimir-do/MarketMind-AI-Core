# P2.1 Report — AI Recommendation Layer

Дата: 2026-07-14
Проект: `MarketMind-AI-Core-main`

## Цель P2.1

Создать первый AI-слой MarketMind AI — рекомендательную систему, которая помогает продавцу принимать решения на основе анализа данных товаров.

## AI Layer Architecture

```
AnalysisResult (от ProductAnalyzer)
    ↓
AIRecommendationEngine
    ↓
AIRecommendationResult (с AISuggestions)
    ↓
ApprovalQueue (ожидает подтверждения человека)
    ↓
Approved suggestions → Apply к UnifiedProduct
```

### Ключевые компоненты

| Компонент | Модуль | Роль |
|---|---|---|
| AIProvider | `app/ai_recommendation/provider.py` | Протокол для AI-провайдеров |
| AIRecommendationEngine | `app/ai_recommendation/engine.py` | Генерация рекомендаций |
| AISuggestion | `app/ai_recommendation/suggestions.py` | Предложение по улучшению |
| ApprovalQueue | `app/ai_recommendation/approval.py` | Очередь подтверждений |
| MockAIProvider | `app/ai_recommendation/mock_provider.py` | Мок для тестов |

## Provider Abstraction

```python
class AIProvider(Protocol):
    async def complete(prompt, *, system, max_tokens, temperature) -> AIResponse
    def is_available() -> bool
    def name() -> str
```

Поддерживаемые провайдеры (через обёртки):
- Claude (Anthropic SDK)
- Grok (xAI HTTP)
- Gemini (Google HTTP)
- MiMo (будущее)
- DeepSeek (будущее)
- Локальные модели (будущее)

## Human Approval Flow

```
AI рекомендует → ApprovalQueue → Пользователь подтверждает/отклоняет → Применяется к товару
```

AI НЕ должен:
- Автоматически менять товар
- Автоматически публиковать
- Удалять данные

AI только предлагает.

## AI Suggestions Format

```json
{
  "field": "description",
  "suggestion_type": "rewrite",
  "before": "короткое описание...",
  "after": "Расширенное описание с ключевыми преимуществами...",
  "reason": "Description is only 32 chars — aim for 150+",
  "confidence": 0.85,
  "source_finding": "quality_description_short"
}
```

### Типы suggestions

| Тип | Описание |
|---|---|
| rewrite | Переписать поле |
| optimize | Оптимизировать поле |
| fill | Заполнить пустое поле |
| flag | Пометить проблему |
| pricing | Рекомендация по цене |

## Созданные компоненты

| Файл | Строки | Роль |
|---|---|---|
| `app/ai_recommendation/__init__.py` | Re-exports | Package |
| `app/ai_recommendation/provider.py` | ~50 | AIProvider Protocol + AIResponse |
| `app/ai_recommendation/suggestions.py` | ~60 | AISuggestion + results |
| `app/ai_recommendation/mock_provider.py` | ~40 | MockAIProvider |
| `app/ai_recommendation/engine.py` | ~150 | AIRecommendationEngine |
| `app/ai_recommendation/approval.py` | ~80 | ApprovalQueue |
| `tests/test_ai_recommendation.py` | ~100 | 22 теста |

## Изменённые файлы

Нет — только новые файлы. Существующий код не затронут.

## Тестирование

```
372 passed, 24 warnings, 0 failed
```

- 278 существующих тестов — все проходят
- 72 теста P1.x — все проходят
- 22 теста AI recommendation — все проходят
- 0 regressions

## Готовность к AI Agents

AI Layer готов к расширению:
- Provider Protocol позволяет добавлять новые провайдеры без изменения engine
- ApprovalQueue обеспечивает контроль человека
- MockAIProvider позволяет тестировать без API
- Engine отделён от конкретного провайдера

## Субагенты

| Агент | actor_id | Роль |
|---|---|---|
| Architect Agent | `general-72` | Дизайн AI layer |
| Developer Agent | `general-73` | Реализация (7 файлов) |
| Test Agent | `general-74` | Верификация |
| Reviewer Agent | `general-75` | Ревью — APPROVE |

## Готовность к следующим этапам

P2.1 завершён. AI Recommendation Layer создан. Рекомендуемые следующие шаги:
- P2.2: Интеграция AI layer с pipeline (run_with_ai_recommendations)
- P2.3: Telegram /ai_suggest команда
- P2.4: Реальные AI провайдеры (Anthropic, OpenAI)
