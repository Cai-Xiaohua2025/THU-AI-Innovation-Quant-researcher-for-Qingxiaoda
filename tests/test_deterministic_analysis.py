from __future__ import annotations

from qingyan_agent.contracts import AnswerProfile
from qingyan_agent.deterministic_analysis import (
    append_missing_announcement_links,
    append_context_safe_followups,
    build_context_safe_followups,
    classify_reference_levels,
    compose_single_answer,
    resolve_answer_profile,
)
from qingyan_agent.models import MarketSnapshot, Target
from qingyan_agent.research_planning import EvidenceCheckResult, research_topics
from qingyan_agent.universe import infer_intent


def sample_snapshot():
    return MarketSnapshot(
        target=Target("CNStock", "600900", "长江电力", confidence=96),
        quote={"price": 28.1, "source": "test"},
        technical={
            "last_close": 28.1,
            "sample_size": 180,
            "trend_label": "区间震荡，方向待确认",
            "trend_basis": ["收盘价位于MA20下方"],
            "trend_rule_version": "QY-TECH-2.0",
            "ma5": 28.144,
            "ma20": 28.545,
            "ma60": 27.273,
            "low_20d": 27.51,
            "high_20d": 29.57,
        },
    )


def test_reference_levels_classify_ma60_as_support_when_below_price():
    snapshot = sample_snapshot()
    levels = classify_reference_levels(snapshot.quote, snapshot.technical)

    assert any(item["label"] == "MA60" for item in levels["support"])
    assert not any(item["label"] == "MA60" for item in levels["resistance"])
    assert any(item["label"] == "MA20" for item in levels["resistance"])


def test_scenarios_use_nearest_directional_levels_and_markdown_spacing():
    snapshot = sample_snapshot()
    answer = compose_single_answer(
        "分析走势",
        snapshot.target,
        "technical",
        snapshot,
        [],
        [],
        None,
        EvidenceCheckResult(100, "complete", ["target", "quote", "technical"], []),
        AnswerProfile.DETAILED,
    )

    assert "支撑观察位" in answer
    assert "MA60 27.273 元" in answer
    assert "收于MA60" not in answer.split("| 偏强情景 |", 1)[1].split("|", 1)[0]
    assert "\n\n| 情景 | 可验证条件 | 研究含义 |" in answer
    assert "证据完备度 100/100（完整）" in answer


def test_announcement_appendix_uses_child_heading_level():
    snapshot = sample_snapshot()
    snapshot.announcements = [{
        "symbol": "600900",
        "title": "测试公告",
        "date": "2026-08-01",
        "url": "https://example.com/test.pdf",
        "source": "cninfo",
        "attachment": {
            "status": "ok",
            "message": "正文已提取",
            "text": "[第1页]\n公告事实",
        },
    }]
    answer = compose_single_answer(
        "看看公告",
        snapshot.target,
        "announcement",
        snapshot,
        [],
        [],
        None,
        EvidenceCheckResult(100, "complete", ["target", "announcements"], []),
        AnswerProfile.DETAILED,
    )

    assert "### 公告附件正文证据" in answer
    assert "#### 测试公告" in answer


def test_standard_answer_does_not_dump_announcement_source_text():
    snapshot = sample_snapshot()
    raw_text = "[第1页]\n这是不应出现在聊天正文中的大段公告原文" * 30
    snapshot.announcements = [{
        "symbol": "600900",
        "title": "测试公告",
        "date": "2026-08-01",
        "url": "https://static.cninfo.com.cn/test.pdf",
        "source": "cninfo",
        "attachment": {"status": "ok", "text": raw_text},
    }]
    analysis = [{
        "title": "测试公告",
        "date": "2026-08-01",
        "source_url": "https://static.cninfo.com.cn/test.pdf",
        "facts": ["公司披露测试公告。"],
        "inferences": ["尚不能判断方向性影响。"],
        "potential_impacts": [],
        "risks": ["需要继续核验正文。"],
        "verification_items": [],
        "source_pages": [1],
    }]

    standard = compose_single_answer(
        "看看走势和公告",
        snapshot.target,
        "full_research",
        snapshot,
        [],
        [],
        None,
        EvidenceCheckResult(100, "complete"),
        AnswerProfile.STANDARD,
        analysis,
    )
    detailed = compose_single_answer(
        "看看走势和公告",
        snapshot.target,
        "full_research",
        snapshot,
        [],
        [],
        None,
        EvidenceCheckResult(100, "complete"),
        AnswerProfile.DETAILED,
        analysis,
    )

    assert "这是不应出现在聊天正文中的大段公告原文" not in standard
    assert "公告原文摘录保留在 Markdown/PDF 报告附录" in standard
    assert "[查看巨潮资讯原文](https://static.cninfo.com.cn/test.pdf)" in standard
    assert "这是不应出现在聊天正文中的大段公告原文" in detailed

    concise = compose_single_answer(
        "帮我简单看看走势和公告",
        snapshot.target,
        "full_research",
        snapshot,
        [],
        [],
        None,
        EvidenceCheckResult(100, "complete"),
        AnswerProfile.CONCISE,
        analysis,
    )
    assert "简单概括" in concise
    assert "正文页码证据" not in concise
    assert "公告事实" not in concise


def test_answer_profile_defaults_to_standard_and_honors_explicit_requests():
    assert resolve_answer_profile("帮我看看长江电力走势") == AnswerProfile.STANDARD
    assert resolve_answer_profile("简单说一下长江电力走势") == AnswerProfile.CONCISE
    assert resolve_answer_profile("帮我简单看看长江电力最近走势和公告") == AnswerProfile.CONCISE
    assert resolve_answer_profile("给我一份详细报告") == AnswerProfile.DETAILED


def test_missing_announcement_source_links_are_appended_after_model_synthesis():
    answer = "## 基本面与事件证据\n- 近期公告包括年度权益分派实施公告。"
    analyses = [{
        "title": "年度权益分派实施公告",
        "date": "2026-07-10",
        "source_url": "https://static.cninfo.com.cn/example.pdf",
    }]

    completed = append_missing_announcement_links(answer, analyses)

    assert "## 公告原文链接" in completed
    assert "[年度权益分派实施公告](https://static.cninfo.com.cn/example.pdf)" in completed
    assert append_missing_announcement_links(completed, analyses) == completed


def test_technical_followups_deepen_broaden_and_reformat_without_repeating_menu():
    target = Target("CNStock", "002046", "国机精工", confidence=96)

    prompts = build_context_safe_followups(
        target,
        question="请分析国机精工 002046 近期走势、均线结构和量能变化",
        intent="technical",
        topics={"technical"},
        technical={"is_intraday": True, "bar_status": "intraday_partial"},
    )

    assert len(prompts) == 3
    assert all("国机精工 002046" in prompt for prompt in prompts)
    assert "收盘后重新核验" in prompts[0]
    assert "近期公告" in prompts[1]
    assert "当前技术面分析" in prompts[2]
    assert "纯技术面版" not in "\n".join(prompts)
    assert "技术面 + 公告事件版" not in "\n".join(prompts)


def test_reformat_followup_has_same_scope_with_or_without_history():
    target = Target("CNStock", "002046", "国机精工", confidence=96)
    prompt = build_context_safe_followups(
        target,
        question="请分析国机精工 002046 近期走势",
        intent="technical",
        topics={"technical"},
    )[2]

    standalone_intent = infer_intent(f"user: {prompt}")
    inherited_intent = infer_intent("\n".join([
        "user: 请分析国机精工 002046 近期走势",
        "assistant: 已完成技术面分析。",
        f"user: {prompt}",
    ]))

    assert standalone_intent == "technical"
    assert inherited_intent == "technical"
    assert research_topics(standalone_intent, prompt) == {"technical"}


def test_followups_rotate_delivery_action_after_memo_request():
    target = Target("CNStock", "002046", "国机精工", confidence=96)
    prompts = build_context_safe_followups(
        target,
        question=(
            "将国机精工 002046 的当前技术面分析整理成一页式投研纪要，"
            "保留核心结论和主要风险"
        ),
        intent="technical",
        topics={"technical"},
    )

    assert "后续跟踪清单" in prompts[2]
    assert "整理成一页式投研纪要" not in prompts[2]


def test_technical_and_announcement_followups_add_fundamental_scope():
    target = Target("CNStock", "002046", "国机精工", confidence=96)
    prompts = build_context_safe_followups(
        target,
        question="结合国机精工 002046 的技术走势和近期公告进行分析",
        intent="full_research",
        topics={"technical", "announcement"},
    )

    assert "基本面与业绩" in prompts[1]
    assert "技术面与公告事件分析" in prompts[2]


def test_append_context_safe_followups_is_idempotent_for_new_marker():
    target = Target("CNStock", "002046", "国机精工", confidence=96)
    answer = append_context_safe_followups(
        "## 研究结论\n- 测试结论",
        target,
        question="分析国机精工 002046 走势",
        intent="technical",
        topics={"technical"},
    )

    assert answer.count("## 接下来可以继续") == 1
    assert append_context_safe_followups(answer, target) == answer
