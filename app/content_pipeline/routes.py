"""API-роуты Content Intelligence Pipeline."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.content_pipeline.artifact_store import ArtifactStore
from app.content_pipeline.jobs import JOB_TYPE, process_content_pipeline_job
from app.content_pipeline.parsing import ContentPipelineParseError
from app.content_pipeline.prompt_registry import PromptNotFoundError
from app.effective_card.service import EffectiveProductCardService
from app.projects.service import ProjectNotFoundError, ProjectService

router = APIRouter()
logger = logging.getLogger(__name__)

_ARTIFACT_ROUTE_TYPES = {
    "content-strategy": "content_strategy",
    "semantic-plan": "semantic_plan",
    "fact-check": "fact_check_report",
    "quality-report": "quality_report",
}


def _pipeline_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ProjectNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (PromptNotFoundError, ContentPipelineParseError)):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail="Не удалось выполнить операцию Content Pipeline")


async def _project_product_id(request: Request, project_id: str, product_id: int) -> str:
    project_product = await ProjectService(request.app.state.db).get_project_product(project_id, product_id)
    return project_product.project_product_id


async def _queue_pipeline_job(request: Request, project_id: str, product_id: int, background_tasks: BackgroundTasks):
    try:
        await EffectiveProductCardService(request.app.state.db).get_effective_card(project_id, product_id)
    except Exception as exc:
        raise _pipeline_error(exc) from exc

    job = await request.app.state.db.create_job(
        JOB_TYPE,
        {"project_id": project_id, "product_id": product_id},
    )
    background_tasks.add_task(process_content_pipeline_job, request.app, job.job_id, project_id, product_id)
    return job


@router.post("/api/projects/{project_id}/products/{product_id}/content-pipeline/run")
async def run_content_pipeline_route(
    project_id: str, product_id: int, request: Request, background_tasks: BackgroundTasks
):
    job = await _queue_pipeline_job(request, project_id, product_id, background_tasks)
    return {"job_id": job.job_id, "status": "queued"}


@router.post("/projects/{project_id}/products/{product_id}/content-pipeline/run")
async def run_content_pipeline_page(
    project_id: str, product_id: int, request: Request, background_tasks: BackgroundTasks
):
    """HTML-триггер запуска пайплайна со страницы товара проекта (не /api)."""
    await _queue_pipeline_job(request, project_id, product_id, background_tasks)
    return RedirectResponse(url=f"/projects/{project_id}/products/{product_id}", status_code=303)


@router.get("/api/content-pipeline/jobs/{job_id}")
async def get_content_pipeline_job(job_id: str, request: Request):
    record = await request.app.state.db.get_job(job_id)
    if record is None or record.job_type != JOB_TYPE:
        raise HTTPException(status_code=404, detail="Job not found")

    result = None
    if record.result_json:
        try:
            result = json.loads(record.result_json)
        except (TypeError, ValueError):
            result = None

    return {
        "job_id": record.job_id,
        "status": record.status,
        "progress": record.progress,
        "result": result,
        "error_class": record.error_class,
        "error_text": record.error_text,
        "created_at": record.created_at,
        "finished_at": record.finished_at,
    }


def _register_artifact_route(route_suffix: str, artifact_type: str) -> None:
    @router.get(f"/api/projects/{{project_id}}/products/{{product_id}}/{route_suffix}")
    async def _get_latest_artifact(project_id: str, product_id: int, request: Request):
        try:
            project_product_id = await _project_product_id(request, project_id, product_id)
        except Exception as exc:
            raise _pipeline_error(exc) from exc

        store = ArtifactStore(request.app.state.db)
        record = await store.get_latest(
            project_id=project_id, project_product_id=project_product_id, artifact_type=artifact_type
        )
        if record is None:
            raise HTTPException(status_code=404, detail=f"No {artifact_type} generated yet for this product")
        return {
            "artifact_id": record.artifact_id,
            "version_number": record.version_number,
            "prompt_id": record.prompt_id,
            "prompt_version": record.prompt_version,
            "model_used": record.model_used,
            "created_at": record.created_at,
            "payload": store.payload_dict(record),
        }

    @router.get(f"/api/projects/{{project_id}}/products/{{product_id}}/{route_suffix}/history")
    async def _get_artifact_history(project_id: str, product_id: int, request: Request, limit: int = 50):
        try:
            project_product_id = await _project_product_id(request, project_id, product_id)
        except Exception as exc:
            raise _pipeline_error(exc) from exc

        store = ArtifactStore(request.app.state.db)
        records = await store.list_history(
            project_id=project_id,
            project_product_id=project_product_id,
            artifact_type=artifact_type,
            limit=limit,
        )
        return [
            {
                "artifact_id": r.artifact_id,
                "version_number": r.version_number,
                "created_at": r.created_at,
                "payload": store.payload_dict(r),
            }
            for r in records
        ]


for _suffix, _artifact_type in _ARTIFACT_ROUTE_TYPES.items():
    _register_artifact_route(_suffix, _artifact_type)
