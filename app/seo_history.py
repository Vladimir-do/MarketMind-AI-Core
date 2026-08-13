"""SEO measurement cycle — in-memory snapshot tracker for SEO audit history."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.semantic_core import SemanticCore
from app.seo_intelligence import SEOAuditResult

_MAX_SNAPSHOTS_PER_PRODUCT = 1000


@dataclass
class SEOAuditSnapshot:
    product_id: int
    project_id: str
    score: int
    tier: str
    semantic_coverage: float
    semantic_junk: float
    findings_count: int
    recommendations_count: int
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        return d


class SEOHistoryService:
    """In-memory SEO snapshot history tracker."""

    def __init__(self) -> None:
        self._store: dict[str, list[SEOAuditSnapshot]] = {}

    @staticmethod
    def _key(project_id: str, product_id: int) -> str:
        return f"{project_id}:{product_id}"

    async def record_audit(
        self,
        project_id: str,
        product_id: int,
        seo_result: SEOAuditResult,
        semantic_core: SemanticCore,
    ) -> SEOAuditSnapshot:
        snapshot = SEOAuditSnapshot(
            product_id=product_id,
            project_id=project_id,
            score=seo_result.score,
            tier=seo_result.tier,
            semantic_coverage=semantic_core.coverage_score,
            semantic_junk=semantic_core.junk_ratio,
            findings_count=len(seo_result.findings),
            recommendations_count=len(seo_result.recommendations),
        )
        key = self._key(project_id, product_id)
        if key not in self._store:
            self._store[key] = []
        self._store[key].append(snapshot)
        if len(self._store[key]) > _MAX_SNAPSHOTS_PER_PRODUCT:
            self._store[key] = self._store[key][-_MAX_SNAPSHOTS_PER_PRODUCT:]
        return snapshot

    async def get_history(
        self, project_id: str, product_id: int, limit: int = 50
    ) -> list[SEOAuditSnapshot]:
        key = self._key(project_id, product_id)
        items = self._store.get(key, [])
        return list(reversed(items[-limit:]))

    async def get_latest(
        self, project_id: str, product_id: int
    ) -> SEOAuditSnapshot | None:
        key = self._key(project_id, product_id)
        items = self._store.get(key, [])
        return items[-1] if items else None

    async def get_score_trend(
        self, project_id: str, product_id: int
    ) -> list[dict[str, Any]]:
        key = self._key(project_id, product_id)
        items = self._store.get(key, [])
        return [
            {
                "score": snapshot.score,
                "tier": snapshot.tier,
                "created_at": snapshot.created_at.isoformat(),
            }
            for snapshot in items
        ]
