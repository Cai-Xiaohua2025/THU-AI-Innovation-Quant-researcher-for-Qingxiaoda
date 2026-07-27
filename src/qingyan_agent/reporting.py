"""Report and chart generation."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Settings


@dataclass
class ReportArtifacts:
    markdown_path: Path
    pdf_path: Path | None
    chart_paths: list[Path]
    attachments: list[dict]


class ReportService:
    def __init__(self, settings: Settings, request_base_url: str = "") -> None:
        self.settings = settings
        self.request_base_url = request_base_url.rstrip("/")

    def create(self, title: str, markdown: str, charts: list[Path] | None = None) -> ReportArtifacts:
        self.settings.report_dir.mkdir(parents=True, exist_ok=True)
        stem = safe_name(title) or "qingyan_research_report"
        stamp = time.strftime("%Y%m%d_%H%M%S")
        md_path = self.settings.report_dir / f"{stem}_{stamp}.md"
        pdf_path = self.settings.report_dir / f"{stem}_{stamp}.pdf"
        chart_paths = charts or []
        md_path.write_text(markdown, encoding="utf-8")
        pdf_ok = write_pdf(pdf_path, markdown, chart_paths)
        attachments = [self.attachment(md_path, "text", "text/markdown")]
        for chart in chart_paths:
            attachments.append(self.attachment(chart, "image", "image/png"))
        if pdf_ok:
            attachments.insert(0, self.attachment(pdf_path, "pdf", "application/pdf"))
        return ReportArtifacts(md_path, pdf_path if pdf_ok else None, chart_paths, attachments)

    def attachment(self, path: Path, file_type: str, mime_type: str) -> dict:
        base = self.settings.public_base_url or self.request_base_url
        file_url = f"{base}/files/{path.name}" if base else path.resolve().as_uri()
        return {
            "fileUrl": file_url,
            "fileName": path.name,
            "fileType": file_type,
            "mimeType": mime_type,
            "fileSize": path.stat().st_size,
        }


class ChartService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def price_chart(self, title: str, klines: list[dict]) -> Path | None:
        if len(klines) < 5:
            return None
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            configure_matplotlib_zh(plt)
            dates = [row.get("date") for row in klines[-90:]]
            closes = [row.get("close") for row in klines[-90:]]
            path = self._chart_path(title, "price")
            plt.figure(figsize=(9, 4.8))
            plt.plot(dates, closes, linewidth=2)
            plt.title(title)
            plt.xlabel("Date")
            plt.ylabel("Close")
            plt.xticks(rotation=35, fontsize=7)
            plt.tight_layout()
            plt.savefig(path, dpi=160)
            plt.close()
            return path
        except Exception:
            return None

    def screening_chart(self, title: str, rows: list[dict]) -> Path | None:
        if not rows:
            return None
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            configure_matplotlib_zh(plt)
            top = rows[:8]
            names = [item.get("name") or item.get("symbol") for item in top]
            scores = [item.get("score", 0) for item in top]
            path = self._chart_path(title, "screening")
            plt.figure(figsize=(9, 4.8))
            plt.bar(names, scores)
            plt.title(title)
            plt.ylabel("Research Score")
            plt.xticks(rotation=30, ha="right")
            plt.tight_layout()
            plt.savefig(path, dpi=160)
            plt.close()
            return path
        except Exception:
            return None

    def backtest_chart(self, title: str, equity_curve: list[dict]) -> Path | None:
        if len(equity_curve) < 3:
            return None
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            configure_matplotlib_zh(plt)
            path = self._chart_path(title, "backtest")
            plt.figure(figsize=(9, 4.8))
            plt.plot([row.get("date") for row in equity_curve], [row.get("equity") for row in equity_curve], linewidth=2)
            plt.title(title)
            plt.ylabel("Equity")
            plt.xticks(rotation=35, fontsize=7)
            plt.tight_layout()
            plt.savefig(path, dpi=160)
            plt.close()
            return path
        except Exception:
            return None

    def _chart_path(self, title: str, kind: str) -> Path:
        self.settings.report_dir.mkdir(parents=True, exist_ok=True)
        return self.settings.report_dir / f"{safe_name(title)}_{kind}_{time.strftime('%Y%m%d_%H%M%S')}.png"


def safe_name(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff-]+", "_", value or "", flags=re.UNICODE).strip("_")[:54]


def configure_matplotlib_zh(plt) -> None:
    for font in ("Microsoft YaHei", "SimHei", "SimSun", "Arial Unicode MS"):
        try:
            plt.rcParams["font.sans-serif"] = [font, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            return
        except Exception:
            pass


def write_pdf(path: Path, markdown: str, chart_paths: list[Path]) -> bool:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
        font_name = "Helvetica"
        for candidate in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simsun.ttc"):
            if Path(candidate).exists():
                try:
                    pdfmetrics.registerFont(TTFont("QingyanFont", candidate))
                    font_name = "QingyanFont"
                    break
                except Exception:
                    pass
        page_width, page_height = A4
        c = canvas.Canvas(str(path), pagesize=A4)
        c.setFont(font_name, 10)
        y = page_height - 45
        for raw_line in markdown.splitlines():
            line = raw_line.replace("#", "").strip()
            if not line:
                y -= 8
                continue
            for chunk in wrap(line, 48):
                c.drawString(42, y, chunk)
                y -= 15
                if y < 70:
                    c.showPage()
                    c.setFont(font_name, 10)
                    y = page_height - 45
        for chart in chart_paths:
            if y < 340:
                c.showPage()
                y = page_height - 45
            c.drawImage(ImageReader(str(chart)), 42, y - 280, width=500, height=260, preserveAspectRatio=True, mask="auto")
            y -= 300
        c.save()
        return True
    except Exception:
        return False


def wrap(line: str, length: int) -> list[str]:
    if len(line) <= length:
        return [line]
    return [line[i:i + length] for i in range(0, len(line), length)]
