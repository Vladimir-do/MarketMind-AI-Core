# P2.4 Report — Real AI Providers

Дата: 2026-07-14
Проект: `MarketMind-AI-Core-main`

## Цель P2.4

Подключить реальные AI-провайдеры к MarketMind AI с возможностью переключения без изменения кода.

## AI Provider Architecture

```
AIRecommendationEngine
    ↓
AIProvider Protocol
    ↓
BaseAIProvider (ABC)
    ↓
├── OpenAICompatibleProvider (OpenAI, DeepSeek, MiMo)
├── OllamaProvider (local)
└── FallbackAIProvider (wrapper)
```

### Провайдеры

| Провайдер | API | Модель | Ключ |
|---|---|---|---|
| OpenAI | /v1/chat/completions | gpt-4o | OPENAI_API_KEY |
| DeepSeek | /v1/chat/completions | deepseek-chat | DEEPSEEK_API_KEY |
| MiMo | /v1/chat/completions | mimo | MIMO_API_KEY |
| Ollama | /api/chat | llama3 | не нужен |
| Claude | /v1/chat/completions | claude-3-5-sonnet | ANTHROPIC_API_KEY |
| Grok | /v1/chat/completions | grok-3-mini | GROK_API_KEY |
| Gemini | /v1/chat/completions | gemini-2.0-flash | GEMINI_API_KEY |

### OpenAICompatibleProvider

Покрывает все API, совместимые с OpenAI:
- OpenAI
- DeepSeek
- MiMo
- Claude (через OpenAI gateway)
- Grok (xAI)
- Gemini

## Поддерживаемые модели

| Провайдер | Модель по умолчанию | Конфигурация |
|---|---|---|
| OpenAI | gpt-4o | OPENAI_MODEL |
| DeepSeek | deepseek-chat | DEEPSEEK_MODEL |
| MiMo | mimo | MIMO_MODEL |
| Ollama | llama3 | OLLAMA_MODEL |

## Конфигурация

```env
AI_ENABLED=true
AI_PROVIDER=openai

OPENAI_API_KEY=sk-...
DEEPSEEK_API_KEY=sk-...
MIMO_API_KEY=...
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3

AI_ENABLE_FALLBACK=1
AI_FALLBACK_PROVIDERS=openai,deepseek,ollama
```

## Fallback стратегия

```python
FallbackAIProvider([OpenAIProvider, DeepSeekProvider, OllamaProvider])
```

- Пробует провайдеры последовательно
- Пропускает недоступные
- При ошибке переходит к следующему
- Все провайдеры упали → RuntimeError

## Безопасность

- API ключи только из .env
- Нет хардкоженных ключей в коде
- Ollama не требует ключа
- Fallback не ломает pipeline

## Созданные файлы

| Файл | Роль |
|---|---|
| `app/ai_recommendation/providers/__init__.py` | Package |
| `app/ai_recommendation/providers/base.py` | BaseAIProvider ABC |
| `app/ai_recommendation/providers/openai_compatible.py` | OpenAI/DeepSeek/MiMo |
| `app/ai_recommendation/providers/ollama_provider.py` | Local Ollama |
| `app/ai_recommendation/providers/factory.py` | ProviderType + factory |
| `app/ai_recommendation/providers/fallback.py` | FallbackAIProvider |
| `tests/test_providers.py` | 27 тестов |

## Изменённые файлы

| Файл | Изменение |
|---|---|
| `app/config.py` | Добавлены OPENAI_API_KEY, DEEPSEEK_API_KEY, MIMO_API_KEY, OLLAMA_BASE_URL, OLLAMA_MODEL, AI_FALLBACK_PROVIDERS |

## Тестирование

```
410 passed, 24 warnings, 0 failed
```

- 278 существующих тестов — все проходят
- 132 теста P1.x/P2.x — все проходят
- 27 тестов providers — все проходят
- 0 regressions

## Готовность к AI Agents

Provider система готова:
- Любой провайдер добавляется через ProviderType enum + base class
- Fallback обеспечивает отказоустойчивость
- Ollama позволяет тестировать локально без API
- Factory обеспечивает конфигурируемость через .env

## Субагенты

| Агент | actor_id | Роль |
|---|---|---|
| Architect Agent | `general-82` | Дизайн provider системы |
| Developer Agent | `general-83` | Реализация (6 файлов) |
| Test Agent | `general-84` | Верификация |
| Reviewer Agent | `general-85` | Ревью — APPROVE |

## Готовность к следующим этапам

P2.4 завершён. Provider система работает. Рекомендуемые следующие шаги:
- P2.5: Telegram /ai_suggest команда
- P2.6: Inline-клавиатуры для Telegram
- P2.7: AI-агенты для автономной работы
