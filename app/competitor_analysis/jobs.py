"""Фоновая job-обвязка для обновления конкурентного анализа.

По образцу app.content_pipeline.jobs.process_content_pipeline_job.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.competitor_analysis.service import CompetitorAnalysisService
from app.projects.service import ProjectNotFoundError

if TYPE_CHECKING:
    from app.database import Database

logger = logging.getLogger(__name__)

JOB_TYPE = "competitor_analysis_refresh"


async def process_competitor_refresh_job(app, job_id: str, project_id: str, product_id: int) -> dict[str, Any]:
    db: Database = app.state.db
    logger.info(
        "Competitor refresh queued job_id=%s project_id=%s product_id=%s stage=queued",
        job_id,
        project_id,
        product_id,
    )
    await db.start_job(job_id)

    try:
        service = CompetitorAnalysisService(db)
        batch_id, records = await service.refresh_competitors(project_id, product_id)
        result = {
            "job_id": job_id,
            "project_id": project_id,
            "product_id": product_id,
            "status": "completed",
            "batch_id": batch_id,
            "competitor_count": len(records),
        }
        await db.finish_job(job_id, result)
        logger.info(
            "Competitor refresh completed job_id=%s project_id=%s product_id=%s count=%s stage=completed",
            job_id,
            project_id,
            product_id,
            len(records),
        )
        return result
    except ProjectNotFoundError as exc:
        logger.warning("Competitor refresh job %s failed: %s", job_id, exc, exc_info=True)
        await db.fail_job(job_id, exc, details={"job_id": job_id, "project_id": project_id, "product_id": product_id})
        raise
    except Exception as exc:
        logger.warning("Competitor refresh job %s failed: %s", job_id, exc, exc_info=True)
        await db.fail_job(job_id, exc)
        raise
