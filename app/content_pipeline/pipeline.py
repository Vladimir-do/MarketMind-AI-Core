"""Оркестратор Content Intelligence Pipeline.

Product Passport -> Content Strategy -> Semantic Plan -> Title -> Benefits ->
Description -> SEO Auditor -> Fact Checker -> Marketplace Validator ->
Quality Controller -> AI Proposal Queue.

Каждая LLM-стадия сохраняет промежуточный артефакт через ArtifactStore.
Финальные title/description/selling_points попадают в существующий
DatabaseApprovalQueue как обычные AISuggestion — без новой approval-логики.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.ai_recommendation.db_approval import DatabaseApprovalQueue
from app.ai_recommendation.providers.factory import create_configured_provider
from app.ai_recommendation.suggestions import AIRecommendationResult, AISuggestion
from app.competitor_analysis.store import CompetitorSnapshotStore
from app.content_pipeline.artifact_store import ArtifactStore
from app.content_pipeline.benefits_generator import generate_benefits
from app.content_pipeline.description_generator import generate_description
from app.content_pipeline.fact_checker import run_fact_check
from app.content_pipeline.marketplace_validator import validate_for_marketplace
from app.content_pipeline.passport import build_passport
from app.content_pipeline.quality_controller import build_quality_report
from app.content_pipeline.semantic_planner import semantic_plan_for_passport
from app.content_pipeline.seo_auditor import audit_draft
from app.content_pipeline.strategy_builder import build_content_strategy
from app.content_pipeline.title_generator import generate_title
from app.effective_card.service import EffectiveProductCardService

if TYPE_CHECKING:
    from app.ai_recommendation.provider import AIProvider
    from app.content_pipeline.schemas import ProductPassport, QualityReport
    from app.database import Database


@dataclass
class ContentPipelineRunResult:
    project_id: str
    product_id: int
    passport: ProductPassport
    quality_report: QualityReport
    approval_ids: list[str]
    fact_check_contradicted: bool


async def run_content_pipeline(
    db: Database,
    *,
    project_id: str,
    product_id: int,
    provider: AIProvider | None = None,
    job_id: str | None = None,
) -> ContentPipelineRunResult:
    provider = provider or create_configured_provider()
    effective_service = EffectiveProductCardService(db)
    artifact_store = ArtifactStore(db)
    queue = DatabaseApprovalQueue(db)

    card = await effective_service.get_effective_card(project_id, product_id)
    passport = build_passport(card)

    strategy_outcome = await build_content_strategy(passport, provider)
    await artifact_store.save_artifact(
        project_id=project_id,
        project_product_id=passport.project_product_id,
        product_id=product_id,
        artifact_type="content_strategy",
        payload=strategy_outcome.result,
        prompt_id=strategy_outcome.prompt_id,
        prompt_version=strategy_outcome.prompt_version,
        model_used=strategy_outcome.model_used,
        job_id=job_id,
    )

    competitor_batch = await CompetitorSnapshotStore(db).get_latest_batch(
        project_id=project_id, project_product_id=passport.project_product_id
    )
    competitor_names = [c.competitor_name for c in competitor_batch] or None
    _core, semantic_plan = semantic_plan_for_passport(passport, competitor_names=competitor_names)
    await artifact_store.save_artifact(
        project_id=project_id,
        project_product_id=passport.project_product_id,
        product_id=product_id,
        artifact_type="semantic_plan",
        payload=semantic_plan,
        job_id=job_id,
    )

    title_outcome = await generate_title(passport, strategy_outcome.result, semantic_plan, provider)
    benefits_outcome = await generate_benefits(passport, strategy_outcome.result, semantic_plan, provider)
    description_outcome = await generate_description(
        passport, strategy_outcome.result, semantic_plan, benefits_outcome.result, provider
    )

    final_title = title_outcome.result.title
    final_description = description_outcome.result.full_description
    final_tags = list(dict.fromkeys(title_outcome.result.used_keywords + description_outcome.result.used_keywords))

    seo_summary = audit_draft(passport, title=final_title, description=final_description, tags=final_tags or None)

    fact_check_text = "\n".join([final_title, final_description, *benefits_outcome.result.bullets])
    fact_check = run_fact_check(fact_check_text, passport)
    await artifact_store.save_artifact(
        project_id=project_id,
        project_product_id=passport.project_product_id,
        product_id=product_id,
        artifact_type="fact_check_report",
        payload=fact_check,
        job_id=job_id,
    )

    marketplace_result = validate_for_marketplace(
        passport, title=final_title, description=final_description, tags=final_tags or None
    )

    quality_report = build_quality_report(
        seo=seo_summary,
        marketplace=marketplace_result,
        fact_check=fact_check,
        description=description_outcome.result,
        image_count=len(passport.image_urls),
    )
    await artifact_store.save_artifact(
        project_id=project_id,
        project_product_id=passport.project_product_id,
        product_id=product_id,
        artifact_type="quality_report",
        payload=quality_report,
        job_id=job_id,
    )

    common_metadata = {
        "source": "content_pipeline",
        "project_id": project_id,
        "project_product_id": passport.project_product_id,
        "product_name": passport.title,
        "job_id": job_id,
        "fact_check_contradicted": fact_check.contradicted_count > 0,
        "cqi": quality_report.cqi,
    }

    suggestions = [
        AISuggestion(
            field="title",
            suggestion_type="rewrite",
            before=passport.title,
            after=final_title,
            reason=title_outcome.result.reasoning or "Сгенерировано Content Intelligence Pipeline",
            confidence=title_outcome.result.confidence,
            source_finding="content_pipeline_title",
            metadata={
                **common_metadata,
                "prompt_id": title_outcome.prompt_id,
                "prompt_version": title_outcome.prompt_version,
                "model_used": title_outcome.model_used,
            },
        ),
        AISuggestion(
            field="description",
            suggestion_type="rewrite",
            before=passport.description or "",
            after=final_description,
            reason=description_outcome.result.reasoning or "Сгенерировано Content Intelligence Pipeline",
            confidence=description_outcome.result.confidence,
            source_finding="content_pipeline_description",
            metadata={
                **common_metadata,
                "prompt_id": description_outcome.prompt_id,
                "prompt_version": description_outcome.prompt_version,
                "model_used": description_outcome.model_used,
            },
        ),
        AISuggestion(
            field="selling_points",
            suggestion_type="rewrite",
            before="\n".join(card.effective_snapshot.get("selling_points") or []),
            after="\n".join(benefits_outcome.result.bullets),
            reason=benefits_outcome.result.reasoning or "Сгенерировано Content Intelligence Pipeline",
            confidence=benefits_outcome.result.confidence,
            source_finding="content_pipeline_benefits",
            metadata={
                **common_metadata,
                "prompt_id": benefits_outcome.prompt_id,
                "prompt_version": benefits_outcome.prompt_version,
                "model_used": benefits_outcome.model_used,
            },
        ),
    ]

    overall_confidence = round(sum(s.confidence for s in suggestions) / len(suggestions), 2)
    added = await queue.add(
        AIRecommendationResult(
            product_id=str(product_id),
            suggestions=suggestions,
            summary=f"Content Intelligence Pipeline: CQI={quality_report.cqi}",
            overall_confidence=overall_confidence,
            model_used=title_outcome.model_used,
        )
    )

    return ContentPipelineRunResult(
        project_id=project_id,
        product_id=product_id,
        passport=passport,
        quality_report=quality_report,
        approval_ids=[item.approval_id for item in added],
        fact_check_contradicted=fact_check.contradicted_count > 0,
    )
