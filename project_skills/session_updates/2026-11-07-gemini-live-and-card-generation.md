# MarketMind AI — Gemini live generation enabled (2026-11-07)

## Network / provider
- HAPP was switched to a different egress: AS200223 Etheron Hosting, Alkmaar, NL.
- Gemini TLS works through both HAPP local HTTP ports 10808 and 10809.
- Authenticated generation request through the production `OpenAICompatibleProvider` succeeded with `gemini-3.5-flash-lite`, response exactly `MARKETMIND_OK`.
- `.env` now sets `AI_HTTP_PROXY=http://127.0.0.1:10808`; Telegram continues using its separate SOCKS5 proxy on 10808.
- `marketmind-bot.service` restarted and is active.

## Card generation validation
- Ran the actual `build_enhanced_ozon_card_draft()` pipeline against Gemini using a sample product title: "Комплекс витаминов группы B и магний".
- Gemini returned a Russian SEO title, description, selling points, attributes/keywords and AI notes.
- The sample had no product-specific composition, dose, capsule count, photos, price, weight or dimensions; quality report correctly marked it not ready (score 21) and listed missing fields. This was a test fixture, not a claim that the real Ozon product was fully parsed.

## Safety improvement
- Strengthened system prompt for vitamins/supplements to prohibit invented manufacturer supply, dose, serving, form, quantity and use claims.
- Added deterministic post-processing for common unsupported supplement claims in descriptions and selling points.
- Replaced generic supplement fallback description with fact-conscious wording.
- Added regression test for removal of unverified manufacturer/usage claims.

## Validation
- Focused AI/provider/card/Telegram/marketplace regression suite: 96 passed, 2 existing BeautifulSoup deprecation warnings.
- `compileall` and `git diff --check`: passed.
- Bot service active after restart.

## Next step
- User should send the real Ozon product URL to their Telegram bot and inspect the generated draft. Ozon may still block source-page scraping; in that case the bot can recover only title/ID from URL and must request missing composition, dosage, package count, price and photos rather than invent them.
