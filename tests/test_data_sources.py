from __future__ import annotations

from threading import Barrier

import pytest

from qingyan_agent.config import Settings
from qingyan_agent.data_sources import (
    AShareDataClient,
    annotate_intraday_bar,
    cninfo_market_params,
    technical_indicators,
    tencent_market_symbol,
)
from qingyan_agent.deterministic_analysis import resolve_answer_profile
from qingyan_agent.contracts import AnswerProfile
from qingyan_agent.models import Target
from qingyan_agent.universe import (
    effective_user_text,
    infer_intent,
    infer_target,
    normalize_security_candidate,
    parse_security_reference,
    security_search_queries,
    target_resolution_notes,
    user_turn_texts,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.content = b""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def make_client(tmp_path):
    return AShareDataClient(Settings(
        report_dir=tmp_path / "reports",
        cache_dir=tmp_path / "cache",
        request_timeout_sec=1,
        llm_base_url="",
        llm_api_key="",
        llm_model="",
    ))


def test_greeting_and_security_query_extraction():
    assert infer_intent("user: 你好") == "greeting"
    assert infer_intent("帮我分析一下长江电力的走势") == "technical"
    assert security_search_queries("帮我分析一下长江电力的走势") == ["长江电力"]
    assert security_search_queries("请分析新光光电近期风险") == ["新光光电"]
    assert infer_target("分析万达轴承 920002") == Target("CNStock", "920002", confidence=78)
    assert infer_target("分析贝特瑞 835185") == Target("CNStock", "835185", confidence=78)
    assert tencent_market_symbol("920002") == "bj920002"
    assert cninfo_market_params("920002") == ("third", "bj")


@pytest.mark.parametrize("prompt", [
    "帮我分析一下长江电力（600900）最近的走势吧，顺便看看近期有没有重要公告，有哪些风险需要注意？",
    "看看长江电力的技术面，还有没有什么重要消息",
    "分析宁德时代最近行情，再说说公司公告",
    "贵州茅台走势如何，有什么事件风险",
])
def test_natural_multi_topic_questions_resolve_to_full_research(prompt):
    assert infer_intent(prompt) == "full_research"


@pytest.mark.parametrize(("prompt", "expected_intent"), [
    ("帮我分析一下近期吉林化纤的相关走势", "technical"),
    ("最近吉林化纤走势怎么样", "technical"),
    ("想看看吉林化纤近期的走势", "technical"),
    ("吉林化纤这只股票最近表现如何", "technical"),
    ("吉林化纤短期趋势怎么看", "technical"),
    ("分析下吉林化纤这票", "full_research"),
    ("请问吉林化纤现在什么情况", "technical"),
    ("帮忙看下吉林化纤最近的行情", "technical"),
    ("我想知道吉林化纤股价最近是强是弱", "technical"),
    ("请对吉林化纤做一个近期技术面分析", "technical"),
    ("吉林化纤今天为什么跌", "announcement"),
    ("吉林化纤最近有什么异动", "announcement"),
    ("吉林化纤近期有什么公告", "announcement"),
    ("吉林化纤最近基本面怎么样", "fundamental"),
    ("看一下吉林化纤的业绩和估值", "fundamental"),
    ("吉林化纤技术面和公告一起分析", "full_research"),
])
def test_student_style_queries_extract_security_and_intent(prompt, expected_intent):
    assert security_search_queries(prompt)[0] == "吉林化纤"
    assert infer_intent(prompt) == expected_intent


@pytest.mark.parametrize(("prompt", "expected_query", "expected_intent"), [
    ("能不能看看长江电力最近走得怎么样", "长江电力", "technical"),
    ("麻烦分析宁德时代后市", "宁德时代", "technical"),
    ("中航光电最近有啥消息", "中航光电", "announcement"),
    ("吉林化纤咋回事", "吉林化纤", "announcement"),
    ("长江电力这两天行情咋样", "长江电力", "technical"),
    ("能给我看看吉林化纤吗", "吉林化纤", "full_research"),
    ("吉林化纤最近咋样啊", "吉林化纤", "technical"),
    ("关于东方财富近期走势怎么看", "东方财富", "technical"),
    ("比亚迪短线支撑压力怎么看", "比亚迪", "technical"),
    ("请查一下贵州茅台最新公告", "贵州茅台", "announcement"),
    ("我想问一下中芯国际的估值和业绩", "中芯国际", "fundamental"),
    ("万达轴承有没有什么消息", "万达轴承", "announcement"),
    ("新光光电为何突然上涨", "新光光电", "announcement"),
    ("宁德时代最近的量价表现", "宁德时代", "technical"),
    ("帮我做一下长江电力技术面与公告分析", "长江电力", "full_research"),
])
def test_broader_classmate_query_simulation(prompt, expected_query, expected_intent):
    assert security_search_queries(prompt)[0] == expected_query
    assert infer_intent(prompt) == expected_intent


def test_classmate_query_with_code_prefers_exact_six_digit_symbol():
    assert security_search_queries("看看吉林化纤（000420）近期表现")[0] == "000420"
    assert infer_target("看看吉林化纤（000420）近期表现") == Target(
        "CNStock", "000420", confidence=78,
    )


def test_multiturn_colloquial_followup_inherits_previous_security_query():
    prompt = "\n".join([
        "user: 帮我看看吉林化纤最近走势",
        "assistant: 已完成初步分析。",
        "user: 那后面怎么看呢",
    ])
    queries = security_search_queries(prompt)
    assert "吉林化纤" in queries
    assert infer_intent(prompt) == "technical"


@pytest.mark.parametrize(("wrapped", "expected"), [
    ("近期吉林化纤的相关走势", "吉林化纤"),
    ("吉林化纤这只股票最近表现如何", "吉林化纤"),
    ("请对中航光电做一个近期技术面分析", "中航光电"),
    ("想看看长江电力近期的股价走势", "长江电力"),
    ("帮忙看下新光光电现在什么情况", "新光光电"),
    ("万达轴承后面怎么看", "万达轴承"),
])
def test_normalize_security_candidate_for_common_wrappers(wrapped, expected):
    assert normalize_security_candidate(wrapped) == expected


def test_resolve_jilin_chemical_fiber_from_student_style_request(monkeypatch, tmp_path):
    client = make_client(tmp_path)
    prompt = "帮我分析一下近期吉林化纤的相关走势"

    def fake_request(method, url, **kwargs):
        assert method == "POST"
        assert kwargs["data"]["keyWord"] == "吉林化纤"
        return FakeResponse([{
            "code": "000420",
            "zwjc": "吉林化纤",
            "orgId": "gssz0000420",
            "category": "A股",
        }])

    monkeypatch.setattr(client, "_request", fake_request)
    target = client.resolve_target(prompt, infer_target(prompt))
    assert target == Target("CNStock", "000420", "吉林化纤", "", 96, "gssz0000420")


@pytest.mark.parametrize("prompt", [
    "请解读中航光电近期公告，区分公告事实、事件影响、潜在催化和需要继续核验的风险。",
    "解读中航光电近期公告",
    "分析一下中航光电的近期公告",
    "中航光电最近有什么公告",
    "请看一下中航光电公告",
])
def test_security_query_removes_announcement_request_language(prompt):
    assert security_search_queries(prompt)[0] == "中航光电"


def test_resolve_target_for_recent_announcement_request(monkeypatch, tmp_path):
    client = make_client(tmp_path)
    prompt = "请解读中航光电近期公告，区分公告事实、事件影响、潜在催化和需要继续核验的风险。"

    def fake_request(method, url, **kwargs):
        assert method == "POST"
        assert kwargs["data"]["keyWord"] == "中航光电"
        return FakeResponse([{
            "code": "002179",
            "zwjc": "中航光电",
            "orgId": "9900003783",
            "category": "A股",
        }])

    monkeypatch.setattr(client, "_request", fake_request)
    target = client.resolve_target(prompt, infer_target(prompt))
    assert target == Target("CNStock", "002179", "中航光电", "", 96, "9900003783")


def test_multiturn_followup_inherits_target_only_from_user_messages():
    prompt = "\n".join([
        "user: 你好，帮我分析一下长江电力的走势",
        "assistant: 上一轮分析了艾森股份 688720，但这只是模型回答。",
        "user: 1. 纯技术面版",
    ])
    assert user_turn_texts(prompt) == ["你好，帮我分析一下长江电力的走势", "1. 纯技术面版"]
    assert infer_target(prompt) is None
    assert infer_intent(prompt) == "technical"
    assert "长江电力" in security_search_queries(prompt)
    assert "688720" not in security_search_queries(prompt)


def test_multiturn_latest_user_target_overrides_earlier_target():
    prompt = "\n".join([
        "user: 分析宁德时代 300750 的走势",
        "assistant: 已完成。",
        "user: 换成贵州茅台 600519",
    ])
    target = infer_target(prompt)
    assert target is not None
    assert target.symbol == "600519"


def test_latest_invalid_code_and_new_name_do_not_inherit_previous_security():
    latest = "请分析吉林化纤004200近期走势，注明数据日期、均线结构、量能变化、趋势判断和主要风险。"
    prompt = "\n".join([
        "user: 请分析长江电力 600900 近期走势",
        "assistant: 已完成长江电力分析。",
        f"user: {latest}",
    ])

    reference = parse_security_reference(latest)

    assert reference.raw_codes == ("004200",)
    assert reference.valid_codes == ()
    assert reference.name_queries == ("吉林化纤",)
    assert infer_target(prompt) is None
    assert security_search_queries(prompt, infer_target(prompt)) == ["吉林化纤"]


def test_resolve_new_name_with_mistyped_code_and_expose_correction_note(monkeypatch, tmp_path):
    client = make_client(tmp_path)
    prompt = "\n".join([
        "user: 分析长江电力 600900",
        "assistant: 已完成。",
        "user: 请分析吉林化纤004200近期走势",
    ])
    queries = []

    def fake_request(method, url, **kwargs):
        queries.append(kwargs["data"]["keyWord"])
        return FakeResponse([{
            "code": "000420",
            "zwjc": "吉林化纤",
            "orgId": "gssz0000420",
            "category": "A股",
        }])

    monkeypatch.setattr(client, "_request", fake_request)
    target = client.resolve_target(prompt, infer_target(prompt))

    assert queries == ["吉林化纤"]
    assert target == Target("CNStock", "000420", "吉林化纤", "", 96, "gssz0000420")
    assert target_resolution_notes("请分析吉林化纤004200近期走势", target) == [
        "输入代码 004200 不是有效的公开 A 股代码；已按公司名称核验为吉林化纤（000420）。"
    ]


def test_resolve_name_only_switch_before_historical_target(monkeypatch, tmp_path):
    client = make_client(tmp_path)
    prompt = "user: 分析长江电力 600900\nassistant: 已完成\nuser: 换成吉林化纤"

    def fake_request(method, url, **kwargs):
        assert kwargs["data"]["keyWord"] == "吉林化纤"
        return FakeResponse([{
            "code": "000420",
            "zwjc": "吉林化纤",
            "orgId": "gssz0000420",
            "category": "A股",
        }])

    monkeypatch.setattr(client, "_request", fake_request)

    assert infer_target(prompt) is None
    assert client.resolve_target(prompt, infer_target(prompt)).symbol == "000420"


def test_conflicting_valid_code_and_company_name_are_not_silently_resolved(monkeypatch, tmp_path):
    client = make_client(tmp_path)
    prompt = "user: 分析长江电力 600900\nassistant: 已完成\nuser: 分析吉林化纤 600900"

    def fake_request(method, url, **kwargs):
        query = kwargs["data"]["keyWord"]
        if query == "600900":
            return FakeResponse([{
                "code": "600900",
                "zwjc": "长江电力",
                "orgId": "gssh0600900",
                "category": "A股",
            }])
        assert query == "吉林化纤"
        return FakeResponse([{
            "code": "000420",
            "zwjc": "吉林化纤",
            "orgId": "gssz0000420",
            "category": "A股",
        }])

    monkeypatch.setattr(client, "_request", fake_request)
    target = client.resolve_target(prompt, infer_target(prompt))

    assert target is None
    assert "名称与证券代码可能不一致" in target_resolution_notes(
        "分析吉林化纤 600900",
        target,
    )[0]


def test_latest_user_turn_controls_profile_without_assistant_text_pollution():
    prompt = "\n".join([
        "user: 请分析长江电力 600900 近期走势",
        "assistant: 你还可以选择投研纪要简版，或查看贵州茅台 600519。",
        "user: 继续分析长江电力 600900：技术面 + 公告事件版",
    ])

    current = effective_user_text(prompt)

    assert current == "继续分析长江电力 600900：技术面 + 公告事件版"
    assert "简版" not in current
    assert "贵州茅台" not in current
    assert resolve_answer_profile(current) == AnswerProfile.STANDARD
    assert infer_intent(prompt) == "full_research"
    assert infer_target(prompt).symbol == "600900"


@pytest.mark.parametrize(("choice", "expected_text"), [
    ("1", "纯技术面版"),
    ("选2", "技术面 + 公告事件版"),
    ("第三种", "综合研究投研纪要简版"),
])
def test_effective_user_text_expands_numeric_followup_without_assistant_context(choice, expected_text):
    prompt = f"user: 分析长江电力 600900\nassistant: 可选三个版本\nuser: {choice}"

    assert expected_text in effective_user_text(prompt)


def test_intraday_bar_annotation_distinguishes_partial_and_completed_daily_bar():
    intraday = {"data_date": "2026-08-17"}
    completed = {"data_date": "2026-08-17"}

    annotate_intraday_bar({"market_time": "20260817142838"}, intraday)
    annotate_intraday_bar({"market_time": "20260817150100"}, completed)

    assert intraday["is_intraday"] is True
    assert intraday["bar_status"] == "intraday_partial"
    assert intraday["market_snapshot_time"] == "20260817142838"
    assert completed["is_intraday"] is False
    assert completed["bar_status"] == "completed_daily_bar"


def test_collect_only_calls_sources_required_by_current_topics(monkeypatch, tmp_path):
    client = make_client(tmp_path)
    target = Target("CNStock", "600900", "长江电力", confidence=96)
    monkeypatch.setattr(client, "resolve_target", lambda prompt, inferred=None: target)
    monkeypatch.setattr(client, "quote", lambda unused: {"price": 28.0, "source": "test"})
    monkeypatch.setattr(client, "klines", lambda unused, limit: [])
    monkeypatch.setattr(
        client,
        "fundamentals",
        lambda unused: pytest.fail("technical scope must not fetch fundamentals"),
    )
    monkeypatch.setattr(
        client,
        "announcements",
        lambda unused, include_text=False: pytest.fail("technical scope must not fetch announcements"),
    )

    result = client.collect(target, topics={"technical"})

    assert result.quote["price"] == 28.0
    assert result.fundamentals == {}
    assert result.announcements == []
    assert {status.source for status in result.statuses} == {"market_quote", "market_kline"}


def test_fundamental_cache_is_normalized_before_reuse(monkeypatch, tmp_path):
    client = AShareDataClient(Settings(
        report_dir=tmp_path / "reports",
        cache_dir=tmp_path / "cache",
        enable_akshare=True,
        llm_base_url="",
        llm_api_key="",
        llm_model="",
    ))
    cached = {
        "日期": "2026-03-31",
        "净资产收益率(%)": 2.97,
        "销售毛利率(%)": float("nan"),
        "source": "akshare_financial_analysis_indicator",
    }
    writes = []
    monkeypatch.setattr(client, "_read_cache", lambda *args, **kwargs: cached)
    monkeypatch.setattr(client, "_write_cache", lambda key, value: writes.append((key, value)))

    result = client.fundamentals(Target("CNStock", "600900", "长江电力"))

    assert "销售毛利率(%)" not in result
    assert result["净资产收益率(%)"] == 2.97
    assert writes and "销售毛利率(%)" not in writes[0][1]


@pytest.mark.parametrize(("choice", "expected"), [
    ("1", "technical"),
    ("1. **纯技术面版**，2. 技术面 + 公告事件版，3. 投研纪要简版", "technical"),
    ("选2", "full_research"),
    ("第三种", "full_research"),
])
def test_followup_choice_intent(choice, expected):
    prompt = f"user: 分析宁德时代走势\nassistant: 请选择版本\nuser: {choice}"
    assert infer_intent(prompt) == expected


def test_resolve_target_from_cninfo_name(monkeypatch, tmp_path):
    client = make_client(tmp_path)

    def fake_request(method, url, **kwargs):
        assert method == "POST"
        assert kwargs["data"]["keyWord"] == "长江电力"
        return FakeResponse([{
            "code": "600900",
            "zwjc": "长江电力",
            "orgId": "gssh0600900",
            "category": "A股",
        }])

    monkeypatch.setattr(client, "_request", fake_request)
    target = client.resolve_target("帮我分析一下长江电力的走势")
    assert target == Target("CNStock", "600900", "长江电力", "", 96, "gssh0600900")


def test_resolve_target_from_previous_user_turn(monkeypatch, tmp_path):
    client = make_client(tmp_path)
    prompt = "\n".join([
        "user: 帮我分析一下长江电力的走势",
        "assistant: 已完成上一轮分析。",
        "user: 1. 纯技术面版",
    ])

    def fake_request(method, url, **kwargs):
        assert kwargs["data"]["keyWord"] == "长江电力"
        return FakeResponse([{
            "code": "600900",
            "zwjc": "长江电力",
            "orgId": "gssh0600900",
            "category": "A股",
        }])

    monkeypatch.setattr(client, "_request", fake_request)
    target = client.resolve_target(prompt, infer_target(prompt))
    assert target is not None
    assert target.symbol == "600900"
    assert target.name == "长江电力"


def test_quote_falls_back_after_tencent_failure(monkeypatch, tmp_path):
    client = make_client(tmp_path)
    target = Target("CNStock", "600900", "长江电力", confidence=96, org_id="gssh0600900")

    monkeypatch.setattr(client, "_fetch_tencent_quote", lambda unused: (_ for _ in ()).throw(RuntimeError("blocked")))
    monkeypatch.setattr(client, "_fetch_sina_quote", lambda unused: {
        "symbol": "600900",
        "name": "长江电力",
        "price": 28.1,
        "change_pct": -0.5,
    })
    monkeypatch.setattr(client, "_fetch_eastmoney_quote", lambda unused: pytest.fail("third source should not run"))

    quote = client.quote(target)
    assert quote["symbol"] == "600900"
    assert quote["source"] == "sina_quote"
    assert quote["is_stale"] is False
    assert quote["data_mode"] == "online_with_short_cache"
    assert quote["fetched_at"]


def test_bse_name_resolution_prefers_current_920_code(monkeypatch, tmp_path):
    client = make_client(tmp_path)

    def fake_request(method, url, **kwargs):
        assert kwargs["data"]["keyWord"] == "万达轴承"
        return FakeResponse([{
            "code": "920002",
            "zwjc": "万达轴承",
            "orgId": "gfbj0873843",
            "category": "A股",
        }])

    monkeypatch.setattr(client, "_request", fake_request)
    target = client.resolve_target("分析万达轴承的走势")
    assert target == Target("CNStock", "920002", "万达轴承", "", 96, "gfbj0873843")


def test_bse_old_code_is_normalized_to_current_920_code(monkeypatch, tmp_path):
    client = make_client(tmp_path)
    calls = []

    def fake_request(method, url, **kwargs):
        query = kwargs["data"]["keyWord"]
        calls.append(query)
        if query == "835185":
            return FakeResponse([{
                "code": "835185",
                "zwjc": "贝特瑞",
                "orgId": "gfbj0835185",
                "category": "A股",
            }])
        return FakeResponse([
            {"code": "835185", "zwjc": "贝特瑞", "orgId": "gfbj0835185", "category": "A股"},
            {"code": "920185", "zwjc": "贝特瑞", "orgId": "gfbj0835185", "category": "A股"},
        ])

    monkeypatch.setattr(client, "_request", fake_request)
    target = client.resolve_target("分析贝特瑞 835185", infer_target("分析贝特瑞 835185"))
    assert calls == ["835185", "贝特瑞"]
    assert target is not None
    assert target.symbol == "920185"


def test_bse_kline_falls_back_to_sina_unadjusted(monkeypatch, tmp_path):
    client = make_client(tmp_path)
    target = Target("CNStock", "920002", "万达轴承", confidence=96, org_id="gfbj0873843")
    rows = [{
        "date": f"2026-01-{index + 1:02d}",
        "open": 10.0,
        "close": 10.0 + index,
        "high": 11.0 + index,
        "low": 9.0,
        "volume": 100000.0,
        "amount": None,
    } for index in range(20)]
    monkeypatch.setattr(client, "_fetch_tencent_klines", lambda unused, limit: [])
    monkeypatch.setattr(client, "_fetch_sina_klines", lambda unused, limit: rows)
    monkeypatch.setattr(client, "_fetch_eastmoney_klines", lambda unused, limit: pytest.fail("third source should not run"))

    result = client.klines(target, limit=180)
    assert len(result) == 20
    assert result[-1]["source"] == "sina_unadjusted_kline"
    assert result[-1]["price_adjustment"] == "不复权"


def test_kline_uses_tencent_and_writes_identity_cache(monkeypatch, tmp_path):
    client = make_client(tmp_path)
    target = Target("CNStock", "688011", "新光光电", confidence=96, org_id="9900038995")
    rows = [
        {
            "date": f"2026-01-{index + 1:02d}",
            "open": 10.0,
            "close": 10.0 + index,
            "high": 11.0 + index,
            "low": 9.0,
            "volume": 1000.0,
            "amount": 10000.0,
        }
        for index in range(20)
    ]
    monkeypatch.setattr(client, "_fetch_tencent_klines", lambda unused, limit: rows)
    monkeypatch.setattr(client, "_fetch_eastmoney_klines", lambda unused, limit: pytest.fail("fallback should not run"))

    result = client.klines(target, limit=180)
    assert len(result) == 20
    assert result[-1]["source"] == "tencent_qfq_kline"
    cached = client._read_cache("kline_688011_180.json")
    assert cached["symbol"] == "688011"
    assert len(cached["rows"]) == 20


def test_enabling_fundamentals_ignores_old_disabled_metadata_cache(monkeypatch, tmp_path):
    settings = Settings(
        report_dir=tmp_path / "reports",
        cache_dir=tmp_path / "cache",
        enable_akshare=True,
        llm_base_url="",
        llm_api_key="",
        llm_model="",
    )
    client = AShareDataClient(settings)
    target = Target("CNStock", "600900", "长江电力", confidence=96)
    client._write_cache("fundamental_600900.json", {
        "_message": "optional akshare fundamentals disabled",
    })
    monkeypatch.setattr(client.fundamental_provider, "fundamentals", lambda unused: {
        "净资产收益率(%)": 12.5,
        "source": "akshare_financial_analysis_indicator",
    })

    result = client.fundamentals(target)

    assert result["净资产收益率(%)"] == 12.5
    assert "_message" not in result


def test_announcements_use_org_id_and_drop_cross_symbol_rows(monkeypatch, tmp_path):
    client = make_client(tmp_path)
    target = Target("CNStock", "688011", "新光光电", confidence=96, org_id="9900038995")
    captured = {}

    def fake_request(method, url, **kwargs):
        captured.update(kwargs["data"])
        return FakeResponse({
            "announcements": [
                {
                    "secCode": "688720",
                    "secName": "艾森股份",
                    "orgId": "9900046652",
                    "announcementTitle": "错误串标公告",
                    "announcementTime": 1786723200000,
                    "adjunctUrl": "finalpage/incorrect.pdf",
                },
                {
                    "secCode": "688011",
                    "secName": "新光光电",
                    "orgId": "9900038995",
                    "announcementTitle": "新光光电正确公告",
                    "announcementTime": 1786723200000,
                    "adjunctUrl": "finalpage/correct.pdf",
                },
            ]
        })

    monkeypatch.setattr(client, "_request", fake_request)
    rows = client.announcements(target)
    assert captured["stock"] == "688011,9900038995"
    assert [row["symbol"] for row in rows] == ["688011"]
    assert rows[0]["name"] == "新光光电"
    assert rows[0]["title"] == "新光光电正确公告"


def test_announcements_optionally_enrich_recent_pdf_text(monkeypatch, tmp_path):
    client = make_client(tmp_path)
    target = Target("CNStock", "688011", "新光光电", confidence=96, org_id="9900038995")
    monkeypatch.setattr(client, "_request", lambda *args, **kwargs: FakeResponse({
        "announcements": [{
            "secCode": "688011",
            "secName": "新光光电",
            "orgId": "9900038995",
            "announcementTitle": "正文提取测试公告",
            "announcementTime": 1786723200000,
            "adjunctUrl": "finalpage/correct.pdf",
        }]
    }))
    monkeypatch.setattr(client.announcement_reader, "enrich", lambda rows: [dict(
        rows[0],
        attachment={"status": "ok", "text": "[第1页]\n公告事实"},
    )])
    rows = client.announcements(target, include_text=True)
    assert rows[0]["attachment"]["status"] == "ok"
    assert "公告事实" in rows[0]["attachment"]["text"]


def test_bse_announcements_use_bj_market_params(monkeypatch, tmp_path):
    client = make_client(tmp_path)
    target = Target("CNStock", "920002", "万达轴承", confidence=96, org_id="gfbj0873843")
    captured = {}

    def fake_request(method, url, **kwargs):
        captured.update(kwargs["data"])
        return FakeResponse({"announcements": []})

    monkeypatch.setattr(client, "_request", fake_request)
    client.announcements(target)
    assert captured["stock"] == "920002,gfbj0873843"
    assert captured["column"] == "third"
    assert captured["plate"] == "bj"


def test_legacy_announcement_cache_is_rejected(tmp_path):
    client = make_client(tmp_path)
    client.settings.cache_dir.mkdir(parents=True, exist_ok=True)
    client._write_cache("announcements_688011.json", [{"title": "艾森股份错误公告"}])
    assert client._read_announcement_cache("announcements_688011.json", "688011") is None


def test_technical_indicators_expose_auditable_research_methodology():
    rows = []
    for index in range(180):
        close = 10 + index * 0.025 + ((index % 9) - 4) * 0.015
        rows.append({
            "date": f"2026-{(index // 28) + 1:02d}-{(index % 28) + 1:02d}",
            "open": close - 0.03,
            "close": close,
            "high": close + 0.12,
            "low": close - 0.11,
            "volume": 100000 + index * 500,
            "source": "test_qfq_kline",
            "price_adjustment": "前复权",
        })

    result = technical_indicators(rows)

    assert result["sample_size"] == 180
    assert result["trend_rule_version"] == "QY-TECH-2.0"
    assert result["trend_basis"]
    assert result["relative_volume_definition"] == "最新交易日成交量/前19个交易日平均成交量"
    assert result["relative_volume_baseline_days"] == 19
    assert result["return_definition"].startswith("C_t/C_(t-20)-1")
    assert result["rsi14"] is not None
    assert result["atr14_pct"] is not None
    assert result["max_drawdown_60d_pct"] <= 0
    assert 0 <= result["range_position_60d_pct"] <= 100
    assert result["volatility_percentile_in_sample_pct"] is not None


def test_collect_runs_independent_sources_with_bounded_concurrency(monkeypatch, tmp_path):
    client = make_client(tmp_path)
    target = Target("CNStock", "600900", "长江电力", confidence=96, org_id="gssh0600900")
    barrier = Barrier(4, timeout=2)

    monkeypatch.setattr(client, "resolve_target", lambda prompt, existing=None: existing or target)

    def quote(unused):
        barrier.wait()
        return {"symbol": target.symbol, "price": 28.1, "source": "test"}

    def klines(unused, limit=180):
        barrier.wait()
        return [{
            "date": f"2026-01-{(index % 28) + 1:02d}",
            "close": 20 + index * 0.1,
            "high": 20.2 + index * 0.1,
            "low": 19.8 + index * 0.1,
            "volume": 1000 + index,
            "source": "test",
        } for index in range(60)]

    def fundamentals(unused):
        barrier.wait()
        return {"净资产收益率(%)": 10.0, "source": "test"}

    def announcements(unused, *, include_text=False):
        barrier.wait()
        return [{"symbol": target.symbol, "title": "测试公告"}]

    monkeypatch.setattr(client, "quote", quote)
    monkeypatch.setattr(client, "klines", klines)
    monkeypatch.setattr(client, "fundamentals", fundamentals)
    monkeypatch.setattr(client, "announcements", announcements)

    result = client.collect(target)

    assert result.quote["price"] == 28.1
    assert result.technical["sample_size"] == 60
    assert all(not status.source.startswith("collect:") for status in result.statuses)
