"""Report and chart generation."""

from __future__ import annotations

import html
import logging
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from .artifacts import ArtifactRegistry
from .config import Settings


LOGGER = logging.getLogger(__name__)


@dataclass
class ReportArtifacts:
    markdown_path: Path
    pdf_path: Path | None
    chart_paths: list[Path]
    attachments: list[dict]


class ReportService:
    def __init__(
        self,
        settings: Settings,
        request_base_url: str = "",
        artifact_registry: ArtifactRegistry | None = None,
    ) -> None:
        self.settings = settings
        self.request_base_url = request_base_url.rstrip("/")
        self.artifact_registry = artifact_registry or ArtifactRegistry(settings)

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
        record = self.artifact_registry.register(path, file_type, mime_type)
        if base:
            return self.artifact_registry.attachment(record, base)
        # CLI-only fallback keeps the historic local URI behavior while still
        # creating an index record. HTTP deployments never expose this URI.
        attachment = self.artifact_registry.attachment(record, "")
        attachment["fileUrl"] = path.resolve().as_uri()
        return attachment


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
            rows = [row for row in klines[-120:] if row.get("close") is not None]
            dates = [row.get("date") for row in rows]
            closes = [float(row.get("close")) for row in rows]
            volumes = [float(row.get("volume") or 0) for row in rows]
            positions = list(range(len(dates)))
            tick_positions = sparse_tick_positions(len(dates), max_ticks=8)
            tick_labels = [str(dates[index] or "") for index in tick_positions]
            path = self._chart_path(title, "price")
            figure, (price_axis, volume_axis) = plt.subplots(
                2,
                1,
                figsize=(10.5, 7.8),
                sharex=True,
                gridspec_kw={"height_ratios": [3.2, 1], "hspace": 0.05},
            )
            figure.patch.set_facecolor("#FFFFFF")

            price_axis.plot(positions, closes, linewidth=2.1, color="#154C79", label="收盘价", zorder=4)
            moving_average_specs = (
                (5, "MA5", "#D97706", 1.25),
                (20, "MA20", "#7C3AED", 1.45),
                (60, "MA60", "#0F766E", 1.55),
            )
            for window, label, color, width in moving_average_specs:
                series = moving_average(closes, window)
                if any(value is not None for value in series):
                    price_axis.plot(positions, series, linewidth=width, color=color, label=label, alpha=0.95)

            price_axis.scatter([positions[-1]], [closes[-1]], s=28, color="#154C79", zorder=5)
            price_axis.annotate(
                f"{closes[-1]:.2f}",
                (positions[-1], closes[-1]),
                xytext=(-8, 10),
                textcoords="offset points",
                ha="right",
                fontsize=8.5,
                color="#154C79",
            )
            adjustment = str(rows[-1].get("price_adjustment") or "复权口径待核验")
            price_axis.set_ylabel(f"{adjustment}价格")
            price_axis.grid(axis="y", alpha=0.18, linewidth=0.7, color="#64748B")
            price_axis.margins(x=0.012)
            price_axis.legend(loc="upper left", ncol=4, frameon=False, fontsize=8.5)
            price_axis.spines[["top", "right"]].set_visible(False)
            price_axis.spines[["left", "bottom"]].set_color("#CBD5E1")

            bar_colors = ["#C2413B"]
            for index in range(1, len(closes)):
                bar_colors.append("#C2413B" if closes[index] >= closes[index - 1] else "#168B65")
            volume_axis.bar(positions, volumes, width=0.72, color=bar_colors, alpha=0.78)
            if len(volumes) >= 20:
                volume_axis.plot(positions, moving_average(volumes, 20), color="#475569", linewidth=1.1, label="20日均量")
                volume_axis.legend(loc="upper left", frameon=False, fontsize=8)
            volume_axis.set_ylabel("成交量")
            volume_axis.grid(axis="y", alpha=0.15, linewidth=0.6, color="#64748B")
            volume_axis.spines[["top", "right"]].set_visible(False)
            volume_axis.spines[["left", "bottom"]].set_color("#CBD5E1")
            volume_axis.ticklabel_format(axis="y", style="sci", scilimits=(0, 0))

            plt.sca(volume_axis)
            plt.xticks(tick_positions, tick_labels, rotation=24, ha="right", fontsize=8)
            figure.suptitle(title, x=0.08, y=0.992, ha="left", fontsize=15, fontweight="bold", color="#102A43")
            figure.text(0.08, 0.94, f"数据截止：{dates[-1]}  |  价格与成交量联合观察", fontsize=8.5, color="#64748B")
            figure.text(0.94, 0.975, "清研量策·A股研究助手", ha="right", fontsize=8.5, color="#154C79")
            figure.text(0.94, 0.025, "红色=上涨日  绿色=下跌日  |  历史数据不代表未来表现", ha="right", fontsize=7.2, color="#94A3B8")
            figure.subplots_adjust(left=0.08, right=0.96, top=0.885, bottom=0.14)
            figure.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
            plt.close(figure)
            return path
        except Exception:
            LOGGER.exception("Price chart rendering failed for %s", title)
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


def moving_average(values: list[float], window: int) -> list[float | None]:
    """Return a same-length simple moving average series."""
    if window <= 0:
        return [None] * len(values)
    result: list[float | None] = []
    rolling_sum = 0.0
    for index, value in enumerate(values):
        rolling_sum += float(value)
        if index >= window:
            rolling_sum -= float(values[index - window])
        result.append(rolling_sum / window if index >= window - 1 else None)
    return result


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
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
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
        from reportlab.lib.styles import getSampleStyleSheet
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
        page_width, page_height = A4
        left_margin = 18 * mm
        right_margin = 18 * mm
        usable_width = page_width - left_margin - right_margin
        doc = SimpleDocTemplate(
            str(path),
            pagesize=A4,
            leftMargin=left_margin,
            rightMargin=right_margin,
            topMargin=24 * mm,
            bottomMargin=19 * mm,
            title=document_title,
            author="清研量策",
            subject="清研量策·A股研究助手公开信息研究报告",
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
            story.append(Paragraph("核心图表", styles["Heading2CN"]))
            story.append(Spacer(1, 4 * mm))
        for chart in chart_paths:
            if not chart.exists():
                continue
            image = Image(str(chart))
            max_width, max_height = usable_width, 148 * mm
            scale = min(max_width / image.imageWidth, max_height / image.imageHeight, 1.0)
            image.drawWidth = image.imageWidth * scale
            image.drawHeight = image.imageHeight * scale
            image.hAlign = "CENTER"
            story.extend([image, Spacer(1, 7 * mm)])

        def decorate_page(canvas, document) -> None:
            canvas.saveState()
            canvas.setTitle(document_title)
            canvas.setAuthor("清研量策")

            # Institutional-style running header and the requested corner brand.
            canvas.setFillColor(colors.HexColor("#102A43"))
            canvas.rect(0, page_height - 5 * mm, page_width, 5 * mm, stroke=0, fill=1)
            canvas.setFont(bold_font_name, 8.3)
            canvas.setFillColor(colors.HexColor("#154C79"))
            canvas.drawRightString(page_width - right_margin, page_height - 11.5 * mm, "清研量策·A股研究助手")
            canvas.setFont(font_name, 7.4)
            canvas.setFillColor(colors.HexColor("#64748B"))
            header_title = document_title if len(document_title) <= 30 else document_title[:29] + "…"
            canvas.drawString(left_margin, page_height - 11.5 * mm, header_title)
            canvas.setStrokeColor(colors.HexColor("#D9E2F1"))
            canvas.setLineWidth(0.45)
            canvas.line(left_margin, page_height - 14.5 * mm, page_width - right_margin, page_height - 14.5 * mm)

            if document.page == 1:
                canvas.setFillColor(colors.HexColor("#154C79"))
                canvas.rect(left_margin, page_height - 34 * mm, 2.2 * mm, 14 * mm, stroke=0, fill=1)
                canvas.setFont(font_name, 7.2)
                canvas.setFillColor(colors.HexColor("#94A3B8"))
                canvas.drawRightString(page_width - right_margin, page_height - 17.8 * mm, "QINGYAN A-SHARE RESEARCH")

            canvas.setStrokeColor(colors.HexColor("#D9E2F1"))
            canvas.setLineWidth(0.5)
            canvas.line(left_margin, 13 * mm, page_width - right_margin, 13 * mm)
            canvas.setFont(font_name, 7.5)
            canvas.setFillColor(colors.HexColor("#6B7280"))
            canvas.drawString(left_margin, 8 * mm, "公开信息研究辅助 · 不构成投资建议")
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
    from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
    from reportlab.lib.styles import ParagraphStyle

    return {
        "TitleCN": ParagraphStyle(
            "TitleCN",
            parent=sample_styles["Title"],
            fontName=bold_font_name,
            fontSize=22,
            leading=31,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#102A43"),
            leftIndent=8,
            spaceBefore=8,
            spaceAfter=15,
        ),
        "Heading2CN": ParagraphStyle(
            "Heading2CN",
            parent=sample_styles["Heading2"],
            fontName=bold_font_name,
            fontSize=14.2,
            leading=21,
            textColor=colors.HexColor("#154C79"),
            borderColor=colors.HexColor("#154C79"),
            borderWidth=0,
            borderPadding=(0, 0, 2, 0),
            spaceBefore=14,
            spaceAfter=8,
            keepWithNext=True,
        ),
        "Heading3CN": ParagraphStyle(
            "Heading3CN",
            parent=sample_styles["Heading3"],
            fontName=bold_font_name,
            fontSize=12,
            leading=18,
            textColor=colors.HexColor("#334E68"),
            spaceBefore=8,
            spaceAfter=5,
            keepWithNext=True,
        ),
        "BodyCN": ParagraphStyle(
            "BodyCN",
            parent=sample_styles["BodyText"],
            fontName=font_name,
            fontSize=9.8,
            leading=16.2,
            alignment=TA_JUSTIFY,
            textColor=colors.HexColor("#1F2933"),
            spaceAfter=5,
            wordWrap="CJK",
        ),
        "BulletCN": ParagraphStyle(
            "BulletCN",
            parent=sample_styles["BodyText"],
            fontName=font_name,
            fontSize=9.7,
            leading=15.8,
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
            borderPadding=7,
            borderColor=colors.HexColor("#B8D4E8"),
            borderWidth=0.6,
            backColor=colors.HexColor("#F3F8FC"),
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
            fontSize=8.6,
            leading=13,
            alignment=TA_LEFT,
            textColor=colors.white,
            wordWrap="CJK",
        ),
        "TableCellCN": ParagraphStyle(
            "TableCellCN",
            parent=sample_styles["BodyText"],
            fontName=font_name,
            fontSize=8.35,
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
            story.append(HRFlowable(width="100%", thickness=1.1, color=colors.HexColor("#154C79"), spaceBefore=0, spaceAfter=10))
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
    if column_count == 2:
        column_widths = [usable_width * 0.31, usable_width * 0.69]
    elif column_count == 3:
        column_widths = [usable_width * 0.27, usable_width * 0.365, usable_width * 0.365]
    else:
        column_widths = [usable_width / column_count] * column_count
    table = Table(rendered, colWidths=column_widths, repeatRows=1, hAlign="LEFT", splitByRow=1)
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#135E96")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5.5),
    ]
    for row_index in range(1, len(rendered)):
        background = "#F7FAFC" if row_index % 2 == 0 else "#FFFFFF"
        commands.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor(background)))
        if column_count == 2:
            commands.append(("BACKGROUND", (0, row_index), (0, row_index), colors.HexColor("#EEF5FA")))
    table.setStyle(TableStyle(commands))
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
