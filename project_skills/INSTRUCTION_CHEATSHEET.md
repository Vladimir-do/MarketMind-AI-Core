# Шпаргалка: как подключить скиллы к нейронке

## Главная идея

Нейронка обычно не видит папку со скиллами сама по себе. Она подхватывает ее через instruction-файл, который конкретный инструмент читает автоматически.

Минимальный переносимый комплект:

```text
project/
  project_skills/
    SKILLPACK.md
    skillpack.json
    skills_index.json
    skills_database.md
    validate_skills.py
    INSTRUCTION_CHEATSHEET.md
```

## Как выбрать instruction-файл

| Где работаешь | Куда положить инструкцию | Что взять из `project_skills/install_snippets/` |
|---|---|---|
| Codex / OpenAI coding agent | `AGENTS.md` в корень проекта | `AGENTS.md` |
| Claude Code | `CLAUDE.md` в корень проекта | `CLAUDE.md` |
| Cursor | `.cursor/rules/project-skills.md` | `cursor-project-skills.md` |
| GitHub Copilot | `.github/copilot-instructions.md` | `copilot-instructions.md` |
| Windsurf | `.windsurfrules` в корень проекта | `windsurfrules` |
| ChatGPT / Claude / Gemini в браузере | вручную загрузить/вставить | `SKILLPACK.md` + `skills_index.json` |

## Самый простой вариант

Если не знаешь, какой инструмент будет использоваться, положи в корень проекта `AGENTS.md`.

```text
project/
  AGENTS.md
  project_skills/
```

Многие coding agents читают `AGENTS.md`. Если конкретный инструмент его не читает, файл просто не помешает.

## Усиленный триггер

Внутри `project_skills/` уже есть marker-файл:

```text
project_skills/.skillscheck
```

Если агент или инструкция видит этот файл, skillpack считается активным.

Дополнительные триггеры описаны здесь:

```text
project_skills/SKILL_TRIGGERS.md
```

Самые полезные:

- keyword-trigger: если запрос касается `parser`, `database`, `telegram`, `AI`, `export`, `resilience`, `playwright`, агент должен искать skill в `skills_index.json`;
- code marker: комментарий `# @skills: ai-provider-router, database-async-sqlalchemy` в начале файла;
- `pyproject.toml` marker: секция `[tool.skillpack]`.

## Как проверить, что инструкция подхватилась

Во всех шаблонах есть тестовая фраза.

Напиши нейронке:

```text
skillpack check
```

Если она ответит:

```text
SKILLPACK_LOADED
```

значит instruction-файл работает.

Если не ответила так:

1. Проверь, что файл лежит в правильном месте.
2. Проверь точное имя файла.
3. Перезапусти инструмент или открой проект заново.
4. Если это браузерная нейронка, автоподхвата нет: нужно загрузить `SKILLPACK.md` вручную.

## Как подключить в новый проект

1. Скопируй папку `project_skills/` в корень нового проекта.
2. Выбери instruction-файл по таблице выше.
3. Скопируй шаблон из `project_skills/install_snippets/` в нужное место.
4. Открой проект в нейронке/агенте.
5. Напиши `skillpack check`.
6. Если ответ `SKILLPACK_LOADED`, можно работать.

## Что должна делать нейронка после подключения

Правильное поведение:

- сначала читает `project_skills/SKILLPACK.md`;
- ищет нужные рецепты в `skills_index.json`;
- открывает подробности в `skills_database.md`;
- учитывает `dependencies` и `dependents`;
- не создает новый паттерн, если уже есть похожий skill;
- перед финальным ответом выполняет `SESSION_UPDATE_PROTOCOL.md`;
- после правок запускает `python project_skills/validate_skills.py`.

## Как заставить базу пополняться после каждой сессии

В skillpack уже добавлен протокол:

```text
project_skills/SESSION_UPDATE_PROTOCOL.md
```

В конце сессии агент должен сделать одно из четырех:

1. обновить существующий skill;
2. добавить новый skill;
3. создать pending proposal в `project_skills/session_updates/`;
4. явно сказать: новых reusable skills не появилось.

Если агент забыл, напиши:

```text
skillpack session close
```

Это ручной раздражитель, который запускает проверку сессии на новые рецепты.

## Когда использовать ручную загрузку

Ручная загрузка нужна, если ты работаешь:

- в обычном ChatGPT/Claude/Gemini без доступа к файлам проекта;
- в веб-интерфейсе, где нельзя читать локальную папку;
- с моделью через API без файлового контекста.

В этом случае загрузи или вставь:

1. `project_skills/SKILLPACK.md`
2. `project_skills/skills_index.json`
3. нужные куски из `project_skills/skills_database.md`

## Быстрая диагностика

| Симптом | Что значит | Что сделать |
|---|---|---|
| Нейронка не отвечает `SKILLPACK_LOADED` | instruction не прочитан | проверить имя и место файла |
| Нейронка знает про `SKILLPACK.md`, но не использует skills | слабая инструкция | добавить правило "Before coding, read SKILLPACK.md" |
| Нейронка ссылается на несуществующий skill | drift или hallucination | запустить `validate_skills.py` и проверить `skills_index.json` |
| JSON и Markdown разъехались | база обновлялась вручную | запустить валидатор и синхронизировать ID |

## Рекомендуемый стандарт для твоих проектов

Для каждого нового проекта держи такую структуру:

```text
project/
  AGENTS.md
  project_skills/
    SKILLPACK.md
    skillpack.json
    skills_index.json
    skills_database.md
    missing_skills_prioritized.yaml
    architecture_review.md
    validate_skills.py
    INSTRUCTION_CHEATSHEET.md
    install_snippets/
```

Такой формат наиболее переносимый: его можно использовать с coding agents, IDE-ассистентами, локальными LLM и браузерными моделями.
