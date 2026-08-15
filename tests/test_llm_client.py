import requests

from qingyan_agent.config import Settings
from qingyan_agent.llm_client import UpstreamLLMClient, extract_message_content, normalize_chat_completions_url


class FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self.payload = payload
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}")

    def json(self):
        return self.payload


def test_normalize_chat_completions_url():
    assert normalize_chat_completions_url("https://gateway.example.com") == "https://gateway.example.com/v1/chat/completions"
    assert normalize_chat_completions_url("https://gateway.example.com/v1/") == "https://gateway.example.com/v1/chat/completions"
    assert normalize_chat_completions_url("https://gateway.example.com/v1/chat/completions") == "https://gateway.example.com/v1/chat/completions"


def test_upstream_llm_openai_compatible_request(monkeypatch, tmp_path):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse({
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "## 研究结论摘要\n上游综合测试\n\n## 关键证据\n- 测试证据\n\n## 风险与待验证事项\n- 待核验",
                }
            }]
        })

    monkeypatch.setattr("qingyan_agent.llm_client.requests.post", fake_post)
    settings = Settings(
        report_dir=tmp_path / "reports",
        cache_dir=tmp_path / "cache",
        api_token="",
        public_base_url="",
        llm_base_url="https://gateway.example.com/v1",
        llm_api_key="upstream-secret",
        llm_model="example-model",
    )
    result = UpstreamLLMClient(settings).synthesize(
        question="测试问题",
        intent="full_research",
        evidence={"quote": {"price": 10.0, "source": "test"}},
        deterministic_draft="本地草稿",
    )

    assert result.used is True
    assert "上游综合测试" in result.content
    assert captured["url"] == "https://gateway.example.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer upstream-secret"
    assert captured["json"]["model"] == "example-model"
    assert captured["json"]["stream"] is False
    assert captured["json"]["messages"][0]["role"] == "system"


def test_upstream_failure_returns_fallback_result(monkeypatch, tmp_path):
    def fail_post(*args, **kwargs):
        raise requests.Timeout("test timeout")

    monkeypatch.setattr("qingyan_agent.llm_client.requests.post", fail_post)
    settings = Settings(
        report_dir=tmp_path / "reports",
        cache_dir=tmp_path / "cache",
        api_token="",
        public_base_url="",
        llm_base_url="https://gateway.example.com",
        llm_model="example-model",
    )
    result = UpstreamLLMClient(settings).synthesize(
        question="测试问题",
        intent="full_research",
        evidence={},
        deterministic_draft="本地草稿",
    )

    assert result.used is False
    assert result.content == ""
    assert "Timeout" in result.error


def test_extract_message_content_parts():
    payload = {
        "choices": [{
            "message": {
                "content": [
                    {"type": "text", "text": "第一段"},
                    {"type": "output_text", "text": "第二段"},
                ]
            }
        }]
    }
    assert extract_message_content(payload) == "第一段\n第二段"


def test_retries_with_max_completion_tokens_for_modern_models(monkeypatch, tmp_path):
    payloads = []

    def fake_post(url, **kwargs):
        payloads.append(kwargs["json"])
        if len(payloads) == 1:
            return FakeResponse(
                {"error": {"message": "max_tokens is not supported"}},
                status_code=400,
                text="max_tokens is not supported; use max_completion_tokens",
            )
        return FakeResponse({
            "choices": [{"message": {"content": "兼容重试成功"}}]
        })

    monkeypatch.setattr("qingyan_agent.llm_client.requests.post", fake_post)
    settings = Settings(
        report_dir=tmp_path / "reports",
        cache_dir=tmp_path / "cache",
        api_token="",
        public_base_url="",
        llm_base_url="https://gateway.example.com/v1",
        llm_model="reasoning-model",
    )
    result = UpstreamLLMClient(settings).synthesize(
        question="测试问题",
        intent="full_research",
        evidence={},
        deterministic_draft="本地草稿",
    )

    assert result.used is True
    assert result.content == "兼容重试成功"
    assert len(payloads) == 2
    assert "max_tokens" in payloads[0]
    assert "temperature" in payloads[0]
    assert "max_tokens" not in payloads[1]
    assert "temperature" not in payloads[1]
    assert payloads[1]["max_completion_tokens"] == settings.llm_max_tokens
