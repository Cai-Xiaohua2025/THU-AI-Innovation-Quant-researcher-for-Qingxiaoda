"""CNInfo security-resolution and announcement provider."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..models import Target
from ..universe import is_a_share_code
from .providers import EASTMONEY_HEADERS, RequestCallable


CNINFO_HEADERS = {
    "User-Agent": EASTMONEY_HEADERS["User-Agent"],
    "Referer": "http://www.cninfo.com.cn/",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}


class CNInfoProvider:
    """Pure CNInfo adapter; caching and attachment extraction stay in the facade."""

    provider_name = "cninfo"

    def __init__(self, request: RequestCallable, timeout: int) -> None:
        self._request = request
        self.timeout = timeout

    def resolve_security(self, query: str, target: Target | None = None) -> dict[str, Any] | None:
        response = self._request(
            "POST",
            "https://www.cninfo.com.cn/new/information/topSearch/query",
            data={"keyWord": query, "maxSecNum": "10"},
            headers=CNINFO_HEADERS,
            timeout=self.timeout,
        )
        response.raise_for_status()
        match = select_cninfo_security(response.json(), query, target)
        return self._prefer_current_bse_security(match) if match else None

    def announcements(self, target: Target, *, lookback_days: int) -> list[dict[str, Any]]:
        today = datetime.now()
        start = today - timedelta(days=lookback_days)
        column, plate = cninfo_market_params(target.symbol)
        response = self._request(
            "POST",
            "https://www.cninfo.com.cn/new/hisAnnouncement/query",
            data={
                "stock": f"{target.symbol},{target.org_id}",
                "tabName": "fulltext",
                "pageSize": "12",
                "pageNum": "1",
                "column": column,
                "category": "",
                "plate": plate,
                "seDate": f"{start:%Y-%m-%d}~{today:%Y-%m-%d}",
                "searchkey": "",
                "secid": "",
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            },
            headers=CNINFO_HEADERS,
            timeout=self.timeout,
        )
        response.raise_for_status()
        rows = []
        for item in (response.json().get("announcements") or []):
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
                "source": self.provider_name,
            })
        return rows

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
                timeout=self.timeout,
            )
            response.raise_for_status()
            current = next((item for item in response.json() if (
                isinstance(item, dict)
                and str(item.get("code") or "").startswith("920")
                and str(item.get("orgId") or "") == org_id
                and item.get("category") == "A股"
            )), None)
            return current or match
        except Exception:
            return match


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


def cninfo_market_params(symbol: str) -> tuple[str, str]:
    if is_bse_symbol(symbol):
        return "third", "bj"
    return ("sse", "sh") if str(symbol).startswith("6") else ("szse", "sz")


def is_bse_symbol(symbol: str) -> bool:
    return str(symbol or "").startswith(("4", "8", "920"))


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
