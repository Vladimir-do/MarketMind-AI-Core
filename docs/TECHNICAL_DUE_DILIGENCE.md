# MarketMind AI Technical Due Diligence

This document is a buyer-facing truth map. It separates what works today from what is prototype-level and what should be built before selling MarketMind AI as a SaaS.

## Works Today

| Area | Evidence |
|---|---|
| Telegram and CLI entrypoints | `app/main.py`, `app/bot.py` |
| Product monitoring flow | `app/worker.py`, `app/updater.py`, `app/database.py` |
| Parser routing | `app/parsers/router.py`, `tests/test_parsers.py` |
| Ozon/WB/Yandex/FunPay parser modules | `app/parsers/` |
| Price history and exports | `app/database.py`, `app/exporter.py`, `tests/test_exports.py` |
| HTML reports | `app/reporter.py`, `templates/report_template.html` |
| Ozon card draft/export | `app/card_filler.py`, `tests/test_card_filler.py` |
| Card profiles | `app/card_profiles.py`, `profiles/*.yaml`, `tests/test_card_profiles.py` |
| Scrape attempt/block telemetry | `app/database.py`, `tests/test_database.py` |
| Skillpack documentation and index | `project_skills/` |

## Prototype / Usable Core

| Area | Current State | Buyer-Safe Claim |
|---|---|---|
| Natural-language intent router | Implemented with tests, still evolving | "Prototype intent layer" |
| Task planner | Builds plans and exposes missing skills | "Planner core exists" |
| Agent loop | Classify/strategy/execute/evaluate/fallback model | "Agent-oriented workflow" |
| Skill manifest graph | YAML manifests, dependency/fallback model | "Skill graph prototype" |
| Execution FSM | State model exists | "Execution lifecycle foundation" |
| Self-healing | Playbooks and regression-first workflow | "Measured repair process" |
| Generic scraping | Universal extraction and classification work | "Generic scraper foundation" |

## Planned / Not Yet Productized

| Area | Needed For |
|---|---|
| FastAPI layer | External API and integrations |
| Multi-user auth/roles | SaaS or agency accounts |
| Postgres + Alembic | Production persistence |
| Queue/scheduler | Reliable batch jobs |
| Dashboard | Buyer-friendly operations UI |
| Billing/subscriptions | SaaS monetization |
| Seller API validation | Production Ozon card compliance |
| Deployment scripts | Repeatable installation |
| Observability dashboard | Business-grade monitoring |
| Public demo dataset | Safe repeatable demos |

## Main Technical Strengths

- Clear marketplace specialization.
- Ozon card generation is commercially concrete.
- Skillpack creates reusable engineering memory.
- Planner/agent loop gives an extensible architecture path.
- Telemetry and block memory make scraping failures observable.
- Tests cover many core areas rather than only happy-path scripts.

## Main Risks

- `app/bot.py` is still large and should continue being decomposed.
- Marketplace scraping can break due to anti-bot changes.
- Some older Russian docs/strings may show mojibake in Windows console if encoding is misconfigured.
- Agent/planner layer is promising but not a fully autonomous production runtime.
- SaaS packaging is missing: API, UI, auth, billing, deployment and support docs.
- Live marketplace demos require safe URLs and controlled network/proxy setup.

## Suggested Buyer Verification

Run focused tests:

```bash
.\.venv\Scripts\python.exe -m unittest tests.test_card_filler tests.test_card_profiles tests.test_task_planner tests.test_agent_loop -v
```

Run broader local suite:

```bash
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Inspect CLI diagnostics:

```bash
py -3.11 -m app.main --metrics 20
py -3.11 -m app.main --blocks 20
```

Inspect key source files:

```text
app/card_filler.py
app/task_intents.py
app/task_planner.py
app/agent_loop.py
app/skill_manifest.py
app/updater.py
app/worker.py
app/database.py
project_skills/skills_index.json
project_skills/skills_database.md
```

## Honest Sale Position

Best sale framing:

> MarketMind AI is a working marketplace automation core with strong Ozon card generation, marketplace parsers, exports, telemetry and an agent-oriented skill/planner architecture.

Avoid selling it as:

> Finished autonomous SaaS platform.

The best buyer is someone who values a large head start and can productize the core into a white-label tool, internal automation system or SaaS.
