"""OpenAI-compatible request and response helpers."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class InputFile:
    filename: str = ""
    url: str = ""
    file_id: str = ""


@dataclass
class ParsedRequest:
    model: str
    stream: bool
    prompt: str
    files: list[InputFile] = field(default_factory=list)


def parse_request(payload: dict[str, Any]) -> ParsedRequest:
    messages = payload.get("messages") or []
    texts: list[str] = []
    files: list[InputFile] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        content = message.get("content")
        if isinstance(content, str):
            if content.strip():
                texts.append(f"{role}: {content.strip()}")
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                part_type = part.get("type")
                if part_type == "text":
                    text = str(part.get("text") or "").strip()
                    if text:
                        texts.append(f"{role}: {text}")
                elif part_type == "file":
                    f = part.get("file") or {}
                    files.append(InputFile(
                        filename=str(f.get("filename") or ""),
                        url=str(f.get("url") or ""),
                        file_id=str(f.get("file_id") or ""),
                    ))
    return ParsedRequest(
        model=str(payload.get("model") or "qingyan-liangce-agent"),
        stream=bool(payload.get("stream", False)),
        prompt="\n".join(texts).strip(),
        files=files,
    )


def completion_response(model: str, content: str, attachments: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": estimate_usage(content),
        "x_soda": {"attachments": attachments},
    }


def stream_response(model: str, content: str, attachments: list[dict[str, Any]]) -> Iterable[str]:
    chat_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    yield "data: " + json.dumps({
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
    }, ensure_ascii=False) + "\n\n"
    for start in range(0, len(content), 200):
        yield "data: " + json.dumps({
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {"content": content[start:start + 200]}, "finish_reason": None}],
        }, ensure_ascii=False) + "\n\n"
    stop = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "usage": estimate_usage(content),
        "x_soda": {"attachments": attachments},
    }
    yield "data: " + json.dumps(stop, ensure_ascii=False) + "\n\n"
    yield "data: [DONE]\n\n"


def estimate_usage(content: str) -> dict[str, int]:
    token_estimate = max(1, len(content or "") // 4)
    return {"prompt_tokens": token_estimate, "completion_tokens": token_estimate, "total_tokens": token_estimate * 2}
