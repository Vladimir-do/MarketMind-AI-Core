# MarketMind AI Demo Scenarios

These demos are designed for buyers, partners and technical reviewers. Each demo should be short, visible and tied to a business outcome.

## Demo 1. Ozon Card Generation

Goal: show the clearest commercial use case.

Audience: marketplace sellers, e-commerce agencies, automation studios.

### Story

A user gives product text or a product URL. MarketMind AI builds an Ozon card draft, researches competitor context when available, applies a profile and returns JSON/XLSX files.

### Flow

1. Start the Telegram bot.
2. Run `/profile` and show available profiles.
3. Select a profile, for example `/profile electronics`.
4. Run `/ozon_card`.
5. Send a product brief:

```text
Wireless 3-in-1 charging station, black, 15W, for iPhone, Apple Watch and AirPods, price 2490, 12-month warranty
```

6. Show the generated preview.
7. Show exported JSON/XLSX.
8. Mention fallback behavior: if competitor search or AI provider is unavailable, the local draft still works.

### What to emphasize

- Reduces manual card preparation.
- Supports profiles and required attributes.
- Produces buyer-readable artifacts, not just logs.
- Strongest module for productization.

### Proof points

- `app/card_filler.py`
- `app/card_profiles.py`
- `tests/test_card_filler.py`
- `tests/test_card_profiles.py`

## Demo 2. Marketplace Monitoring and Update

Goal: show operational marketplace intelligence.

Audience: scraping companies, marketplace analytics teams, sellers with many tracked items.

### Story

A user adds product URLs, the worker routes each URL to the right parser, stores price history and exposes scrape metrics/block diagnostics.

### Flow

1. Start the Telegram bot or CLI.
2. Add a marketplace URL through `/add`.
3. Run `/update` or:

```bash
py -3.11 -m app.main --update
```

4. Show recent attempts:

```bash
py -3.11 -m app.main --metrics 20
```

5. Show block diagnostics:

```bash
py -3.11 -m app.main --blocks 20
```

6. Export data through `/export_excel` or `/export_csv`.

### What to emphasize

- Central parser routing.
- Async worker with progress.
- Price history and export.
- Anti-bot events are measured instead of guessed.

### Proof points

- `app/parsers/router.py`
- `app/worker.py`
- `app/updater.py`
- `app/database.py`
- `tests/test_parsers.py`
- `tests/test_worker.py`
- `tests/test_database.py`

## Demo 3. Skillpack, Planner and Agent Loop

Goal: show why MarketMind AI is more than a normal parser.

Audience: technical buyers, potential cofounders, AI-agent startups.

### Story

The system turns a natural-language task into a structured task, builds a plan from available skills, shows missing/planned executors honestly, and uses an agent loop with classify/strategy/execute/evaluate/fallback stages.

### Flow

1. Show `project_skills/skills_index.json`.
2. Show selected skills:
   - `task-intent-engine`
   - `task-planner-skill-registry`
   - `skill-manifest-graph-execution-fsm`
   - `adaptive-block-memory-strategy`
   - `ozon-card-ai-enhancement`
3. Show `app/task_intents.py` turning text into a `StructuredTask`.
4. Show `app/task_planner.py` building a `TaskPlan`.
5. Show `app/agent_loop.py` stages.
6. Run focused tests:

```bash
.\.venv\Scripts\python.exe -m unittest tests.test_task_intents tests.test_task_planner tests.test_agent_loop -v
```

### What to emphasize

- Skills are reusable engineering recipes, not just documentation.
- Planner separates available, planned and missing capabilities.
- The repair workflow is regression-first and measurable.
- This is an extensible core that can become a SaaS or white-label engine.

### Proof points

- `project_skills/SKILLPACK.md`
- `project_skills/skills_index.json`
- `project_skills/skills_database.md`
- `app/task_intents.py`
- `app/task_planner.py`
- `app/skill_manifest.py`
- `app/agent_loop.py`
- `docs/AGENT_TRAINING_PLAYBOOK.md`
- `docs/SELF_HEALING_PLAYBOOK.md`

## Recording Tips

- Keep each video under 3 minutes.
- Show inputs and outputs, not long terminal noise.
- Use one clean product example.
- Avoid claiming full autonomy; say "agent-oriented workflow" and "prototype planner".
- End each demo with the generated artifact, test output or telemetry screen.
