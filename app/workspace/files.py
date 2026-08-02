"""Safe local workspace file handling."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import IMPORT_MAX_FILE_BYTES, MARKETMIND_WORKSPACE_DIR

_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9а-яА-ЯёЁ._-]+")
_SUPPORTED_IMPORT_SUFFIXES = {".csv", ".xlsx", ".xlsm"}


class WorkspaceError(ValueError):
    """Workspace operation failed safely."""


@dataclass(frozen=True)
class StoredProjectFile:
    original_filename: str
    stored_filename: str
    relative_path: str
    absolute_path: Path
    sha256: str
    size_bytes: int
    file_format: str


def project_root(project_id: str) -> Path:
    return MARKETMIND_WORKSPACE_DIR / "projects" / _safe_segment(project_id)


def project_subdir(project_id: str, name: str) -> Path:
    root = project_root(project_id)
    target = root / name
    _ensure_inside(root, target)
    target.mkdir(parents=True, exist_ok=True)
    return target


def store_source_file(project_id: str, filename: str, content: bytes) -> StoredProjectFile:
    original = Path(filename or "upload").name
    suffix = Path(original).suffix.lower()
    if suffix not in _SUPPORTED_IMPORT_SUFFIXES:
        raise WorkspaceError("Формат файла не поддерживается")
    if not content:
        raise WorkspaceError("Файл пустой")
    if len(content) > IMPORT_MAX_FILE_BYTES:
        raise WorkspaceError("Файл слишком большой для безопасного импорта")
    digest = hashlib.sha256(content).hexdigest()
    safe_stem = _safe_filename(Path(original).stem)[:80] or "source"
    stored_name = f"{safe_stem}_{digest[:12]}{suffix}"
    source_dir = project_subdir(project_id, "source")
    target = source_dir / stored_name
    _ensure_inside(project_root(project_id), target)
    if not target.exists():
        target.write_bytes(content)
    relative_path = target.relative_to(project_root(project_id)).as_posix()
    return StoredProjectFile(
        original_filename=original,
        stored_filename=stored_name,
        relative_path=relative_path,
        absolute_path=target,
        sha256=digest,
        size_bytes=len(content),
        file_format=suffix.removeprefix("."),
    )


def stored_source_file(project_id: str, relative_path: str, *, original_filename: str, sha256: str, size_bytes: int, file_format: str) -> StoredProjectFile:
    root = project_root(project_id)
    target = root / relative_path
    _ensure_inside(root, target)
    if not target.exists() or not target.is_file():
        raise WorkspaceError("Сохранённый файл импорта не найден")
    return StoredProjectFile(
        original_filename=Path(original_filename).name,
        stored_filename=target.name,
        relative_path=target.relative_to(root).as_posix(),
        absolute_path=target,
        sha256=sha256,
        size_bytes=size_bytes,
        file_format=file_format,
    )


def project_artifact_path(project_id: str, folder: str, filename: str) -> tuple[Path, str]:
    safe_name = _safe_filename(filename)
    if not safe_name:
        safe_name = f"artifact_{uuid.uuid4().hex[:8]}"
    target_dir = project_subdir(project_id, folder)
    target = target_dir / safe_name
    _ensure_inside(project_root(project_id), target)
    relative_path = target.relative_to(project_root(project_id)).as_posix()
    return target, relative_path


def _safe_segment(value: str) -> str:
    cleaned = _safe_filename(value)
    if not cleaned or cleaned in {".", ".."}:
        raise WorkspaceError("Некорректный идентификатор проекта")
    return cleaned


def _safe_filename(value: str) -> str:
    name = Path(value).name.strip().replace("\x00", "")
    name = _SAFE_NAME_RE.sub("_", name)
    name = name.strip("._ ")
    return name[:120]


def _ensure_inside(root: Path, target: Path) -> None:
    root_resolved = root.resolve()
    target_resolved = target.resolve()
    if root_resolved != target_resolved and root_resolved not in target_resolved.parents:
        raise WorkspaceError("Путь выходит за пределы проекта")
