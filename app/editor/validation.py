"""Validation rules for editable product cards."""

from __future__ import annotations

from typing import Any

from app.editor.schemas import ValidationIssue, ValidationResult, normalize_card_payload

_AVAILABILITY = {"in_stock", "out_of_stock", "deleted", "blocked", "unknown"}
_MARKETPLACES = {"ozon", "wildberries", "yandex_market", "unknown"}
_BANNED_PHRASES = ("лучший в мире", "гарантированно лечит", "100% результат")


def validate_card_payload(payload: dict[str, Any]) -> ValidationResult:
    data = normalize_card_payload(payload)
    issues: list[ValidationIssue] = []

    title = str(data.get("title") or "").strip()
    if not title:
        issues.append(ValidationIssue("title", "Название товара обязательно"))
    if len(title) > 255:
        issues.append(ValidationIssue("title", "Название товара не должно быть длиннее 255 символов"))

    description = data.get("description")
    if description is not None and len(str(description)) > 5000:
        issues.append(ValidationIssue("description", "Описание не должно быть длиннее 5000 символов"))

    brand = data.get("brand")
    if brand is not None and len(str(brand)) > 120:
        issues.append(ValidationIssue("brand", "Бренд не должен быть длиннее 120 символов"))

    price = data.get("price")
    if price is not None:
        try:
            if int(price) < 0:
                issues.append(ValidationIssue("price", "Цена не может быть отрицательной"))
        except (TypeError, ValueError):
            issues.append(ValidationIssue("price", "Цена должна быть целым числом"))

    availability = str(data.get("availability") or "unknown")
    if availability not in _AVAILABILITY:
        issues.append(ValidationIssue("availability", "Некорректный статус наличия"))

    marketplace = str(data.get("marketplace") or "unknown")
    if marketplace not in _MARKETPLACES:
        issues.append(ValidationIssue("marketplace", "Некорректный маркетплейс"))

    image_urls = data.get("image_urls") or []
    if len(image_urls) > 50:
        issues.append(ValidationIssue("image_urls", "Нельзя указать больше 50 изображений"))
    for url in image_urls:
        if not str(url).startswith(("http://", "https://")):
            issues.append(ValidationIssue("image_urls", "Ссылки на изображения должны начинаться с http:// или https://"))
            break

    attributes = data.get("attributes") or {}
    if len(attributes) > 200:
        issues.append(ValidationIssue("attributes", "Нельзя указать больше 200 характеристик"))
    for key, value in attributes.items():
        if len(str(key)) > 120 or len(str(value)) > 1000:
            issues.append(ValidationIssue("attributes", "Характеристика или значение слишком длинные"))
            break

    text = f"{title} {description or ''}".lower()
    for phrase in _BANNED_PHRASES:
        if phrase in text:
            issues.append(ValidationIssue("description", f"Недопустимая формулировка: {phrase}"))

    return ValidationResult(is_valid=not any(issue.severity == "error" for issue in issues), issues=issues)
