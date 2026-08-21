"""Backtest gateway plus local fallback simulation."""

from __future__ import annotations

import math
import statistics
from typing import Any

import requests

from .config import Settings
from .models import BacktestResult, Target


class BacktestService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run_ma_cross(self, target: Target, klines: list[dict[str, Any]]) -> BacktestResult:
        if self.settings.backtest_gateway_url and self.settings.backtest_gateway_token:
            remote = self._submit_remote(target)
            if remote:
                return remote
        return local_ma_cross_backtest(
            klines,
            fee_bps=self.settings.backtest_fee_bps,
            slippage_bps=self.settings.backtest_slippage_bps,
            risk_free_rate=self.settings.backtest_risk_free_rate,
        )

    def _submit_remote(self, target: Target) -> BacktestResult | None:
        url = f"{self.settings.backtest_gateway_url}/api/agent/v1/backtests"
        headers = {
            "Authorization": f"Bearer {self.settings.backtest_gateway_token}",
            "Content-Type": "application/json",
            "Idempotency-Key": f"qingyan-{target.symbol}-ma-cross",
        }
        payload = {
            "market": target.market,
            "symbol": target.symbol,
            "timeframe": "1D",
            "start_date": "2023-01-01",
            "strictMode": True,
            "code": (
                "fast = SMA(close, 10)\n"
                "slow = SMA(close, 30)\n"
                "df['buy'] = CROSSOVER(fast, slow).fillna(False).astype(bool)\n"
                "df['sell'] = CROSSUNDER(fast, slow).fillna(False).astype(bool)"
            ),
        }
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=self.settings.request_timeout_sec)
            if response.status_code >= 400:
                return None
            data = response.json()
            return BacktestResult(
                source="external_backtest_gateway",
                metrics={"status": data.get("message") or "submitted", "raw": data.get("data") or data},
                logs=["Submitted MA cross strategy to configured backtest gateway."],
            )
        except Exception:
            return None


def local_ma_cross_backtest(
    klines: list[dict[str, Any]],
    fast: int = 10,
    slow: int = 30,
    *,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
    risk_free_rate: float = 0.0,
) -> BacktestResult:
    if fast < 1 or slow < 2 or fast >= slow:
        raise ValueError("moving-average windows must satisfy 1 <= fast < slow")
    if fee_bps < 0 or slippage_bps < 0:
        raise ValueError("fee_bps and slippage_bps must be non-negative")

    rows = []
    for row in klines:
        try:
            close = float(row.get("close"))
        except (TypeError, ValueError):
            continue
        if close > 0:
            rows.append(dict(row, close=close))
    if len(rows) < slow + 2:
        return BacktestResult(
            source="local_fallback",
            metrics={
                "status": "insufficient_data",
                "message": "K线样本不足，无法运行均线回测。",
                "required_rows": slow + 2,
                "sample_rows": len(rows),
            },
            logs=["Need at least slow-window + 2 rows."],
        )

    closes = [float(row["close"]) for row in rows]
    cash = 1.0
    position = 0.0
    order_count = 0
    completed_trades = 0
    winning_trades = 0
    trade_events: list[dict[str, Any]] = []
    skipped_orders: list[dict[str, Any]] = []
    trade_returns: list[float] = []
    holding_periods: list[int] = []
    equity_curve = []
    peak = 1.0
    max_drawdown = 0.0
    total_fees = 0.0
    total_slippage = 0.0
    turnover = 0.0
    exposed_bars = 0
    entry_equity = None
    entry_index = None
    fee_rate = fee_bps / 10_000
    slippage_rate = slippage_bps / 10_000

    for idx in range(slow, len(rows)):
        ma_fast_prev = sum(closes[idx - fast - 1:idx - 1]) / fast
        ma_slow_prev = sum(closes[idx - slow - 1:idx - 1]) / slow
        ma_fast = sum(closes[idx - fast:idx]) / fast
        ma_slow = sum(closes[idx - slow:idx]) / slow
        price = closes[idx]
        cross_up = ma_fast_prev <= ma_slow_prev and ma_fast > ma_slow
        cross_down = ma_fast_prev >= ma_slow_prev and ma_fast < ma_slow

        # Both moving averages end at idx - 1. The simulated order is executed
        # at rows[idx].close, so the strategy never trades on future data.
        if cross_up and position == 0:
            reason = execution_block_reason(rows[idx], "buy")
            if reason:
                skipped_orders.append({
                    "side": "buy",
                    "date": rows[idx].get("date"),
                    "reason": reason,
                })
            else:
                execution_price = price * (1 + slippage_rate)
                entry_equity = cash
                notional = cash / (1 + fee_rate)
                fee = notional * fee_rate
                position = notional / execution_price
                total_fees += fee
                total_slippage += position * (execution_price - price)
                turnover += notional
                cash = 0.0
                entry_index = idx
                order_count += 1
                trade_events.append({
                    "side": "buy",
                    "date": rows[idx].get("date"),
                    "price": round(execution_price, 6),
                })
        elif cross_down and position > 0:
            reason = execution_block_reason(rows[idx], "sell")
            if reason:
                skipped_orders.append({
                    "side": "sell",
                    "date": rows[idx].get("date"),
                    "reason": reason,
                })
            else:
                execution_price = price * (1 - slippage_rate)
                gross_proceeds = position * execution_price
                fee = gross_proceeds * fee_rate
                cash = gross_proceeds - fee
                total_fees += fee
                total_slippage += position * (price - execution_price)
                turnover += gross_proceeds
                position = 0.0
                completed_trades += 1
                trade_return = cash / entry_equity - 1 if entry_equity else 0.0
                trade_returns.append(trade_return)
                if trade_return > 0:
                    winning_trades += 1
                if entry_index is not None:
                    holding_periods.append(idx - entry_index)
                order_count += 1
                trade_events.append({
                    "side": "sell",
                    "date": rows[idx].get("date"),
                    "price": round(execution_price, 6),
                })
                entry_equity = None
                entry_index = None

        equity = cash + position * price
        if position > 0:
            exposed_bars += 1
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1)
        equity_curve.append({"date": rows[idx].get("date"), "equity": round(equity, 4)})

    final_equity = cash + position * closes[-1] if equity_curve else 1.0
    equity_values = [float(row["equity"]) for row in equity_curve]
    equity_returns = [
        equity_values[index] / equity_values[index - 1] - 1
        for index in range(1, len(equity_values))
        if equity_values[index - 1]
    ]
    periods = max(1, len(equity_values) - 1)
    years = periods / 252
    cagr = final_equity ** (1 / years) - 1 if final_equity > 0 and years > 0 else None
    annualized_volatility = (
        statistics.pstdev(equity_returns) * math.sqrt(252)
        if len(equity_returns) > 1 else 0.0
    )
    daily_risk_free = (1 + risk_free_rate) ** (1 / 252) - 1
    sharpe = None
    if len(equity_returns) > 1 and statistics.pstdev(equity_returns) > 0:
        sharpe = (
            (statistics.mean(equity_returns) - daily_risk_free)
            / statistics.pstdev(equity_returns)
            * math.sqrt(252)
        )
    calmar = cagr / abs(max_drawdown) if cagr is not None and max_drawdown < 0 else None
    benchmark_return = closes[-1] / closes[slow] - 1 if closes[slow] else 0.0
    metrics = {
        "status": "ok",
        "strategy": f"MA{fast}/MA{slow} cross, long-only research simulation",
        "signal_assumption": "均线信号仅使用截至前一条K线的收盘价，下一条K线按收盘价模拟成交。",
        "execution_price": "next_bar_close",
        "total_return_pct": round((final_equity - 1) * 100, 2),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "cagr_pct": rounded_pct(cagr),
        "annualized_volatility_pct": rounded_pct(annualized_volatility),
        "sharpe_ratio": rounded_value(sharpe),
        "calmar_ratio": rounded_value(calmar),
        # Keep `trades` as a compatibility alias for historical clients. Its
        # precise meaning is order events, not completed round trips.
        "trades": order_count,
        "order_count": order_count,
        "completed_trades": completed_trades,
        "winning_trades": winning_trades,
        "win_rate_pct": round(winning_trades / completed_trades * 100, 2) if completed_trades else None,
        "average_trade_return_pct": (
            round(statistics.mean(trade_returns) * 100, 2) if trade_returns else None
        ),
        "average_holding_bars": (
            round(statistics.mean(holding_periods), 2) if holding_periods else None
        ),
        "open_position": position > 0,
        "trade_events": trade_events,
        "skipped_order_count": len(skipped_orders),
        "skipped_orders": skipped_orders,
        "exposure_pct": round(exposed_bars / len(equity_curve) * 100, 2) if equity_curve else 0.0,
        "turnover_pct": round(turnover * 100, 2),
        "buy_and_hold_return_pct": round(benchmark_return * 100, 2),
        "excess_return_pct": round(((final_equity - 1) - benchmark_return) * 100, 2),
        "total_fees_pct": round(total_fees * 100, 4),
        "estimated_slippage_cost_pct": round(total_slippage * 100, 4),
        "fee_bps": fee_bps,
        "slippage_bps": slippage_bps,
        "risk_free_rate": risk_free_rate,
        "sample_rows": len(rows),
        "sample_start_date": rows[0].get("date"),
        "sample_end_date": rows[-1].get("date"),
        "simulation_start_date": rows[slow].get("date"),
        "simulation_end_date": rows[-1].get("date"),
        "signal_warmup_bars": slow,
        "note": (
            "Local fallback simulation does not force-close the final position. Configured fees and "
            "slippage are applied; suspension, zero-volume and limit-up/down constraints are honored "
            "only when the supplied K-line rows explicitly contain those flags. Corporate actions "
            "beyond the supplied price-adjustment series and order-book liquidity are not modeled."
        ),
    }
    return BacktestResult(source="local_fallback", metrics=metrics, equity_curve=equity_curve, logs=["Local fallback backtest completed."])


def execution_block_reason(row: dict[str, Any], side: str) -> str:
    if flag_true(row.get("is_suspended")) or flag_true(row.get("suspended")):
        return "suspended"
    if "volume" in row:
        try:
            if float(row.get("volume") or 0) <= 0:
                return "zero_volume"
        except (TypeError, ValueError):
            return "invalid_volume"
    if side == "buy" and flag_true(row.get("limit_up")):
        return "limit_up"
    if side == "sell" and flag_true(row.get("limit_down")):
        return "limit_down"
    return ""


def flag_true(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def rounded_pct(value: float | None) -> float | None:
    return round(value * 100, 2) if value is not None and math.isfinite(value) else None


def rounded_value(value: float | None) -> float | None:
    return round(value, 4) if value is not None and math.isfinite(value) else None
