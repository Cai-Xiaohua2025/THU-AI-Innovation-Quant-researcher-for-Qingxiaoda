"""Rule-driven research plans and deterministic evidence completeness checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from .contracts import ResearchStep
from .domain.indicators import has_data_fields


@dataclass(frozen=True)
class EvidenceRequirement:
    key: str
    description: str
    required: bool = True


@dataclass
class EvidenceCheckResult:
    score: int
    grade: str
    satisfied: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def generate_research_plan(intent: str, *, has_images: bool = False) -> list[ResearchStep]:
    """Build a bounded, auditable plan without asking an LLM to choose tools."""
    specs: list[tuple[str, str, bool]] = [("interpret", "理解问题并识别研究意图", True)]
    if intent == "greeting" and not has_images:
        specs.append(("respond", "返回能力说明", False))
    elif intent == "screening":
        specs.extend([
            ("screening", "收集候选池证据并执行多因子评分", True),
            ("analyze", "生成确定性筛选分析", True),
            ("synthesize", "可选调用上游模型综合证据", False),
            ("review", "执行合规与事实边界检查", True),
            ("compose_report", "组织研究报告与附件元数据", True),
        ])
    else:
        specs.extend([
            ("resolve_target", "解析并核验 A 股研究标的", not has_images),
            ("collect_evidence", "收集当前研究意图所需的结构化证据", True),
        ])
        if intent == "backtest":
            specs.append(("backtest", "执行 MA10/MA30 历史研究回测", True))
        specs.extend([
            ("analyze", "生成确定性研究分析", True),
            ("synthesize", "可选调用上游模型综合证据", False),
            ("review", "执行合规与事实边界检查", True),
            ("compose_report", "组织研究报告与附件元数据", True),
        ])
    return [
        ResearchStep(
            step_id=f"step-{index}",
            step_type=step_type,
            description=description,
            required=required,
        )
        for index, (step_type, description, required) in enumerate(specs, start=1)
    ]


def evidence_requirements(
    intent: str,
    evidence: dict[str, Any],
    question: str = "",
) -> list[EvidenceRequirement]:
    valid_images = any(
        isinstance(item, dict) and item.get("status") == "ok"
        for item in evidence.get("images") or []
    )
    if intent == "screening":
        return [EvidenceRequirement("screening", "至少一个可解释的筛选结果")]
    if valid_images and not evidence.get("target"):
        return [EvidenceRequirement("images", "至少一张通过安全校验的图片")]

    requirements = [EvidenceRequirement("target", "已核验的 A 股标的")]
    if intent == "technical":
        requirements.extend([
            EvidenceRequirement("quote", "有效实时或缓存行情"),
            EvidenceRequirement("technical", "基于足量 K 线计算的技术指标"),
        ])
    elif intent == "fundamental":
        requirements.append(EvidenceRequirement("fundamentals", "至少一个有效财务指标"))
    elif intent == "announcement":
        requirements.append(EvidenceRequirement("announcements", "标的一致的巨潮公告记录"))
    elif intent == "backtest":
        requirements.extend([
            EvidenceRequirement("technical", "基于足量 K 线计算的技术指标"),
            EvidenceRequirement("backtest", "成功完成的本地或远程回测"),
        ])
    else:
        requested = research_topics(intent, question)
        if "technical" in requested:
            requirements.extend([
                EvidenceRequirement("quote", "有效实时或缓存行情"),
                EvidenceRequirement("technical", "基于足量 K 线计算的技术指标"),
            ])
        if "fundamental" in requested:
            requirements.append(EvidenceRequirement("fundamentals", "至少一个有效财务指标"))
        if "announcement" in requested:
            requirements.append(EvidenceRequirement("announcements", "标的一致的巨潮公告记录"))
    return requirements


def evaluate_evidence(
    intent: str,
    evidence: dict[str, Any],
    question: str = "",
) -> EvidenceCheckResult:
    validators: dict[str, Callable[[Any], bool]] = {
        "target": lambda value: isinstance(value, dict) and bool(value.get("symbol")),
        "quote": lambda value: isinstance(value, dict) and positive_number(value.get("price")),
        "technical": lambda value: isinstance(value, dict)
        and value.get("status") != "insufficient_data"
        and positive_number(value.get("last_close")),
        "fundamentals": lambda value: isinstance(value, dict) and has_data_fields(value),
        "announcements": lambda value: isinstance(value, list) and bool(value)
        and all(isinstance(item, dict) and item.get("symbol") for item in value),
        "backtest": lambda value: isinstance(value, dict)
        and value.get("status") not in {None, "insufficient_data", "failed"},
        "screening": lambda value: isinstance(value, list) and bool(value),
        "images": lambda value: isinstance(value, list)
        and any(isinstance(item, dict) and item.get("status") == "ok" for item in value),
    }
    requirements = evidence_requirements(intent, evidence, question)
    satisfied: list[str] = []
    missing: list[str] = []
    for requirement in requirements:
        valid = validators[requirement.key](evidence.get(requirement.key))
        (satisfied if valid else missing).append(requirement.key)
    total = len(requirements)
    score = round(len(satisfied) / total * 100) if total else 100
    grade = "complete" if score == 100 else "partial" if score > 0 else "insufficient"
    warnings = [
        f"缺少{requirement.description}"
        for requirement in requirements
        if requirement.key in missing
    ]
    required_keys = {requirement.key for requirement in requirements}
    source_requirement = {
        "target": "target",
        "market_quote": "quote",
        "market_kline": "technical",
        "fundamental": "fundamentals",
        "cninfo_announcement": "announcements",
        "announcement_attachment": "announcements",
    }
    failed_sources = [
        str(status.get("source")) for status in evidence.get("statuses") or []
        if isinstance(status, dict)
        and not status.get("ok")
        and status.get("source")
        and source_requirement.get(str(status.get("source")), "") in required_keys
    ]
    if failed_sources:
        warnings.append("数据源不可用或证据为空：" + "、".join(dict.fromkeys(failed_sources)))
    return EvidenceCheckResult(score, grade, satisfied, missing, warnings)


def requested_topics(question: str) -> set[str]:
    value = str(question or "").lower()
    topics: set[str] = set()
    if any(term in value for term in ("综合", "全面", "完整研究", "深度研究")):
        topics.add("comprehensive")
    if any(term in value for term in (
        "走势", "趋势", "技术", "k线", "均线", "行情", "股价", "量价", "支撑", "压力",
    )):
        topics.add("technical")
    if any(term in value for term in ("公告", "消息", "新闻", "事件", "催化", "异动")):
        topics.add("announcement")
    if any(term in value for term in (
        "财报", "基本面", "业绩", "利润", "营收", "现金流", "负债", "估值", "roe", "pe", "pb",
    )):
        topics.add("fundamental")
    return topics


def research_topics(intent: str, question: str = "") -> set[str]:
    """Resolve the evidence/section scope from the current user turn only."""
    fixed = {
        "technical": {"technical"},
        "fundamental": {"fundamental"},
        "announcement": {"announcement"},
        "backtest": {"technical", "backtest"},
    }
    if intent in fixed:
        return set(fixed[intent])
    if intent != "full_research":
        return set()
    requested = requested_topics(question)
    if not requested or "comprehensive" in requested:
        return {"technical", "fundamental", "announcement"}
    return requested - {"comprehensive"}


def positive_number(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False
