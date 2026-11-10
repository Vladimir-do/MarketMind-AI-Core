# MarketMind AI — adaptive Ozon skip fallback fix (2026-11-07)

## User-reported regression
- Resubmitting Ozon URL 823223431 produced: “Пропускаю ozon: same URL recently blocked by browser” and “Добавлено: 0 товаров | Ошибок: 1”.
- Root cause: worker_add_urls had provisional-save fallback only after OzonUpdater.add_urls returned 0. The adaptive strategy `decision.skip` branch used `continue` before reaching that fallback.

## Fix
- Extracted `_save_ozon_provisional_url(db, url, notify)` helper.
- The adaptive skip branch now invokes the helper for Ozon before continuing. It does not retry the blocked site; it persists URL-derived draft metadata only.
- The ordinary failed-scrape branch reuses the same helper.
- It stores URL, URL-slug title, no price, no image, availability=`blocked`; tells user the title is unverified and includes Ozon article ID when present.
- It still records adaptive skip telemetry and increments errors; final response also reports draft links saved.

## Validation
- Added regression test for recently blocked Ozon URL being saved when strategy skips scraping.
- Targeted suite: 43 passed, 2 warnings.
- `git diff --check` passed.
- `python -m compileall -q app tests` passed.
- Restarted marketmind-bot.service; service active.
