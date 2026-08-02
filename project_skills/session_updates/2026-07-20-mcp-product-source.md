# Pending Skill Proposal: MCP Product Source Fallback

Status: pending

## Context

During Ozon field testing, direct Ozon API calls returned `403` from the current
network/IP. Browser fallback was intentionally skipped with
`OZON_SKIP_BROWSER_AFTER_API_BLOCK=1` to avoid burning Playwright attempts
against an already blocked route.

An opt-in MCP stdio product source was added as an alternative data route:

- `app/parsers/mcp_sources.py`
- `app/parsers/alt_sources.py`
- `app/parsers/ozon.py`
- `app/updater.py`

## Reusable Pattern

When a protected marketplace blocks direct API/browser fetching, call a separate
MCP server as an alternative source. Keep this source disabled by default and
configure it only through environment variables:

- `MARKETMIND_MCP_ENABLED`
- `MARKETMIND_MCP_COMMAND_JSON`
- `MARKETMIND_MCP_PRODUCT_TOOL`
- `MARKETMIND_MCP_PROTOCOL_VERSION`
- `MARKETMIND_MCP_TIMEOUT`

## Proposed Skill

Potential skill ID: `parser-mcp-product-source`

Category: `parser`

Dependencies:

- `parser-base-contract`
- `parser-marketplace-router`
- `playwright-ozon-stealth-fetch`
- `config-env-loader`

## Quality Rules

- MCP must be opt-in and disabled by default.
- Do not store secrets in source code or `.env.example`.
- Use JSON array command configuration to avoid shell quoting.
- MCP output must be normalized to the existing product dict/ProductData shape.
- MCP fallback must not bypass approval workflow or publish product-card changes.
- Existing parser routes must continue to work without an MCP server installed.

## Validation Added

- Unit tests for MCP payload normalization.
- Unit tests for MCP-first alternative source ordering.
- Unit tests for Ozon API-block fallback to alternative sources.
- Unit tests for adaptive `skip_api` and full `skip` falling back to alternative
  sources before browser launch.
- Stdio MCP client smoke with a fake local MCP server.
- Near-production field test with real Ozon URLs, real worker/update pipeline,
  temporary SQLite, real Ozon `403` responses, and fake local MCP stdio server:
  add path saved 3/3 products, update path processed 3/3 products, and no
  Playwright debug artifacts were created after adaptive skip handling was fixed.

## Open Items

- Connect a real Ozon-capable MCP server.
- Decide whether to promote this pending proposal into `skills_database.md`.
- Add production guidance for MCP server isolation and credential handling once
  the real server is selected.
