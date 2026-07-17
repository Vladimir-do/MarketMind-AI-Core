"""Transactional product card editor service."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select

from app.database import Database, PriceHistory, Product, ProductCardDraft, ProductCardVersion, ProjectProduct
from app.domain.events.models import AggregateType, DomainEvent, EventActor, EventSource
from app.domain.events.repository import DomainEventRepository
from app.editor.repository import ProductEditorRepository
from app.editor.schemas import CardDiffItem, ValidationResult, normalize_card_payload
from app.editor.validation import validate_card_payload


class EditorError(Exception):
    """Base editor error."""


class EditorNotFoundError(EditorError):
    """Requested product/draft/version does not exist."""


class EditorConflictError(EditorError):
    """Optimistic locking conflict."""

    def __init__(self, message: str, *, conflict: dict[str, Any]) -> None:
        super().__init__(message)
        self.conflict = conflict


class EditorValidationError(EditorError):
    """Draft payload is invalid."""

    def __init__(self, validation: ValidationResult) -> None:
        super().__init__("Черновик содержит ошибки")
        self.validation = validation


@dataclass(frozen=True)
class ApplyResult:
    version: ProductCardVersion
    event: DomainEvent
    diff: list[CardDiffItem]


class ProductCardEditorService:
    """Coordinates drafts, complete versions and persisted editor events."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create_draft(
        self,
        product_id: int,
        *,
        payload: dict[str, Any] | None = None,
        base_version_id: str | None = None,
        actor_id: str | None = "local_user",
        comment: str | None = None,
        project_id: str | None = None,
        project_product_id: str | None = None,
    ) -> ProductCardDraft:
        now = datetime.now(UTC)
        async with self._db.session() as session:
            product = await session.get(Product, product_id)
            if product is None:
                raise EditorNotFoundError("Товар не найден")
            if project_id or project_product_id:
                await self._require_project_product(session, product_id, project_id, project_product_id)
            repo = ProductEditorRepository(session)
            base_version_id = base_version_id or await self._current_version_id(
                repo,
                product,
                project_id=project_id,
                project_product_id=project_product_id,
            )
            current = await self._effective_snapshot(
                session,
                product,
                project_id=project_id,
                project_product_id=project_product_id,
            )
            draft_payload = normalize_card_payload({**current, **(payload or {})})
            draft = ProductCardDraft(
                draft_id=f"draft_{uuid.uuid4().hex}",
                product_id=product_id,
                project_id=project_id,
                project_product_id=project_product_id,
                base_version_id=base_version_id,
                status="draft",
                payload_json=self._json(draft_payload),
                validation_json=None,
                created_by=actor_id,
                created_at=now,
                updated_at=now,
                revision=1,
                comment=comment,
            )
            session.add(draft)
            await session.commit()
            return draft

    async def list_drafts(
        self,
        product_id: int,
        *,
        status: str | None = None,
        project_id: str | None = None,
        project_product_id: str | None = None,
    ) -> list[ProductCardDraft]:
        async with self._db.session() as session:
            if await session.get(Product, product_id) is None:
                raise EditorNotFoundError("Товар не найден")
            return await ProductEditorRepository(session).list_drafts(
                product_id,
                status=status,
                project_id=project_id,
                project_product_id=project_product_id,
            )

    async def update_draft(
        self,
        product_id: int,
        draft_id: str,
        *,
        payload: dict[str, Any],
        revision: int,
        comment: str | None = None,
        project_id: str | None = None,
        project_product_id: str | None = None,
    ) -> ProductCardDraft:
        now = datetime.now(UTC)
        async with self._db.session() as session:
            draft = await self._get_owned_draft(session, product_id, draft_id, project_id, project_product_id)
            if draft.revision != revision:
                raise EditorConflictError(
                    "Черновик был изменён после открытия",
                    conflict={"current_revision": draft.revision, "requested_revision": revision},
                )
            merged = normalize_card_payload({**self._load_json(draft.payload_json), **payload})
            draft.payload_json = self._json(merged)
            draft.validation_json = None
            draft.comment = comment if comment is not None else draft.comment
            draft.updated_at = now
            draft.revision += 1
            await session.commit()
            return draft

    async def discard_draft(self, product_id: int, draft_id: str) -> ProductCardDraft:
        async with self._db.session() as session:
            draft = await self._get_owned_draft(session, product_id, draft_id, None, None)
            draft.status = "discarded"
            draft.updated_at = datetime.now(UTC)
            draft.revision += 1
            await session.commit()
            return draft

    async def validate_draft(
        self,
        product_id: int,
        draft_id: str,
        *,
        project_id: str | None = None,
        project_product_id: str | None = None,
    ) -> ValidationResult:
        async with self._db.session() as session:
            draft = await self._get_owned_draft(session, product_id, draft_id, project_id, project_product_id)
            validation = validate_card_payload(self._load_json(draft.payload_json))
            draft.validation_json = self._json(validation.to_dict())
            draft.status = "ready_for_review" if validation.is_valid else "draft"
            draft.updated_at = datetime.now(UTC)
            await session.commit()
            return validation

    async def apply_draft(
        self,
        product_id: int,
        draft_id: str,
        *,
        revision: int,
        actor_id: str | None = "local_user",
        comment: str | None = None,
        project_id: str | None = None,
        project_product_id: str | None = None,
    ) -> ApplyResult:
        now = datetime.now(UTC)
        async with self._db.session() as session:
            product = await session.get(Product, product_id)
            if product is None:
                raise EditorNotFoundError("Товар не найден")
            project_product = None
            if project_id or project_product_id:
                project_product = await self._require_project_product(session, product_id, project_id, project_product_id)
            draft = await self._get_owned_draft(session, product_id, draft_id, project_id, project_product_id)
            if draft.revision != revision:
                raise EditorConflictError(
                    "Черновик был изменён после открытия",
                    conflict={"current_revision": draft.revision, "requested_revision": revision},
                )
            repo = ProductEditorRepository(session)
            current_version_id = await self._current_version_id(
                repo,
                product,
                project_id=project_id,
                project_product_id=project_product_id,
            )
            if draft.base_version_id != current_version_id:
                current_snapshot = await self._effective_snapshot(
                    session,
                    product,
                    project_id=project_id,
                    project_product_id=project_product_id,
                )
                draft_snapshot = self._load_json(draft.payload_json)
                draft.status = "conflicted"
                draft.updated_at = now
                await session.commit()
                raise EditorConflictError(
                    "Карточка была изменена после создания черновика",
                    conflict={
                        "base_version_id": draft.base_version_id,
                        "current_version_id": current_version_id,
                        "diff": [item.to_dict() for item in self._diff(current_snapshot, draft_snapshot)],
                    },
                )

            draft_payload = normalize_card_payload(self._load_json(draft.payload_json))
            validation = validate_card_payload(draft_payload)
            if not validation.is_valid:
                draft.validation_json = self._json(validation.to_dict())
                await session.commit()
                raise EditorValidationError(validation)

            before = await self._effective_snapshot(
                session,
                product,
                project_id=project_id,
                project_product_id=project_product_id,
            )
            snapshot = normalize_card_payload({**before, **draft_payload})
            diff = self._diff(before, snapshot)
            if not diff:
                raise EditorValidationError(
                    ValidationResult(False, [])
                )

            checksum = self.checksum(snapshot)
            duplicate = await self._latest_same_checksum(
                repo,
                product_id,
                checksum,
                project_id=project_id,
                project_product_id=project_product_id,
            )
            if duplicate is not None:
                draft.status = "applied"
                draft.updated_at = now
                await session.commit()
                return ApplyResult(version=duplicate, event=self._noop_event(product_id, now), diff=[])

            event_id = f"product:{product_id}:manual:{uuid.uuid4().hex}"
            version_number = await repo.next_version_number(product_id)
            version = ProductCardVersion(
                version_id=f"version:{product_id}:{version_number:04d}",
                product_id=product_id,
                project_id=project_id,
                project_product_id=project_product_id,
                version_number=version_number,
                snapshot_json=self._json(snapshot),
                snapshot_schema_version=1,
                source="manual",
                actor_type="user",
                actor_id=actor_id,
                comment=comment or draft.comment,
                created_at=now,
                base_version_id=draft.base_version_id,
                trigger_event_id=event_id,
                checksum=checksum,
            )
            session.add(version)
            event = self._manual_event(
                product_id,
                event_id,
                actor_id,
                now,
                diff,
                version.version_id,
                comment,
                project_id=project_id,
                project_product_id=project_product_id,
            )
            await DomainEventRepository(session).append(event, correlation_id=draft.draft_id, causation_id=draft.draft_id)
            if project_product is None:
                self._apply_snapshot_to_product(session, product, snapshot, before, now)
            else:
                project_product.effective_updated_at = now
                project_product.updated_at = now
            draft.status = "applied"
            draft.updated_at = now
            draft.revision += 1
            await session.commit()
            return ApplyResult(version=version, event=event, diff=diff)

    async def rollback_version(
        self,
        product_id: int,
        version_number: int,
        *,
        current_version_id: str | None = None,
        actor_id: str | None = "local_user",
        reason: str | None = None,
        project_id: str | None = None,
        project_product_id: str | None = None,
    ) -> ApplyResult:
        now = datetime.now(UTC)
        async with self._db.session() as session:
            product = await session.get(Product, product_id)
            if product is None:
                raise EditorNotFoundError("Товар не найден")
            project_product = None
            if project_id or project_product_id:
                project_product = await self._require_project_product(session, product_id, project_id, project_product_id)
            repo = ProductEditorRepository(session)
            target = await repo.get_version(
                product_id,
                version_number,
                project_id=project_id,
                project_product_id=project_product_id,
            )
            if target is None:
                raise EditorNotFoundError("Версия не найдена")
            actual_current = await self._current_version_id(
                repo,
                product,
                project_id=project_id,
                project_product_id=project_product_id,
            )
            if current_version_id and current_version_id != actual_current:
                raise EditorConflictError(
                    "Карточка была изменена после открытия версии",
                    conflict={"current_version_id": actual_current, "requested_version_id": current_version_id},
                )
            before = await self._effective_snapshot(
                session,
                product,
                project_id=project_id,
                project_product_id=project_product_id,
            )
            snapshot = self._load_json(target.snapshot_json)
            diff = self._diff(before, snapshot)
            event_id = f"product:{product_id}:rollback:{uuid.uuid4().hex}"
            next_number = await repo.next_version_number(product_id)
            version = ProductCardVersion(
                version_id=f"version:{product_id}:{next_number:04d}",
                product_id=product_id,
                project_id=project_id,
                project_product_id=project_product_id,
                version_number=next_number,
                snapshot_json=self._json(snapshot),
                snapshot_schema_version=1,
                source="rollback",
                actor_type="user",
                actor_id=actor_id,
                comment=reason,
                created_at=now,
                base_version_id=actual_current,
                trigger_event_id=event_id,
                checksum=self.checksum(snapshot),
            )
            session.add(version)
            event = self._rollback_event(
                product_id,
                event_id,
                actor_id,
                now,
                diff,
                target.version_id,
                version.version_id,
                reason,
                project_id=project_id,
                project_product_id=project_product_id,
            )
            await DomainEventRepository(session).append(event, correlation_id=event_id, causation_id=target.trigger_event_id)
            if project_product is None:
                self._apply_snapshot_to_product(session, product, snapshot, before, now)
            else:
                project_product.effective_updated_at = now
                project_product.updated_at = now
            await session.commit()
            return ApplyResult(version=version, event=event, diff=diff)

    async def list_persisted_versions(
        self,
        product_id: int,
        *,
        project_id: str | None = None,
        project_product_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ProductCardVersion]:
        async with self._db.session() as session:
            return await ProductEditorRepository(session).list_versions(
                product_id,
                project_id=project_id,
                project_product_id=project_product_id,
                limit=limit,
                offset=offset,
            )

    async def list_audit_events(self, product_id: int, *, limit: int = 50, offset: int = 0) -> list[DomainEvent]:
        async with self._db.session() as session:
            return await DomainEventRepository(session).list_by_aggregate(
                AggregateType.PRODUCT.value,
                str(product_id),
                limit=limit,
                offset=offset,
            )

    async def _get_owned_draft(
        self,
        session,
        product_id: int,
        draft_id: str,
        project_id: str | None = None,
        project_product_id: str | None = None,
    ) -> ProductCardDraft:
        draft = await session.get(ProductCardDraft, draft_id)
        if draft is None or draft.product_id != product_id:
            raise EditorNotFoundError("Черновик не найден")
        if project_id is not None and draft.project_id != project_id:
            raise EditorNotFoundError("Черновик не найден")
        if project_product_id is not None and draft.project_product_id != project_product_id:
            raise EditorNotFoundError("Черновик не найден")
        return draft

    async def _current_version_id(
        self,
        repo: ProductEditorRepository,
        product: Product,
        *,
        project_id: str | None = None,
        project_product_id: str | None = None,
    ) -> str:
        latest = await repo.latest_version(product.id, project_id=project_id, project_product_id=project_product_id)
        if latest is not None:
            return latest.version_id
        marker = product.last_check.isoformat() if product.last_check else "unknown"
        return f"source:{product.id}:{marker}"

    async def _effective_snapshot(
        self,
        session,
        product: Product,
        *,
        project_id: str | None = None,
        project_product_id: str | None = None,
    ) -> dict[str, Any]:
        if project_id or project_product_id:
            project_product = await self._require_project_product(session, product.id, project_id, project_product_id)
            latest = await ProductEditorRepository(session).latest_version(
                product.id,
                project_id=project_product.project_id,
                project_product_id=project_product.project_product_id,
            )
            if latest is not None:
                return normalize_card_payload(self._load_json(latest.snapshot_json))
            return normalize_card_payload(self._load_json(project_product.latest_source_snapshot_json))
        latest_price = await session.scalar(
            select(PriceHistory)
            .where(PriceHistory.product_id == product.id)
            .order_by(desc(PriceHistory.recorded_at))
            .limit(1)
        )
        marketplace = self._marketplace_from_url(product.url)
        return normalize_card_payload(
            {
                "title": product.name or "",
                "description": None,
                "brand": None,
                "price": latest_price.price if latest_price else None,
                "availability": latest_price.availability_status if latest_price else "unknown",
                "image_urls": [product.image_url] if product.image_url else [],
                "attributes": {},
                "marketplace": marketplace,
                "external_product_id": str(product.id),
            }
        )

    def _apply_snapshot_to_product(
        self,
        session,
        product: Product,
        snapshot: dict[str, Any],
        before: dict[str, Any],
        now: datetime,
    ) -> None:
        product.name = snapshot.get("title") or product.name
        images = snapshot.get("image_urls") or []
        product.image_url = images[0] if images else product.image_url
        product.last_check = now
        if before.get("price") != snapshot.get("price") or before.get("availability") != snapshot.get("availability"):
            session.add(
                PriceHistory(
                    product_id=product.id,
                    price=snapshot.get("price"),
                    availability_status=snapshot.get("availability") or "unknown",
                    recorded_at=now,
                )
            )

    async def _latest_same_checksum(
        self,
        repo: ProductEditorRepository,
        product_id: int,
        checksum: str,
        *,
        project_id: str | None = None,
        project_product_id: str | None = None,
    ) -> ProductCardVersion | None:
        latest = await repo.latest_version(product_id, project_id=project_id, project_product_id=project_product_id)
        if latest is not None and latest.checksum == checksum:
            return latest
        return None

    @staticmethod
    def _diff(before: dict[str, Any], after: dict[str, Any]) -> list[CardDiffItem]:
        result = []
        for field in sorted(set(before) | set(after)):
            if before.get(field) != after.get(field):
                result.append(CardDiffItem(field, before.get(field), after.get(field)))
        return result

    @staticmethod
    def _manual_event(
        product_id: int,
        event_id: str,
        actor_id: str | None,
        occurred_at: datetime,
        diff: list[CardDiffItem],
        version_id: str,
        comment: str | None,
        *,
        project_id: str | None = None,
        project_product_id: str | None = None,
    ) -> DomainEvent:
        aggregate_id = project_product_id or str(product_id)
        return DomainEvent(
            event_id=event_id,
            aggregate_type=AggregateType.PRODUCT.value,
            aggregate_id=aggregate_id,
            event_type="product.manual_change_applied",
            source=EventSource.USER.value,
            actor=EventActor("local_user" if project_id else "user", actor_id=actor_id, display_name="Пользователь"),
            occurred_at=occurred_at,
            payload={
                "product_id": product_id,
                "project_id": project_id,
                "project_product_id": project_product_id,
                "changes": [item.to_dict() for item in diff],
                "version_id": version_id,
                "comment": comment,
            },
            metadata={"source_table": "domain_event_records"},
        )

    @staticmethod
    def _rollback_event(
        product_id: int,
        event_id: str,
        actor_id: str | None,
        occurred_at: datetime,
        diff: list[CardDiffItem],
        source_version_id: str,
        version_id: str,
        reason: str | None,
        *,
        project_id: str | None = None,
        project_product_id: str | None = None,
    ) -> DomainEvent:
        aggregate_id = project_product_id or str(product_id)
        return DomainEvent(
            event_id=event_id,
            aggregate_type=AggregateType.PRODUCT.value,
            aggregate_id=aggregate_id,
            event_type="product.version_rolled_back",
            source=EventSource.USER.value,
            actor=EventActor("local_user" if project_id else "user", actor_id=actor_id, display_name="Пользователь"),
            occurred_at=occurred_at,
            payload={
                "product_id": product_id,
                "project_id": project_id,
                "project_product_id": project_product_id,
                "changes": [item.to_dict() for item in diff],
                "source_version_id": source_version_id,
                "version_id": version_id,
                "reason": reason,
            },
            metadata={"source_table": "domain_event_records"},
        )

    @staticmethod
    def _noop_event(product_id: int, occurred_at: datetime) -> DomainEvent:
        return DomainEvent(
            event_id=f"product:{product_id}:noop:{uuid.uuid4().hex}",
            aggregate_type=AggregateType.PRODUCT.value,
            aggregate_id=str(product_id),
            event_type="product.snapshot_duplicate",
            source=EventSource.SYSTEM.value,
            occurred_at=occurred_at,
            payload={"product_id": product_id},
        )

    @staticmethod
    async def _require_project_product(
        session,
        product_id: int,
        project_id: str | None,
        project_product_id: str | None,
    ) -> ProjectProduct:
        stmt = select(ProjectProduct).where(ProjectProduct.product_id == product_id)
        if project_id is not None:
            stmt = stmt.where(ProjectProduct.project_id == project_id)
        if project_product_id is not None:
            stmt = stmt.where(ProjectProduct.project_product_id == project_product_id)
        record = await session.scalar(stmt)
        if record is None:
            raise EditorNotFoundError("Товар не найден в проекте")
        return record

    @staticmethod
    def checksum(snapshot: dict[str, Any]) -> str:
        raw = ProductCardEditorService._json(snapshot)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _json(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _load_json(raw: str | None) -> dict[str, Any]:
        return json.loads(raw or "{}")

    @staticmethod
    def _marketplace_from_url(url: str | None) -> str:
        low = (url or "").lower()
        if "ozon.ru" in low:
            return "ozon"
        if "wildberries.ru" in low or "wb.ru" in low:
            return "wildberries"
        if "market.yandex" in low or "yandex.ru/market" in low:
            return "yandex_market"
        return "unknown"
