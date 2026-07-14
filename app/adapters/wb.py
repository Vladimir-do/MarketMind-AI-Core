from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter

from app.core.enums import AvailabilityStatus, FetchStatus, Marketplace
from app.core.models import ProductSnapshot
from app.parsers.wildberries import WildberriesParser


async def fetch_wb_snapshot(url: str, proxy: str | None = None) -> tuple[ProductSnapshot, int | None, int]:
    """
    Возвращает (snapshot, http_status, latency_ms).
    """
    t0 = perf_counter()
    parser = WildberriesParser()
    data = await parser.fetch_product(url, proxy=proxy)
    latency_ms = int((perf_counter() - t0) * 1000)

    if not data:
        snap = ProductSnapshot(
            marketplace=Marketplace.WILDBERRIES,
            url=url,
            fetched_at=datetime.now(timezone.utc),
            fetch_status=FetchStatus.BLOCKED,
            availability=AvailabilityStatus.UNKNOWN,
            raw=None,
        )
        return snap, None, latency_ms

    snap = ProductSnapshot(
        marketplace=Marketplace.WILDBERRIES,
        url=url,
        fetched_at=datetime.now(timezone.utc),
        fetch_status=FetchStatus.OK,
        availability=AvailabilityStatus.IN_STOCK if data.availability == "in_stock" else AvailabilityStatus.OUT_OF_STOCK,
        name=data.name,
        price=int(data.price) if data.price is not None else None,
        image_url=data.image_url,
        raw=None,
    )
    return snap, None, latency_ms

