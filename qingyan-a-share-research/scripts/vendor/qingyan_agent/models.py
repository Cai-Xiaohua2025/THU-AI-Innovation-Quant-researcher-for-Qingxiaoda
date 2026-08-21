"""Shared data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import (
    AnnouncementRecord,
    Artifact,
    DataErrorKind,
    FundamentalData,
    KlineBar,
    QuoteData,
    ResearchContext,
    TechnicalIndicators,
)


@dataclass(frozen=True)
class Target:
    market: str
    symbol: str
    name: str = ""
    sector: str = ""
    confidence: int = 50
    org_id: str = ""


@dataclass
class DataStatus:
    source: str
    ok: bool
    message: str = ""
    error_kind: DataErrorKind | None = None


@dataclass
class MarketSnapshot:
    target: Target | None
    quote: QuoteData = field(default_factory=dict)
    klines: list[KlineBar] = field(default_factory=list)
    technical: TechnicalIndicators = field(default_factory=dict)
    fundamentals: FundamentalData = field(default_factory=dict)
    announcements: list[AnnouncementRecord] = field(default_factory=list)
    statuses: list[DataStatus] = field(default_factory=list)


@dataclass
class ScreeningResult:
    universe_name: str
    rows: list[dict[str, Any]]
    statuses: list[DataStatus] = field(default_factory=list)


@dataclass
class BacktestResult:
    source: str
    metrics: dict[str, Any]
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)


@dataclass
class ResearchOutput:
    title: str
    answer: str
    report_markdown: str
    attachments: list[Artifact] = field(default_factory=list)
    report_enabled: bool = True
    context: ResearchContext | None = None
