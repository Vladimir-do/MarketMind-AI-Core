# Agent Instructions

Before answering architecture questions, writing code, reviewing code, or creating new project patterns, use the local skillpack:

0. If `project_skills/.skillscheck` exists, the skillpack is active.
1. Read `project_skills/SKILLPACK.md`.
2. Read `project_skills/SKILL_TRIGGERS.md`.
3. Search `project_skills/skills_index.json` for relevant reusable skills.
4. Open `project_skills/skills_database.md` for the detailed recipe.
5. Prefer existing skill patterns over inventing new ones.
6. If a file contains `@skills:`, read those skill IDs before editing it.
7. Before the final answer of each session, follow `project_skills/SESSION_UPDATE_PROTOCOL.md`.
8. If skills are edited, run:

```bash
python project_skills/validate_skills.py
```

Test phrase:

If the user asks `skillpack check`, answer exactly:

```text
SKILLPACK_LOADED
```

If the user asks `skillpack session close`, inspect the session for reusable skills and update the skillpack, create a pending proposal, or state that no reusable skills appeared.
