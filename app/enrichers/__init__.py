"""Pluggable enrichment strategies for the import pipeline."""

from __future__ import annotations

from typing import Protocol

from app.products.schema import UnifiedProduct


class EnrichmentResult:
    """Result of enriching a single product."""

    __slots__ = ("product", "metadata")

    def __init__(self, product: UnifiedProduct, metadata: dict | None = None):
        self.product = product
        self.metadata = metadata or {}


class EnrichmentStrategy(Protocol):
    """Interface for product enrichment strategies."""

    def enrich(self, product: UnifiedProduct) -> EnrichmentResult: ...
