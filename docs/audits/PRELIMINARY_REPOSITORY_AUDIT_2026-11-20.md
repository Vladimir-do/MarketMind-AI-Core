# MarketMind AI Core — Preliminary Repository Audit (2026-11-20)

Scope: read-only inspection of the public repository main branch. No runtime execution, no secrets inspection, no destructive operations. Findings below are static observations, not confirmed exploitability.

## Confirmed observations

### A-01 — CORS is configured permissively (security review priority: high)
File: app/web/app.py
The app configures CORSMiddleware with allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]. This is a broad policy and deserves deliberate review. Replace with environment-configured explicit origins; credentials should only be enabled when needed. Add tests for expected origins and preflight behavior.

### A-02 — AI provider errors can be returned to callers (security/privacy review priority: medium)
File: app/ai_client.py
Provider exception handlers log exception details with repr/traceback and return error text containing exception type and message. Review whether upstream error messages may contain request details, provider response fragments, or sensitive context. Prefer safe user-facing error codes/messages and sanitized structured logs.

### A-03 — CI lint and formatting are broad and not clearly aligned with project's documented selective lint policy (maintenance priority: medium)
File: .github/workflows/ci.yml
CI runs `ruff check .` and `ruff format --check .`. AGENTS.md documents a narrower F821/F401/F841 command and says full-style cleanup is not automatic. Confirm the intended policy and make CI's enforcement explicit to avoid drift and unexpected large cleanup.

### A-04 — Documentation and roadmap need reconciliation (planning priority: medium)
README presents the current project shape, while several older audit documents contain historical snapshots and recommendations. The tree includes numerous phase reports and audits. Add a single dated source-of-truth status index with status labels (historical/current/verified/unverified) and links, instead of treating old reports as live evidence.

### A-05 — AI-provider availability/fallback logic should be tested against configuration (reliability priority: medium)
File: app/ai_client.py
The configured provider path and fallback path differ: explicit provider selection dispatches directly, while an unrecognized provider tries available keys in a fixed order. Verify intended behavior for invalid provider names, disabled AI, missing keys, timeouts, and error handling with a focused test matrix.

## Not yet verified
- Full test suite and CI state on the current commit.
- Actual CORS exploitability in deployment context.
- Whether provider exceptions leak secrets in practice.
- SSRF coverage across every URL fetcher and importer.
- Authentication/access control posture for web routes.
- Runtime database concurrency, migrations and backup/restore integrity.
- Dependency vulnerability status.
- Secret exposure in commit history (not inspected).

## Next safe audit stages
1. Inspect all web routes and middleware for access control, CSRF, upload validation and unsafe file paths.
2. Inspect URL fetching/parsing paths for SSRF, redirects, DNS/IP validation, timeouts and size limits.
3. Inspect database/migration/backup integrity and concurrency.
4. Inspect AI prompts/provider handling for privacy, injection boundaries, logging and timeout/retry behavior.
5. Inspect imports/exports for resource limits, formula injection and file path safety.
6. Review tests/CI and dependency pinning; run tests only in an isolated environment when available.

## Safety
This audit branch is additive and does not change main. Findings are provisional until tests and contextual inspection confirm them.
