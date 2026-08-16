from __future__ import annotations

from datetime import datetime

import pytest

from qingyan_agent.config import Settings
from qingyan_agent.data_sources import AShareDataClient, cninfo_market_params, tencent_market_symbol
from qingyan_agent.models import Target
from qingyan_agent.universe import (
    infer_intent,
    infer_target,
    normalize_security_candidate,
    security_search_queries,
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
