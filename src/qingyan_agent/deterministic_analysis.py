"""Deterministic, evidence-bound research answer composition."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from .contracts import AnnouncementAnalysis, AnswerProfile
from .models import BacktestResult, MarketSnapshot, ScreeningResult, Target
from .research_planning import EvidenceCheckResult, research_topics


def compose_single_answer(
    question: str,
    target: Target | None,
    intent: str,
    snapshot: MarketSnapshot,
    file_notes: list[dict[str, str]],
    image_notes: list[dict[str, object]],
    backtest: BacktestResult | None,
    evidence_check: EvidenceCheckResult | None = None,
    profile: AnswerProfile = AnswerProfile.STANDARD,
    announcement_analyses: list[AnnouncementAnalysis] | None = None,
) -> str:
    if profile == AnswerProfile.DETAILED:
        return _compose_detailed_answer(
            question,
            target,
            intent,
            snapshot,
            file_notes,
            image_notes,
            backtest,
            evidence_check,
            announcement_analyses or [],
        )
    return _compose_standard_answer(
        question,
        target,
        intent,
        snapshot,
        file_notes,
        image_notes,
        backtest,
        evidence_check,
        announcement_analyses or [],
        concise=profile == AnswerProfile.CONCISE,
    )


def _compose_detailed_answer(
    question: str,
    target: Target | None,
    intent: str,
    snapshot: MarketSnapshot,
    file_notes: list[dict[str, str]],
    image_notes: list[dict[str, object]],
    backtest: BacktestResult | None,
    evidence_check: EvidenceCheckResult | None,
    announcement_analyses: list[AnnouncementAnalysis],
) -> str:
    quote = snapshot.quote or {}
    tech = snapshot.technical or {}
    topics = research_topics(intent, question)
    include_technical = "technical" in topics
    include_fundamentals = "fundamental" in topics
    include_announcements = "announcement" in topics
    data_date = tech.get("data_date") or market_date_from_quote(quote) or "待核验"
    evidence_grade = evidence_grade_text(evidence_check)

    lines = ["## 研究结论摘要"]
    if target:
        lines.append(
            f"- 研究对象：{target.name or target.symbol}（{target.symbol}）；"
            f"市场：{target.market}；行业：{target.sector or '待核验'}；证券身份识别置信度 {target.confidence}%。"
        )
    elif image_notes:
        lines.append("- 研究对象：未从文本确认六位证券代码，图片结论仅能作为形态观察，标的身份待核验。")
    else:
        lines.append("- 研究对象：暂未识别到明确 A 股标的，请补充公司名和六位股票代码。")
    if include_technical:
        lines.append(
            f"- **数据口径**：核心技术数据截止 {data_date}，"
            f"{tech.get('price_adjustment') or '复权口径待核验'}；技术样本 {tech.get('sample_size') or 0} 个交易日；"
            f"证据完备度 {evidence_grade}。"
        )
    else:
        lines.append(f"- **证据完备度**：{evidence_grade}。")
    if include_technical and tech.get("trend_label"):
        basis = "、".join(tech.get("trend_basis") or []) or "详见指标表"
        lines.append(
            f"- **趋势判断**：{tech.get('trend_label')}。该结论由可复核规则 "
            f"{tech.get('trend_rule_version') or '待核验'} 生成，主要依据为：{basis}。"
        )
        lines.append(
            f"- **价格结构**：{tech.get('ma_alignment') or '待核验'}；"
            f"近20日价格结构为“{tech.get('price_structure_20d') or '待核验'}”。"
            "模型标签是对指标的归纳，不作为独立证据重复计权。"
        )
    elif include_technical and tech.get("message"):
        lines.append(f"- **技术数据限制**：{tech.get('message')}")

    if include_technical:
        append_detailed_technical_sections(lines, quote, tech, data_date)

    if include_fundamentals:
        fields = [
            (key, value) for key, value in snapshot.fundamentals.items()
            if not key.startswith("_")
        ][:10] if snapshot.fundamentals else []
        lines.append("\n## 基本面证据")
        if fields:
            lines.append("- 已获取的结构化财务字段：" + "；".join(
                f"{key}={value}" for key, value in fields
            ) + "。")
        else:
            message = research_message_zh(
                snapshot.fundamentals.get("_message")
            ) if snapshot.fundamentals else ""
            lines.append(
                f"- 结构化财务证据不足：{message or '未获取可核验的核心财务字段'}。"
                "本报告不因此推断估值、盈利质量或业绩超预期。"
            )

    if include_announcements:
        append_detailed_announcement_sections(lines, snapshot, announcement_analyses)

    if file_notes:
        lines.append("\n## 用户附件证据")
        for note in file_notes:
            lines.append(f"- {note['filename']}：{note['status']}。{note['summary'] or '未抽取到有效正文。'}")

    if image_notes:
        lines.append("\n## 上传图片证据")
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

    lines.append("\n## 数据质量与方法说明")
    if include_technical:
        lines.extend([
            f"- 行情来源：{quote.get('source') or '待核验'}；K线来源：{tech.get('source') or '待核验'}；抓取时间：{quote.get('fetched_at') or tech.get('fetched_at') or '待核验'}。",
            f"- 20日收益定义：{tech.get('return_definition') or '待核验'}；年化波动率按日收益标准差×√252计算。",
            "- 相对大盘、行业指数和可比公司的超额收益未在当前证据包中提供，因此报告不将绝对收益等同于相对强弱。",
            "- 关键价位是基于历史高低点和动态均线的观察位，不是保证有效的交易价位。",
        ])
        if tech.get("is_intraday"):
            lines.append("- 当前包含盘中尚未完成的当日日K，价格、成交量、均线和动量指标会随收盘前行情继续变化。")
    if include_fundamentals:
        lines.append(f"- 基本面来源：{snapshot.fundamentals.get('source') or '待核验'}；数据日期：{snapshot.fundamentals.get('data_date') or snapshot.fundamentals.get('日期') or '待核验'}。")
    if include_announcements:
        lines.append(f"- 公告来源：cninfo；共取得 {len(snapshot.announcements)} 条公告，正文提取状态见报告附录。")
    relevant_statuses = statuses_for_topics(snapshot, topics)
    if relevant_statuses:
        lines.append("\n### 数据源状态")
        lines.extend([
            f"- {status.source}：{'可用' if status.ok else '不完整'}；"
            f"{research_message_zh(status.message) or '无补充说明'}"
            for status in relevant_statuses
        ])

    lines.append("\n## 主要风险与待验证事项")
    if include_technical:
        lines.extend([
            "- **趋势失效风险**：若价格有效跌破近期结构低点，并在下跌时放量，当前的震荡或修复假设需要重新评估。",
            "- **流动性与突破失败风险**：单日相对成交量偏低时，突破持续性存疑；但低量也可能同时表示抛压有限，必须结合后续价格确认。",
            "- **波动与回撤风险**：历史波动率只描述过去的双向弹性，不是未来回撤上限；应同时参考ATR和历史最大回撤。",
        ])
        if tech.get("is_intraday"):
            lines.append("- **盘中数据风险**：当前使用盘中未完成日K，收盘后的技术指标可能与本次快照不同。")
    if include_announcements:
        lines.append(announcement_risk_text(snapshot))
    if include_fundamentals:
        lines.append("- **基本面验证风险**：财务指标需要结合定期报告口径、现金流、负债和资本开支继续核验，单一字段不代表完整经营质量。")
    lines.append("- **数据与模型风险**：重要结论应以交易所、公司定期报告和权威数据库交叉验证。")
    lines.append("\n> 本报告是公开信息研究辅助材料，不构成投资建议、收益承诺、代客理财或自动交易指令。")
    return "\n".join(lines)


def append_detailed_technical_sections(
    lines: list[str],
    quote: dict[str, Any],
    tech: dict[str, Any],
    data_date: str,
) -> None:
    lines.append("\n## 市场快照与核心指标")
    lines.extend([
        "| 指标 | 当前值 | 研究解读 |",
        "| --- | --- | --- |",
        f"| 最新有效价格 | {fmt(quote.get('price'))} 元 | 涨跌幅 {fmt(quote.get('change_pct'), '%')}；市场时间 {format_market_time(quote.get('market_time')) or data_date} |",
        f"| MA5 / MA20 / MA60 | {fmt(tech.get('ma5'))} / {fmt(tech.get('ma20'))} / {fmt(tech.get('ma60'))} | 现价乖离率 {fmt(tech.get('bias_ma5_pct'), '%')} / {fmt(tech.get('bias_ma20_pct'), '%')} / {fmt(tech.get('bias_ma60_pct'), '%')} |",
        f"| 5日 / 20日 / 60日收益 | {fmt(tech.get('return_5d_pct'), '%')} / {fmt(tech.get('return_20d_pct'), '%')} / {fmt(tech.get('return_60d_pct'), '%')} | 绝对收益，未扣除大盘和行业因素 |",
        f"| RSI14 / MACD柱 | {fmt(tech.get('rsi14'))} / {fmt(tech.get('macd_hist'))} | 动量辅助指标，不单独触发结论 |",
        f"| ATR14 / 日波动率 | {fmt(tech.get('atr14_pct'), '%')} / {fmt(tech.get('daily_volatility_pct'), '%')} | 用于衡量日常价格振幅，不是未来跌幅预测 |",
        f"| 20日相对成交量 | {fmt(tech.get('relative_volume_20d'))} | 仅表示最新交易日相对前19日均量的水平 |",
        f"| 60日最大回撤 | {fmt(tech.get('max_drawdown_60d_pct'), '%')} | 历史区间回撤，不代表未来损失上限 |",
    ])

    lines.append("\n## 走势与均线结构")
    if tech.get("trend_label"):
        lines.append(
            f"- 收盘价相对 MA5、MA20、MA60 的偏离分别为 "
            f"{fmt(tech.get('bias_ma5_pct'), '%')}、{fmt(tech.get('bias_ma20_pct'), '%')}、"
            f"{fmt(tech.get('bias_ma60_pct'), '%')}。"
            "均线上下关系与标准多头/空头排列分开判断，不因“现价低于某条均线”就直接认定趋势反转。"
        )
        lines.append(
            f"- MA5 近5日变化 {fmt(tech.get('ma5_slope_5d_pct'), '%')}，"
            f"MA20 近5日变化 {fmt(tech.get('ma20_slope_5d_pct'), '%')}，"
            f"MA60 近20日变化 {fmt(tech.get('ma60_slope_20d_pct'), '%')}。"
            "斜率与价格位置共同构成趋势判断，避免仅用单日截面下结论。"
        )
        lines.append(
            f"- 近60日区间为 {fmt(tech.get('low_60d'))}—{fmt(tech.get('high_60d'))} 元，"
            f"现价处于该区间约 {fmt(tech.get('range_position_60d_pct'), '%')} 分位。"
            "只有在该分位可核验时，报告才使用“低位”或“高位”等位置性描述。"
        )
    else:
        lines.append("- 缺少足够的连续K线，不对均线方向、价格结构和关键位做确定性判断。")

    lines.append("\n## 量价、动量与波动")
    if tech.get("relative_volume_20d") is not None:
        lines.append(
            f"- 最新交易日相对成交量为 {tech.get('relative_volume_20d')}，"
            f"定义为“{tech.get('relative_volume_definition')}”。"
            f"近5日均量较前5日变化 {fmt(tech.get('volume_5d_change_pct'), '%')}。"
            "前者是单日量能水平，后者才用于观察近期量能方向，两者不混用。"
        )
    lines.append(
        f"- 近{tech.get('annualized_volatility_window_days') or '若干'}日年化历史波动率为 "
        f"{fmt(tech.get('annualized_volatility_pct'), '%')}，在当前可用滚动样本中约处于 "
        f"{fmt(tech.get('volatility_percentile_in_sample_pct'), '%')} 分位，判定为"
        f"“{tech.get('volatility_assessment') or '待核验'}”。波动率是双向弹性指标，不等同于下跌概率。"
    )
    lines.append(
        f"- RSI14={fmt(tech.get('rsi14'))}，MACD DIF/DEA/柱={fmt(tech.get('macd_dif'))}/"
        f"{fmt(tech.get('macd_dea'))}/{fmt(tech.get('macd_hist'))}。"
        "动量指标仅用于与趋势和量价交叉验证。"
    )

    lines.append("\n## 关键价位与情景推演")
    levels = classify_reference_levels(quote, tech)
    lines.append(
        f"- **参考支撑观察位**：{format_levels(levels['support'])}；"
        f"**参考压力观察位**：{format_levels(levels['resistance'])}；"
        f"**动态争夺位**：{format_levels(levels['contested'])}。"
        "均线会逐日变化，不应将当前数值视为永久固定价位。"
    )
    lines.append("")
    lines.extend([
        "| 情景 | 可验证条件 | 研究含义 |",
        "| --- | --- | --- |",
        f"| 偏强情景 | 连续2—3个交易日收于{scenario_level(levels['resistance'], '最近压力观察位')}上方，且成交量恢复至基准均量附近或以上 | 突破证据增强，继续观察更高一级压力位和回踩确认 |",
        f"| 中性情景 | 价格在{scenario_range(levels)}内反复，量能仍低于基准 | 维持区间整理，不对突破方向做先验假设 |",
        f"| 偏弱情景 | 收盘有效跌破{scenario_level(levels['support'], '最近支撑观察位')}，且下跌时量能放大 | 当前震荡或修复假设失效，趋势延续风险上升 |",
    ])


def append_detailed_announcement_sections(
    lines: list[str],
    snapshot: MarketSnapshot,
    announcement_analyses: list[AnnouncementAnalysis],
) -> None:
    lines.append("\n## 公告与事件证据")
    if snapshot.announcements:
        lines.append("\n### 近期公告及核验状态")
        for item in snapshot.announcements[:6]:
            attachment = item.get("attachment") if isinstance(item.get("attachment"), dict) else None
            extraction = ""
            if attachment:
                if attachment.get("status") == "ok":
                    extraction = (
                        f"；正文已提取 {attachment.get('text_chars') or 0} 字符，"
                        f"{attachment.get('pages_with_text') or 0}/"
                        f"{attachment.get('pages_total') or 0} 页含文本"
                    )
                else:
                    extraction = f"；正文提取状态：{attachment.get('status')}"
            lines.append(
                f"- {item.get('title')}（{item.get('date') or '日期待核验'}"
                f"{extraction}；来源 {item.get('source') or '待核验'}）"
            )
        if not any(
            isinstance(item.get("attachment"), dict)
            and item["attachment"].get("status") == "ok"
            for item in snapshot.announcements
        ):
            lines.append("- 上述仅为公告标题线索；正文未成功提取的公告不纳入事实结论，也不将标题解读为业绩超预期。")
    else:
        lines.append("- 暂未获取近期公告列表，需以交易所、巨潮资讯和公司法定披露文件继续核验。")

    append_announcement_analysis(lines, announcement_analyses, max_items=6)
    extracted_announcements = [
        item for item in snapshot.announcements
        if isinstance(item.get("attachment"), dict)
    ]
    if extracted_announcements:
        lines.append("\n### 公告附件正文证据")
        for item in extracted_announcements:
            attachment = item["attachment"]
            lines.append(f"\n#### {item.get('title') or '未命名公告'}（{item.get('date') or '日期待核验'}）")
            lines.append(f"- 原文链接：{item.get('url') or '待核验'}")
            lines.append(f"- 提取状态：{attachment.get('message') or attachment.get('status') or '待核验'}")
            if attachment.get("status") == "ok" and attachment.get("text"):
                lines.append("- 正文摘录（页码标签按 PDF 页面顺序）：")
                lines.append("```text")
                lines.append(announcement_excerpt(str(attachment.get("text") or "")))
                lines.append("```")


def statuses_for_topics(snapshot: MarketSnapshot, topics: set[str]) -> list[Any]:
    source_topics = {
        "market_quote": "technical",
        "market_kline": "technical",
        "fundamental": "fundamental",
        "cninfo_announcement": "announcement",
        "announcement_attachment": "announcement",
    }
    return [
        status for status in snapshot.statuses
        if status.source == "target" or source_topics.get(status.source) in topics
    ]


def _compose_standard_answer(
    question: str,
    target: Target | None,
    intent: str,
    snapshot: MarketSnapshot,
    file_notes: list[dict[str, str]],
    image_notes: list[dict[str, object]],
    backtest: BacktestResult | None,
    evidence_check: EvidenceCheckResult | None,
    announcement_analyses: list[AnnouncementAnalysis],
    *,
    concise: bool,
) -> str:
    quote = snapshot.quote or {}
    tech = snapshot.technical or {}
    topics = research_topics(intent, question)
    include_technical = "technical" in topics
    include_announcements = "announcement" in topics
    include_fundamentals = "fundamental" in topics
    data_date = tech.get("data_date") or market_date_from_quote(quote) or "待核验"
    name = target.name or target.symbol if target else "待核验标的"
    symbol = target.symbol if target else ""
    lines = ["## 研究结论摘要"]
    lines.append(
        f"- 研究对象：{name}{f'（{symbol}）' if symbol else ''}；"
        f"证据完备度 {evidence_grade_text(evidence_check)}。"
    )
    if include_technical and tech.get("trend_label"):
        lines.append(
            f"- 走势判断：{tech.get('trend_label')}；最新有效价格 {fmt(quote.get('price'))} 元，"
            f"近20日收益 {fmt(tech.get('return_20d_pct'), '%')}，"
            f"20日相对成交量 {fmt(tech.get('relative_volume_20d'))}。"
        )
    elif include_technical:
        lines.append(f"- 技术证据限制：{tech.get('message') or '行情或K线不足，暂不判断趋势'}。")
    if evidence_check and evidence_check.missing:
        lines.append("- 待补证据：" + "、".join(evidence_check.missing) + "。")

    if include_technical:
        lines.append("\n## 市场快照与核心指标")
        if concise:
            lines.append(
                f"- 数据截止 {data_date}；价格 {fmt(quote.get('price'))} 元；"
                f"MA5/MA20/MA60={fmt(tech.get('ma5'))}/{fmt(tech.get('ma20'))}/{fmt(tech.get('ma60'))}；"
                f"年化波动率 {fmt(tech.get('annualized_volatility_pct'), '%')}。"
            )
        else:
            lines.extend([
                "",
                "| 指标 | 当前值 |",
                "| --- | --- |",
                f"| 最新有效价格 | {fmt(quote.get('price'))} 元；涨跌幅 {fmt(quote.get('change_pct'), '%')} |",
                f"| MA5 / MA20 / MA60 | {fmt(tech.get('ma5'))} / {fmt(tech.get('ma20'))} / {fmt(tech.get('ma60'))} |",
                f"| 5日 / 20日 / 60日收益 | {fmt(tech.get('return_5d_pct'), '%')} / {fmt(tech.get('return_20d_pct'), '%')} / {fmt(tech.get('return_60d_pct'), '%')} |",
                f"| RSI14 / MACD柱 | {fmt(tech.get('rsi14'))} / {fmt(tech.get('macd_hist'))} |",
                f"| 年化波动率 / 60日最大回撤 | {fmt(tech.get('annualized_volatility_pct'), '%')} / {fmt(tech.get('max_drawdown_60d_pct'), '%')} |",
                f"| 20日相对成交量 | {fmt(tech.get('relative_volume_20d'))} |",
                f"| 5日成交量变化 | {fmt(tech.get('volume_5d_change_pct'), '%')} |",
            ])
        levels = classify_reference_levels(quote, tech)
        lines.append("\n## 关键价位与情景推演")
        lines.append(
            f"- 支撑观察位：{format_levels(levels['support'][:2])}；"
            f"压力观察位：{format_levels(levels['resistance'][:2])}；"
            f"争夺位：{format_levels(levels['contested'][:2])}。"
        )
        if not concise:
            lines.extend([
                "",
                "| 情景 | 可验证条件 |",
                "| --- | --- |",
                f"| 偏强 | 连续2—3日站上{scenario_level(levels['resistance'], '最近压力观察位')}，且量能恢复 |",
                f"| 中性 | 维持在{scenario_range(levels)}内反复 |",
                f"| 偏弱 | 放量跌破{scenario_level(levels['support'], '最近支撑观察位')} |",
            ])

    if include_announcements:
        append_announcement_analysis(
            lines,
            announcement_analyses,
            max_items=2 if concise else 3,
            compact=concise,
        )

    if include_fundamentals:
        lines.append("\n## 基本面证据")
        fields = [(key, value) for key, value in snapshot.fundamentals.items() if not key.startswith("_")]
        if fields:
            lines.append("- 已取得字段：" + "；".join(f"{key}={value}" for key, value in fields[:6]) + "。")
        else:
            message = research_message_zh(snapshot.fundamentals.get("_message")) if snapshot.fundamentals else ""
            lines.append(f"- 财务字段待补充：{message or '未取得可核验财务指标'}。")

    if backtest:
        metrics = backtest.metrics
        lines.append("\n## 回测验证")
        lines.append(
            f"- 状态 {metrics.get('status')}；总收益 {fmt(metrics.get('total_return_pct'), '%')}；"
            f"最大回撤 {fmt(metrics.get('max_drawdown_pct'), '%')}；"
            f"订单 {metrics.get('order_count', metrics.get('trades', 0))} 次；"
            f"完整交易 {metrics.get('completed_trades', 0)} 次。"
        )

    lines.append("\n## 数据质量与方法说明")
    if include_technical:
        lines.append(
            f"- 数据截止 {data_date}；行情来源 {quote.get('source') or '待核验'}；"
            f"K线来源 {tech.get('source') or '待核验'}；复权口径 {tech.get('price_adjustment') or '待核验'}。"
        )
        if tech.get("is_intraday"):
            lines.append("- 当前包含盘中尚未完成的当日日K，价格、成交量、均线和动量指标会随收盘前行情继续变化。")
    if include_fundamentals:
        lines.append(
            f"- 基本面来源 {snapshot.fundamentals.get('source') or '待核验'}；"
            f"数据日期 {snapshot.fundamentals.get('data_date') or snapshot.fundamentals.get('日期') or '待核验'}。"
        )
    if include_announcements:
        extracted = sum(
            isinstance(item.get("attachment"), dict) and item["attachment"].get("status") == "ok"
            for item in snapshot.announcements
        )
        lines.append(
            f"- 共取得 {len(snapshot.announcements)} 条公告，成功读取最近 {extracted} 条正文；"
            "聊天正文仅展示结构化结论，公告原文摘录保留在 Markdown/PDF 报告附录。"
        )
    if file_notes:
        lines.append(f"- 已处理用户附件 {len(file_notes)} 个；附件摘要可能受字符上限影响。")
    if image_notes:
        lines.append(f"- 已处理图片 {len(image_notes)} 张；只有状态为 ok 的图片可供视觉分析。")

    lines.append("\n## 主要风险与待验证事项")
    risk_lines = []
    if include_technical:
        risk_lines.extend([
            "- 趋势和关键价位来自历史数据，不能保证后续继续有效。",
            "- 当前量能和波动指标只描述历史状态，不等同于未来涨跌概率。",
        ])
        if tech.get("is_intraday"):
            risk_lines.append("- 当前使用盘中未完成日K，收盘后的技术指标可能与本次快照不同。")
    if include_announcements:
        for analysis in announcement_analyses[:2 if concise else 3]:
            risk_lines.extend(f"- {risk}" for risk in analysis.get("risks", [])[:1])
    if include_fundamentals:
        risk_lines.append("- 财务指标需要结合定期报告口径、现金流、负债和资本开支继续核验。")
    if not risk_lines:
        risk_lines.append("- 当前证据不足以形成确定性经营或价格判断，需继续核验法定披露。")
    lines.extend(list(dict.fromkeys(risk_lines))[:3 if concise else 5])
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


def prepend_research_notices(answer: str, notices: list[str]) -> str:
    """Keep identity corrections visible even when an upstream answer is used."""
    clean = [str(item).strip() for item in notices if str(item).strip()]
    value = str(answer or "").strip()
    if not clean or all(item in value for item in clean):
        return value
    lines = ["## 标的核验说明"]
    lines.extend(f"- {item}" for item in clean)
    return "\n".join(lines) + "\n\n" + value


def append_context_safe_followups(
    answer: str,
    target: Target | None,
    *,
    question: str = "",
    intent: str = "",
    topics: set[str] | None = None,
    technical: dict[str, Any] | None = None,
) -> str:
    """Append distinct, self-contained next steps for the current research state.

    Every prompt repeats the resolved security because some clients do not send
    chat history on the next request. The research scope is also made explicit
    so the same prompt resolves consistently with or without that history.
    """
    if not target or not target.symbol:
        return answer
    markers = ("## 接下来可以继续", "## 可继续追问（请保留标的）")
    if any(marker in answer for marker in markers):
        return answer
    prompts = build_context_safe_followups(
        target,
        question=question,
        intent=intent,
        topics=topics,
        technical=technical,
    )
    return answer.rstrip() + "\n\n" + "\n".join([
        markers[0],
        "可直接选择以下任一完整问题：",
        *(f"- `{prompt}`" for prompt in prompts),
    ])


def build_context_safe_followups(
    target: Target,
    *,
    question: str = "",
    intent: str = "",
    topics: set[str] | None = None,
    technical: dict[str, Any] | None = None,
) -> list[str]:
    """Build deepen, broaden, and reformat actions without repeating a menu."""
    label = f"{target.name or target.symbol} {target.symbol}"
    current_topics = set(topics) if topics is not None else research_topics(intent, question)
    value = str(question or "").lower()
    technical = technical or {}

    if "backtest" in current_topics or intent == "backtest":
        deepen = f"进一步检验{label}回测结果对参数、交易成本和样本区间的敏感性"
    elif "technical" in current_topics:
        is_intraday = bool(
            technical.get("is_intraday")
            or technical.get("bar_status") == "intraday_partial"
        )
        if is_intraday and "收盘后重新核验" not in value:
            deepen = (
                f"收盘后重新核验{label}的技术信号，"
                "重点观察量能和关键价位是否得到确认"
            )
        elif any(term in value for term in ("确认条件", "失效条件", "关键支撑、压力")):
            deepen = (
                f"复核{label}的技术面支撑、压力与量价配合，"
                "并给出偏强、震荡和转弱情景"
            )
        else:
            deepen = f"进一步分析{label}当前技术走势的确认条件与失效条件"
    elif "announcement" in current_topics:
        deepen = f"梳理{label}近期公告中的关键事实、潜在影响和待验证事项"
    elif "fundamental" in current_topics:
        deepen = f"进一步核验{label}的盈利质量、现金流和估值风险"
    else:
        deepen = f"梳理{label}综合研究结论中最需要持续验证的关键事项"

    if "technical" in current_topics and "announcement" not in current_topics:
        broaden = f"结合{label}近期公告，判断事件因素是否强化或削弱当前技术走势"
    elif "announcement" in current_topics and "technical" not in current_topics:
        broaden = f"结合{label}的技术走势和量价变化，评估近期公告的市场反应"
    elif "fundamental" not in current_topics:
        broaden = (
            f"补充分析{label}的基本面与业绩，"
            "核验其是否支持当前技术面和公告事件结论"
        )
    else:
        broaden = f"对{label}当前技术信号进行历史回测，并说明参数和交易约束"

    scope = followup_scope_text(current_topics, intent)
    if any(term in value for term in ("投研纪要", "一页式", "汇报摘要")):
        deliver = (
            f"为{label}的{scope}生成后续跟踪清单，"
            "明确需要更新的数据、验证条件和风险信号"
        )
    else:
        deliver = (
            f"将{label}的{scope}整理成一页式投研纪要，"
            "保留核心结论、关键证据、验证条件和主要风险"
        )
    return [deepen, broaden, deliver]


def followup_scope_text(topics: set[str], intent: str = "") -> str:
    """Return wording that keeps a reformatting request scope-independent."""
    ordered = [topic for topic in ("technical", "fundamental", "announcement") if topic in topics]
    labels = {
        "technical": "技术面",
        "fundamental": "基本面",
        "announcement": "公告事件",
    }
    if "backtest" in topics or intent == "backtest":
        return "技术面与回测结果"
    if not ordered:
        return "技术面、基本面与公告事件综合研究结论"
    if len(ordered) == 1:
        return f"当前{labels[ordered[0]]}分析"
    if len(ordered) == 3:
        return "技术面、基本面与公告事件综合研究结论"
    return "与".join(labels[topic] for topic in ordered) + "分析"


def append_missing_announcement_links(
    answer: str,
    analyses: list[AnnouncementAnalysis],
    *,
    max_items: int = 3,
) -> str:
    """Ensure an answer that discusses announcements exposes their source URLs."""
    value = str(answer or "").rstrip()
    relevant = []
    for analysis in analyses:
        title = str(analysis.get("title") or "").strip()
        url = safe_announcement_url(analysis.get("source_url"))
        if title and url and (title in value or "公告" in value):
            relevant.append((title, url))
        if len(relevant) >= max_items:
            break
    missing = [(title, url) for title, url in relevant if url not in value]
    if not missing:
        return value
    lines = ["## 公告原文链接"]
    lines.extend(f"- [{title}]({url})" for title, url in missing)
    return value + "\n\n" + "\n".join(lines)


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


def resolve_answer_profile(question: str) -> AnswerProfile:
    value = str(question or "").lower()
    if (
        any(term in value for term in ("一句话", "简单说", "简短", "简洁", "简版", "概括一下"))
        or re.search(r"简单(?:地)?(?:看|分析|介绍|总结|讲)", value)
    ):
        return AnswerProfile.CONCISE
    if any(term in value for term in ("详细", "完整报告", "深度", "底稿", "全面研究", "详细报告")):
        return AnswerProfile.DETAILED
    return AnswerProfile.STANDARD


def append_announcement_analysis(
    lines: list[str],
    analyses: list[AnnouncementAnalysis],
    *,
    max_items: int,
    compact: bool = False,
) -> None:
    lines.append("\n## 重要公告解读")
    if not analyses:
        lines.append("- 暂未取得可供结构化分析的公告，需继续核对巨潮资讯和交易所披露。")
        return
    for index, analysis in enumerate(analyses[:max_items], start=1):
        lines.append(f"\n### {index}. {analysis.get('title')}（{analysis.get('date') or '日期待核验'}）")
        facts = analysis.get("facts") or []
        inferences = analysis.get("inferences") or []
        impacts = analysis.get("potential_impacts") or []
        risks = analysis.get("risks") or []
        verification = analysis.get("verification_items") or []
        pages = analysis.get("source_pages") or []
        source_url = safe_announcement_url(analysis.get("source_url"))
        if compact:
            fact_summary = facts[1:3] if len(facts) > 1 else facts[:1]
            conclusion = (inferences + impacts)[:1]
            summary = compact_answer_text(" ".join(fact_summary + conclusion), 260)
            attention = compact_answer_text(" ".join((risks + verification)[:1]), 160)
            if summary:
                lines.append("- **简单概括**：" + summary)
            if attention:
                lines.append("- **需要注意**：" + attention)
            if source_url:
                lines.append(f"- **公告原文**：[查看巨潮资讯原文]({source_url})")
            continue
        if facts:
            lines.append("- **公告事实**：" + " ".join(facts[:3]))
        if inferences or impacts:
            lines.append("- **分析推断与潜在影响**：" + " ".join((inferences + impacts)[:3]))
        if risks or verification:
            lines.append("- **风险与待验证**：" + " ".join((risks + verification)[:3]))
        if pages:
            lines.append("- **正文页码证据**：第 " + "、".join(str(page) for page in pages) + " 页。")
        if source_url:
            lines.append(f"- **公告原文**：[查看巨潮资讯原文]({source_url})")


def announcement_risk_text(snapshot: MarketSnapshot) -> str:
    extracted = sum(
        isinstance(item.get("attachment"), dict) and item["attachment"].get("status") == "ok"
        for item in snapshot.announcements
    )
    total = len(snapshot.announcements)
    if not total:
        return "- **公告证据风险**：当前未取得近期公告列表，事件风险需要继续核验。"
    if extracted == 0:
        return "- **公告证据说明**：本次只取得公告标题、没有读到正文，因此不判断公告会让业绩变好还是变差；具体内容请打开原文核对。"
    if extracted < total:
        return f"- **公告证据说明**：本次查到 {total} 条公告，读取了其中 {extracted} 条正文；其余公告只作为线索，不仅凭标题判断利好或利空。"
    return "- **公告证据说明**：已读取当前列示公告正文；若 PDF 是扫描件、复杂表格或内容被截断，仍需打开原文核对。"


def safe_announcement_url(value: Any) -> str:
    url = str(value or "").strip()
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    return url if parsed.scheme in {"http", "https"} and bool(parsed.netloc) else ""


def compact_answer_text(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def announcement_excerpt(value: str, limit: int = 1400) -> str:
    text = str(value or "").replace("```", "''' ").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "\n[摘录已截断，完整抽取文本保留在证据包中]"


def evidence_grade_text(result: EvidenceCheckResult | None) -> str:
    if result is None:
        return "待核验"
    labels = {
        "complete": "完整",
        "partial": "部分完整",
        "insufficient": "不足",
    }
    return f"{result.score}/100（{labels.get(result.grade, result.grade)}）"


def classify_reference_levels(
    quote: dict[str, Any],
    technical: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    price = to_number(quote.get("price")) or to_number(technical.get("last_close"))
    result: dict[str, list[dict[str, Any]]] = {
        "support": [],
        "resistance": [],
        "contested": [],
    }
    if price is None or price <= 0:
        return result
    tolerance = max(price * 0.005, 0.01)
    candidates = (
        ("近20日低点", technical.get("low_20d")),
        ("MA60", technical.get("ma60")),
        ("MA20", technical.get("ma20")),
        ("MA5", technical.get("ma5")),
        ("近20日高点", technical.get("high_20d")),
    )
    seen: list[float] = []
    for label, raw_value in candidates:
        value = to_number(raw_value)
        if value is None or value <= 0 or any(abs(value - prior) < 0.0001 for prior in seen):
            continue
        seen.append(value)
        level = {"label": label, "value": round(value, 4), "distance_pct": round((value / price - 1) * 100, 2)}
        if abs(value - price) <= tolerance:
            result["contested"].append(level)
        elif value < price:
            result["support"].append(level)
        else:
            result["resistance"].append(level)
    result["support"].sort(key=lambda item: item["value"], reverse=True)
    result["resistance"].sort(key=lambda item: item["value"])
    result["contested"].sort(key=lambda item: abs(item["distance_pct"]))
    return result


def format_levels(levels: list[dict[str, Any]]) -> str:
    if not levels:
        return "暂无可核验价位"
    return "、".join(f"{item['label']} {fmt(item['value'])} 元" for item in levels)


def scenario_level(levels: list[dict[str, Any]], fallback: str) -> str:
    if not levels:
        return fallback
    item = levels[0]
    return f"{item['label']} {fmt(item['value'])} 元"


def scenario_range(levels: dict[str, list[dict[str, Any]]]) -> str:
    lower = scenario_level(levels["support"], "动态支撑")
    upper = scenario_level(levels["resistance"], "动态压力")
    return f"{lower}与{upper}之间"


def to_number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None



def fmt(value, suffix: str = "") -> str:
    if value is None:
        return "N/A"
    return f"{value}{suffix}"


def market_date_from_quote(quote: dict) -> str:
    value = str((quote or {}).get("market_time") or "")
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) < 8:
        return ""
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"


def format_market_time(value) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    if len(digits) >= 14:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]} {digits[8:10]}:{digits[10:12]}:{digits[12:14]}"
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return str(value or "")


def research_message_zh(value) -> str:
    message = str(value or "")
    if message.startswith("optional akshare fundamentals disabled"):
        return "结构化财务数据模块未启用，未取得可复核的盈利、现金流、负债率与估值字段"
    if message.startswith("optional akshare fundamentals unavailable"):
        return "结构化财务数据源暂不可用，财务结论待以定期报告和权威数据库核验"
    return message
