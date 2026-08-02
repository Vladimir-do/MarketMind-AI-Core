# P0.1 + P0.2 Report — First Safe Fix Batch

Дата: 2026-07-14
Проект: `MarketMind-AI-Core-main`

## Что было исправлено

### P0.1 — Критическая уязвимость в `allowed()`

**Проблема:** Функция `allowed()` в `app/bot.py:126` использовала `not ADMIN_IDS or user_id in ADMIN_IDS`. При пустом списке `ADMIN_IDS` (значение по умолчанию) выражение `not ADMIN_IDS` возвращало `True`, и функция разрешала доступ **любому** пользователю Telegram.

**Причина:** Классическая ошибка инверсии короткого замыкания — пустой список проходил проверку.

**Исправление:** Однострочная инверсия логики:
- **Было:** `return not ADMIN_IDS or user_id in ADMIN_IDS`
- **Стало:** `return bool(ADMIN_IDS) and user_id in ADMIN_IDS`

**Файлы:**
| Файл | Изменение |
|---|---|
| `app/bot.py:126` | Инверсия логики `allowed()` |
| `tests/test_bot_helpers.py:6,23` | Добавлен `allowed` в импорты |
| `tests/test_bot_helpers.py:959-984` | 4 теста в `AllowedAccessTests` |

**Тесты:**
1. `test_empty_admin_ids_denies_access` — пустой список → `False`
2. `test_user_in_admin_ids_allows_access` — пользователь в списке → `True`
3. `test_user_not_in_admin_ids_denies_access` — пользователь не в списке → `False`
4. `test_allowed_does_not_leak_admin_ids` — тип возврата `bool`, без утечки секретов

### P0.2 — Неатомарная запись `record_scrape_attempt`

**Проблема:** Метод `record_scrape_attempt()` в `app/database.py:436-438` коммитил `ScrapeAttempt` в сессии A, затем вызывал `record_blocked_pattern()` в **отдельной** сессии B. При ошибке во второй сессии первая уже была закоммичена — некonsистентное состояние.

**Причина:** Два независимых INSERT в разных транзакциях без координации.

**Исправление:** `BlockedPattern` добавляется в ту же сессию, что и `ScrapeAttempt`, с единым `await s.commit()`. При ошибке — полный rollback.

**Файлы:**
| Файл | Изменение |
|---|---|
| `app/database.py:409-454` | BlockedPattern перенесён в ту же сессию |
| `tests/test_database.py:320-382` | 2 regression-теста |

**Тесты:**
1. `test_record_scrape_attempt_writes_both_rows_atomically` — обе записи в одной транзакции
2. `test_record_scrape_attempt_rolls_back_when_blocked_pattern_fails` — при ошибке BlockedPattern весь transaction откатывается

## Какие субагенты работали

| Агент | actor_id | Роль |
|---|---|---|
| Security Fix Agent | `general-16` | Исправил `allowed()`, добавил 4 теста |
| Database Fix Agent | `general-17` | Сделал `record_scrape_attempt` атомарным, добавил 2 теста |
| Test Agent | `general-18` | Read-only анализ покрытия |
| Reviewer Agent | `general-19` | Ревью обоих патчей |

## Решения Reviewer Agent

| Патч | Вердикт | Обоснование |
|---|---|---|
| P0.1 | **APPROVE** | Корневая причина исправлена, минимальные изменения, тесты покрывают все кейсы, обратно совместим |
| P0.2 | **APPROVE** | Атомарность подтверждена, rollback работает, JSONL остаётся вне транзакции (по设计), обратно совместим |

## Результаты тестов

```
274 passed, 24 warnings, 14 subtests passed in 19.14s
```

- 268 оригинальных тестов — все проходят
- 6 новых тестов — все проходят
- Нет regressions

## Какие проблемы остались

- При деплое с пустым `ADMIN_IDS` бот будет **блокировать всех** — операторы должны задать `ADMIN_IDS` в `.env`
- JSONL-записи BlockedPattern остаются вне транзакции (fire-and-forget) — это осознанное решение, не проблема

## Что рекомендуется делать следующим

Следующий безопасный этап — **P0.4**: включить WAL mode для SQLite (`PRAGMA journal_mode=WAL`). Это однстрочное изменение в `Database.init()`, которое снижает contention при конкурентном чтении/записи.
