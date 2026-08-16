from __future__ import annotations

from dataclasses import replace
from io import BytesIO

from reportlab.pdfgen import canvas

from qingyan_agent.announcement_reader import AnnouncementAttachmentReader, extract_pdf_document
from qingyan_agent.config import Settings


class DownloadResponse:
    def __init__(
        self,
        content: bytes,
        content_type: str = "application/pdf",
        content_length: int | None = None,
    ) -> None:
        self.content = content
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(content) if content_length is None else content_length),
        }

    def iter_content(self, chunk_size=8192):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start:start + chunk_size]

    def close(self):
        return None


def make_settings(tmp_path, **kwargs) -> Settings:
    base = Settings(
        report_dir=tmp_path / "reports",
        cache_dir=tmp_path / "cache",
        request_timeout_sec=1,
        llm_base_url="",
        llm_api_key="",
        llm_model="",
    )
    return replace(base, **kwargs)


def make_pdf(*page_texts: str) -> bytes:
    output = BytesIO()
    document = canvas.Canvas(output)
    for text in page_texts:
        document.drawString(72, 760, text)
        document.showPage()
    document.save()
    return output.getvalue()


def test_extract_pdf_document_retains_page_labels_and_limits_chars():
    result = extract_pdf_document(
        make_pdf("First page announcement fact", "Second page risk detail"),
        max_pages=2,
        max_chars=45,
    )
    assert result["status"] == "ok"
    assert "[第1页]" in result["text"]
    assert result["pages_total"] == 2
    assert result["pages_processed"] == 2
    assert result["truncated"] is True
    assert result["text_chars"] <= 45


def test_reader_downloads_extracts_and_reuses_cache(monkeypatch, tmp_path):
    pdf = make_pdf("Board approved the capital reduction proposal")
    calls = []

    def fake_download(url, **kwargs):
        calls.append(url)
        return DownloadResponse(pdf), url

    monkeypatch.setattr("qingyan_agent.announcement_reader.download_response", fake_download)
    reader = AnnouncementAttachmentReader(make_settings(tmp_path))
    url = "https://static.cninfo.com.cn/finalpage/test.pdf"

    online = reader.read(url)
    cached = reader.read(url)

    assert online["status"] == "ok"
    assert "capital reduction" in online["text"]
    assert online["sha256"]
    assert online["data_mode"] == "online_extraction"
    assert cached["data_mode"] == "extraction_cache"
    assert calls == [url]


def test_reader_rejects_oversized_attachment_before_streaming(monkeypatch, tmp_path):
    pdf = make_pdf("announcement")
    monkeypatch.setattr(
        "qingyan_agent.announcement_reader.download_response",
        lambda url, **kwargs: (DownloadResponse(pdf, content_length=4096), url),
    )
    reader = AnnouncementAttachmentReader(make_settings(
        tmp_path,
        max_download_bytes=2048,
        announcement_attachment_max_bytes=2048,
    ))
    result = reader.read("https://static.cninfo.com.cn/finalpage/large.pdf")
    assert result["status"] == "failed"
    assert "exceeds limit" in result["message"]


def test_reader_rejects_html_disguised_as_pdf(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "qingyan_agent.announcement_reader.download_response",
        lambda url, **kwargs: (DownloadResponse(b"<html>blocked</html>", "text/html"), url),
    )
    reader = AnnouncementAttachmentReader(make_settings(tmp_path))
    result = reader.read("https://static.cninfo.com.cn/finalpage/not-a-pdf.pdf")
    assert result["status"] == "failed"
    assert "not a PDF" in result["message"]


def test_enrich_only_processes_configured_number_of_recent_rows(monkeypatch, tmp_path):
    reader = AnnouncementAttachmentReader(make_settings(
        tmp_path,
        announcement_attachment_max_files=2,
    ))
    calls = []
    monkeypatch.setattr(reader, "read", lambda url: calls.append(url) or {"status": "ok", "text": url})
    rows = reader.enrich([
        {"title": "one", "url": "https://example.com/1.pdf"},
        {"title": "two", "url": "https://example.com/2.pdf"},
        {"title": "three", "url": "https://example.com/3.pdf"},
    ])
    assert calls == ["https://example.com/1.pdf", "https://example.com/2.pdf"]
    assert rows[0]["attachment"]["status"] == "ok"
    assert rows[1]["attachment"]["status"] == "ok"
    assert "attachment" not in rows[2]
