from __future__ import annotations

from qingyan_agent.announcement_analysis import analyze_announcement, analyze_announcements


def test_dividend_announcement_separates_facts_inference_and_risk():
    analysis = analyze_announcement({
        "title": "长江电力2025年年度权益分派实施公告",
        "date": "2026-07-10",
        "url": "https://static.cninfo.com.cn/example.pdf",
        "attachment": {
            "status": "ok",
            "text": "[第1页]\nA 股每股现金红利0.79元（含税）\n[第2页]\n2025 年全年现金红利为每股1.00元",
        },
    })

    assert any("0.79" in fact for fact in analysis["facts"])
    assert any("1.00" in fact for fact in analysis["facts"])
    assert any("除息" in impact for impact in analysis["potential_impacts"])
    assert any("持续" in risk for risk in analysis["risks"])
    assert analysis["source_pages"] == [1, 2]
    assert analysis["source_url"] == "https://static.cninfo.com.cn/example.pdf"


def test_exchangeable_bond_analysis_does_not_call_registration_a_sale():
    analysis = analyze_announcement({
        "title": "关于可交换公司债券办理补充担保及信托登记的公告",
        "date": "2026-07-18",
        "attachment": {
            "status": "ok",
            "text": "[第1页]\n将 21,531,000 股办理补充担保及信托登记。",
        },
    })

    assert any("21,531,000" in fact for fact in analysis["facts"])
    assert any("不等同于控股股东已经减持" in inference for inference in analysis["inferences"])
    assert any("换股价格" in item for item in analysis["verification_items"])


def test_announcement_analysis_prioritizes_material_events_and_limits_count():
    rows = [
        {"title": "董事会会议决议公告", "date": "2026-08-01"},
        {"title": "年度权益分派实施公告", "date": "2026-08-02"},
        {"title": "总法律顾问辞职公告", "date": "2026-08-03"},
    ]

    analyses = analyze_announcements(rows, limit=2)

    assert len(analyses) == 2
    assert analyses[0]["title"] == "年度权益分派实施公告"
    assert analyses[0]["facts"]
    assert analyses[0]["verification_items"]
