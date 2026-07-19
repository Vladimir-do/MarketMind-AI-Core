"""System status, backup and restore UI routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.backups.service import BackupError, create_database_backup, restore_database_backup
from app.database import Database
from app.runtime_paths import list_backups, runtime_layout, system_status
from app.web.app import templates

router = APIRouter()


@router.get("/system", response_class=HTMLResponse)
async def system_page(request: Request):
    status_data = await system_status(request.app.state.db)
    return templates.TemplateResponse(
        request,
        "system.html",
        {
            "status": status_data,
            "backups": list_backups(runtime_layout().backups_dir),
            "active": "system",
        },
    )


@router.post("/system/backups")
async def create_backup(request: Request):
    try:
        create_database_backup(reason="manual")
    except BackupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedirectResponse("/system", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/system/backups/{backup_name}/restore")
async def restore_backup(backup_name: str, request: Request):
    form = await request.form()
    try:
        current_db = request.app.state.db
        if hasattr(current_db, "_engine"):
            await current_db._engine.dispose()
        restore_database_backup(backup_name, confirmation=str(form.get("confirmation") or ""))
        new_db = Database()
        await new_db.init()
        request.app.state.db = new_db
    except BackupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedirectResponse("/system", status_code=status.HTTP_303_SEE_OTHER)
