# Project Skillpack

This folder is a reusable engineering skill base extracted from the project.

## How To Use

1. Read `skills_index.json` first.
2. Select relevant skills by `id`, `category`, `complexity`, `maturity`, `priority`, `dependencies`, or `dependents`.
3. Open `skills_database.md` for the full human-readable recipe.
4. Prefer existing skills and patterns before inventing new ones.
5. If you add, rename, or remove a skill, update both `skills_database.md` and `skills_index.json`.
6. After changes, run:

```bash
python project_skills/validate_skills.py
```

7. At the end of every session, follow `SESSION_UPDATE_PROTOCOL.md`.

## Important Rules For Agents

- Do not treat this as a technology list. Treat it as reusable development recipes.
- If `project_skills/.skillscheck` exists, this skillpack is active.
- Read `SKILL_TRIGGERS.md` to understand keyword triggers and `@skills:` markers.
- Use skill IDs when referencing patterns in plans, code reviews, or implementation notes.
- Check `dependents` before changing a foundational skill.
- Use `missing_skills_prioritized.yaml` as the improvement backlog.
- If a needed skill is missing, add it with a stable ID, category, dependencies, maturity, and source paths.

## Main Files

- `skills_index.json` - machine-readable catalog.
- `skills_database.md` - detailed skill cards.
- `missing_skills_prioritized.yaml` - prioritized missing skills.
- `architecture_review.md` - architecture risks and roadmap.
- `validate_skills.py` - drift validator.
- `INSTRUCTION_CHEATSHEET.md` - how to connect this skillpack to different AI tools.
- `.skillscheck` - marker file that tells agents the skillpack is active.
- `SKILL_TRIGGERS.md` - keyword triggers, `@skills:` comments and pyproject marker.
- `SESSION_UPDATE_PROTOCOL.md` - required end-of-session update workflow.
- `session_updates/` - inbox for pending skill proposals.
