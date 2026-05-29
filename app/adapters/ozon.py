from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter

from app.core.enums import AvailabilityStatus, FetchStatus, Marketplace
from app.core.models import ProductSnapshot
from app.updater import OzonUpdater


async def fetch_ozon_snapshot(updater: OzonUpdater, url: str) -> tuple[ProductSnapshot, int | None, int]:
    """
    Возвращает (snapshot, http_status, latency_ms).
    Playwright сейчас не отдаёт http_status в текущей реализации — поэтому None.
    """
    t0 = perf_counter()
    data = await updater.process_url(url)
    latency_ms = int((perf_counter() - t0) * 1000)

    if not data:
        snap = ProductSnapshot(
            marketplace=Marketplace.OZON,
            url=url,
            fetched_at=datetime.now(timezone.utc),
            fetch_status=FetchStatus.BLOCKED,
            availability=AvailabilityStatus.UNKNOWN,
            raw=None,
        )
        return snap, None, latency_ms

    availability = data.get("availability") or "unknown"
    if availability == "in_stock":
        av = AvailabilityStatus.IN_STOCK
    elif availability == "out_of_stock":
        av = AvailabilityStatus.OUT_OF_STOCK
    else:
        av = AvailabilityStatus.UNKNOWN

    snap = ProductSnapshot(
        marketplace=Marketplace.OZON,
        url=url,
        fetched_at=datetime.now(timezone.utc),
        fetch_status=FetchStatus.OK,
        availability=av,
        name=data.get("name"),
        price=data.get("price"),
        image_url=data.get("image_url"),
        raw=None,
    )
    return snap, None, latency_ms

