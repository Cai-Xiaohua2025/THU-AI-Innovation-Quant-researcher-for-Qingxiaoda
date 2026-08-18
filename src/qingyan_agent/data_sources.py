"""Stable public-data access with graceful degradation."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from .announcement_reader import AnnouncementAttachmentReader
from .config import Settings
from .domain.indicators import (
    has_data_fields as domain_has_data_fields,
    technical_indicators as domain_technical_indicators,
)
from .contracts import DataErrorKind
from .infrastructure.cache import FileCacheStore
from .infrastructure.http import ResilientHttpClient
from .market_data.cninfo import (
    CNInfoProvider,
    cninfo_market_params as provider_cninfo_market_params,
    is_bse_symbol,
)
from .market_data.fundamentals import AkShareFundamentalProvider, normalize_fundamental_mapping
from .market_data.providers import (
    FunctionMarketDataProvider,
    fetch_eastmoney_klines,
    fetch_eastmoney_quote,
    fetch_sina_klines,
    fetch_sina_quote,
    fetch_tencent_klines,
    fetch_tencent_quote,
)
from .models import DataStatus, MarketSnapshot, Target
from .universe import (
    is_a_share_code,
    latest_user_text,
    parse_security_reference,
    security_search_queries,
)


LOGGER = logging.getLogger(__name__)


class AShareDataClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.announcement_reader = AnnouncementAttachmentReader(settings)
        self.cache = FileCacheStore(settings.cache_dir)
        self.http = ResilientHttpClient()
        dynamic_request = lambda *args, **kwargs: self._request(*args, **kwargs)
        self.cninfo_provider = CNInfoProvider(dynamic_request, settings.request_timeout_sec)
        self.fundamental_provider = AkShareFundamentalProvider()
        self.market_providers = {
            "tencent": FunctionMarketDataProvider(
                "tencent", dynamic_request, settings.request_timeout_sec,
                fetch_tencent_quote, fetch_tencent_klines,
            ),
            "sina": FunctionMarketDataProvider(
                "sina", dynamic_request, settings.request_timeout_sec,
                fetch_sina_quote, fetch_sina_klines,
            ),
            "eastmoney": FunctionMarketDataProvider(
                "eastmoney", dynamic_request, settings.request_timeout_sec,
                fetch_eastmoney_quote, fetch_eastmoney_klines,
            ),
        }

    def resolve_target(self, prompt: str, target: Target | None = None) -> Target | None:
        """Resolve an A-share code/name/orgId without trusting model-generated identity."""
        latest_reference = parse_security_reference(latest_user_text(prompt))
        if latest_reference.explicit:
            resolved_codes = [
                resolved for query in latest_reference.valid_codes
                if (resolved := self._resolve_security_query(query)) is not None
            ]
            resolved_names = [
                resolved for query in latest_reference.name_queries
                if (resolved := self._resolve_security_query(query)) is not None
            ]
            code_symbols = {item.symbol for item in resolved_codes}
            name_symbols = {item.symbol for item in resolved_names}
            if code_symbols and name_symbols and code_symbols.isdisjoint(name_symbols):
                return None
            if resolved_codes:
                return resolved_codes[0]
            if resolved_names:
                return resolved_names[0]
            # A valid current-turn code remains a safer fallback than an older
            # conversation target when identity providers are temporarily down.
            if latest_reference.valid_codes:
                code = latest_reference.valid_codes[0]
                return explicit_target_fallback(code, target)
            return None

        if target and target.symbol:
            cached = self._read_security_cache(target.symbol)
            if cached:
                return merge_target(target, cached)

        for query in security_search_queries(prompt, target):
            resolved = self._resolve_security_query(query, target)
            if resolved:
                return resolved
        return target

    def _resolve_security_query(
        self,
        query: str,
        target: Target | None = None,
    ) -> Target | None:
        cached = self._find_cached_security(query)
        if cached:
            return merge_target(target, cached)
        try:
            match = self.cninfo_provider.resolve_security(query, target)
            if not match:
                return None
            identity = {
                "market": "CNStock",
                "symbol": str(match.get("code") or ""),
                "name": str(match.get("zwjc") or ""),
                "org_id": str(match.get("orgId") or ""),
                "source": "cninfo_top_search",
                "fetched_at": now_iso(),
            }
            self._write_cache(f"security_{identity['symbol']}.json", identity)
            return merge_target(target, identity)
        except Exception:
            return None

    def collect(
        self,
        target: Target | None,
        *,
        include_announcement_text: bool = False,
        topics: set[str] | None = None,
    ) -> MarketSnapshot:
        if target:
            target = self.resolve_target(target.symbol or target.name, target)
        snapshot = MarketSnapshot(target=target)
        if not target:
            snapshot.statuses.append(DataStatus(
                "target",
                False,
                "未识别到明确 A 股标的。",
                DataErrorKind.INVALID_INPUT,
            ))
            return snapshot
        requested = set(topics or {"technical", "fundamental", "announcement"})
        unexpected_errors: list[DataStatus] = []
        with ThreadPoolExecutor(
            max_workers=self.settings.data_collection_workers,
            thread_name_prefix="qingyan-collect",
        ) as executor:
            futures = {}
            if "technical" in requested or "backtest" in requested:
                futures["quote"] = executor.submit(self.quote, target)
                futures["klines"] = executor.submit(self.klines, target, 180)
            if "fundamental" in requested:
                futures["fundamentals"] = executor.submit(self.fundamentals, target)
            if "announcement" in requested:
                futures["announcements"] = executor.submit(
                    self.announcements,
                    target,
                    include_text=include_announcement_text,
                )
            results: dict[str, Any] = {
                "quote": {},
                "klines": [],
                "fundamentals": {},
                "announcements": [],
            }
            for source, future in futures.items():
                try:
                    results[source] = future.result()
                except Exception as exc:
                    results[source] = [] if source in {"klines", "announcements"} else {}
                    unexpected_errors.append(DataStatus(
                        f"collect:{source}",
                        False,
                        f"unexpected {exc.__class__.__name__}: {str(exc)[:120]}",
                        DataErrorKind.UNEXPECTED,
                    ))
        snapshot.quote = results["quote"]
        snapshot.klines = results["klines"]
        if "technical" in requested or "backtest" in requested:
            snapshot.technical = domain_technical_indicators(snapshot.klines)
            annotate_intraday_bar(snapshot.quote, snapshot.technical)
        snapshot.fundamentals = results["fundamentals"]
        snapshot.announcements = results["announcements"]
        snapshot.statuses.extend(unexpected_errors)
        if "technical" in requested or "backtest" in requested:
            snapshot.statuses.extend([
                DataStatus(
                "market_quote",
                bool(snapshot.quote.get("price")),
                snapshot.quote.get("message") or f"source={snapshot.quote.get('source', 'unknown')}",
                None if snapshot.quote.get("price") else DataErrorKind.UPSTREAM_UNAVAILABLE,
                ),
                DataStatus(
                "market_kline",
                bool(snapshot.klines),
                f"{len(snapshot.klines)} rows; source={snapshot.klines[-1].get('source', 'unknown') if snapshot.klines else 'none'}",
                None if snapshot.klines else DataErrorKind.UPSTREAM_UNAVAILABLE,
                ),
            ])
        if "fundamental" in requested:
            snapshot.statuses.append(DataStatus(
                "fundamental",
                has_data_fields(snapshot.fundamentals),
                snapshot.fundamentals.get("_message")
                or f"source={snapshot.fundamentals.get('source', 'unknown')}",
                None if has_data_fields(snapshot.fundamentals) else DataErrorKind.UPSTREAM_UNAVAILABLE,
            ))
        if "announcement" in requested:
            snapshot.statuses.append(DataStatus(
                "cninfo_announcement",
                bool(snapshot.announcements),
                f"{len(snapshot.announcements)} rows",
                None if snapshot.announcements else DataErrorKind.UPSTREAM_UNAVAILABLE,
            ))
        if "announcement" in requested and include_announcement_text:
            attachments = [
                item.get("attachment") for item in snapshot.announcements
                if isinstance(item.get("attachment"), dict)
            ]
            extracted = sum(item.get("status") == "ok" for item in attachments)
            snapshot.statuses.append(DataStatus(
                "announcement_attachment",
                extracted > 0,
                f"{extracted}/{len(attachments)} PDFs extracted; "
                f"max_files={self.settings.announcement_attachment_max_files}",
            ))
        return snapshot

    def quote(self, target: Target) -> dict[str, Any]:
        cache_key = f"quote_{target.symbol}.json"
        cached = self._read_quote_cache(cache_key, target.symbol, max_age_sec=30)
        if cached is not None:
            return cached
        stale = self._read_quote_cache(cache_key, target.symbol)
        errors = []
        for source_name, fetcher in (
            ("tencent_quote", self._fetch_tencent_quote),
            ("sina_quote", self._fetch_sina_quote),
            ("eastmoney_push2", self._fetch_eastmoney_quote),
        ):
            try:
                result = fetcher(target)
                if str(result.get("symbol") or "") != target.symbol or not result.get("price"):
                    raise ValueError("quote identity or price validation failed")
                result["source"] = source_name
                result["fetched_at"] = now_iso()
                result["is_stale"] = False
                result["data_mode"] = "online_with_short_cache"
                result["cache_ttl_sec"] = 30
                self._write_cache(cache_key, result)
                return result
            except Exception as exc:
                errors.append(f"{source_name}: {exc.__class__.__name__}: {str(exc)[:100]}")
        if stale is not None:
            result = dict(stale)
            result["is_stale"] = True
            result["data_mode"] = "stale_cache"
            result["message"] = "在线行情源不可用，使用已校验的历史缓存；请核对 fetched_at。"
            return result
        return {
            "symbol": target.symbol,
            "name": target.name,
            "source": "market_quote_unavailable",
            "message": "quote unavailable: " + " | ".join(errors)[:320],
        }

    def klines(self, target: Target, limit: int = 180) -> list[dict[str, Any]]:
        cache_key = f"kline_{target.symbol}_{limit}.json"
        cached = self._read_kline_cache(cache_key, target.symbol, max_age_sec=180)
        if cached is not None:
            return cached
        stale = self._read_kline_cache(cache_key, target.symbol)
        errors = []
        for source_name, fetcher in (
            ("tencent_qfq_kline", self._fetch_tencent_klines),
            ("sina_unadjusted_kline", self._fetch_sina_klines),
            ("eastmoney_qfq_kline", self._fetch_eastmoney_klines),
        ):
            try:
                rows = fetcher(target, limit)
                if len(rows) < 20:
                    raise ValueError("insufficient kline rows")
                fetched_at = now_iso()
                for row in rows:
                    row["source"] = source_name
                    row["fetched_at"] = fetched_at
                    row["is_stale"] = False
                    row["price_adjustment"] = "不复权" if source_name == "sina_unadjusted_kline" else "前复权"
                    row["data_mode"] = "online_with_short_cache"
                    row["cache_ttl_sec"] = 180
                self._write_cache(cache_key, {
                    "symbol": target.symbol,
                    "name": target.name,
                    "source": source_name,
                    "fetched_at": fetched_at,
                    "rows": rows,
                })
                return rows
            except Exception as exc:
                errors.append(f"{source_name}:{exc.__class__.__name__}")
                continue
        if stale:
            return [dict(row, is_stale=True) for row in stale]
        if errors:
            LOGGER.warning(
                "K-line sources unavailable symbol=%s errors=%s",
                target.symbol,
                ",".join(errors),
            )
        return []

    def announcements(self, target: Target, *, include_text: bool = False) -> list[dict[str, Any]]:
        cache_key = f"announcements_{target.symbol}.json"
        cached = self._read_announcement_cache(cache_key, target.symbol, max_age_sec=3600)
        if cached is not None:
            return self.announcement_reader.enrich(cached) if include_text else cached
        stale = self._read_announcement_cache(cache_key, target.symbol)
        if not target.org_id:
            target = self.resolve_target(target.symbol or target.name, target) or target
        if not target.org_id:
            rows = stale or []
            return self.announcement_reader.enrich(rows) if include_text else rows
        try:
            rows = self.cninfo_provider.announcements(
                target,
                lookback_days=self.settings.announcement_lookback_days,
            )
            self._write_cache(cache_key, {
                "symbol": target.symbol,
                "name": target.name,
                "org_id": target.org_id,
                "source": "cninfo",
                "fetched_at": now_iso(),
                "rows": rows,
            })
            return self.announcement_reader.enrich(rows) if include_text else rows
        except Exception as exc:
            LOGGER.warning(
                "CNINFO announcements unavailable symbol=%s error=%s",
                target.symbol,
                exc.__class__.__name__,
            )
            rows = stale or []
            return self.announcement_reader.enrich(rows) if include_text else rows

    def _fetch_tencent_quote(self, target: Target) -> dict[str, Any]:
        return self.market_providers["tencent"].quote(target)

    def _fetch_sina_quote(self, target: Target) -> dict[str, Any]:
        return self.market_providers["sina"].quote(target)

    def _fetch_eastmoney_quote(self, target: Target) -> dict[str, Any]:
        return self.market_providers["eastmoney"].quote(target)

    def _fetch_tencent_klines(self, target: Target, limit: int) -> list[dict[str, Any]]:
        return self.market_providers["tencent"].klines(target, limit)

    def _fetch_sina_klines(self, target: Target, limit: int) -> list[dict[str, Any]]:
        return self.market_providers["sina"].klines(target, limit)

    def _fetch_eastmoney_klines(self, target: Target, limit: int) -> list[dict[str, Any]]:
        return self.market_providers["eastmoney"].klines(target, limit)

    def fundamentals(self, target: Target) -> dict[str, Any]:
        cache_key = f"fundamental_{target.symbol}.json"
        if not self.settings.enable_akshare:
            return {
                "_message": (
                    "optional akshare fundamentals disabled; "
                    "set QINGYAN_ENABLE_AKSHARE=true to enable richer fields."
                )
            }
        cached = self._read_cache(cache_key, max_age_sec=86400)
        if isinstance(cached, dict) and has_data_fields(cached):
            normalized = normalize_fundamental_mapping(cached)
            if normalized != cached:
                self._write_cache(cache_key, normalized)
            return normalized
        data = normalize_fundamental_mapping(self.fundamental_provider.fundamentals(target))
        self._write_cache(cache_key, data)
        return data

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        return self.http.request(method, url, **kwargs)

    def _read_security_cache(self, symbol: str) -> dict[str, Any] | None:
        value = self._read_cache(f"security_{symbol}.json", max_age_sec=30 * 86400)
        if not isinstance(value, dict) or str(value.get("symbol") or "") != symbol:
            return None
        if not value.get("name") or not value.get("org_id"):
            return None
        return value

    def _find_cached_security(self, query: str) -> dict[str, Any] | None:
        if is_a_share_code(query):
            return self._read_security_cache(query)
        try:
            for path in self.settings.cache_dir.glob("security_*.json"):
                value = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(value, dict) and str(value.get("name") or "").lower() == query.lower():
                    return value
        except Exception:
            return None
        return None

    def _read_quote_cache(self, key: str, symbol: str, max_age_sec: int | None = None) -> dict[str, Any] | None:
        value = self._read_cache(key, max_age_sec=max_age_sec)
        if not isinstance(value, dict) or str(value.get("symbol") or "") != symbol:
            return None
        if not value.get("price"):
            return None
        value.setdefault("volume_unit", "手")
        value.pop("volume_shares", None)
        return value

    def _read_kline_cache(self, key: str, symbol: str, max_age_sec: int | None = None) -> list[dict[str, Any]] | None:
        value = self._read_cache(key, max_age_sec=max_age_sec)
        if not isinstance(value, dict) or str(value.get("symbol") or "") != symbol:
            return None
        rows = value.get("rows")
        if not isinstance(rows, list) or not rows:
            return None
        return [row for row in rows if isinstance(row, dict)]

    def _read_announcement_cache(self, key: str, symbol: str, max_age_sec: int | None = None) -> list[dict[str, Any]] | None:
        value = self._read_cache(key, max_age_sec=max_age_sec)
        if not isinstance(value, dict) or str(value.get("symbol") or "") != symbol:
            return None
        rows = value.get("rows")
        if not isinstance(rows, list):
            return None
        if any(str(row.get("symbol") or "") != symbol for row in rows if isinstance(row, dict)):
            return None
        return [row for row in rows if isinstance(row, dict)]

    def _cache_path(self, key: str) -> Path:
        return self.cache.path_for(key)

    def _read_cache(self, key: str, max_age_sec: int | None = None) -> Any:
        return self.cache.read(key, max_age_sec=max_age_sec)

    def _write_cache(self, key: str, value: Any) -> None:
        if not self.cache.write(key, value):
            LOGGER.warning("Cache write failed key=%s", key)


def merge_target(target: Target | None, identity: dict[str, Any]) -> Target:
    symbol = str(identity.get("symbol") or (target.symbol if target else ""))
    name = str(identity.get("name") or (target.name if target else ""))
    org_id = str(identity.get("org_id") or (target.org_id if target else ""))
    return Target(
        market=(target.market if target else "CNStock"),
        symbol=symbol,
        name=name,
        sector=(target.sector if target else ""),
        confidence=max(target.confidence if target else 0, 96),
        org_id=org_id,
    )


def explicit_target_fallback(code: str, target: Target | None = None) -> Target:
    if target and target.symbol == code:
        return target
    return Target("CNStock", code, confidence=78)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def annotate_intraday_bar(quote: dict[str, Any], technical: dict[str, Any]) -> None:
    """Mark indicators derived from an unfinished current-day daily bar."""
    market_time = "".join(character for character in str(quote.get("market_time") or "") if character.isdigit())
    data_date = str(technical.get("data_date") or "").replace("-", "")
    technical["is_intraday"] = False
    technical["bar_status"] = "completed_daily_bar"
    if len(market_time) < 12 or len(data_date) != 8 or market_time[:8] != data_date:
        return
    hour_minute = int(market_time[8:12])
    if 915 <= hour_minute < 1500:
        technical["is_intraday"] = True
        technical["bar_status"] = "intraday_partial"
        technical["market_snapshot_time"] = market_time[:14]


def tencent_market_symbol(symbol: str) -> str:
    value = str(symbol).strip()
    if is_bse_symbol(value):
        return "bj" + value
    return ("sh" if value.startswith("6") else "sz") + value


def eastmoney_secid(symbol: str) -> str:
    symbol = str(symbol).strip()
    market_id = "1" if symbol.startswith("6") else "0"
    return f"{market_id}.{symbol}"


def cninfo_market_params(symbol: str) -> tuple[str, str]:
    """Compatibility export for callers that historically imported this facade helper."""
    return provider_cninfo_market_params(symbol)


def normalize_em_price(value: Any) -> float | None:
    number = to_float(value)
    if number is None:
        return None
    return round(number / 100, 4)


def normalize_em_ratio(value: Any) -> float | None:
    number = to_float(value)
    if number is None:
        return None
    return round(number / 100, 4)


def to_float(value: Any) -> float | None:
    try:
        if value in (None, "", "-"):
            return None
        return float(value)
    except Exception:
        return None


technical_indicators = domain_technical_indicators
has_data_fields = domain_has_data_fields
