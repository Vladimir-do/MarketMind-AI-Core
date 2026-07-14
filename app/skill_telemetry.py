from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ExecutionMetrics:
    execution_time_ms: int = 0
    failures: int = 0
    retries: int = 0
    token_usage: int = 0


@dataclass(frozen=True, slots=True)
class SkillRunRecord:
    skill_id: str
    status: str
    metrics: ExecutionMetrics = field(default_factory=ExecutionMetrics)
    failure_trigger: str | None = None
    recovery: str | None = None
    run_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def successful(self) -> bool:
        return self.status == "success"


@dataclass(frozen=True, slots=True)
class SkillTelemetrySummary:
    skill_id: str
    total_runs: int
    success_rate: float
    avg_execution_time_ms: int
    failures: int
    retries: int
    token_usage: int


class JsonlSkillTelemetryStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, record: SkillRunRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(record)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def load(self) -> list[SkillRunRecord]:
        if not self.path.exists():
            return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            records.append(
                SkillRunRecord(
                    skill_id=raw["skill_id"],
                    status=raw["status"],
                    metrics=ExecutionMetrics(**raw.get("metrics", {})),
                    failure_trigger=raw.get("failure_trigger"),
                    recovery=raw.get("recovery"),
                    run_id=raw.get("run_id"),
                    created_at=raw.get("created_at") or datetime.now(timezone.utc).isoformat(),
                )
            )
        return records

    def summarize(self, skill_id: str) -> SkillTelemetrySummary:
        records = [record for record in self.load() if record.skill_id == skill_id]
        if not records:
            return SkillTelemetrySummary(skill_id, 0, 0.0, 0, 0, 0, 0)
        total = len(records)
        successes = sum(1 for record in records if record.successful)
        execution_time = sum(record.metrics.execution_time_ms for record in records)
        failures = sum(record.metrics.failures for record in records)
        retries = sum(record.metrics.retries for record in records)
        token_usage = sum(record.metrics.token_usage for record in records)
        return SkillTelemetrySummary(
            skill_id=skill_id,
            total_runs=total,
            success_rate=round(successes / total, 4),
            avg_execution_time_ms=round(execution_time / total),
            failures=failures,
            retries=retries,
            token_usage=token_usage,
        )
