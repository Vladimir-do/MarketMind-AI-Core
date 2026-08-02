"""Prompt Registry — централизованный реестр LLM-промптов пайплайна.

Промпты хранятся как YAML-файлы в prompts/ (по аналогии с профилями карточек
в app/card_profiles.py + profiles/*.yaml) — это код, который должен
ревьюиться через git diff, а не оперативные данные для рантайм-редактирования.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path

import yaml

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


class PromptNotFoundError(RuntimeError):
    """Не найден активный промпт с заданным id/marketplace/category."""


@dataclass(slots=True)
class PromptSpec:
    id: str
    version: str
    status: str
    purpose: str
    model: str
    marketplace: str
    category: str | None
    input_schema: str
    output_schema: str
    system_prompt: str
    user_prompt_template: str

    def resolve_input_schema(self):
        return _resolve_dotted(self.input_schema)

    def resolve_output_schema(self):
        return _resolve_dotted(self.output_schema)

    def render_user_prompt(self, **context: object) -> str:
        return self.user_prompt_template.format(**context)


def _resolve_dotted(dotted_path: str):
    module_path, _, attr_name = dotted_path.rpartition(".")
    module = importlib.import_module(module_path)
    return getattr(module, attr_name)


def _load_all_specs() -> list[PromptSpec]:
    specs: list[PromptSpec] = []
    if not PROMPTS_DIR.exists():
        return specs
    for path in sorted(PROMPTS_DIR.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        specs.append(
            PromptSpec(
                id=str(raw["id"]),
                version=str(raw.get("version", "1")),
                status=str(raw.get("status", "draft")),
                purpose=str(raw.get("purpose", "")),
                model=str(raw.get("model", "")),
                marketplace=str(raw.get("marketplace", "universal")),
                category=raw.get("category"),
                input_schema=str(raw.get("input_schema", "")),
                output_schema=str(raw.get("output_schema", "")),
                system_prompt=str(raw.get("system_prompt", "")),
                user_prompt_template=str(raw.get("user_prompt_template", "")),
            )
        )
    return specs


def get_prompt(
    prompt_id: str,
    *,
    marketplace: str = "universal",
    category: str | None = None,
) -> PromptSpec:
    """Резолюция: marketplace+category -> marketplace -> universal, только status=active."""
    candidates = [spec for spec in _load_all_specs() if spec.id == prompt_id and spec.status == "active"]
    if not candidates:
        raise PromptNotFoundError(f"No active prompt registered for id={prompt_id!r}")

    marketplace = (marketplace or "universal").lower()

    if category:
        for spec in candidates:
            if spec.marketplace == marketplace and spec.category == category:
                return spec

    for spec in candidates:
        if spec.marketplace == marketplace and spec.category is None:
            return spec

    for spec in candidates:
        if spec.marketplace == "universal" and spec.category is None:
            return spec

    raise PromptNotFoundError(
        f"No active prompt for id={prompt_id!r} matching marketplace={marketplace!r}/category={category!r}, "
        "and no universal fallback registered"
    )
