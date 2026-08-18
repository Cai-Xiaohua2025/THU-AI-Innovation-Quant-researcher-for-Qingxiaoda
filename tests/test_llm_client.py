import requests

from qingyan_agent.config import Settings
from qingyan_agent.contracts import AnswerProfile
from qingyan_agent.llm_client import (
    UpstreamLLMClient,
    answer_respects_profile,
    build_synthesis_input,
    deduplicate_repeated_blocks,
    extract_message_content,
    normalize_chat_completions_url,
    sanitize_evidence_for_llm,
)


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


def test_upstream_llm_multimodal_request(monkeypatch, tmp_path):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return FakeResponse({"choices": [{"message": {"content": "图片趋势已分析"}}]})

    monkeypatch.setattr("qingyan_agent.llm_client.requests.post", fake_post)
    settings = Settings(
        report_dir=tmp_path / "reports",
        cache_dir=tmp_path / "cache",
        llm_base_url="https://gateway.example.com/v1",
        llm_model="vision-model",
    )
    result = UpstreamLLMClient(settings).synthesize(
        question="分析这张K线图",
        intent="technical",
        evidence={"images": [{"status": "ok"}]},
        deterministic_draft="本地草稿",
        image_data_urls=["data:image/png;base64,AAAA"],
    )

    assert result.used is True
    content = captured["json"]["messages"][1]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,AAAA", "detail": "high"},
    }


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


def test_synthesis_input_carries_announcement_source_text_only_once():
    raw = "[第1页]\n唯一公告原文标记-XYZ"
    evidence = {
        "announcements": [{
            "symbol": "600900",
            "title": "测试公告",
            "date": "2026-08-01",
            "attachment": {"status": "ok", "text": raw},
        }],
        "announcement_analysis": [{
            "title": "测试公告",
            "facts": ["结构化事实"],
        }],
    }

    content = build_synthesis_input(
        question="看看公告",
        intent="announcement",
        evidence=evidence,
        deterministic_draft="标准草稿只包含结构化事实，不包含原文标记。",
        max_chars=12000,
    )
    sanitized, excerpts = sanitize_evidence_for_llm(evidence)

    assert content.count("唯一公告原文标记-XYZ") == 1
    assert "source_excerpts" in content
    assert sanitized["announcements"][0]["attachment"]["text_available"] is True
    assert "text" not in sanitized["announcements"][0]["attachment"]
    assert excerpts[0]["title"] == "测试公告"


def test_synthesis_input_preserves_final_instruction_under_budget_pressure():
    content = build_synthesis_input(
        question="问题" * 1000,
        intent="full_research",
        evidence={"large": "证据" * 10000},
        deterministic_draft="草稿" * 10000,
        max_chars=5000,
    )

    assert len(content) <= 5000
    assert content.endswith("必须区分公告事实、分析推断、潜在影响和待验证事项。")


def test_final_answer_deduplicates_repeated_long_paragraphs_only():
    duplicate = "这是一段重复的公告正文证据。" * 12
    content = f"## 公告证据\n\n{duplicate}\n\n## 其他部分\n\n{duplicate}\n\n短句\n\n短句"

    result = deduplicate_repeated_blocks(content)

    assert result.count(duplicate) == 1
    assert result.count("短句") == 2


def test_chat_answer_profile_rejects_report_only_announcement_source_text():
    safe = "## 重要公告解读\n- 公司披露年度分红安排。\n- [查看原文](https://example.com/a.pdf)"
    raw = "## 公告附件正文证据\n[第1页]\n证券代码：600900\n" + "公告原文" * 200

    assert answer_respects_profile(safe, AnswerProfile.CONCISE) is True
    assert answer_respects_profile(raw, AnswerProfile.STANDARD) is False
    assert answer_respects_profile("正常分析" * 1500, AnswerProfile.STANDARD) is False
    assert answer_respects_profile(raw, AnswerProfile.DETAILED) is True
