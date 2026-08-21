"""Optional structured fundamental-data provider."""

from __future__ import annotations

import os
from datetime import datetime
from math import isfinite
from typing import Any

from ..models import Target


class AkShareFundamentalProvider:
    provider_name = "akshare_financial_analysis_indicator"

    def fundamentals(self, target: Target) -> dict[str, Any]:
        return fetch_akshare_fundamentals(target.symbol)


def fetch_akshare_fundamentals(symbol: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    try:
        os.environ.setdefault("TQDM_DISABLE", "1")
        import akshare as ak

        frame = ak.stock_financial_analysis_indicator(
            symbol=symbol,
            start_year=str(datetime.now().year - 4),
        )
        if frame is not None and not frame.empty:
            latest = frame.tail(1).to_dict(orient="records")[0]
            for key in (
                "日期",
                "摊薄每股收益(元)",
                "加权每股收益(元)",
                "每股经营性现金流(元)",
                "净资产收益率(%)",
                "销售毛利率(%)",
                "资产负债率(%)",
            ):
                cleaned = normalize_fundamental_value(latest.get(key))
                if key in latest and cleaned is not None:
                    data[key] = cleaned
            data["source"] = "akshare_financial_analysis_indicator"
            data["data_date"] = str(data.get("日期") or "")
            data["fetched_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    except Exception as exc:
        data["_message"] = f"optional akshare fundamentals unavailable: {str(exc)[:140]}"
    return data


def normalize_fundamental_mapping(value: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in (value or {}).items():
        cleaned = normalize_fundamental_value(item)
        if cleaned is not None or str(key).startswith("_"):
            result[key] = cleaned if cleaned is not None else item
    return result


def normalize_fundamental_value(value: Any) -> Any | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned or cleaned.lower() in {"nan", "nat", "none", "null", "<na>"}:
            return None
        return cleaned
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
        if value is None:
            return None
    try:
        if bool(value != value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, float):
        return value if isfinite(value) else None
    if isinstance(value, (int, bool)):
        return value
    return str(value)
