# MarketMind AI — AI provider network diagnosis (2026-11-07)

## Code change
- Production card generation uses `create_configured_provider()` -> `OpenAICompatibleProvider.complete()`.
- `aiohttp` did not inherit proxy environment variables. Provider now explicitly resolves `AI_HTTP_PROXY` / standard HTTP(S)_PROXY and passes `proxy=`.
- `AI_HTTP_PROXY=direct|none|off` now explicitly bypasses HTTP proxy variables. Applied `AI_HTTP_PROXY=direct` in local `.env`; Telegram transport uses its separate proxy configuration.
- Added tests for explicit proxy routing and direct-mode bypass.

## Live network diagnosis
- Direct IPv4 egress country: NL; IP-info ASN/org: AS60404 Liteserver, city Alkmaar (public IP not recorded here).
- HAPP HTTP proxy ports 10808 and 10809 exit through the same country/provider.
- Through HAPP, CONNECT succeeds but TLS to `generativelanguage.googleapis.com:443` is rejected with `TLS alert handshake failure`. Other Google hosts and Telegram API work through HAPP.
- Direct TLS to Gemini API succeeds, but an authenticated generation request returns HTTP 400 `FAILED_PRECONDITION`: `User location is not supported for the API use.` The same error is returned by the actual production `OpenAICompatibleProvider` path.
- IPv6 is unavailable on this connection.
- Google lists the Netherlands as a supported Gemini API region, so this appears to be an IP/network geolocation or reputation classification problem for this egress range, not a bad API key or model. Google developer forum has recent reports of the same error from Netherlands-hosted servers; Google's moderator recommends testing another network / mobile hotspot and reporting the IP issue.

## Validation
- Focused AI/card/Telegram/marketplace suite: 95 passed, 2 existing BeautifulSoup deprecation warnings.
- Compileall and `git diff --check`: passed.
- Real generation is still blocked by Google's HTTP 400 location check. Do not claim the AI generation is operational until a request succeeds.

## Next action
- Test the same configured API key from a different egress network (e.g. phone hotspot without VPN) or change HAPP to a different supported-region exit IP/provider. If the request still gets the same 400, submit Google's IP/location issue report.
