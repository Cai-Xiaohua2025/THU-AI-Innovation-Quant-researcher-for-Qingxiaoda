from __future__ import annotations

import json
import stat

from qingyan_agent.config import Settings
from qingyan_agent.conversation_store import ConversationStore, sanitize_url
from qingyan_agent.protocol import InputFile, InputImage, ParsedRequest


def make_settings(tmp_path, **kwargs) -> Settings:
    return Settings(
        report_dir=tmp_path / "reports",
        cache_dir=tmp_path / "cache",
        conversation_dir=tmp_path / "conversations",
        llm_base_url="",
        llm_api_key="",
        llm_model="",
        **kwargs,
    )


def test_conversation_store_writes_private_daily_json_and_sanitizes_urls(tmp_path):
    store = ConversationStore(make_settings(tmp_path))
    parsed = ParsedRequest(
        model="qingyan-liangce-agent",
        stream=False,
        prompt="user: 分析吉林化纤近期走势",
        max_tokens=1200,
        files=[InputFile(
            filename="report.pdf",
            url="https://user:secret@example.com/report.pdf?token=private#page=1",
        )],
        images=[InputImage(
            url="https://images.example.com/chart.png?signature=private",
            detail="high",
        )],
    )
    path = store.save(
        request_id="request/test:id",
        parsed=parsed,
        response_text="吉林化纤近期处于中性震荡。",
        finish_reason="stop",
        title="吉林化纤走势研究报告",
        report_enabled=True,
        attachments=[{
            "fileName": "吉林化纤报告.pdf",
            "fileType": "pdf",
            "mimeType": "application/pdf",
            "fileSize": 1234,
            "fileUrl": "https://server.example.com/files/report.pdf?secret=1",
        }],
        processing_ms=42.5,
    )
    assert path is not None and path.exists()
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["request"]["prompt"] == "user: 分析吉林化纤近期走势"
    assert record["response"]["content"] == "吉林化纤近期处于中性震荡。"
    assert record["request"]["files"][0]["url"] == "https://example.com/report.pdf"
    assert record["request"]["images"][0]["url"] == "https://images.example.com/chart.png"
    assert "fileUrl" not in record["response"]["attachments"][0]
    assert record["storage"]["authorization_header_saved"] is False
    assert record["storage"]["configured_api_key_saved"] is False
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_conversation_store_respects_storage_character_limit(tmp_path):
    store = ConversationStore(make_settings(tmp_path, conversation_max_chars=5))
    path = store.save(
        request_id="limited",
        parsed=ParsedRequest(model="m", stream=True, prompt="123456789"),
        response_text="abcdefghi",
        finish_reason="length",
        title="test",
        report_enabled=False,
        attachments=[],
    )
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["request"]["prompt"] == "12345"
    assert record["request"]["prompt_truncated_for_storage"] is True
    assert record["response"]["content"] == "abcde"
    assert record["response"]["content_truncated_for_storage"] is True


def test_sanitize_url_rejects_non_http_urls():
    assert sanitize_url("file:///etc/passwd") == ""
    assert sanitize_url("data:text/plain,secret") == ""


def test_conversation_storage_can_be_disabled(tmp_path):
    store = ConversationStore(make_settings(tmp_path, save_conversations=False))
    path = store.save(
        request_id="disabled",
        parsed=ParsedRequest(model="m", stream=False, prompt="do not save"),
        response_text="not saved",
        finish_reason="stop",
        title="test",
        report_enabled=False,
        attachments=[],
    )
    assert path is None
    assert not (tmp_path / "conversations").exists()
