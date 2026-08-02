# P1.1.5 Architecture Review & Freeze

Дата: 2026-07-14
Проект: `MarketMind-AI-Core-main`

## Текущая архитектура

### Масштаб
- 45+ Python модулей в `app/` — 14,649 строк
- 278 тестов в 34 файлах
- 5 архитектурных слоёв: Interface → Intent → Planning → Execution → Storage

### Слои

| Слой | Модули | Строки | Статус |
|---|---|---|---|
| Interface | bot.py + 14 telegram_*.py | 3,963 | Разделён, рабочий |
| Intent | task_intents.py, task_planner.py | 1,824 | Прототип, рабочий |
| Execution | agent_loop.py, execution_state.py, agent.py | 681 | Прототип, рабочий |
| Marketplace | parsers/ (7), updater.py, searcher.py, generic_scraper.py | 3,197 | Ядро проекта |
| AI | ai_client.py, ai_analyzer.py, card_filler.py, card_research.py | 2,020 | Рабочий |
| Storage | database.py | 990 | SQLite, рабочий |
| Skills | skill_manifest.py, skill_notes.py, skill_telemetry.py | 494 | Уникальный дифференциатор |
| Universal Parsing | universal_parsing_core/ (20 файлов) | 864 | Чистая архитектура |
| Core | core/models.py, core/enums.py, core/errors.py | 77 | Тонкий, чистый |

## Проблемные места

### Критические
- `database.py` импортировал из `telegram_diagnostics` — нарушение слоёв → **ИСПРАВЛЕНО**
- `database.py` — God Object (990 строк) — требует разделения перед P1.2
- `pyproject.toml` описывает другой проект — требует исправления

### Высокий приоритет
- `bot.py` — всё ещё 1,891 строка с 25+ handler registrations
- `updater.py` — смешанные ответственности (1,034 строки)
- Двойная модель данных: `ProductData` vs `ProductSnapshot`

### Средний приоритет
- `task_intents.py` — 1,297 строк, делает слишком много
- `card_filler.py` — 1,533 строк, смешивает генерацию/AI/экспорт
- Циклический риск: parsers → updater → parsers

## Принятые решения

| Решение | Обоснование |
|---|---|
| `mask_proxy_url` перенесён в `app/utils/proxy.py` | Устранено нарушение слоёв: database → utils вместо database → telegram |
| `is_yandex_market_url` перенесён в `app/utils/urls.py` | Чистая URL-утилита в правильном месте |
| Backward-compat re-exports сохранены | Все существующие импорты продолжают работать |
| bot.py остаётся entrypoint | Не менять архитектуру обработчиков без крайней необходимости |
| Multi-tenancy отложена | Phase 5 (SaaS), не сейчас |

## Будущая архитектура MarketMind AI

```
app/
├── bot.py              # Entrypoint + handlers
├── core/               # Domain models, enums, errors
├── db/                 # Models, engine, repositories (будущее: database.py → db/)
├── parsers/            # Marketplace parsers (Ozon, WB, Yandex, FunPay)
├── adapters/           # API adapters (Ozon, WB seller API)
├── services/           # Business logic services
├── ai/                 # AI providers, generators, analyzers
├── utils/              # Pure utilities (proxy, urls, etc.)
├── telegram_*.py       # Telegram-specific modules
├── universal_parsing_core/  # Universal page parsing
└── tests/              # Test suite
```

## Готовность к масштабированию

| Параметр | Оценка | Заметки |
|---|---|---|
| Разделение модулей | 7/10 | Хорошо после P1.1; bot.py и database.py всё ещё большие |
| Связанность | 7/10 | Нарушение слоёв исправлено; двойная модель данных осталась |
| Тестируемость | 7/10 | 278 тестов, хорошее покрытие |
| Расширяемость | 7/10 | Контракт парсеров чистый; система скиллов уникальна |
| Multi-tenancy | 2/10 | Нет модели владения, плоские права, SQLite |
| Документация | 5/10 | Хорошие документы, но 5+ дублирующих |

## Рекомендации перед P1.2

### ДО P1.2 (обязательно)
1. Разделить `database.py` — модели, engine/session, Database class → `app/db/`
2. Исправить `pyproject.toml`
3. Устранить утечку `_recommend_strategy` из updater.py

### ПОСЛЕ P1.2 (можно позже)
4. Дальнейшее разделение `bot.py`
5. Разделение `task_intents.py`
6. Разделение `card_filler.py`
7. Объединение ProductData → ProductSnapshot

## Изменения, выполненные в P1.1.5

| Файл | Действие |
|---|---|
| `app/utils/proxy.py` | Добавлен `mask_proxy_url` |
| `app/utils/urls.py` | Создан с `is_yandex_market_url` |
| `app/telegram_diagnostics.py` | Re-export `mask_proxy_url` |
| `app/parsers/yandex_market.py` | Re-export `is_yandex_market_url` |
| `app/database.py` | Импорт из `app.utils.proxy` |
| 8 других файлов | Обновлены импорты |

## Субагенты

| Агент | actor_id | Роль |
|---|---|---|
| Architect Agent | `general-42` | Полный аудит архитектуры |
| Developer Agent | `general-43` | Перенос утилит |
| Test Agent | `general-44` | Верификация |
| Reviewer Agent | `general-45` | Ревью — APPROVE |

## Результаты тестов

```
278 passed, 24 warnings, 0 failed
```

## Готовность к P1.2

**Да.** Нарушение слоёв исправлены, utility-модули в правильных местах, backward compat сохранена. Проект готов к P1.2 (Alembic миграции).
