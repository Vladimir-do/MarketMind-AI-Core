"""Product validation rules for the import pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.products.schema import UnifiedProduct


@dataclass
class ValidationError:
    """Records a validation rule violation."""

    product_index: int
    rule: str
    field: str
    message: str
    severity: str = "error"  # "error" or "warning"


class ProductValidator:
    """Validates UnifiedProduct instances against a set of business rules."""

    def validate(self, products: list[UnifiedProduct]) -> tuple[list[UnifiedProduct], list[ValidationError]]:
        """Validate products and return (valid_products, errors)."""
        valid_products = []
        errors: list[ValidationError] = []

        for idx, product in enumerate(products):
            product_errors = self._validate_product(idx, product)
            error_severities = {e.severity for e in product_errors}

            # Only include product if no error-level issues
            if "error" not in error_severities:
                valid_products.append(product)
            errors.extend(product_errors)

        return valid_products, errors

    def _validate_product(self, idx: int, product: UnifiedProduct) -> list[ValidationError]:
        """Run all validation rules against a single product."""
        errors: list[ValidationError] = []

        # required_name
        if not product.name or not product.name.strip():
            errors.append(ValidationError(
                product_index=idx,
                rule="required_name",
                field="name",
                message="Product name must not be empty",
                severity="error",
            ))

        # required_source_id
        if not product.source_id or not product.source_id.strip():
            errors.append(ValidationError(
                product_index=idx,
                rule="required_source_id",
                field="source_id",
                message="Source ID must not be empty",
                severity="error",
            ))

        # price_positive
        if product.price is not None and product.price <= 0:
            errors.append(ValidationError(
                product_index=idx,
                rule="price_positive",
                field="price",
                message=f"Price must be positive, got {product.price}",
                severity="error",
            ))

        # price_range
        if product.price is not None and product.price >= 50_000_000:
            errors.append(ValidationError(
                product_index=idx,
                rule="price_range",
                field="price",
                message=f"Price {product.price} exceeds maximum range (50,000,000)",
                severity="warning",
            ))

        # old_price_gt_price
        if product.old_price is not None and product.price is not None:
            if product.old_price <= product.price:
                errors.append(ValidationError(
                    product_index=idx,
                    rule="old_price_gt_price",
                    field="old_price",
                    message=f"Old price ({product.old_price}) must be greater than current price ({product.price})",
                    severity="warning",
                ))

        # url_valid
        if product.source_url:
            try:
                result = urlparse(product.source_url)
                if not all([result.scheme, result.netloc]):
                    raise ValueError("Invalid URL")
            except Exception:
                errors.append(ValidationError(
                    product_index=idx,
                    rule="url_valid",
                    field="source_url",
                    message=f"Invalid URL: {product.source_url}",
                    severity="error",
                ))

        # dimensions_complete
        dimensions = [product.width_mm, product.height_mm, product.depth_mm]
        if any(d is not None for d in dimensions):
            if not all(d is not None for d in dimensions):
                errors.append(ValidationError(
                    product_index=idx,
                    rule="dimensions_complete",
                    field="dimensions",
                    message="All three dimensions (width, height, depth) must be specified together",
                    severity="error",
                ))

        # weight_positive
        if product.weight_g is not None and product.weight_g <= 0:
            errors.append(ValidationError(
                product_index=idx,
                rule="weight_positive",
                field="weight_g",
                message=f"Weight must be positive, got {product.weight_g}",
                severity="error",
            ))

        # name_length
        if product.name and len(product.name) > 140:
            errors.append(ValidationError(
                product_index=idx,
                rule="name_length",
                field="name",
                message=f"Name length {len(product.name)} exceeds 140 characters",
                severity="warning",
            ))

        # description_length
        if product.description and len(product.description) > 4000:
            errors.append(ValidationError(
                product_index=idx,
                rule="description_length",
                field="description",
                message=f"Description length {len(product.description)} exceeds 4000 characters",
                severity="warning",
            ))

        return errors
