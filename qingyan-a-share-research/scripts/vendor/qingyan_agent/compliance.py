"""Financial compliance guardrails."""

from __future__ import annotations

import re


RISK_NOTICE_ZH = (
    "合规提示：以上内容仅基于公开信息、用户授权上传材料和历史数据进行研究辅助，"
    "不构成投资建议、收益承诺、代客理财或自动交易指令。市场有风险，投资决策应由用户独立判断并自行承担风险。"
)

RISK_NOTICE_EN = (
    "Compliance note: This output is research assistance based on public information, "
    "user-authorized materials, and historical data only. It is not investment advice, "
    "a return guarantee, asset management, or an automated trading instruction."
)

UNSAFE_PATTERNS = (
    r"必须买入",
    r"必须卖出",
    r"稳赚",
    r"保本",
    r"保证收益",
    r"代客理财",
    r"自动下单",
    r"\bmust\s+(buy|sell|long|short)\b",
    r"\bguaranteed?\s+(profit|return)\b",
)


def normalize_question(text: str) -> str:
    value = text or ""
    replacements = {
        "荐股": "生成候选研究清单",
        "推荐股票": "筛选研究对象并说明研究依据",
        "买入建议": "研究观察结论",
        "卖出建议": "风险复盘结论",
        "该不该买": "从研究角度分析机会、风险和待验证事项",
        "能不能买": "从研究角度分析机会、风险和待验证事项",
        "必须买入": "进行买入条件与失效条件的情景研究",
        "必须卖出": "进行卖出条件与失效条件的情景研究",
        "保证收益": "评估潜在收益、损失与不确定性",
        "稳赚": "评估潜在收益、损失与不确定性",
        "保本": "评估下行风险与资本损失可能性",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    return value


def guard_output(text: str, *, language: str = "zh") -> str:
    guarded = text or ""
    notice = RISK_NOTICE_ZH if language.startswith("zh") else RISK_NOTICE_EN
    marker = "合规提示：" if language.startswith("zh") else "Compliance note:"
    # A previous pass may already contain the notice. Keep the notice outside
    # unsafe-pattern rewriting so its own phrases (for example 代客理财) are
    # not corrupted and a second notice is never appended.
    if marker in guarded:
        guarded = guarded.partition(marker)[0].rstrip()
    # Remove model-authored disclaimer sentences before rewriting unsafe
    # affirmative language. Otherwise a valid negation such as
    # "不构成……代客理财" is corrupted by the `代客理财` replacement below.
    if language.startswith("zh"):
        guarded = re.sub(
            r"(?:^|\n)[>\-\s]*[^\n。！？]*不构成投资建议[^\n。！？]*[。！？]?",
            "",
            guarded,
            flags=re.IGNORECASE,
        ).strip()
    for pattern in UNSAFE_PATTERNS:
        guarded = re.sub(
            pattern,
            lambda match: match.group(0) if is_negated_context(guarded, match.start()) else "仅作为研究线索",
            guarded,
            flags=re.IGNORECASE,
        )
    return guarded.rstrip() + "\n\n" + notice


def is_negated_context(text: str, start: int) -> bool:
    """Keep prohibited phrases intact when they are explicitly being denied."""
    prefix = text[max(0, start - 24):start]
    return bool(re.search(r"(?:不|非|无|未|不会|不能|不得|禁止|避免)[^。！？\n]{0,12}$", prefix))
