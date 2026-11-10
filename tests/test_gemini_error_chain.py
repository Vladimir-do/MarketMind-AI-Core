"""Integration test: HTTP 429 from Gemini → ask_ai → job_records.error_text."""

import contextlib
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from tests.helpers import reload_app_modules


class _FakeGeminiResponse:
    def __init__(self, status: int, body: str, headers: dict | None = None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def text(self):
        return self._body


class _FakeGeminiSession:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def post(self, *args, **kwargs):
        if self._exc is not None:
            outer = self._exc

            class _Raising:
                async def __aenter__(self):
                    raise outer

                async def __aexit__(self, *a):
                    return False

            return _Raising()
        return self._response


def _mock_effective_service():
    card = SimpleNamespace(
        effective_snapshot={
            "title": "Test Product",
            "description": "Test description",
            "brand": "TestBrand",
            "category": "TestCat",
            "price": 100,
            "tags": ["tag1"],
            "marketplace": "ozon",
        },
        project_product_id=1,
    )
    mock_svc = AsyncMock()
    mock_svc.get_effective_card.return_value = card
    return mock_svc


class GeminiErrorToJobRecordsTests(unittest.IsolatedAsyncioTestCase):
    """Verify that HTTP 429 from Gemini flows correctly to job_records."""

    async def test_429_does_not_create_succeeded_job(self):
        import app.ai_client as ai_client
        from app.ai_recommendation.job_queue import process_project_seo_suggestion_job
        from app.database import ApprovalRecord, JobRecord

        body = (
            '{"error":{"code":429,'
            '"message":"Quota exceeded for metric: '
            "generativelanguage.googleapis.com/generate_content_free_tier_requests, "
            'limit: 0, model: gemini-2.0-flash",'
            '"status":"RESOURCE_EXHAUSTED"}}'
        )
        response = _FakeGeminiResponse(429, body)

        def session_factory(*a, **kw):
            return _FakeGeminiSession(response=response)

        job_id = f"test-429-{uuid.uuid4().hex[:8]}"
        _, database = reload_app_modules(database_url="sqlite+aiosqlite://")
        db = database.Database()
        await db.init()
        mock_app = MagicMock()
        mock_app.state.db = db
        mock_app.state.ai_queue = None

        with (
            patch.dict("os.environ", {"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "test-key"}),
            patch.object(ai_client, "GEMINI_API_KEY", "test-key"),
            patch.object(ai_client.aiohttp, "ClientSession", session_factory),
            patch(
                "app.ai_recommendation.job_queue.EffectiveProductCardService",
                return_value=_mock_effective_service(),
            ),
        ):
            await db.create_job("seo_suggestion", {"action": "test"}, job_id=job_id)
            await db.start_job(job_id)

            error_raised = False
            try:
                await process_project_seo_suggestion_job(
                    mock_app,
                    job_id,
                    "project-test",
                    99001,
                    action="Расширить описание",
                )
            except RuntimeError:
                error_raised = True

            self.assertTrue(error_raised, "Expected RuntimeError for 429 error")

        from sqlalchemy import select

        async with db.session() as s:
            result = await s.execute(select(JobRecord).where(JobRecord.job_id == job_id))
            job = result.scalar_one()

        self.assertEqual(job.status, "failed")
        self.assertIn("429", job.error_text)
        self.assertIn("quota", job.error_text.lower())
        self.assertNotIn("TimeoutError", job.error_text)
        self.assertNotIn("test-key", job.error_text)

        async with db.session() as s:
            approvals = await s.execute(select(ApprovalRecord).where(ApprovalRecord.product_id == "99001"))
            self.assertEqual(len(approvals.scalars().all()), 0)

    async def test_timeout_error_does_not_create_succeeded_job(self):
        import app.ai_client as ai_client
        from app.ai_recommendation.job_queue import process_project_seo_suggestion_job
        from app.database import JobRecord

        def session_factory(*a, **kw):
            return _FakeGeminiSession(exc=TimeoutError("connection timed out"))

        job_id = f"test-timeout-{uuid.uuid4().hex[:8]}"
        _, database = reload_app_modules(database_url="sqlite+aiosqlite://")
        db = database.Database()
        await db.init()
        mock_app = MagicMock()
        mock_app.state.db = db
        mock_app.state.ai_queue = None

        with (
            patch.dict("os.environ", {"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "test-key"}),
            patch.object(ai_client, "GEMINI_API_KEY", "test-key"),
            patch.object(ai_client.aiohttp, "ClientSession", session_factory),
            patch(
                "app.ai_recommendation.job_queue.EffectiveProductCardService",
                return_value=_mock_effective_service(),
            ),
        ):
            await db.create_job("seo_suggestion", {"action": "test"}, job_id=job_id)
            await db.start_job(job_id)

            error_raised = False
            try:
                await process_project_seo_suggestion_job(
                    mock_app,
                    job_id,
                    "project-test",
                    99002,
                    action="Улучшить заголовок",
                )
            except RuntimeError:
                error_raised = True

            self.assertTrue(error_raised, "Expected RuntimeError for timeout")

        from sqlalchemy import select

        async with db.session() as s:
            result = await s.execute(select(JobRecord).where(JobRecord.job_id == job_id))
            job = result.scalar_one()

        self.assertEqual(job.status, "failed")
        self.assertIn("timeout", job.error_text.lower())
        self.assertNotIn("429", job.error_text)
        self.assertNotIn("test-key", job.error_text)

    async def test_error_text_not_parsed_as_json(self):
        from app.ai_recommendation.engine import AIRecommendationEngine

        error_text = "AI error: Gemini API недоступен: quota (HTTP 429)"
        suggestions = AIRecommendationEngine._parse_suggestions(error_text)
        self.assertEqual(suggestions, [])

    async def test_error_string_not_treated_as_successful_response(self):
        import app.ai_client as ai_client
        from app.ai_recommendation.job_queue import process_project_seo_suggestion_job
        from app.database import ApprovalRecord, JobRecord

        error_response = _FakeGeminiResponse(
            429,
            '{"error":{"code":429,"message":"Quota exceeded","status":"RESOURCE_EXHAUSTED"}}',
        )

        def session_factory(*a, **kw):
            return _FakeGeminiSession(response=error_response)

        job_id = f"test-noapproval-{uuid.uuid4().hex[:8]}"
        _, database = reload_app_modules(database_url="sqlite+aiosqlite://")
        db = database.Database()
        await db.init()
        mock_app = MagicMock()
        mock_app.state.db = db
        mock_app.state.ai_queue = None

        with (
            patch.dict("os.environ", {"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "test-key"}),
            patch.object(ai_client, "GEMINI_API_KEY", "test-key"),
            patch.object(ai_client.aiohttp, "ClientSession", session_factory),
            patch(
                "app.ai_recommendation.job_queue.EffectiveProductCardService",
                return_value=_mock_effective_service(),
            ),
        ):
            await db.create_job("seo_suggestion", {"action": "test"}, job_id=job_id)
            await db.start_job(job_id)

            with contextlib.suppress(RuntimeError):
                await process_project_seo_suggestion_job(mock_app, job_id, "project-x", 99003, action="test")

        from sqlalchemy import select

        async with db.session() as s:
            result = await s.execute(select(JobRecord).where(JobRecord.job_id == job_id))
            job = result.scalar_one()

        self.assertEqual(job.status, "failed")
        self.assertIn("429", job.error_text)

        async with db.session() as s:
            approvals = await s.execute(select(ApprovalRecord).where(ApprovalRecord.product_id == "99003"))
            self.assertEqual(len(approvals.scalars().all()), 0)


if __name__ == "__main__":
    unittest.main()
