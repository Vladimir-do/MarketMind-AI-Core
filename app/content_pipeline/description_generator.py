"""Description Generator — собирает описание из стратегии, семантики и преимуществ."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.content_pipeline.parsing import ContentPipelineParseError, StageOutcome, parse_json_response
from app.content_pipeline.prompt_registry import get_prompt
from app.content_pipeline.schemas import (
    BenefitsGenerationResult,
    ContentStrategy,
    DescriptionGenerationResult,
    ProductPassport,
    SemanticPlan,
)

if TYPE_CHECKING:
    from app.ai_recommendation.provider import AIProvider

_PROMPT_ID = "description_generator"


async def generate_description(
    passport: ProductPassport,
    strategy: ContentStrategy,
    semantic_plan: SemanticPlan,
    benefits: BenefitsGenerationResult,
    provider: AIProvider,
) -> StageOutcome[DescriptionGenerationResult]:
    spec = get_prompt(_PROMPT_ID, marketplace=passport.marketplace)
    prompt = spec.render_user_prompt(
        title=passport.title,
        attributes="; ".join(f"{k}: {v}" for k, v in passport.attributes.items()) or "нет данных",
        brand=passport.brand or "не указан",
        category=passport.category or "не указана",
        strategy_tone_of_voice=strategy.tone_of_voice,
        strategy_description_structure=", ".join(strategy.description_structure) or "нет данных",
        strategy_forbidden_claims=", ".join(strategy.forbidden_claims) or "нет данных",
        benefits_bullets="\n".join(f"- {b}" for b in benefits.description_bullets or benefits.bullets) or "нет данных",
        semantic_description_terms=", ".join(semantic_plan.description_terms) or "нет данных",
    )
    response = await provider.complete(prompt, system=spec.system_prompt, max_tokens=2000)
    if not response.ok:
        raise ContentPipelineParseError(
            f"AI provider error: {response.error_type or 'unknown'} {response.error_message}",
            raw_text=response.text,
        )
    result = parse_json_response(response.text, DescriptionGenerationResult)
    return StageOutcome(
        result=result,
        prompt_id=spec.id,
        prompt_version=spec.version,
        model_used=response.model,
    )
