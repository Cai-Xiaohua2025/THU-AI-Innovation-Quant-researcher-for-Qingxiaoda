"""Research report composition independent from orchestration and I/O."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from .contracts import EvidenceBundle


def compose_report(
    title: str,
    question: str,
    payload: EvidenceBundle | dict[str, Any],
    file_notes: list[dict[str, str]],
    answer: str,
) -> str:
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S")
    technical = payload.get("technical") if isinstance(payload.get("technical"), dict) else {}
    quote = payload.get("quote") if isinstance(payload.get("quote"), dict) else {}
    data_date = technical.get("data_date") or market_date_from_quote(quote) or "待核验"
    metadata = {
        "title": title,
        "generated_at": generated_at,
        "report_standard": "QY-A-SHARE-RESEARCH-2.0",
        "file_count": len(file_notes),
        "payload": sanitize_report_metadata(payload),
    }
    return "\n".join([
        f"# {title}",
        "",
        "> 清研量策·A股研究助手 · 公开信息正式研究版",
        "",
        "| 报告信息 | 内容 |",
        "| --- | --- |",
        f"| 报告生成时间 | {generated_at} |",
        f"| 核心数据截止 | {data_date} |",
        f"| 价格口径 | {technical.get('price_adjustment') or '待核验'} |",
        f"| 行情 / K线来源 | {quote.get('source') or '待核验'} / {technical.get('source') or '待核验'} |",
        "| 报告标准 | QY-A-SHARE-RESEARCH-2.0；事实、计算指标、模型标签、分析推断分层表达 |",
        "",
        "## 用户问题",
        report_display_question(question),
        "",
        "## 结构化元数据",
        "```json",
        json.dumps(metadata, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        answer,
    ])


def market_date_from_quote(quote: dict[str, Any]) -> str:
    value = str((quote or {}).get("market_time") or "")
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) < 8:
        return ""
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"


def report_display_question(question: str) -> str:
    value = str(question or "").strip()
    user_turns = re.findall(r"(?:^|\n)user:\s*([^\n]+)", value, flags=re.IGNORECASE)
    return user_turns[-1].strip() if user_turns else value


def sanitize_report_metadata(value: Any) -> Any:
    """Keep report metadata auditable without duplicating extracted source bodies."""
    if isinstance(value, list):
        return [sanitize_report_metadata(item) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key == "text" and isinstance(item, str):
            result.setdefault("text_available", bool(item.strip()))
            result.setdefault("text_chars", len(item))
            continue
        result[key] = sanitize_report_metadata(item)
    return result
