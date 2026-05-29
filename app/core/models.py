from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl

from app.core.enums import AvailabilityStatus, FetchStatus, Marketplace


class ProductSnapshot(BaseModel):
    marketplace: Marketplace = Marketplace.UNKNOWN
    url: HttpUrl
    fetched_at: datetime

    fetch_status: FetchStatus = FetchStatus.OK
    availability: AvailabilityStatus = AvailabilityStatus.UNKNOWN

    name: str | None = None
    price: int | None = Field(default=None, ge=0)
    old_price: int | None = Field(default=None, ge=0)
    discount_pct: int | None = Field(default=None, ge=0, le=100)
    currency: str = "RUB"

    image_url: HttpUrl | None = None

    raw: dict[str, Any] | None = None

