from __future__ import annotations

import pytest

from qingyan_agent.backtest import local_ma_cross_backtest


def rows(closes: list[float]) -> list[dict]:
    return [
        {"date": f"2026-01-{index + 1:02d}", "close": close}
        for index, close in enumerate(closes)
    ]


def test_backtest_rejects_invalid_windows():
    with pytest.raises(ValueError):
        local_ma_cross_backtest(rows([10.0] * 10), fast=5, slow=5)


def test_backtest_reports_insufficient_sample():
    result = local_ma_cross_backtest(rows([10.0] * 6), fast=2, slow=5)

    assert result.metrics["status"] == "insufficient_data"
    assert result.metrics["required_rows"] == 7
    assert result.metrics["sample_rows"] == 6


def test_backtest_constant_prices_have_no_orders_or_drawdown():
    result = local_ma_cross_backtest(rows([10.0] * 12), fast=2, slow=5)

    assert result.metrics["status"] == "ok"
    assert result.metrics["order_count"] == 0
    assert result.metrics["completed_trades"] == 0
    assert result.metrics["total_return_pct"] == 0.0
    assert result.metrics["max_drawdown_pct"] == 0.0
    assert result.metrics["open_position"] is False


def test_backtest_cross_up_and_down_uses_next_bar_close_without_lookahead():
    closes = [10, 10, 10, 10, 10, 10, 12, 14, 14, 8, 6, 6]
    result = local_ma_cross_backtest(rows(closes), fast=2, slow=5)

    assert result.metrics["order_count"] == 2
    assert result.metrics["trades"] == 2
    assert result.metrics["completed_trades"] == 1
    assert result.metrics["open_position"] is False
    assert result.metrics["trade_events"] == [
        {"side": "buy", "date": "2026-01-08", "price": 14.0},
        {"side": "sell", "date": "2026-01-11", "price": 6.0},
    ]
    assert result.metrics["total_return_pct"] < 0
    assert result.metrics["max_drawdown_pct"] < 0
    assert result.metrics["execution_price"] == "next_bar_close"


def test_backtest_final_open_position_is_marked_to_market_not_force_closed():
    closes = [10, 10, 10, 10, 10, 10, 12, 14, 16, 18]
    result = local_ma_cross_backtest(rows(closes), fast=2, slow=5)

    assert result.metrics["order_count"] == 1
    assert result.metrics["completed_trades"] == 0
    assert result.metrics["open_position"] is True
    assert result.metrics["trade_events"][0]["side"] == "buy"
    assert result.metrics["total_return_pct"] > 0


def test_backtest_ignores_non_numeric_and_non_positive_closes():
    values = rows([10.0] * 8)
    values.extend([
        {"date": "bad", "close": "not-a-number"},
        {"date": "zero", "close": 0},
    ])

    result = local_ma_cross_backtest(values, fast=2, slow=5)

    assert result.metrics["sample_rows"] == 8


def test_backtest_reports_professional_risk_and_benchmark_metrics():
    closes = [10, 10, 10, 10, 10, 10, 12, 14, 14, 8, 6, 6]
    result = local_ma_cross_backtest(rows(closes), fast=2, slow=5)

    for key in (
        "cagr_pct",
        "annualized_volatility_pct",
        "sharpe_ratio",
        "calmar_ratio",
        "win_rate_pct",
        "exposure_pct",
        "turnover_pct",
        "buy_and_hold_return_pct",
        "excess_return_pct",
    ):
        assert key in result.metrics
    assert 0 <= result.metrics["exposure_pct"] <= 100
    assert result.metrics["turnover_pct"] > 0
    assert result.metrics["win_rate_pct"] == 0.0


def test_backtest_costs_reduce_equity_and_are_reported():
    closes = [10, 10, 10, 10, 10, 10, 12, 14, 14, 8, 6, 6]
    free = local_ma_cross_backtest(rows(closes), fast=2, slow=5)
    costly = local_ma_cross_backtest(
        rows(closes),
        fast=2,
        slow=5,
        fee_bps=20,
        slippage_bps=30,
    )

    assert costly.metrics["total_return_pct"] < free.metrics["total_return_pct"]
    assert costly.metrics["total_fees_pct"] > 0
    assert costly.metrics["estimated_slippage_cost_pct"] > 0
    assert costly.metrics["trade_events"][0]["price"] > free.metrics["trade_events"][0]["price"]
    assert costly.metrics["trade_events"][1]["price"] < free.metrics["trade_events"][1]["price"]


@pytest.mark.parametrize(("field", "value", "reason"), [
    ("limit_up", True, "limit_up"),
    ("is_suspended", True, "suspended"),
    ("volume", 0, "zero_volume"),
])
def test_backtest_skips_blocked_buy_orders(field, value, reason):
    data = rows([10, 10, 10, 10, 10, 10, 12, 14, 16, 18])
    data[7][field] = value

    result = local_ma_cross_backtest(data, fast=2, slow=5)

    assert result.metrics["order_count"] == 0
    assert result.metrics["skipped_order_count"] == 1
    assert result.metrics["skipped_orders"][0]["reason"] == reason


def test_backtest_skips_limit_down_sell_and_keeps_position_marked_to_market():
    data = rows([10, 10, 10, 10, 10, 10, 12, 14, 14, 8, 6, 6])
    data[10]["limit_down"] = True

    result = local_ma_cross_backtest(data, fast=2, slow=5)

    assert result.metrics["order_count"] == 1
    assert result.metrics["completed_trades"] == 0
    assert result.metrics["open_position"] is True
    assert result.metrics["skipped_orders"] == [{
        "side": "sell",
        "date": "2026-01-11",
        "reason": "limit_down",
    }]
