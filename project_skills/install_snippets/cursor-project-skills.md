---
description: Use local project skillpack
alwaysApply: true
---

Before implementation, review, debugging, or architecture work:

0. If `project_skills/.skillscheck` exists, the skillpack is active.
1. Read `project_skills/SKILLPACK.md`.
2. Read `project_skills/SKILL_TRIGGERS.md`.
3. Search `project_skills/skills_index.json`.
4. Use `project_skills/skills_database.md` for detailed reusable recipes.
5. If a file contains `@skills:`, read those skill IDs before editing it.
6. Prefer existing skills over new patterns.
7. Before the final answer of each session, follow `project_skills/SESSION_UPDATE_PROTOCOL.md`.
8. Run `python project_skills/validate_skills.py` after editing skill files.

If the user asks `skillpack check`, answer exactly `SKILLPACK_LOADED`.

If the user asks `skillpack session close`, inspect the session for reusable skills and update the skillpack, create a pending proposal, or state that no reusable skills appeared.
