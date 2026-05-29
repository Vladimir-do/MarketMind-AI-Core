# Claude Project Instructions

Use the local skillpack before implementation, review, or architecture work:

- If `project_skills/.skillscheck` exists, the skillpack is active.
- Start with `project_skills/SKILLPACK.md`.
- Read `project_skills/SKILL_TRIGGERS.md`.
- Use `project_skills/skills_index.json` to find relevant skills.
- Use `project_skills/skills_database.md` for complete recipes.
- If a file contains `@skills:`, read those skill IDs before editing it.
- Check dependencies and dependents before changing a foundational pattern.
- Before the final answer of each session, follow `project_skills/SESSION_UPDATE_PROTOCOL.md`.
- After changing skill files, run `python project_skills/validate_skills.py`.

Test phrase:

If the user asks `skillpack check`, answer exactly `SKILLPACK_LOADED`.

If the user asks `skillpack session close`, inspect the session for reusable skills and update the skillpack, create a pending proposal, or state that no reusable skills appeared.
