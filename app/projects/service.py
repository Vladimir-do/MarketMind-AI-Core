"""Local client project workflow service."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import desc, select

from app.database import (
    ClientProject,
    ClientProjectFile,
    Database,
    ImportMappingPreset,
    ProjectProduct,
)
from app.editor.service import ProductCardEditorService
from app.workspace.files import StoredProjectFile, project_root

if TYPE_CHECKING:
    from app.products.schema import UnifiedProduct


class ProjectError(ValueError):
    """Base project workflow error."""


class ProjectNotFoundError(ProjectError):
    """Project was not found."""


class ProjectConflictError(ProjectError):
    """Project operation conflicts with current state."""


class ProjectService:
    """Coordinates local client projects and project product links."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create_project(
        self,
        *,
        name: str,
        client_name: str | None = None,
        marketplace: str = "unknown",
        description: str | None = None,
        notes: str | None = None,
    ) -> ClientProject:
        now = datetime.now(UTC)
        project_id = f"project_{uuid.uuid4().hex[:12]}"
        export_directory = (project_root(project_id) / "exports").as_posix()
        async with self._db.session() as session:
            project = ClientProject(
                project_id=project_id,
                name=_required_text(name, "Название проекта обязательно"),
                client_name=_optional_text(client_name),
                marketplace=_optional_text(marketplace) or "unknown",
                status="new",
                description=_optional_text(description),
                notes=_optional_text(notes),
                export_directory=export_directory,
                created_at=now,
                updated_at=now,
            )
            session.add(project)
            await session.commit()
            return project

    async def list_projects(self, *, include_archived: bool = False) -> list[ClientProject]:
        async with self._db.session() as session:
            stmt = select(ClientProject).order_by(desc(ClientProject.updated_at))
            if not include_archived:
                stmt = stmt.where(ClientProject.status != "archived")
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_project(self, project_id: str) -> ClientProject:
        async with self._db.session() as session:
            project = await session.get(ClientProject, project_id)
            if project is None:
                raise ProjectNotFoundError("Проект не найден")
            return project

    async def update_project(self, project_id: str, updates: dict[str, Any]) -> ClientProject:
        async with self._db.session() as session:
            project = await session.get(ClientProject, project_id)
            if project is None:
                raise ProjectNotFoundError("Проект не найден")
            for field in ("name", "client_name", "marketplace", "description", "notes"):
                if field in updates:
                    value = _required_text(updates[field], "Название проекта обязательно") if field == "name" else _optional_text(updates[field])
                    setattr(project, field, value)
            if "status" in updates:
                project.status = _normalize_status(updates["status"])
                if project.status == "completed":
                    project.completed_at = datetime.now(UTC)
            project.updated_at = datetime.now(UTC)
            await session.commit()
            return project

    async def archive_project(self, project_id: str) -> ClientProject:
        return await self.update_project(project_id, {"status": "archived"})

    async def record_source_file(
        self,
        project_id: str,
        stored: StoredProjectFile,
        *,
        row_count: int | None = None,
        successful_rows: int = 0,
        warning_count: int = 0,
        error_count: int = 0,
        errors: list[str] | None = None,
        schema_version: str = "local-import-v1",
        encoding: str | None = None,
        delimiter: str | None = None,
        selected_sheet: str | None = None,
        summary: dict[str, Any] | None = None,
    ) -> tuple[ClientProjectFile, bool]:
        now = datetime.now(UTC)
        async with self._db.session() as session:
            project = await session.get(ClientProject, project_id)
            if project is None:
                raise ProjectNotFoundError("Проект не найден")
            existing = await session.scalar(
                select(ClientProjectFile)
                .where(ClientProjectFile.project_id == project_id)
                .where(ClientProjectFile.sha256 == stored.sha256)
            )
            if existing is not None:
                return existing, False
            record = ClientProjectFile(
                file_id=f"file_{uuid.uuid4().hex[:12]}",
                project_id=project_id,
                original_filename=stored.original_filename,
                stored_filename=stored.stored_filename,
                relative_path=stored.relative_path,
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                file_format=stored.file_format,
                schema_version=schema_version,
                encoding=encoding,
                delimiter=delimiter,
                selected_sheet=selected_sheet,
                row_count=row_count,
                successful_rows=successful_rows,
                warning_count=warning_count,
                error_count=error_count,
                import_status="completed" if not errors else "completed_with_errors",
                import_errors_json=json.dumps(errors or [], ensure_ascii=False),
                import_summary_json=json.dumps(summary or {}, ensure_ascii=False, sort_keys=True),
                imported_at=now,
                created_at=now,
            )
            session.add(record)
            project.source_filename = stored.original_filename
            project.source_file_hash = stored.sha256
            project.source_imported_at = now
            project.status = "in_progress" if project.status == "new" else project.status
            project.updated_at = now
            await session.commit()
            return record, True

    async def source_file_exists(self, project_id: str, sha256: str) -> bool:
        async with self._db.session() as session:
            await self._require_project(session, project_id)
            existing = await session.scalar(
                select(ClientProjectFile)
                .where(ClientProjectFile.project_id == project_id)
                .where(ClientProjectFile.sha256 == sha256)
            )
            return existing is not None

    async def list_mapping_presets(self, project_id: str) -> list[ImportMappingPreset]:
        async with self._db.session() as session:
            await self._require_project(session, project_id)
            result = await session.execute(
                select(ImportMappingPreset)
                .where(ImportMappingPreset.project_id == project_id)
                .where(ImportMappingPreset.active.is_(True))
                .order_by(desc(ImportMappingPreset.last_used_at), desc(ImportMappingPreset.created_at))
            )
            return list(result.scalars().all())

    async def get_mapping_preset(self, project_id: str, preset_id: str) -> ImportMappingPreset:
        async with self._db.session() as session:
            record = await session.scalar(
                select(ImportMappingPreset)
                .where(ImportMappingPreset.project_id == project_id)
                .where(ImportMappingPreset.preset_id == preset_id)
                .where(ImportMappingPreset.active.is_(True))
            )
            if record is None:
                raise ProjectNotFoundError("Сохранённое сопоставление не найдено")
            return record

    async def save_mapping_preset(
        self,
        project_id: str,
        *,
        name: str,
        marketplace: str,
        schema_version: str,
        source_columns: list[str],
        mapping: dict[str, str],
        header_fingerprint: str,
    ) -> ImportMappingPreset:
        now = datetime.now(UTC)
        async with self._db.session() as session:
            await self._require_project(session, project_id)
            record = ImportMappingPreset(
                preset_id=f"preset_{uuid.uuid4().hex[:12]}",
                project_id=project_id,
                name=_required_text(name, "Название сопоставления обязательно"),
                marketplace=_optional_text(marketplace) or "unknown",
                schema_version=schema_version,
                source_columns_json=json.dumps(list(source_columns), ensure_ascii=False),
                mapping_json=json.dumps(dict(mapping), ensure_ascii=False, sort_keys=True),
                header_fingerprint=header_fingerprint,
                active=True,
                created_at=now,
                last_used_at=now,
            )
            session.add(record)
            await session.commit()
            return record

    async def touch_mapping_preset(self, project_id: str, preset_id: str) -> None:
        async with self._db.session() as session:
            record = await session.scalar(
                select(ImportMappingPreset)
                .where(ImportMappingPreset.project_id == project_id)
                .where(ImportMappingPreset.preset_id == preset_id)
                .where(ImportMappingPreset.active.is_(True))
            )
            if record is None:
                raise ProjectNotFoundError("Сохранённое сопоставление не найдено")
            record.last_used_at = datetime.now(UTC)
            await session.commit()

    async def delete_mapping_preset(self, project_id: str, preset_id: str) -> None:
        async with self._db.session() as session:
            record = await session.scalar(
                select(ImportMappingPreset)
                .where(ImportMappingPreset.project_id == project_id)
                .where(ImportMappingPreset.preset_id == preset_id)
            )
            if record is None:
                raise ProjectNotFoundError("Сохранённое сопоставление не найдено")
            record.active = False
            await session.commit()

    async def list_files(self, project_id: str) -> list[ClientProjectFile]:
        async with self._db.session() as session:
            await self._require_project(session, project_id)
            result = await session.execute(
                select(ClientProjectFile)
                .where(ClientProjectFile.project_id == project_id)
                .order_by(desc(ClientProjectFile.created_at))
            )
            return list(result.scalars().all())

    async def link_imported_product(
        self,
        project_id: str,
        product,
        unified: UnifiedProduct,
        *,
        source_file_id: str | None = None,
        source_row_index: int | None = None,
    ) -> tuple[ProjectProduct, bool]:
        now = datetime.now(UTC)
        snapshot = _snapshot_from_unified(unified, product.id)
        snapshot_json = ProductCardEditorService._json(snapshot)
        snapshot_hash = ProductCardEditorService.checksum(snapshot)
        async with self._db.session() as session:
            await self._require_project(session, project_id)
            existing = await session.scalar(
                select(ProjectProduct)
                .where(ProjectProduct.project_id == project_id)
                .where(ProjectProduct.product_id == product.id)
            )
            if existing is not None:
                changed = existing.latest_source_snapshot_hash != snapshot_hash
                existing.latest_source_snapshot_json = snapshot_json
                existing.latest_source_snapshot_hash = snapshot_hash
                existing.source_file_id = source_file_id or existing.source_file_id
                existing.source_row_index = source_row_index
                existing.source_updated_at = now if changed else existing.source_updated_at
                existing.updated_at = now
                await session.commit()
                return existing, changed
            record = ProjectProduct(
                project_product_id=f"pp_{uuid.uuid4().hex[:12]}",
                project_id=project_id,
                product_id=product.id,
                source_file_id=source_file_id,
                source_row_index=source_row_index,
                source_snapshot_json=snapshot_json,
                source_snapshot_hash=snapshot_hash,
                latest_source_snapshot_json=snapshot_json,
                latest_source_snapshot_hash=snapshot_hash,
                status="active",
                created_at=now,
                updated_at=now,
                source_updated_at=now,
                effective_updated_at=now,
            )
            session.add(record)
            await session.commit()
            return record, True

    async def list_project_products(self, project_id: str, *, limit: int = 100, offset: int = 0) -> list[ProjectProduct]:
        async with self._db.session() as session:
            await self._require_project(session, project_id)
            result = await session.execute(
                select(ProjectProduct)
                .where(ProjectProduct.project_id == project_id)
                .order_by(desc(ProjectProduct.updated_at))
                .limit(max(1, min(limit, 500)))
                .offset(max(offset, 0))
            )
            return list(result.scalars().all())

    async def get_project_product(self, project_id: str, product_id: int) -> ProjectProduct:
        async with self._db.session() as session:
            record = await session.scalar(
                select(ProjectProduct)
                .where(ProjectProduct.project_id == project_id)
                .where(ProjectProduct.product_id == product_id)
            )
            if record is None:
                raise ProjectNotFoundError("Товар не найден в проекте")
            return record

    @staticmethod
    async def _require_project(session, project_id: str) -> ClientProject:
        project = await session.get(ClientProject, project_id)
        if project is None:
            raise ProjectNotFoundError("Проект не найден")
        return project


def _required_text(value: Any, message: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ProjectError(message)
    return text


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_status(value: Any) -> str:
    status = str(value or "").strip()
    allowed = {"new", "in_progress", "ready_for_review", "completed", "archived"}
    if status not in allowed:
        raise ProjectError("Некорректный статус проекта")
    return status


def _snapshot_from_unified(product: UnifiedProduct, product_id: int) -> dict[str, Any]:
    attributes = dict(product.attributes or {})
    for key, value in product.raw.items():
        if key == "__field_sources":
            continue
        attributes.setdefault(f"source:{key}", "" if value is None else str(value))
    return {
        "title": product.name or "",
        "description": product.description,
        "brand": product.brand,
        "category": product.category,
        "sku": product.sku,
        "price": product.price,
        "old_price": product.old_price,
        "discount_pct": product.discount_pct,
        "availability": product.availability or "unknown",
        "image_urls": list(product.image_urls or []),
        "weight_g": product.weight_g,
        "width_mm": product.width_mm,
        "height_mm": product.height_mm,
        "depth_mm": product.depth_mm,
        "attributes": attributes,
        "marketplace": product.marketplace or "unknown",
        "external_product_id": product.sku or product.source_id or str(product_id),
        "source_url": product.source_url,
        "_provenance": {"field_sources": product.raw.get("__field_sources", {})},
    }
