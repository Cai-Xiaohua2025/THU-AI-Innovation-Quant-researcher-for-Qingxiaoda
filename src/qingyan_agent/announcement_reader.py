"""Bounded download, extraction, and caching for public announcement PDFs."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .config import Settings
from .file_reader import download_response, read_limited


EXTRACTOR_VERSION = 1
PDF_MIME_TYPES = {
    "application/pdf",
    "application/octet-stream",
    "binary/octet-stream",
    "",
}


class AnnouncementAttachmentReader:
    """Attach bounded, page-labelled PDF text to the newest announcements."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def enrich(self, announcements: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = [dict(item) for item in announcements]
        remaining = self.settings.announcement_attachment_max_files
        if remaining <= 0:
            return rows
        for row in rows:
            url = str(row.get("url") or "").strip()
            if not url or remaining <= 0:
                continue
            row["attachment"] = self.read(url)
            remaining -= 1
        return rows

    def read(self, url: str) -> dict[str, Any]:
        cached = self._read_cache(url)
        if cached is not None:
            cached["data_mode"] = "extraction_cache"
            return cached

        limit = min(
            self.settings.max_download_bytes,
            self.settings.announcement_attachment_max_bytes,
        )
        try:
            response, final_url = download_response(
                url,
                timeout=self.settings.request_timeout_sec,
                allow_private=self.settings.allow_private_file_urls,
            )
            try:
                declared_size = response.headers.get("Content-Length", "").strip()
                if declared_size and int(declared_size) > limit:
                    raise ValueError(f"announcement attachment exceeds limit: {limit} bytes")
                content = read_limited(response, limit)
                mime = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            finally:
                response.close()

            if mime not in PDF_MIME_TYPES:
                raise ValueError(f"announcement attachment is not a PDF: {mime}")
            if not content.startswith(b"%PDF-"):
                raise ValueError("announcement attachment does not contain a valid PDF signature")

            result = extract_pdf_document(
                content,
                max_pages=self.settings.announcement_attachment_max_pages,
                max_chars=self.settings.announcement_attachment_max_chars,
            )
            result.update({
                "source_url": final_url,
                "filename": Path(urlsplit(final_url).path).name or "announcement.pdf",
                "mime_type": "application/pdf",
                "byte_size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "fetched_at": now_iso(),
                "extractor_version": EXTRACTOR_VERSION,
                "max_pages": self.settings.announcement_attachment_max_pages,
                "max_chars": self.settings.announcement_attachment_max_chars,
                "data_mode": "online_extraction",
            })
            if result["status"] in {"ok", "no_selectable_text"}:
                self._write_cache(url, result)
            return result
        except Exception as exc:
            return {
                "status": "failed",
                "message": f"attachment extraction failed: {exc.__class__.__name__}: {str(exc)[:180]}",
                "source_url": url,
                "extractor_version": EXTRACTOR_VERSION,
                "data_mode": "extraction_failed",
            }

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        return self.settings.cache_dir / f"announcement_attachment_{digest}.json"

    def _read_cache(self, url: str) -> dict[str, Any] | None:
        path = self._cache_path(url)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                return None
            if value.get("source_url") != url:
                return None
            if value.get("extractor_version") != EXTRACTOR_VERSION:
                return None
            if value.get("max_pages") != self.settings.announcement_attachment_max_pages:
                return None
            if value.get("max_chars") != self.settings.announcement_attachment_max_chars:
                return None
            if value.get("status") not in {"ok", "no_selectable_text"}:
                return None
            return value
        except Exception:
            return None

    def _write_cache(self, url: str, value: dict[str, Any]) -> None:
        try:
            self.settings.cache_dir.mkdir(parents=True, exist_ok=True)
            payload = dict(value, source_url=url)
            self._cache_path(url).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass


def extract_pdf_document(content: bytes, *, max_pages: int, max_chars: int) -> dict[str, Any]:
    """Extract selectable PDF text while retaining one-based page labels."""
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    pages_total = len(reader.pages)
    pages_processed = min(pages_total, max_pages)
    segments: list[str] = []
    pages_with_text = 0
    page_errors = 0
    used_chars = 0
    truncated = pages_total > max_pages

    for index, page in enumerate(reader.pages[:max_pages], start=1):
        try:
            page_text = clean_pdf_text(page.extract_text() or "")
        except Exception:
            page_errors += 1
            continue
        if not page_text:
            continue
        pages_with_text += 1
        separator = "\n\n" if segments else ""
        label = f"[第{index}页]\n"
        remaining = max_chars - used_chars - len(separator)
        if remaining <= len(label):
            truncated = True
            break
        available = remaining - len(label)
        excerpt = page_text[:available]
        if len(excerpt) < len(page_text):
            truncated = True
        segment = label + excerpt
        segments.append(segment)
        used_chars += len(separator) + len(segment)
        if truncated and len(excerpt) < len(page_text):
            break

    text = "\n\n".join(segments).strip()
    if not text:
        return {
            "status": "no_selectable_text",
            "message": "PDF 已读取，但未提取到可选择文本；可能是扫描件，需要 OCR。",
            "text": "",
            "text_chars": 0,
            "pages_total": pages_total,
            "pages_processed": pages_processed,
            "pages_with_text": 0,
            "page_errors": page_errors,
            "truncated": truncated,
        }
    return {
        "status": "ok",
        "message": "公告 PDF 正文已提取，页码标签来自 PDF 页面顺序。",
        "text": text,
        "text_chars": len(text),
        "pages_total": pages_total,
        "pages_processed": pages_processed,
        "pages_with_text": pages_with_text,
        "page_errors": page_errors,
        "truncated": truncated,
    }


def clean_pdf_text(value: str) -> str:
    text = str(value or "").replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(character for character in text if character in "\n\t" or ord(character) >= 32)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
