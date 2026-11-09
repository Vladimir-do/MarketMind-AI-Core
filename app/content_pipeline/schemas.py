"""Pydantic-контракты для стадий Content Intelligence Pipeline.

Каждая стадия конвейера (Content Strategy Builder, Semantic Planner,
Title/Benefits/Description Generator, Fact Checker, Marketplace Validator,
Quality Controller) принимает и возвращает строгие Pydantic-модели —
никакого свободного текста как внутреннего формата обмена между стадиями.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ClaimVerdictType = Literal["confirmed", "contradicted", "unverifiable"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── Product Passport ──────────────────────────────────────────────────────


class ProductPassport(_StrictModel):
    """Единственный источник истины о товаре для всех стадий пайплайна.

    Строится из EffectiveProductCard (app/effective_card/service.py) —
    см. app/content_pipeline/passport.py::build_passport().
    """

    product_id: int
    project_id: str
    project_product_id: str
    title: str
    description: str | None = None
    brand: str | None = None
    category: str | None = None
    sku: str | None = None
    marketplace: str
    price: int | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    image_urls: list[str] = Field(default_factory=list)
    weight_g: int | None = None
    width_mm: int | None = None
    height_mm: int | None = None
    depth_mm: int | None = None
    source_url: str | None = None

    @field_validator("title")
    @classmethod
    def _title_required(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Product Passport requires a non-empty title")
        return value

    @field_validator("marketplace")
    @classmethod
    def _marketplace_required(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Product Passport requires a marketplace")
        return value


# ── Content Strategy Builder ──────────────────────────────────────────────


class ContentStrategy(_StrictModel):
    target_audience: str
    usage_scenarios: list[str] = Field(default_factory=list)
    key_need: str
    key_selling_proposition: str
    secondary_benefits: list[str] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)
    objection_responses: list[str] = Field(default_factory=list)
    tone_of_voice: str
    description_structure: list[str] = Field(default_factory=list)
    priority_attributes: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    formality_level: str = "professional"


# ── Semantic Planner ───────────────────────────────────────────────────────


class SemanticPlan(_StrictModel):
    """Распределение уже классифицированных терминов (SemanticCore) по зонам карточки.

    Планировщик не генерирует новые ключи, а только распределяет
    результат app/semantic_core.py::build_semantic_core().
    """

    title_terms: list[str] = Field(default_factory=list)
    benefits_terms: list[str] = Field(default_factory=list)
    description_terms: list[str] = Field(default_factory=list)
    excluded_terms: list[str] = Field(default_factory=list)
    competitor_gap_terms: list[str] = Field(default_factory=list)


# ── Title Generator ────────────────────────────────────────────────────────


class TitleGenerationResult(_StrictModel):
    title: str
    alternatives: list[str] = Field(default_factory=list)
    used_keywords: list[str] = Field(default_factory=list)
    reasoning: str = ""
    confidence: float = 0.0

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, value: float) -> float:
        return max(0.0, min(1.0, value))


# ── Benefits Generator ─────────────────────────────────────────────────────


class BenefitsGenerationResult(_StrictModel):
    """Каждый bullet строится по схеме Свойство → Польза → Результат
    и должен ссылаться на подтверждённое свойство из ProductPassport."""

    bullets: list[str] = Field(default_factory=list)
    infographic_bullets: list[str] = Field(default_factory=list)
    description_bullets: list[str] = Field(default_factory=list)
    objection_counters: list[str] = Field(default_factory=list)
    reasoning: str = ""
    confidence: float = 0.0

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, value: float) -> float:
        return max(0.0, min(1.0, value))


# ── Description Generator ──────────────────────────────────────────────────


class DescriptionGenerationResult(_StrictModel):
    short_description: str
    full_description: str
    blocks: dict[str, str] = Field(default_factory=dict)
    used_keywords: list[str] = Field(default_factory=list)
    reasoning: str = ""
    confidence: float = 0.0

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, value: float) -> float:
        return max(0.0, min(1.0, value))


# ── Fact Checker ────────────────────────────────────────────────────────────


class Claim(_StrictModel):
    text: str
    claim_type: Literal["weight", "dimension", "percent", "quantity", "warranty", "material", "color", "other"]
    value: str
    unit: str | None = None


class ClaimVerdict(_StrictModel):
    claim: Claim
    verdict: ClaimVerdictType
    passport_field: str | None = None
    passport_value: str | None = None
    explanation: str = ""


class FactCheckResult(_StrictModel):
    claims: list[ClaimVerdict] = Field(default_factory=list)
    confirmed_count: int = 0
    contradicted_count: int = 0
    unverifiable_count: int = 0
    passed: bool = True


# ── SEO Auditor / Marketplace Validator ─────────────────────────────────────


class SEOAuditSummary(_StrictModel):
    """Тонкая Pydantic-обёртка над app.seo_intelligence.SEOAuditResult."""

    score: int
    tier: str
    ready: bool
    findings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class MarketplaceValidationResult(_StrictModel):
    ready: bool
    score: int
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ── Quality Controller (CQI) ─────────────────────────────────────────────────


class QualityReport(_StrictModel):
    """Композиция уже посчитанных детерминированных оценок в единый CQI.

    Не новая ML-модель — агрегатор существующих оценок (SEO, маркетплейс-
    готовность, доля подтверждённых фактов, структура текста).
    """

    seo_score: int
    marketplace_ready: bool
    fact_check_pass_rate: float
    readability_score: int
    visual_ready_score: int
    cqi: int
    breakdown: dict[str, int] = Field(default_factory=dict)
