# MarketMind AI — Claude Code project instructions

## Source of truth
- Read `AGENTS.md` before any implementation. It contains the project's binding engineering, security, testing, and Git rules.
- Treat `project_skills/.skillscheck` as activation of the project skillpack.
- Before substantial work, read `project_skills/SKILLPACK.md`, `project_skills/SKILL_TRIGGERS.md`, and relevant skill cards from `skills_index.json` / `skills_database.md`.
- Follow `project_skills/SESSION_UPDATE_PROTOCOL.md` at the end of substantial engineering sessions.
- Follow the graphify instructions below when the graph exists.

## Safe workflow
1. Start with `git status --short --branch`, inspect the existing diff, and identify user-owned changes. Never overwrite, stage, revert, reset, clean, or commit unrelated work.
2. Inspect only the relevant files and tests. Prefer small changes over refactors.
3. Before editing shared database, parser, Telegram, pipeline, AI-provider, or web routing code, explain the plan and blast radius.
4. Do not read, print, copy, or expose `.env`, credentials, tokens, private keys, cookies, or browser profiles. Use placeholders in examples.
5. Never call paid APIs, use API credits, change billing, or add paid services. Use only the user's already-authorized subscription allowance; stop if billing is unclear.
6. Never run migrations against real data, deploy, publish, push, or change remote Git state without explicit approval.
7. Do not start Docker, broad browser automation, multiple agents, parallel full test suites, or resource-heavy jobs without a clear need and permission.
8. Never claim a fix is complete until relevant checks have actually passed.

## Verification
- Use the existing virtual environment: `.venv/bin/python`.
- Focused tests first; full suite only when the change's blast radius requires it.
- Ruff safety check:
  `RUFF_CACHE_DIR=/tmp/marketmind-ai-core-ruff .venv/bin/python -m ruff check app tests --select F821,F401,F841`
- Skillpack validation after skillpack changes:
  `.venv/bin/python project_skills/validate_skills.py`
- Do not run broad automatic formatting or `ruff --fix` across the repository.

## Graphify
- If `graphify-out/graph.json` exists, use `graphify query "<question>"` for scoped codebase questions.
- Use `graphify path` / `graphify explain` when relationship or concept context is needed.
- After modifying source code, run `graphify update .` when available; do not update the graph for editor-only configuration changes.
