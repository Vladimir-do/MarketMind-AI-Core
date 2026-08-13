from __future__ import annotations

from abc import ABC, abstractmethod

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.universal_parsing_core.schemas.parse_result import ParseResult
    from app.universal_parsing_core.schemas.parse_context import ParseContext


class BaseParser(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def parse(self, context: ParseContext) -> ParseResult:
        ...
