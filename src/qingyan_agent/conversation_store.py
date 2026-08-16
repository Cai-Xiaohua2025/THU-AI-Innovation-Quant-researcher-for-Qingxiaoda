"""Local, privacy-conscious persistence for successful chat conversations."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .config import Settings
from .protocol import ParsedRequest


SCHEMA_VERSION = 1


class ConversationStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if self.settings.save_conversations:
            self.ensure_ready()

    def ensure_ready(self) -> bool:
        try:
            self.settings.conversation_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.settings.conversation_dir, 0o700)
            return self.settings.conversation_dir.is_dir() and os.access(
                self.settings.conversation_dir,
                os.W_OK,
            )
        except OSError:
            return False

    def save(
        self,
        *,
        request_id: str,
        parsed: ParsedRequest,
        response_text: str,
        finish_reason: str,
        title: str,
        report_enabled: bool,
        attachments: list[dict[str, Any]],
        processing_ms: float | None = None,
    ) -> Path | None:
        if not self.settings.save_conversations:
            return None
        now = datetime.now().astimezone()
        day_dir = self.settings.conversation_dir / now.strftime("%Y-%m-%d")
        try:
            day_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(day_dir, 0o700)
            prompt, prompt_truncated = bounded_text(
                parsed.prompt,
                self.settings.conversation_max_chars,
            )
            answer, answer_truncated = bounded_text(
                response_text,
                self.settings.conversation_max_chars,
            )
            record = {
                "schema_version": SCHEMA_VERSION,
                "conversation_id": request_id,
                "created_at": now.isoformat(timespec="milliseconds"),
                "request": {
                    "model": parsed.model,
                    "stream": parsed.stream,
                    "max_tokens": parsed.max_tokens,
                    "prompt": prompt,
                    "prompt_truncated_for_storage": prompt_truncated,
                    "files": [{
                        "filename": item.filename,
                        "url": sanitize_url(item.url),
                        "has_file_id": bool(item.file_id),
                    } for item in parsed.files],
                    "images": [{
                        "url": sanitize_url(item.url),
                        "detail": item.detail,
                    } for item in parsed.images],
                },
                "response": {
                    "title": title,
                    "content": answer,
                    "content_truncated_for_storage": answer_truncated,
                    "finish_reason": finish_reason,
                    "report_enabled": report_enabled,
                    "attachments": [{
                        "file_name": item.get("fileName"),
                        "file_type": item.get("fileType"),
                        "mime_type": item.get("mimeType"),
                        "file_size": item.get("fileSize"),
                    } for item in attachments],
                },
                "processing_ms": round(processing_ms, 1) if processing_ms is not None else None,
                "storage": {
                    "authorization_header_saved": False,
                    "configured_api_key_saved": False,
                    "url_query_parameters_saved": False,
                },
            }
            safe_id = safe_identifier(request_id)
            filename = f"{now.strftime('%H%M%S_%f')}_{safe_id}.json"
            path = day_dir / filename
            temporary = day_dir / f".{filename}.{uuid.uuid4().hex}.tmp"
            temporary.write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
            os.chmod(path, 0o600)
            return path
        except Exception:
            return None


def bounded_text(value: str, limit: int) -> tuple[str, bool]:
    text = str(value or "")
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def sanitize_url(value: str) -> str:
    """Drop credentials, query strings, and fragments before local persistence."""
    url = str(value or "").strip()
    if not url:
        return ""
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ""
        host = parsed.hostname
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    except Exception:
        return ""


def safe_identifier(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("._-")[:80]
    return safe or uuid.uuid4().hex
