"""Default A-share research universe and symbol inference."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Target


A_SHARE_CODE_RE = re.compile(
    r"(?<!\d)(60[0135]\d{3}|68[89]\d{3}|00[0123]\d{3}|30[01]\d{3}|920\d{3}|[48]\d{5})(?!\d)"
)
ANY_SIX_DIGIT_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


@dataclass(frozen=True)
class SecurityReference:
    raw_codes: tuple[str, ...] = ()
    valid_codes: tuple[str, ...] = ()
    name_queries: tuple[str, ...] = ()

    @property
    def explicit(self) -> bool:
        return bool(self.raw_codes or self.name_queries)


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


GREETING_EXACT = {
    "你好",
    "您好",
    "嗨",
    "哈喽",
    "在吗",
    "hi",
    "hello",
    "你是谁",
    "请介绍一下你自己",
    "介绍一下你自己",
    "请说明你的研究能力",
}

GREETING_PHRASES = (
    "你能做什么",
    "你有什么功能",
    "有哪些功能",
    "怎么使用",
    "如何使用",
    "使用说明",
    "能力介绍",
)

SECURITY_QUERY_PREFIXES = (
    "继续分析一下",
    "继续分析",
    "继续看看",
    "继续看",
    "再分析一下",
    "再分析",
    "再看看",
    "再看",
    "接着分析",
    "接着看",
    "换成",
    "换为",
    "改成",
    "改看",
    "改为",
    "将",
    "能不能帮我看看",
    "能不能看看",
    "能否帮我看看",
    "能否看看",
    "能给我看看",
    "可以帮我看看",
    "请帮我做一下",
    "请帮我做一个",
    "请帮我做个",
    "帮我做一下",
    "帮我做一个",
    "帮我做个",
    "能不能帮我分析一下",
    "能不能帮我分析",
    "能否帮我分析一下",
    "能否帮我分析",
    "请帮忙分析一下",
    "请帮忙分析",
    "帮忙分析一下",
    "帮忙分析",
    "麻烦分析一下",
    "麻烦分析",
    "想请你分析一下",
    "想请你分析",
    "请帮我解读一下",
    "请帮我解读",
    "帮我解读一下",
    "帮我解读",
    "请解读一下",
    "请解读",
    "解读一下",
    "解读",
    "请帮我看一下",
    "请帮我看看",
    "请帮我看下",
    "帮我看一下",
    "帮我看看",
    "帮我看下",
    "帮忙看一下",
    "帮忙看看",
    "帮忙看下",
    "麻烦看一下",
    "麻烦看看",
    "麻烦看下",
    "请看一下",
    "请看看",
    "请看下",
    "看一下",
    "看下",
    "想了解一下",
    "想了解",
    "想看看",
    "想看一下",
    "我想知道",
    "我想问问",
    "我想问一下",
    "请问一下",
    "请问",
    "请帮我",
    "麻烦帮我",
    "我想了解一下",
    "我想了解",
    "帮我分析一下",
    "帮我分析",
    "请分析一下",
    "请分析",
    "分析一下",
    "分析下",
    "分析",
    "请研究一下",
    "请研究",
    "研究一下",
    "研究",
    "请介绍一下",
    "请介绍",
    "介绍一下",
    "介绍",
    "请查一下",
    "帮我查一下",
    "查一下",
    "关于",
    "请对",
    "对",
    "看看",
)

SECURITY_QUERY_LEADING_MODIFIERS = (
    "最近一段时间",
    "近一段时间",
    "这段时间",
    "近段时间",
    "近期",
    "最近",
    "最新",
    "近来",
    "当前",
    "目前",
    "现在",
    "今天",
    "这两天",
    "这几天",
    "短期",
    "中期",
    "短线",
    "中线",
    "相关",
)

SECURITY_TOPIC_MARKERS = (
    "技术面和公告",
    "技术面与公告",
    "走势和公告",
    "走势与公告",
    "现在什么情况",
    "最近什么情况",
    "什么情况",
    "为什么上涨",
    "为什么下跌",
    "为什么涨",
    "为什么跌",
    "为何上涨",
    "为何下跌",
    "为何涨",
    "为何跌",
    "是强是弱",
    "股价",
    "走势",
    "趋势",
    "技术面",
    "技术分析",
    "基本面",
    "业绩",
    "营收",
    "盈利",
    "估值",
    "财报",
    "公告",
    "新闻",
    "消息",
    "行情",
    "表现",
    "后市",
    "支撑",
    "压力",
    "异动",
    "涨停",
    "上涨",
    "下跌",
    "涨跌",
    "强弱",
    "量价",
)

SECURITY_QUERY_SUFFIXES = (
    "的近期股价走势",
    "近期股价走势",
    "的相关走势",
    "相关走势",
    "的近期走势",
    "近期走势",
    "的走势分析",
    "走势分析",
    "的股价走势",
    "股价走势",
    "的走势",
    "走势",
    "的短期趋势",
    "短期趋势",
    "的趋势",
    "趋势",
    "的技术分析",
    "技术分析",
    "的技术面分析",
    "技术面分析",
    "的技术面",
    "技术面",
    "的基本面",
    "基本面",
    "的财报",
    "财报",
    "的公告",
    "公告",
    "的消息",
    "消息",
    "近期风险",
    "主要风险",
    "的风险",
    "风险",
    "最近表现如何",
    "近期表现如何",
    "股价表现",
    "市场表现",
    "的表现",
    "表现",
    "的行情",
    "行情",
    "的后市",
    "后市",
    "后面怎么看",
    "接下来怎么看",
    "怎么看",
    "走得怎么样",
    "走得",
    "现在什么情况",
    "最近什么情况",
    "什么情况",
    "是强是弱",
    "强不强",
    "为什么上涨",
    "为什么下跌",
    "为什么涨",
    "为什么跌",
    "为何上涨",
    "为何下跌",
    "为何涨",
    "为何跌",
    "涨停原因",
    "下跌原因",
    "异动原因",
    "异动",
    "是强是弱",
    "有没有什么",
    "有啥",
    "咋回事",
    "为何突然",
    "值得关注吗",
    "值不值得关注",
    "值得关注",
    "值得注意吗",
    "值得注意",
    "发布了哪些",
    "发布了什么",
    "有哪些",
    "有什么",
    "是什么",
    "怎么回事",
    "有机会吗",
    "有没有机会",
    "能不能买",
    "能买吗",
    "可以买吗",
    "值得买吗",
    "咋样",
    "做一个",
    "做一下",
    "这家公司",
    "这个公司",
    "这只股票",
    "这只票",
    "这票",
    "个股",
    "股票",
    "相关",
    "近期",
    "最近",
    "最新",
    "近来",
    "当前",
    "目前",
    "现在",
    "今天",
    "这两天",
    "这几天",
    "短期",
    "中期",
    "短线",
    "中线",
    "怎么样",
    "如何",
    "呢",
    "呀",
    "啊",
    "吧",
    "吗",
)

SECURITY_QUERY_STOPWORDS = {
    "你好",
    "您好",
    "谢谢",
    "继续",
    "纯技术面版",
    "技术面公告事件版",
    "适合汇报投研纪要的简版",
    "老师",
    "同学",
    "老师你好",
    "继续分析",
    "再详细一点",
    "注明数据日期",
    "数据日期",
    "均线结构",
    "量能变化",
    "趋势判断和",
    "趋势判断",
    "主要风险",
    "这个",
}

NON_SECURITY_QUERY_PREFIXES = (
    "注明",
    "数据日期",
    "均线",
    "量能",
    "趋势判断",
    "主要风险",
    "风险提示",
    "详细",
    "继续分析",
    "这个",
)


def infer_target(prompt: str) -> Target | None:
    # Prefer the newest user turn, but inherit a previously named security when
    # the latest turn is a short follow-up such as "1" or "继续分析公告".
    # Assistant messages are deliberately excluded so model text cannot silently
    # replace the user's chosen security.
    turns = user_turn_texts(prompt)
    if not turns:
        return None
    latest = turns[-1]
    current = explicit_target_from_text(latest)
    if current:
        return current
    # A new company name or even a mistyped six-digit code is an explicit
    # switch signal. Do not silently inherit the previous security in that case;
    # the provider must resolve and validate the latest name/code combination.
    if parse_security_reference(latest).explicit:
        return None
    for text in reversed(turns[:-1]):
        inherited = explicit_target_from_text(text)
        if inherited:
            return inherited
    return None


def explicit_target_from_text(text: str) -> Target | None:
    lower = str(text or "").lower()
    for alias, target in ALIASES.items():
        if alias.lower() in lower:
            return target
    code_match = A_SHARE_CODE_RE.search(text or "")
    if not code_match:
        return None
    code = code_match.group(1)
    for item in DEFAULT_A_SHARE_UNIVERSE:
        if item.symbol == code:
            return item
    return Target("CNStock", code, confidence=78)


def infer_intent(prompt: str) -> str:
    turns = user_turn_texts(prompt)
    latest = turns[-1] if turns else (prompt or "")
    choice_intent = followup_choice_intent(latest)
    if choice_intent:
        return choice_intent
    explicit = explicit_intent(latest, allow_greeting=True)
    if explicit:
        return explicit
    for previous in reversed(turns[:-1]):
        inherited = explicit_intent(previous, allow_greeting=False)
        if inherited:
            return inherited
    return "full_research"


def explicit_intent(text: str, *, allow_greeting: bool) -> str | None:
    value = (text or "").lower()
    if allow_greeting and is_greeting_prompt(value):
        return "greeting"
    if any(word in value for word in ("选股", "筛选", "股票池", "候选", "排行", "排名", "screen")):
        return "screening"
    if any(word in value for word in ("回测", "策略", "因子", "收益", "回撤", "胜率", "backtest")):
        return "backtest"
    fundamental_terms = (
        "财报", "年报", "季报", "利润", "现金流", "roe", "pe", "pb", "基本面",
        "业绩", "营收", "盈利", "毛利", "负债", "估值", "经营情况", "经营表现",
    )
    announcement_terms = (
        "公告", "新闻", "消息", "政策", "归因", "为什么", "为何", "异动", "催化", "事件", "事件驱动",
        "咋回事",
    )
    technical_terms = (
        "走势", "k线", "均线", "rsi", "macd", "趋势", "技术", "股价", "行情", "表现",
        "涨跌", "强弱", "后市", "短线", "中线", "支撑", "压力", "量价", "怎么看", "咋样",
        "什么情况", "走得怎么样",
    )
    topic_hits = sum((
        any(word in value for word in fundamental_terms),
        any(word in value for word in announcement_terms),
        any(word in value for word in technical_terms),
    ))
    if topic_hits >= 2 or any(word in value for word in ("综合分析", "全面分析", "综合研究")):
        return "full_research"
    if any(word in value for word in fundamental_terms):
        return "fundamental"
    if any(word in value for word in announcement_terms):
        return "announcement"
    if any(word in value for word in technical_terms):
        return "technical"
    return None


def followup_choice_intent(text: str) -> str | None:
    value = re.sub(r"[*_`#]", "", text or "").strip().lower()
    if re.match(r"^(?:选\s*)?1(?:\s|[.、，,:：)）]|$)", value) or value.startswith(("第一种", "第一个")):
        return "technical"
    if re.match(r"^(?:选\s*)?2(?:\s|[.、，,:：)）]|$)", value) or value.startswith(("第二种", "第二个")):
        return "full_research"
    if re.match(r"^(?:选\s*)?3(?:\s|[.、，,:：)）]|$)", value) or value.startswith(("第三种", "第三个")):
        return "full_research"
    return None


def user_turn_texts(prompt: str) -> list[str]:
    """Extract user turns from the flattened OpenAI message history."""
    value = (prompt or "").strip()
    role_matches = list(re.finditer(
        r"(?:^|\n)(system|user|assistant|tool):\s*",
        value,
        flags=re.IGNORECASE,
    ))
    if not role_matches:
        return [value] if value else []
    turns: list[str] = []
    for index, match in enumerate(role_matches):
        if match.group(1).lower() != "user":
            continue
        end = role_matches[index + 1].start() if index + 1 < len(role_matches) else len(value)
        content = value[match.end():end].strip()
        if content:
            turns.append(content)
    return turns


def latest_user_text(prompt: str) -> str:
    """Return the latest user turn from the flattened OpenAI message history."""
    turns = user_turn_texts(prompt)
    return turns[-1] if turns else (prompt or "").strip()


def effective_user_text(prompt: str) -> str:
    """Expand numeric follow-up choices without consulting assistant messages."""
    latest = latest_user_text(prompt)
    cleaned = re.sub(r"[*_`#]", "", latest).strip().lower()
    if re.match(r"^(?:选\s*)?1(?:\s|[.、，,:：)）]|$)", cleaned) or cleaned.startswith(("第一种", "第一个")):
        return latest + "；纯技术面版"
    if re.match(r"^(?:选\s*)?2(?:\s|[.、，,:：)）]|$)", cleaned) or cleaned.startswith(("第二种", "第二个")):
        return latest + "；技术面 + 公告事件版"
    if re.match(r"^(?:选\s*)?3(?:\s|[.、，,:：)）]|$)", cleaned) or cleaned.startswith(("第三种", "第三个")):
        return latest + "；综合研究投研纪要简版"
    return latest


def parse_security_reference(text: str) -> SecurityReference:
    """Extract an explicit security switch from one user turn."""
    value = str(text or "").strip()
    raw_codes = tuple(dict.fromkeys(ANY_SIX_DIGIT_CODE_RE.findall(value)))
    valid_codes = tuple(code for code in raw_codes if is_a_share_code(code))
    names: list[str] = []
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,40}", value):
        candidate = normalize_security_candidate(chunk)
        if is_probable_security_name(candidate) and candidate not in names:
            names.append(candidate)
    return SecurityReference(raw_codes, valid_codes, tuple(names))


def target_resolution_notes(question: str, target: Target | None) -> list[str]:
    """Describe deterministic code correction/conflict outcomes to the user."""
    reference = parse_security_reference(question)
    if not reference.raw_codes:
        return []
    invalid_codes = [code for code in reference.raw_codes if code not in reference.valid_codes]
    if invalid_codes and target:
        return [
            f"输入代码 {invalid_codes[0]} 不是有效的公开 A 股代码；"
            f"已按公司名称核验为{target.name or target.symbol}（{target.symbol}）。"
        ]
    if invalid_codes and not target:
        return [
            f"输入代码 {invalid_codes[0]} 不是有效的公开 A 股代码，"
            "且当前公司名称未完成证券身份核验；本次未沿用历史证券数据。"
        ]
    if reference.valid_codes and target and target.symbol not in reference.valid_codes:
        return [
            "当前输入中的公司名称与证券代码未核验为同一证券；"
            "为避免分析错标的，本次不继承上一轮股票。"
        ]
    if reference.valid_codes and not target and reference.name_queries:
        return [
            "当前输入中的公司名称与证券代码可能不一致；"
            "为避免分析错标的，本次未沿用历史证券数据。"
        ]
    return []


def is_greeting_prompt(prompt: str) -> bool:
    value = re.sub(r"[\s，。！？!?、,.]+", "", latest_user_text(prompt)).lower()
    if value in GREETING_EXACT:
        return True
    return any(phrase in value for phrase in GREETING_PHRASES) and not any(
        term in value for term in ("股票", "代码", "走势", "财报", "公告", "回测", "选股")
    )


def security_search_queries(prompt: str, target: Target | None = None) -> list[str]:
    """Build conservative CNINFO lookup terms from a natural-language request."""
    queries: list[str] = []
    turns = user_turn_texts(prompt)
    latest = turns[-1] if turns else str(prompt or "")
    latest_reference = parse_security_reference(latest)
    if latest_reference.explicit:
        queries.extend(latest_reference.valid_codes)
        queries.extend(latest_reference.name_queries)
        return list(dict.fromkeys(query.strip() for query in queries if query.strip()))

    if target:
        if target.symbol:
            queries.append(target.symbol)
        if target.name:
            queries.append(target.name)

    for text in reversed(turns):
        if followup_choice_intent(text):
            continue
        code_match = A_SHARE_CODE_RE.search(text)
        if code_match:
            queries.append(code_match.group(1))

        for chunk in re.findall(r"[\u4e00-\u9fff]{2,40}", text):
            candidate = normalize_security_candidate(chunk)
            if 2 <= len(candidate) <= 16 and candidate not in SECURITY_QUERY_STOPWORDS:
                queries.append(candidate)

    deduplicated: list[str] = []
    for query in queries:
        value = query.strip()
        if value and value not in deduplicated:
            deduplicated.append(value)
    return deduplicated


def is_probable_security_name(value: str) -> bool:
    candidate = str(value or "").strip()
    if not 2 <= len(candidate) <= 16 or candidate in SECURITY_QUERY_STOPWORDS:
        return False
    if candidate.startswith(NON_SECURITY_QUERY_PREFIXES):
        return False
    if candidate in SECURITY_TOPIC_MARKERS or candidate in SECURITY_QUERY_SUFFIXES:
        return False
    return True


def normalize_security_candidate(value: str) -> str:
    """Remove natural-language wrappers around a possible Chinese security name."""
    candidate = str(value or "").strip()
    changed = True
    while candidate and changed:
        changed = False
        for prefix in SECURITY_QUERY_PREFIXES:
            if candidate.startswith(prefix):
                candidate = candidate[len(prefix):]
                changed = True
                break
        for modifier in SECURITY_QUERY_LEADING_MODIFIERS:
            if candidate.startswith(modifier):
                candidate = candidate[len(modifier):]
                changed = True
                break
        for suffix in SECURITY_QUERY_SUFFIXES:
            if candidate.endswith(suffix):
                candidate = candidate[:-len(suffix)]
                changed = True
                break
        stripped = candidate.strip("的")
        if stripped != candidate:
            candidate = stripped
            changed = True
        marker_positions = [
            candidate.find(marker) for marker in SECURITY_TOPIC_MARKERS
            if candidate.find(marker) >= 2
        ]
        if marker_positions:
            candidate = candidate[:min(marker_positions)].rstrip("的")
            changed = True
    return candidate.strip()


def is_a_share_code(value: str) -> bool:
    return bool(re.fullmatch(A_SHARE_CODE_RE.pattern, str(value or "")))
