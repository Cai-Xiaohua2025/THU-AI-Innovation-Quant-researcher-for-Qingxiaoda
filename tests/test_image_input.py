from __future__ import annotations

import base64
from dataclasses import replace

import pytest
import requests

from qingyan_agent.app import create_app
from qingyan_agent.config import Settings
from qingyan_agent.file_reader import FileReader, validate_remote_url
from qingyan_agent.protocol import InputImage, parse_request


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class DownloadResponse:
    def __init__(self, content: bytes, content_type: str = "image/png", content_length: int | None = None):
        self.content = content
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(content) if content_length is None else content_length),
        }

    def iter_content(self, chunk_size=8192):
        yield self.content

    def close(self):
        return None


def settings(tmp_path, **kwargs):
    base = Settings(
        report_dir=tmp_path / "reports",
        cache_dir=tmp_path / "cache",
        conversation_dir=tmp_path / "conversations",
        request_timeout_sec=1,
        api_token="",
        public_base_url="",
        llm_base_url="",
        llm_api_key="",
        llm_model="",
    )
    return replace(base, **kwargs)


def test_parse_image_url_with_text_and_history():
    parsed = parse_request({
        "messages": [
            {"role": "assistant", "content": "请上传图片"},
            {"role": "user", "content": [
                {"type": "text", "text": "分析这张K线图"},
                {"type": "image_url", "image_url": {"url": "https://oss.example.com/chart.png", "detail": "high"}},
            ]},
        ]
    })
    assert "assistant: 请上传图片" in parsed.prompt
    assert "user: 分析这张K线图" in parsed.prompt
    assert len(parsed.images) == 1
    assert parsed.images[0].url == "https://oss.example.com/chart.png"
    assert parsed.images[0].detail == "high"


def test_private_image_url_is_blocked():
    with pytest.raises(ValueError, match="blocked"):
        validate_remote_url("http://127.0.0.1/chart.png")


def test_non_image_content_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "qingyan_agent.file_reader.download_response",
        lambda *args, **kwargs: (DownloadResponse(b"not an image", "text/plain"), "https://oss.example.com/chart.png"),
    )
    result = FileReader(settings(tmp_path)).read_image(InputImage("https://oss.example.com/chart.png"))
    assert result.status.startswith("read failed:")
    assert not result.data_url


def test_oversized_image_is_rejected_before_read(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "qingyan_agent.file_reader.download_response",
        lambda *args, **kwargs: (DownloadResponse(PNG_1X1, content_length=2048), "https://oss.example.com/chart.png"),
    )
    result = FileReader(settings(tmp_path, max_image_bytes=1024)).read_image(
        InputImage("https://oss.example.com/chart.png")
    )
    assert "image exceeds limit" in result.status


def test_image_chat_uses_vision_and_returns_analysis(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(
        "qingyan_agent.file_reader.download_response",
        lambda *args, **kwargs: (DownloadResponse(PNG_1X1), "https://oss.example.com/chart.png"),
    )

    class LLMResponse:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": (
                "## 研究结论摘要\n图片呈震荡走势。\n\n"
                "## 关键证据\n- 只使用图中可见线条。\n\n"
                "## 风险与待验证事项\n- 精确数值待核验。"
            )}}]}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return LLMResponse()

    monkeypatch.setattr("qingyan_agent.llm_client.requests.post", fake_post)
    app = create_app(settings(
        tmp_path,
        llm_base_url="https://gateway.example.com/v1",
        llm_model="vision-model",
    ))
    response = app.test_client().post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "分析图中的趋势"},
            {"type": "image_url", "image_url": {"url": "https://oss.example.com/chart.png"}},
        ]}],
    })
    assert response.status_code == 200
    assert "图片呈震荡走势" in response.get_json()["choices"][0]["message"]["content"]
    upstream_content = captured["json"]["messages"][1]["content"]
    assert any(part.get("type") == "image_url" for part in upstream_content)


def test_image_chat_fails_closed_when_vision_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "qingyan_agent.file_reader.download_response",
        lambda *args, **kwargs: (DownloadResponse(PNG_1X1), "https://oss.example.com/chart.png"),
    )
    monkeypatch.setattr(
        "qingyan_agent.llm_client.requests.post",
        lambda *args, **kwargs: (_ for _ in ()).throw(requests.Timeout("vision timeout")),
    )
    app = create_app(settings(
        tmp_path,
        llm_base_url="https://gateway.example.com/v1",
        llm_model="vision-model",
    ))
    response = app.test_client().post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "分析图中的趋势"},
            {"type": "image_url", "image_url": {"url": "https://oss.example.com/chart.png"}},
        ]}],
    })
    content = response.get_json()["choices"][0]["message"]["content"]
    assert "视觉模型不可用" in content
    assert "没有假装识别" in content
