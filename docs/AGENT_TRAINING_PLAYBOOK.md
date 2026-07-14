# Parser Agent Training Playbook

This playbook describes how to teach the parser agent to work reliably without
fine-tuning a model checkpoint. In this project, "training" means tightening the
agent's operating loop, skill manifests, regression tests, telemetry and
session memory.

For live bug reports and repair requests, use
`docs/SELF_HEALING_PLAYBOOK.md` first. Training changes should still feed the
lesson back into the skillpack after the fix is verified.

## Goal

The agent should not guess a handler from one keyword. It should:

1. Convert user text into a `StructuredTask`.
2. Build a `TaskPlan` from the skill registry.
3. Refuse silent execution when a required skill is `missing` or `planned`.
4. Execute only available skills through existing contracts.
5. Record measurable signals: tests, scrape attempt status, latency, errors,
   block patterns or generated files.
6. Turn repeated failures and useful workarounds into skillpack updates.

## Core Rules

- Treat multiline user input as one technical task, not as separate commands.
- If a URL is present, work with that URL and do not replace it with marketplace
  search unless the user explicitly asks for search.
- Parser code must return `ProductData` or a list of `ProductData`.
- Worker code must report progress and preserve resumability.
- Scrape attempts must write telemetry when parsing touches a real marketplace.
- Missing executors must become visible plan steps, not silent fallback behavior.
- Live marketplace bugs should get regression tests or a pending skill proposal.

## Training Loop

1. Collect examples
   - Good user prompts.
   - Failed prompts.
   - Marketplace block pages.
   - Parser exceptions.
   - Expected output files.

2. Normalize intent
   - Add or update tests in `tests/test_task_intents.py`.
   - Keep fields separate from requirements.
   - Preserve context across follow-up messages.
   - For URL scraping tasks, set a domain-level `parameters["task_type"]`
     before execution, for example `product_catalog`, `restaurant_menu`,
     `freelance_project`, `article`, `api_source`, or `universal_page`.
     This domain type should decide the executor/schema before generic product
     extraction starts.

3. Plan before execution
   - Add or update tests in `tests/test_task_planner.py`.
   - Mark new skills as `missing` until an executor exists.
   - Keep `quality.self_critic` last.

4. Implement the smallest safe executor
   - Use existing parser/router/worker/database contracts.
   - Add telemetry for scrape attempts and adaptive block decisions.
   - Avoid marketplace-specific dicts outside parser boundaries.

5. Verify
   - Run focused tests for the touched layer.
   - Run the full suite for shared routing, workers, parser contracts, CLI,
     database, Telegram or skillpack changes.
   - Run live smoke checks only when safe and necessary.

6. Feed the lesson back
   - Update `project_skills/skills_database.md` and
     `project_skills/skills_index.json`, or create a pending proposal in
     `project_skills/session_updates/`.
   - Run `python project_skills/validate_skills.py` after skillpack edits.

## What To Improve First

1. Unknown intent fallback
   - Add a friendly clarification path for low-confidence tasks.
   - Keep it non-executing until confidence improves.

2. Generic scraping executor
   - Start with safe HTML fetch, timeout, user-agent, parse validation and
     pagination detection.
   - Keep browser fallback explicit and telemetry-backed.

3. Execution telemetry
   - Persist per-step status, latency, selected fallback and validation result.
   - Feed repeated failures into pending skill proposals.

4. Russian text integrity
   - Add a lightweight check that user-facing Russian strings render correctly.
   - Do not add new mojibake strings to prompts, bot answers or docs.

## Definition Of Done

The agent is "trained" for a behavior when there is:

- a representative user prompt;
- an intent regression test;
- a planner regression test when skills are involved;
- an executor or an explicit missing skill;
- measurable verification output;
- a skillpack update or a conscious "no reusable skill" decision.
