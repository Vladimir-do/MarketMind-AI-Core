# Pending Skill Proposal: Claude API proxy isolation and credential readiness

Status: pending

## What Changed

The Anthropic SDK's default HTTPX client reads all proxy environment variables. On this host, `ALL_PROXY=socks://127.0.0.1:3067` was stale and used a scheme unsupported by HTTPX, while `HTTPS_PROXY=http://127.0.0.1:10809` was reachable. The Claude client now creates an explicit HTTPX async client with `trust_env=False`, selecting only HTTPS_PROXY/HTTP_PROXY (uppercase or lowercase), then passes it to `AsyncAnthropic`. This prevents an unrelated stale ALL_PROXY from breaking Claude requests and keeps proxy selection deterministic.

A live API request confirmed that the API key is accepted and the request reaches Anthropic; the provider rejected it only because the account credit balance is too low. Claude Pro subscription is separate from API credits.

## Verification

- `tests/test_ai_client.py`: 25 passed, including a regression test proving the invalid ALL_PROXY is ignored and the working HTTPS proxy is selected.
- Ruff targeted checks passed.
- Full project suite is running after this change; record its final result before promoting this proposal.

## Why It Is Reusable

Desktop VPN/proxy clients may export stale or nonstandard ALL_PROXY values alongside a working HTTP(S) proxy. SDKs that implicitly inherit all proxy variables can fail before making any network request. Explicit per-client proxy configuration with `trust_env=False` avoids mutating global environment state and makes API transport behavior testable.

## Candidate Skill

- ID: `python-sdk-explicit-proxy-configuration`
- Category: `network` or `integration`
- Source paths: `app/ai_client.py`, `tests/test_ai_client.py`
- Dependencies: `httpx`
- Maturity: pending; validate against another external SDK integration before promotion.
