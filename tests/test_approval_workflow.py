"""Tests for the approval workflow with DB persistence and rollback."""

from __future__ import annotations

import json
import os
import unittest
from datetime import UTC

from tests.helpers import reload_app_modules


class ApprovalWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
        reload_app_modules(database_url="sqlite+aiosqlite://")

        from app.ai_recommendation.db_approval import DatabaseApprovalQueue
        from app.ai_recommendation.suggestions import AIRecommendationResult, AISuggestion
        from app.database import Database

        self.db = Database()
        await self.db.init()
        self.queue = DatabaseApprovalQueue(self.db)
        self.AISuggestion = AISuggestion
        self.AIRecommendationResult = AIRecommendationResult

    async def asyncTearDown(self):
        await self.db._engine.dispose()

    def _make_result(self, product_id="prod-001", **kwargs):
        defaults = {
            "field": "title",
            "suggestion_type": "improve",
            "before": "Old title",
            "after": "New improved title",
            "reason": "Better SEO",
            "confidence": 0.9,
        }
        defaults.update(kwargs)
        return self.AIRecommendationResult(
            product_id=product_id,
            suggestions=[self.AISuggestion(**defaults)],
        )

    async def test_add_record_to_db(self):
        result = self._make_result()
        added = await self.queue.add(result)
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].product_id, "prod-001")

        all_items = await self.queue.get_all()
        self.assertEqual(len(all_items), 1)
        self.assertEqual(all_items[0].suggestion.after, "New improved title")

    async def test_approve_updates_status(self):
        result = self._make_result()
        added = await self.queue.add(result)
        aid = added[0].approval_id

        approved = await self.queue.approve(aid)
        self.assertIsNotNone(approved)
        self.assertTrue(approved.approved)

        # Verify in DB
        record = await self.queue.get_record(aid)
        self.assertEqual(record.status, "approved")
        self.assertIsNotNone(record.reviewed_at)

    async def test_reject_updates_status_with_reason(self):
        result = self._make_result()
        added = await self.queue.add(result)
        aid = added[0].approval_id

        rejected = await self.queue.reject(aid, reason="Not relevant")
        self.assertIsNotNone(rejected)
        self.assertFalse(rejected.approved)
        self.assertIn("Not relevant", rejected.suggestion.reason)

        # Verify in DB
        record = await self.queue.get_record(aid)
        self.assertEqual(record.status, "rejected")
        self.assertEqual(record.reject_reason, "Not relevant")

    async def test_rollback_restores_original_value(self):
        """Test that rollback restores the original value from snapshot."""
        result = self._make_result(
            before="Original title",
            after="AI suggested title",
        )
        added = await self.queue.add(result)
        aid = added[0].approval_id

        # Approve
        await self.queue.approve(aid)

        # Simulate apply with snapshot
        from datetime import datetime

        from app.database import ApprovalRecord
        async with self.db.session() as s:
            record = (await s.execute(
                select(ApprovalRecord).where(ApprovalRecord.approval_id == aid)
            )).scalar_one()
            snapshot = json.dumps({
                "field": "title",
                "value": "Original title",
                "timestamp": datetime.now(UTC).isoformat(),
            })
            record.snapshot_before = snapshot
            record.applied_at = datetime.now(UTC)
            await s.commit()

        # Create a mock product with the field set to the AI value
        class FakeProduct:
            title = "AI suggested title"

        product = FakeProduct()
        self.assertEqual(product.title, "AI suggested title")

        # Rollback with product
        success = await self.queue.rollback(aid, product=product)
        self.assertTrue(success)

        # Verify product field was restored
        self.assertEqual(product.title, "Original title")

        # Verify rollback info in DB
        info = await self.queue.get_rollback_info(aid)
        self.assertIsNotNone(info)
        self.assertEqual(info["status"], "rolled_back")
        self.assertEqual(info["snapshot_before"]["value"], "Original title")

    async def test_rollback_without_product_succeeds(self):
        """Test that rollback works without a product (backward compat)."""
        result = self._make_result(
            before="Original title",
            after="AI suggested title",
        )
        added = await self.queue.add(result)
        aid = added[0].approval_id

        await self.queue.approve(aid)

        from datetime import datetime

        from app.database import ApprovalRecord
        async with self.db.session() as s:
            record = (await s.execute(
                select(ApprovalRecord).where(ApprovalRecord.approval_id == aid)
            )).scalar_one()
            snapshot = json.dumps({
                "field": "title",
                "value": "Original title",
                "timestamp": datetime.now(UTC).isoformat(),
            })
            record.snapshot_before = snapshot
            record.applied_at = datetime.now(UTC)
            await s.commit()

        # Rollback without product
        success = await self.queue.rollback(aid)
        self.assertTrue(success)

        info = await self.queue.get_rollback_info(aid)
        self.assertEqual(info["status"], "rolled_back")

    async def test_apply_saves_snapshots(self):
        """Test that apply_approved saves before/after snapshots."""
        from app.database import Product, url_to_hash

        # Create a product in DB
        async with self.db.session() as s:
            product = Product(
                url_hash=url_to_hash("https://example.com/1"),
                url="https://example.com/1",
                name="Test Product",
            )
            s.add(product)
            await s.commit()
            product_id = product.id

        result = self._make_result(product_id=str(product_id), field="name", after="New Product Name")
        added = await self.queue.add(result)
        aid = added[0].approval_id

        # Approve
        await self.queue.approve(aid)

        # Apply
        async with self.db.session() as s:
            product = (await s.execute(
                select(Product).where(Product.id == product_id)
            )).scalar_one()

        applied = await self.queue.apply_approved(product)
        self.assertEqual(applied, ["name"])

        # Verify snapshots saved
        record = await self.queue.get_record(aid)
        self.assertIsNotNone(record.snapshot_before)
        self.assertIsNotNone(record.snapshot_after)
        self.assertIsNotNone(record.applied_at)

        # Verify snapshot content
        before_snap = json.loads(record.snapshot_before)
        after_snap = json.loads(record.snapshot_after)
        self.assertEqual(before_snap["field"], "name")
        self.assertEqual(after_snap["value"], "New Product Name")

    async def test_history_records_operations(self):
        """Test that history tracks all operations."""
        # Add multiple items
        result1 = self._make_result(product_id="p1")
        result2 = self._make_result(product_id="p2", field="description")
        await self.queue.add(result1)
        await self.queue.add(result2)

        all_items = await self.queue.get_all()
        await self.queue.approve(all_items[0].approval_id)
        await self.queue.reject(all_items[1].approval_id, reason="Skip")

        history = await self.queue.get_history()
        self.assertEqual(len(history), 2)

        # Filter by product
        history_p1 = await self.queue.get_history(product_id="p1")
        self.assertEqual(len(history_p1), 1)
        self.assertEqual(history_p1[0]["status"], "approved")

        history_p2 = await self.queue.get_history(product_id="p2")
        self.assertEqual(len(history_p2), 1)
        self.assertEqual(history_p2[0]["status"], "rejected")

    async def test_queue_survives_restart(self):
        """Test that data persists across queue instances."""
        from app.ai_recommendation.db_approval import DatabaseApprovalQueue

        result = self._make_result()
        added = await self.queue.add(result)
        aid = added[0].approval_id
        await self.queue.approve(aid)

        # Create new queue instance (simulates restart)
        queue2 = DatabaseApprovalQueue(self.db)
        all_items = await queue2.get_all()
        self.assertEqual(len(all_items), 1)
        self.assertEqual(all_items[0].approval_id, aid)
        self.assertTrue(all_items[0].approved)

    async def test_get_pending_returns_only_pending(self):
        result1 = self._make_result(product_id="p1")
        result2 = self._make_result(product_id="p2")
        added1 = await self.queue.add(result1)
        await self.queue.add(result2)

        await self.queue.approve(added1[0].approval_id)

        pending = await self.queue.get_pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].product_id, "p2")

    async def test_reject_nonexistent_returns_none(self):
        result = await self.queue.reject("nonexistent-id", reason="test")
        self.assertIsNone(result)

    async def test_approve_nonexistent_returns_none(self):
        result = await self.queue.approve("nonexistent-id")
        self.assertIsNone(result)

    async def test_get_status_counts_empty_queue_returns_all_zero(self):
        counts = await self.queue.get_status_counts()
        self.assertEqual(counts, {"total": 0, "pending": 0, "approved": 0, "rejected": 0, "rolled_back": 0})

    async def test_get_status_counts_reflects_mixed_statuses(self):
        await self.queue.add(self._make_result("p1"))
        approved = (await self.queue.add(self._make_result("p2")))[0]
        rejected = (await self.queue.add(self._make_result("p3")))[0]

        await self.queue.approve(approved.approval_id)
        await self.queue.reject(rejected.approval_id, reason="test")

        counts = await self.queue.get_status_counts()

        self.assertEqual(counts["total"], 3)
        self.assertEqual(counts["pending"], 1)
        self.assertEqual(counts["approved"], 1)
        self.assertEqual(counts["rejected"], 1)
        self.assertEqual(counts["rolled_back"], 0)


# Need select for inline queries
from sqlalchemy import select  # noqa: E402

if __name__ == "__main__":
    unittest.main()
