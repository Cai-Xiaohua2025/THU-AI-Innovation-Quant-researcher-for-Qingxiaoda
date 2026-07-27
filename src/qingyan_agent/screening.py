"""Multi-stock screening workflow."""

from __future__ import annotations

from .data_sources import AShareDataClient
from .models import DataStatus, ScreeningResult, Target
from .universe import DEFAULT_A_SHARE_UNIVERSE


class StockScreener:
    def __init__(self, data_client: AShareDataClient) -> None:
        self.data_client = data_client

    def screen(self, universe: list[Target] | None = None, limit: int = 8) -> ScreeningResult:
        targets = universe or DEFAULT_A_SHARE_UNIVERSE
        rows = []
        statuses: list[DataStatus] = []
        for target in targets:
            snapshot = self.data_client.collect(target)
            statuses.extend(snapshot.statuses)
            score, factors = score_snapshot(snapshot)
            rows.append({
                "market": target.market,
                "symbol": target.symbol,
                "name": target.name,
                "sector": target.sector,
                "score": score,
                "factors": factors,
                "risk_tags": risk_tags(snapshot, factors),
            })
        rows.sort(key=lambda item: item["score"], reverse=True)
        return ScreeningResult("default_a_share_research_universe", rows[:limit], statuses)


def score_snapshot(snapshot) -> tuple[float, dict]:
    tech = snapshot.technical or {}
    quote = snapshot.quote or {}
    fundamentals = snapshot.fundamentals or {}
    score = 50.0
    factors = {}

    ret20 = tech.get("return_20d_pct")
    if ret20 is not None:
        momentum_score = clamp(50 + ret20 * 1.2, 0, 100)
        score += (momentum_score - 50) * 0.25
        factors["momentum_20d"] = round(momentum_score, 2)

    trend = tech.get("trend_label") or ""
    trend_score = 60 if "改善" in trend or "偏强" in trend else 40 if "承压" in trend or "偏弱" in trend else 50
    score += (trend_score - 50) * 0.25
    factors["trend"] = trend_score

    volatility = tech.get("annualized_volatility_pct")
    if volatility is not None:
        risk_score = clamp(100 - volatility, 0, 100)
        score += (risk_score - 50) * 0.18
        factors["volatility_control"] = round(risk_score, 2)

    volume_ratio = tech.get("volume_ratio_20d")
    if volume_ratio is not None:
        liquidity_score = clamp(45 + min(volume_ratio, 3) * 15, 0, 100)
        score += (liquidity_score - 50) * 0.12
        factors["liquidity_activity"] = round(liquidity_score, 2)

    if fundamentals:
        quality_score = 55
        roe = first_number(fundamentals, ("净资产收益率(%)", "roe", "ROE"))
        debt = first_number(fundamentals, ("资产负债率(%)", "debt_ratio"))
        if roe is not None:
            quality_score += min(max(roe, -10), 30) * 0.8
        if debt is not None and debt > 70:
            quality_score -= 10
        score += (clamp(quality_score, 0, 100) - 50) * 0.20
        factors["financial_quality"] = round(clamp(quality_score, 0, 100), 2)
    else:
        factors["financial_quality"] = "pending"

    if quote.get("price"):
        factors["quote_available"] = True
    else:
        score -= 4
        factors["quote_available"] = False

    return round(clamp(score, 0, 100), 2), factors


def risk_tags(snapshot, factors: dict) -> list[str]:
    tags = []
    tech = snapshot.technical or {}
    if tech.get("annualized_volatility_pct") and tech["annualized_volatility_pct"] > 45:
        tags.append("高波动")
    if tech.get("volume_ratio_20d") and tech["volume_ratio_20d"] > 2.2:
        tags.append("放量异动")
    if not snapshot.fundamentals:
        tags.append("财务字段待补充")
    if not snapshot.announcements:
        tags.append("公告检索待核验")
    if not snapshot.quote.get("price"):
        tags.append("实时行情不可用")
    return tags or ["常规风险"]


def first_number(data: dict, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = data.get(key)
        try:
            if value not in (None, ""):
                return float(value)
        except Exception:
            pass
    return None


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
