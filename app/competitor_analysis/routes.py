"""API-роуты Competitor Analysis."""

from __future__ import annotations

import json
import logging
import statistics

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.competitor_analysis.jobs import JOB_TYPE, process_competitor_refresh_job
from app.competitor_analysis.store import CompetitorSnapshotStore
from app.effective_card.service import EffectiveProductCardService
from app.projects.service import ProjectNotFoundError, ProjectService

router = APIRouter()
logger = logging.getLogger(__name__)


def _competitor_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ProjectNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=500, detail="Не удалось выполнить операцию Competitor Analysis")


def _snapshot_to_dict(record) -> dict:
    return {
        "snapshot_id": record.snapshot_id,
        "batch_id": record.batch_id,
        "marketplace": record.marketplace,
        "competitor_name": record.competitor_name,
        "competitor_url": record.competitor_url,
        "price": record.price,
        "old_price": record.old_price,
        "rating": record.rating,
        "reviews_count": record.reviews_count,
        "reviews": CompetitorSnapshotStore.reviews_of(record),
        "search_query": record.search_query,
        "created_at": record.created_at,
    }


def _batch_aggregates(records: list) -> dict:
    prices = [r.price for r in records if r.price is not None]
    ratings = [r.rating for r in records if r.rating is not None]
    return {
        "count": len(records),
        "median_price": statistics.median(prices) if prices else None,
        "min_price": min(prices) if prices else None,
        "max_price": max(prices) if prices else None,
        "min_rating": min(ratings) if ratings else None,
        "max_rating": max(ratings) if ratings else None,
    }


async def _queue_refresh_job(request: Request, project_id: str, product_id: int, background_tasks: BackgroundTasks):
    try:
        await EffectiveProductCardService(request.app.state.db).get_effective_card(project_id, product_id)
    except Exception as exc:
        raise _competitor_error(exc) from exc

    job = await request.app.state.db.create_job(
        JOB_TYPE,
        {"project_id": project_id, "product_id": product_id},
    )
    background_tasks.add_task(process_competitor_refresh_job, request.app, job.job_id, project_id, product_id)
    return job


@router.post("/api/projects/{project_id}/products/{product_id}/competitors/refresh")
async def refresh_competitors_route(
    project_id: str, product_id: int, request: Request, background_tasks: BackgroundTasks
):
    job = await _queue_refresh_job(request, project_id, product_id, background_tasks)
    return {"job_id": job.job_id, "status": "queued"}


@router.post("/projects/{project_id}/products/{product_id}/competitors/refresh")
async def refresh_competitors_page(
    project_id: str, product_id: int, request: Request, background_tasks: BackgroundTasks
):
    """HTML-триггер со страницы товара проекта (не /api)."""
    await _queue_refresh_job(request, project_id, product_id, background_tasks)
    return RedirectResponse(url=f"/projects/{project_id}/products/{product_id}", status_code=303)


@router.get("/api/projects/{project_id}/products/{product_id}/competitors")
async def get_latest_competitors(project_id: str, product_id: int, request: Request):
    try:
        project_product = await ProjectService(request.app.state.db).get_project_product(project_id, product_id)
    except Exception as exc:
        raise _competitor_error(exc) from exc

    store = CompetitorSnapshotStore(request.app.state.db)
    records = await store.get_latest_batch(
        project_id=project_id, project_product_id=project_product.project_product_id
    )
    if not records:
        raise HTTPException(status_code=404, detail="Конкурентный анализ ещё не запускался для этого товара")
    return {
        "batch_id": records[0].batch_id,
        "aggregates": _batch_aggregates(records),
        "competitors": [_snapshot_to_dict(r) for r in records],
    }


@router.get("/api/projects/{project_id}/products/{product_id}/competitors/history")
async def get_competitors_history(project_id: str, product_id: int, request: Request, limit: int = 20):
    try:
        project_product = await ProjectService(request.app.state.db).get_project_product(project_id, product_id)
    except Exception as exc:
        raise _competitor_error(exc) from exc

    store = CompetitorSnapshotStore(request.app.state.db)
    batches = await store.list_batches(
        project_id=project_id, project_product_id=project_product.project_product_id, limit=limit
    )
    return [
        {
            "batch_id": batch[0].batch_id,
            "created_at": batch[0].created_at,
            "aggregates": _batch_aggregates(batch),
            "competitors": [_snapshot_to_dict(r) for r in batch],
        }
        for batch in batches
    ]


@router.get("/api/competitor-analysis/jobs/{job_id}")
async def get_competitor_refresh_job(job_id: str, request: Request):
    from app.database import JobRecord

    db = request.app.state.db
    async with db.session() as session:
        record = await session.get(JobRecord, job_id)
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
