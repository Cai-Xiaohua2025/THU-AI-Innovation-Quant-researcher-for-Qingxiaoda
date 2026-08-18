"""Tencent, Sina, and Eastmoney quote/K-line adapters."""

from __future__ import annotations

from typing import Any, Callable

import requests

from ..models import Target


RequestCallable = Callable[..., requests.Response]

EASTMONEY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
}
TENCENT_HEADERS = {
    "User-Agent": EASTMONEY_HEADERS["User-Agent"],
    "Referer": "https://gu.qq.com/",
}
SINA_HEADERS = {
    "User-Agent": EASTMONEY_HEADERS["User-Agent"],
    "Referer": "https://finance.sina.com.cn/",
}


class FunctionMarketDataProvider:
    """Protocol adapter around the existing normalized source functions."""

    def __init__(
        self,
        provider_name: str,
        request: RequestCallable,
        timeout: int,
        quote_fetcher: Callable[[RequestCallable, Target, int], dict[str, Any]],
        kline_fetcher: Callable[[RequestCallable, Target, int, int], list[dict[str, Any]]],
    ) -> None:
        self.provider_name = provider_name
        self._request = request
        self.timeout = timeout
        self._quote_fetcher = quote_fetcher
        self._kline_fetcher = kline_fetcher

    def quote(self, target: Target) -> dict[str, Any]:
        return self._quote_fetcher(self._request, target, self.timeout)

    def klines(self, target: Target, limit: int) -> list[dict[str, Any]]:
        return self._kline_fetcher(self._request, target, limit, self.timeout)


def fetch_tencent_quote(request: RequestCallable, target: Target, timeout: int) -> dict[str, Any]:
    market_symbol = tencent_market_symbol(target.symbol)
    response = request(
        "GET",
        f"https://qt.gtimg.cn/q={market_symbol}",
        headers=TENCENT_HEADERS,
        timeout=timeout,
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


def fetch_sina_quote(request: RequestCallable, target: Target, timeout: int) -> dict[str, Any]:
    market_symbol = tencent_market_symbol(target.symbol)
    response = request(
        "GET",
        f"https://hq.sinajs.cn/list={market_symbol}",
        headers=SINA_HEADERS,
        timeout=timeout,
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


def fetch_eastmoney_quote(request: RequestCallable, target: Target, timeout: int) -> dict[str, Any]:
    response = request(
        "GET",
        "https://push2.eastmoney.com/api/qt/stock/get",
        params={
            "secid": eastmoney_secid(target.symbol),
            "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f170",
        },
        headers=EASTMONEY_HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()
    row = response.json().get("data") or {}
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


def fetch_tencent_klines(
    request: RequestCallable,
    target: Target,
    limit: int,
    timeout: int,
) -> list[dict[str, Any]]:
    market_symbol = tencent_market_symbol(target.symbol)
    response = request(
        "GET",
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
        params={"param": f"{market_symbol},day,,,{limit},qfq"},
        headers=TENCENT_HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()
    block = ((response.json().get("data") or {}).get(market_symbol) or {})
    quote_fields = ((block.get("qt") or {}).get(market_symbol) or []) if isinstance(block.get("qt"), dict) else []
    if len(quote_fields) > 2 and str(quote_fields[2]) != target.symbol:
        raise ValueError("Tencent kline symbol mismatch")
    rows = []
    for item in block.get("qfqday") or block.get("day") or []:
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


def fetch_sina_klines(
    request: RequestCallable,
    target: Target,
    limit: int,
    timeout: int,
) -> list[dict[str, Any]]:
    response = request(
        "GET",
        "https://quotes.sina.cn/cn/api/openapi.php/CN_MarketDataService.getKLineData",
        params={
            "symbol": tencent_market_symbol(target.symbol),
            "scale": "240",
            "ma": "no",
            "datalen": str(limit),
        },
        headers=SINA_HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()
    rows = []
    for item in (response.json().get("result") or {}).get("data") or []:
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


def fetch_eastmoney_klines(
    request: RequestCallable,
    target: Target,
    limit: int,
    timeout: int,
) -> list[dict[str, Any]]:
    response = request(
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
        timeout=timeout,
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


def tencent_market_symbol(symbol: str) -> str:
    value = str(symbol).strip()
    if value.startswith(("4", "8", "920")):
        return "bj" + value
    return ("sh" if value.startswith("6") else "sz") + value


def eastmoney_secid(symbol: str) -> str:
    value = str(symbol).strip()
    return f"{'1' if value.startswith('6') else '0'}.{value}"


def normalize_em_price(value: Any) -> float | None:
    number = to_float(value)
    return round(number / 100, 4) if number is not None else None


def normalize_em_ratio(value: Any) -> float | None:
    number = to_float(value)
    return round(number / 100, 4) if number is not None else None


def to_float(value: Any) -> float | None:
    try:
        if value in (None, "", "-"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
