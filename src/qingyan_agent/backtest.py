"""Backtest gateway plus local fallback simulation."""

from __future__ import annotations

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
        return local_ma_cross_backtest(klines)

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


def local_ma_cross_backtest(klines: list[dict[str, Any]], fast: int = 10, slow: int = 30) -> BacktestResult:
    rows = [row for row in klines if row.get("close") is not None]
    if len(rows) < slow + 2:
        return BacktestResult(
            source="local_fallback",
            metrics={"status": "insufficient_data", "message": "K线样本不足，无法运行均线回测。"},
            logs=["Need at least slow-window + 2 rows."],
        )

    closes = [float(row["close"]) for row in rows]
    cash = 1.0
    position = 0.0
    entry_price = None
    trades = 0
    equity_curve = []
    peak = 1.0
    max_drawdown = 0.0

    for idx in range(slow, len(rows)):
        ma_fast_prev = sum(closes[idx - fast - 1:idx - 1]) / fast
        ma_slow_prev = sum(closes[idx - slow - 1:idx - 1]) / slow
        ma_fast = sum(closes[idx - fast:idx]) / fast
        ma_slow = sum(closes[idx - slow:idx]) / slow
        price = closes[idx]
        cross_up = ma_fast_prev <= ma_slow_prev and ma_fast > ma_slow
        cross_down = ma_fast_prev >= ma_slow_prev and ma_fast < ma_slow

        if cross_up and position == 0:
            position = cash / price
            cash = 0.0
            entry_price = price
            trades += 1
        elif cross_down and position > 0:
            cash = position * price
            position = 0.0
            entry_price = None
            trades += 1

        equity = cash + position * price
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1)
        equity_curve.append({"date": rows[idx].get("date"), "equity": round(equity, 4)})

    final_equity = equity_curve[-1]["equity"] if equity_curve else 1.0
    metrics = {
        "status": "ok",
        "strategy": f"MA{fast}/MA{slow} cross, long-only research simulation",
        "total_return_pct": round((final_equity - 1) * 100, 2),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "trades": trades,
        "sample_rows": len(rows),
        "note": "Local fallback simulation ignores fees, slippage, suspensions, and limit-up/down constraints.",
    }
    return BacktestResult(source="local_fallback", metrics=metrics, equity_curve=equity_curve, logs=["Local fallback backtest completed."])
