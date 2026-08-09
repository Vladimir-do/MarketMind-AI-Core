"""SQLite backup and restore service for local production mode."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.runtime_paths import ensure_runtime_layout, sqlite_database_path


class BackupError(ValueError):
    """Backup or restore failed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_database_backup(*, reason: str = "manual", db_path: Path | None = None, backups_dir: Path | None = None) -> dict:
    source = db_path or sqlite_database_path()
    if source is None:
        raise BackupError("Поддерживается только SQLite backup")
    layout = ensure_runtime_layout()
    target_dir = backups_dir or layout.backups_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    safe_reason = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in reason)[:40] or "backup"
    target = target_dir / f"marketmind_{timestamp}_{safe_reason}.db"
    if source.exists():
        with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
            src.backup(dst)
    else:
        target.touch()
    return backup_record(target)


def create_backup_if_database_exists(*, reason: str = "startup") -> dict | None:
    db_path = sqlite_database_path()
    if db_path is None or not db_path.exists():
        return None
    return create_database_backup(reason=reason, db_path=db_path)


def backup_record(path: Path) -> dict:
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path),
        "size_bytes": stat.st_size,
        "created_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        "checksum": sha256_file(path),
    }


def restore_database_backup(backup_name: str, *, confirmation: str, db_path: Path | None = None, backups_dir: Path | None = None) -> dict:
    if confirmation != "ВОССТАНОВИТЬ":
        raise BackupError("Для восстановления введите ВОССТАНОВИТЬ")
    target_db = db_path or sqlite_database_path()
    if target_db is None:
        raise BackupError("Поддерживается только SQLite restore")
    layout = ensure_runtime_layout()
    source_dir = backups_dir or layout.backups_dir
    backup_path = source_dir / Path(backup_name).name
    if not backup_path.exists() or not backup_path.is_file():
        raise BackupError("Резервная копия не найдена")
    protective = create_database_backup(reason="pre_restore", db_path=target_db, backups_dir=source_dir)
    target_db.parent.mkdir(parents=True, exist_ok=True)
    # Copy into a temp file first, then atomically swap it into place.
    # A concurrent connection that already has target_db open keeps seeing a
    # fully-consistent file (old or new) at every instant this way -- an
    # in-place shutil.copy2() straight onto the live path could expose a
    # partially-overwritten file to any reader active during the copy.
    tmp_path = target_db.with_name(f"{target_db.name}.restore_tmp")
    shutil.copy2(backup_path, tmp_path)
    os.replace(tmp_path, target_db)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{target_db}{suffix}")
        sidecar.unlink(missing_ok=True)
    restored = backup_record(target_db)
    return {"restored": restored, "protective_backup": protective}
