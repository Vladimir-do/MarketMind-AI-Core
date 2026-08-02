import json
from types import SimpleNamespace

import pytest

from app.web.routes.suggestions import _recent_jobs


class FakeDB:
    async def get_recent_jobs(self, limit=10):
        return [
            SimpleNamespace(
                job_id="job-1",
                job_type="seo_ai_suggestions",
                status="failed",
                progress=10,
                payload_json="{}",
                result_json=json.dumps({
                    "provider": "gemini",
                    "model": "gemini-2.5-flash",
                    "stage": "read_timeout",
                    "status_code": None,
                    "latency_ms": 60001.0,
                    "error_type": "TimeoutError",
                    "error_message": "request timed out",
                }),
                error_class="AIJobFailure",
                error_text="AI request failed",
                created_at=None,
                started_at=None,
                finished_at=None,
                updated_at=None,
            )
        ]


@pytest.mark.asyncio
async def test_recent_jobs_exposes_structured_failed_job_diagnostics():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=FakeDB())))
    jobs = await _recent_jobs(request)
    assert len(jobs) == 1
    assert jobs[0]["diagnostics"]["provider"] == "gemini"
    assert jobs[0]["diagnostics"]["stage"] == "read_timeout"
    assert jobs[0]["diagnostics"]["error_type"] == "TimeoutError"
