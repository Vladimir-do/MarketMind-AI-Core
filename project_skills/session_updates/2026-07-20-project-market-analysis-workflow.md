# Pending Skill Proposal: Project Market Analysis Workflow

Status: pending

## What changed

Added a project-scoped market analysis workflow:

- web page: `GET /projects/{project_id}/market-analysis`;
- API endpoint: `POST /api/projects/{project_id}/market-analysis`;
- shared helper module: `app/market_analysis.py`;
- HTMX result template for empty and successful marketplace search;
- regression coverage in `tests/test_client_projects.py`.

The workflow accepts a marketplace query, uses existing marketplace search contracts,
converts `ProductData` into a generated CSV-compatible import source, stores that source
as a project file, then reuses the existing project import pipeline.

## Why this is reusable

This pattern is useful whenever a user wants the project to start from market discovery
instead of a manual CSV/XLSX import. The key reusable decision is to keep market search
outside the project database mutation path, then import found candidates through the
same source-file and approval-compatible project pipeline.

## Candidate skill

ID suggestion: `project-market-analysis-import-workflow`

Category: `workflow`

Dependencies:

- `parser-base-contract`
- `parser-marketplace-router`
- `background-worker-progress`
- `parsing-craft-playbook`

Source paths:

- `app/market_analysis.py`
- `app/web/routes/projects.py`
- `app/web/templates/project_market_analysis.html`
- `app/web/templates/project_market_analysis_result.html`
- `tests/test_client_projects.py`

## Quality rules captured

- Do not create fake products when marketplace search returns nothing.
- Preserve `ProductData` as the parser contract and avoid raw marketplace dicts in project routes.
- Reuse the existing import pipeline so source files, provenance, SEO, exports, and reports stay consistent.
- Keep duplicate generated analysis imports explicit and deterministic.
- Cover the route with patched parser results so CI does not depend on live marketplace availability.
- Preserve marketplace facts in project snapshots, not only in raw attributes: `sku`, `category`, `source_url`, `image_urls`, `old_price`, discount and dimensions should round-trip into effective cards when known.
- Treat missing weight/dimensions differently for `source=market_analysis` candidates because search listings often cannot provide those facts. Do not show unavailable marketplace-listing facts as primary product defects.
- Reject ultra-broad discovery queries such as `все`/`all` before calling marketplace search. They produce mixed-category junk, fake categories and unusable niche analysis.
- Import mapping must preserve enum-like availability strings (`in_stock`, `out_of_stock`, `unknown`) instead of treating every non-numeric availability value as in-stock.
- Natural-language project tasks should be normalized before marketplace search. A phrase like `сегодня ищем нишу на рынке чем торговать прибыльнее` should expand into bounded concrete starter hypotheses instead of being sent to WB as one literal broad query.
- Marketplace search results need a relevance gate before import. Require overlap between meaningful query tokens and product title/brand/category, deduplicate normalized titles, and treat missing WB search stock rows as `unknown` instead of false `out_of_stock`.
- Open-ended profit wording variants such as `сегодня мы ищем чем выгодней торговать` must be detected before concrete-query extraction. Otherwise words like `торговать/выгодней` become a literal marketplace query and retrieve text-matching junk.
- Keep market metrics out of SEO-facing descriptions. Rating, review count, price and discount belong in attributes/report fields; the generated description should remain product/niche oriented so semantic-core and SEO audits do not learn service words like `рыночные`, `данные`, `рейтинг`, `отзывов`.
- Approval workflow must have an explicit apply phase. For project-scoped SEO suggestions, `approve` should create and apply a project card draft through `ProductCardEditorService`, persist a version for rollback, and mark `ApprovalRecord.applied_at`; merely changing the queue status to `approved` is not enough.
- Suggestion metadata is part of the routing contract. Preserve `project_id`, `project_product_id`, and `product_name` when approving/rejecting records, otherwise the UI cannot connect an approved AI suggestion back to the effective project card.
- SEO keyword/tag suggestions should normalize comma/semicolon strings into a list before persistence and semantic-core analysis, otherwise downstream code may treat a string as character tokens.
- Approval apply must be idempotent for duplicate queued suggestions. If the requested field value is already present in the effective card, mark the approval as applied with before/after snapshots instead of raising a no-diff editor validation error.
- For templates that can reload while a dev server is already running, avoid adding new custom Jinja filters unless the Python process is restarted. Prefer inline safe formatting or route-provided display fields for small UI labels such as project creation timestamps.

## Follow-up

Telegram should call the same market analysis helper through a progress-aware command instead of duplicating search/import logic in `app/bot.py`.
