"""Единая точка разбора JSON-ответов LLM для стадий Content Pipeline.

Не дублирует app.card_filler._extract_json_object / AIRecommendationEngine._parse_suggestions
(старый код, который не трогаем) — но использует тот же приём снятия
markdown-fence, плюс валидацию через Pydantic вместо ручного построения dict.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

_SchemaT = TypeVar("_SchemaT", bound=BaseModel)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


@dataclass
class StageOutcome(Generic[_SchemaT]):
    """Результат одной LLM-стадии вместе с метаданными для трассируемости."""

    result: _SchemaT
    prompt_id: str
    prompt_version: str
    model_used: str


class ContentPipelineParseError(RuntimeError):
    """LLM вернул ответ, который не удалось разобрать в ожидаемую схему."""

    def __init__(self, message: str, *, raw_text: str) -> None:
        super().__init__(message)
        self.raw_text = raw_text


def _strip_json_object(text: str) -> str | None:
    if not text:
        return None
    raw = _FENCE_RE.sub("", text.strip()).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return raw[start : end + 1]


def parse_json_response(text: str, schema: type[_SchemaT]) -> _SchemaT:
    """Разбирает ответ LLM в строгую Pydantic-схему.

    Бросает ContentPipelineParseError с сырым текстом ответа, если JSON
    не найден, невалиден, или не проходит валидацию схемы — вызывающая
    стадия решает, что делать (retry, fallback, провалить job).
    """
    candidate = _strip_json_object(text)
    if candidate is None:
        raise ContentPipelineParseError("LLM response does not contain a JSON object", raw_text=text)

    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ContentPipelineParseError(f"LLM response is not valid JSON: {exc}", raw_text=text) from exc

    if not isinstance(data, dict):
        raise ContentPipelineParseError("LLM response JSON is not an object", raw_text=text)

    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        logger.warning("Content pipeline schema validation failed for %s: %s", schema.__name__, exc)
        raise ContentPipelineParseError(f"LLM response did not match {schema.__name__}: {exc}", raw_text=text) from exc
