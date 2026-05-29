from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml


class ScoringPolicy(StrEnum):
    BALANCED = "balanced"
    FAST = "fast"
    CHEAP = "cheap"
    STABLE = "stable"
    PRODUCTION_SAFE = "production_safe"


@dataclass(frozen=True, slots=True)
class SkillQuality:
    reliability: float = 0.0
    speed: float = 0.0
    reuse: float = 0.0
    complexity: float = 1.0
    cost: float = 0.5
    token_usage: float = 0.5
    risk: float = 0.5
    success_rate: float = 0.0

    @property
    def score(self) -> float:
        return self.score_for(ScoringPolicy.BALANCED)

    def score_for(self, policy: ScoringPolicy | str) -> float:
        policy = ScoringPolicy(policy)
        weights = {
            ScoringPolicy.BALANCED: {
                "reliability": 0.30,
                "success_rate": 0.20,
                "reuse": 0.18,
                "speed": 0.14,
                "low_complexity": 0.08,
                "low_cost": 0.05,
                "low_token_usage": 0.03,
                "low_risk": 0.02,
            },
            ScoringPolicy.FAST: {
                "speed": 0.42,
                "reliability": 0.22,
                "success_rate": 0.15,
                "low_complexity": 0.10,
                "reuse": 0.06,
                "low_cost": 0.03,
                "low_token_usage": 0.01,
                "low_risk": 0.01,
            },
            ScoringPolicy.CHEAP: {
                "low_cost": 0.34,
                "low_token_usage": 0.25,
                "reliability": 0.18,
                "success_rate": 0.10,
                "speed": 0.06,
                "reuse": 0.04,
                "low_complexity": 0.02,
                "low_risk": 0.01,
            },
            ScoringPolicy.STABLE: {
                "reliability": 0.42,
                "success_rate": 0.28,
                "low_risk": 0.12,
                "reuse": 0.08,
                "low_complexity": 0.05,
                "speed": 0.03,
                "low_cost": 0.01,
                "low_token_usage": 0.01,
            },
            ScoringPolicy.PRODUCTION_SAFE: {
                "reliability": 0.36,
                "success_rate": 0.24,
                "low_risk": 0.18,
                "low_complexity": 0.10,
                "reuse": 0.07,
                "speed": 0.02,
                "low_cost": 0.02,
                "low_token_usage": 0.01,
            },
        }[policy]

        values = {
            "reliability": self.reliability,
            "success_rate": self.success_rate or self.reliability,
            "reuse": self.reuse,
            "speed": self.speed,
            "low_complexity": 1.0 - self.complexity,
            "low_cost": 1.0 - self.cost,
            "low_token_usage": 1.0 - self.token_usage,
            "low_risk": 1.0 - self.risk,
        }
        return round(
            sum(values[key] * weight for key, weight in weights.items()),
            4,
        )


@dataclass(frozen=True, slots=True)
class FailurePattern:
    site: str
    trigger: str
    recovery: str
    cooldown_seconds: int = 0


@dataclass(frozen=True, slots=True)
class SkillManifest:
    skill_id: str
    name: str
    category: str
    status: str = "missing"
    requires: tuple[str, ...] = ()
    enhances: tuple[str, ...] = ()
    fallback_to: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()
    anti_patterns: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    quality: SkillQuality = field(default_factory=SkillQuality)
    failure_patterns: tuple[FailurePattern, ...] = ()

    @property
    def available(self) -> bool:
        return self.status == "available"


@dataclass(frozen=True, slots=True)
class ResolvedSkill:
    manifest: SkillManifest
    selected_for: str | None = None


@dataclass(frozen=True, slots=True)
class SkillGraphResolution:
    steps: tuple[ResolvedSkill, ...]
    missing: tuple[str, ...]

    @property
    def executable(self) -> bool:
        return not self.missing and all(step.manifest.available for step in self.steps)


class SkillGraph:
    def __init__(self, manifests: list[SkillManifest], scoring_policy: ScoringPolicy | str = ScoringPolicy.BALANCED):
        self._manifests = {manifest.skill_id: manifest for manifest in manifests}
        self.scoring_policy = ScoringPolicy(scoring_policy)

    @property
    def manifests(self) -> tuple[SkillManifest, ...]:
        return tuple(self._manifests.values())

    def get(self, skill_id: str) -> SkillManifest:
        return self._manifests.get(
            skill_id,
            SkillManifest(skill_id=skill_id, name=skill_id, category="unknown", status="missing"),
        )

    def resolve(self, skill_ids: list[str]) -> SkillGraphResolution:
        ordered: list[ResolvedSkill] = []
        missing: list[str] = []
        seen: set[str] = set()
        visiting: set[str] = set()

        def visit(skill_id: str, selected_for: str | None = None) -> None:
            manifest = self._select_manifest(skill_id)
            if manifest.skill_id in visiting:
                raise ValueError(f"Skill dependency cycle detected at {manifest.skill_id}")
            if manifest.skill_id in seen:
                return

            visiting.add(manifest.skill_id)
            for dep_id in manifest.requires:
                visit(dep_id)
            visiting.remove(manifest.skill_id)

            seen.add(manifest.skill_id)
            ordered.append(ResolvedSkill(manifest, selected_for=selected_for if manifest.skill_id != skill_id else None))
            if not manifest.available:
                missing.append(manifest.skill_id)

        for skill_id in skill_ids:
            selected = self._select_manifest(skill_id)
            visit(skill_id, selected_for=skill_id if selected.skill_id != skill_id else None)

        return SkillGraphResolution(tuple(ordered), tuple(dict.fromkeys(missing)))

    def _select_manifest(self, skill_id: str) -> SkillManifest:
        manifest = self.get(skill_id)
        if manifest.available:
            return manifest
        fallbacks = [self.get(fallback_id) for fallback_id in manifest.fallback_to]
        available = [fallback for fallback in fallbacks if fallback.available]
        if not available:
            return manifest
        return sorted(
            available,
            key=lambda item: item.quality.score_for(self.scoring_policy),
            reverse=True,
        )[0]

    def to_mermaid(self, root_ids: list[str] | None = None) -> str:
        selected = [self.get(skill_id) for skill_id in root_ids] if root_ids else sorted(
            self._manifests.values(),
            key=lambda item: item.skill_id,
        )
        selected_ids = {manifest.skill_id for manifest in selected}
        if root_ids:
            for root_id in root_ids:
                self._collect_related(root_id, selected_ids)

        lines = ["graph TD"]
        for manifest in sorted((self.get(skill_id) for skill_id in selected_ids), key=lambda item: item.skill_id):
            node_id = _node_id(manifest.skill_id)
            label = f"{manifest.skill_id}\\n{manifest.status}\\nq={manifest.quality.score_for(self.scoring_policy):.2f}"
            lines.append(f'  {node_id}["{label}"]')
            for dep_id in manifest.requires:
                if dep_id in selected_ids:
                    lines.append(f"  {node_id} --> {_node_id(dep_id)}")
            for fallback_id in manifest.fallback_to:
                if fallback_id in selected_ids:
                    lines.append(f"  {node_id} -. fallback .-> {_node_id(fallback_id)}")
            for enhanced_id in manifest.enhances:
                if enhanced_id in selected_ids:
                    lines.append(f"  {node_id} -. enhances .-> {_node_id(enhanced_id)}")
        return "\n".join(lines)

    def _collect_related(self, skill_id: str, selected_ids: set[str]) -> None:
        manifest = self.get(skill_id)
        selected_ids.add(manifest.skill_id)
        for related_id in (*manifest.requires, *manifest.fallback_to, *manifest.enhances):
            if related_id not in selected_ids:
                self._collect_related(related_id, selected_ids)


def load_skill_manifests(directory: str | Path) -> list[SkillManifest]:
    root = Path(directory)
    manifests: list[SkillManifest] = []
    if not root.exists():
        return manifests
    for path in sorted(root.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        items = raw if isinstance(raw, list) else [raw]
        manifests.extend(_manifest_from_dict(item) for item in items if item)
    return manifests


def load_default_skill_graph(scoring_policy: ScoringPolicy | str = ScoringPolicy.BALANCED) -> SkillGraph:
    root = Path(__file__).resolve().parent.parent / "project_skills" / "skill_manifests"
    return SkillGraph(load_skill_manifests(root), scoring_policy=scoring_policy)


def _as_tuple(raw: Any) -> tuple[str, ...]:
    if not raw:
        return ()
    if isinstance(raw, str):
        return (raw,)
    return tuple(str(item) for item in raw)


def _manifest_from_dict(raw: dict[str, Any]) -> SkillManifest:
    quality_raw = raw.get("quality") or {}
    failures = []
    for item in raw.get("failure_patterns") or ():
        failures.append(
            FailurePattern(
                site=str(item.get("site", "")),
                trigger=str(item.get("trigger", "")),
                recovery=str(item.get("recovery", "")),
                cooldown_seconds=int(item.get("cooldown_seconds", 0) or 0),
            )
        )

    return SkillManifest(
        skill_id=str(raw["skill_id"]),
        name=str(raw.get("name") or raw["skill_id"]),
        category=str(raw.get("category") or "general"),
        status=str(raw.get("status") or "missing"),
        requires=_as_tuple(raw.get("requires")),
        enhances=_as_tuple(raw.get("enhances")),
        fallback_to=_as_tuple(raw.get("fallback_to")),
        provides=_as_tuple(raw.get("provides")),
        anti_patterns=_as_tuple(raw.get("anti_patterns")),
        tests=_as_tuple(raw.get("tests")),
        quality=SkillQuality(
            reliability=float(quality_raw.get("reliability", 0.0) or 0.0),
            speed=float(quality_raw.get("speed", 0.0) or 0.0),
            reuse=float(quality_raw.get("reuse", 0.0) or 0.0),
            complexity=float(quality_raw.get("complexity", 1.0) or 1.0),
            cost=float(quality_raw.get("cost", 0.5) or 0.0),
            token_usage=float(quality_raw.get("token_usage", 0.5) or 0.0),
            risk=float(quality_raw.get("risk", 0.5) or 0.0),
            success_rate=float(quality_raw.get("success_rate", 0.0) or 0.0),
        ),
        failure_patterns=tuple(failures),
    )


def _node_id(skill_id: str) -> str:
    return "skill_" + "".join(char if char.isalnum() else "_" for char in skill_id)
