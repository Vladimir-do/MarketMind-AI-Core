"""Competitor Analysis — поиск и сохранение конкурентов по маркетплейсам.

Переиспользует существующий live-поиск (app.parsers.router.search_all_marketplaces)
и уже готовый, но нигде не вызываемый WildberriesParser._fetch_reviews() —
ничего не парсит заново.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

import aiohttp

from app.competitor_analysis.store import CompetitorSnapshotStore
from app.content_pipeline.passport import build_passport
from app.effective_card.service import EffectiveProductCardService
from app.parsers.router import search_all_marketplaces
from app.parsers.wildberries import WildberriesParser, _build_wb_headers, _extract_wb_id

if TYPE_CHECKING:
    from app.database import CompetitorSnapshot, Database

logger = logging.getLogger(__name__)

_MAX_PER_MARKETPLACE = 5
_MAX_WB_REVIEWS_FETCHED = 3


class CompetitorAnalysisService:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._store = CompetitorSnapshotStore(db)

    async def refresh_competitors(
        self, project_id: str, product_id: int
    ) -> tuple[str, list[CompetitorSnapshot]]:
        card = await EffectiveProductCardService(self._db).get_effective_card(project_id, product_id)
        passport = build_passport(card)
        query = " ".join(passport.title.split())

        results = await search_all_marketplaces(query, max_per_site=_MAX_PER_MARKETPLACE)

        wb_products = results.get("wildberries") or []
        if wb_products:
            await self._attach_wb_reviews(wb_products, limit=_MAX_WB_REVIEWS_FETCHED)

        flat: list[tuple[str, object]] = [
            (marketplace, product) for marketplace, products in results.items() for product in products
        ]

        batch_id, records = await self._store.save_batch(
            project_id=project_id,
            project_product_id=passport.project_product_id,
            product_id=product_id,
            search_query=query,
            products=flat,
        )
        return batch_id, records

    @staticmethod
    async def _attach_wb_reviews(products: list, *, limit: int) -> None:
        """Дописывает тексты отзывов в product.reviews для топ-N WB результатов.

        Мутирует `products` на месте (по индексу) — важно передавать сюда
        оригинальный список (не срез-копию), иначе изменения потеряются.
        """
        parser = WildberriesParser()
        async with aiohttp.ClientSession(headers=_build_wb_headers()) as session:
            for index in range(min(limit, len(products))):
                product = products[index]
                nm_id = _extract_wb_id(product.url)
                if nm_id is None:
                    continue
                reviews = await parser._fetch_reviews(session, nm_id)
                if reviews:
                    products[index] = replace(product, reviews=reviews)
