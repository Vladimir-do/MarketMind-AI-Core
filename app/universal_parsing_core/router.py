from __future__ import annotations

from dataclasses import dataclass

from app.universal_parsing_core.parsers.base import BaseParser
from app.universal_parsing_core.schemas.parse_context import ParseContext
from app.universal_parsing_core.schemas.parse_result import ParseResult
from app.universal_parsing_core.schemas.task_type import TaskType


@dataclass(frozen=True)
class ParserRegistration:
    parser: BaseParser
    priority: int = 100
    supports_js: bool = False


class Router:
    def __init__(self) -> None:
        self._parsers: dict[TaskType, list[ParserRegistration]] = {}

    def register(
        self,
        task_type: TaskType,
        parser: BaseParser,
        *,
        priority: int = 100,
        supports_js: bool = False,
    ) -> None:
        registrations = self._parsers.setdefault(task_type, [])
        registrations.append(
            ParserRegistration(parser=parser, priority=priority, supports_js=supports_js)
        )
        registrations.sort(key=lambda item: item.priority)

    def parse(
        self,
        url: str,
        *,
        html: str | None = None,
        task_type: TaskType = TaskType.UNIVERSAL_PAGE,
    ) -> ParseResult:
        registrations = self._parsers.get(task_type, [])
        if not registrations:
            raise ValueError(f"No parser registered for task type: {task_type}")

        last_result: ParseResult | None = None
        parser_chain: list[str] = []
        for registration in registrations:
            parser_chain.append(registration.parser.name)
            context = ParseContext(url=url, html=html, parser_chain=list(parser_chain))
            result = registration.parser.parse(context)
            if not result.parser_chain:
                result.parser_chain = list(parser_chain)
            last_result = result
            if result.success:
                return result

        if last_result is None:
            raise ValueError(f"No parser registered for task type: {task_type}")
        return last_result
