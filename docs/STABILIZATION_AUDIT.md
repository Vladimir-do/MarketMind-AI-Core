# STABILIZATION_AUDIT.md — MarketMind AI

> Дата аудита: 2026-08-09
> Тип: READ-ONLY аудит. Ничего не изменено, не исправлено, не отрефакторено.
> Коммит на момент аудита: `8c434c7`
> Метод: прочитаны 4 предыдущих аудита (2026-07-12 — 2026-07-17, см. §0), затем текущее состояние
> кода перепроверено напрямую (чтение файлов + `graphify query/explain`), так как с последнего
> аудита прошло ~3 недели активной разработки (P3.6–P3.9, P4, P5, P6, domain events, timeline,
> content pipeline, competitor analysis, SEO semantic core).

---

## 0. Что уже было известно (и что из этого устарело)

В `docs/` уже существует 5 предыдущих аудитов/инвентаризаций проекта:
`ARCHITECTURE_REPORT.md`, `ARCHITECTURE_CONFLICTS.md`, `PROJECT_INVENTORY.md` (все 2026-07-12),
`PROJECT_AUDIT.md` (2026-07-14), `CODEX_CURRENT_STATE_AUDIT.md`/`WORKTREE_STABILIZATION_REPORT.md`/
`P4_PLATFORM_HARDENING_AUDIT.md`/`LEGACY_RUFF_BACKLOG.md` (2026-07-14 — 2026-07-17).

Часть их выводов **уже неверна** и не должна больше повторяться:

| Старое утверждение | Текущее состояние |
|---|---|
| «FastAPI отсутствует» | Есть полноценное FastAPI-приложение (`app/web/app.py`, 12 роутеров, 40 Jinja2-шаблонов) |
| «`parsers/` vs `adapters/` — неясная разница, возможное дублирование» | Разница ясна: `app/adapters/*` — тонкая обёртка над `app/parsers/*`/`app/updater.py`, конвертирующая в `ProductSnapshot`. Дублирования логики парсинга нет |
| «`Database.init()` виснет на старте» | Исправлено через `app/compat/aiosqlite_patch.py` (монкипатч, не root-fix — см. D4) |
| «Нет repository-layer» | Появился частично (`ProductEditorRepository`, `DomainEventRepository`, `TimelineRepository`), но применяется непоследовательно — см. D11 |
| «`app/database.py` — слишком большой модуль» | Подтверждено, не исправлено, вырос дальше (1438 строк) — см. D9 |
| «Нет проекта/магазина как сущности» | Реализовано (`ClientProject`, весь `app/web/routes/projects.py`) |
| «Нет редактора карточек» | Реализовано (`app/editor/` + `ProductCardEditorService`) |

Остальные пункты старых аудитов (секреты в `.env`, runtime-артефакты в репозитории, разрозненная документация) не перепроверялись в этом аудите — см. §7 для новых находок по этим темам.

---

## 1. Current architecture

```
                    ┌─────────────────────────────────────────────┐
                    │              ДВА НЕЗАВИСИМЫХ UI              │
                    │  Telegram Bot (app/bot.py + telegram_*.py)   │
                    │  Web App (FastAPI, app/web/routes/*.py)      │
                    └───────────────┬───────────────┬─────────────┘
                                    │               │
                    ┌───────────────▼──┐   ┌────────▼──────────────┐
                    │  Bot: НЕТ service │   │  Web: сервисы есть,   │
                    │  layer для чтения │   │  но непоследовательно │
                    │  (прямой SQLAlch- │   │  (ProjectService,     │
                    │  emy в handlers)  │   │  EditorService, ...)  │
                    └───────────────┬──┘   └────────┬──────────────┘
                                    │               │
                    ┌───────────────▼───────────────▼─────────────┐
                    │         app/database.py (1438 строк)         │
                    │  15 ORM-моделей + CRUD + JSONL-логи +        │
                    │  adaptive cooldown/circuit-breaker engine     │
                    │  (god object, см. D9)                        │
                    └───────────────┬───────────────────────────────┘
                                    │
                    ┌───────────────▼───────────────────────────────┐
                    │  Parsers (Ozon/WB/Yandex/FunPay) +            │
                    │  Adapters (тонкая обёртка) +                  │
                    │  LLM (2 независимые абстракции, см. D16)      │
                    └─────────────────────────────────────────────┘
```

Ключевое архитектурное наблюдение, не зафиксированное в старых аудитах: в проекте существуют
**два параллельных, независимо развивающихся конвейера** генерации карточки товара:

1. **Legacy/операторский** (Telegram + CLI): `worker.py` → `updater.py`/`parsers/*` → `database.py`
   (прямой доступ) → `card_filler.py` + `ai_client.py` (простой LLM-вызов) → `exporter.py`/`reporter.py`.
2. **Современный/клиентский** (Web, client projects): `projects/imports.py` → `ProjectService` →
   `ai_recommendation/*` (структурированный LLM-слой с fallback) → `editor/service.py`
   (drafts/versions с optimistic locking) → `DatabaseApprovalQueue` → export/report services.

Они делят только парсеры и ORM-модели. Любое исправление бизнес-логики в одном конвейере
(например, конвертация snapshot→UnifiedProduct, обработка ошибок LLM) **не распространяется**
на другой — см. D12, D16, D17.

---

## 2. Project map

| Слой | Модули |
|---|---|
| Входные точки | `app/main.py` (CLI), `app/bot.py` (Telegram), `app/web/app.py` (FastAPI), `mcp_server.py`, `deploy_cloud.py` |
| UI (web) | `app/web/routes/*.py` (11 роутеров), `app/web/templates/*` (40 файлов) |
| UI (bot) | `app/bot.py` + 20 `app/telegram_*.py` модулей |
| Services | `app/projects/service.py`, `app/editor/service.py`, `app/effective_card/service.py`, `app/products/analyzer.py`, `app/timeline/`, `app/content_pipeline/`, `app/competitor_analysis/`, `app/ai_recommendation/` |
| Domain | `app/domain/events/*` (чистый, см. §Dependency violations) |
| Repositories (частично) | `app/editor/repository.py`, `app/domain/events/repository.py`, `app/timeline/repository.py` |
| Database | `app/database.py` (1438 строк, god object), `app/compat/aiosqlite_patch.py` (монкипатч) |
| Migrations | `alembic/` — 10 линейных миграций, без ветвлений |
| Parsers | `app/parsers/{ozon,wildberries,yandex_market,funpay,alt_sources,router,base,universal(dead)}.py` |
| Adapters | `app/adapters/{ozon,wb}.py` — обёртки над parsers/updater |
| LLM | `app/ai_client.py` (legacy) + `app/ai_recommendation/providers/*` (структурированный, с fallback) |
| Config | `app/config.py` (не единственный источник — см. D5) |
| Тесты | `tests/` — 90+ файлов, ~823 теста, в основном реального поведения (см. §8) |
| CI | `.github/workflows/ci.yml` (ruff + pytest, mypy установлен но не запускается — см. D18) |

Крупнейшие файлы (потенциальные god objects):

| Файл | Строк |
|---|---|
| `app/bot.py` | 1872 |
| `app/card_filler.py` | 1533 |
| `app/web/routes/projects.py` | 1470 (51 endpoint) |
| `app/database.py` | 1438 |
| `app/task_intents.py` | 1297 |
| `app/updater.py` | 1049 |

---

## 3. Critical user flows

### Сценарий A — Web / Client Project (современный путь)

```
import → save → analyze → generate → validate → accept proposal → export
```

| Шаг | Файлы/модули |
|---|---|
| import | `POST /api/projects/{id}/imports`, `/imports/preview` — `app/web/routes/projects.py:540-635`, `app/projects/imports.py`, `app/pipeline.py` (ImportPipeline) |
| save | `app/projects/service.py` (ProjectService), таблицы `ClientProject`/`ClientProjectFile`/`ProjectProduct` в `app/database.py` |
| analyze | `/market-analysis` (`projects.py:635`), SEO/semantic-core (`app/effective_card/service.py`, `app/products/analyzer.py`), конкуренты (`app/competitor_analysis/*`) |
| generate | AI-предложения — `app/ai_recommendation/job_queue.py` + `providers/*`; черновики — `ProductCardEditorService.create_draft` (`app/editor/service.py`) |
| validate | quality-preview — `app/effective_card/service.py`, `projects.py:1014` |
| **accept proposal** | `suggestions.py:approve_suggestion` → **`DatabaseApprovalQueue.apply_approved()`** — здесь находится P0-дефект D1 |
| export | `ProjectExportService`/`ClientDeliveryReportService`, `projects.py:1136-1258` |

### Сценарий B — Telegram/CLI (операторский, legacy путь)

```
add → save → analyze → generate → (no formal validate) → (no formal accept) → export
```

| Шаг | Файлы/модули |
|---|---|
| add | `/add`, `--enrich` — `app/worker.py:worker_add_urls` → `app/updater.py`/`app/parsers/*` |
| save | `app/database.py:save_product()` — здесь находится race-условие D2 |
| analyze | `/analyze`, `/deep_analyze` — `app/ai_analyzer.py`, `app/agent.py` (через `app/ai_client.py` — **другой** LLM-слой, чем в сценарии A) |
| generate | `/ozon_card` — `app/card_filler.py` + `app/ai_client.py` |
| validate | Отсутствует как формальный шаг — только ручной просмотр оператором в Telegram |
| accept | Отсутствует формальная approval-очередь — расхождение со сценарием A |
| export | `/export_csv`, `/export_excel`, `/report` — `app/exporter.py`, `app/reporter.py` |

**Наблюдение:** сценарии A и B — это по сути одна и та же бизнес-задача (превратить сырые данные
товара в карточку маркетплейса), реализованная дважды, с разной степенью зрелости
(A имеет approval/versioning/validation, B — нет). Это не баг, но架构ческий факт, который стоит
учитывать при планировании: любая новая бизнес-политика («не публиковать карточку без проверки
X») должна быть внедрена в оба конвейера отдельно.

---

## 4. Dependency violations

Ожидаемая схема: `UI → API → Services → Domain → Repositories/Integrations`.

| # | Нарушение | Файлы | Серьёзность |
|---|---|---|---|
| D13 | Telegram-бот вообще не имеет service-слоя для чтения: прямой `SQLAlchemy`/`app.database` импорт и inline-запросы в обработчиках команд | `app/bot.py:14,17,1055-1104,1146-1154,1333-1338,1377` (`cmd_list`, `cmd_status`, `_broadcast_changes`) | **P2** |
| D14 | API→DB в обход service-слоя: `product_detail.py` — почти все хелперы открывают сессию напрямую; 4 места в `projects.py` (экспорт/отчёт по одному id) в обход уже существующих `ProjectExportService`/`ClientDeliveryReportService`; `reports.py` — прямой `select(ApprovalRecord.status)`; дублирующийся inline `session.get(JobRecord, ...)` в `content_pipeline/routes.py` и `competitor_analysis/routes.py` | см. список выше | **P2** |
| D25 | `app/domain/events/builders.py` импортирует `app.database.Product` не под `TYPE_CHECKING` и делает `isinstance(source, Product)` — минорная утечка infrastructure в domain-модуль, который в остальном чист | `app/domain/events/builders.py:7,92` | **P3** |
| D11 | Repository-паттерн применён непоследовательно: реален для editor/domain-events/timeline, но `ProjectService`, `CompetitorSnapshotStore`, `DatabaseApprovalQueue`, `job_queue.py` обращаются к SQLAlchemy напрямую и одновременно исполняют роль repository | `app/projects/service.py`, `app/competitor_analysis/store.py`, `app/ai_recommendation/db_approval.py` | **P2** |

**Позитивная находка:** Jinja2-шаблоны (`app/web/templates/*`) полностью чисты от прямого
доступа к БД — весь проброс данных идёт через route handlers. UI→DB нарушений на уровне
шаблонов не найдено.

---

## 5. Critical defects

> **Исправление после начала работы над P0 #1 (2026-08-09):** при реализации фикса для D1
> выяснилось, что первоначальная оценка была ошибочной — см. запись в конце §5 (D1, теперь P3).
> Ниже фиксирую как было (для прозрачности процесса), так и исправленный вывод.

### P0 — ломает основной сценарий/данные

*(пусто — единственный кандидат, D1, при более глубокой проверке оказался не P0; см. ниже)*

### P1 — высокая вероятность регрессии

**D2. Гонка в `Database.save_product()`.** Check-then-act без обработки `IntegrityError`:
два конкурентных парсинга одного URL оба видят «товара нет» и оба делают `INSERT` — второй
падает необработанным исключением на `UNIQUE(url_hash)`. `app/database.py:1373-1438`. Нет теста
на конкурентный вызов (T3).

**D3. Тихое проглатывание ошибок записи телеметрии на уровне DEBUG.**
`record_blocked_pattern` и оба JSONL-writer'а (`app/database.py:993,1007,1018`) оборачивают
**весь** `try`-блок (включая сам `commit()`) в `except Exception as e: logger.debug(...)`.
DEBUG обычно выключен в проде → сбой записи полностью невидим. Эти данные напрямую питают
adaptive cooldown/circuit-breaker (`get_marketplace_health`) — деградация антибот-эвристики
происходит незаметно для оператора.

**D4. Хрупкий монкипатч `app/compat/aiosqlite_patch.py`.** Патчит приватные атрибуты
`aiosqlite.core.Connection` (`_connect`, `_execute`, `close`), заменяя wake-up на busy-poll
каждые 1мс; использует устаревший `asyncio.get_event_loop()`; нет проверки версии `aiosqlite`.
Это единственный фикс исходного зависания `Database.init()` — при обновлении `aiosqlite` патч
может либо перестать применяться тихо, либо упасть на `AttributeError` при подключении, вернув
исходный hang-баг. Нет теста, привязанного к конкретной версии зависимости (T6).

**D5. Расхождение дефолта `AI_PROVIDER`.** `app/config.py:115` — дефолт `"grok"`.
`app/ai_recommendation/providers/factory.py:81` читает `os.getenv("AI_PROVIDER", "ollama")`
напрямую, в обход `config.py`, с **другим** дефолтом. В зависимости от того, какой код-путь
инициализирует провайдера, поведение при отсутствующей переменной окружения различается.

**D6. `ProviderType.claude` сломан в фабрике.** Определён в `factory.py:21` (модель, ключ),
но отсутствует в `_PROVIDER_BASE_URLS` (`factory.py:48-52`) и `_DEFAULT_BASE_URLS`
(`openai_compatible.py:26-30`). При `AI_PROVIDER=claude` создаётся провайдер с `base_url=""`,
`is_available()` всегда `False`, даже при валидном `ANTHROPIC_API_KEY`. Не покрыто тестами
(`tests/test_providers.py` тестирует только deepseek/ollama/openai/bogus) — T1.
**Замечание:** grok/gemini работают, сломан только claude.

**D7. Синхронный AI-вызов внутри HTTP-запроса.** `api_queue_project_seo_suggestions`
(`app/web/routes/projects.py:883-965`) `await`-ит `process_project_seo_suggestion_job`
напрямую внутри обработчика, а не через `BackgroundTasks`, в отличие от идентичного по сути
эндпоинта на уровне продукта (`product_detail.py:405`, который использует `BackgroundTasks`
корректно). Запрос блокируется на полный AI round-trip; при однопроцессном деплое это может
задерживать обработку других запросов.

**D8. Замена `Database` на лету в `system.py:restore_backup`.**
`app/web/routes/system.py:39-49` — при восстановлении бэкапа диспозится текущий engine и
`request.app.state.db` заменяется на новый `Database()` посреди обработки запроса. Другой
одновременный запрос, держащий старую ссылку, может обратиться к disposed engine.
Правдоподобная гонка при однопроцессном деплое (admin-операция, но потенциально при активном
трафике).

### D1 — пересмотрено: P0 → P3

При начале работы над фиксом выяснилось, что `ApprovalEventBuilder.build()`
(`app/domain/events/builders.py:129-178`) уже трактует «применено» как **отдельную,
независимую от `status` ось**: событие `approval.applied` строится из `record.applied_at is
not None`, а не из `record.status`. Это осознанный, рабочий дизайн: `status` отслеживает решение
проверяющего (`pending`/`approved`/`rejected`/`rolled_back`), `applied_at` — отдельно, было ли
решение применено. Реальный продакшен-путь применения — `mark_applied()`
(`app/ai_recommendation/db_approval.py:122-157`, вызывается из
`app/web/routes/suggestions.py:_apply_project_suggestion`) — работает по этой схеме корректно:
approve → apply → `applied_at` проставляется → domain-event строится верно → таймлайн
показывает это верно → повторное одобрение идемпотентно (короткое замыкание через сравнение
`before_value == requested_value` в `_apply_project_suggestion`).

Метод `apply_approved()` (изначально принятый за источник бага) **не вызывается из
продакшен-кода вообще** — только из `tests/test_approval_workflow.py`. Если бы `status` был
принудительно переведён в `"applied"`, это сломало бы существующую проверку
`record.status in {"approved", "rejected"}` в `ApprovalEventBuilder.build()` (строка 145) —
то есть внесло бы регресс в таймлайн там, где сейчас всё работает верно.

**Единственный оставшийся реальный (и низкоприоритетный) дефект:** расхождение сериализации
snapshot между `apply_approved()` (`str(current_value)`, `db_approval.py:201`) и `mark_applied()`
(без приведения типа) — затрагивает только неиспользуемый в проде метод. **Понижено до P3**,
см. D1' в §9 (пересчитано в итоговой сводке).

---

## 6. High-risk areas

Помимо P0/P1 из §5 — области, заслуживающие приоритетного внимания из-за частоты
использования/центральности (god-node по графу знаний):

- **`app/database.py`** (134 связи в графе, `UnifiedProduct`/`Product` — 139/81 связей) —
  самый связанный модуль проекта, при этом самый неоднородный по ответственности (D9).
- **`detect_task_intent()`/`StructuredTask`** (104/81 связей) — центральная точка NL-роутинга
  в Telegram-боте; архитектурно нормально для своей роли, но означает, что любой баг здесь
  влияет на весь бот.
- **LLM-провайдеры** — единственная точка входа для AI-функциональности в обоих сценариях (A и B);
  D5/D6 напрямую бьют по надёжности шага «generate».

---

## 7. Technical debt

| # | Проблема | Файлы | Серьёзность |
|---|---|---|---|
| D9 | `app/database.py` — god object: 15 ORM-моделей + connection lifecycle + generic CRUD + JSONL-логирование + полноценный adaptive cooldown/circuit-breaker engine (~280 строк scraper-бизнес-логики) в одном файле/классе | `app/database.py` | **P2** |
| D10 | Два параллельных механизма миграции: Alembic (чистый, линейный) vs. `_migrate_scrape_attempts` — ad-hoc ALTER-TABLE шим, до сих пор выполняющийся при каждом `Database.init()`. Ничто не гарантирует их синхронность | `app/database.py:621-682` | **P2** |
| D11 | Repository-паттерн непоследователен (см. §4/D11) | — | **P2** |
| D12 | Дублирование бизнес-логики: конвертация snapshot→`UnifiedProduct` независимо реализована дважды | `app/effective_card/service.py:200-225`, `app/ai_recommendation/job_queue.py:91-122` | **P2** |
| D15 | `app/bot.py` (1872 строк) и `app/web/routes/projects.py` (1470 строк/51 endpoint) — god-модули. `bot.py` вырос обратно после разделения в P1.1. `handle_unhandled_message` смешивает разбор намерения + разбиение задач + диспетчеризацию + форматирование ответа в одной функции | `app/bot.py`, `app/web/routes/projects.py` | **P2** |
| D16 | Две независимые LLM-абстракции (`app/ai_client.py` и `app/ai_recommendation/providers/*`) обслуживают разные сценарии по назначению, но дублируют одинаковую логику выбора провайдера/HTTP-вызова для одних и тех же вендоров (Grok/Gemini/Claude/Groq) | `app/ai_client.py`, `app/ai_recommendation/providers/*` | **P2** |
| D17 | `app/ai_client.py` сигнализирует об ошибке магической строкой `"AI error: ..."` вместо исключения/структурированного результата — вызывающий код должен знать про этот префикс | `app/ai_client.py` | **P2** |
| D18 | CI устанавливает `mypy`, но никогда не запускает (только `ruff`). `scripts/`/`tools/` не подключены к CI; `marketmind_launcher.sh`/`planned_marketmind_run.sh` не упоминаются нигде — orphaned | `.github/workflows/ci.yml`, `scripts/`, `tools/` | **P2** |
| D19 | Несогласованная retry-стратегия: `wildberries.py` — каскадный fallback, `ozon.py` — ручной exponential backoff, `yandex_market.py` — **вообще без retry/fallback**. `tenacity` заявлен в зависимостях, но нигде не используется (см. D22) | `app/parsers/{wildberries,ozon,yandex_market}.py` | **P2** |
| D20 | Скрытый side effect: `generate_ozon_batch_card_files` (сборка пачки карточек в Telegram) незаметно скрейпит URL и пишет новые товары в БД через `worker_add_urls` с no-op `quiet_notify` — пользователь видит только итоговый файл, не подозревая о записи в БД мониторинга | `app/telegram_card_handlers.py:141-251` | **P2** |
| D21 | Bot-обработчики экспорта проглатывают ошибки совсем без логирования (`except Exception as e: await message.answer(...)`, ни одного `logger` вызова) — в отличие от всех остальных обработчиков файла | `app/bot.py:1413-1415,1424-1425` | **P2** |

---

## 8. Missing tests

| # | Пробел | Связано с | Серьёзность |
|---|---|---|---|
| T2 | Нет теста, что `DatabaseApprovalQueue.apply_approved()` реально переводит `status` в `"applied"` — именно поэтому баг D1 остался незамеченным | D1 | **P1** (поднимает видимость P0-дефекта) |
| T1 | Нет теста, прогоняющего `create_configured_provider()` с `AI_PROVIDER=claude`/`grok` — баг D6 невидим для CI | D6 | **P2** |
| T3 | Нет теста на конкурентный вызов `save_product()` для одного URL | D2 | **P2** |
| T4 | `mypy` установлен, но не запускается ни в одном CI job — регрессии типов невидимы до рантайма | D18 | **P2** |
| T6 | Нет теста, привязывающего поведение `aiosqlite_patch.py` к конкретной версии `aiosqlite` | D4 | **P2** |
| D29 | `tests/test_cli.py::test_report_mode_passes_embed_images_flag` — проверяет только, что `export_html_report` был вызван с нужными аргументами, не саму генерацию отчёта (mock-heavy) | — | **P3** |

**В целом (позитивная находка):** выборка ~18 файлов тестов из ~90+ показала преимущественно
тесты реального поведения — `test_parsers.py` вызывает реальные функции парсинга на
сконструированном HTML/JSON, `test_web_api.py` поднимает настоящее FastAPI-приложение с
временной SQLite и проверяет реальные HTTP-ответы, `test_worker.py` использует
рукописный `FakeDB` с реальными телами методов, а не `MagicMock`. Мокается в основном только
сетевая граница (внешние API), а не собственная бизнес-логика — это именно то, что нужно
для «тестов, проверяющих реальное поведение».

---

## 9. Dead/duplicate code

| # | Находка | Серьёзность |
|---|---|---|
| D23 | `app/parsers/universal.py` (`UniversalParser`) мёртв в проде: зарегистрирован в `router.PARSERS`, но `fetch_product_auto()` никогда не вызывает `get_parser_class()` — явно ветвится только на wildberries/ozon/yandex_market. Интерфейс даже не совпадает с контрактом `BaseParser`. Заменён живым `app/universal_parsing_core/parsers/universal_html.py` | **P3** |
| D22 | `tenacity==8.2.3` заявлен в `requirements.txt`, нигде не импортируется — весь retry реализован вручную | **P3** |
| D26 | `WB_CABLE_MANAGEMENT_CANDIDATES` — большая захардкоженная константа с тестовыми данными живёт прямо в `app/web/routes/projects.py` | **P3** |
| D24 | `app/web/routes/import_.py` возвращает HTTP 200 с `status="failed"` в теле при ошибке импорта, а не код ошибки — ловушка для не-HTMX клиентов | **P2** |
| D27 | `tests/test_providers.py::test_unavailable_no_url` — неверно названный тест (на деле проверяет, что провайдер ДОСТУПЕН) | **P3** |
| D28 | `app/parsers/funpay.py` не имеет собственного `try/except` (падает на `response.raise_for_status()`) — безопасно только благодаря единственному вызывающему коду в `bot.py`, который оборачивает широко | **P3** |
| — | **Не является дублированием (перепроверено, старый аудит ошибался):** `app/adapters/*` — тонкие обёртки над `parsers/`/`updater.py`, а не отдельная реализация | — |
| D25 | `app/domain/events/builders.py` — минорная утечка infra-типа в domain (см. §4) | **P3** |

---

## 10. External integration risks

- **Ozon** (`app/parsers/ozon.py`) — ручной exponential backoff, реальные таймауты (15-60с),
  захардкоженные API URL и CSS-селектор (`h1`) как единая точка отказа, но есть alt-source
  fallback. `bypass_system_proxy()` (наш недавний коммит) снижает риск ложной блокировки
  антиботом на машине разработчика.
- **Wildberries** (`app/parsers/wildberries.py`) — самый устойчивый парсер: каскадный fallback
  через 4 уровня источников (облачная функция → API v1-3 → search API → 80 basket-хостов).
- **Yandex Market** (`app/parsers/yandex_market.py`) — **самый слабый**: единственный HTTP-запрос,
  единственный таймаут 30с, без retry и без fallback-источника (D19).
- **FunPay** (`app/parsers/funpay.py`) — не имеет собственной защиты от исключений (D28).
- **LLM (оба конвейера)** — единая точка отказа шага «generate» в обоих сценариях A и B;
  конкретные дефекты см. D5, D6, D16, D17. Секреты (`ANTHROPIC_API_KEY`, `GROK_API_KEY`,
  `GEMINI_API_KEY` и др.) нигде не логируются, есть явная редакция в error-сообщениях
  (`ai_client.py:267-271`) — это сделано аккуратно.
- **Конфигурация** не централизована: 25 обращений к `os.getenv`/`os.environ` разбросаны
  по 9 файлам вне `app/config.py`, включая случай реального расхождения дефолтов (D5).

---

## 11. Database/migration risks

- **Alembic**: 10 миграций, строго линейная цепочка, без веток и конфликтов. Все
  `add_column(nullable=False)` снабжены `server_default` — не найдено разрушительных операций
  на заполненной таблице. Отсутствие `batch_alter_table` для `op.drop_column` на SQLite
  теоретически ломает `downgrade()` на очень старых версиях SQLite — низкий риск, `downgrade`
  редко используется на практике.
- **Второй, неформальный путь миграции** — `_migrate_scrape_attempts` внутри `Database.init()`,
  выполняется на каждом старте параллельно с Alembic (D10).
- **WAL-режим** (фикс P0.4) — на месте, регрессий не найдено, конкуренция читателей/писателей
  для SQLite обрабатывается корректно (сессия на вызов).
- **Гонки записи**: D1 (approval status), D2 (`save_product` race), D8 (замена engine на лету
  при restore).
- **`app/compat/aiosqlite_patch.py`** — фактический фикс исходного зависания БД, но хрупкий
  монкипатч приватных атрибутов (D4) — самый серьёзный скрытый риск для стабильности БД в целом,
  так как при его поломке возвращается исходный класс P0-проблемы (hang на старте).

---

## 12. Recommended stabilization order

Согласно уже принятой методологии проекта (заморозка → аудит → карта → сценарии → baseline →
защитные тесты → нарушения → фиксы по одному классу → verify → commit), следующий шаг —
**не фиксы**, а:

1. Зафиксировать baseline (текущие 823 прошедших теста — уже сделано сегодня при коммите
   `8c434c7`, можно использовать как отправную точку).
2. Добавить защитные тесты именно на выявленные здесь дефекты **до** их исправления — в первую
   очередь T2 (approval status) и T3 (save_product race), поскольку они по конструкции
   регрессионные (тест должен падать на текущем коде, затем чиниться вместе с дефектом).
3. Далее — предлагаемый порядок классов проблем (каждый — отдельный цикл
   fix → verify → commit):

   *(Класс «Approval/accept-proposal integrity», ранее заявленный как P0, снят — при
   детальной проверке D1 оказался не багом, см. §5. Реальный P0-класса дефектов на момент
   аудита не найдено.)*

   **Класс 1 — Database race conditions** (D2, T3). Обработка `IntegrityError` в
   `save_product()`, возможно row-level компенсация.

   **Класс 2 — Silent failure visibility** (D3, D21, D8). Разные файлы, но одна и та же
   природа проблемы («ошибка проглочена без сигнала оператору») — можно чинить один
   паттерн сразу в нескольких местах за один проход.

   **Класс 3 — aiosqlite patch hardening** (D4, T6). Добавить guard на несовпадение версии/
   внутренних атрибутов вместо тихого no-op при поломке монкипатча.

   **Класс 4 — LLM provider configuration** (D5, D6, T1). Один и тот же файл-фабрика,
   один логический класс изменений, напрямую влияет на надёжность шага «generate» в обоих
   сценариях.

   **Класс 5 — Async job execution consistency** (D7). Перевести синхронный inline AI-вызов
   на `BackgroundTasks`.

   **Класс 6 — `app/database.py` decomposition** (D9, D10, D11). Крупный рефакторинг,
   стоит делать последним и только после того, как классы 1-4 закрыты и защищены тестами —
   именно этот файл имеет наибольший blast radius в проекте (134 связи в графе).

   Остальные P2/P3-пункты (D12-D28) — можно группировать по подсистемам (LLM-дублирование,
   god-модули UI, CI/tooling, dead code) и чинить по мере продвижения, они не блокируют
   основные сценарии.

---

## Итоговая сводка

> **Обновлено 2026-08-09 после начала работы над P0 #1** — D1 пересмотрен с P0 на P3
> (см. разбор в конце §5). Актуальные счётчики ниже.

**Найдено дефектов: 29**

| Уровень | Количество | Список |
|---|---|---|
| **P0** | 0 | — |
| **P1** | 7 | D2, D3, D4, D5, D6, D7, D8 |
| **P2** | 14 | D9, D10, D11, D12, D13, D14, D15, D16, D17, D18, D19, D20, D21, D24 |
| **P3** | 8 | D1 (пересмотрен), D22, D23, D25, D26, D27, D28, D29 |

Итого 0+7+14+8 = 29.

### 5 наиболее опасных проблем (обновлено)

1. **D6 (P1)** — провайдер `claude` в `ai_recommendation`-конвейере сломан на уровне конфигурации
   (пустой `base_url`). Учитывая, что `ANTHROPIC_API_KEY` — один из основных заявленных секретов
   проекта, это может означать, что выбранный по умолчанию AI-провайдер тихо не работает.
2. **D5 (P1)** — расхождение дефолтного `AI_PROVIDER` между `config.py` (`grok`) и
   `factory.py` (`ollama`) — тихая неверная конфигурация в зависимости от кодового пути.
3. **D4 (P1)** — монкипатч `aiosqlite_patch.py`, единственный фикс исходного зависания БД
   на старте, хрупок к обновлению зависимости; поломка отбрасывает проект к исходному
   классу проблемы (зависание на старте).
4. **D2 (P1)** — необработанная гонка в `save_product()` при конкурентном парсинге одного URL —
   правдоподобна при одновременной работе бота, веб-приложения и CLI над одними и теми же товарами.
5. **D3 (P1)** — тихое проглатывание на уровне DEBUG ошибок записи в `record_blocked_pattern`/
   JSONL-логи, питающие adaptive cooldown/circuit-breaker — деградация антибот-защиты незаметна
   оператору.

### С чего рекомендуется начать

P0 пуст. Начинаем с P1, по одному дефекту за цикл (минимальная правка → targeted tests →
полный regression suite → E2E → commit):

1. **P1 #1 — D2** (гонка в `save_product()`) — самый изолированный фикс, чёткий паттерн
   (обработка `IntegrityError`), понятный targeted-тест на конкурентный вызов.
2. **P1 #2 — D3** (тихое проглатывание ошибок телеметрии) — поднять уровень логирования/не
   проглатывать сбой самого `commit()`.
3. **P1 #3 — D8** (замена `Database` на лету при restore) — сузить окно гонки.
4. **P1 #4 — D4** (хрупкий монкипатч aiosqlite) — добавить guard на несовпадение внутренних
   атрибутов вместо тихого no-op.
5. **P1 #5 — D5 + D6** (конфигурация AI-провайдера) — один файл/подсистема, один цикл:
   унифицировать дефолт `AI_PROVIDER` и добавить `claude` в `_PROVIDER_BASE_URLS`.
6. **P1 #6 — D7** (синхронный AI-вызов внутри HTTP-запроса) — перевести на `BackgroundTasks`
   по аналогии с product-level эндпоинтом.

Далее — P2 (архитектурный рефакторинг, начиная с декомпозиции `app/database.py`), только после
закрытия всех P1.

---

**Аудит остановлен согласно ограничению задачи. Изменений в код (кроме этого документа) не
вносилось.**
