# STABILIZATION_AUDIT.md — MarketMind AI

> Дата аудита: 2026-08-09
> Тип: READ-ONLY аудит на момент написания (см. журнал фиксов ниже для того, что изменилось с тех пор).
> Коммит на момент аудита: `8c434c7`
>
> **Журнал стабилизации (P0/P1 закрыты 2026-08-09):**
> - D1 пересмотрен P0→P3 при попытке фикса (см. §5) — реального бага не оказалось.
> - D2 (race в save_product) — исправлено, `448a44b`.
> - D3 (тихие DEBUG-логи телеметрии) — исправлено, `d21373a`.
> - D8 (неатомарная замена файла БД при restore) — исправлено, `c95751f`.
> - D4 (хрупкий монкипатч aiosqlite) — исправлено, `6003908`.
> - D5+D6 (конфигурация AI-провайдера, сломанный claude) — исправлено, `09cf21e`.
> - D7 (синхронный AI-вызов в HTTP-запросе) — исправлено, `22c60a3`.
>
> Все P0/P1 закрыты. Остаётся P2 (архитектурный рефакторинг) и P3 (косметика) — см. §7.
>
> **Журнал P2 (начат 2026-08-10):**
> - **D9 — RESOLVED** (`ef7b016`, `2459afe`, `1f81570`, `5b46161`, 2026-08-09/10). `app/database.py`
>   декомпозирован в пакет `app/database/{base,models,resilience,utils,core}.py`. Модели/чистая
>   resilience-логика/утилиты вынесены из класса `Database`. Публичный контракт сохранён полностью
>   (`app/database/__init__.py` — фасад с reload-каскадом). Класс `Database` (core.py, 887 строк)
>   намеренно не дробился дальше на repository-классы — это отдельная, более рискованная задача
>   (см. D11). Полный test suite (833) + `verify_control_build.sh` + smoke test — зелёные на момент
>   коммита.
> - **D14 (частично) — RESOLVED** (см. запись ниже в §4). Устранён дублированный
>   `session.get(JobRecord, job_id)` в `content_pipeline/routes.py` и `competitor_analysis/routes.py`
>   → общий `Database.get_job()`. Остальная часть D14 (`product_detail.py`, `projects.py`,
>   `reports.py`) — **не тронута**, остаётся открытой.
> - **D13 (частично) — RESOLVED** (2026-08-10, см. запись ниже в §4). Убрана прямая зависимость
>   `cmd_list`/`cmd_status`/`_broadcast_changes` от `Database`/сырого SQLAlchemy → новый
>   `app/telegram_read_service.py` (`TelegramReadService`, 4 метода). Цепочка стала
>   `handler → Service → Database`.
> - **D13, продолжение (частично) — RESOLVED** (2026-08-10, см. запись ниже в §4). Убрана прямая
>   зависимость `cmd_update`/`cmd_reviews` от `Database`/сырого SQLAlchemy → `TelegramReadService`
>   расширен методами `get_product_count()`/`get_recent_wildberries_products()` (6 методов всего).
>   `handle_reviews_choice` — **отдельный** обработчик (FSM-продолжение `/reviews`, не сама команда
>   `cmd_reviews`), тоже делал прямой `db.session()`/`s.get(Product, ...)` — на тот момент не тронут,
>   вне заявленного scope той итерации.
> - **D13, финал — RESOLVED** (2026-08-10, см. запись ниже в §4). `handle_reviews_choice` тоже
>   переведён на `TelegramReadService` → новый метод `get_product_by_id()` (7 методов всего).
>   Полный статический скан `app/bot.py` на `db.session(`/`select(`/`.execute(`/`.scalars(`/
>   `.scalar(`/`session.get(`/`session.add(`/прямое использование ORM-моделей — **0 совпадений**;
>   `Product`/`PriceHistory` больше не импортируются в `bot.py` вообще. D13 в его исходной
>   формулировке (raw `db.session()`/`select()` inline в обработчиках) — **RESOLVED**. Отдельно
>   зафиксировано (не как D13-нарушение, а как смежное наблюдение к **D11**): ~8 других команд
>   `bot.py` (`cmd_metrics`, `cmd_blocks`, `cmd_health`, `handle_urls`, `cmd_make_card_last`,
>   `cmd_subscribe`, `handle_natural_card_urls`) по-прежнему читают/пишут через собственные
>   инкапсулированные методы `Database` (`db.get_latest_product()` и т.п.), а не через
>   `TelegramReadService` — это не «сырой SQL», а вызов уже существующего repository-слоя,
>   архитектурно другой (более мягкий) класс несогласованности, чем то, ради чего заводился D13;
>   в скоуп текущей задачи не входило и не расширялось.
> - **`image_urls` в `_unified_from_snapshot` — NOT REPRODUCIBLE** (2026-08-10, расследование по
>   находке из D12; см. новую запись §9/D12'). Полный трейс данных (`_snapshot_from_unified` →
>   импорт CSV → `ProjectProduct.source_snapshot_json` → `normalize_card_payload` для черновиков →
>   `_unified_from_snapshot`) показал: **все** реальные писатели snapshot'а приводят `image_urls`
>   к `list[str]` до того, как строка могла бы достичь этой функции. Прямой unit-тест подтверждает,
>   что САМА функция не защищена (если вызвать её напрямую со строкой — испортит данные посимвольно),
>   но ни одного реального пути вызова с сырой строкой не найдено. **Production-код не менялся**
>   (по инструкции задачи). Найдена смежная, реально достижимая версия того же класса дефекта в
>   `normalize_card_payload()` (`app/editor/schemas.py:66-74`, через `payload` параметр
>   `create_draft`/`update_draft`/`draft_quality_preview` — потенциальный внешний API-вызов, не
>   через UI) — зафиксирована как отдельная Deferred finding, не исправлена (другая функция, вне
>   заявленного скоупа).
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
| D13 | ~~Telegram-бот вообще не имеет service-слоя для чтения: прямой `SQLAlchemy`/`app.database` импорт и inline-запросы в обработчиках команд~~ **RESOLVED 2026-08-10**: для `cmd_list`/`cmd_status`/`_broadcast_changes`/`cmd_update`/`cmd_reviews` введён и расширен `TelegramReadService` (`app/telegram_read_service.py`, 7 методов). **Финал (тот же день)**: `handle_reviews_choice` (FSM-продолжение после `/reviews`) тоже переведён на сервис — добавлен `get_product_by_id()`, заменивший `async with db.session() as s: product = await s.get(Product, ...)`. Полный статический скан `app/bot.py` на `db.session(`/`select(`/`.execute(`/`.scalars(`/`.scalar(`/`session.get(`/`session.add(`/прямые ORM-модели — **0 совпадений**; `Product`/`PriceHistory` не импортируются в `bot.py`. Исходно сформулированная проблема (raw SQLAlchemy inline в обработчиках) устранена полностью. **Смежное наблюдение (не D13-нарушение, ближе к D11)**: ~8 других команд (`cmd_metrics`, `cmd_blocks`, `cmd_health`, `handle_urls`, `cmd_make_card_last`, `cmd_subscribe`, `handle_natural_card_urls`) читают/пишут через собственные методы `Database` (`db.get_latest_product()` и т.п.), минуя `TelegramReadService`, — это вызов уже существующего repository-слоя, не сырой SQL, в scope D13 никогда не входило | `app/bot.py` (0 прямых `db.session()`/`select()`); `app/telegram_read_service.py` (7 методов, закрывают все read-пути `cmd_list`/`cmd_status`/`_broadcast_changes`/`cmd_update`/`cmd_reviews`/`handle_reviews_choice`) | **P2** |
| D14 | API→DB в обход service-слоя: `product_detail.py` — почти все хелперы открывают сессию напрямую; 4 места в `projects.py` (экспорт/отчёт по одному id) в обход уже существующих `ProjectExportService`/`ClientDeliveryReportService`; ~~`reports.py` — прямой `select(ApprovalRecord.status)`~~ **RESOLVED 2026-08-11** (см. D11-D): вынесено в `DatabaseApprovalQueue.get_status_counts()`; ~~дублирующийся inline `session.get(JobRecord, ...)` в `content_pipeline/routes.py` и `competitor_analysis/routes.py`~~ **RESOLVED 2026-08-10**: заменено на общий `Database.get_job()`, оба роут-файла больше не импортируют `app.database` вообще. Остальная часть (`product_detail.py`, `projects.py`) — открыта | см. список выше | **P2** |
| D25 | `app/domain/events/builders.py` импортирует `app.database.Product` не под `TYPE_CHECKING` и делает `isinstance(source, Product)` — минорная утечка infrastructure в domain-модуль, который в остальном чист | `app/domain/events/builders.py:7,92` | **P3** |
| D11 | **Уточнено 2026-08-10, полный read-only mapping (без изменения кода)**: исходная формулировка была неточна — «Database-owning service/store» (класс хранит `Database`, сам открывает `db.session()` на каждый метод, сам коммитит, без отдельного repository) на деле не исключение, а **доминирующий** паттерн — 11 классов: `ProjectService`, `ProjectArchiveService`, `CompetitorSnapshotStore`, `DatabaseApprovalQueue`, `ArtifactStore`, `EffectiveProductCardService`, `ProjectExportService`, `ClientDeliveryReportService`, `TimelineRepository`, `TelegramReadService`, `DeepAnalyzer`. Отдельный injected-session repository (`ProductEditorRepository`, `DomainEventRepository`) используется только в `editor`, и обоснованно: там одна транзакция должна атомарно затронуть несколько репозиториев сразу (draft/version + domain event) — это ACCEPTABLE-вариация, а не нарушение. Настоящие CRITICAL VIOLATION — это API-слой, управляющий session напрямую: `app/web/routes/product_detail.py` (5 приватных helper'ов на уровне модуля), `app/web/routes/projects.py` (4 места: скачивание export/report по id), `app/web/routes/reports.py` (`_suggestion_stats()`) — пересекается с уже открытым D14. Отдельно — свободные module-level функции с сырым `db.session()`/`select()` вне какого-либо класса: `app/agent.py` (5 функций), `app/exporter.py`, `app/reporter.py`, `app/runtime_paths.py:system_status()` (запрос к БД в файле про пути ФС — не туда положено), `app/ai_recommendation/job_queue.py` (`_get_product`, `_get_last_price`). Найдены **подтверждённые дубли одного и того же запроса** (см. §6-аналог в отчёте mapping-задачи): `job_queue.py:_get_last_price()` побайтово идентичен `Database.get_last_price()`; `job_queue.py:_get_product()` идентичен (по форме) `TelegramReadService.get_product_by_id()` (оба — `session.get(Product, id)`); `EffectiveProductCardService._get_project_product()` побайтово идентичен `ProjectService.get_project_product()` (включая переиспользование того же класса исключения `ProjectNotFoundError`) — риск рассинхронизации при будущих правках, как это уже было с D14/JobRecord. `cmd_metrics`/`cmd_blocks`/`cmd_health`/`handle_urls`/`cmd_make_card_last`/`cmd_subscribe`/`handle_natural_card_urls` (см. D13) — это НЕ нарушение D11: обычный вызов `Database`-фасада, тот же паттерн, что и остальные 11 классов. Transaction ownership: `Database.session()` — голый `AsyncSession`, без auto-commit; во всех проверенных местах commit делает тот, кто открыл сессию (Service/Store), repository-классы (`ProductEditorRepository`, `DomainEventRepository`) сами никогда не коммитят — правило соблюдается последовательно везде, где проверено. Shortlist минимальных кандидатов на будущее исправление: D11-A (слить дубль `_get_project_product`, не начато), ~~D11-B (слить `job_queue._get_last_price` → `Database.get_last_price`, самый безопасный, точный аналог уже сделанного D14/`get_job()`)~~ **RESOLVED 2026-08-13**: `job_queue.py:_get_last_price()` (дубль-функция, единственный вызывающий на строке ~329) удалена целиком; вызов заменён на уже существующий `db.get_last_price(product_id)`; попутно удалён ставший неиспользуемым `from sqlalchemy import desc, select` (оба символа использовались только в удалённой функции). `PriceHistory`-импорт сохранён — нужен для сигнатуры `_build_unified()`. Ruff/импорт `app.ai_recommendation.job_queue` чистые. Тесты: `tests/test_gemini_error_chain.py`, `tests/test_product_detail.py`, `tests/test_client_projects.py`, `tests/test_unified_from_snapshot.py` — 110/110, идентично baseline до правки; полный suite 887/887 без новых падений. ~~D11-C (слить `job_queue._get_product`/`TelegramReadService.get_product_by_id` через общий `Database`-метод)~~ **RESOLVED 2026-08-13**: добавлен `Database.get_product_by_id()` (`app/database/core.py`, рядом с `get_job()`, тот же `session.get(Model, id)`-паттерн). `job_queue.py:_get_product()` удалена целиком, вызов заменён на `db.get_product_by_id(product_id)`. `TelegramReadService.get_product_by_id()` — публичная сигнатура и поведение сохранены (нужны для `bot.py:1361` и прямых unit-тестов), тело заменено на `return await self._db.get_product_by_id(product_id)`; `job_queue` и `telegram_read_service` по-прежнему не зависят друг от друга — оба идут через общий `Database`-facade, а не друг через друга. Попутно (прямое следствие удаления функций-обёрток) `Database`/`PriceHistory`/`Product` в `job_queue.py` стали типами только для аннотаций — вынесены под `TYPE_CHECKING` (TC001), реэкспорт из файла не найден, риска нет. Ruff/импорт всех трёх модулей чистые. Тесты: `tests/test_telegram_read_service.py`, `tests/test_bot_helpers.py`, `tests/test_gemini_error_chain.py`, `tests/test_product_detail.py`, `tests/test_client_projects.py`, `tests/test_unified_from_snapshot.py` — 208/208, идентично baseline; `test_bot_helpers.py` патчит `get_product_by_id` через `patch.object` на уровне метода, поэтому смена внутренней реализации теста не задевает. Полный suite — см. отдельный прогон. ~~D11-D (`reports.py:_suggestion_stats` — та же форма, что и остальной D14)~~ **RESOLVED 2026-08-11**: `reports.py:_suggestion_stats()` больше не открывает `db.session()`/`select(ApprovalRecord.status)` напрямую — заменено на `await DatabaseApprovalQueue(request.app.state.db).get_status_counts()`; сам запрос перенесён в новый метод `DatabaseApprovalQueue.get_status_counts()` (`app/ai_recommendation/db_approval.py`), `reports.py` больше не импортирует `app.database.ApprovalRecord`/`sqlalchemy.select`. Пересечение с D14 (`reports.py`) закрыто тем же изменением. Тесты: `tests/test_approval_workflow.py` (+2, unit на `get_status_counts()` — пустая очередь и смешанные статусы), `tests/test_reports_ui.py` (+2, через `/api/reports/client-summary`, покрывают все 4 статуса включая `rolled_back`) — 4 новых теста, все проходят. D11-E (перенести `system_status()` из `runtime_paths.py` в подходящее место) | `app/web/routes/product_detail.py`, `app/web/routes/projects.py`, ~~`app/web/routes/reports.py`~~ (D11-D RESOLVED); `app/agent.py`, `app/exporter.py`, `app/reporter.py`, `app/runtime_paths.py`; `app/ai_recommendation/job_queue.py` (~~`_get_last_price` дубль~~ D11-B RESOLVED, ~~`_get_product` дубль~~ D11-C RESOLVED); `app/database/core.py` (+`get_product_by_id()`), `app/telegram_read_service.py` (D11-C); `app/effective_card/service.py`, `app/projects/service.py` (дубль `_get_project_product`, D11-A открыт) | **P2** |

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
| D9 | ~~`app/database.py` — god object: 15 ORM-моделей + connection lifecycle + generic CRUD + JSONL-логирование + полноценный adaptive cooldown/circuit-breaker engine (~280 строк scraper-бизнес-логики) в одном файле/классе~~ **RESOLVED 2026-08-09/10**: декомпозирован в `app/database/{base,models,resilience,utils,core}.py`. `Database`-класс (core.py) остаётся одной большой сущностью (887 строк) — намеренно не дробился дальше, см. D11 | `app/database/` | **P2** |
| D10 | Два параллельных механизма миграции: Alembic (чистый, линейный) vs. `_migrate_scrape_attempts` — ad-hoc ALTER-TABLE шим, до сих пор выполняющийся при каждом `Database.init()`. Ничто не гарантирует их синхронность | `app/database.py:621-682` | **P2** |
| D11 | Repository-паттерн непоследователен (см. §4/D11) | — | **P2** |
| D12 | Дублирование бизнес-логики: конвертация snapshot→`UnifiedProduct` независимо реализована дважды. **Уточнено 2026-08-10 при попытке выбрать этот P2**: функции **не идентичны** — `_build_project_unified` (job_queue.py) вычисляет `thumbnail_url` и защищён от случая, когда `image_urls` приходит строкой (иначе `_unified_from_snapshot` даст `list(str)` → список символов вместо URL — потенциальный скрытый баг); `_unified_from_snapshot` (effective_card/service.py) передаёт `discount_pct`, которого нет в другой версии; `attributes`/`tags` по-разному приводятся к типам (`str()`-принудительно vs нет). Честное объединение требует либо принять поведенческие изменения, либо параметризовать — не тривиальный минимальный фикс, отложено. **Расследование `image_urls`-подозрения (2026-08-10) — NOT REPRODUCIBLE**: полный трейс данных (`_snapshot_from_unified` → импорт → `normalize_card_payload` → `_unified_from_snapshot`) показал, что каждый реальный писатель snapshot'а уже приводит `image_urls` к `list[str]` — строка никогда не достигает `_unified_from_snapshot` через существующий код. Функция сама по себе не защищена (подтверждено unit-тестом при прямом вызове), но нерабочий сценарий недостижим — production-код не менялся (`tests/test_unified_from_snapshot.py`, `tests/test_client_projects.py::test_import_with_comma_separated_image_cell_produces_real_url_list_not_characters`). Найдена смежная, **реально достижимая** версия того же класса дефекта в `normalize_card_payload()` (`app/editor/schemas.py:66-74`) — не исправлена, другая функция, отдельная задача | `app/effective_card/service.py:200-225`, `app/ai_recommendation/job_queue.py:91-122` | **P2** |
| D15 | `app/bot.py` (1872 строк) и `app/web/routes/projects.py` (1470 строк/51 endpoint) — god-модули. `bot.py` вырос обратно после разделения в P1.1. `handle_unhandled_message` смешивает разбор намерения + разбиение задач + диспетчеризацию + форматирование ответа в одной функции | `app/bot.py`, `app/web/routes/projects.py` | **P2** |
| D16 | Две независимые LLM-абстракции (`app/ai_client.py` и `app/ai_recommendation/providers/*`) обслуживают разные сценарии по назначению, но дублируют одинаковую логику выбора провайдера/HTTP-вызова для одних и тех же вендоров (Grok/Gemini/Claude/Groq) | `app/ai_client.py`, `app/ai_recommendation/providers/*` | **P2** |
| D17 | `app/ai_client.py` сигнализирует об ошибке магической строкой `"AI error: ..."` вместо исключения/структурированного результата — вызывающий код должен знать про этот префикс | `app/ai_client.py` | **P2** |
| D18 | CI устанавливает `mypy`, но никогда не запускает (только `ruff`). `scripts/`/`tools/` не подключены к CI; `marketmind_launcher.sh`/`planned_marketmind_run.sh` не упоминаются нигде — orphaned | `.github/workflows/ci.yml`, `scripts/`, `tools/` | **P2** |
| D19 | Несогласованная retry-стратегия: `wildberries.py` — каскадный fallback, `ozon.py` — ручной exponential backoff, `yandex_market.py` — **вообще без retry/fallback**. `tenacity` заявлен в зависимостях, но нигде не используется (см. D22) | `app/parsers/{wildberries,ozon,yandex_market}.py` | **P2** |
| D20 | Скрытый side effect: `generate_ozon_batch_card_files` (сборка пачки карточек в Telegram) незаметно скрейпит URL и пишет новые товары в БД через `worker_add_urls` с no-op `quiet_notify` — пользователь видит только итоговый файл, не подозревая о записи в БД мониторинга | `app/telegram_card_handlers.py:141-251` | **P2** |
| D21 | Bot-обработчики экспорта проглатывают ошибки совсем без логирования (`except Exception as e: await message.answer(...)`, ни одного `logger` вызова) — в отличие от всех остальных обработчиков файла | `app/bot.py:1413-1415,1424-1425` | **P2** |
| D30 | ~~**Новая находка 2026-08-10** (обнаружена при расследовании D12/`image_urls`): `normalize_card_payload()` не защищена от `image_urls`, приходящего строкой — `for item in result.get("image_urls") or []:` посимвольно разберёт строку вместо того, чтобы принять её как один URL или разделить по запятой. Реально достижимо через `payload: dict[str, Any]` параметр `ProductCardEditorService.create_draft`/`update_draft`/`EffectiveProductCardService.draft_quality_preview` — то есть напрямую через API-запрос (`POST .../drafts`), в обход UI (ни один HTML-шаблон сейчас не отправляет `image_urls` в теле запроса — проверено).~~ **RESOLVED 2026-08-10**: подтверждено 3 реально достижимых пути (`POST/PATCH /api/products/{id}/drafts[...]` в `app/web/routes/editor.py`, `POST /api/projects/{pid}/products/{id}/drafts/{did}/quality-preview` в `app/web/routes/projects.py`) — ни на одном нет Pydantic-схемы, тело JSON проходит без проверки типов. Канонический контракт (`EditableProductCard.image_urls: list[str]`) и уже существующий в этом же проекте прецедент обработки строки как comma-separated списка (`app/ai_recommendation/job_queue.py:_build_project_unified`, `app/projects/imports.py` CSV-импорт, а также сосед `tags` в самой `normalize_card_payload`) — выбран вариант B (нормализация, не отказ). Минимальный фикс: `app/editor/schemas.py:66-75` — добавлена проверка `isinstance(raw_urls, str)` перед циклом, строка разбивается по запятой (без замены `;`, по прецеденту `image_urls`, а не `tags`). Другие поля/функции (`_unified_from_snapshot`, D11, D12, D13, Telegram, Database, Alembic, маркетплейсы, LLM) не тронуты. Тесты: `tests/test_editor_schemas.py` (8 юнит-тестов на `normalize_card_payload`, 3 из них падали до фикса), `tests/test_card_editor.py` (2 новых теста через реальный `POST`/`PATCH /api/products/{id}/drafts`), `tests/test_client_projects.py` (1 новый тест через `POST .../drafts/{id}/quality-preview`) — итого 12 новых тестов, все проходят после фикса. Полный прогон: 867 passed (было 855 + 12 новых), 0 новых падений. `scripts/verify_control_build.sh` — зелёный. Smoke-test через реальный FastAPI/TestClient (без моков) — подтверждён | `app/editor/schemas.py:66-75` | **P2** |

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

**Найдено дефектов: 30** (D30 добавлен 2026-08-10 при расследовании D12/`image_urls`; закрыт тем же днём)

| Уровень | Количество | Список |
|---|---|---|
| **P0** | 0 | — |
| **P1** | 7 (все закрыты) | D2, D3, D4, D5, D6, D7, D8 |
| **P2** | 15 (3 закрыты полностью, 1 частично: D9 ✅, D13 ✅, D30 ✅, D14 частично ✅) | D9 ✅, D10, D11, D12 (уточнён, `image_urls`-подозрение — NOT REPRODUCIBLE), D13 ✅, D14 (частично ✅), D15, D16, D17, D18, D19, D20, D21, D24, D30 ✅ |
| **P3** | 8 | D1 (пересмотрен), D22, D23, D25, D26, D27, D28, D29 |

Итого 0+7+15+8 = 30. Записи не удаляются при решении — история сохраняется через ~~зачёркивание~~ + RESOLVED-пометку.

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
