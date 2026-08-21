"""Deterministic, evidence-bound announcement event analysis."""

from __future__ import annotations

import re
from typing import Any

from .contracts import AnnouncementAnalysis, AnnouncementRecord


def analyze_announcements(
    announcements: list[AnnouncementRecord] | list[dict[str, Any]],
    *,
    limit: int = 6,
) -> list[AnnouncementAnalysis]:
    analyses = [analyze_announcement(item) for item in announcements]
    analyses.sort(key=lambda item: item.get("importance_score", 0), reverse=True)
    return analyses[:limit]


def analyze_announcement(item: dict[str, Any]) -> AnnouncementAnalysis:
    title = compact(str(item.get("title") or "未命名公告"), 160)
    date = str(item.get("date") or "日期待核验")
    attachment = item.get("attachment") if isinstance(item.get("attachment"), dict) else {}
    text = str(attachment.get("text") or "")
    facts = [f"公司于 {date} 披露《{title}》。"]
    inferences: list[str] = []
    impacts: list[str] = []
    risks: list[str] = []
    verification: list[str] = []

    if any(term in title for term in ("辞职", "离任")):
        if "因工作调整" in text:
            facts.append("公告正文说明本次离任原因为工作调整。")
        if "改任" in text or "继续在" in text:
            facts.append("公告正文显示相关人员离任后仍可能在公司体系内任职，具体职务以原文为准。")
        if "未持有" in text:
            facts.append("公告正文说明相关人员在披露时未持有公司股票。")
        inferences.append("从已提取正文看，本事项更接近管理岗位调整，尚无证据表明其直接改变公司控制权或核心经营。")
        impacts.append("短期影响主要集中在治理安排和后续继任情况，而非已确认的财务变化。")
        risks.append("若后续出现更多核心管理人员调整，应重新评估治理连续性。")
        verification.append("继续核对继任人选、职责交接及后续董事会公告。")
    elif any(term in title for term in ("权益分派", "利润分配", "现金红利", "分红")):
        per_share = first_match(text, r"(?:A\s*股)?每股(?:派发)?现金红利\s*([0-9.]+)\s*元")
        annual = first_match(text, r"全年现金红利为每股\s*([0-9.]+)\s*元")
        if per_share:
            facts.append(f"公告正文披露本次现金红利为每股 {per_share} 元（税务口径以原文为准）。")
        if annual and annual != per_share:
            facts.append(f"公告正文披露对应年度全年现金红利合计为每股 {annual} 元。")
        inferences.append("现金分红反映股东回报安排，但不能单独证明盈利质量或未来分红水平。")
        impacts.append("除息会带来价格机械调整，除息日前后的价格变化不应全部解释为基本面变化。")
        risks.append("高分红能否持续仍取决于经营现金流、负债、资本开支和未来盈利。")
        verification.append("结合年度报告核对自由现金流、分红支付率和资本开支计划。")
    elif any(term in title for term in ("可交换公司债", "可交换债", "补充担保", "信托登记")):
        shares = first_match(text, r"将\s*([0-9,]+)\s*股")
        facts.append("公告涉及控股股东可交换债项下的担保或信托登记安排。")
        if shares:
            facts.append(f"已提取正文提到补充登记股份数量为 {shares} 股，最终以公告原文为准。")
        inferences.append("补充担保或信托登记不等同于控股股东已经减持，也不等同于债券已经完成换股。")
        impacts.append("市场可能关注未来换股带来的股份供给预期，但实际影响取决于换股价格、剩余规模和持有人行为。")
        risks.append("若后续进入大规模换股阶段，可能形成阶段性的流通股份供给和预期扰动。")
        verification.append("继续核对可交换债剩余规模、换股价格、换股期限和实际换股公告。")
    elif "发电量" in title:
        facts.append("公告披露公司阶段性发电量完成情况，具体同比和分区域数据需以正文表格为准。")
        inferences.append("发电量是水电企业经营的重要数量指标，但收入和利润还受电价、市场化交易及成本等因素影响。")
        impacts.append("发电量变化可作为阶段经营趋势线索，不能直接等同于利润同比变化。")
        risks.append("来水、水库调度、电力消纳和电价变化都可能使发电量与利润表现出现偏离。")
        verification.append("核对发电量同比、主要电站分项数据、电价和后续定期报告。")
    elif "董事会" in title or "股东会" in title:
        facts.append("该公告属于公司治理或会议决议披露，具体议案需读取正文后逐项判断。")
        inferences.append("仅凭会议决议标题不能判断其对盈利、估值或股价的方向性影响。")
        risks.append("若正文包含重大投资、融资、关联交易或人事变动，应单独评估。")
        verification.append("读取并核对会议审议议案、表决结果及相关专项公告。")
    else:
        inferences.append("当前只能确认公告标题和日期，不对未提取或未明确披露的金额、业绩影响作推断。")
        risks.append("标题可能不足以覆盖公告中的条件、例外和风险提示。")
        verification.append("以公告正文和交易所后续问询或补充公告继续核验。")

    source_status = str(attachment.get("status") or "title_only")
    if source_status != "ok":
        verification.append("当前公告正文未成功提取，以上分析仅使用标题级事实。")
    elif attachment.get("truncated"):
        verification.append("正文提取受页数或字符上限影响，未覆盖部分需查阅原文。")

    return {
        "title": title,
        "date": date,
        "source_url": str(item.get("url") or ""),
        "facts": deduplicate(facts),
        "inferences": deduplicate(inferences),
        "potential_impacts": deduplicate(impacts),
        "risks": deduplicate(risks),
        "verification_items": deduplicate(verification),
        "source_pages": source_pages(text),
        "source_status": source_status,
        "importance_score": importance_score(title),
    }


def importance_score(title: str) -> int:
    score = 0
    weighted = (
        (35, ("业绩", "年报", "季报", "利润", "分红", "权益分派")),
        (30, ("可交换债", "担保", "信托", "重大合同", "诉讼", "处罚")),
        (25, ("发电量", "经营数据", "资产重组", "收购", "投资")),
        (15, ("辞职", "离任", "董事会", "股东会")),
    )
    for weight, terms in weighted:
        if any(term in title for term in terms):
            score = max(score, weight)
    return score


def source_pages(text: str) -> list[int]:
    return list(dict.fromkeys(int(value) for value in re.findall(r"\[第(\d+)页\]", text)))


def first_match(text: str, pattern: str) -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def compact(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
