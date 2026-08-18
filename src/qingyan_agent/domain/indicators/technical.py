"""Deterministic, auditable technical-indicator calculations."""

from __future__ import annotations

import math
import statistics
from typing import Any

from ...contracts import KlineBar, TechnicalIndicators


FUNDAMENTAL_METADATA_KEYS = {
    "source",
    "provider",
    "fetched_at",
    "data_date",
    "status",
    "message",
    "error",
    "is_stale",
}


def technical_indicators(rows: list[KlineBar] | list[dict[str, Any]]) -> TechnicalIndicators:
    valid_rows = []
    for row in rows:
        close = to_float(row.get("close"))
        if close is not None and close > 0:
            valid_rows.append(row)
    closes = [float(row["close"]) for row in valid_rows]
    highs = [to_float(row.get("high")) or close for row, close in zip(valid_rows, closes)]
    lows = [to_float(row.get("low")) or close for row, close in zip(valid_rows, closes)]
    if len(closes) < 20:
        return {"status": "insufficient_data", "message": "K线样本不足，暂不计算技术指标。"}

    def mean_at_end(values: list[float], window: int, offset: int = 0) -> float | None:
        end = len(values) - offset
        start = end - window
        if start < 0 or end <= 0:
            return None
        return statistics.mean(values[start:end])

    def pct_change(current: float | None, previous: float | None) -> float | None:
        if current is None or previous in (None, 0):
            return None
        return (current / previous - 1) * 100

    def rounded(value: float | None, digits: int = 2) -> float | None:
        return round(value, digits) if value is not None and math.isfinite(value) else None

    last = closes[-1]
    ma5 = mean_at_end(closes, 5)
    ma20 = mean_at_end(closes, 20)
    ma60 = mean_at_end(closes, 60)
    ma5_slope = pct_change(ma5, mean_at_end(closes, 5, offset=5))
    ma20_slope = pct_change(ma20, mean_at_end(closes, 20, offset=5))
    ma60_slope = pct_change(ma60, mean_at_end(closes, 60, offset=20))
    ret20 = (last / closes[-21] - 1) * 100 if len(closes) >= 21 and closes[-21] else None
    ret5 = (last / closes[-6] - 1) * 100 if len(closes) >= 6 and closes[-6] else None
    ret60 = (last / closes[-61] - 1) * 100 if len(closes) >= 61 and closes[-61] else None
    returns = [(closes[index] / closes[index - 1] - 1) for index in range(1, len(closes)) if closes[index - 1]]
    sample = returns[-60:] if len(returns) >= 60 else returns
    volatility = statistics.pstdev(sample) * math.sqrt(252) * 100 if len(sample) > 1 else None

    rolling_volatility = []
    if len(returns) >= 60:
        for end in range(60, len(returns) + 1):
            window = returns[end - 60:end]
            rolling_volatility.append(statistics.pstdev(window) * math.sqrt(252) * 100)
    volatility_percentile = None
    if volatility is not None and rolling_volatility:
        volatility_percentile = sum(value <= volatility for value in rolling_volatility) / len(rolling_volatility) * 100

    volumes = [
        value for row in valid_rows
        if (value := to_float(row.get("volume"))) is not None and value >= 0
    ]
    relative_volume = None
    volume_baseline = None
    if len(volumes) >= 20:
        volume_baseline = statistics.mean(volumes[-20:-1])
        if volume_baseline > 0:
            relative_volume = volumes[-1] / volume_baseline
    volume_5d = statistics.mean(volumes[-5:]) if len(volumes) >= 5 else None
    prior_volume_5d = statistics.mean(volumes[-10:-5]) if len(volumes) >= 10 else None
    volume_5d_change = pct_change(volume_5d, prior_volume_5d)

    high20 = max(highs[-20:])
    low20 = min(lows[-20:])
    high60 = max(highs[-60:]) if len(closes) >= 60 else None
    low60 = min(lows[-60:]) if len(closes) >= 60 else None
    range_position_60 = None
    if high60 is not None and low60 is not None and high60 > low60:
        range_position_60 = (last - low60) / (high60 - low60) * 100

    rolling_peak = closes[-60] if len(closes) >= 60 else closes[0]
    max_drawdown = 0.0
    for close in closes[-60:]:
        rolling_peak = max(rolling_peak, close)
        max_drawdown = min(max_drawdown, close / rolling_peak - 1)

    gains = [max(value, 0.0) for value in returns[-14:]]
    losses = [max(-value, 0.0) for value in returns[-14:]]
    rsi14 = None
    if len(gains) == 14:
        avg_gain = statistics.mean(gains)
        avg_loss = statistics.mean(losses)
        rsi14 = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)

    def ema_series(values: list[float], period: int) -> list[float]:
        alpha = 2 / (period + 1)
        result = [values[0]]
        for value in values[1:]:
            result.append(alpha * value + (1 - alpha) * result[-1])
        return result

    ema12 = ema_series(closes, 12)
    ema26 = ema_series(closes, 26)
    dif_series = [fast - slow for fast, slow in zip(ema12, ema26)]
    dea_series = ema_series(dif_series, 9)
    macd_dif = dif_series[-1]
    macd_dea = dea_series[-1]
    macd_hist = (macd_dif - macd_dea) * 2

    true_ranges = []
    for index, row in enumerate(valid_rows):
        high = to_float(row.get("high"))
        low = to_float(row.get("low"))
        if high is None or low is None:
            continue
        previous_close = closes[index - 1] if index > 0 else closes[index]
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    atr14 = statistics.mean(true_ranges[-14:]) if len(true_ranges) >= 14 else None
    atr14_pct = atr14 / last * 100 if atr14 is not None and last else None

    structure = "区间震荡"
    earlier_highs, recent_highs = highs[-20:-10], highs[-10:]
    earlier_lows, recent_lows = lows[-20:-10], lows[-10:]
    if max(recent_highs) > max(earlier_highs) and min(recent_lows) > min(earlier_lows):
        structure = "高点与低点同步抬高"
    elif max(recent_highs) < max(earlier_highs) and min(recent_lows) < min(earlier_lows):
        structure = "高点与低点同步下移"

    alignment = "均线粘合或混合排列"
    if ma60 is not None and last > ma5 > ma20 > ma60:
        alignment = "标准多头排列"
    elif ma60 is not None and last < ma5 < ma20 < ma60:
        alignment = "标准空头排列"

    trend_score = 0
    trend_basis = []
    if last >= ma20:
        trend_score += 1
        trend_basis.append("收盘价位于MA20上方")
    else:
        trend_score -= 1
        trend_basis.append("收盘价位于MA20下方")
    if ma5 >= ma20:
        trend_score += 1
        trend_basis.append("MA5不低于MA20")
    else:
        trend_score -= 1
        trend_basis.append("MA5低于MA20")
    if ma20_slope is not None:
        trend_score += 1 if ma20_slope > 0 else -1
        trend_basis.append(f"MA20近5日{'上行' if ma20_slope > 0 else '下行'}")
    if ma60 is not None:
        trend_score += 1 if last >= ma60 else -1
        trend_basis.append(f"收盘价位于MA60{'上方' if last >= ma60 else '下方'}")
    trend = "区间震荡，方向待确认"
    if trend_score >= 2:
        trend = "趋势改善，但需量价确认"
    elif trend_score <= -2:
        trend = "中期趋势承压"

    volatility_label = "缺少历史分位参照"
    if volatility_percentile is not None:
        if volatility_percentile >= 80:
            volatility_label = "处于当前样本高波动区间"
        elif volatility_percentile <= 20:
            volatility_label = "处于当前样本低波动区间"
        else:
            volatility_label = "处于当前样本中等波动区间"

    return {
        "last_close": round(last, 4),
        "ma5": rounded(ma5, 4),
        "ma20": rounded(ma20, 4),
        "ma60": rounded(ma60, 4),
        "bias_ma5_pct": rounded(pct_change(last, ma5)),
        "bias_ma20_pct": rounded(pct_change(last, ma20)),
        "bias_ma60_pct": rounded(pct_change(last, ma60)),
        "ma5_slope_5d_pct": rounded(ma5_slope),
        "ma20_slope_5d_pct": rounded(ma20_slope),
        "ma60_slope_20d_pct": rounded(ma60_slope),
        "ma_alignment": alignment,
        "return_5d_pct": rounded(ret5),
        "return_20d_pct": rounded(ret20),
        "return_60d_pct": rounded(ret60),
        "annualized_volatility_pct": rounded(volatility),
        "daily_volatility_pct": rounded(volatility / math.sqrt(252) if volatility is not None else None),
        "annualized_volatility_window_days": len(sample),
        "volatility_percentile_in_sample_pct": rounded(volatility_percentile),
        "volatility_assessment": volatility_label,
        "relative_volume_20d": rounded(relative_volume),
        "volume_baseline_19d": rounded(volume_baseline, 2),
        "volume_5d_change_pct": rounded(volume_5d_change),
        "relative_volume_baseline_days": 19 if relative_volume is not None else None,
        "relative_volume_definition": "最新交易日成交量/前19个交易日平均成交量",
        "return_window_days": 20 if ret20 is not None else None,
        "return_definition": "C_t/C_(t-20)-1，基于同一复权口径收盘价",
        "rsi14": rounded(rsi14),
        "macd_dif": rounded(macd_dif, 4),
        "macd_dea": rounded(macd_dea, 4),
        "macd_hist": rounded(macd_hist, 4),
        "atr14": rounded(atr14, 4),
        "atr14_pct": rounded(atr14_pct),
        "high_20d": rounded(high20, 4),
        "low_20d": rounded(low20, 4),
        "high_60d": rounded(high60, 4),
        "low_60d": rounded(low60, 4),
        "range_position_60d_pct": rounded(range_position_60),
        "max_drawdown_60d_pct": rounded(max_drawdown * 100),
        "price_structure_20d": structure,
        "price_adjustment": valid_rows[-1].get("price_adjustment") or (
            "前复权" if "qfq" in str(valid_rows[-1].get("source") or "") else "待核验"
        ),
        "trend_label": trend,
        "trend_score": trend_score,
        "trend_rule_version": "QY-TECH-2.0",
        "trend_basis": trend_basis,
        "source": valid_rows[-1].get("source"),
        "data_date": valid_rows[-1].get("date"),
        "fetched_at": valid_rows[-1].get("fetched_at"),
        "is_stale": any(bool(row.get("is_stale")) for row in rows),
        "sample_size": len(valid_rows),
    }


def has_data_fields(value: dict[str, Any]) -> bool:
    return any(
        not str(key).startswith("_")
        and str(key) not in FUNDAMENTAL_METADATA_KEYS
        and item not in (None, "")
        and not (isinstance(item, float) and math.isnan(item))
        for key, item in value.items()
    )


def to_float(value: Any) -> float | None:
    try:
        if value in (None, "", "-"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
