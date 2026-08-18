"""Research orchestration for the competition agent."""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from .announcement_analysis import analyze_announcements
from .backtest import BacktestService
from .compliance import guard_output, normalize_question
from .contracts import AnswerProfile, ResearchContext, ResearchStep
from .data_sources import AShareDataClient
from .deterministic_analysis import (
    append_missing_announcement_links,
    append_context_safe_followups,
    compose_greeting_answer,
    compose_screening_answer,
    compose_single_answer,
    prepend_research_notices,
    resolve_answer_profile,
)
from .file_reader import FileSummary, ImageSummary
from .llm_client import (
    LLMResult,
    UpstreamLLMClient,
    answer_respects_profile,
    deduplicate_repeated_blocks,
)
from .models import BacktestResult, MarketSnapshot, ResearchOutput, Target
from .reporting import ChartService
from .report_composer import compose_report
from .research_planning import evaluate_evidence, generate_research_plan, research_topics
from .screening import StockScreener
from .universe import (
    effective_user_text,
    infer_intent,
    infer_target,
    latest_user_text,
    target_resolution_notes,
    user_turn_texts,
)


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
        conversation = normalize_question(prompt or "")
        if not conversation.strip() and images:
            conversation = "请分析上传的 K 线或行情图片，只使用图中清晰可见的信息。"
        latest_question = latest_user_text(conversation)
        execution_question = effective_user_text(conversation)
        intent = infer_intent(conversation)
        if images and intent == "greeting":
            intent = "technical"
        context = ResearchContext(
            question=latest_question,
            intent=intent,
            conversation_turns=user_turn_texts(conversation),
        )
        context.plan = generate_research_plan(intent, has_images=bool(images))
        answer_profile = resolve_answer_profile(execution_question)
        topics = research_topics(intent, execution_question)
        interpret_step = context_step(context, "interpret")
        interpret_step.start()
        interpret_step.complete("intent")
        file_notes = summarize_files(files)
        image_notes = summarize_images(images)
        image_data_urls = [item.data_url for item in images if item.status == "ok" and item.data_url]
        charts: list[Path] = []

        if intent == "greeting":
            response_step = context_step(context, "respond")
            response_step.start()
            answer = guard_output(compose_greeting_answer())
            response_step.complete("answer")
            context.complete()
            return ResearchOutput(
                "清研量策使用指南",
                answer,
                answer,
                report_enabled=False,
                context=context,
            ), charts

        if intent == "screening":
            screening_step = context_step(context, "screening")
            screening_step.start()
            screening = self.screener.screen()
            screening_step.complete("screening", "data_statuses")
            chart = self.chart_service.screening_chart("候选股票池研究评分", screening.rows)
            if chart:
                charts.append(chart)
            title = "候选股票池研究报告"
            analyze_step = context_step(context, "analyze")
            analyze_step.start()
            deterministic_answer = compose_screening_answer(screening)
            analyze_step.complete("deterministic_answer")
            evidence = {
                "screening": screening.rows,
                "data_statuses": [status.__dict__ for status in screening.statuses],
                "attachments": file_notes,
                "images": image_notes,
            }
            completeness = evaluate_evidence(intent, evidence, execution_question)
            context.evidence_completeness = completeness.as_dict()
            context.missing_evidence = completeness.missing
            context.warnings.extend(completeness.warnings)
            synthesize_step = context_step(context, "synthesize")
            synthesize_step.start()
            answer, llm_result = self.synthesize(
                execution_question, intent, evidence, deterministic_answer, image_data_urls=image_data_urls,
            )
            synthesize_step.complete("upstream_llm" if llm_result.used else "deterministic_fallback")
            review_step = context_step(context, "review")
            review_step.start()
            answer = guard_output(answer)
            review_step.complete("answer")
            evidence["upstream_llm"] = llm_result.public_metadata(self.llm_configured)
            context.evidence = evidence
            context.data_statuses = evidence["data_statuses"]
            context.model_metadata = evidence["upstream_llm"]
            compose_step = context_step(context, "compose_report")
            compose_step.start()
            compose_step.complete("report")
            context.complete()
            evidence["research_context"] = context.public_metadata()
            report = compose_report(title, latest_question, evidence, file_notes, answer)
            return ResearchOutput(title, answer, report, context=context), charts

        target_step = context_step(context, "resolve_target")
        target_step.start()
        target, resolution_notes = resolve_research_target(
            self.data_client,
            conversation,
            latest_question,
        )
        context.warnings.extend(resolution_notes)
        context.target = target.__dict__ if target else None
        if target:
            target_step.complete("target")
        elif images and not target_step.required:
            target_step.skip("图片研究未要求必须识别 A 股标的")
        else:
            target_step.fail("未识别到明确 A 股标的")

        include_announcement_text = "announcement" in topics
        evidence_step = context_step(context, "collect_evidence")
        evidence_step.start()
        snapshot = collect_snapshot(
            self.data_client,
            target,
            include_announcement_text=include_announcement_text,
            topics=topics,
        )
        evidence_keys = ["target"]
        if "technical" in topics:
            evidence_keys.extend(["quote", "technical"])
        if "fundamental" in topics:
            evidence_keys.append("fundamentals")
        if "announcement" in topics:
            evidence_keys.extend(["announcements", "announcement_analysis"])
        evidence_step.complete(*evidence_keys)
        if snapshot.klines:
            chart = self.chart_service.price_chart(f"{(target.name if target else '') or (target.symbol if target else '')} 价格趋势", snapshot.klines)
            if chart:
                charts.append(chart)

        backtest_result = None
        if intent == "backtest" and target:
            backtest_step = context_step(context, "backtest")
            backtest_step.start()
            backtest_result = self.backtester.run_ma_cross(target, snapshot.klines)
            backtest_step.complete("backtest")
            chart = self.chart_service.backtest_chart(f"{target.name or target.symbol} 回测净值", backtest_result.equity_curve)
            if chart:
                charts.append(chart)

        title = build_title(target, intent, bool(images))
        announcement_analyses = analyze_announcements(snapshot.announcements)
        collected_payload = build_evidence_payload(
            target=target,
            snapshot=snapshot,
            backtest_result=backtest_result,
            file_notes=file_notes,
            image_notes=image_notes,
            announcement_analyses=announcement_analyses,
            resolution_notes=resolution_notes,
            image_only=bool(images and not target),
        )
        report_payload = synthesis_evidence_for_intent(
            intent,
            collected_payload,
            execution_question,
        )
        completeness = evaluate_evidence(intent, report_payload, execution_question)
        context.evidence_completeness = completeness.as_dict()
        context.missing_evidence = completeness.missing
        context.warnings.extend(completeness.warnings)
        analyze_step = context_step(context, "analyze")
        analyze_step.start()
        deterministic_answer = compose_single_answer(
            execution_question,
            target,
            intent,
            snapshot,
            file_notes,
            image_notes,
            backtest_result,
            completeness,
            answer_profile,
            announcement_analyses,
        )
        detailed_report_answer = compose_single_answer(
            execution_question,
            target,
            intent,
            snapshot,
            file_notes,
            image_notes,
            backtest_result,
            completeness,
            AnswerProfile.DETAILED,
            announcement_analyses,
        )
        deterministic_answer = prepend_research_notices(deterministic_answer, resolution_notes)
        detailed_report_answer = prepend_research_notices(detailed_report_answer, resolution_notes)
        analyze_step.complete("deterministic_answer")
        synthesize_step = context_step(context, "synthesize")
        synthesize_step.start()
        if answer_profile == AnswerProfile.CONCISE and not image_data_urls:
            answer = deterministic_answer
            llm_result = LLMResult(error="concise profile uses deterministic response")
        else:
            answer, llm_result = self.synthesize(
                execution_question,
                intent,
                report_payload,
                deterministic_answer,
                image_data_urls=image_data_urls,
            )
        if llm_result.used and (
            not answer_respects_profile(answer, answer_profile)
            or not answer_uses_resolved_target(answer, target)
        ):
            answer = deterministic_answer
            llm_result = LLMResult(
                latency_ms=llm_result.latency_ms,
                error="upstream answer rejected by profile or target-identity validation",
            )
        synthesize_step.complete("upstream_llm" if llm_result.used else "deterministic_fallback")
        if image_data_urls and not llm_result.used:
            answer = deterministic_answer.rstrip() + (
                "\n\n## 图片分析状态\n"
                "- 图片已安全读取，但本次视觉模型不可用，因此没有假装识别图中走势。请稍后重试；"
                "若同时提供股票名称和代码，系统仍可先用结构化行情完成交叉核验。"
            )
        answer = deduplicate_repeated_blocks(answer)
        answer = prepend_research_notices(answer, resolution_notes)
        if "announcement" in topics:
            answer = append_missing_announcement_links(
                answer,
                announcement_analyses,
                max_items=2 if answer_profile == AnswerProfile.CONCISE else 3,
            )
        answer = append_context_safe_followups(
            answer,
            target,
            question=execution_question,
            intent=intent,
            topics=topics,
            technical=snapshot.technical,
        )
        review_step = context_step(context, "review")
        review_step.start()
        answer = guard_output(answer)
        review_step.complete("answer")
        report_payload["upstream_llm"] = llm_result.public_metadata(self.llm_configured)
        context.evidence = report_payload
        context.data_statuses = report_payload["statuses"]
        context.model_metadata = report_payload["upstream_llm"]
        compose_step = context_step(context, "compose_report")
        compose_step.start()
        compose_step.complete("report")
        context.complete()
        report_payload["research_context"] = context.public_metadata()
        report = compose_report(
            title,
            latest_question,
            report_payload,
            file_notes,
            guard_output(detailed_report_answer),
        )
        return ResearchOutput(title, answer, report, context=context), charts

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
        if not result.used:
            return deterministic_answer, result
        if institutional_report_complete(result.content, intent, question):
            return result.content, result
        # Preserve the auditable local report when an upstream model returns a
        # short-form answer. The model text remains available as a clearly
        # separated synthesis instead of replacing required evidence sections.
        combined = deterministic_answer.rstrip() + "\n\n## 模型综合补充\n" + result.content.strip()
        return combined, result


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


def context_step(context: ResearchContext, step_type: str) -> ResearchStep:
    return next(step for step in context.plan if step.step_type == step_type)


def institutional_report_complete(content: str, intent: str, question: str = "") -> bool:
    requirements = {
        "screening": (500, ("研究结论", "风险")),
        "backtest": (600, ("研究结论", "回测", "风险")),
        "announcement": (600, ("研究结论摘要", "公告", "风险")),
        "fundamental": (600, ("研究结论摘要", "基本面", "风险")),
        "technical": (700, ("研究结论摘要", "市场快照", "关键价位", "风险")),
    }
    if intent == "full_research":
        topics = research_topics(intent, question)
        required_sections = ["研究结论摘要", "风险"]
        if "technical" in topics:
            required_sections.append("市场快照")
        if "fundamental" in topics:
            required_sections.append("基本面")
        if "announcement" in topics:
            required_sections.append("公告")
        minimum_length = 700 + max(0, len(topics) - 1) * 200
        required = tuple(required_sections)
    else:
        minimum_length, required = requirements.get(
            intent,
            (700, ("研究结论摘要", "数据质量", "风险")),
        )
    value = content or ""
    return len(value) >= minimum_length and all(section in value for section in required)


def synthesis_evidence_for_intent(intent: str, evidence: dict, question: str) -> dict:
    """Keep upstream evidence scoped to the latest user request."""
    requested = research_topics(intent, question)

    keys = {"target", "attachments", "images", "research_context", "resolution_notes"}
    source_names = {"target"}
    if "technical" in requested:
        keys.update({"quote", "technical"})
        source_names.update({"market_quote", "market_kline"})
    if "fundamental" in requested:
        keys.add("fundamentals")
        source_names.add("fundamental")
    if "announcement" in requested:
        keys.update({"announcements", "announcement_analysis"})
        source_names.update({"cninfo_announcement", "announcement_attachment"})
    if "backtest" in requested:
        keys.add("backtest")

    result = {key: evidence.get(key) for key in keys if key in evidence}
    statuses = evidence.get("statuses") or evidence.get("data_statuses") or []
    result["statuses"] = [
        status for status in statuses
        if isinstance(status, dict) and str(status.get("source") or "") in source_names
    ]
    return result


def resolve_research_target(
    data_client: AShareDataClient,
    conversation: str,
    latest_question: str,
) -> tuple[Target | None, list[str]]:
    target = data_client.resolve_target(conversation, infer_target(conversation))
    return target, target_resolution_notes(latest_question, target)


def build_evidence_payload(
    *,
    target: Target | None,
    snapshot: MarketSnapshot,
    backtest_result: BacktestResult | None,
    file_notes: list[dict[str, str]],
    image_notes: list[dict[str, object]],
    announcement_analyses: list[dict],
    resolution_notes: list[str],
    image_only: bool,
) -> dict:
    return {
        "target": target.__dict__ if target else None,
        "quote": snapshot.quote,
        "technical": snapshot.technical,
        "fundamentals": snapshot.fundamentals,
        "announcements": snapshot.announcements[:8],
        "statuses": [
            status.__dict__ for status in snapshot.statuses
            if not (image_only and status.source == "target")
        ],
        "backtest": backtest_result.metrics if backtest_result else None,
        "attachments": file_notes,
        "images": image_notes,
        "resolution_notes": resolution_notes,
        "announcement_analysis": announcement_analyses,
    }


def answer_uses_resolved_target(answer: str, target: Target | None) -> bool:
    """Reject only explicit research-object contradictions from an upstream model."""
    if not target or not target.symbol:
        return True
    for line in str(answer or "").splitlines()[:30]:
        if "研究对象" not in line and "分析对象" not in line:
            continue
        codes = re.findall(r"(?<!\d)\d{6}(?!\d)", line)
        if codes and target.symbol not in codes:
            return False
    return True


def collect_snapshot(
    data_client: AShareDataClient,
    target: Target | None,
    *,
    include_announcement_text: bool,
    topics: set[str],
):
    """Call topic-aware clients while preserving older collect adapters."""
    parameters = inspect.signature(data_client.collect).parameters.values()
    supports_topics = any(
        parameter.name == "topics" or parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )
    kwargs = {"include_announcement_text": include_announcement_text}
    if supports_topics:
        kwargs["topics"] = topics
    return data_client.collect(target, **kwargs)


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
