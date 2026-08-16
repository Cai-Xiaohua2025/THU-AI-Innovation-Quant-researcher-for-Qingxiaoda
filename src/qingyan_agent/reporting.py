"""Report and chart generation."""

from __future__ import annotations

import html
import logging
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .config import Settings


LOGGER = logging.getLogger(__name__)


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
        stamp = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
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
        file_url = f"{base}/files/{quote(path.name)}" if base else path.resolve().as_uri()
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
            positions = list(range(len(dates)))
            tick_positions = sparse_tick_positions(len(dates), max_ticks=8)
            tick_labels = [str(dates[index] or "") for index in tick_positions]
            path = self._chart_path(title, "price")
            plt.figure(figsize=(9, 4.8))
            plt.plot(positions, closes, linewidth=2)
            plt.title(title)
            plt.xlabel("Date")
            plt.ylabel("Close")
            plt.xticks(tick_positions, tick_labels, rotation=25, ha="right", fontsize=8)
            plt.grid(axis="y", alpha=0.22, linewidth=0.7)
            plt.margins(x=0.015)
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
        suffix = uuid.uuid4().hex[:8]
        return self.settings.report_dir / f"{safe_name(title)}_{kind}_{time.strftime('%Y%m%d_%H%M%S')}_{suffix}.png"


def safe_name(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff-]+", "_", value or "", flags=re.UNICODE).strip("_")[:54]


def sparse_tick_positions(length: int, max_ticks: int = 8) -> list[int]:
    """Return evenly spaced tick positions including both chart endpoints."""
    if length <= 0 or max_ticks <= 0:
        return []
    if length <= max_ticks or max_ticks == 1:
        return list(range(length)) if max_ticks != 1 else [0]
    return sorted({round(index * (length - 1) / (max_ticks - 1)) for index in range(max_ticks)})


def configure_matplotlib_zh(plt) -> None:
    candidates = (
        "Noto Sans CJK SC",
        "Noto Sans CJK JP",
        "Source Han Sans SC",
        "Microsoft YaHei",
        "SimHei",
        "SimSun",
        "Arial Unicode MS",
    )
    try:
        from matplotlib import font_manager
        for path in (
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
        ):
            if Path(path).exists():
                font_manager.fontManager.addfont(path)
        installed = {item.name for item in font_manager.fontManager.ttflist}
        selected = next((font for font in candidates if font in installed), "DejaVu Sans")
        plt.rcParams["font.sans-serif"] = [selected, "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
    except Exception:
        plt.rcParams["axes.unicode_minus"] = False


def write_pdf(path: Path, markdown: str, chart_paths: list[Path]) -> bool:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.platypus import (
            HRFlowable,
            Image,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )

        font_name, bold_font_name = register_pdf_fonts(pdfmetrics)
        document_title = extract_document_title(markdown) or "清研量策研究报告"
        prepared_markdown = prepare_pdf_markdown(markdown)
        page_width, _ = A4
        left_margin = 18 * mm
        right_margin = 18 * mm
        usable_width = page_width - left_margin - right_margin
        doc = SimpleDocTemplate(
            str(path),
            pagesize=A4,
            leftMargin=left_margin,
            rightMargin=right_margin,
            topMargin=20 * mm,
            bottomMargin=18 * mm,
            title=document_title,
            author="清研量策",
            subject="A股公开信息研究报告",
        )
        styles = build_pdf_styles(getSampleStyleSheet(), font_name, bold_font_name, colors)
        story = markdown_story(
            prepared_markdown,
            styles,
            usable_width,
            colors,
            Paragraph,
            Spacer,
            Table,
            TableStyle,
            HRFlowable,
        )
        if chart_paths:
            story.append(PageBreak())
            story.append(Paragraph("图表附件", styles["Heading2CN"]))
            story.append(Spacer(1, 4 * mm))
        for chart in chart_paths:
            if not chart.exists():
                continue
            image = Image(str(chart))
            max_width, max_height = usable_width, 105 * mm
            scale = min(max_width / image.imageWidth, max_height / image.imageHeight, 1.0)
            image.drawWidth = image.imageWidth * scale
            image.drawHeight = image.imageHeight * scale
            image.hAlign = "CENTER"
            story.extend([image, Spacer(1, 7 * mm)])

        def decorate_page(canvas, document) -> None:
            canvas.saveState()
            canvas.setTitle(document_title)
            canvas.setAuthor("清研量策")
            canvas.setStrokeColor(colors.HexColor("#D9E2F1"))
            canvas.setLineWidth(0.5)
            canvas.line(left_margin, 13 * mm, page_width - right_margin, 13 * mm)
            canvas.setFont(font_name, 8)
            canvas.setFillColor(colors.HexColor("#6B7280"))
            canvas.drawString(left_margin, 8 * mm, "清研量策 · 公开信息研究辅助")
            canvas.drawRightString(page_width - right_margin, 8 * mm, f"第 {document.page} 页")
            canvas.restoreState()

        doc.build(story, onFirstPage=decorate_page, onLaterPages=decorate_page)
        return True
    except Exception as exc:
        LOGGER.exception("PDF rendering failed for %s: %s", path, exc)
        return False


def register_pdf_fonts(pdfmetrics) -> tuple[str, str]:
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont

    candidates = (
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/arphic/ukai.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simsun.ttc",
    )
    for candidate in candidates:
        if not Path(candidate).exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont("QingyanCN", candidate, subfontIndex=0))
            pdfmetrics.registerFontFamily(
                "QingyanCN",
                normal="QingyanCN",
                bold="QingyanCN",
                italic="QingyanCN",
                boldItalic="QingyanCN",
            )
            return "QingyanCN", "QingyanCN"
        except Exception as exc:
            LOGGER.warning("Unable to embed PDF font %s: %s", candidate, exc)
    fallback = "STSong-Light"
    pdfmetrics.registerFont(UnicodeCIDFont(fallback))
    pdfmetrics.registerFontFamily(
        fallback,
        normal=fallback,
        bold=fallback,
        italic=fallback,
        boldItalic=fallback,
    )
    return fallback, fallback


def build_pdf_styles(sample_styles, font_name: str, bold_font_name: str, colors) -> dict[str, object]:
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
    from reportlab.lib.styles import ParagraphStyle

    return {
        "TitleCN": ParagraphStyle(
            "TitleCN",
            parent=sample_styles["Title"],
            fontName=bold_font_name,
            fontSize=20,
            leading=28,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#102A43"),
            spaceAfter=12,
        ),
        "Heading2CN": ParagraphStyle(
            "Heading2CN",
            parent=sample_styles["Heading2"],
            fontName=bold_font_name,
            fontSize=15,
            leading=21,
            textColor=colors.HexColor("#135E96"),
            spaceBefore=12,
            spaceAfter=7,
            keepWithNext=True,
        ),
        "Heading3CN": ParagraphStyle(
            "Heading3CN",
            parent=sample_styles["Heading3"],
            fontName=bold_font_name,
            fontSize=12,
            leading=18,
            textColor=colors.HexColor("#243B53"),
            spaceBefore=8,
            spaceAfter=5,
            keepWithNext=True,
        ),
        "BodyCN": ParagraphStyle(
            "BodyCN",
            parent=sample_styles["BodyText"],
            fontName=font_name,
            fontSize=10.2,
            leading=17,
            alignment=TA_JUSTIFY,
            textColor=colors.HexColor("#1F2933"),
            spaceAfter=5,
            wordWrap="CJK",
        ),
        "BulletCN": ParagraphStyle(
            "BulletCN",
            parent=sample_styles["BodyText"],
            fontName=font_name,
            fontSize=10,
            leading=16,
            leftIndent=14,
            firstLineIndent=-8,
            bulletIndent=4,
            textColor=colors.HexColor("#1F2933"),
            spaceAfter=4,
            wordWrap="CJK",
        ),
        "QuoteCN": ParagraphStyle(
            "QuoteCN",
            parent=sample_styles["BodyText"],
            fontName=font_name,
            fontSize=9.8,
            leading=16,
            leftIndent=12,
            rightIndent=8,
            borderWidth=0,
            borderPadding=7,
            backColor=colors.HexColor("#F1F5F9"),
            textColor=colors.HexColor("#475569"),
            spaceBefore=4,
            spaceAfter=7,
            wordWrap="CJK",
        ),
        "CodeCN": ParagraphStyle(
            "CodeCN",
            parent=sample_styles["Code"],
            fontName=font_name,
            fontSize=8.5,
            leading=13,
            leftIndent=7,
            rightIndent=7,
            borderPadding=7,
            backColor=colors.HexColor("#F8FAFC"),
            textColor=colors.HexColor("#334155"),
            spaceBefore=4,
            spaceAfter=7,
            wordWrap="CJK",
        ),
        "TableHeaderCN": ParagraphStyle(
            "TableHeaderCN",
            parent=sample_styles["BodyText"],
            fontName=bold_font_name,
            fontSize=8.8,
            leading=13,
            alignment=TA_LEFT,
            textColor=colors.white,
            wordWrap="CJK",
        ),
        "TableCellCN": ParagraphStyle(
            "TableCellCN",
            parent=sample_styles["BodyText"],
            fontName=font_name,
            fontSize=8.5,
            leading=13,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#1F2933"),
            wordWrap="CJK",
        ),
    }


def markdown_story(markdown: str, styles: dict, usable_width: float, colors, Paragraph, Spacer, Table, TableStyle, HRFlowable) -> list:
    lines = markdown.splitlines()
    story: list = []
    index = 0
    in_code = False
    code_lines: list[str] = []
    while index < len(lines):
        raw = lines[index].rstrip()
        stripped = raw.strip()
        if stripped.startswith("```"):
            if in_code:
                story.append(Paragraph("<br/>".join(code_line_html(line) for line in code_lines), styles["CodeCN"]))
                code_lines = []
                in_code = False
            else:
                in_code = True
            index += 1
            continue
        if in_code:
            code_lines.append(raw)
            index += 1
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            table_lines = []
            while index < len(lines) and lines[index].strip().startswith("|") and lines[index].strip().endswith("|"):
                table_lines.append(lines[index].strip())
                index += 1
            table = markdown_table(table_lines, styles, usable_width, colors, Paragraph, Table, TableStyle)
            if table is not None:
                story.extend([table, Spacer(1, 6)])
            continue
        if not stripped:
            story.append(Spacer(1, 4))
        elif re.fullmatch(r"-{3,}", stripped):
            story.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#CBD5E1"), spaceBefore=5, spaceAfter=7))
        elif raw.startswith("# "):
            story.append(Paragraph(inline_markdown(raw[2:].strip()), styles["TitleCN"]))
        elif raw.startswith("## "):
            story.append(Paragraph(inline_markdown(raw[3:].strip()), styles["Heading2CN"]))
        elif raw.startswith("### "):
            story.append(Paragraph(inline_markdown(raw[4:].strip()), styles["Heading3CN"]))
        elif stripped.startswith(">"):
            story.append(Paragraph(inline_markdown(stripped.lstrip("> ")), styles["QuoteCN"]))
        elif re.match(r"^\s*[-*]\s+", raw):
            value = re.sub(r"^\s*[-*]\s+", "", raw)
            story.append(Paragraph(inline_markdown(value), styles["BulletCN"], bulletText="•"))
        elif re.match(r"^\s*\d+[.)、]\s*", raw):
            match = re.match(r"^\s*(\d+)[.)、]\s*(.*)", raw)
            number, value = match.groups() if match else ("", stripped)
            story.append(Paragraph(inline_markdown(value), styles["BulletCN"], bulletText=f"{number}."))
        else:
            story.append(Paragraph(inline_markdown(stripped), styles["BodyCN"]))
        index += 1
    if code_lines:
        story.append(Paragraph("<br/>".join(code_line_html(line) for line in code_lines), styles["CodeCN"]))
    return story


def markdown_table(lines: list[str], styles: dict, usable_width: float, colors, Paragraph, Table, TableStyle):
    rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines]
    rows = [row for row in rows if not all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in row)]
    if not rows or not rows[0]:
        return None
    column_count = max(len(row) for row in rows)
    normalized = [row + [""] * (column_count - len(row)) for row in rows]
    rendered = []
    for row_index, row in enumerate(normalized):
        style = styles["TableHeaderCN"] if row_index == 0 else styles["TableCellCN"]
        rendered.append([Paragraph(inline_markdown(cell), style) for cell in row])
    table = Table(rendered, colWidths=[usable_width / column_count] * column_count, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#135E96")),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def inline_markdown(value: str) -> str:
    escaped = html.escape(value or "")
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<font color='#0F766E'>\1</font>", escaped)
    escaped = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"<link href='\2' color='#135E96'>\1</link>", escaped)
    return escaped


def code_line_html(value: str) -> str:
    return html.escape(value or "").replace(" ", "&nbsp;") or "&nbsp;"


def prepare_pdf_markdown(markdown: str) -> str:
    """Remove internal JSON evidence while preserving the human-readable report."""
    value = markdown or ""
    return re.sub(
        r"\n## 结构化元数据\s*\n```json\s*\n.*?\n```\s*\n",
        "\n",
        value,
        flags=re.DOTALL,
    ).strip()


def extract_document_title(markdown: str) -> str:
    match = re.search(r"^#\s+(.+)$", markdown or "", flags=re.MULTILINE)
    return match.group(1).strip() if match else ""
