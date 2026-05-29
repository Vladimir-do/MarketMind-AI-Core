# Skillpack Triggers

Этот файл описывает «раздражители», которые помогают агенту вспомнить про базу скиллов не только на старте сессии, но и во время работы.

## 1. Marker-файл `.skillscheck`

Файл:

```text
project_skills/.skillscheck
```

Смысл:

- если агент видит этот файл, значит skillpack активен;
- `SKILLPACK.md` является главным входом;
- `skills_index.json` является машинным каталогом;
- `validate_skills.py` проверяет drift.

Что написать агенту:

```text
If `project_skills/.skillscheck` exists, treat the local skillpack as active.
Before implementing, reviewing, or changing architecture, read `project_skills/SKILLPACK.md`.
```

## 2. Keyword-trigger

Если запрос или файл касается этих слов, агент должен проверить skillpack:

```text
parser, parsing, marketplace, database, sqlite, sqlalchemy, telegram, bot,
fsm, aiogram, export, csv, xlsx, report, ai, llm, grok, claude,
resilience, retry, rate limit, circuit breaker, playwright, selenium,
config, env, yaml, json, deploy, cloud, api, fastapi, sandbox
```

Правило:

```text
If the user request or edited files mention any skill-trigger keyword, search
`project_skills/skills_index.json` before choosing an implementation pattern.
```

## 3. Комментарий в коде `@skills:`

В начало файла можно добавить:

```python
# @skills: database-async-sqlalchemy, resilience-marketplace-circuit
```

Или в Markdown:

```md
<!-- @skills: ai-provider-router, ai-json-extraction -->
```

Смысл:

- агент сразу видит, какие рецепты уже применены в файле;
- это помогает не переписывать архитектуру в другом стиле;
- это полезно как живая документация для людей.

Правило:

```text
When a file contains `@skills:`, read the listed skill IDs from
`project_skills/skills_database.md` before editing that file.
```

## 4. `pyproject.toml` marker

Если проект использует `pyproject.toml`, можно добавить секцию:

```toml
[tool.skillpack]
enabled = true
entrypoint = "project_skills/SKILLPACK.md"
index = "project_skills/skills_index.json"
validator = "project_skills/validate_skills.py"
```

Смысл:

- часть агентов просматривает `pyproject.toml` при старте;
- это еще одна стандартная точка входа;
- настройки можно читать машинно.

## 5. Проверочный prompt

После подключения напиши агенту:

```text
skillpack check
```

Ожидаемый ответ:

```text
SKILLPACK_LOADED
```

Если ответ другой, instruction-файл или marker не подхватился.

## 6. Session-close trigger

В конце каждой сессии с агентом срабатывает правило:

```text
Before the final answer, follow `project_skills/SESSION_UPDATE_PROTOCOL.md`.
Update the skillpack, create a pending proposal, or explicitly say that no reusable skills appeared.
```

Короткая команда-подсказка для пользователя:

```text
skillpack session close
```

Если пользователь написал это явно, агент обязан проверить сессию на новые reusable skills.

## Рекомендуемый набор

Для максимального шанса автоподхвата держи в проекте:

```text
project/
  AGENTS.md
  project_skills/
    .skillscheck
    SKILLPACK.md
    SKILL_TRIGGERS.md
    SESSION_UPDATE_PROTOCOL.md
    skills_index.json
    skills_database.md
```

Дополнительно добавляй `@skills:` в важные файлы, где уже применен конкретный рецепт.
