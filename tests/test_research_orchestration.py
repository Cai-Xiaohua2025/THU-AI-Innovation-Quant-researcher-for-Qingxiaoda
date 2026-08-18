from __future__ import annotations

from qingyan_agent.llm_client import LLMResult
from qingyan_agent.models import DataStatus, MarketSnapshot, Target
from qingyan_agent.research_agent import ResearchAgent, answer_uses_resolved_target
from qingyan_agent.research_planning import evaluate_evidence, generate_research_plan


class DataClient:
    target = Target("CNStock", "600900", "长江电力", confidence=96)

    def resolve_target(self, question, inferred=None):
        return self.target

    def collect(self, target, *, include_announcement_text=False):
        return MarketSnapshot(target=target)


class Charts:
    def price_chart(self, *args, **kwargs):
        return None

    def backtest_chart(self, *args, **kwargs):
        return None

    def screening_chart(self, *args, **kwargs):
        return None


class ScopedDataClient(DataClient):
    def __init__(self):
        self.include_announcement_text_calls = []

    def collect(self, target, *, include_announcement_text=False, topics=None):
        self.include_announcement_text_calls.append(include_announcement_text)
        return MarketSnapshot(
            target=target,
            quote={
                "price": 27.98,
                "change_pct": -0.43,
                "source": "tencent_quote",
                "market_time": "20260817142838",
            },
            technical={
                "last_close": 27.98,
                "data_date": "2026-08-17",
                "price_adjustment": "前复权",
                "source": "tencent_qfq_kline",
                "sample_size": 181,
                "trend_label": "区间震荡，方向待确认",
                "trend_rule_version": "QY-TECH-2.0",
                "trend_basis": ["收盘价位于MA20下方", "收盘价位于MA60上方"],
                "ma5": 28.13,
                "ma20": 28.495,
                "ma60": 27.3098,
                "low_20d": 27.51,
                "high_20d": 29.57,
                "relative_volume_20d": 0.56,
                "volume_5d_change_pct": -35.0,
                "return_20d_pct": -3.45,
                "is_intraday": True,
                "bar_status": "intraday_partial",
            },
            fundamentals={
                "日期": "2026-03-31",
                "净资产收益率(%)": 2.97,
                "销售毛利率(%)": float("nan"),
                "source": "akshare_financial_analysis_indicator",
            },
            announcements=[{
                "symbol": "600900",
                "title": "长江电力2025年年度权益分派实施公告",
                "date": "2026-07-10",
                "url": "https://static.cninfo.com.cn/example.pdf",
                "source": "cninfo",
                "attachment": {
                    "status": "ok",
                    "text": "[第1页]\n只允许进入详细报告的公告正文",
                },
            }],
            statuses=[
                DataStatus("market_quote", True, "source=tencent_quote"),
                DataStatus("market_kline", True, "181 rows"),
                DataStatus("fundamental", True, "source=akshare"),
                DataStatus("cninfo_announcement", True, "1 rows"),
                DataStatus("announcement_attachment", True, "1/1 PDFs extracted"),
            ],
        )


class CapturingUpstream:
    configured = True

    def __init__(self):
        self.calls = []

    def synthesize(self, **kwargs):
        self.calls.append(kwargs)
        return LLMResult(error="test uses deterministic fallback")


class SwitchingDataClient(ScopedDataClient):
    def resolve_target(self, question, inferred=None):
        assert inferred is None
        return Target("CNStock", "000420", "吉林化纤", confidence=96, org_id="gssz0000420")


def test_research_agent_returns_auditable_context_without_changing_answer_contract():
    agent = ResearchAgent(DataClient(), object(), object(), Charts(), None)

    output, charts = agent.run("user: 分析长江电力 600900 的走势", [])

    assert charts == []
    assert output.context is not None
    assert output.context.target["symbol"] == "600900"
    assert output.context.completed_at
    assert [step.step_type for step in output.context.plan] == [
        "interpret", "resolve_target", "collect_evidence", "analyze",
        "synthesize", "review", "compose_report",
    ]
    assert output.context.evidence_completeness["grade"] == "partial"
    assert output.context.missing_evidence == ["quote", "technical"]
    assert all(step.status.value == "completed" for step in output.context.plan)
    assert "研究对象：长江电力" in output.answer
    assert '"research_context"' in output.report_markdown


def test_rule_driven_plan_is_bounded_and_intent_specific():
    backtest = generate_research_plan("backtest")
    greeting = generate_research_plan("greeting")
    image_only = generate_research_plan("technical", has_images=True)

    assert [step.step_type for step in backtest].count("backtest") == 1
    assert [step.step_type for step in greeting] == ["interpret", "respond"]
    assert next(step for step in image_only if step.step_type == "resolve_target").required is False
    assert len(backtest) < 10


def test_evidence_check_distinguishes_metadata_only_fundamentals():
    base = {"target": {"symbol": "600900"}}

    missing = evaluate_evidence("fundamental", {
        **base,
        "fundamentals": {"source": "akshare", "_message": "unavailable"},
    })
    available = evaluate_evidence("fundamental", {
        **base,
        "fundamentals": {"净资产收益率(%)": 12.5, "source": "akshare"},
    })

    assert missing.score == 50
    assert missing.missing == ["fundamentals"]
    assert available.score == 100
    assert available.grade == "complete"


def test_evidence_check_accepts_safe_image_without_stock_target():
    result = evaluate_evidence("technical", {
        "target": None,
        "images": [{"status": "ok", "filename": "chart.png"}],
    })

    assert result.score == 100
    assert result.satisfied == ["images"]


def test_standard_chat_hides_raw_announcement_while_detailed_report_keeps_it():
    raw_text = "[第1页]\n公告原始证据仅应进入详细报告"

    class AnnouncementDataClient(DataClient):
        def collect(self, target, *, include_announcement_text=False, topics=None):
            return MarketSnapshot(
                target=target,
                quote={"price": 28.1, "source": "test"},
                technical={"last_close": 28.1, "trend_label": "区间震荡"},
                announcements=[{
                    "symbol": "600900",
                    "title": "年度权益分派实施公告",
                    "date": "2026-07-10",
                    "url": "https://static.cninfo.com.cn/example.pdf",
                    "source": "cninfo",
                    "attachment": {"status": "ok", "text": raw_text},
                }],
            )

    agent = ResearchAgent(AnnouncementDataClient(), object(), object(), Charts(), None)
    output, _ = agent.run("帮我看看长江电力 600900 最近走势，顺便看看公告", [])

    assert "公告原始证据仅应进入详细报告" not in output.answer
    assert "公告事实" in output.answer
    assert "https://static.cninfo.com.cn/example.pdf" in output.answer
    assert "公告原始证据仅应进入详细报告" in output.report_markdown
    assert output.report_markdown.count("公告原始证据仅应进入详细报告") == 1
    assert len(output.answer) < len(output.report_markdown)


def test_concise_question_skips_upstream_and_keeps_bounded_local_answer():
    class Upstream:
        configured = True

        def synthesize(self, **kwargs):
            raise AssertionError("concise answer must not call the upstream model")

    agent = ResearchAgent(DataClient(), object(), object(), Charts(), Upstream())
    output, _ = agent.run("帮我简单看看长江电力 600900 最近走势和公告", [])

    assert len(output.answer) < 2400
    assert "公告附件正文证据" not in output.answer


def test_full_research_only_requires_topics_requested_by_natural_question():
    result = evaluate_evidence(
        "full_research",
        {
            "target": {"symbol": "600900"},
            "quote": {"price": 28.1},
            "technical": {"last_close": 28.1},
            "fundamentals": {"_message": "disabled"},
            "announcements": [{"symbol": "600900", "title": "测试公告"}],
            "statuses": [{"source": "fundamental", "ok": False}],
        },
        "看看长江电力最近的走势，顺便看看近期公告",
    )

    assert result.grade == "complete"
    assert result.score == 100
    assert "fundamentals" not in result.missing
    assert not any("fundamental" in warning for warning in result.warnings)


def test_multiturn_followup_uses_latest_user_scope_and_standard_profile():
    data_client = ScopedDataClient()
    upstream = CapturingUpstream()
    agent = ResearchAgent(data_client, object(), object(), Charts(), upstream)
    latest = "继续分析长江电力 600900：技术面 + 公告事件版"
    prompt = "\n".join([
        "user: 请分析长江电力600900近期走势，注明均线结构和量能变化。",
        "assistant: 上轮结果很长。你也可以选择投研纪要简版，或分析贵州茅台 600519。",
        f"user: {latest}",
    ])

    output, _ = agent.run(prompt, [])

    assert output.context.question == latest
    assert output.context.intent == "full_research"
    assert output.context.conversation_turns == [
        "请分析长江电力600900近期走势，注明均线结构和量能变化。",
        latest,
    ]
    assert data_client.include_announcement_text_calls == [True]
    assert len(upstream.calls) == 1
    assert upstream.calls[0]["question"] == latest
    assert "technical" in upstream.calls[0]["evidence"]
    assert "announcements" in upstream.calls[0]["evidence"]
    assert "fundamentals" not in upstream.calls[0]["evidence"]
    assert "fundamentals" not in output.context.evidence
    assert "| 指标 | 当前值 |" in output.answer
    assert "## 重要公告解读" in output.answer
    assert "## 基本面证据" not in output.answer
    assert "销售毛利率" not in output.answer
    assert "只允许进入详细报告的公告正文" not in output.answer
    assert "只允许进入详细报告的公告正文" in output.report_markdown
    assert "## 基本面证据" not in output.report_markdown
    assert "当前包含盘中尚未完成的当日日K" in output.answer


def test_pure_technical_turn_does_not_expand_to_unrequested_sources_or_report_sections():
    data_client = ScopedDataClient()
    upstream = CapturingUpstream()
    agent = ResearchAgent(data_client, object(), object(), Charts(), upstream)

    output, _ = agent.run(
        "请分析长江电力600900近期走势，注明数据日期、均线结构、量能变化、趋势判断和主要风险。",
        [],
    )

    assert output.context.intent == "technical"
    assert data_client.include_announcement_text_calls == [False]
    assert set(upstream.calls[0]["evidence"]) >= {"target", "quote", "technical", "statuses"}
    assert "fundamentals" not in upstream.calls[0]["evidence"]
    assert "announcements" not in upstream.calls[0]["evidence"]
    assert "fundamentals" not in output.context.evidence
    assert "announcements" not in output.context.evidence
    assert "## 重要公告解读" not in output.answer
    assert "## 基本面证据" not in output.answer
    assert "## 公告与事件证据" not in output.report_markdown
    assert "## 基本面证据" not in output.report_markdown


def test_new_security_with_mistyped_code_replaces_historical_target_everywhere():
    data_client = SwitchingDataClient()
    upstream = CapturingUpstream()
    agent = ResearchAgent(data_client, object(), object(), Charts(), upstream)
    latest = "请分析吉林化纤004200近期走势，注明数据日期、均线结构、量能变化、趋势判断和主要风险。"
    prompt = "\n".join([
        "user: 请分析长江电力600900近期走势",
        "assistant: 已完成长江电力 600900 的分析。",
        f"user: {latest}",
    ])

    output, _ = agent.run(prompt, [])

    assert output.context.question == latest
    assert output.context.target["symbol"] == "000420"
    assert output.context.target["name"] == "吉林化纤"
    assert output.title.startswith("吉林化纤")
    assert "输入代码 004200 不是有效的公开 A 股代码" in output.answer
    assert "研究对象：吉林化纤（000420）" in output.answer
    assert output.answer.count("吉林化纤 000420") >= 3
    assert "结合吉林化纤 000420近期公告" in output.answer
    assert "长江电力" not in output.answer
    assert "600900" not in output.answer
    assert upstream.calls[0]["question"] == latest
    assert upstream.calls[0]["evidence"]["target"]["symbol"] == "000420"
    assert upstream.calls[0]["evidence"]["resolution_notes"]


def test_upstream_target_guard_rejects_explicit_wrong_research_object_only():
    target = Target("CNStock", "000420", "吉林化纤")

    assert answer_uses_resolved_target("## 研究结论\n研究对象：吉林化纤（000420）", target)
    assert not answer_uses_resolved_target("## 研究结论\n研究对象：长江电力（600900）", target)
    assert answer_uses_resolved_target("## 研究结论\n吉林化纤近期处于震荡阶段。", target)
