"""Fact Checker — эвристическая (без ML) сверка утверждений с Product Passport.

Извлекает количественные и атрибутные утверждения из сгенерированного
текста регулярными выражениями и сверяет их с полями ProductPassport.
Ничего не переписывает автоматически — только формирует вердикт по
каждому утверждению (confirmed / contradicted / unverifiable).
"""

from __future__ import annotations

import re

from app.content_pipeline.schemas import Claim, ClaimVerdict, FactCheckResult, ProductPassport

_TOLERANCE = 0.05  # допуск ±5% на округления

_WEIGHT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(кг|г|kg|g)\b", re.IGNORECASE)
_DIMENSION_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(мм|см|mm|cm)\b", re.IGNORECASE)
_PERCENT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_QUANTITY_RE = re.compile(r"(\d+)\s*(шт|штук[аи]?|предмет[а-я]*|пар[а-я]*)\b", re.IGNORECASE)
_WARRANTY_RE = re.compile(r"гаранти\w*\s*(\d+)\s*(лет|год[а-у]?|месяц\w*)", re.IGNORECASE)

_MATERIAL_KEYS = ("материал", "material")
_COLOR_KEYS = ("цвет", "color")


def _to_float(raw: str) -> float:
    return float(raw.replace(",", "."))


def extract_claims(text: str) -> list[Claim]:
    if not text:
        return []
    claims: list[Claim] = []

    for match in _WEIGHT_RE.finditer(text):
        claims.append(
            Claim(text=match.group(0), claim_type="weight", value=match.group(1), unit=match.group(2).lower())
        )

    for match in _DIMENSION_RE.finditer(text):
        claims.append(
            Claim(text=match.group(0), claim_type="dimension", value=match.group(1), unit=match.group(2).lower())
        )

    for match in _PERCENT_RE.finditer(text):
        claims.append(Claim(text=match.group(0), claim_type="percent", value=match.group(1), unit="%"))

    for match in _QUANTITY_RE.finditer(text):
        claims.append(Claim(text=match.group(0), claim_type="quantity", value=match.group(1), unit=None))

    for match in _WARRANTY_RE.finditer(text):
        claims.append(
            Claim(text=match.group(0), claim_type="warranty", value=match.group(1), unit=match.group(2).lower())
        )

    lowered = text.lower()
    for key in _MATERIAL_KEYS:
        idx = lowered.find(key)
        if idx != -1:
            claims.append(Claim(text=text[idx : idx + 60].strip(), claim_type="material", value="", unit=None))
            break
    for key in _COLOR_KEYS:
        idx = lowered.find(key)
        if idx != -1:
            claims.append(Claim(text=text[idx : idx + 60].strip(), claim_type="color", value="", unit=None))
            break

    return claims


def _weight_grams(value: float, unit: str) -> float:
    return value * 1000 if unit in ("кг", "kg") else value


def _within_tolerance(claim_value: float, passport_value: float) -> bool:
    if passport_value == 0:
        return claim_value == 0
    return abs(claim_value - passport_value) / passport_value <= _TOLERANCE


def _find_attribute(passport: ProductPassport, keys: tuple[str, ...]) -> tuple[str, str] | None:
    for attr_key, attr_value in passport.attributes.items():
        low_key = attr_key.lower()
        if any(key in low_key for key in keys):
            return attr_key, attr_value
    return None


def verify_claim(claim: Claim, passport: ProductPassport) -> ClaimVerdict:
    if claim.claim_type == "weight" and passport.weight_g is not None:
        claim_grams = _weight_grams(_to_float(claim.value), claim.unit or "г")
        confirmed = _within_tolerance(claim_grams, float(passport.weight_g))
        return ClaimVerdict(
            claim=claim,
            verdict="confirmed" if confirmed else "contradicted",
            passport_field="weight_g",
            passport_value=str(passport.weight_g),
            explanation="Совпадает с весом в паспорте товара" if confirmed else "Расходится с весом в паспорте товара",
        )

    if claim.claim_type == "dimension":
        dims = {
            "width_mm": passport.width_mm,
            "height_mm": passport.height_mm,
            "depth_mm": passport.depth_mm,
        }
        raw = _to_float(claim.value)
        claim_mm = raw * 10 if (claim.unit or "").lower() in ("см", "cm") else raw
        for field_name, dim_value in dims.items():
            if dim_value is not None and _within_tolerance(claim_mm, float(dim_value)):
                return ClaimVerdict(
                    claim=claim,
                    verdict="confirmed",
                    passport_field=field_name,
                    passport_value=str(dim_value),
                    explanation=f"Совпадает с {field_name} в паспорте товара",
                )
        if any(v is not None for v in dims.values()):
            return ClaimVerdict(
                claim=claim,
                verdict="contradicted",
                passport_field=None,
                passport_value=None,
                explanation="Не совпадает ни с одним из габаритов в паспорте товара",
            )
        return ClaimVerdict(
            claim=claim,
            verdict="unverifiable",
            explanation="В паспорте товара нет габаритов для проверки",
        )

    if claim.claim_type in ("material", "color"):
        keys = _MATERIAL_KEYS if claim.claim_type == "material" else _COLOR_KEYS
        found = _find_attribute(passport, keys)
        if found is None:
            return ClaimVerdict(
                claim=claim,
                verdict="unverifiable",
                explanation=f"В паспорте товара нет атрибута «{claim.claim_type}»",
            )
        attr_key, attr_value = found
        confirmed = attr_value.lower() in claim.text.lower()
        return ClaimVerdict(
            claim=claim,
            verdict="confirmed" if confirmed else "contradicted",
            passport_field=attr_key,
            passport_value=attr_value,
            explanation="Совпадает с атрибутом паспорта" if confirmed else f"Атрибут паспорта: {attr_value}",
        )

    # percent / quantity / warranty — как правило нет прямого поля в паспорте
    return ClaimVerdict(
        claim=claim,
        verdict="unverifiable",
        explanation=f"В паспорте товара нет поля для проверки утверждения типа «{claim.claim_type}»",
    )


def run_fact_check(text: str, passport: ProductPassport) -> FactCheckResult:
    claims = extract_claims(text)
    verdicts = [verify_claim(claim, passport) for claim in claims]
    confirmed = sum(1 for v in verdicts if v.verdict == "confirmed")
    contradicted = sum(1 for v in verdicts if v.verdict == "contradicted")
    unverifiable = sum(1 for v in verdicts if v.verdict == "unverifiable")
    return FactCheckResult(
        claims=verdicts,
        confirmed_count=confirmed,
        contradicted_count=contradicted,
        unverifiable_count=unverifiable,
        passed=contradicted == 0,
    )
