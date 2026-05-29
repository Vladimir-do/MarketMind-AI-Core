"""
worker.py - orchestration for marketplace parsing from bot commands.
"""
import asyncio

from app.config import PROXY, logger
from app.database import Database
from app.parsers.router import MARKETPLACE_EMOJI, detect_marketplace
from app.parsers.wildberries import WildberriesParser
from app.parsers.yandex_market import YandexMarketParser
from app.resilience import resilience
from app.updater import OzonUpdater
from app.utils.error_research import research_parse_failure

MAX_CONCURRENT_UPDATES = 3


async def _wait_marketplace_window(marketplace: str, notify) -> None:
    if resilience.is_open(marketplace):
        remaining = resilience.cooldown_remaining(marketplace)
        mins = max(1, remaining // 60)
        await notify(
            f"{marketplace.title()} cooldown: {mins} мин. "
            "Жду окно, чтобы не усугублять блокировку."
        )
        await asyncio.sleep(max(1, remaining))
    await resilience.wait_rate_limit(marketplace)


async def _mark_block_and_alert(marketplace: str, notify) -> None:
    cooldown_sec = resilience.mark_block(marketplace)
    if cooldown_sec and resilience.should_emit_open_alert(marketplace):
        mins = max(1, cooldown_sec // 60)
        await notify(
            f"{marketplace.title()} ушел в защиту. "
            f"Circuit breaker открыт на {mins} мин."
        )


async def _recommend_strategy(db: Database, marketplace: str, url: str) -> dict:
    default = {
        "strategy": "normal",
        "skip": False,
        "skip_browser": False,
        "reason": "",
        "cooldown_sec": 0,
    }
    try:
        recommend = getattr(db, "recommend_scrape_strategy", None)
        if not recommend:
            return default
        decision = await recommend(marketplace, url=url)
        return {**default, **(decision or {})}
    except Exception as e:
        logger.debug(f"adaptive strategy unavailable: {e}")
        return default


async def worker_add_urls(db: Database, urls: list[str], notify, proxy: str = None) -> str:
    added = 0
    errors = 0

    for url in urls:
        marketplace = detect_marketplace(url)
        icon = MARKETPLACE_EMOJI.get(marketplace, "")
        if marketplace in {"wildberries", "ozon", "yandex_market"}:
            await _wait_marketplace_window(marketplace, notify)
            decision = await _recommend_strategy(db, marketplace, url)
            if decision.get("skip"):
                await notify(f"Пропускаю {marketplace}: {decision['reason']}")
                try:
                    await db.record_blocked_pattern(
                        url=url,
                        marketplace=marketplace,
                        source="strategy",
                        status="skipped",
                        trigger="adaptive_skip",
                        strategy=decision["strategy"],
                        cooldown_sec=decision.get("cooldown_sec", 0),
                    )
                except Exception:
                    pass
                errors += 1
                continue
            if decision.get("skip_api") and marketplace != "ozon":
                await notify(f"Skipping {marketplace} API route: {decision['reason']}")
                try:
                    await db.record_blocked_pattern(
                        url=url,
                        marketplace=marketplace,
                        source="strategy",
                        status="skipped",
                        trigger="adaptive_api_cooldown",
                        strategy=decision["strategy"],
                        cooldown_sec=decision.get("cooldown_sec", 0),
                    )
                except Exception:
                    pass
                errors += 1
                continue

        try:
            if marketplace == "wildberries":
                parser = WildberriesParser(attempt_recorder=db.record_scrape_attempt)
                data = await parser.fetch_product(url, proxy=proxy or PROXY or None)
                if data:
                    payload = data.to_dict()
                    payload["price"] = data.price
                    payload["availability"] = data.availability
                    await db.save_product(url, payload)
                    added += 1
                    resilience.mark_success("wildberries")
                    await notify(f"OK {icon} <b>{data.name[:60]}</b>\nЦена: {data.price} RUB | {data.availability}")
                else:
                    errors += 1
                    await _mark_block_and_alert("wildberries", notify)
                    await notify(f"WARN {icon} Не удалось получить данные:\n{url}")

            elif marketplace == "ozon":
                async with OzonUpdater(db, proxy=proxy or PROXY or None) as updater:
                    result = await updater.add_urls([url], callback=notify)
                added += result
                if result <= 0:
                    await _mark_block_and_alert("ozon", notify)
                else:
                    resilience.mark_success("ozon")

            elif marketplace == "yandex_market":
                parser = YandexMarketParser(attempt_recorder=db.record_scrape_attempt)
                data = await parser.fetch_product(url)
                if data:
                    payload = data.to_dict()
                    payload["price"] = data.price
                    payload["availability"] = data.availability
                    await db.save_product(url, payload)
                    added += 1
                    resilience.mark_success("yandex_market")
                    await notify(f"✅ {icon} <b>{data.name[:60]}</b>\n💰 {data.price} ₽ | {data.availability}")
                else:
                    errors += 1
                    await _mark_block_and_alert("yandex_market", notify)
                    await notify(f"⚠️ {icon} Не удалось получить данные:\n{url}")

            else:
                await notify(f"Неизвестный маркетплейс: {url}")
                try:
                    await research_parse_failure(
                        source="worker_unknown_marketplace",
                        url=url,
                        detail=f"detect_marketplace returned: {marketplace}",
                        marketplace="unknown",
                    )
                except Exception:
                    pass
                errors += 1

        except Exception as e:
            logger.exception(f"worker_add_urls error for {url}")
            await notify(f"Ошибка: {e}")
            try:
                await research_parse_failure(
                    source="worker_add_urls_exception",
                    url=url,
                    detail=str(e)[:400],
                    marketplace=marketplace if marketplace != "unknown" else None,
                )
            except Exception:
                pass
            errors += 1
            if marketplace in {"wildberries", "ozon", "yandex_market"}:
                await _mark_block_and_alert(marketplace, notify)

    result = f"Добавлено: <b>{added}</b> товаров"
    if errors:
        result += f" | Ошибок: {errors}"
    await notify(result)
    return result


async def worker_update_all(db: Database, notify, proxy: str = None) -> str:
    products = await db.get_all_products()
    wb_products = [p for p in products if "wildberries" in p.url]
    ozon_products = [p for p in products if "ozon" in p.url]
    yandex_products = [p for p in products if "market.yandex" in p.url]

    async def update_wildberries() -> tuple[int, list[dict]]:
        if not wb_products:
            return 0, []

        await notify(f"Updating {len(wb_products)} Wildberries products...")
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_UPDATES)

        async def update_product(product):
            async with semaphore:
                updated = 0
                changes = []
                await _wait_marketplace_window("wildberries", notify)
                decision = await _recommend_strategy(db, "wildberries", product.url)
                if decision.get("skip"):
                    await notify(f"Skipping WB {product.name[:50]}: {decision['reason']}")
                    try:
                        await db.record_blocked_pattern(
                            url=product.url,
                            marketplace="wildberries",
                            source="strategy",
                            status="skipped",
                            trigger="adaptive_skip",
                            strategy=decision["strategy"],
                            cooldown_sec=decision.get("cooldown_sec", 0),
                        )
                    except Exception:
                        pass
                    return updated, changes
                if decision.get("skip_api"):
                    await notify(f"Skipping WB API route {product.name[:50]}: {decision['reason']}")
                    try:
                        await db.record_blocked_pattern(
                            url=product.url,
                            marketplace="wildberries",
                            source="strategy",
                            status="skipped",
                            trigger="adaptive_api_cooldown",
                            strategy=decision["strategy"],
                            cooldown_sec=decision.get("cooldown_sec", 0),
                        )
                    except Exception:
                        pass
                    return updated, changes
                try:
                    async def record_wb_attempt(**kwargs):
                        await db.record_scrape_attempt(product_id=product.id, **kwargs)

                    parser = WildberriesParser(attempt_recorder=record_wb_attempt)
                    data = await parser.fetch_product(product.url, proxy=proxy or PROXY or None)
                    if data:
                        payload = data.to_dict()
                        _, price_changed = await db.save_product(product.url, payload)
                        updated = 1
                        resilience.mark_success("wildberries")
                        if price_changed:
                            changes.append({
                                "name": data.name,
                                "price": data.price,
                                "availability": data.availability,
                                "marketplace": "wildberries",
                            })
                            await notify(f"WB {data.name[:50]}: {data.price} RUB")
                    else:
                        await _mark_block_and_alert("wildberries", notify)
                except Exception as e:
                    logger.error(f"WB update error: {e}")
                    await _mark_block_and_alert("wildberries", notify)
                    try:
                        await research_parse_failure(
                            source="worker_wb_update_exception",
                            url=product.url,
                            detail=str(e)[:400],
                            marketplace="wildberries",
                        )
                    except Exception:
                        pass
                return updated, changes

        results = await asyncio.gather(*(update_product(product) for product in wb_products))
        updated = sum(result[0] for result in results)
        changes = [change for result in results for change in result[1]]
        return updated, changes

    async def update_ozon() -> tuple[int, list[dict]]:
        if not ozon_products:
            return 0, []

        await notify(f"Updating {len(ozon_products)} Ozon products...")
        await _wait_marketplace_window("ozon", notify)
        try:
            async with OzonUpdater(db, proxy=proxy or PROXY or None) as updater:
                updated, ozon_changes = await updater.update_all(callback=notify)
                if updated <= 0 and ozon_products:
                    await _mark_block_and_alert("ozon", notify)
                else:
                    resilience.mark_success("ozon")
                return updated, [{**c, "marketplace": "ozon"} for c in ozon_changes]
        except Exception as e:
            logger.error(f"Ozon update error: {e}")
            await _mark_block_and_alert("ozon", notify)
            try:
                await research_parse_failure(
                    source="worker_ozon_update_exception",
                    url=None,
                    detail=str(e)[:400],
                    marketplace="ozon",
                )
            except Exception:
                pass
            return 0, []

    async def update_yandex_market() -> tuple[int, list[dict]]:
        if not yandex_products:
            return 0, []

        await notify(f"Updating {len(yandex_products)} Yandex Market products...")
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_UPDATES)

        async def update_product(product):
            async with semaphore:
                updated = 0
                changes = []
                await _wait_marketplace_window("yandex_market", notify)
                decision = await _recommend_strategy(db, "yandex_market", product.url)
                if decision.get("skip"):
                    await notify(f"Skipping Yandex Market {product.name[:50]}: {decision['reason']}")
                    try:
                        await db.record_blocked_pattern(
                            url=product.url,
                            marketplace="yandex_market",
                            source="strategy",
                            status="skipped",
                            trigger="adaptive_skip",
                            strategy=decision["strategy"],
                            cooldown_sec=decision.get("cooldown_sec", 0),
                        )
                    except Exception:
                        pass
                    return updated, changes
                if decision.get("skip_api"):
                    await notify(f"Skipping Yandex Market HTML route {product.name[:50]}: {decision['reason']}")
                    try:
                        await db.record_blocked_pattern(
                            url=product.url,
                            marketplace="yandex_market",
                            source="strategy",
                            status="skipped",
                            trigger="adaptive_api_cooldown",
                            strategy=decision["strategy"],
                            cooldown_sec=decision.get("cooldown_sec", 0),
                        )
                    except Exception:
                        pass
                    return updated, changes
                try:
                    async def record_attempt(**kwargs):
                        await db.record_scrape_attempt(product_id=product.id, **kwargs)

                    parser = YandexMarketParser(attempt_recorder=record_attempt)
                    data = await parser.fetch_product(product.url)
                    if data:
                        payload = data.to_dict()
                        _, price_changed = await db.save_product(product.url, payload)
                        updated = 1
                        resilience.mark_success("yandex_market")
                        if price_changed:
                            changes.append({
                                "name": data.name,
                                "price": data.price,
                                "availability": data.availability,
                                "marketplace": "yandex_market",
                            })
                            await notify(f"Yandex Market {data.name[:50]}: {data.price} RUB")
                    else:
                        await _mark_block_and_alert("yandex_market", notify)
                except Exception as e:
                    logger.error(f"Yandex Market update error: {e}")
                    await _mark_block_and_alert("yandex_market", notify)
                    try:
                        await research_parse_failure(
                            source="worker_yandex_market_update_exception",
                            url=product.url,
                            detail=str(e)[:400],
                            marketplace="yandex_market",
                        )
                    except Exception:
                        pass
                return updated, changes

        results = await asyncio.gather(*(update_product(product) for product in yandex_products))
        updated = sum(result[0] for result in results)
        changes = [change for result in results for change in result[1]]
        return updated, changes

    results = await asyncio.gather(update_wildberries(), update_ozon(), update_yandex_market())
    updated = sum(result[0] for result in results)
    changes = [change for result in results for change in result[1]]

    if changes:
        lines = [f"Price changes ({len(changes)}):"]
        for ch in changes:
            icon = MARKETPLACE_EMOJI.get(ch.get("marketplace", ""), "")
            status = "OK" if ch["availability"] == "in_stock" else "NO"
            lines.append(f"{status} {icon} {ch['name'][:40]}: {ch['price']} RUB")
        report = "\n".join(lines)
    else:
        report = "No price changes found"

    summary = f"Update finished. Processed: <b>{updated}</b> products\n\n{report}"
    await notify(summary)
    return summary
