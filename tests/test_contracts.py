from __future__ import annotations

from qingyan_agent.contracts import DataErrorKind, ResearchContext, ResearchStepStatus
from qingyan_agent.models import DataStatus


def test_research_context_tracks_auditable_step_lifecycle():
    context = ResearchContext(question="分析长江电力", intent="technical")
    step = context.add_step("collect_evidence", "收集结构化证据")
    step.start()
    step.complete("quote", "technical")
    context.complete()

    metadata = context.public_metadata()
    assert metadata["request_id"]
    assert metadata["completed_at"]
    assert metadata["steps"][0]["status"] == ResearchStepStatus.COMPLETED
    assert metadata["steps"][0]["evidence_keys"] == ["quote", "technical"]


def test_data_status_has_a_structured_optional_error_kind():
    status = DataStatus(
        "market_quote",
        False,
        "all providers unavailable",
        DataErrorKind.UPSTREAM_UNAVAILABLE,
    )

    assert status.error_kind == "upstream_unavailable"
