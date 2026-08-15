"""Qingxiaoda URL file reader."""

from __future__ import annotations

import mimetypes
import ipaddress
import socket
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

import requests

from .config import Settings
from .protocol import InputFile


DOWNLOAD_HEADERS = {"User-Agent": "Qingyan-Liangce-Agent/0.3 (+file-ingestion)"}
MAX_REDIRECTS = 3
MAX_EXTRACTED_ARCHIVE_BYTES = 80 * 1024 * 1024


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
        filename = Path(item.filename or "uploaded_file").name or "uploaded_file"
        if not item.url:
            return FileSummary(filename=filename, status="file_id mode is not enabled; please use file.url")
        try:
            response, final_url = download_response(
                item.url,
                timeout=self.settings.request_timeout_sec,
                allow_private=self.settings.allow_private_file_urls,
            )
            try:
                declared_size = response.headers.get("Content-Length", "").strip()
                if declared_size and int(declared_size) > self.settings.max_download_bytes:
                    raise ValueError(f"file exceeds limit: {self.settings.max_download_bytes} bytes")
                content = read_limited(response, self.settings.max_download_bytes)
                mime = response.headers.get("Content-Type", "").split(";")[0].strip()
            finally:
                response.close()
            if filename == "uploaded_file":
                filename = Path(urlsplit(final_url).path).name or filename
            mime = mime or mimetypes.guess_type(filename)[0] or "application/octet-stream"
            return FileSummary(
                filename=filename,
                status="ok",
                mime_type=mime,
                text=extract_text(content, filename, mime),
                source_url=final_url,
            )
        except Exception as exc:
            return FileSummary(filename=filename, status=f"read failed: {str(exc)[:180]}", source_url=item.url)


def download_response(url: str, *, timeout: int, allow_private: bool) -> tuple[requests.Response, str]:
    current_url = url
    for redirect_count in range(MAX_REDIRECTS + 1):
        validate_remote_url(current_url, allow_private=allow_private)
        response = requests.get(
            current_url,
            headers=DOWNLOAD_HEADERS,
            timeout=(min(timeout, 10), timeout),
            stream=True,
            allow_redirects=False,
        )
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location", "").strip()
            response.close()
            if not location:
                raise ValueError("file URL redirect is missing Location")
            if redirect_count >= MAX_REDIRECTS:
                raise ValueError("file URL has too many redirects")
            current_url = urljoin(current_url, location)
            continue
        response.raise_for_status()
        return response, current_url
    raise ValueError("file URL has too many redirects")


def validate_remote_url(url: str, *, allow_private: bool = False) -> None:
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("file URL must use http or https")
    if not parsed.hostname:
        raise ValueError("file URL must include a host")
    if parsed.username or parsed.password:
        raise ValueError("file URL must not contain credentials")
    if allow_private:
        return
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise ValueError("file URL host could not be resolved") from exc
    if not addresses:
        raise ValueError("file URL host could not be resolved")
    for value in addresses:
        address = ipaddress.ip_address(value.split("%", 1)[0])
        if not address.is_global:
            raise ValueError("private, loopback, link-local, and reserved file URLs are blocked")


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
            validate_archive_size(archive)
            xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml)
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        return "\n".join(node.text or "" for node in root.findall(".//w:t", namespace))[:20000]
    except Exception as exc:
        return f"DOCX extraction failed: {str(exc)[:160]}"


def extract_excel(content: bytes) -> str:
    try:
        if zipfile.is_zipfile(BytesIO(content)):
            with zipfile.ZipFile(BytesIO(content)) as archive:
                validate_archive_size(archive)
        import pandas as pd
        sheets = pd.read_excel(BytesIO(content), sheet_name=None, nrows=120)
        chunks = []
        for sheet_name, frame in list(sheets.items())[:6]:
            chunks.append(f"## Sheet: {sheet_name}\n{frame.to_csv(index=False)}")
        return "\n\n".join(chunks)[:20000]
    except Exception as exc:
        return f"Excel extraction failed: {str(exc)[:160]}"


def validate_archive_size(archive: zipfile.ZipFile) -> None:
    expanded_size = sum(item.file_size for item in archive.infolist())
    if expanded_size > MAX_EXTRACTED_ARCHIVE_BYTES:
        raise ValueError(f"expanded archive exceeds limit: {MAX_EXTRACTED_ARCHIVE_BYTES} bytes")
