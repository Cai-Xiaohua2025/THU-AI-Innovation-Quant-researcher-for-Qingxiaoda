"""Typed cross-module contracts for normalized research data."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, TypedDict
from uuid import uuid4


class QuoteData(TypedDict, total=False):
    symbol: str
    name: str
    price: float
    open: float
    high: float
    low: float
    previous_close: float
    change_pct: float
    volume: float
    volume_unit: str
    amount: float
    market_time: str
    source: str
    fetched_at: str
    is_stale: bool
    data_mode: str
    cache_ttl_sec: int
    message: str


class KlineBar(TypedDict, total=False):
    date: str
    open: float
    close: float
    high: float
    low: float
    volume: float
    amount: float | None
    source: str
    fetched_at: str
    is_stale: bool
    price_adjustment: str
    data_mode: str
    cache_ttl_sec: int


class TechnicalIndicators(TypedDict, total=False):
    status: str
    message: str
    last_close: float
    ma5: float | None
    ma20: float | None
    ma60: float | None
    return_5d_pct: float | None
    return_20d_pct: float | None
    return_60d_pct: float | None
    annualized_volatility_pct: float | None
    volatility_percentile_in_sample_pct: float | None
    relative_volume_20d: float | None
    volume_5d_change_pct: float | None
    trend_label: str
    trend_score: int
    trend_rule_version: str
    trend_basis: list[str]
    price_adjustment: str
    source: str | None
    data_date: str | None
    fetched_at: str | None
    is_stale: bool
    sample_size: int
    bar_status: str
    is_intraday: bool
    market_snapshot_time: str


class FundamentalData(TypedDict, total=False):
    source: str
    fetched_at: str
    data_date: str
    _message: str
    _error: str


class AnnouncementRecord(TypedDict, total=False):
    symbol: str
    name: str
    org_id: str
    title: str
    date: str
    url: str
    source: str
    attachment: dict[str, Any]


class ScreeningFactors(TypedDict, total=False):
    momentum_20d: float
    trend: float
    volatility_control: float
    liquidity_activity: float
    financial_quality: float | str
    quote_available: bool


class Artifact(TypedDict, total=False):
    fileName: str
    fileUrl: str
    fileType: str
    mimeType: str
    fileSize: int
    artifactId: str
    createdAt: str
    expiresAt: str
    sha256: str


class EvidenceBundle(TypedDict, total=False):
    target: dict[str, Any] | None
    quote: QuoteData
    technical: TechnicalIndicators
    fundamentals: FundamentalData
    announcements: list[AnnouncementRecord]
    announcement_analysis: list[AnnouncementAnalysis]
    statuses: list[dict[str, Any]]
    backtest: dict[str, Any] | None
    attachments: list[dict[str, Any]]
    images: list[dict[str, Any]]
    upstream_llm: dict[str, Any]


class ResearchStepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AnswerProfile(str, Enum):
    CONCISE = "concise"
    STANDARD = "standard"
    DETAILED = "detailed"


class AnnouncementAnalysis(TypedDict, total=False):
    title: str
    date: str
    source_url: str
    facts: list[str]
    inferences: list[str]
    potential_impacts: list[str]
    risks: list[str]
    verification_items: list[str]
    source_pages: list[int]
    source_status: str
    importance_score: int


class DataErrorKind(str, Enum):
    INVALID_INPUT = "invalid_input"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    INVALID_RESPONSE = "invalid_response"
    TIMEOUT = "timeout"
    CACHE_ERROR = "cache_error"
    UNEXPECTED = "unexpected"


@dataclass
class ResearchStep:
    step_id: str
    step_type: str
    description: str
    required: bool = True
    status: ResearchStepStatus = ResearchStepStatus.PENDING
    started_at: str | None = None
    completed_at: str | None = None
    error: str = ""
    evidence_keys: list[str] = field(default_factory=list)

    def start(self) -> None:
        self.status = ResearchStepStatus.RUNNING
        self.started_at = now_iso()

    def complete(self, *evidence_keys: str) -> None:
        self.status = ResearchStepStatus.COMPLETED
        self.completed_at = now_iso()
        self.evidence_keys.extend(key for key in evidence_keys if key)

    def fail(self, error: str) -> None:
        self.status = ResearchStepStatus.FAILED
        self.completed_at = now_iso()
        self.error = str(error)[:240]

    def skip(self, reason: str = "") -> None:
        self.status = ResearchStepStatus.SKIPPED
        self.completed_at = now_iso()
        self.error = str(reason)[:240]


@dataclass
class ResearchContext:
    question: str
    intent: str
    request_id: str = field(default_factory=lambda: uuid4().hex)
    conversation_turns: list[str] = field(default_factory=list)
    target: dict[str, Any] | None = None
    plan: list[ResearchStep] = field(default_factory=list)
    evidence: EvidenceBundle = field(default_factory=EvidenceBundle)
    missing_evidence: list[str] = field(default_factory=list)
    data_statuses: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    evidence_completeness: dict[str, Any] = field(default_factory=dict)
    artifacts: list[Artifact] = field(default_factory=list)
    model_metadata: dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: now_iso())
    completed_at: str | None = None

    def add_step(self, step_type: str, description: str, *, required: bool = True) -> ResearchStep:
        step = ResearchStep(
            step_id=f"step-{len(self.plan) + 1}",
            step_type=step_type,
            description=description,
            required=required,
        )
        self.plan.append(step)
        return step

    def complete(self) -> None:
        self.completed_at = now_iso()

    def public_metadata(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "intent": self.intent,
            "target": self.target,
            "steps": [asdict(step) for step in self.plan],
            "missing_evidence": self.missing_evidence,
            "warnings": self.warnings,
            "evidence_completeness": self.evidence_completeness,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")
