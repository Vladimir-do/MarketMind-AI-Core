# Import Image Fetcher SSRF Review — 2026-11-21

Static review only; no network execution.

## I-01 — Source URL image enrichment can fetch arbitrary HTTP(S) destinations
File: app/importers/image_fetcher.py
The helper normalizes URLs to HTTP/HTTPS and calls urllib.request.urlopen with a timeout. No hostname allowlist, IP-range filtering, DNS resolution policy, redirect revalidation, or response byte limit beyond a read cap is visible in this module. This may expose a server-side request forgery surface if source URLs are attacker-controlled and the importer is run in a networked environment. A read cap of 1.2 MB exists for response content, but the initial request and redirect behavior still require policy controls.

Suggested remediation before use in exposed or untrusted workflows:
- Enforce an explicit allowed-host policy where feasible (marketplace/source allowlist).
- If arbitrary URLs are a product requirement, resolve and reject loopback, private, link-local, multicast, reserved and unspecified IP addresses; account for IPv4/IPv6 and DNS rebinding.
- Disable automatic redirects or revalidate every redirect target before following.
- Bound total response bytes and verify content-type, with request timeout.
- Add tests using mocked resolver/request layers to cover private IPs, mixed DNS, redirects and malformed URLs.
- Avoid testing by sending requests to internal or real third-party targets.

## Status
Not patched in this review because the safe redirect/DNS behavior requires a deliberate transport implementation and comprehensive tests. This is a prioritized finding, not a confirmed exploit.
