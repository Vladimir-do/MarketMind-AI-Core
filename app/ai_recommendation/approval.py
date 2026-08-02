"""Approval queue for AI-generated suggestions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.ai_recommendation.suggestions import AISuggestion


@dataclass
class PendingApproval:
    """A suggestion awaiting human approval."""

    suggestion: AISuggestion
    product_id: str
    approval_id: str = ""
    approved: bool | None = None

    def __post_init__(self) -> None:
        if not self.approval_id:
            self.approval_id = uuid.uuid4().hex[:12]


class ApprovalQueue:
    """Manages pending approvals for AI suggestions."""

    def __init__(self) -> None:
        self._queue: dict[str, PendingApproval] = {}

    def add(self, result) -> list[PendingApproval]:
        """Add all suggestions from an AIRecommendationResult to the queue."""
        added: list[PendingApproval] = []
        for suggestion in result.suggestions:
            approval = PendingApproval(
                suggestion=suggestion,
                product_id=result.product_id,
            )
            self._queue[approval.approval_id] = approval
            added.append(approval)
        return added

    def approve(self, approval_id: str) -> PendingApproval | None:
        """Mark a suggestion as approved."""
        item = self._queue.get(approval_id)
        if item is None:
            return None
        item.approved = True
        return item

    def reject(self, approval_id: str, reason: str = "") -> PendingApproval | None:
        """Mark a suggestion as rejected."""
        item = self._queue.get(approval_id)
        if item is None:
            return None
        item.approved = False
        if reason:
            item.suggestion = AISuggestion(
                field=item.suggestion.field,
                suggestion_type=item.suggestion.suggestion_type,
                before=item.suggestion.before,
                after=item.suggestion.after,
                reason=f"{item.suggestion.reason} [отклонено: {reason}]",
                confidence=item.suggestion.confidence,
                source_finding=item.suggestion.source_finding,
                metadata=item.suggestion.metadata,
            )
        return item

    def get_pending(self) -> list[PendingApproval]:
        """Return all unreviewed suggestions."""
        return [item for item in self._queue.values() if item.approved is None]

    def get_all(self) -> list[PendingApproval]:
        return list(self._queue.values())

    @staticmethod
    def apply_approved(product, approvals: list[PendingApproval]):
        """Apply approved suggestions to a product object by setting field values."""
        for approval in approvals:
            if not approval.approved:
                continue
            suggestion = approval.suggestion
            if hasattr(product, suggestion.field):
                setattr(product, suggestion.field, suggestion.after)
        return product
