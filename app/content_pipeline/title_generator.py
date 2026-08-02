"""Title Generator — работает поверх готовых ContentStrategy и SemanticPlan."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.content_pipeline.parsing import ContentPipelineParseError, StageOutcome, parse_json_response
from app.content_pipeline.prompt_registry import get_prompt
from app.content_pipeline.schemas import ContentStrategy, ProductPassport, SemanticPlan, TitleGenerationResult
from app.seo_rules import get_marketplace_rules

if TYPE_CHECKING:
    from app.ai_recommendation.provider import AIProvider

_PROMPT_ID = "title_generator"


async def generate_title(
    passport: ProductPassport,
    strategy: ContentStrategy,
    semantic_plan: SemanticPlan,
    provider: AIProvider,
) -> StageOutcome[TitleGenerationResult]:
    spec = get_prompt(_PROMPT_ID, marketplace=passport.marketplace)
    rules = get_marketplace_rules(passport.marketplace)
    prompt = spec.render_user_prompt(
        title=passport.title,
        brand=passport.brand or "не указан",
        category=passport.category or "не указана",
        attributes="; ".join(f"{k}: {v}" for k, v in passport.attributes.items()) or "нет данных",
        marketplace=passport.marketplace,
        title_max=rules.title_max,
        strategy_target_audience=strategy.target_audience,
        strategy_key_selling_proposition=strategy.key_selling_proposition,
        strategy_tone_of_voice=strategy.tone_of_voice,
        semantic_title_terms=", ".join(semantic_plan.title_terms) or "нет данных",
    )
    response = await provider.complete(prompt, system=spec.system_prompt, max_tokens=1200)
    if not response.ok:
        raise ContentPipelineParseError(
            f"AI provider error: {response.error_type or 'unknown'} {response.error_message}",
            raw_text=response.text,
        )
    result = parse_json_response(response.text, TitleGenerationResult)
    return StageOutcome(
        result=result,
        prompt_id=spec.id,
        prompt_version=spec.version,
        model_used=response.model,
    )
