from __future__ import annotations

from qingyan_agent.compliance import guard_output, normalize_question


def test_normalize_question_rewrites_prohibited_deterministic_trading_language():
    normalized = normalize_question("请保证收益并告诉我必须买入哪只股票")

    assert "保证收益" not in normalized
    assert "必须买入" not in normalized
    assert "情景研究" in normalized


def test_guard_output_appends_compliance_notice_once():
    guarded = guard_output("## 研究结论\n这里只提供公开信息研究。")
    guarded_twice = guard_output(guarded)

    assert "合规提示" in guarded
    assert guarded_twice.count("合规提示") == 1


def test_guard_output_does_not_corrupt_negative_disclaimer():
    guarded = guard_output("本报告不构成投资建议、收益承诺、代客理财或自动交易指令。")

    assert "不构成投资建议、收益承诺、仅作为研究线索" not in guarded
    assert guarded.count("不构成投资建议、收益承诺、代客理财或自动交易指令") == 1


def test_guard_output_still_rewrites_affirmative_unsafe_language():
    guarded = guard_output("我们可以代客理财，而且保证收益。")

    assert "代客理财" not in guarded.partition("合规提示：")[0]
    assert "保证收益" not in guarded.partition("合规提示：")[0]
