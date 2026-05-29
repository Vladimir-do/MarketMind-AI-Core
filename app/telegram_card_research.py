from __future__ import annotations

from collections.abc import Awaitable, Callable


SearchFn = Callable[[str, int], Awaitable[list[dict]]]


async def build_card_research_message(query: str, search: SearchFn | None = None) -> str:
    from app.card_research import build_card_research_report
    from app.searcher import search_ozon

    search = search or search_ozon
    competitors = await search(query, 10)
    return await build_card_research_report(query, competitors)
