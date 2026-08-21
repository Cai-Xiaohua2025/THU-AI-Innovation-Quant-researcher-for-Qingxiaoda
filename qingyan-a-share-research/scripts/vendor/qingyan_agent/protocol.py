"""OpenAI-compatible request and response helpers."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import urlsplit


@dataclass
class InputFile:
    filename: str = ""
    url: str = ""
    file_id: str = ""


@dataclass
class InputImage:
    url: str = ""
    detail: str = "auto"


@dataclass
class ParsedRequest:
    model: str
    stream: bool
    prompt: str
    max_tokens: int | None = None
    files: list[InputFile] = field(default_factory=list)
    images: list[InputImage] = field(default_factory=list)


def parse_request(payload: dict[str, Any]) -> ParsedRequest:
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty array")
    stream = payload.get("stream", False)
    if not isinstance(stream, bool):
        raise ValueError("stream must be a boolean")

    texts: list[str] = []
    files: list[InputFile] = []
    images: list[InputImage] = []
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
                elif part_type == "image_url":
                    image = part.get("image_url") or {}
                    if isinstance(image, str):
                        image = {"url": image}
                    if isinstance(image, dict):
                        url = str(image.get("url") or "").strip()
                        if url:
                            detail = str(image.get("detail") or "auto").strip().lower()
                            if detail not in {"auto", "low", "high"}:
                                detail = "auto"
                            images.append(InputImage(url=url, detail=detail))
    prompt = "\n".join(texts).strip()
    if not prompt and not files and not images:
        raise ValueError("messages must contain text, image_url, or a supported file part")

    max_tokens = payload.get("max_completion_tokens", payload.get("max_tokens"))
    if max_tokens is not None:
        if isinstance(max_tokens, bool):
            raise ValueError("max_tokens must be a positive integer")
        try:
            max_tokens = int(max_tokens)
        except (TypeError, ValueError) as exc:
            raise ValueError("max_tokens must be a positive integer") from exc
        if max_tokens < 1:
            raise ValueError("max_tokens must be a positive integer")

    model = str(payload.get("model") or "qingyan-liangce-agent").strip()
    if len(model) > 128:
        raise ValueError("model is too long")
    return ParsedRequest(
        model=model,
        stream=stream,
        prompt=prompt,
        max_tokens=max_tokens,
        files=files,
        images=images,
    )


def completion_response(
    model: str,
    prompt: str,
    content: str,
    attachments: list[dict[str, Any]] | None = None,
    finish_reason: str = "stop",
) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": finish_reason,
        }],
        "usage": estimate_usage(prompt, content),
        "x_soda": {"attachments": attachments or []},
    }


def append_artifact_links(content: str, attachments: list[dict[str, Any]] | None) -> str:
    """Expose generated artifacts in the message when a client hides x_soda metadata."""
    value = str(content or "").rstrip()
    labels = {
        "application/pdf": "下载 PDF 研报",
        "text/markdown": "查看 Markdown 研报",
        "image/png": "查看研究图表",
    }
    links = []
    for attachment in attachments or []:
        url = str(attachment.get("fileUrl") or "").strip()
        mime = str(attachment.get("mimeType") or "").strip().lower()
        label = labels.get(mime)
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        if not label or parsed.scheme not in {"http", "https"} or not parsed.netloc or url in value:
            continue
        links.append(f"- [{label}]({url})")
    if not links:
        return value
    section = "## 研究报告附件\n" + "\n".join(links)
    for marker in ("\n\n合规提示：", "\n\nCompliance note:"):
        position = value.rfind(marker)
        if position >= 0:
            return value[:position].rstrip() + "\n\n" + section + value[position:]
    return value + "\n\n" + section


def stream_response(
    model: str,
    prompt: str,
    content: str,
    attachments: list[dict[str, Any]] | None = None,
    finish_reason: str = "stop",
    *,
    chat_id: str | None = None,
    created: int | None = None,
) -> Iterable[str]:
    chat_id = chat_id or f"chatcmpl-{uuid.uuid4().hex}"
    created = created or int(time.time())
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
        "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
        "usage": estimate_usage(prompt, content),
        "x_soda": {"attachments": attachments or []},
    }
    yield "data: " + json.dumps(stop, ensure_ascii=False) + "\n\n"
    yield "data: [DONE]\n\n"


def progress_event(
    model: str,
    stage: str,
    message: str,
    *,
    chat_id: str,
    created: int,
    event: str = "progress",
) -> str:
    """Emit an additive extension while preserving OpenAI chunk shape."""
    payload = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
        "x_qingyan": {
            "event": event,
            "stage": stage,
            "message": message,
        },
    }
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def estimate_usage(prompt: str, content: str) -> dict[str, int]:
    prompt_tokens = estimate_tokens(prompt)
    completion_tokens = estimate_tokens(content)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def truncate_to_token_budget(content: str, max_tokens: int | None) -> str:
    """Apply a conservative character-based limit for OpenAI-compatible clients."""
    if max_tokens is None:
        return content
    if estimate_tokens(content) <= max_tokens:
        return content

    result: list[str] = []
    budget_units = max_tokens * 4
    used_units = 0
    for character in content:
        character_units = 4 if ord(character) > 127 else 1
        if used_units + character_units > budget_units:
            break
        result.append(character)
        used_units += character_units
    return "".join(result).rstrip()


def estimate_tokens(text: str) -> int:
    """Estimate tokens without requiring a model-specific tokenizer.

    CJK characters are conservatively counted as one token and ASCII text as
    roughly four characters per token. The number is for compatibility metadata,
    not billing.
    """
    value = text or ""
    units = sum(4 if ord(character) > 127 else 1 for character in value)
    return max(1, (units + 3) // 4)
