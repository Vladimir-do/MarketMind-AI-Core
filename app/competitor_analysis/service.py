"""Competitor Analysis — поиск и сохранение конкурентов по маркетплейсам.

Переиспользует существующий live-поиск (app.parsers.router.search_all_marketplaces)
и уже готовый, но нигде не вызываемый WildberriesParser._fetch_reviews() —
ничего не парсит заново.
"""

from __future__ import annotations

import logging
import re
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
_MAX_OZON_REVIEW_FETCHED = 2

# Same class of bug as D31 (app/card_filler.py::_filter_relevant_competitors):
# search_all_marketplaces() is a plain full-text search on the product's own
# title -- a brand name that collides with an unrelated real product (e.g. a
# niche brand matching a well-known cosmetics/appliance brand) returns
# results from a completely different product category. Require at least one
# shared word stem with the product's own title/category (brand words
# excluded on both sides) before trusting a marketplace hit as an actual
# competitor. This mirrors card_filler.py's algorithm, but operates on
# ProductPassport/ProductData here instead of OzonCardDraft/dict -- unifying
# the two into one shared utility is a separate, broader change, not part of
# this fix.
_COMPETITOR_STOP_WORDS = {
    "для",
    "или",
    "без",
    "при",
    "под",
    "над",
    "товар",
    "шт",
    "набор",
    "ozon",
    "wb",
    "wildberries",
    "черный",
    "белый",
}


def _product_type_stems(title: str, category: str | None, brand: str | None) -> set[str]:
    brand_tokens = {w.lower()[:5] for w in re.findall(r"[A-Za-zА-Яа-яЁё]{2,}", brand or "")}
    stems: set[str] = set()
    for source in (title or "", category or ""):
        for word in re.findall(r"[A-Za-zА-Яа-яЁё0-9+]{3,}", source.lower()):
            if word in _COMPETITOR_STOP_WORDS or word.isdigit():
                continue
            stem = word[:5]
            if stem in brand_tokens:
                continue
            stems.add(stem)
    return stems


def _is_relevant_competitor(product: object, type_stems: set[str]) -> bool:
    if not type_stems:
        return True
    name = (getattr(product, "name", "") or "").lower()
    comp_stems = {word[:5] for word in re.findall(r"[A-Za-zА-Яа-яЁё0-9+]{3,}", name)}
    return bool(comp_stems & type_stems)


class CompetitorAnalysisService:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._store = CompetitorSnapshotStore(db)

    async def refresh_competitors(self, project_id: str, product_id: int) -> tuple[str, list[CompetitorSnapshot]]:
        card = await EffectiveProductCardService(self._db).get_effective_card(project_id, product_id)
        passport = build_passport(card)
        query = " ".join(passport.title.split())

        results = await search_all_marketplaces(query, max_per_site=_MAX_PER_MARKETPLACE)

        type_stems = _product_type_stems(passport.title, passport.category, passport.brand)
        results = {
            marketplace: [p for p in products if _is_relevant_competitor(p, type_stems)]
            for marketplace, products in results.items()
        }

        wb_products = results.get("wildberries") or []
        if wb_products:
            await self._attach_wb_reviews(wb_products, limit=_MAX_WB_REVIEWS_FETCHED)

        ozon_products = results.get("ozon") or []
        if ozon_products:
            await self._attach_ozon_review_signals(ozon_products, limit=_MAX_OZON_REVIEW_FETCHED)

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

    @staticmethod
    async def _attach_ozon_review_signals(products: list, *, limit: int) -> None:
        """Fetch lightweight Ozon product API data for a few top competitors.

        Only explicit review text and rating fields returned by Ozon are attached;
        blocked, missing, or malformed responses leave the original result intact.
        """
        from app.parsers.ozon import OzonParser

        parser = OzonParser()
        for index in range(min(limit, len(products))):
            product = products[index]
            if not product.url:
                continue
            try:
                data = await parser._fetch_api_data(product.url)
            except Exception as exc:
                logger.debug("Ozon review enrichment failed for %s: %s", product.url, exc)
                continue
            if not data:
                continue
            products[index] = replace(
                product,
                rating=data.get("rating") if data.get("rating") is not None else product.rating,
                reviews_count=(
                    data.get("reviews_count") if data.get("reviews_count") is not None else product.reviews_count
                ),
                reviews=data.get("reviews") or product.reviews,
            )
