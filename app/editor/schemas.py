"""Schemas and helpers for editable product cards."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

EditableStatus = Literal["draft", "ready_for_review", "applied", "discarded", "conflicted"]


@dataclass(frozen=True)
class EditableProductCard:
    title: str
    description: str | None = None
    brand: str | None = None
    price: int | None = None
    availability: str = "unknown"
    image_urls: list[str] = field(default_factory=list)
    attributes: dict[str, str] = field(default_factory=dict)
    marketplace: str = "unknown"
    external_product_id: str | None = None
    selling_points: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    message: str
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    issues: list[ValidationIssue]

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class CardDiffItem:
    field: str
    old_value: Any
    new_value: Any

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_card_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize editable card payload without inventing missing values."""
    result = dict(payload)
    for key in ("title", "description", "brand", "marketplace", "external_product_id"):
        if isinstance(result.get(key), str):
            result[key] = " ".join(result[key].strip().split()) if key != "description" else result[key].strip()
    if "image_urls" in result:
        seen: set[str] = set()
        urls = []
        for item in result.get("image_urls") or []:
            text = str(item).strip()
            if text and text not in seen:
                seen.add(text)
                urls.append(text)
        result["image_urls"] = urls
    if "tags" in result:
        raw_tags = result.get("tags") or []
        if isinstance(raw_tags, str):
            raw_tags = raw_tags.replace(";", ",").split(",")
        seen_tags: set[str] = set()
        tags = []
        for item in raw_tags:
            text = str(item).strip()
            if text and text not in seen_tags:
                seen_tags.add(text)
                tags.append(text)
        result["tags"] = tags
    if "attributes" in result:
        attrs = {}
        for key, value in (result.get("attributes") or {}).items():
            clean_key = str(key).strip()
            clean_value = str(value).strip()
            if clean_key and clean_value:
                attrs[clean_key] = clean_value
        result["attributes"] = attrs
    if "selling_points" in result:
        raw_points = result.get("selling_points") or []
        if isinstance(raw_points, str):
            raw_points = raw_points.split("\n")
        seen_points: set[str] = set()
        points = []
        for item in raw_points:
            text = " ".join(str(item).strip().split())
            if text and text not in seen_points:
                seen_points.add(text)
                points.append(text)
        result["selling_points"] = points
    if "price" in result and result["price"] not in (None, ""):
        result["price"] = int(result["price"])
    return result
