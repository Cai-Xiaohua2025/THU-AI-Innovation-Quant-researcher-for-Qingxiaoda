"""Stable public-data access with graceful degradation."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from .config import Settings
from .models import DataStatus, MarketSnapshot, Target


EASTMONEY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
}

CNINFO_HEADERS = {
    "User-Agent": EASTMONEY_HEADERS["User-Agent"],
    "Referer": "http://www.cninfo.com.cn/",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


class AShareDataClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def collect(self, target: Target | None) -> MarketSnapshot:
        snapshot = MarketSnapshot(target=target)
        if not target:
            snapshot.statuses.append(DataStatus("target", False, "未识别到明确 A 股标的。"))
            return snapshot
        snapshot.quote = self.quote(target)
        snapshot.klines = self.klines(target, limit=180)
        snapshot.technical = technical_indicators(snapshot.klines)
        snapshot.fundamentals = self.fundamentals(target)
        snapshot.announcements = self.announcements(target)
        snapshot.statuses.extend([
            DataStatus("eastmoney_quote", bool(snapshot.quote.get("price")), snapshot.quote.get("message", "")),
            DataStatus("eastmoney_kline", bool(snapshot.klines), f"{len(snapshot.klines)} rows"),
            DataStatus("fundamental", has_data_fields(snapshot.fundamentals), snapshot.fundamentals.get("_message", "")),
            DataStatus("cninfo_announcement", bool(snapshot.announcements), f"{len(snapshot.announcements)} rows"),
        ])
        return snapshot

    def quote(self, target: Target) -> dict[str, Any]:
        cache_key = f"quote_{target.symbol}.json"
        cached = self._read_cache(cache_key, max_age_sec=30)
        if cached is not None:
            return cached
        stale = self._read_cache(cache_key)
        secid = eastmoney_secid(target.symbol)
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {"secid": secid, "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f170"}
        try:
            response = requests.get(url, params=params, headers=EASTMONEY_HEADERS, timeout=self.settings.request_timeout_sec)
            response.raise_for_status()
            data = response.json()
            row = data.get("data") or {}
            price = normalize_em_price(row.get("f43"))
            result = {
                "symbol": row.get("f57") or target.symbol,
                "name": row.get("f58") or target.name,
                "price": price,
                "open": normalize_em_price(row.get("f46")),
                "high": normalize_em_price(row.get("f44")),
                "low": normalize_em_price(row.get("f45")),
                "previous_close": normalize_em_price(row.get("f60")),
                "change_pct": normalize_em_ratio(row.get("f170")),
                "volume": row.get("f47"),
                "amount": row.get("f48"),
                "source": "eastmoney_push2",
            }
            self._write_cache(cache_key, result)
            return result
        except Exception as exc:
            if stale is not None:
                stale["message"] = "using stale quote cache because live source is unavailable"
                return stale
            return {"source": "eastmoney_push2", "message": f"quote unavailable: {str(exc)[:160]}"}

    def klines(self, target: Target, limit: int = 180) -> list[dict[str, Any]]:
        cache_key = f"kline_{target.symbol}_{limit}.json"
        cached = self._read_cache(cache_key, max_age_sec=180)
        if cached is not None:
            return cached
        stale = self._read_cache(cache_key)
        secid = eastmoney_secid(target.symbol)
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": secid,
            "klt": "101",
            "fqt": "1",
            "lmt": str(limit),
            "end": "20500101",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        }
        try:
            response = requests.get(url, params=params, headers=EASTMONEY_HEADERS, timeout=self.settings.request_timeout_sec)
            response.raise_for_status()
            data = response.json()
            rows = []
            for item in ((data.get("data") or {}).get("klines") or []):
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
            self._write_cache(cache_key, rows)
            return rows
        except Exception:
            return stale if isinstance(stale, list) else []

    def announcements(self, target: Target) -> list[dict[str, Any]]:
        cache_key = f"announcements_{target.symbol}.json"
        cached = self._read_cache(cache_key, max_age_sec=3600)
        if cached is not None:
            return cached
        stale = self._read_cache(cache_key)
        today = datetime.now()
        start = today - timedelta(days=self.settings.announcement_lookback_days)
        url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
        payload = {
            "stock": f"{target.symbol},{target.name}",
            "tabName": "fulltext",
            "pageSize": "12",
            "pageNum": "1",
            "column": "sse" if target.symbol.startswith("6") else "szse",
            "category": "",
            "plate": "sh" if target.symbol.startswith("6") else "sz",
            "seDate": f"{start:%Y-%m-%d}~{today:%Y-%m-%d}",
            "searchkey": "",
            "secid": "",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
        try:
            response = requests.post(url, data=payload, headers=CNINFO_HEADERS, timeout=self.settings.request_timeout_sec)
            response.raise_for_status()
            data = response.json()
            rows = []
            for item in data.get("announcements") or []:
                adjunct = item.get("adjunctUrl") or ""
                rows.append({
                    "title": clean_html(item.get("announcementTitle") or ""),
                    "date": format_cninfo_date(item.get("announcementTime")),
                    "url": f"https://static.cninfo.com.cn/{adjunct}" if adjunct else "",
                    "source": "cninfo",
                })
            self._write_cache(cache_key, rows)
            return rows
        except Exception:
            return stale if isinstance(stale, list) else []

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


def eastmoney_secid(symbol: str) -> str:
    symbol = str(symbol).strip()
    market_id = "1" if symbol.startswith("6") else "0"
    return f"{market_id}.{symbol}"


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
        "volume_ratio_20d": round(vr, 2) if vr is not None else None,
        "trend_label": trend,
    }


def has_data_fields(value: dict[str, Any]) -> bool:
    return any(not str(key).startswith("_") for key in value)
