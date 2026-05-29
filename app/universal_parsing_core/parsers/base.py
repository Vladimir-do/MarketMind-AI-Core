from __future__ import annotations

from abc import ABC, abstractmethod

from app.universal_parsing_core.schemas.parse_context import ParseContext
from app.universal_parsing_core.schemas.parse_result import ParseResult


class BaseParser(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def parse(self, context: ParseContext) -> ParseResult:
        ...
