from app.ai_recommendation.provider import AIResponse
from app.ai_recommendation.providers.base import BaseAIProvider


class DummyProvider(BaseAIProvider):
    def name(self) -> str:
        return "dummy"

    async def complete(self, prompt: str, system: str = "", max_tokens: int = 2048, temperature: float = 0.3):
        return AIResponse(text="ok", model=self._model)


def test_ai_response_ok_property():
    assert AIResponse(text="done", model="x").ok is True
    assert AIResponse(text="", model="x").ok is False
    assert AIResponse(text="done", model="x", error_type="TimeoutError").ok is False


def test_error_response_contains_diagnostics():
    provider = DummyProvider(api_key="k", model="m", base_url="https://example.test")
    response = provider._create_error_response(
        TimeoutError("slow"),
        "prompt",
        status_code=504,
        stage="read_timeout",
    )
    assert response.text == ""
    assert response.model == "m"
    assert response.error_type == "TimeoutError"
    assert response.error_message == "slow"
    assert response.status_code == 504
    assert response.error_stage == "read_timeout"
    assert response.ok is False
