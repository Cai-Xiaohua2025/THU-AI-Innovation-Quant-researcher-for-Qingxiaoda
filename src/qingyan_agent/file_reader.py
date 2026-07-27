"""Qingxiaoda URL file reader."""

from __future__ import annotations

import mimetypes
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

import requests

from .config import Settings
from .protocol import InputFile


@dataclass
class FileSummary:
    filename: str
    status: str
    mime_type: str = ""
    text: str = ""
    source_url: str = ""


class FileReader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def read_all(self, files: list[InputFile]) -> list[FileSummary]:
        return [self.read_one(item) for item in files]

    def read_one(self, item: InputFile) -> FileSummary:
        filename = item.filename or "uploaded_file"
        if not item.url:
            return FileSummary(filename=filename, status="file_id mode is not enabled; please use file.url")
        try:
            response = requests.get(item.url, timeout=self.settings.request_timeout_sec, stream=True)
            response.raise_for_status()
            content = read_limited(response, self.settings.max_download_bytes)
            mime = response.headers.get("Content-Type", "").split(";")[0].strip()
            mime = mime or mimetypes.guess_type(filename)[0] or "application/octet-stream"
            return FileSummary(filename=filename, status="ok", mime_type=mime, text=extract_text(content, filename, mime), source_url=item.url)
        except Exception as exc:
            return FileSummary(filename=filename, status=f"read failed: {str(exc)[:180]}", source_url=item.url)


def read_limited(response: requests.Response, limit: int) -> bytes:
    buffer = bytearray()
    for chunk in response.iter_content(chunk_size=8192):
        if not chunk:
            continue
        buffer.extend(chunk)
        if len(buffer) > limit:
            raise ValueError(f"file exceeds limit: {limit} bytes")
    return bytes(buffer)


def extract_text(content: bytes, filename: str, mime: str) -> str:
    suffix = Path(filename).suffix.lower()
    if mime.startswith("text/") or suffix in {".txt", ".md", ".csv", ".json"}:
        return decode_text(content)[:20000]
    if suffix == ".pdf" or mime == "application/pdf":
        return extract_pdf(content)
    if suffix == ".docx":
        return extract_docx(content)
    if suffix in {".xlsx", ".xls"}:
        return extract_excel(content)
    return f"File received, but text extraction is not available for {mime or suffix}."


def decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return content.decode(encoding, errors="replace")
        except Exception:
            continue
    return content.decode("utf-8", errors="replace")


def extract_pdf(content: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(content))
        pages = [(page.extract_text() or "") for page in reader.pages[:15]]
        text = "\n".join(pages).strip()
        return text[:20000] if text else "PDF was read, but no selectable text was extracted."
    except Exception as exc:
        return f"PDF extraction failed: {str(exc)[:160]}"


def extract_docx(content: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml)
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        return "\n".join(node.text or "" for node in root.findall(".//w:t", namespace))[:20000]
    except Exception as exc:
        return f"DOCX extraction failed: {str(exc)[:160]}"


def extract_excel(content: bytes) -> str:
    try:
        import pandas as pd
        sheets = pd.read_excel(BytesIO(content), sheet_name=None, nrows=120)
        chunks = []
        for sheet_name, frame in list(sheets.items())[:6]:
            chunks.append(f"## Sheet: {sheet_name}\n{frame.to_csv(index=False)}")
        return "\n\n".join(chunks)[:20000]
    except Exception as exc:
        return f"Excel extraction failed: {str(exc)[:160]}"
