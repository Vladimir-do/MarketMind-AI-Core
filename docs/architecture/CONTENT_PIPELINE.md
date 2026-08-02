# CONTENT_PIPELINE.md — Content Intelligence Pipeline

> Дата: 2026-08-02
> Модуль: `app/content_pipeline/`

---

## 1. Назначение

Многостадийный конвейер генерации карточки товара, заменяющий одиночный
one-shot LLM-вызов (`app/card_filler.py::build_enhanced_ozon_card_draft`)
на цепочку специализированных стадий с явной стратегией контента,
распределением ключевых слов и проверкой фактов:

```
Product Passport
      │
      ▼
Content Strategy Builder  (LLM)
      │
      ▼
Semantic Planner          (детерминированный, поверх app.semantic_core)
      │
      ▼
Title Generator            (LLM)
      │
      ▼
Benefits Generator          (LLM)
      │
      ▼
Description Generator        (LLM)
      │
      ▼
SEO Auditor                   (детерминированный, поверх app.seo_intelligence)
      │
      ▼
Fact Checker                   (детерминированный, regex + сверка с Passport)
      │
      ▼
Marketplace Validator            (детерминированный, тот же audit_unified_product_seo,
      │                            но .ready — блокирующий критерий)
      ▼
Quality Controller (CQI)          (агрегатор уже посчитанных оценок)
      │
      ▼
AI Proposal Queue                  (существующий DatabaseApprovalQueue)
```

Пайплайн v1 работает только для товаров внутри клиентских проектов
(`ClientProject`/`ProjectProduct`) — только там есть `EffectiveProductCard`,
`ProductCardVersion` и полноценный approve/apply/rollback workflow. Товары
из Telegram-скрапинга (`Product` без проекта) вне охвата v1: модель `Product`
не хранит description/attributes, применять туда сгенерированный контент
физически некуда.

---

## 2. Модуль `app/content_pipeline/`

| Файл | Роль |
|---|---|
| `schemas.py` | Pydantic v2 контракты всех стадий (`extra="forbid"`) |
| `passport.py` | Адаптер `EffectiveProductCard` → `ProductPassport` |
| `prompt_registry.py` + `prompts/*.yaml` | Централизованный реестр LLM-промптов |
| `parsing.py` | Единый разбор JSON-ответов LLM в Pydantic-схему |
| `semantic_planner.py` | Распределение терминов `SemanticCore` по зонам карточки |
| `seo_auditor.py` / `marketplace_validator.py` | Тонкие адаптеры над `audit_unified_product_seo()` |
| `fact_checker.py` | Эвристическая сверка утверждений с Product Passport |
| `quality_controller.py` | Композиция оценок в единый CQI |
| `strategy_builder.py` / `title_generator.py` / `benefits_generator.py` / `description_generator.py` | LLM-стадии |
| `artifact_store.py` | CRUD для `ContentPipelineArtifact` (версионируемые промежуточные артефакты) |
| `pipeline.py` | Оркестратор — последовательно вызывает все стадии |
| `jobs.py` | `process_content_pipeline_job()` — фоновая job-обвязка |
| `routes.py` | API/HTML-роуты |

### Переиспользуется, не дублируется
- AI-провайдер: `app.ai_recommendation.providers.factory.create_configured_provider()` — единый async-интерфейс `BaseAIProvider.complete()`. Старый `app.ai_client.ask_ai()` (используется `card_filler.py`) не тронут и не используется новым кодом.
- Очередь предложений: финальные title/description/selling_points попадают в существующий `DatabaseApprovalQueue` (`app.ai_recommendation.db_approval`) как обычные `AISuggestion` — новой approval-семантики нет.
- SEO-пороги: `app.seo_rules.get_marketplace_rules()` — одна и та же логика используется и в SEO Auditor (информационная стадия), и в Marketplace Validator (блокирующий gate), чтобы пороги не расходились.
- Семантика: `app.semantic_core.build_semantic_core()` — Semantic Planner только распределяет уже классифицированные термины по зонам, не генерирует новые ключи.

---

## 3. Данные

### `ContentPipelineArtifact` (таблица `content_pipeline_artifacts`)
Версионируемые промежуточные артефакты (`content_strategy`, `semantic_plan`,
`fact_check_report`, `quality_report`) — НЕ approval-семантика (без
approve/reject), просто история для GET-роутов и трассируемости. Уникальность
по `(project_id, project_product_id, artifact_type, version_number)`.

Миграция: `alembic/versions/e1f2a3b4c5d6_add_content_pipeline_artifacts.py`
(head после `d5e6f7a8b9c0_add_job_records`).

### `selling_points` — новое поле карточки
Преимущества товара получили собственное поле (`app/editor/schemas.py`
`EditableProductCard.selling_points: list[str]`) вместо того, чтобы
складываться в `description` — можно отдельно approve/reject/показывать в
инфографике. Затронуты: `normalize_card_payload`/`validate_card_payload`,
`_suggestion_payload()` в `app/web/routes/suggestions.py` (round-trip
строка↔список через `\n`-разделитель), `app/exports/service.py` (новая
колонка в CSV/XLSX), `project_product_edit.html` (текстовое поле).

### Prompt Registry
`prompts/*.yaml` (не БД — промпты это код, должны ревьюиться через git diff).
Каждый файл: `id`, `version`, `status` (active/draft/deprecated), `purpose`,
`model`, `marketplace`, `category`, `input_schema`/`output_schema` (dotted
path на Pydantic-модель), `system_prompt`, `user_prompt_template`
(`.format()`-шаблон, без Jinja2). Резолюция в `get_prompt()`:
`marketplace+category → marketplace → universal`, только `status=active`.

---

## 4. API

Все роуты — project-scoped, под `/api/projects/{project_id}/products/{product_id}/...`:

- `POST .../content-pipeline/run` — ставит фоновую job (`BackgroundTasks`), возвращает `{job_id, status}`.
- `GET /api/content-pipeline/jobs/{job_id}` — статус job.
- `GET .../content-strategy` / `.../semantic-plan` / `.../fact-check` / `.../quality-report` (+ `/history`) — последний/все версии артефакта.
- `POST /projects/{project_id}/products/{product_id}/content-pipeline/run` (без `/api`) — HTML-триггер со страницы товара, redirect 303 обратно на страницу.

UI: секция "Content Intelligence Pipeline" на `project_product_detail.html` — CQI-бейдж, разбивка по компонентам, краткая стратегия, кнопка запуска/перегенерации.

---

## 5. Тесты

46 юнит-тестов фундамента (без моков LLM) + 7 тестов генераторов + 4
интеграционных теста оркестратора + 6 HTTP-тестов роутов — все на SQLite
in-memory, без Docker, без реального API-ключа (используется скриптуемый
`tests/content_pipeline_fakes.py::ScriptedAIProvider` — очередь
предзаданных ответов по стадиям, в отличие от `MockAIProvider`, который
всегда отдаёт один и тот же ответ).

---

## 6. Известные ограничения

- **Только project-scoped товары.** Standalone-товары из Telegram-бота вне охвата — требует расширения схемы `Product`.
- **Fact Checker — эвристика, не ML.** Regex-извлечение утверждений (вес/габариты/%/комплектация/гарантия/материал/цвет), сверка с паспортом с допуском ±5%. При противоречии предложение всё равно ставится в очередь с флагом `fact_check_contradicted=true` в metadata — решение остаётся за оператором при approve (консистентно с общей философией `DatabaseApprovalQueue`, где ничего не применяется без явного подтверждения).
- **Промпты не протестированы на реальной модели** — тесты используют скриптованные ответы; перед продакшн-релизом промпты (`prompts/*.yaml`) стоит прогнать на реальном провайдере (`AI_PROVIDER` в `.env`) и доработать по факту качества ответов.
- **Per-stage перегенерация не реализована.** Есть только полный `run` (все 4 LLM-стадии подряд); отдельные `POST .../title|benefits|description` для точечного перезапуска одной стадии — не реализованы в этой итерации, требуют существующих `content_strategy`/`semantic_plan` артефактов как входа.
- Известный существующий баг вне зоны этого модуля: `AI_PROVIDER` дефолт расходится между `app/config.py` (`"grok"`) и `providers/factory.py::create_configured_provider` (`"ollama"`).

---

## 7. Что готово для следующего этапа

Инфраструктура marketplace-agnostic (SEO-пороги, Semantic Planner,
Fact Checker не завязаны на Ozon) — расширение на Wildberries/Яндекс.Маркет
не требует изменений в `content_pipeline/`, только: (а) добавить/уточнить
пороги в `app/seo_rules.py` при необходимости, (б) прогнать существующие
промпты для новых площадок (поле `marketplace` в YAML уже поддерживает
per-marketplace варианты промптов через Prompt Registry).
