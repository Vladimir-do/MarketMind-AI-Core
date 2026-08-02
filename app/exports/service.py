"""Project-scoped export generation."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import openpyxl
from sqlalchemy import select

from app.config import EXPORT_SCHEMA_VERSION
from app.database import ClientProject, ClientProjectFile, Database, ProjectExport
from app.effective_card.service import EffectiveProductCard, EffectiveProductCardService, _unified_from_snapshot
from app.exports.safety import sanitize_export_row, sanitize_spreadsheet_cell
from app.seo_intelligence import audit_unified_product_seo
from app.workspace.files import project_artifact_path

_BASE_HEADERS = [
    "project_id",
    "product_id",
    "marketplace",
    "external_product_id",
    "title",
    "description",
    "brand",
    "price",
    "availability",
    "image_urls",
    "attributes",
    "source_quality_score",
    "effective_quality_score",
    "latest_version_id",
    "warnings",
]

_EXPORT_HEADERS = _BASE_HEADERS + [
    "seo_score",
    "seo_level",
    "seo_ready",
    "seo_recommendations",
    "seo_critical_issues",
    "seo_warning_issues",
]

_CSV_SEO_HEADERS = [
    "seo_score",
    "seo_tier",
    "seo_ready",
    "seo_recommendations",
]

_TIER_LABELS: dict[str, str] = {
    "strong": "Сильная",
    "usable": "ОК",
    "needs_work": "Доработка",
    "weak": "Слабая",
}


class ProjectExportService:
    """Creates local export files from EffectiveProductCard only."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._effective = EffectiveProductCardService(db)

    async def preview(self, project_id: str, *, marketplace_profile: str = "universal") -> dict[str, Any]:
        rows = await self._rows(project_id, marketplace_profile=marketplace_profile)
        return {
            "project_id": project_id,
            "marketplace_profile": marketplace_profile,
            "total_products": len(rows),
            "items": rows[:20],
            "warnings": [],
        }

    async def create_export(
        self,
        project_id: str,
        *,
        file_format: str = "csv",
        marketplace_profile: str = "universal",
    ) -> ProjectExport:
        rows = await self._rows(project_id, marketplace_profile=marketplace_profile)
        safe_format = file_format.lower()
        now = datetime.now(UTC)
        export_id = f"export_{uuid.uuid4().hex[:12]}"
        filename = f"project_{project_id}_{marketplace_profile}_{now.strftime('%Y%m%d_%H%M%S')}_{export_id[-6:]}.{safe_format}"
        target, relative_path = project_artifact_path(project_id, "exports", filename)
        if safe_format == "csv":
            target.write_bytes(_csv_bytes(rows))
        elif safe_format == "json":
            target.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        elif safe_format == "xlsx":
            target.write_bytes(_xlsx_bytes(rows))
        else:
            raise ValueError("Формат экспорта не поддерживается")
        checksum = hashlib.sha256(target.read_bytes()).hexdigest()
        async with self._db.session() as session:
            project = await session.get(ClientProject, project_id)
            if project is None:
                raise ValueError("Проект не найден")
            source_file_result = await session.execute(
                select(ClientProjectFile)
                .where(ClientProjectFile.project_id == project_id)
                .order_by(ClientProjectFile.created_at)
            )
            manifest = {
                "project_id": project_id,
                "export_id": export_id,
                "format": safe_format,
                "schema_version": EXPORT_SCHEMA_VERSION,
                "generated_at": now.isoformat(),
                "source_file_hashes": [record.sha256 for record in source_file_result.scalars().all()],
                "product_count": len(rows),
                "warning_count": 0,
                "error_count": 0,
                "effective_versions": [
                    row.get("latest_version_id")
                    for row in rows
                    if row.get("latest_version_id")
                ],
                "checksum": checksum,
            }
            record = ProjectExport(
                export_id=export_id,
                project_id=project_id,
                export_type="product_cards",
                marketplace_profile=marketplace_profile,
                file_format=safe_format,
                schema_version=EXPORT_SCHEMA_VERSION,
                relative_path=relative_path,
                product_count=len(rows),
                checksum=checksum,
                manifest_json=json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                status="created",
                warnings_json="[]",
                created_at=now,
            )
            session.add(record)
            await session.commit()
            return record

    async def list_exports(self, project_id: str) -> list[ProjectExport]:
        async with self._db.session() as session:
            result = await session.execute(
                select(ProjectExport)
                .where(ProjectExport.project_id == project_id)
                .order_by(ProjectExport.created_at.desc())
            )
            return list(result.scalars().all())

    async def _rows(self, project_id: str, *, marketplace_profile: str) -> list[dict[str, Any]]:
        cards = await self._effective.list_effective_cards(project_id, limit=500)
        result = []
        for card in cards:
            quality = await self._effective.quality(project_id, card.product_id)
            seo = audit_unified_product_seo(_unified_from_snapshot(card.effective_snapshot, card.product_id))
            result.append(_export_row(card, quality, marketplace_profile, seo))
        return result


def _export_row(card: EffectiveProductCard, quality: dict[str, Any], marketplace_profile: str, seo: Any) -> dict[str, Any]:
    snapshot = card.effective_snapshot
    critical = sum(1 for f in seo.findings if f.severity == "critical")
    warning = sum(1 for f in seo.findings if f.severity == "warning")
    rec_text = "\n".join(r.action for r in seo.recommendations[:5])
    row = {
        "project_id": card.project_id,
        "product_id": card.product_id,
        "marketplace": marketplace_profile if marketplace_profile != "universal" else snapshot.get("marketplace"),
        "external_product_id": snapshot.get("external_product_id"),
        "title": snapshot.get("title"),
        "description": snapshot.get("description"),
        "brand": snapshot.get("brand"),
        "price": snapshot.get("price"),
        "availability": snapshot.get("availability"),
        "image_urls": ", ".join(snapshot.get("image_urls") or []),
        "attributes": json.dumps(snapshot.get("attributes") or {}, ensure_ascii=False, sort_keys=True),
        "source_quality_score": quality["source"]["score"],
        "effective_quality_score": quality["effective"]["score"],
        "latest_version_id": card.latest_version_id,
        "warnings": "; ".join(card.warnings),
        # SEO-колонки для XLSX (человекочитаемые)
        "seo_score": seo.score,
        "seo_level": _TIER_LABELS.get(seo.tier, seo.tier),
        "seo_ready": "да" if seo.ready else "нет",
        "seo_recommendations": rec_text,
        "seo_critical_issues": critical,
        "seo_warning_issues": warning,
        # SEO-колонки для CSV (snake_case)
        "seo_tier": seo.tier,
    }
    return sanitize_export_row(row)


_CSV_HEADERS = _BASE_HEADERS + _CSV_SEO_HEADERS


def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_CSV_HEADERS)
    writer.writeheader()
    for row in rows:
        writer.writerow({header: row.get(header, "") for header in _CSV_HEADERS})
    return buffer.getvalue().encode("utf-8-sig")


def _xlsx_bytes(rows: list[dict[str, Any]]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Карточки"
    sheet.append(_EXPORT_HEADERS)
    for row in rows:
        sheet.append([sanitize_spreadsheet_cell(row.get(header, "")) for header in _EXPORT_HEADERS])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
