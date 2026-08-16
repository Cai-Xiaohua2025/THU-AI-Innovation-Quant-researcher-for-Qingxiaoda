"""Research orchestration for the competition agent."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .backtest import BacktestService
from .compliance import guard_output, normalize_question
from .data_sources import AShareDataClient
from .file_reader import FileSummary, ImageSummary
from .llm_client import LLMResult, UpstreamLLMClient
from .models import BacktestResult, MarketSnapshot, ResearchOutput, ScreeningResult, Target
from .reporting import ChartService
from .screening import StockScreener
from .universe import infer_intent, infer_target


class ResearchAgent:
    def __init__(
        self,
        data_client: AShareDataClient,
        screener: StockScreener,
        backtester: BacktestService,
        chart_service: ChartService,
        llm_client: UpstreamLLMClient | None = None,
    ) -> None:
        self.data_client = data_client
        self.screener = screener
        self.backtester = backtester
        self.chart_service = chart_service
        self.llm_client = llm_client

    def run(
        self,
        prompt: str,
        files: list[FileSummary],
        images: list[ImageSummary] | None = None,
    ) -> tuple[ResearchOutput, list[Path]]:
        images = images or []
        question = normalize_question(prompt or "")
        if not question.strip() and images:
            question = "请分析上传的 K 线或行情图片，只使用图中清晰可见的信息。"
        intent = infer_intent(question)
        if images and intent == "greeting":
            intent = "technical"
        file_notes = summarize_files(files)
        image_notes = summarize_images(images)
        image_data_urls = [item.data_url for item in images if item.status == "ok" and item.data_url]
        charts: list[Path] = []

        if intent == "greeting":
            answer = guard_output(compose_greeting_answer())
            return ResearchOutput(
                "清研量策使用指南",
                answer,
                answer,
                report_enabled=False,
            ), charts

        if intent == "screening":
            screening = self.screener.screen()
            chart = self.chart_service.screening_chart("候选股票池研究评分", screening.rows)
            if chart:
                charts.append(chart)
            title = "候选股票池研究报告"
            deterministic_answer = compose_screening_answer(screening)
            evidence = {
                "screening": screening.rows,
                "data_statuses": [status.__dict__ for status in screening.statuses],
                "attachments": file_notes,
                "images": image_notes,
            }
            answer, llm_result = self.synthesize(
                question, intent, evidence, deterministic_answer, image_data_urls=image_data_urls,
            )
            answer = guard_output(answer)
            evidence["upstream_llm"] = llm_result.public_metadata(self.llm_configured)
            report = compose_report(title, question, evidence, file_notes, answer)
            return ResearchOutput(title, answer, report), charts

        target = self.data_client.resolve_target(question, infer_target(question))

        include_announcement_text = intent == "announcement" or (
            intent == "full_research" and "公告" in question
        )
        snapshot = self.data_client.collect(
            target,
            include_announcement_text=include_announcement_text,
        )
        if snapshot.klines:
            chart = self.chart_service.price_chart(f"{(target.name if target else '') or (target.symbol if target else '')} 价格趋势", snapshot.klines)
            if chart:
                charts.append(chart)

        backtest_result = None
        if intent == "backtest" and target:
            backtest_result = self.backtester.run_ma_cross(target, snapshot.klines)
            chart = self.chart_service.backtest_chart(f"{target.name or target.symbol} 回测净值", backtest_result.equity_curve)
            if chart:
                charts.append(chart)

        title = build_title(target, intent, bool(images))
        report_payload = {
            "target": target.__dict__ if target else None,
            "quote": snapshot.quote,
            "technical": snapshot.technical,
            "fundamentals": snapshot.fundamentals,
            "announcements": snapshot.announcements[:8],
            "statuses": [
                status.__dict__ for status in snapshot.statuses
                if not (images and not target and status.source == "target")
            ],
            "backtest": backtest_result.metrics if backtest_result else None,
            "attachments": file_notes,
            "images": image_notes,
        }
        deterministic_answer = compose_single_answer(
            question, target, intent, snapshot, file_notes, image_notes, backtest_result,
        )
        answer, llm_result = self.synthesize(
            question,
            intent,
            report_payload,
            deterministic_answer,
            image_data_urls=image_data_urls,
        )
        if image_data_urls and not llm_result.used:
            answer = deterministic_answer.rstrip() + (
                "\n\n## 图片分析状态\n"
                "- 图片已安全读取，但本次视觉模型不可用，因此没有假装识别图中走势。请稍后重试；"
                "若同时提供股票名称和代码，系统仍可先用结构化行情完成交叉核验。"
            )
        answer = append_context_safe_followups(answer, target)
        answer = guard_output(answer)
        report_payload["upstream_llm"] = llm_result.public_metadata(self.llm_configured)
        report = compose_report(title, question, report_payload, file_notes, answer)
        return ResearchOutput(title, answer, report), charts

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_client and self.llm_client.configured)

    def synthesize(
        self,
        question: str,
        intent: str,
        evidence: dict,
        deterministic_answer: str,
        image_data_urls: list[str] | None = None,
    ) -> tuple[str, LLMResult]:
        if not self.llm_client:
            return deterministic_answer, LLMResult()
        result = self.llm_client.synthesize(
            question=question,
            intent=intent,
            evidence=evidence,
            deterministic_draft=deterministic_answer,
            image_data_urls=image_data_urls,
        )
        return (result.content if result.used else deterministic_answer), result


def build_title(target: Target | None, intent: str, has_images: bool = False) -> str:
    suffix = {
        "fundamental": "财报与基本面研究报告",
        "announcement": "公告与消息归因报告",
        "technical": "走势与技术指标研究报告",
        "backtest": "策略回测研究报告",
        "full_research": "综合金融研究报告",
    }.get(intent, "综合金融研究报告")
    if target:
        return f"{target.name or target.symbol}{suffix}"
    if has_images:
        return "K线与行情图片技术分析报告"
    return suffix


def summarize_files(files: list[FileSummary]) -> list[dict[str, str]]:
    keywords = ("营业收入", "收入", "净利润", "利润", "现金流", "资产负债", "毛利率", "ROE", "风险", "管理层讨论", "重大事项")
    notes = []
    for item in files:
        text = item.text or ""
        snippets = []
        for keyword in keywords:
            idx = text.find(keyword)
            if idx >= 0:
                snippets.append(text[max(0, idx - 90):idx + 260].replace("\n", " "))
        if not snippets and text:
            snippets.append(text[:900].replace("\n", " "))
        notes.append({"filename": item.filename, "status": item.status, "summary": "\n".join(snippets[:5])[:2400]})
    return notes


def summarize_images(images: list[ImageSummary]) -> list[dict[str, object]]:
    return [{
        "filename": item.filename,
        "status": item.status,
        "mime_type": item.mime_type,
        "width": item.width,
        "height": item.height,
        "source_url": item.source_url,
    } for item in images]


def compose_single_answer(
    question: str,
    target: Target | None,
    intent: str,
    snapshot: MarketSnapshot,
    file_notes: list[dict[str, str]],
    image_notes: list[dict[str, object]],
    backtest: BacktestResult | None,
) -> str:
    lines = ["## 研究结论摘要"]
    if target:
        lines.append(f"- 研究对象：{target.name or target.symbol}（{target.market}:{target.symbol}，行业：{target.sector or '待补充'}，识别置信度 {target.confidence}%）。")
    elif image_notes:
        lines.append(
            "- 本次未从文本确认股票代码；可以先分析上传图片中的可见形态，"
            "但图片标题或标注中的公司名称仍应结合六位代码核验。"
        )
    else:
        lines.append("- 暂未识别到明确 A 股标的；请补充公司名、股票代码或上传公告/财报附件。")

    quote = snapshot.quote or {}
    if quote.get("price"):
        freshness = "历史缓存" if quote.get("is_stale") else "行情源快照"
        volume_text = ""
        if quote.get("volume") is not None:
            volume_text = f"，成交量 {quote.get('volume')} {quote.get('volume_unit') or '单位待核验'}"
        lines.append(
            f"- 最近市场快照：价格 {quote.get('price')}，涨跌幅 {fmt(quote.get('change_pct'), '%')}{volume_text}，"
            f"来源 {quote.get('source')}（{freshness}，市场时间 {quote.get('market_time') or '待核验'}，"
            f"抓取时间 {quote.get('fetched_at') or '待核验'}）。"
        )
    else:
        lines.append(f"- 行情状态：暂未获取到最近市场快照；{quote.get('message', '可继续使用研究框架和附件材料分析。')}")

    tech = snapshot.technical or {}
    if tech.get("trend_label"):
        lines.append(
            f"- 技术观察：{tech.get('trend_label')}；MA5={fmt(tech.get('ma5'))}，MA20={fmt(tech.get('ma20'))}，"
            f"20日收益={fmt(tech.get('return_20d_pct'), '%')}，"
            f"近{tech.get('annualized_volatility_window_days') or '若干'}个交易日年化波动="
            f"{fmt(tech.get('annualized_volatility_pct'), '%')}，"
            f"20日相对成交量={fmt(tech.get('relative_volume_20d'))}；"
            f"数据日期={tech.get('data_date') or '待核验'}，{tech.get('price_adjustment') or '复权口径待核验'}，"
            f"来源={tech.get('source') or '待核验'}。"
        )
    elif tech.get("message"):
        lines.append(f"- 技术观察：{tech.get('message')}")

    if snapshot.fundamentals:
        fields = [(k, v) for k, v in snapshot.fundamentals.items() if not k.startswith("_")][:8]
        if fields:
            lines.append("- 财务字段：" + "；".join([f"{k}={v}" for k, v in fields]) + "。")
        else:
            lines.append(f"- 财务字段：{snapshot.fundamentals.get('_message', '可通过附件财报增强解析。')}")
    else:
        lines.append("- 财务字段：暂未获取结构化财务数据，建议上传年报/季报或配置财务数据依赖。")

    if snapshot.announcements:
        lines.append("\n## 近期公告线索")
        for item in snapshot.announcements[:6]:
            attachment = item.get("attachment") if isinstance(item.get("attachment"), dict) else None
            extraction = ""
            if attachment:
                if attachment.get("status") == "ok":
                    extraction = (
                        f"；正文已提取 {attachment.get('text_chars') or 0} 字符，"
                        f"{attachment.get('pages_with_text') or 0}/{attachment.get('pages_total') or 0} 页含文本"
                    )
                else:
                    extraction = f"；正文提取状态：{attachment.get('status')}"
            lines.append(
                f"- {item.get('title')}（{item.get('date') or 'date N/A'}{extraction}）"
            )
    else:
        lines.append("\n## 近期公告线索\n- 暂未获取公告列表，需以交易所、巨潮资讯、公司官网等原始公告继续核验。")

    extracted_announcements = [
        item for item in snapshot.announcements
        if isinstance(item.get("attachment"), dict)
    ]
    if extracted_announcements:
        lines.append("\n## 公告附件正文证据")
        for item in extracted_announcements:
            attachment = item["attachment"]
            lines.append(f"\n### {item.get('title') or '未命名公告'}（{item.get('date') or '日期待核验'}）")
            lines.append(f"- 原文链接：{item.get('url') or '待核验'}")
            lines.append(f"- 提取状态：{attachment.get('message') or attachment.get('status') or '待核验'}")
            if attachment.get("status") == "ok" and attachment.get("text"):
                lines.append("- 正文摘录（页码标签按 PDF 页面顺序）：")
                lines.append("```text")
                lines.append(announcement_excerpt(str(attachment.get("text") or "")))
                lines.append("```")

    if file_notes:
        lines.append("\n## 附件材料摘要")
        for note in file_notes:
            lines.append(f"- {note['filename']}：{note['status']}。{note['summary'] or '未抽取到有效正文。'}")

    if image_notes:
        lines.append("\n## 上传图片")
        for note in image_notes:
            dimensions = (
                f"{note.get('width')}×{note.get('height')}"
                if note.get("width") and note.get("height") else "尺寸待核验"
            )
            lines.append(
                f"- {note.get('filename') or '图片'}：{note.get('status')}，"
                f"{note.get('mime_type') or '类型待核验'}，{dimensions}。"
            )
        if not any(note.get("status") == "ok" for note in image_notes):
            lines.append("- 本次没有可供视觉模型读取的有效图片，不能据此判断走势或形态。")

    if backtest:
        lines.append("\n## 回测验证")
        lines.append("- 来源：" + backtest.source)
        for key, value in backtest.metrics.items():
            lines.append(f"- {key}: {value}")

    lines.append("\n## 风险与待验证事项")
    lines.append("- 数据源可能存在延迟、缺失或口径差异，正式结论应回到交易所公告、公司定期报告和权威数据库核验。")
    lines.append("- 如果进入选股环节，需要加入行业中性化、流动性、交易成本、涨跌停/停牌约束和样本外检验。")
    lines.append("- 系统默认不连接券商、不读取个人资产、不执行实盘交易。")
    return "\n".join(lines)


def compose_greeting_answer() -> str:
    return """你好，我是“清研量策”，一个面向公开 A 股信息的合规金融研究智能体。

我可以帮助你完成：

1. **单股走势研究**：行情、K 线、均线、波动和成交活跃度分析；也可以上传 K 线截图做视觉分析。
2. **公告与事件解读**：检索近期公告，区分事实、分析推断和待核验事项。
3. **财报与附件分析**：结合 PDF、Word、Excel、Markdown 等材料提取研究线索。
4. **候选股票池筛选**：按动量、趋势、波动、流动性、财务质量和数据可用性生成研究清单。
5. **策略回测**：对指定股票运行 MA10/MA30 等研究型历史回测，并说明收益、回撤和模型限制。
6. **研究报告生成**：输出中文研究结论，并生成 Markdown、PDF 和图表附件。

你可以这样提问：

- `分析长江电力 600900 的近期走势和主要风险`
- 上传 K 线截图后提问：`请分析图中的趋势、量价特征、支撑压力和风险`
- `解读新光光电 688011 的近期公告`
- `对贵州茅台 600519 做 MA10/MA30 回测`
- `从内置股票池生成一个候选研究清单`
- 上传财报后提问：`分析盈利质量、现金流风险和待核验事项`

为了避免代码与公司名称混淆，建议首次提问同时提供**公司名称和六位股票代码**。系统不具备券商账户连接或交易执行能力。"""


def append_context_safe_followups(answer: str, target: Target | None) -> str:
    """Make follow-up prompts self-contained for clients that omit chat history."""
    if not target or not target.symbol:
        return answer
    marker = "## 可继续追问（请保留标的）"
    if marker in answer:
        return answer
    label = f"{target.name or target.symbol} {target.symbol}"
    return answer.rstrip() + "\n\n" + "\n".join([
        marker,
        "为保证下一轮仍能准确识别股票，请直接发送下面任一完整句子：",
        f"1. `继续分析{label}：纯技术面版`",
        f"2. `继续分析{label}：技术面 + 公告事件版`",
        f"3. `将{label}整理成适合汇报的投研纪要简版`",
    ])


def compose_screening_answer(screening: ScreeningResult) -> str:
    lines = ["## 候选股票池研究结果"]
    lines.append(f"- 股票池：{screening.universe_name}")
    lines.append("- 评分口径：动量、趋势、波动控制、成交活跃度、财务质量和数据可用性综合评分。")
    lines.append("")
    for idx, row in enumerate(screening.rows, start=1):
        lines.append(
            f"{idx}. {row['name']}（{row['symbol']}，{row.get('sector') or '行业待补充'}）"
            f"：研究分 {row['score']}；风险标签：{', '.join(row['risk_tags'])}；因子：{row['factors']}"
        )
    lines.append("\n## 使用建议")
    lines.append("- 该结果仅用于生成研究清单，不表示买卖建议。")
    lines.append("- 进入下一步前，应补充公告核验、财报字段、行业对比、回测和交易约束。")
    return "\n".join(lines)


def announcement_excerpt(value: str, limit: int = 1400) -> str:
    text = str(value or "").replace("```", "''' ").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "\n[摘录已截断，完整抽取文本保留在证据包中]"


def compose_report(title: str, question: str, payload: dict, file_notes: list[dict[str, str]], answer: str) -> str:
    metadata = {
        "title": title,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "file_count": len(file_notes),
        "payload": payload,
    }
    return "\n".join([
        f"# {title}",
        "",
        "## 用户问题",
        question,
        "",
        "## 结构化元数据",
        "```json",
        json.dumps(metadata, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        answer,
    ])


def fmt(value, suffix: str = "") -> str:
    if value is None:
        return "N/A"
    return f"{value}{suffix}"
