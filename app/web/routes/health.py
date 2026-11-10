"""Liveness and database-readiness endpoints."""

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Report that the web process is alive; do not depend on external services."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> dict[str, str]:
    """Report readiness only when the configured database answers a trivial query."""
    db = getattr(request.app.state, "db", None)
    if db is None or not hasattr(db, "_engine"):
        raise HTTPException(status_code=503, detail="Database is not initialized")
    try:
        async with db._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="Database is not ready") from None
    return {"status": "ready", "database": "ok"}
