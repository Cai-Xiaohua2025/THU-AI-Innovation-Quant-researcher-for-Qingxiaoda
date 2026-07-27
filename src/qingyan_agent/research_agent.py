"""Research orchestration for the competition agent."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .backtest import BacktestService
from .compliance import guard_output, normalize_question
from .data_sources import AShareDataClient
from .file_reader import FileSummary
from .models import BacktestResult, MarketSnapshot, ResearchOutput, ScreeningResult, Target
from .reporting import ChartService
from .screening import StockScreener
from .universe import infer_intent, infer_target


class ResearchAgent:
    def __init__(self, data_client: AShareDataClient, screener: StockScreener, backtester: BacktestService, chart_service: ChartService) -> None:
        self.data_client = data_client
        self.screener = screener
        self.backtester = backtester
        self.chart_service = chart_service

    def run(self, prompt: str, files: list[FileSummary]) -> tuple[ResearchOutput, list[Path]]:
        question = normalize_question(prompt or "")
        intent = infer_intent(question)
        target = infer_target(question)
        file_notes = summarize_files(files)
        charts: list[Path] = []

        if intent == "screening":
            screening = self.screener.screen()
            chart = self.chart_service.screening_chart("候选股票池研究评分", screening.rows)
            if chart:
                charts.append(chart)
            title = "候选股票池研究报告"
            answer = compose_screening_answer(screening)
            report = compose_report(title, question, {"screening": screening.rows}, file_notes, answer)
            return ResearchOutput(title, guard_output(answer), report), charts

        snapshot = self.data_client.collect(target)
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

        title = build_title(target, intent)
        answer = compose_single_answer(question, target, intent, snapshot, file_notes, backtest_result)
        answer = guard_output(answer)
        report_payload = {
            "target": target.__dict__ if target else None,
            "quote": snapshot.quote,
            "technical": snapshot.technical,
            "fundamentals": snapshot.fundamentals,
            "announcements": snapshot.announcements[:8],
            "statuses": [status.__dict__ for status in snapshot.statuses],
            "backtest": backtest_result.metrics if backtest_result else None,
        }
        report = compose_report(title, question, report_payload, file_notes, answer)
        return ResearchOutput(title, answer, report), charts


def build_title(target: Target | None, intent: str) -> str:
    suffix = {
        "fundamental": "财报与基本面研究报告",
        "announcement": "公告与消息归因报告",
        "technical": "走势与技术指标研究报告",
        "backtest": "策略回测研究报告",
        "full_research": "综合金融研究报告",
    }.get(intent, "综合金融研究报告")
    if target:
        return f"{target.name or target.symbol}{suffix}"
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


def compose_single_answer(
    question: str,
    target: Target | None,
    intent: str,
    snapshot: MarketSnapshot,
    file_notes: list[dict[str, str]],
    backtest: BacktestResult | None,
) -> str:
    lines = ["## 研究结论摘要"]
    if target:
        lines.append(f"- 研究对象：{target.name or target.symbol}（{target.market}:{target.symbol}，行业：{target.sector or '待补充'}，识别置信度 {target.confidence}%）。")
    else:
        lines.append("- 暂未识别到明确 A 股标的；请补充公司名、股票代码或上传公告/财报附件。")

    quote = snapshot.quote or {}
    if quote.get("price"):
        lines.append(f"- 最新行情：价格 {quote.get('price')}，涨跌幅 {fmt(quote.get('change_pct'), '%')}，来源 {quote.get('source')}。")
    else:
        lines.append(f"- 行情状态：暂未获取到实时价格；{quote.get('message', '可继续使用研究框架和附件材料分析。')}")

    tech = snapshot.technical or {}
    if tech.get("trend_label"):
        lines.append(
            f"- 技术观察：{tech.get('trend_label')}；MA5={fmt(tech.get('ma5'))}，MA20={fmt(tech.get('ma20'))}，"
            f"20日收益={fmt(tech.get('return_20d_pct'), '%')}，年化波动={fmt(tech.get('annualized_volatility_pct'), '%')}。"
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
            lines.append(f"- {item.get('title')}（{item.get('date') or 'date N/A'}）")
    else:
        lines.append("\n## 近期公告线索\n- 暂未获取公告列表，需以交易所、巨潮资讯、公司官网等原始公告继续核验。")

    if file_notes:
        lines.append("\n## 附件材料摘要")
        for note in file_notes:
            lines.append(f"- {note['filename']}：{note['status']}。{note['summary'] or '未抽取到有效正文。'}")

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
