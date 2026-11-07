"""Database-backed approval queue for AI-generated suggestions."""

from __future__ import annotations

import contextlib
import json
import logging
import uuid
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import select

from app.ai_recommendation.approval import PendingApproval
from app.ai_recommendation.suggestions import AISuggestion
from app.database import ApprovalRecord, Database

logger = logging.getLogger(__name__)


class DatabaseApprovalQueue:
    """Manages pending approvals with DB persistence.

    Wraps the same interface as ApprovalQueue but persists to approval_records.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(self, result) -> list[PendingApproval]:
        """Add all suggestions from an AIRecommendationResult to the DB queue."""
        added: list[PendingApproval] = []
        async with self._db.session() as s:
            for suggestion in result.suggestions:
                approval_id = uuid.uuid4().hex[:12]
                metadata_json = json.dumps(suggestion.metadata, ensure_ascii=False) if suggestion.metadata else None
                record = ApprovalRecord(
                    approval_id=approval_id,
                    product_id=result.product_id,
                    field=suggestion.field,
                    suggestion_type=suggestion.suggestion_type,
                    before_value=suggestion.before,
                    after_value=suggestion.after,
                    reason=suggestion.reason,
                    confidence=suggestion.confidence,
                    source_finding=suggestion.source_finding or None,
                    metadata_json=metadata_json,
                    status="pending",
                    created_at=datetime.now(UTC),
                )
                s.add(record)
                added.append(
                    PendingApproval(
                        suggestion=suggestion,
                        product_id=result.product_id,
                        approval_id=approval_id,
                    )
                )
            await s.commit()
        return added

    async def approve(self, approval_id: str) -> PendingApproval | None:
        """Mark a suggestion as approved."""
        now = datetime.now(UTC)
        async with self._db.session() as s:
            result = await s.execute(select(ApprovalRecord).where(ApprovalRecord.approval_id == approval_id))
            record = result.scalar_one_or_none()
            if record is None:
                return None
            record.status = "approved"
            record.reviewed_at = now
            await s.commit()
            return self._record_to_approval(record)

    async def reject(self, approval_id: str, reason: str = "") -> PendingApproval | None:
        """Mark a suggestion as rejected."""
        now = datetime.now(UTC)
        async with self._db.session() as s:
            result = await s.execute(select(ApprovalRecord).where(ApprovalRecord.approval_id == approval_id))
            record = result.scalar_one_or_none()
            if record is None:
                return None
            record.status = "rejected"
            record.reject_reason = reason or None
            record.reviewed_at = now
            await s.commit()
            full_reason = f"{record.reason} [отклонено: {reason}]" if reason else record.reason
            item = self._record_to_approval(record)
            return PendingApproval(
                suggestion=AISuggestion(
                    field=item.suggestion.field,
                    suggestion_type=item.suggestion.suggestion_type,
                    before=item.suggestion.before,
                    after=item.suggestion.after,
                    reason=full_reason,
                    confidence=item.suggestion.confidence,
                    source_finding=item.suggestion.source_finding,
                    metadata=item.suggestion.metadata,
                ),
                product_id=item.product_id,
                approval_id=item.approval_id,
                approved=item.approved,
            )

    async def reset_pending(self, approval_id: str) -> bool:
        """Return a reviewed suggestion to pending state after failed apply."""
        async with self._db.session() as s:
            result = await s.execute(select(ApprovalRecord).where(ApprovalRecord.approval_id == approval_id))
            record = result.scalar_one_or_none()
            if record is None:
                return False
            record.status = "pending"
            record.reviewed_at = None
            record.snapshot_before = None
            record.snapshot_after = None
            record.applied_at = None
            await s.commit()
            return True

    async def mark_applied(
        self,
        approval_id: str,
        *,
        field: str,
        before_value,
        after_value,
    ) -> bool:
        """Save apply snapshots for an already approved suggestion."""
        now = datetime.now(UTC)
        async with self._db.session() as s:
            result = await s.execute(select(ApprovalRecord).where(ApprovalRecord.approval_id == approval_id))
            record = result.scalar_one_or_none()
            if record is None:
                return False
            record.snapshot_before = json.dumps(
                {
                    "field": field,
                    "value": before_value,
                    "timestamp": now.isoformat(),
                },
                ensure_ascii=False,
            )
            record.snapshot_after = json.dumps(
                {
                    "field": field,
                    "value": after_value,
                    "timestamp": now.isoformat(),
                },
                ensure_ascii=False,
            )
            record.applied_at = now
            await s.commit()
            return True

    async def get_pending(self) -> list[PendingApproval]:
        """Return all unreviewed suggestions."""
        return await self._get_by_status("pending")

    async def get_all(self) -> list[PendingApproval]:
        """Return all suggestions."""
        async with self._db.session() as s:
            result = await s.execute(select(ApprovalRecord).order_by(ApprovalRecord.created_at))
            return [self._record_to_approval(r) for r in result.scalars().all()]

    async def get_status_counts(self) -> dict[str, int]:
        """Breakdown of all ApprovalRecord rows by status, plus a total."""
        async with self._db.session() as s:
            result = await s.execute(select(ApprovalRecord.status))
            statuses = [row[0] for row in result.all()]
        counter = Counter(statuses)
        return {
            "total": len(statuses),
            "pending": counter.get("pending", 0),
            "approved": counter.get("approved", 0),
            "rejected": counter.get("rejected", 0),
            "rolled_back": counter.get("rolled_back", 0),
        }

    async def _get_by_status(self, status: str) -> list[PendingApproval]:
        async with self._db.session() as s:
            result = await s.execute(
                select(ApprovalRecord).where(ApprovalRecord.status == status).order_by(ApprovalRecord.created_at)
            )
            return [self._record_to_approval(r) for r in result.scalars().all()]

    async def apply_approved(self, product) -> list[str]:
        """Apply all approved suggestions to a product and save snapshots.

        Returns list of applied field names.
        """
        applied_fields: list[str] = []
        async with self._db.session() as s:
            result = await s.execute(
                select(ApprovalRecord)
                .where(ApprovalRecord.status == "approved")
                .where(ApprovalRecord.applied_at.is_(None))
                .where(ApprovalRecord.product_id == str(product.id))
            )
            records = result.scalars().all()
            for record in records:
                field_name = record.field
                if hasattr(product, field_name):
                    # Snapshot before
                    current_value = getattr(product, field_name)
                    snapshot_before = json.dumps(
                        {
                            "field": field_name,
                            "value": str(current_value) if current_value is not None else None,
                            "timestamp": datetime.now(UTC).isoformat(),
                        },
                        ensure_ascii=False,
                    )
                    # Apply
                    setattr(product, field_name, record.after_value)
                    # Snapshot after
                    snapshot_after = json.dumps(
                        {
                            "field": field_name,
                            "value": record.after_value,
                            "timestamp": datetime.now(UTC).isoformat(),
                        },
                        ensure_ascii=False,
                    )
                    record.snapshot_before = snapshot_before
                    record.snapshot_after = snapshot_after
                    record.applied_at = datetime.now(UTC)
                    applied_fields.append(field_name)
            await s.commit()
        return applied_fields

    async def rollback(self, approval_id: str, product=None) -> bool:
        """Restore the original value from snapshot_before.

        If product is provided, restores the field value on the product object.
        Returns True if rollback succeeded.
        """
        async with self._db.session() as s:
            result = await s.execute(select(ApprovalRecord).where(ApprovalRecord.approval_id == approval_id))
            record = result.scalar_one_or_none()
            if record is None or record.snapshot_before is None:
                return False
            try:
                snapshot = json.loads(record.snapshot_before)
                original_value = snapshot.get("value")
            except (json.JSONDecodeError, KeyError):
                logger.warning("Invalid snapshot_before for %s", approval_id)
                return False
            record.rolled_back_at = datetime.now(UTC)
            record.status = "rolled_back"
            if product is not None and hasattr(product, record.field):
                setattr(product, record.field, original_value)
            await s.commit()
            return True

    async def get_rollback_info(self, approval_id: str) -> dict | None:
        """Get rollback information for a specific approval."""
        async with self._db.session() as s:
            result = await s.execute(select(ApprovalRecord).where(ApprovalRecord.approval_id == approval_id))
            record = result.scalar_one_or_none()
            if record is None:
                return None
            snapshot_before = None
            if record.snapshot_before:
                with contextlib.suppress(json.JSONDecodeError, KeyError):
                    snapshot_before = json.loads(record.snapshot_before)
            return {
                "approval_id": record.approval_id,
                "product_id": record.product_id,
                "field": record.field,
                "status": record.status,
                "snapshot_before": snapshot_before,
                "rolled_back_at": record.rolled_back_at.isoformat() if record.rolled_back_at else None,
            }

    async def get_history(self, product_id: str | None = None, limit: int = 50) -> list[dict]:
        """Get approval history, optionally filtered by product_id."""
        async with self._db.session() as s:
            stmt = select(ApprovalRecord).order_by(ApprovalRecord.created_at.desc()).limit(limit)
            if product_id:
                stmt = stmt.where(ApprovalRecord.product_id == product_id)
            result = await s.execute(stmt)
            records = result.scalars().all()
            return [self._record_to_dict(r) for r in records]

    async def get_record(self, approval_id: str) -> ApprovalRecord | None:
        """Get a raw ApprovalRecord by approval_id."""
        async with self._db.session() as s:
            result = await s.execute(select(ApprovalRecord).where(ApprovalRecord.approval_id == approval_id))
            return result.scalar_one_or_none()

    @staticmethod
    def _record_to_approval(record: ApprovalRecord) -> PendingApproval:
        status_map = {"pending": None, "approved": True, "rejected": False}
        metadata = {}
        if record.metadata_json:
            with contextlib.suppress(json.JSONDecodeError, KeyError):
                metadata = json.loads(record.metadata_json)
        return PendingApproval(
            suggestion=AISuggestion(
                field=record.field,
                suggestion_type=record.suggestion_type,
                before=record.before_value or "",
                after=record.after_value,
                reason=record.reason,
                confidence=record.confidence,
                source_finding=record.source_finding or "",
                metadata=metadata,
            ),
            product_id=record.product_id,
            approval_id=record.approval_id,
            approved=status_map.get(record.status),
        )

    @staticmethod
    def _record_to_dict(record: ApprovalRecord) -> dict:
        return {
            "approval_id": record.approval_id,
            "product_id": record.product_id,
            "field": record.field,
            "suggestion_type": record.suggestion_type,
            "before_value": record.before_value,
            "after_value": record.after_value,
            "reason": record.reason,
            "confidence": record.confidence,
            "status": record.status,
            "reject_reason": record.reject_reason,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "reviewed_at": record.reviewed_at.isoformat() if record.reviewed_at else None,
            "applied_at": record.applied_at.isoformat() if record.applied_at else None,
            "rolled_back_at": record.rolled_back_at.isoformat() if record.rolled_back_at else None,
        }
