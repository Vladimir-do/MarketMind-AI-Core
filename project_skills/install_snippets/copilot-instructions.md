# GitHub Copilot Instructions

This repository contains a reusable skillpack in `project_skills/`.

When suggesting code, architecture, refactors, tests, or reviews:

- Treat `project_skills/.skillscheck` as the marker that the skillpack is active.
- Read `project_skills/SKILLPACK.md`.
- Read `project_skills/SKILL_TRIGGERS.md`.
- Use `project_skills/skills_index.json` to identify relevant skills.
- Use `project_skills/skills_database.md` for recipes and snippets.
- If a file contains `@skills:`, use those skill IDs as local architecture hints.
- Prefer existing skill patterns when they fit.
- Keep `skills_index.json` and `skills_database.md` synchronized.
- Before the final response of a session, follow `project_skills/SESSION_UPDATE_PROTOCOL.md`.

If the user asks `skillpack check`, answer exactly `SKILLPACK_LOADED`.

If the user asks `skillpack session close`, inspect the session for reusable skills and update the skillpack, create a pending proposal, or state that no reusable skills appeared.
