# Agent Instructions

This project uses an active local skillpack. Treat it as part of the engineering system, not as optional documentation.

## Startup Protocol

Before answering architecture questions, writing code, reviewing code, or creating new project patterns:

1. If `project_skills/.skillscheck` exists, the skillpack is active.
2. Read `project_skills/SKILLPACK.md`.
3. Read `project_skills/SKILL_TRIGGERS.md`.
4. Search `project_skills/skills_index.json` for relevant reusable skills.
5. Open `project_skills/skills_database.md` for the selected skill recipes.
6. Prefer existing skill patterns before inventing new ones.
7. If a file contains `@skills:`, read those skill IDs before editing it.

## Work Protocol

For substantial changes:

1. Name the relevant skill IDs internally before implementing.
2. Keep changes aligned with existing project contracts: parsers return `ProductData`, workers report progress, scrape attempts write telemetry, CLI modes stay resumable where possible.
3. Turn live bugs into regression tests.
4. Base regression claims on measurable signals: tests, scrape attempts, latency, statuses, traces, logs, or live smoke checks.
5. If measurements are unavailable, say so plainly instead of guessing.
6. For agent behavior/training changes, follow `docs/AGENT_TRAINING_PLAYBOOK.md`: normalize intent, plan with skills, expose missing executors, verify, then feed lessons back into the skillpack.
7. For parser changes, follow `docs/PARSING_CRAFT_PLAYBOOK.md`: prefer structured sources, layer fallbacks, normalize before saving, record telemetry, and cover the marketplace behavior with regression tests.

## Verification Protocol

Before final response after code changes:

1. Run focused tests for the changed area.
2. Run the full test suite when blast radius touches shared routing, workers, database, Telegram, parser contracts, CLI, exports, or skillpack.
3. Run live smoke checks when the feature depends on a real marketplace or real user file and it is safe to do so.
4. Report the exact verification signal, for example `102 tests OK`, `status=ok`, `http_status=200`, `latency_ms=3118`.

## Skillpack Update Protocol

Before the final answer of each session, follow `project_skills/SESSION_UPDATE_PROTOCOL.md`.

If the session introduced a reusable pattern, command, workaround, regression lesson, architecture decision, or missing skill:

1. Update an existing skill or add a new skill to `project_skills/skills_database.md`.
2. Update `project_skills/skills_index.json`.
3. Run:

```bash
python project_skills/validate_skills.py
```

If there is not enough information for a full skill, create a pending proposal in `project_skills/session_updates/`.

If no reusable skill appeared, say that in the final response.

## Test Phrases

If the user asks `skillpack check`, answer exactly:

```text
SKILLPACK_LOADED
```

If the user asks `skillpack session close`, inspect the session for reusable skills and update the skillpack, create a pending proposal, or state that no reusable skills appeared.
