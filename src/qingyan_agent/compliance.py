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
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    return value


def guard_output(text: str, *, language: str = "zh") -> str:
    guarded = text or ""
    for pattern in UNSAFE_PATTERNS:
        guarded = re.sub(pattern, "仅作为研究线索", guarded, flags=re.IGNORECASE)
    notice = RISK_NOTICE_ZH if language.startswith("zh") else RISK_NOTICE_EN
    if notice not in guarded:
        guarded = guarded.rstrip() + "\n\n" + notice
    return guarded
