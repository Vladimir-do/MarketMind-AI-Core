"""CRUD-слой для ContentPipelineArtifact — промежуточных артефактов пайплайна.

В отличие от DatabaseApprovalQueue (approval_records), это НЕ approval-
семантика: артефакты (ContentStrategy/SemanticPlan/FactCheckResult/
QualityReport) не проходят approve/reject, а просто версионируются для
истории и GET-роутов.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import desc, select

from app.database import ContentPipelineArtifact, Database

if TYPE_CHECKING:
    from pydantic import BaseModel

ArtifactType = str  # "content_strategy" | "semantic_plan" | "fact_check_report" | "quality_report"


class ArtifactStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def save_artifact(
        self,
        *,
        project_id: str,
        project_product_id: str,
        product_id: int,
        artifact_type: ArtifactType,
        payload: BaseModel,
        prompt_id: str | None = None,
        prompt_version: str | None = None,
        model_used: str | None = None,
        job_id: str | None = None,
    ) -> ContentPipelineArtifact:
        async with self._db.session() as s:
            result = await s.execute(
                select(ContentPipelineArtifact.version_number)
                .where(ContentPipelineArtifact.project_id == project_id)
                .where(ContentPipelineArtifact.project_product_id == project_product_id)
                .where(ContentPipelineArtifact.artifact_type == artifact_type)
                .order_by(desc(ContentPipelineArtifact.version_number))
                .limit(1)
            )
            last_version = result.scalar_one_or_none()
            record = ContentPipelineArtifact(
                artifact_id=uuid.uuid4().hex[:20],
                project_id=project_id,
                project_product_id=project_product_id,
                product_id=product_id,
                artifact_type=artifact_type,
                version_number=(last_version or 0) + 1,
                payload_json=payload.model_dump_json(),
                schema_version=1,
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                model_used=model_used,
                job_id=job_id,
                created_at=datetime.now(UTC),
            )
            s.add(record)
            await s.commit()
            await s.refresh(record)
            return record

    async def get_latest(
        self,
        *,
        project_id: str,
        project_product_id: str,
        artifact_type: ArtifactType,
    ) -> ContentPipelineArtifact | None:
        async with self._db.session() as s:
            result = await s.execute(
                select(ContentPipelineArtifact)
                .where(ContentPipelineArtifact.project_id == project_id)
                .where(ContentPipelineArtifact.project_product_id == project_product_id)
                .where(ContentPipelineArtifact.artifact_type == artifact_type)
                .order_by(desc(ContentPipelineArtifact.version_number))
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def list_history(
        self,
        *,
        project_id: str,
        project_product_id: str,
        artifact_type: ArtifactType,
        limit: int = 50,
    ) -> list[ContentPipelineArtifact]:
        async with self._db.session() as s:
            result = await s.execute(
                select(ContentPipelineArtifact)
                .where(ContentPipelineArtifact.project_id == project_id)
                .where(ContentPipelineArtifact.project_product_id == project_product_id)
                .where(ContentPipelineArtifact.artifact_type == artifact_type)
                .order_by(desc(ContentPipelineArtifact.version_number))
                .limit(limit)
            )
            return list(result.scalars().all())

    @staticmethod
    def payload_dict(record: ContentPipelineArtifact) -> dict:
        return json.loads(record.payload_json)
