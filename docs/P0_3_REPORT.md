# P0.3 Report — Proxy Credential Masking

Дата: 2026-07-14
Проект: `MarketMind-AI-Core-main`

## Задача

Прекратить хранение прокси-credentials в открытом виде в SQLite и JSONL. Прокси-URL содержат встроенные credentials (например, `socks5://user:pass@ip:port`) и ранее сохранялись как есть в таблицы `scrape_attempts`, `blocked_patterns` и в JSONL-файлы.

## Причина

Каждый прокси-URL с credentials, записанный в БД или JSONL, представлял собой утечку секретов при доступе к файлам данных.

## Что было исправлено

Добавлен вызов существующей функции `mask_proxy_url()` из `app/telegram_diagnostics.py` на входе двух функций записи в БД:

- `record_scrape_attempt()` — маскирование перед любой записью (покрывает 4 точки записи: 2 DB + 2 JSONL)
- `record_blocked_pattern()` — маскирование перед построением payload (покрывает 2 точки записи: 1 DB + 1 JSONL)

**Итого:** 2 строки кода закрывают все 6 точек утечки.

## Изменённые файлы

| Файл | Изменение |
|---|---|
| `app/database.py:12` | Добавлен импорт `from app.telegram_diagnostics import mask_proxy_url` |
| `app/database.py:392` | `proxy = mask_proxy_url(proxy) if proxy else None` в `record_scrape_attempt()` |
| `app/database.py:521` | `proxy = mask_proxy_url(proxy) if proxy else None` в `record_blocked_pattern()` |
| `tests/test_database.py` | Добавлен класс `ProxyMaskingTests` с 4 тестами |

## Добавленные тесты

| Тест | Сценарий |
|---|---|
| `test_record_scrape_attempt_masks_proxy_credentials` | `socks5://user:pass@host:port` → `socks5://***@host:port` |
| `test_record_blocked_pattern_masks_proxy_credentials` | То же для BlockedPattern |
| `test_record_scrape_attempt_preserves_no_credential_proxy` | `socks5://host:port` без credentials → без изменений |
| `test_record_scrape_attempt_none_proxy_stays_none` | `None` → `None` (guard работает) |

## Субагенты

| Агент | actor_id | Роль |
|---|---|---|
| Architect/Audit Agent | `general-20` | Read-only аудит, план реализации |
| Developer Agent | `general-21` | Реализация патча + тесты |
| Test Agent | `general-22` | Независимая верификация |
| Reviewer Agent | `general-23` | Ревью патча |

## Решение Reviewer Agent

**APPROVE** — все 6 путей записи замаскированы, утечек нет, regressions нет, обратная совместимость сохранена.

## Результаты тестов

```
278 passed, 24 warnings, 14 subtests passed
```

- 274 оригинальных тестов — все проходят
- 4 новых теста — все проходят
- 0 regressions

## Оставшиеся риски и технический долг

- Существующие строки в БД содержат plaintext credentials (одноразовая миграция не обязательна, но рекомендуется)
- JSONL-файлы на диске содержат старые записи с credentials (новые записи замаскированы)
- Пустая строка `""` в proxy проходит guard `if proxy` без маскирования (нет credentials — нет риска)

## Следующий этап

P0.4 — включить WAL mode для SQLite (`PRAGMA journal_mode=WAL`).
