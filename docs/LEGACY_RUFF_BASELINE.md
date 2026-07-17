# Legacy Ruff Baseline

Дата аудита: 2026-07-17

Команда:

```bash
RUFF_CACHE_DIR=/tmp/marketmind-ai-core-ruff \
.venv/bin/python -m ruff check app tests --output-format=json
```

Итог после P5 touched-file cleanup:

```text
total: 268
```

P5 не должен автоматически исправлять весь backlog. Новые и измененные P5-файлы должны проходить Ruff полностью.

## Распределение по кодам

| Код | Количество | Категория |
|---|---:|---|
| I001 | 73 | безопасные автоисправления |
| TC001 | 36 | публичные re-export / typing-only imports |
| UP017 | 35 | безопасные автоисправления |
| W293 | 33 | безопасные автоисправления |
| B033 | 19 | потенциальные runtime bugs |
| SIM117 | 16 | style-only |
| SIM105 | 12 | style-only |
| SIM102 | 7 | style-only |
| TC003 | 6 | typing-only imports |
| UP035 | 5 | безопасные автоисправления |
| UP037 | 4 | безопасные автоисправления |
| SIM108 | 3 | style-only |
| C408 | 3 | style-only / тестовый долг |
| F541 | 2 | потенциальные runtime bugs |
| UP045 | 2 | безопасные автоисправления |
| W292 | 2 | безопасные автоисправления |
| N817 | 2 | тестовый долг |
| E402 | 1 | потенциальный runtime/import-order debt |
| F402 | 1 | потенциальные runtime bugs |
| B905 | 1 | потенциальные runtime bugs |
| E401 | 1 | безопасные автоисправления |
| SIM103 | 1 | style-only |
| B007 | 1 | потенциальные runtime bugs |
| SIM110 | 1 | style-only |
| E713 | 1 | потенциальные runtime bugs |
| B008 | 1 | потенциальные runtime bugs |

## Горячие файлы

| Файл | Количество |
|---|---:|
| `app/task_intents.py` | 25 |
| `tests/test_pipeline.py` | 20 |
| `app/database.py` | 18 |
| `app/parsers/alt_sources.py` | 18 |
| `app/parsers/wildberries.py` | 10 |
| `app/ai_recommendation/db_approval.py` | 9 |
| `tests/test_approval_workflow.py` | 9 |
| `app/pipeline.py` | 8 |
| `tests/test_config.py` | 7 |
| `app/generic_scraper.py` | 6 |
| `app/telegram_card_handlers.py` | 6 |

## Безопасные автоисправления

Кандидаты на отдельный maintenance этап:

- `I001`;
- `UP017`;
- `W293`;
- `UP035`;
- `UP037`;
- `W292`;
- `E401`.

Их нельзя применять внутри P5 автоматически, потому что они затрагивают большое число legacy-файлов и могут смешать функциональный Card Editor с форматным шумом.

## Public Re-export / Typing Imports

Коды:

- `TC001`;
- `TC003`.

Часть таких исправлений безопасна, но для публичных re-export и runtime imports требуется ручная проверка, чтобы не сломать импортируемый API.

## Потенциальные Runtime Bugs

Коды:

- `B033`;
- `F541`;
- `F402`;
- `B905`;
- `B007`;
- `E713`;
- `B008`;
- частично `E402`.

Их стоит вынести в отдельный hardening этап после P5 или перед production release.

## Style-only

Коды:

- `SIM117`;
- `SIM105`;
- `SIM102`;
- `SIM108`;
- `SIM103`;
- `SIM110`;
- частично `C408`.

Низкий приоритет для P5.

## Тестовый долг

Коды:

- `N817`;
- часть `I001`;
- часть `C408`;
- часть `W293`.

Исправлять вместе с тестовым maintenance, не смешивая с функциональными миграциями.

## Решение для P5

1. Не выполнять массовый `ruff --fix`.
2. Не использовать `unsafe-fixes`.
3. Проверять новые и измененные P5-файлы отдельной Ruff-командой.
4. Полный Ruff оставить как известный baseline: 268 errors.
5. После P5 запланировать отдельный этап `P5.x Legacy Ruff Cleanup`.
