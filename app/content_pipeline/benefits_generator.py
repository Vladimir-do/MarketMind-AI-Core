"""Benefits Generator — преимущества по схеме Свойство -> Польза -> Результат."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.content_pipeline.parsing import ContentPipelineParseError, StageOutcome, parse_json_response
from app.content_pipeline.prompt_registry import get_prompt
from app.content_pipeline.schemas import (
    BenefitsGenerationResult,
    ContentStrategy,
    ProductPassport,
    SemanticPlan,
)

if TYPE_CHECKING:
    from app.ai_recommendation.provider import AIProvider

_PROMPT_ID = "benefits_generator"


async def generate_benefits(
    passport: ProductPassport,
    strategy: ContentStrategy,
    semantic_plan: SemanticPlan,
    provider: AIProvider,
) -> StageOutcome[BenefitsGenerationResult]:
    spec = get_prompt(_PROMPT_ID, marketplace=passport.marketplace)
    prompt = spec.render_user_prompt(
        title=passport.title,
        attributes="; ".join(f"{k}: {v}" for k, v in passport.attributes.items()) or "нет данных",
        strategy_key_selling_proposition=strategy.key_selling_proposition,
        strategy_secondary_benefits=", ".join(strategy.secondary_benefits) or "нет данных",
        strategy_objections=", ".join(strategy.objections) or "нет данных",
        strategy_objection_responses=", ".join(strategy.objection_responses) or "нет данных",
        semantic_benefits_terms=", ".join(semantic_plan.benefits_terms) or "нет данных",
    )
    response = await provider.complete(prompt, system=spec.system_prompt, max_tokens=1500)
    if not response.ok:
        raise ContentPipelineParseError(
            f"AI provider error: {response.error_type or 'unknown'} {response.error_message}",
            raw_text=response.text,
        )
    result = parse_json_response(response.text, BenefitsGenerationResult)
    return StageOutcome(
        result=result,
        prompt_id=spec.id,
        prompt_version=spec.version,
        model_used=response.model,
    )
