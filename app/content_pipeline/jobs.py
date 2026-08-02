"""Фоновая job-обвязка для Content Intelligence Pipeline.

По образцу app.ai_recommendation.job_queue.process_project_seo_suggestion_job:
db.start_job -> пайплайн -> db.finish_job / db.fail_job.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.content_pipeline.parsing import ContentPipelineParseError
from app.content_pipeline.pipeline import run_content_pipeline
from app.content_pipeline.prompt_registry import PromptNotFoundError
from app.projects.service import ProjectNotFoundError

if TYPE_CHECKING:
    from app.database import Database

logger = logging.getLogger(__name__)

JOB_TYPE = "content_pipeline"


async def process_content_pipeline_job(app, job_id: str, project_id: str, product_id: int) -> dict[str, Any]:
    db: Database = app.state.db
    logger.info(
        "Content pipeline queued job_id=%s project_id=%s product_id=%s stage=queued",
        job_id, project_id, product_id,
    )
    await db.start_job(job_id)

    try:
        run_result = await run_content_pipeline(db, project_id=project_id, product_id=product_id, job_id=job_id)
        result = {
            "job_id": job_id,
            "project_id": project_id,
            "product_id": product_id,
            "status": "completed",
            "cqi": run_result.quality_report.cqi,
            "marketplace_ready": run_result.quality_report.marketplace_ready,
            "fact_check_contradicted": run_result.fact_check_contradicted,
            "approval_ids": run_result.approval_ids,
        }
        await db.finish_job(job_id, result)
        logger.info(
            "Content pipeline completed job_id=%s project_id=%s product_id=%s cqi=%s stage=completed",
            job_id, project_id, product_id, run_result.quality_report.cqi,
        )
        return result
    except (ProjectNotFoundError, PromptNotFoundError, ContentPipelineParseError) as exc:
        logger.warning("Content pipeline job %s failed: %s", job_id, exc, exc_info=True)
        await db.fail_job(job_id, exc, details={"job_id": job_id, "project_id": project_id, "product_id": product_id})
        raise
    except Exception as exc:
        logger.warning("Content pipeline job %s failed: %s", job_id, exc, exc_info=True)
        await db.fail_job(job_id, exc)
        raise
