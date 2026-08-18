from __future__ import annotations

from qingyan_agent.market_data.providers import (
    FunctionMarketDataProvider,
    fetch_eastmoney_klines,
    fetch_eastmoney_quote,
    fetch_sina_klines,
    fetch_sina_quote,
    fetch_tencent_klines,
    fetch_tencent_quote,
)
from qingyan_agent.market_data.cninfo import CNInfoProvider
from qingyan_agent.market_data.fundamentals import (
    AkShareFundamentalProvider,
    normalize_fundamental_mapping,
)
from qingyan_agent.market_data.protocols import (
    AnnouncementProvider,
    FundamentalProvider,
    MarketDataProvider,
    SecurityResolverProvider,
)
from qingyan_agent.models import Target


TARGET = Target("CNStock", "600900", "长江电力")


class Response:
    def __init__(self, payload=None, content=b""):
        self.payload = payload
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_tencent_quote_adapter_normalizes_fields():
    fields = [""] * 36
    fields[1], fields[2], fields[3], fields[4], fields[5] = "长江电力", "600900", "28.1", "28", "28.05"
    fields[6], fields[30], fields[32], fields[33], fields[34], fields[35] = "100", "20260816150000", "0.36", "28.2", "27.8", "x/x/1000"
    request = lambda *args, **kwargs: Response(content=f'v_sh600900="{"~".join(fields)}";'.encode("gbk"))

    quote = fetch_tencent_quote(request, TARGET, 1)

    assert quote["symbol"] == "600900"
    assert quote["price"] == 28.1
    assert quote["volume_unit"] == "手"


def test_sina_quote_adapter_converts_share_volume_to_lots():
    fields = [""] * 32
    fields[0:10] = ["长江电力", "28", "27", "28.1", "28.2", "27.8", "", "", "10000", "200000"]
    fields[30:32] = ["2026-08-16", "15:00:00"]
    request = lambda *args, **kwargs: Response(content=f'var hq_str_sh600900="{",".join(fields)}";'.encode("gbk"))

    quote = fetch_sina_quote(request, TARGET, 1)

    assert quote["volume"] == 100.0
    assert quote["change_pct"] > 4


def test_eastmoney_quote_adapter_normalizes_scaled_prices():
    request = lambda *args, **kwargs: Response({"data": {
        "f57": "600900", "f58": "长江电力", "f43": 2810, "f44": 2820,
        "f45": 2780, "f46": 2800, "f60": 2700, "f170": 407,
    }})

    quote = fetch_eastmoney_quote(request, TARGET, 1)

    assert quote["price"] == 28.1
    assert quote["change_pct"] == 4.07


def test_three_kline_adapters_normalize_rows():
    tencent_request = lambda *args, **kwargs: Response({"data": {"sh600900": {
        "qt": {"sh600900": ["", "", "600900"]},
        "qfqday": [["2026-08-15", "28", "28.1", "28.2", "27.8", "100", "1000"]],
    }}})
    sina_request = lambda *args, **kwargs: Response({"result": {"data": [{
        "day": "2026-08-15 00:00:00", "open": "28", "close": "28.1",
        "high": "28.2", "low": "27.8", "volume": "100",
    }]}})
    eastmoney_request = lambda *args, **kwargs: Response({"data": {
        "code": "600900", "klines": ["2026-08-15,28,28.1,28.2,27.8,100,1000"],
    }})

    assert fetch_tencent_klines(tencent_request, TARGET, 1, 1)[0]["close"] == 28.1
    assert fetch_sina_klines(sina_request, TARGET, 1, 1)[0]["date"] == "2026-08-15"
    assert fetch_eastmoney_klines(eastmoney_request, TARGET, 1, 1)[0]["amount"] == 1000.0


def test_function_market_provider_satisfies_unified_protocol():
    provider = FunctionMarketDataProvider(
        "tencent",
        lambda *args, **kwargs: Response(),
        1,
        lambda request, target, timeout: {"symbol": target.symbol},
        lambda request, target, limit, timeout: [{"date": "2026-08-16"}],
    )

    assert isinstance(provider, MarketDataProvider)
    assert provider.quote(TARGET)["symbol"] == "600900"
    assert provider.klines(TARGET, 1)[0]["date"] == "2026-08-16"


def test_cninfo_provider_resolves_and_normalizes_announcements():
    calls = []

    def request(method, url, **kwargs):
        calls.append((url, kwargs["data"]))
        if "topSearch" in url:
            return Response([{
                "code": "600900",
                "zwjc": "长江电力",
                "orgId": "gssh0600900",
                "category": "A股",
            }])
        return Response({"announcements": [{
            "secCode": "600900",
            "secName": "长江电力",
            "orgId": "gssh0600900",
            "announcementTitle": "<em>年度报告</em>",
            "announcementTime": 1786838400000,
            "adjunctUrl": "finalpage/test.PDF",
        }, {
            "secCode": "000001",
            "announcementTitle": "不应串入其他标的",
        }]})

    provider = CNInfoProvider(request, 1)
    match = provider.resolve_security("长江电力")
    rows = provider.announcements(
        Target("CNStock", "600900", "长江电力", org_id="gssh0600900"),
        lookback_days=30,
    )

    assert isinstance(provider, SecurityResolverProvider)
    assert isinstance(provider, AnnouncementProvider)
    assert match and match["orgId"] == "gssh0600900"
    assert rows == [{
        "symbol": "600900",
        "name": "长江电力",
        "org_id": "gssh0600900",
        "title": "年度报告",
        "date": "2026-08-16",
        "url": "https://static.cninfo.com.cn/finalpage/test.PDF",
        "source": "cninfo",
    }]
    assert calls[1][1]["column"] == "sse"
    assert calls[1][1]["plate"] == "sh"


def test_akshare_provider_satisfies_fundamental_protocol():
    assert isinstance(AkShareFundamentalProvider(), FundamentalProvider)


def test_fundamental_normalization_removes_nan_and_empty_values():
    normalized = normalize_fundamental_mapping({
        "日期": "2026-03-31",
        "净资产收益率(%)": 2.97,
        "销售毛利率(%)": float("nan"),
        "资产负债率(%)": None,
        "空文本": "  ",
        "source": "akshare_financial_analysis_indicator",
    })

    assert normalized == {
        "日期": "2026-03-31",
        "净资产收益率(%)": 2.97,
        "source": "akshare_financial_analysis_indicator",
    }
    assert "销售毛利率(%)" not in normalized
