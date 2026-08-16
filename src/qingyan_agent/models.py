"""Shared data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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


@dataclass
class MarketSnapshot:
    target: Target | None
    quote: dict[str, Any] = field(default_factory=dict)
    klines: list[dict[str, Any]] = field(default_factory=list)
    technical: dict[str, Any] = field(default_factory=dict)
    fundamentals: dict[str, Any] = field(default_factory=dict)
    announcements: list[dict[str, Any]] = field(default_factory=list)
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
    attachments: list[dict[str, Any]] = field(default_factory=list)
    report_enabled: bool = True
