"""Project-scoped archive export."""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.backups.service import sha256_file
from app.database import (
    ClientProject,
    ClientProjectFile,
    Database,
    DomainEventRecord,
    ProductCardVersion,
    ProjectExport,
    ProjectProduct,
    ProjectReport,
)
from app.exports.service import ProjectExportService
from app.projects.service import ProjectNotFoundError
from app.workspace.files import project_artifact_path, project_root


class ProjectArchiveError(ValueError):
    """Project archive operation failed."""


class ProjectArchiveService:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create_project_archive(self, project_id: str) -> dict[str, Any]:
        root = project_root(project_id)
        async with self._db.session() as session:
            project = await session.get(ClientProject, project_id)
            if project is None:
                raise ProjectNotFoundError("Проект не найден")
        export_service = ProjectExportService(self._db)
        await export_service.create_export(project_id, file_format="csv")
        await export_service.create_export(project_id, file_format="xlsx")
        manifest = await self._manifest(project_id)
        archive_name = f"project_{project_id}_archive_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.zip"
        archive_path, relative_path = project_artifact_path(project_id, "archives", archive_name)
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        checksums: dict[str, str] = {}
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            if root.exists():
                for path in sorted(root.rglob("*")):
                    if not path.is_file() or path == archive_path:
                        continue
                    rel = path.relative_to(root).as_posix()
                    if _is_forbidden_archive_path(rel):
                        continue
                    checksums[rel] = sha256_file(path)
                    archive.write(path, f"project/{rel}")
            manifest["checksums"] = checksums
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
            archive.writestr("history/project_history.json", json.dumps(manifest["history"], ensure_ascii=False, indent=2, sort_keys=True))
        return {
            "project_id": project_id,
            "relative_path": relative_path,
            "absolute_path": archive_path,
            "size_bytes": archive_path.stat().st_size,
            "checksum": sha256_file(archive_path),
            "manifest": manifest,
        }

    async def _manifest(self, project_id: str) -> dict[str, Any]:
        async with self._db.session() as session:
            project = await session.get(ClientProject, project_id)
            files = (
                await session.execute(select(ClientProjectFile).where(ClientProjectFile.project_id == project_id))
            ).scalars().all()
            products = (
                await session.execute(select(ProjectProduct).where(ProjectProduct.project_id == project_id))
            ).scalars().all()
            exports = (
                await session.execute(select(ProjectExport).where(ProjectExport.project_id == project_id))
            ).scalars().all()
            reports = (
                await session.execute(select(ProjectReport).where(ProjectReport.project_id == project_id))
            ).scalars().all()
            versions = (
                await session.execute(select(ProductCardVersion).where(ProductCardVersion.project_id == project_id))
            ).scalars().all()
            events = (
                await session.execute(
                    select(DomainEventRecord).where(DomainEventRecord.metadata_json.like(f"%{project_id}%"))
                )
            ).scalars().all()
        if project is None:
            raise ProjectNotFoundError("Проект не найден")
        return {
            "project": _project_dict(project),
            "generated_at": datetime.now(UTC).isoformat(),
            "included": {
                "source_files": len(files),
                "project_products": len(products),
                "exports": len(exports),
                "reports": len(reports),
                "versions": len(versions),
                "events": len(events),
            },
            "history": {
                "files": [_file_dict(item) for item in files],
                "project_products": [_project_product_dict(item) for item in products],
                "exports": [_export_dict(item) for item in exports],
                "reports": [_report_dict(item) for item in reports],
                "versions": [_version_dict(item) for item in versions],
                "events": [_event_dict(item) for item in events],
            },
        }


def _is_forbidden_archive_path(relative_path: str) -> bool:
    lower = relative_path.lower()
    return (
        lower.startswith("../")
        or "/../" in lower
        or lower.startswith(".env")
        or "/.env" in lower
        or "token" in lower
        or "secret" in lower
        or lower.endswith(".log")
    )


def _project_dict(project: ClientProject) -> dict[str, Any]:
    return {
        "project_id": project.project_id,
        "name": project.name,
        "client_name": project.client_name,
        "marketplace": project.marketplace,
        "status": project.status,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }


def _file_dict(record: ClientProjectFile) -> dict[str, Any]:
    return {
        "file_id": record.file_id,
        "original_filename": record.original_filename,
        "relative_path": record.relative_path,
        "sha256": record.sha256,
        "size_bytes": record.size_bytes,
    }


def _project_product_dict(record: ProjectProduct) -> dict[str, Any]:
    return {
        "project_product_id": record.project_product_id,
        "product_id": record.product_id,
        "status": record.status,
        "source_file_id": record.source_file_id,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        "effective_updated_at": record.effective_updated_at.isoformat() if record.effective_updated_at else None,
    }


def _export_dict(record: ProjectExport) -> dict[str, Any]:
    return {
        "export_id": record.export_id,
        "file_format": record.file_format,
        "relative_path": record.relative_path,
        "checksum": record.checksum,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _report_dict(record: ProjectReport) -> dict[str, Any]:
    return {
        "report_id": record.report_id,
        "file_format": record.file_format,
        "relative_path": record.relative_path,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _version_dict(record: ProductCardVersion) -> dict[str, Any]:
    return {
        "version_id": record.version_id,
        "product_id": record.product_id,
        "project_product_id": record.project_product_id,
        "version_number": record.version_number,
        "source": record.source,
        "comment": record.comment,
        "checksum": record.checksum,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _event_dict(record: DomainEventRecord) -> dict[str, Any]:
    return {
        "event_id": record.event_id,
        "aggregate_type": record.aggregate_type,
        "aggregate_id": record.aggregate_id,
        "event_type": record.event_type,
        "source": record.source,
        "occurred_at": record.occurred_at.isoformat() if record.occurred_at else None,
        "correlation_id": record.correlation_id,
    }
