# Legacy Ruff Backlog

Дата: 2026-07-17

Полный Ruff по проекту остаётся диагностической проверкой. Массовый `ruff --fix` в L1.1 не выполнялся, чтобы не менять legacy-код вне текущего workflow.

## Summary

Последний известный diagnostic baseline: 267 legacy errors.

| Код | Количество | Модули | Риск | Автоисправление | Комментарий |
|---|---:|---|---|---|---|
| I001 | 73 | разные legacy modules | LOW | Да, но массово | Сортировка импортов может создать большой diff |
| TC001 | 35 | app/tests | LOW | Частично | Перенос imports под TYPE_CHECKING требует проверки runtime |
| UP017 | 35 | app/tests | LOW | Да | Замена datetime.UTC style, низкий риск |
| W293 | 33 | docs/templates/tests | LOW | Да | Whitespace-only |
| B033 | 19 | tests/app | MEDIUM | Нет | Duplicate set items могут скрывать ошибку теста |
| SIM117 | 16 | app | LOW | Частично | Nested with упрощается, но лучше точечно |
| SIM105 | 12 | app/tests | LOW | Да | suppress context |
| SIM102 | 7 | app | LOW | Да | Nested if |
| TC003 | 6 | app | LOW | Частично | TYPE_CHECKING для third-party imports |
| UP035 | 5 | app/tests | LOW | Да | Deprecated typing imports |
| UP037 | 4 | app/tests | LOW | Да | Quoted annotations |
| C408 | 3 | app/tests | LOW | Да | dict/list literal |
| SIM108 | 3 | app | LOW | Да | ternary |
| F541 | 2 | app | MEDIUM | Да | f-string без placeholders |
| N817 | 2 | app | LOW | Нет | Import alias naming может быть публичным контрактом |
| UP045 | 2 | app | LOW | Да | Optional syntax |
| W292 | 2 | docs/tests | LOW | Да | newline at EOF |
| B007 | 1 | app | MEDIUM | Частично | Неиспользуемая loop variable |
| B008 | 1 | app | MEDIUM | Нет | Function call default argument требует ручной проверки |
| B905 | 1 | app | MEDIUM | Да | strict zip |
| E401 | 1 | app | LOW | Да | Multiple imports on one line |
| E713 | 1 | app | LOW | Да | `not in` |
| F402 | 1 | app | MEDIUM | Нет | Import shadowing может быть runtime bug |
| SIM103 | 1 | app | LOW | Да | Return condition |
| SIM110 | 1 | app | LOW | Да | any/all |

## Recommendation

Разобрать backlog отдельным этапом:

1. Сначала whitespace/import-only safe fixes.
2. Потом потенциальные runtime bugs `B008`, `F402`, `B033`.
3. После каждого набора запускать полный pytest.
4. Не смешивать lint cleanup с product workflow changes.
