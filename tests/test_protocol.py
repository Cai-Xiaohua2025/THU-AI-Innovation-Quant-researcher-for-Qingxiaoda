from __future__ import annotations

import json

import pytest

from qingyan_agent.protocol import (
    append_artifact_links,
    completion_response,
    parse_request,
    progress_event,
    stream_response,
    truncate_to_token_budget,
)


def test_parse_request_preserves_roles_files_images_and_modern_token_limit():
    parsed = parse_request({
        "model": "qingyan-liangce-agent",
        "stream": True,
        "max_completion_tokens": 128,
        "messages": [
            {"role": "system", "content": "只使用公开信息"},
            {"role": "user", "content": [
                {"type": "text", "text": "分析长江电力"},
                {"type": "file", "file": {"filename": "report.pdf", "url": "https://example.com/a.pdf"}},
                {"type": "image_url", "image_url": {"url": "https://example.com/a.png", "detail": "high"}},
            ]},
        ],
    })

    assert parsed.stream is True
    assert parsed.max_tokens == 128
    assert "system: 只使用公开信息" in parsed.prompt
    assert "user: 分析长江电力" in parsed.prompt
    assert parsed.files[0].filename == "report.pdf"
    assert parsed.images[0].detail == "high"


@pytest.mark.parametrize("payload", [
    None,
    {},
    {"messages": []},
    {"messages": [{"role": "user", "content": ""}]},
    {"messages": [{"role": "user", "content": "x"}], "stream": "yes"},
    {"messages": [{"role": "user", "content": "x"}], "max_tokens": 0},
])
def test_parse_request_rejects_invalid_payloads(payload):
    with pytest.raises(ValueError):
        parse_request(payload)


def test_completion_and_sse_keep_openai_and_attachment_shapes():
    attachments = [{
        "fileName": "report.pdf",
        "fileUrl": "https://example.com/files/report.pdf",
        "fileType": "pdf",
        "mimeType": "application/pdf",
        "fileSize": 10,
    }]
    completion = completion_response("model", "question", "answer", attachments)
    assert completion["choices"][0]["message"]["content"] == "answer"
    assert completion["x_soda"]["attachments"] == attachments

    chunks = list(stream_response("model", "question", "answer", attachments))
    assert chunks[-1] == "data: [DONE]\n\n"
    final = json.loads(chunks[-2].removeprefix("data: "))
    assert final["choices"][0]["finish_reason"] == "stop"
    assert final["x_soda"]["attachments"] == attachments


def test_artifact_links_are_visible_when_client_hides_x_soda_metadata():
    attachments = [
        {
            "fileUrl": "https://example.com/files/report.pdf",
            "mimeType": "application/pdf",
        },
        {
            "fileUrl": "https://example.com/files/report.md",
            "mimeType": "text/markdown",
        },
        {
            "fileUrl": "file:///internal/report.png",
            "mimeType": "image/png",
        },
    ]

    answer = append_artifact_links("研究完成。\n\n合规提示：仅作研究辅助。", attachments)

    assert "[下载 PDF 研报](https://example.com/files/report.pdf)" in answer
    assert "[查看 Markdown 研报](https://example.com/files/report.md)" in answer
    assert "file:///internal" not in answer
    assert answer.endswith("合规提示：仅作研究辅助。")
    assert append_artifact_links(answer, attachments) == answer


def test_progress_event_is_an_additive_openai_compatible_chunk():
    chunk = progress_event(
        "model",
        "researching",
        "正在收集证据",
        chat_id="chatcmpl-fixed",
        created=123,
    )
    payload = json.loads(chunk.removeprefix("data: "))

    assert payload["id"] == "chatcmpl-fixed"
    assert payload["choices"][0]["delta"] == {}
    assert payload["choices"][0]["finish_reason"] is None
    assert payload["x_qingyan"] == {
        "event": "progress",
        "stage": "researching",
        "message": "正在收集证据",
    }


def test_truncate_to_token_budget_marks_a_real_prefix():
    text = "这是一个较长的中文回答" * 20
    truncated = truncate_to_token_budget(text, 10)
    assert text.startswith(truncated)
    assert len(truncated) < len(text)
