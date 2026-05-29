from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParseContext:
    url: str
    html: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    payload: Any | None = None
    parser_chain: list[str] = field(default_factory=list)
