# Web Route Security Review — 2026-11-20

Static review of selected FastAPI routes in the audit branch. No execution or exploit testing. These observations need deployment-context verification.

## W-01 — Broad CORS policy (confirmed configuration)
`app/web/app.py` uses `allow_origins=["*"]`, `allow_credentials=True`, `allow_methods=["*"]`, and `allow_headers=["*"]`. This is an unnecessarily broad configuration. Establish an explicit origin allowlist and enable credentials only if required. Add policy tests.

## W-02 — Import endpoint reads uploaded file without visible size limit (confirmed in inspected handler)
`app/web/routes/import_.py` `import_file` calls `await file.read()`, writes the complete bytes to a temporary file, then runs the pipeline. In this handler, no size limit is enforced before reading. Add a bounded streaming read, size limit and safe error response; also bound processing duration and cleanup. Verify reverse-proxy/server limits separately.

## W-03 — Import handler includes exception text in user-facing response (confirmed)
The import failure response constructs `message=f"Ошибка импорта: {exc}"`. Review for unintended disclosure of paths, parser internals, or library messages; return a stable generic message to users and log sanitized diagnostics server-side.

## W-04 — Route-level authentication not apparent in selected routes (unverified systemic issue)
Selected route functions do not show authentication checks directly. This does not establish that authentication is absent: middleware, deployment gateway or other protections may exist. Inspect the complete application/deployment configuration before making a security conclusion. If app is intended to be private/local, document that boundary and ensure it is enforced.

## W-05 — URL marketplace classification by substring in selected display routes (confirmed, low risk on inspected paths)
`dashboard.py`, `products.py`, and `product_detail.py` use substring checks for display classification (e.g. "ozon.ru" in URL). This is not itself an SSRF proof in these display-only helpers, but risks incorrect categorization of hostile lookalike URLs. Prefer shared parsed-host classification.

## W-06 — Per-product DB access in list routes (performance)
`products.py` loads products then queries latest price individually for each product. This is a potential N+1 query pattern. Consider a batched query or relationship/eager strategy and benchmark before refactoring.

## Recommended order
1. Apply bounded upload read / file-size controls.
2. Tighten CORS policy.
3. Sanitize user-visible exception handling.
4. Establish and test access-control boundary (app-level or deployment-level).
5. Consolidate host parsing for classification and review SSRF in actual fetchers.
6. Address N+1 after baseline performance measurements.

