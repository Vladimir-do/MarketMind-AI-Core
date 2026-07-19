"""Runtime mode, filesystem layout and status helpers."""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select

from app.config import DATABASE_URL, MARKETMIND_WORKSPACE_DIR, PROJECT_ROOT, RUNTIME_DATA_DIR
from app.database import ClientProject, Database

LOW_SPACE_BYTES = 1024 * 1024 * 1024
WORK_MODE_MESSAGE = "РАБОЧИЙ РЕЖИМ. ДАННЫЕ СОХРАНЯЮТСЯ"
DEMO_MODE_MESSAGE = "ДЕМОНСТРАЦИОННЫЙ РЕЖИМ. ДАННЫЕ МОГУТ БЫТЬ УДАЛЕНЫ"


@dataclass(frozen=True)
class RuntimeLayout:
    home: Path
    database_dir: Path
    projects_dir: Path
    uploads_dir: Path
    exports_dir: Path
    reports_dir: Path
    backups_dir: Path
    logs_dir: Path


def runtime_layout(home: Path | None = None) -> RuntimeLayout:
    root = home or Path(os.getenv("MARKETMIND_HOME", "") or RUNTIME_DATA_DIR)
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    return RuntimeLayout(
        home=root,
        database_dir=root / "database",
        projects_dir=root / "projects",
        uploads_dir=root / "uploads",
        exports_dir=root / "exports",
        reports_dir=root / "reports",
        backups_dir=root / "backups",
        logs_dir=root / "logs",
    )


def ensure_runtime_layout(home: Path | None = None) -> RuntimeLayout:
    layout = runtime_layout(home)
    for path in (
        layout.home,
        layout.database_dir,
        layout.projects_dir,
        layout.uploads_dir,
        layout.exports_dir,
        layout.reports_dir,
        layout.backups_dir,
        layout.logs_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
    return layout


def sqlite_database_path(database_url: str = DATABASE_URL) -> Path | None:
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        return None
    path = Path(database_url.removeprefix(prefix))
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def runtime_mode() -> str:
    return os.getenv("MARKETMIND_MODE", "work").strip().lower() or "work"


def runtime_banner() -> dict[str, str]:
    mode = runtime_mode()
    if mode == "demo":
        return {"mode": "demo", "message": DEMO_MODE_MESSAGE, "css": "bg-yellow-100 text-yellow-900 border-yellow-300"}
    return {"mode": "work", "message": WORK_MODE_MESSAGE, "css": "bg-green-100 text-green-900 border-green-300"}


def is_tmp_path(path: Path) -> bool:
    try:
        resolved = path.resolve()
        tmp = Path(tempfile.gettempdir()).resolve()
        return resolved == tmp or tmp in resolved.parents
    except OSError:
        return False


async def system_status(db: Database) -> dict:
    layout = runtime_layout()
    db_path = sqlite_database_path()
    workspace_path = MARKETMIND_WORKSPACE_DIR
    disk = shutil.disk_usage(layout.home if layout.home.exists() else layout.home.parent)
    async with db.session() as session:
        total_projects = await session.scalar(select(func.count()).select_from(ClientProject))
        active_projects = await session.scalar(
            select(func.count()).select_from(ClientProject).where(ClientProject.status != "archived")
        )
    backups = list_backups(layout.backups_dir)
    warnings = []
    if is_tmp_path(layout.home) or is_tmp_path(workspace_path) or (db_path is not None and is_tmp_path(db_path)):
        warnings.append("Рабочие данные находятся во временном каталоге /tmp.")
    if disk.free < int(os.getenv("MARKETMIND_LOW_SPACE_BYTES", str(LOW_SPACE_BYTES))):
        warnings.append("Осталось мало свободного места.")
    return {
        "mode": runtime_banner(),
        "database_path": str(db_path) if db_path else DATABASE_URL,
        "workspace_path": str(workspace_path),
        "runtime_home": str(layout.home),
        "free_space_bytes": disk.free,
        "free_space_human": human_bytes(disk.free),
        "last_backup": backups[0] if backups else None,
        "schema_version": read_schema_version(db_path),
        "project_count": int(total_projects or 0),
        "active_project_count": int(active_projects or 0),
        "warnings": warnings,
    }


def read_schema_version(db_path: Path | None) -> str:
    if db_path is None or not db_path.exists():
        return "not initialized"
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("SELECT version_num FROM alembic_version ORDER BY version_num LIMIT 1").fetchone()
            return str(row[0]) if row else "create_all"
    except sqlite3.Error:
        return "unknown"


def list_backups(backups_dir: Path | None = None) -> list[dict]:
    from app.backups.service import backup_record

    directory = backups_dir or runtime_layout().backups_dir
    if not directory.exists():
        return []
    records = [backup_record(path) for path in directory.glob("*.db") if path.is_file()]
    return sorted(records, key=lambda item: item["created_at"], reverse=True)


def human_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{value} B"
