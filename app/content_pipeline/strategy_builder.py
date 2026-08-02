"""Content Strategy Builder — определяет ЦА, УТП, тональность, возражения."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.content_pipeline.parsing import ContentPipelineParseError, StageOutcome, parse_json_response
from app.content_pipeline.prompt_registry import get_prompt
from app.content_pipeline.schemas import ContentStrategy, ProductPassport

if TYPE_CHECKING:
    from app.ai_recommendation.provider import AIProvider

_PROMPT_ID = "content_strategy_builder"


async def build_content_strategy(
    passport: ProductPassport,
    provider: AIProvider,
) -> StageOutcome[ContentStrategy]:
    spec = get_prompt(_PROMPT_ID, marketplace=passport.marketplace)
    prompt = spec.render_user_prompt(
        title=passport.title,
        brand=passport.brand or "не указан",
        category=passport.category or "не указана",
        price=passport.price if passport.price is not None else "не указана",
        marketplace=passport.marketplace,
        attributes="; ".join(f"{k}: {v}" for k, v in passport.attributes.items()) or "нет данных",
        tags=", ".join(passport.tags) or "нет данных",
        description=passport.description or "нет данных",
    )
    response = await provider.complete(prompt, system=spec.system_prompt, max_tokens=1500)
    if not response.ok:
        raise ContentPipelineParseError(
            f"AI provider error: {response.error_type or 'unknown'} {response.error_message}",
            raw_text=response.text,
        )
    strategy = parse_json_response(response.text, ContentStrategy)
    return StageOutcome(
        result=strategy,
        prompt_id=spec.id,
        prompt_version=spec.version,
        model_used=response.model,
    )
