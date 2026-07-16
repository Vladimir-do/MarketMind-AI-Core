from __future__ import annotations

from pydantic import BaseModel


class MarketplaceStats(BaseModel):
    marketplace: str
    count: int


class HealthSummary(BaseModel):
    total_scrape_attempts: int
    total_blocks: int
    marketplaces: list[MarketplaceStats]


class DashboardStats(BaseModel):
    total_products: int
    products_by_marketplace: list[MarketplaceStats]
    health_summary: HealthSummary


class ProductListItem(BaseModel):
    id: int
    name: str | None
    url: str
    marketplace: str
    current_price: int | None
    availability: str
    last_check: str | None


class ImportResult(BaseModel):
    task_id: str
    status: str
    total_products: int
    errors: int
    message: str


class SuggestionItem(BaseModel):
    approval_id: str
    product_id: str
    product_name: str
    field: str
    suggestion_type: str
    before: str
    after: str
    reason: str
    confidence: float
    status: str  # pending | approved | rejected


class SuggestionStats(BaseModel):
    total: int
    pending: int
    approved: int
    rejected: int


class ProductDetailResponse(BaseModel):
    id: int
    name: str | None
    url: str
    image_url: str | None
    marketplace: str
    marketplace_name: str
    current_price: int | None
    availability: str
    first_seen: str | None
    last_check: str | None


class RejectRequest(BaseModel):
    reason: str = ""
