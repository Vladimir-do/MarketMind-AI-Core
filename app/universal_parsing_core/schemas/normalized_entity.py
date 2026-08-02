from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NormalizedEntity:
    entity_type: str
    title: str
    price: float | None = None
    description: str = ""
    url: str = ""
    source: str = "html"
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.title = " ".join(self.title.split())
        self.description = " ".join(self.description.split())
        if self.price is not None and self.price < 0:
            self.price = None
