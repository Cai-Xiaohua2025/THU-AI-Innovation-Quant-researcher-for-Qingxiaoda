"""Stable public-data access with graceful degradation."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from .announcement_reader import AnnouncementAttachmentReader
from .config import Settings
from .models import DataStatus, MarketSnapshot, Target
from .universe import is_a_share_code, security_search_queries


EASTMONEY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
}

CNINFO_HEADERS = {
    "User-Agent": EASTMONEY_HEADERS["User-Agent"],
    "Referer": "http://www.cninfo.com.cn/",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

TENCENT_HEADERS = {
    "User-Agent": EASTMONEY_HEADERS["User-Agent"],
    "Referer": "https://gu.qq.com/",
}

SINA_HEADERS = {
    "User-Agent": EASTMONEY_HEADERS["User-Agent"],
    "Referer": "https://finance.sina.com.cn/",
}


class AShareDataClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.announcement_reader = AnnouncementAttachmentReader(settings)

    def resolve_target(self, prompt: str, target: Target | None = None) -> Target | None:
        """Resolve an A-share code/name/orgId without trusting model-generated identity."""
        if target and target.symbol:
            cached = self._read_security_cache(target.symbol)
            if cached:
                return merge_target(target, cached)

        for query in security_search_queries(prompt, target):
            cached = self._find_cached_security(query)
            if cached:
                return merge_target(target, cached)
            try:
                response = self._request(
                    "POST",
                    "https://www.cninfo.com.cn/new/information/topSearch/query",
                    data={"keyWord": query, "maxSecNum": "10"},
                    headers=CNINFO_HEADERS,
                    timeout=self.settings.request_timeout_sec,
                )
                response.raise_for_status()
                rows = response.json()
                match = select_cninfo_security(rows, query, target)
                if match:
                    match = self._prefer_current_bse_security(match)
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
                continue
        return target

    def collect(self, target: Target | None, *, include_announcement_text: bool = False) -> MarketSnapshot:
        if target:
            target = self.resolve_target(target.symbol or target.name, target)
        snapshot = MarketSnapshot(target=target)
        if not target:
            snapshot.statuses.append(DataStatus("target", False, "未识别到明确 A 股标的。"))
            return snapshot
        snapshot.quote = self.quote(target)
        snapshot.klines = self.klines(target, limit=180)
        snapshot.technical = technical_indicators(snapshot.klines)
        snapshot.fundamentals = self.fundamentals(target)
        snapshot.announcements = self.announcements(target, include_text=include_announcement_text)
        snapshot.statuses.extend([
            DataStatus(
                "market_quote",
                bool(snapshot.quote.get("price")),
                snapshot.quote.get("message") or f"source={snapshot.quote.get('source', 'unknown')}",
            ),
            DataStatus(
                "market_kline",
                bool(snapshot.klines),
                f"{len(snapshot.klines)} rows; source={snapshot.klines[-1].get('source', 'unknown') if snapshot.klines else 'none'}",
            ),
            DataStatus("fundamental", has_data_fields(snapshot.fundamentals), snapshot.fundamentals.get("_message", "")),
            DataStatus("cninfo_announcement", bool(snapshot.announcements), f"{len(snapshot.announcements)} rows"),
        ])
        if include_announcement_text:
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
            except Exception:
                continue
        if stale:
            return [dict(row, is_stale=True) for row in stale]
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
        today = datetime.now()
        start = today - timedelta(days=self.settings.announcement_lookback_days)
        url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
        payload = {
            "stock": f"{target.symbol},{target.org_id}",
            "tabName": "fulltext",
            "pageSize": "12",
            "pageNum": "1",
            "column": cninfo_market_params(target.symbol)[0],
            "category": "",
            "plate": cninfo_market_params(target.symbol)[1],
            "seDate": f"{start:%Y-%m-%d}~{today:%Y-%m-%d}",
            "searchkey": "",
            "secid": "",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
        try:
            response = self._request(
                "POST",
                url,
                data=payload,
                headers=CNINFO_HEADERS,
                timeout=self.settings.request_timeout_sec,
            )
            response.raise_for_status()
            data = response.json()
            rows = []
            for item in data.get("announcements") or []:
                if str(item.get("secCode") or "") != target.symbol:
                    continue
                adjunct = item.get("adjunctUrl") or ""
                rows.append({
                    "symbol": str(item.get("secCode") or target.symbol),
                    "name": str(item.get("secName") or target.name),
                    "org_id": str(item.get("orgId") or target.org_id),
                    "title": clean_html(item.get("announcementTitle") or ""),
                    "date": format_cninfo_date(item.get("announcementTime")),
                    "url": f"https://static.cninfo.com.cn/{adjunct}" if adjunct else "",
                    "source": "cninfo",
                })
            self._write_cache(cache_key, {
                "symbol": target.symbol,
                "name": target.name,
                "org_id": target.org_id,
                "source": "cninfo",
                "fetched_at": now_iso(),
                "rows": rows,
            })
            return self.announcement_reader.enrich(rows) if include_text else rows
        except Exception:
            rows = stale or []
            return self.announcement_reader.enrich(rows) if include_text else rows

    def _fetch_tencent_quote(self, target: Target) -> dict[str, Any]:
        market_symbol = tencent_market_symbol(target.symbol)
        response = self._request(
            "GET",
            f"https://qt.gtimg.cn/q={market_symbol}",
            headers=TENCENT_HEADERS,
            timeout=self.settings.request_timeout_sec,
        )
        response.raise_for_status()
        text = response.content.decode("gbk", errors="replace")
        if '="' not in text:
            raise ValueError("unexpected Tencent quote response")
        fields = text.split('="', 1)[1].rsplit('"', 1)[0].split("~")
        if len(fields) < 36:
            raise ValueError("incomplete Tencent quote response")
        raw_trade = fields[35].split("/")
        amount = to_float(raw_trade[2]) if len(raw_trade) >= 3 else None
        return {
            "symbol": fields[2],
            "name": fields[1] or target.name,
            "price": to_float(fields[3]),
            "open": to_float(fields[5]),
            "high": to_float(fields[33]),
            "low": to_float(fields[34]),
            "previous_close": to_float(fields[4]),
            "change_pct": to_float(fields[32]),
            "volume": to_float(fields[6]),
            "volume_unit": "手",
            "amount": amount,
            "market_time": fields[30],
        }

    def _fetch_eastmoney_quote(self, target: Target) -> dict[str, Any]:
        response = self._request(
            "GET",
            "https://push2.eastmoney.com/api/qt/stock/get",
            params={
                "secid": eastmoney_secid(target.symbol),
                "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f170",
            },
            headers=EASTMONEY_HEADERS,
            timeout=self.settings.request_timeout_sec,
        )
        response.raise_for_status()
        row = (response.json().get("data") or {})
        return {
            "symbol": str(row.get("f57") or ""),
            "name": row.get("f58") or target.name,
            "price": normalize_em_price(row.get("f43")),
            "open": normalize_em_price(row.get("f46")),
            "high": normalize_em_price(row.get("f44")),
            "low": normalize_em_price(row.get("f45")),
            "previous_close": normalize_em_price(row.get("f60")),
            "change_pct": normalize_em_ratio(row.get("f170")),
            "volume": row.get("f47"),
            "volume_unit": "手",
            "amount": row.get("f48"),
        }

    def _fetch_sina_quote(self, target: Target) -> dict[str, Any]:
        market_symbol = tencent_market_symbol(target.symbol)
        response = self._request(
            "GET",
            f"https://hq.sinajs.cn/list={market_symbol}",
            headers=SINA_HEADERS,
            timeout=self.settings.request_timeout_sec,
        )
        response.raise_for_status()
        text = response.content.decode("gbk", errors="replace")
        if '="' not in text:
            raise ValueError("unexpected Sina quote response")
        fields = text.split('="', 1)[1].rsplit('"', 1)[0].split(",")
        if len(fields) < 10 or not fields[0]:
            raise ValueError("incomplete Sina quote response")
        price = to_float(fields[3])
        previous_close = to_float(fields[2])
        change_pct = None
        if price is not None and previous_close:
            change_pct = round((price / previous_close - 1) * 100, 4)
        volume_shares = to_float(fields[8])
        market_time = " ".join(part for part in fields[30:32] if part) if len(fields) > 31 else ""
        return {
            "symbol": target.symbol,
            "name": fields[0] or target.name,
            "price": price,
            "open": to_float(fields[1]),
            "high": to_float(fields[4]),
            "low": to_float(fields[5]),
            "previous_close": previous_close,
            "change_pct": change_pct,
            "volume": round(volume_shares / 100, 2) if volume_shares is not None else None,
            "volume_unit": "手",
            "amount": to_float(fields[9]),
            "market_time": market_time,
        }

    def _fetch_tencent_klines(self, target: Target, limit: int) -> list[dict[str, Any]]:
        market_symbol = tencent_market_symbol(target.symbol)
        response = self._request(
            "GET",
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
            params={"param": f"{market_symbol},day,,,{limit},qfq"},
            headers=TENCENT_HEADERS,
            timeout=self.settings.request_timeout_sec,
        )
        response.raise_for_status()
        block = ((response.json().get("data") or {}).get(market_symbol) or {})
        quote_fields = ((block.get("qt") or {}).get(market_symbol) or []) if isinstance(block.get("qt"), dict) else []
        if len(quote_fields) > 2 and str(quote_fields[2]) != target.symbol:
            raise ValueError("Tencent kline symbol mismatch")
        raw_rows = block.get("qfqday") or block.get("day") or []
        rows = []
        for item in raw_rows:
            if not isinstance(item, list) or len(item) < 6:
                continue
            rows.append({
                "date": item[0],
                "open": to_float(item[1]),
                "close": to_float(item[2]),
                "high": to_float(item[3]),
                "low": to_float(item[4]),
                "volume": to_float(item[5]),
                "amount": to_float(item[6]) if len(item) > 6 else None,
            })
        return rows

    def _fetch_eastmoney_klines(self, target: Target, limit: int) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            params={
                "secid": eastmoney_secid(target.symbol),
                "klt": "101",
                "fqt": "1",
                "lmt": str(limit),
                "end": "20500101",
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            },
            headers=EASTMONEY_HEADERS,
            timeout=self.settings.request_timeout_sec,
        )
        response.raise_for_status()
        block = response.json().get("data") or {}
        if str(block.get("code") or target.symbol) != target.symbol:
            raise ValueError("Eastmoney kline symbol mismatch")
        rows = []
        for item in block.get("klines") or []:
            parts = item.split(",")
            if len(parts) < 7:
                continue
            rows.append({
                "date": parts[0],
                "open": to_float(parts[1]),
                "close": to_float(parts[2]),
                "high": to_float(parts[3]),
                "low": to_float(parts[4]),
                "volume": to_float(parts[5]),
                "amount": to_float(parts[6]),
            })
        return rows

    def _fetch_sina_klines(self, target: Target, limit: int) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            "https://quotes.sina.cn/cn/api/openapi.php/CN_MarketDataService.getKLineData",
            params={
                "symbol": tencent_market_symbol(target.symbol),
                "scale": "240",
                "ma": "no",
                "datalen": str(limit),
            },
            headers=SINA_HEADERS,
            timeout=self.settings.request_timeout_sec,
        )
        response.raise_for_status()
        result = response.json().get("result") or {}
        raw_rows = result.get("data") or []
        rows = []
        for item in raw_rows:
            if not isinstance(item, dict):
                continue
            rows.append({
                "date": str(item.get("day") or "")[:10],
                "open": to_float(item.get("open")),
                "close": to_float(item.get("close")),
                "high": to_float(item.get("high")),
                "low": to_float(item.get("low")),
                "volume": to_float(item.get("volume")),
                "amount": to_float(item.get("amount")),
            })
        return rows

    def fundamentals(self, target: Target) -> dict[str, Any]:
        cache_key = f"fundamental_{target.symbol}.json"
        cached = self._read_cache(cache_key, max_age_sec=86400)
        if cached is not None:
            return cached
        data: dict[str, Any] = {}
        if not self.settings.enable_akshare:
            data["_message"] = "optional akshare fundamentals disabled; set QINGYAN_ENABLE_AKSHARE=true to enable richer fields."
            self._write_cache(cache_key, data)
            return data
        try:
            os.environ.setdefault("TQDM_DISABLE", "1")
            import akshare as ak
            frame = ak.stock_financial_analysis_indicator(symbol=target.symbol, start_year=str(datetime.now().year - 4))
            if frame is not None and not frame.empty:
                latest = frame.tail(1).to_dict(orient="records")[0]
                for key in ("日期", "摊薄每股收益(元)", "加权每股收益(元)", "每股经营性现金流(元)", "净资产收益率(%)", "销售毛利率(%)", "资产负债率(%)"):
                    if key in latest:
                        data[key] = latest.get(key)
                data["source"] = "akshare_financial_analysis_indicator"
        except Exception as exc:
            data["_message"] = f"optional akshare fundamentals unavailable: {str(exc)[:140]}"
        self._write_cache(cache_key, data)
        return data

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        with requests.Session() as session:
            session.trust_env = False
            return session.request(method, url, **kwargs)

    def _prefer_current_bse_security(self, match: dict[str, Any]) -> dict[str, Any]:
        code = str(match.get("code") or "")
        if not code.startswith(("4", "8")):
            return match
        name = str(match.get("zwjc") or "").strip()
        org_id = str(match.get("orgId") or "")
        if not name:
            return match
        try:
            response = self._request(
                "POST",
                "https://www.cninfo.com.cn/new/information/topSearch/query",
                data={"keyWord": name, "maxSecNum": "10"},
                headers=CNINFO_HEADERS,
                timeout=self.settings.request_timeout_sec,
            )
            response.raise_for_status()
            candidates = response.json()
            current = next((item for item in candidates if (
                isinstance(item, dict)
                and str(item.get("code") or "").startswith("920")
                and str(item.get("orgId") or "") == org_id
                and item.get("category") == "A股"
            )), None)
            return current or match
        except Exception:
            return match

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
        return self.settings.cache_dir / key

    def _read_cache(self, key: str, max_age_sec: int | None = None) -> Any:
        path = self._cache_path(key)
        try:
            if not path.exists():
                return None
            if max_age_sec is not None and time.time() - path.stat().st_mtime > max_age_sec:
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _write_cache(self, key: str, value: Any) -> None:
        try:
            self.settings.cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_path(key).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass


def select_cninfo_security(rows: Any, query: str, target: Target | None) -> dict[str, Any] | None:
    if not isinstance(rows, list):
        return None
    candidates = [
        item for item in rows
        if isinstance(item, dict)
        and item.get("category") == "A股"
        and is_a_share_code(str(item.get("code") or ""))
        and item.get("orgId")
        and item.get("zwjc")
    ]
    if target and target.symbol:
        exact = next((item for item in candidates if str(item.get("code")) == target.symbol), None)
        if exact:
            return exact
    normalized = query.strip().lower()
    exact = next((item for item in candidates if str(item.get("code") or "").lower() == normalized), None)
    if exact:
        return exact
    exact_names = [item for item in candidates if str(item.get("zwjc") or "").lower() == normalized]
    if exact_names:
        return next((item for item in exact_names if str(item.get("code") or "").startswith("920")), exact_names[0])
    return candidates[0] if len(candidates) == 1 else None


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


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def tencent_market_symbol(symbol: str) -> str:
    value = str(symbol).strip()
    if is_bse_symbol(value):
        return "bj" + value
    return ("sh" if value.startswith("6") else "sz") + value


def eastmoney_secid(symbol: str) -> str:
    symbol = str(symbol).strip()
    market_id = "1" if symbol.startswith("6") else "0"
    return f"{market_id}.{symbol}"


def is_bse_symbol(symbol: str) -> bool:
    value = str(symbol or "")
    return value.startswith(("4", "8", "920"))


def cninfo_market_params(symbol: str) -> tuple[str, str]:
    if is_bse_symbol(symbol):
        return "third", "bj"
    return ("sse", "sh") if str(symbol).startswith("6") else ("szse", "sz")


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


def clean_html(value: str) -> str:
    return str(value or "").replace("<em>", "").replace("</em>", "")


def format_cninfo_date(value: Any) -> str:
    try:
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return str(value or "")


def technical_indicators(rows: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [to_float(row.get("close")) for row in rows if to_float(row.get("close")) is not None]
    volumes = [to_float(row.get("volume")) for row in rows if to_float(row.get("volume")) is not None]
    if len(closes) < 20:
        return {"status": "insufficient_data", "message": "K线样本不足，暂不计算技术指标。"}
    import statistics
    last = closes[-1]
    ma5 = statistics.mean(closes[-5:])
    ma20 = statistics.mean(closes[-20:])
    ma60 = statistics.mean(closes[-60:]) if len(closes) >= 60 else None
    ret20 = (last / closes[-21] - 1) * 100 if len(closes) >= 21 and closes[-21] else None
    returns = [(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes)) if closes[i - 1]]
    sample = returns[-60:] if len(returns) >= 60 else returns
    vol = (statistics.pstdev(sample) * (252 ** 0.5) * 100) if len(sample) > 1 else None
    vr = None
    if len(volumes) >= 20 and statistics.mean(volumes[-20:-1]) > 0:
        vr = volumes[-1] / statistics.mean(volumes[-20:-1])
    trend = "中性震荡"
    if ma60 and last > ma20 > ma60:
        trend = "中期趋势改善"
    elif ma60 and last < ma20 < ma60:
        trend = "中期趋势承压"
    elif last > ma5 > ma20:
        trend = "短期偏强"
    elif last < ma5 < ma20:
        trend = "短期偏弱"
    return {
        "last_close": round(last, 4),
        "ma5": round(ma5, 4),
        "ma20": round(ma20, 4),
        "ma60": round(ma60, 4) if ma60 else None,
        "return_20d_pct": round(ret20, 2) if ret20 is not None else None,
        "annualized_volatility_pct": round(vol, 2) if vol is not None else None,
        "annualized_volatility_window_days": len(sample),
        "relative_volume_20d": round(vr, 2) if vr is not None else None,
        "relative_volume_baseline_days": 19 if vr is not None else None,
        "return_window_days": 20 if ret20 is not None else None,
        "price_adjustment": rows[-1].get("price_adjustment") or (
            "前复权" if "qfq" in str(rows[-1].get("source") or "") else "待核验"
        ),
        "trend_label": trend,
        "source": rows[-1].get("source") if rows else None,
        "data_date": rows[-1].get("date") if rows else None,
        "fetched_at": rows[-1].get("fetched_at") if rows else None,
        "is_stale": any(bool(row.get("is_stale")) for row in rows),
    }


def has_data_fields(value: dict[str, Any]) -> bool:
    return any(not str(key).startswith("_") for key in value)
