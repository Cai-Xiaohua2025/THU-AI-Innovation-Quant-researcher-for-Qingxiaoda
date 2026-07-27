"""Default A-share research universe and symbol inference."""

from __future__ import annotations

import re

from .models import Target


DEFAULT_A_SHARE_UNIVERSE: list[Target] = [
    Target("CNStock", "600519", "贵州茅台", "食品饮料", 95),
    Target("CNStock", "300750", "宁德时代", "电力设备", 95),
    Target("CNStock", "002594", "比亚迪", "汽车", 95),
    Target("CNStock", "600036", "招商银行", "银行", 95),
    Target("CNStock", "000001", "平安银行", "银行", 92),
    Target("CNStock", "601318", "中国平安", "非银金融", 92),
    Target("CNStock", "601899", "紫金矿业", "有色金属", 90),
    Target("CNStock", "600276", "恒瑞医药", "医药生物", 90),
    Target("CNStock", "000858", "五粮液", "食品饮料", 90),
    Target("CNStock", "688981", "中芯国际", "电子", 88),
    Target("CNStock", "601012", "隆基绿能", "电力设备", 88),
    Target("CNStock", "600030", "中信证券", "非银金融", 88),
]

ALIASES = {
    "贵州茅台": DEFAULT_A_SHARE_UNIVERSE[0],
    "茅台": DEFAULT_A_SHARE_UNIVERSE[0],
    "宁德时代": DEFAULT_A_SHARE_UNIVERSE[1],
    "catl": DEFAULT_A_SHARE_UNIVERSE[1],
    "比亚迪": DEFAULT_A_SHARE_UNIVERSE[2],
    "招商银行": DEFAULT_A_SHARE_UNIVERSE[3],
    "招行": DEFAULT_A_SHARE_UNIVERSE[3],
    "平安银行": DEFAULT_A_SHARE_UNIVERSE[4],
    "中国平安": DEFAULT_A_SHARE_UNIVERSE[5],
    "紫金矿业": DEFAULT_A_SHARE_UNIVERSE[6],
    "恒瑞医药": DEFAULT_A_SHARE_UNIVERSE[7],
    "五粮液": DEFAULT_A_SHARE_UNIVERSE[8],
    "中芯国际": DEFAULT_A_SHARE_UNIVERSE[9],
    "隆基绿能": DEFAULT_A_SHARE_UNIVERSE[10],
    "中信证券": DEFAULT_A_SHARE_UNIVERSE[11],
}


def infer_target(prompt: str) -> Target | None:
    text = prompt or ""
    lower = text.lower()
    for alias, target in ALIASES.items():
        if alias.lower() in lower:
            return target
    code_match = re.search(r"(?<!\d)([036]\d{5})(?!\d)", text)
    if code_match:
        code = code_match.group(1)
        for item in DEFAULT_A_SHARE_UNIVERSE:
            if item.symbol == code:
                return item
        return Target("CNStock", code, confidence=78)
    return None


def infer_intent(prompt: str) -> str:
    text = (prompt or "").lower()
    if any(word in text for word in ("选股", "筛选", "股票池", "候选", "排行", "排名", "screen")):
        return "screening"
    if any(word in text for word in ("回测", "策略", "因子", "收益", "回撤", "胜率", "backtest")):
        return "backtest"
    if any(word in text for word in ("财报", "年报", "季报", "利润", "现金流", "roe", "pe", "pb", "基本面")):
        return "fundamental"
    if any(word in text for word in ("公告", "新闻", "消息", "政策", "归因", "为什么")):
        return "announcement"
    if any(word in text for word in ("走势", "k线", "均线", "rsi", "macd", "趋势", "技术")):
        return "technical"
    return "full_research"
