# COMPETITOR_ANALYSIS.md — Competitor Analysis (Этап 5, сужённый скоуп)

> Дата: 2026-08-02
> Модуль: `app/competitor_analysis/`

---

## 1. Назначение

Персистентный конкурентный анализ для товара внутри клиентского проекта:
периодический снимок конкурентов по маркетплейсам + (для Wildberries) их
реальные тексты отзывов. Результат используется двумя способами:
- отображается на странице товара проекта (цена/рейтинг/отзывы конкурентов);
- подмешивается в Content Intelligence Pipeline (Этап 4) как
  `SemanticPlan.competitor_gap_terms` — частые термины конкурентов,
  которых ещё нет в собственной карточке.

Это сужённый скоуп исходного "Semantic Intelligence & Competitor Analysis":
**Ozon-отзывы и вопросы покупателей сознательно вынесены за скобки** — нет
известного API ни для того, ни для другого, это отдельная исследовательская
задача с неопределённым результатом, не блокирующая эту итерацию.

## 2. Откуда данные (ничего не парсится заново)

- Поиск конкурентов: `search_all_marketplaces()` (`app/parsers/router.py:93`) — тот же реальный live-поиск по WB/Ozon/Я.Маркет, что используется в Telegram-хендлерах и `app/market_analysis.py`.
- Тексты отзывов (только WB, top-3 конкурента): `WildberriesParser._fetch_reviews()` (`app/parsers/wildberries.py:640`) — существовал в коде, но нигде не вызывался; теперь используется из `CompetitorAnalysisService`. nm_id конкурента извлекается из его URL через `_extract_wb_id()` (тот же модуль) — тоже уже существующая функция.
- Термины конкурентов: `extract_competitor_terms()` (`app/seo_intelligence.py:141`) — существующая частотная функция (**требует, чтобы термин встречался минимум у 2 конкурентов** — иначе это шум одной карточки, не сигнал).

## 3. Модуль

| Файл | Роль |
|---|---|
| `store.py` | CRUD для `CompetitorSnapshot` — версионируется по `batch_id` (один запуск = один батч) |
| `service.py` | `CompetitorAnalysisService.refresh_competitors()` — поиск + (для WB) отзывы + сохранение батча |
| `jobs.py` | `process_competitor_refresh_job()` — фоновая job, по образцу `content_pipeline/jobs.py` |
| `routes.py` | API + HTML-триггер |

### `CompetitorSnapshot` (таблица `competitor_snapshots`)
Миграция: `alembic/versions/f2a3b4c5d6e7_add_competitor_snapshots.py` (head после `e1f2a3b4c5d6`). Поля: снапшот конкурента (название/URL/цена/рейтинг/кол-во отзывов/тексты отзывов JSON), привязка к `project_id + project_product_id + product_id`, `batch_id` для группировки, `search_query`.

## 4. Интеграция с Content Pipeline (Этап 4)

`SemanticPlan.competitor_gap_terms: list[str]` — новое поле (`app/content_pipeline/schemas.py`). `semantic_plan_for_passport()` (`app/content_pipeline/semantic_planner.py`) принимает опциональный `competitor_names: list[str]`; если пуст/не передан — работает как раньше, без изменений в поведении. `run_content_pipeline()` (`app/content_pipeline/pipeline.py`) сам подтягивает последний батч через `CompetitorSnapshotStore.get_latest_batch()`, если он есть — порядок стадий не меняется.

## 5. API

- `POST /api/projects/{project_id}/products/{product_id}/competitors/refresh` — фоновая job.
- `GET .../competitors` (+ `/history`) — последний/все батчи с агрегатами (медиана цены, диапазон рейтинга).
- `GET /api/competitor-analysis/jobs/{job_id}` — статус.
- `POST /projects/{project_id}/products/{product_id}/competitors/refresh` (без `/api`) — HTML-триггер со страницы товара, redirect 303.

## 6. Тесты

19 новых тестов (6 store + 3 service + 4 routes + 2 semantic_planner + 2 orchestrator интеграции + 2 уже засчитанных в предыдущих числах) — все на SQLite in-memory, `search_all_marketplaces`/`WildberriesParser._fetch_reviews` мокаются через `unittest.mock.patch`, реальных сетевых вызовов в тестах нет.

## 7. Известные ограничения / что дальше

- Только WB-отзывы; Ozon-отзывы и вопросы покупателей — не реализовано (см. §1).
- Запрос конкурентов строится напрямую из `passport.title` — без уточнения по категории/бренду отдельно; при плохом качестве исходного title поиск конкурентов может быть менее релевантным.
- Нет UI для истории батчей (только API `/history`) — на странице товара показывается только последний батч.
