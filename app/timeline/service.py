"""Timeline service orchestrating repository reads and event building."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.timeline.builder import ProductHistoryBuilder
from app.timeline.schemas import ProductTimeline, TimelineFilter, TimelinePageInfo, TimelinePagination

if TYPE_CHECKING:
    from datetime import datetime

    from app.database import Product
    from app.timeline.repository import TimelineRepository


class TimelineService:
    """Builds paginated product timelines from source tables."""

    def __init__(
        self,
        repository: TimelineRepository,
        builder: ProductHistoryBuilder | None = None,
    ) -> None:
        self._repository = repository
        self._builder = builder or ProductHistoryBuilder()

    async def get_product(self, product_id: int) -> Product | None:
        return await self._repository.get_product(product_id)

    async def build_timeline(
        self,
        *,
        product: Product,
        event_type: str = "all",
        source: str = "all",
        limit: int = 50,
        offset: int = 0,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        sort: str = "newest_first",
    ) -> ProductTimeline:
        safe_limit = max(1, min(limit, 200))
        safe_offset = max(offset, 0)
        safe_sort = sort if sort in {"newest_first", "oldest_first"} else "newest_first"

        price_history = await self._repository.get_price_history(
            product.id,
            date_from=date_from,
            date_to=date_to,
        )
        approval_records = await self._repository.get_approval_records(
            product.id,
            date_from=date_from,
            date_to=date_to,
        )

        filters = TimelineFilter(
            event_type=event_type,
            source=source,
            date_from=date_from,
            date_to=date_to,
        )
        pagination = TimelinePagination(
            limit=safe_limit + 1,
            offset=safe_offset,
            sort=safe_sort,
        )
        events, warnings = self._builder.build_with_warnings(
            product=product,
            price_history=price_history,
            approval_records=approval_records,
            filters=filters,
            pagination=pagination,
        )
        visible_events = events[:safe_limit]
        has_more = len(events) > safe_limit
        return ProductTimeline(
            product_id=product.id,
            items=visible_events,
            pagination=TimelinePageInfo(
                limit=safe_limit,
                offset=safe_offset,
                next_offset=safe_offset + safe_limit if has_more else None,
                total_returned=len(visible_events),
                has_more=has_more,
                sort=safe_sort,
            ),
            warnings=warnings,
        )
