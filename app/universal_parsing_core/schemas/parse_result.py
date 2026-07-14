from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.universal_parsing_core.schemas.normalized_entity import NormalizedEntity
from app.universal_parsing_core.schemas.page_structure import PageStructure
from app.universal_parsing_core.schemas.task_type import TaskType


@dataclass
class ParseResult:
    success: bool
    task_type: TaskType
    page_structure: PageStructure = PageStructure.UNKNOWN
    entities: list[NormalizedEntity] = field(default_factory=list)
    source_url: str = ""
    parser_used: str = ""
    confidence: float = 0.0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_snapshot: dict[str, Any] = field(default_factory=dict)
    parser_chain: list[str] = field(default_factory=list)
    execution_time_ms: int = 0
    next_strategy: str = ""

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        if self.page_structure is None:
            self.page_structure = PageStructure.UNKNOWN
        if self.execution_time_ms < 0:
            self.execution_time_ms = 0
