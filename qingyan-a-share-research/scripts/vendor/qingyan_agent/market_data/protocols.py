"""Lightweight provider contracts for normalized public-market data."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..models import Target


@runtime_checkable
class DataProvider(Protocol):
    """Common identity shared by all external-data providers."""

    provider_name: str


@runtime_checkable
class QuoteProvider(DataProvider, Protocol):
    def quote(self, target: Target) -> dict[str, Any]: ...


@runtime_checkable
class KlineProvider(DataProvider, Protocol):
    def klines(self, target: Target, limit: int) -> list[dict[str, Any]]: ...


@runtime_checkable
class MarketDataProvider(QuoteProvider, KlineProvider, Protocol):
    """Provider able to return both a quote and normalized daily bars."""


@runtime_checkable
class SecurityResolverProvider(DataProvider, Protocol):
    def resolve_security(self, query: str, target: Target | None = None) -> dict[str, Any] | None: ...


@runtime_checkable
class AnnouncementProvider(DataProvider, Protocol):
    def announcements(self, target: Target, *, lookback_days: int) -> list[dict[str, Any]]: ...


@runtime_checkable
class FundamentalProvider(DataProvider, Protocol):
    def fundamentals(self, target: Target) -> dict[str, Any]: ...
