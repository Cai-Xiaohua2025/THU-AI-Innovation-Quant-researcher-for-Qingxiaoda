from __future__ import annotations

from qingyan_agent.models import MarketSnapshot, Target
from qingyan_agent.screening import StockScreener, risk_tags, score_snapshot


TARGET = Target("CNStock", "600000", "测试股份", "测试行业", 90)


def snapshot(**overrides) -> MarketSnapshot:
    values = {
        "target": TARGET,
        "quote": {"price": 10.0},
        "technical": {
            "return_20d_pct": 0.0,
            "trend_label": "区间震荡，方向待确认",
            "annualized_volatility_pct": 20.0,
            "relative_volume_20d": 1.0,
        },
        "fundamentals": {"净资产收益率(%)": 10.0, "资产负债率(%)": 40.0},
        "announcements": [{"title": "测试公告"}],
    }
    values.update(overrides)
    return MarketSnapshot(**values)


def test_relative_volume_factor_and_risk_tag_are_applied():
    item = snapshot(technical={
        "return_20d_pct": 0.0,
        "trend_label": "区间震荡，方向待确认",
        "annualized_volatility_pct": 20.0,
        "relative_volume_20d": 2.8,
    })

    _, factors = score_snapshot(item)

    assert factors["liquidity_activity"] == 87.0
    assert "放量异动" in risk_tags(item, factors)


def test_missing_relative_volume_does_not_invent_liquidity_factor():
    item = snapshot(technical={
        "return_20d_pct": 0.0,
        "trend_label": "区间震荡，方向待确认",
        "annualized_volatility_pct": 20.0,
    })

    _, factors = score_snapshot(item)

    assert "liquidity_activity" not in factors
    assert "放量异动" not in risk_tags(item, factors)


def test_metadata_only_fundamentals_are_unavailable_and_not_scored():
    item = snapshot(fundamentals={
        "_message": "optional fundamentals disabled",
        "source": "configuration",
    })

    score, factors = score_snapshot(item)

    assert factors["financial_quality"] == "pending"
    assert "财务字段待补充" in risk_tags(item, factors)
    assert score == 56.6


def test_empty_fundamental_values_are_not_treated_as_real_data():
    item = snapshot(fundamentals={
        "净资产收益率(%)": None,
        "资产负债率(%)": "",
        "source": "test_provider",
    })

    _, factors = score_snapshot(item)

    assert factors["financial_quality"] == "pending"
    assert "财务字段待补充" in risk_tags(item, factors)


def test_real_fundamental_fields_keep_quality_scoring():
    item = snapshot(fundamentals={
        "source": "test_provider",
        "净资产收益率(%)": 20.0,
        "资产负债率(%)": 45.0,
    })

    _, factors = score_snapshot(item)

    assert factors["financial_quality"] == 71.0
    assert "财务字段待补充" not in risk_tags(item, factors)


def test_score_is_clamped_and_missing_sources_are_tagged():
    item = snapshot(
        quote={},
        technical={
            "return_20d_pct": 10000.0,
            "trend_label": "趋势改善",
            "annualized_volatility_pct": 0.0,
            "relative_volume_20d": 99.0,
        },
        fundamentals={},
        announcements=[],
    )

    score, factors = score_snapshot(item)
    tags = risk_tags(item, factors)

    assert 0 <= score <= 100
    assert "财务字段待补充" in tags
    assert "公告检索待核验" in tags
    assert "实时行情不可用" in tags


def test_screener_sorts_results_and_respects_limit():
    class DataClient:
        def collect(self, target):
            return snapshot(
                target=target,
                technical={
                    "return_20d_pct": 20.0 if target.symbol == "600002" else -10.0,
                    "trend_label": "趋势改善" if target.symbol == "600002" else "中期趋势承压",
                    "annualized_volatility_pct": 20.0,
                    "relative_volume_20d": 1.0,
                },
            )

    universe = [
        Target("CNStock", "600001", "较低分"),
        Target("CNStock", "600002", "较高分"),
    ]
    result = StockScreener(DataClient()).screen(universe, limit=1)

    assert len(result.rows) == 1
    assert result.rows[0]["symbol"] == "600002"
