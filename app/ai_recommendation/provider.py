"""AI provider protocol and response types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class AIResponse:
    """Raw response from an AI provider."""

    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    error_type: str = ""
    error_message: str = ""
    status_code: int | None = None
    error_stage: str = ""

    @property
    def ok(self) -> bool:
        return not self.error_type and bool(self.text.strip())


@runtime_checkable
class AIProvider(Protocol):
    """Protocol for AI completion providers."""

    async def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> AIResponse:
        ...

    def is_available(self) -> bool: ...

    def name(self) -> str: ...
