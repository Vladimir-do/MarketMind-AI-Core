"""Repository helpers for product card editor tables."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import desc, func, select

from app.database import ProductCardDraft, ProductCardVersion

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ProductEditorRepository:
    """Thin repository around editor tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_draft(self, draft_id: str) -> ProductCardDraft | None:
        return await self._session.get(ProductCardDraft, draft_id)

    async def list_drafts(
        self,
        product_id: int,
        *,
        status: str | None = None,
        project_id: str | None = None,
        project_product_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ProductCardDraft]:
        stmt = select(ProductCardDraft).where(ProductCardDraft.product_id == product_id)
        if project_id is not None:
            stmt = stmt.where(ProductCardDraft.project_id == project_id)
        if project_product_id is not None:
            stmt = stmt.where(ProductCardDraft.project_product_id == project_product_id)
        if status:
            stmt = stmt.where(ProductCardDraft.status == status)
        stmt = stmt.order_by(desc(ProductCardDraft.updated_at)).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def latest_version(
        self,
        product_id: int,
        *,
        project_id: str | None = None,
        project_product_id: str | None = None,
    ) -> ProductCardVersion | None:
        stmt = select(ProductCardVersion).where(ProductCardVersion.product_id == product_id)
        if project_id is not None:
            stmt = stmt.where(ProductCardVersion.project_id == project_id)
        elif project_product_id is None:
            stmt = stmt.where(ProductCardVersion.project_id.is_(None))
        if project_product_id is not None:
            stmt = stmt.where(ProductCardVersion.project_product_id == project_product_id)
        result = await self._session.execute(stmt.order_by(desc(ProductCardVersion.version_number)).limit(1))
        return result.scalar_one_or_none()

    async def get_version(
        self,
        product_id: int,
        version_number: int,
        *,
        project_id: str | None = None,
        project_product_id: str | None = None,
    ) -> ProductCardVersion | None:
        stmt = (
            select(ProductCardVersion)
            .where(ProductCardVersion.product_id == product_id)
            .where(ProductCardVersion.version_number == version_number)
        )
        if project_id is not None:
            stmt = stmt.where(ProductCardVersion.project_id == project_id)
        elif project_product_id is None:
            stmt = stmt.where(ProductCardVersion.project_id.is_(None))
        if project_product_id is not None:
            stmt = stmt.where(ProductCardVersion.project_product_id == project_product_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_versions(
        self,
        product_id: int,
        *,
        project_id: str | None = None,
        project_product_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ProductCardVersion]:
        stmt = select(ProductCardVersion).where(ProductCardVersion.product_id == product_id)
        if project_id is not None:
            stmt = stmt.where(ProductCardVersion.project_id == project_id)
        elif project_product_id is None:
            stmt = stmt.where(ProductCardVersion.project_id.is_(None))
        if project_product_id is not None:
            stmt = stmt.where(ProductCardVersion.project_product_id == project_product_id)
        result = await self._session.execute(stmt.order_by(desc(ProductCardVersion.version_number)).limit(limit).offset(offset))
        return list(result.scalars().all())

    async def next_version_number(
        self,
        product_id: int,
        *,
        project_id: str | None = None,
        project_product_id: str | None = None,
    ) -> int:
        # version_number remains unique per product for backward compatibility
        # with the existing ix_product_card_versions_product_number index.
        current = await self._session.scalar(
            select(func.max(ProductCardVersion.version_number)).where(ProductCardVersion.product_id == product_id)
        )
        return int(current or 0) + 1
