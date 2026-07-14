# P1.1 Report — bot.py Module Split

Дата: 2026-07-14
Проект: `MarketMind-AI-Core-main`

## Старая архитектура

`app/bot.py` — 2984 строки, God Module:
- Все 35+ команд Telegram
- NLU роутер
- URL валидация
- Scraping preflight логика
- Генерация карточек
- Conversation patterns
- Marketplace formatting
- FSM состояния
- Модульные глобалы (bot, db, parser_lock, task_planner)

## Новая архитектура

```
bot.py (1891 строк — entrypoint, handlers, FSM, globals)
├── telegram_url_utils.py (54) — URL валидация, извлечение
├── telegram_text_utils.py (296) — NLU текстовые хелперы
├── telegram_conversation.py (88) — conversation patterns
├── telegram_marketplace_utils.py (79) — marketplace formatting
├── telegram_card_handlers.py (251) — генерация карточек
├── telegram_scraping.py (489) — scraping preflight + handlers
├── telegram_messages.py (145) — форматирование (существовал)
├── telegram_exports.py (58) — экспорт (существовал)
├── telegram_ai_reports.py (63) — AI отчёты (существовал)
├── telegram_card_tasks.py (57) — card tasks (существовал)
├── telegram_card_research.py (15) — research (существовал)
├── telegram_diagnostics.py (87) — диагностика (существовал)
└── telegram_humanize.py (219) — humanize (существовал)
```

bot.py: 2984 → 1891 (−1093 строки, −37%)

## Изменённые файлы

| Файл | Действие |
|---|---|
| `app/telegram_url_utils.py` | Создан — 5 функций |
| `app/telegram_text_utils.py` | Создан — 19 функций/констант |
| `app/telegram_conversation.py` | Создан — 3 элемента |
| `app/telegram_marketplace_utils.py` | Создан — 6 функций |
| `app/telegram_card_handlers.py` | Создан — 5 функций |
| `app/telegram_scraping.py` | Создан — 14 функций |
| `app/bot.py` | Модифицирован — импорты + re-exports |

## Тесты

```
278 passed, 24 warnings, 0 failed
```

Все существующие тесты проходят без изменений. Новые тесты не требуются — рефакторинг, не изменение поведения.

## Кроссплатформенность

Все новые модули используют:
- pathlib.Path для путей
- async/await для операций I/O
- Нет платформозависимого кода
- Lazy imports для избежания циклических зависимостей

## Риски

| Риск | Серьёзность | Митигация |
|---|---|---|
| Lazy import в telegram_scraping.py | LOW | Вызывается только при реальном использовании |
| Изменение сигнатур (Step 6) | LOW | Только добавление kwargs, не изменение |
| Тесты патчат bot_module | LOW | Re-exports в bot.py сохраняют совместимость |

## Субагенты

| Агент | actor_id | Шаг |
|---|---|---|
| Architect Agent | `general-34` | Анализ |
| Developer Agent (Step 1) | `general-35` | telegram_url_utils |
| Developer Agent (Step 2) | `general-36` | telegram_text_utils |
| Developer Agent (Step 3) | `general-37` | telegram_conversation |
| Developer Agent (Step 5) | `general-38` | telegram_marketplace_utils |
| Developer Agent (Step 6) | `general-39` | telegram_card_handlers |
| Developer Agent (Step 4) | `general-40` | telegram_scraping |
| Reviewer Agent | `general-41` | Ревью — APPROVE |

## Готовность к следующим этапам

P1.1 завершён. Рекомендуемые следующие шаги:
- P1.2: Alembic миграции
- P1.3: Объединение OzonParser и OzonUpdater
- P1.4: Извлечение общих утилит
