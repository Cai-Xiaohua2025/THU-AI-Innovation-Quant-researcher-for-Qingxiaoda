from __future__ import annotations

import json
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

from qingyan_agent.app import create_app
from qingyan_agent.artifacts import ArtifactRegistry
from qingyan_agent.config import Settings


def settings_for(tmp_path, **changes):
    settings = Settings(
        report_dir=tmp_path / "reports",
        cache_dir=tmp_path / "cache",
        conversation_dir=tmp_path / "conversations",
        artifact_index_path=tmp_path / "artifacts" / "index.json",
        api_token="",
        public_base_url="",
        llm_base_url="",
        llm_api_key="",
        llm_model="",
    )
    return replace(settings, **changes)


def test_artifact_registry_writes_atomic_metadata_index_without_absolute_path(tmp_path):
    settings = settings_for(tmp_path)
    settings.report_dir.mkdir(parents=True)
    path = settings.report_dir / "report.md"
    path.write_text("research", encoding="utf-8")
    registry = ArtifactRegistry(settings)

    record = registry.register(path, "text", "text/markdown")
    attachment = registry.attachment(record, "https://research.example.com")
    index = json.loads(settings.artifact_index_path.read_text(encoding="utf-8"))

    assert index["schema_version"] == 1
    assert index["artifacts"][record["artifact_id"]]["filename"] == "report.md"
    assert str(settings.report_dir) not in settings.artifact_index_path.read_text(encoding="utf-8")
    assert attachment["artifactId"] == record["artifact_id"]
    assert attachment["fileUrl"].endswith("/files/report.md")
    assert len(attachment["sha256"]) == 64


def test_signed_artifact_url_validates_signature_and_expiry(tmp_path, monkeypatch):
    settings = settings_for(
        tmp_path,
        sign_artifact_urls=True,
        artifact_signing_key="test-signing-key",
        artifact_url_ttl_sec=120,
    )
    settings.report_dir.mkdir(parents=True)
    path = settings.report_dir / "report.pdf"
    path.write_bytes(b"%PDF-test")
    registry = ArtifactRegistry(settings)
    record = registry.register(path, "pdf", "application/pdf")
    attachment = registry.attachment(record, "https://research.example.com")
    query = parse_qs(urlsplit(attachment["fileUrl"]).query)

    resolved, status = registry.resolve(
        record["artifact_id"],
        query["expires"][0],
        query["signature"][0],
    )
    assert status == "ok" and resolved == record
    assert registry.resolve(record["artifact_id"], query["expires"][0], "bad")[1] == "invalid_signature"

    monkeypatch.setattr("qingyan_agent.artifacts.time.time", lambda: int(query["expires"][0]) + 1)
    assert registry.resolve(
        record["artifact_id"], query["expires"][0], query["signature"][0],
    )[1] == "expired"


def test_app_can_serve_signed_artifact_url_without_exposing_filename(tmp_path):
    settings = settings_for(
        tmp_path,
        sign_artifact_urls=True,
        artifact_signing_key="test-signing-key",
    )
    client = create_app(settings).test_client()
    response = client.post("/v1/chat/completions", json={
        "model": "qingyan-liangce-agent",
        "messages": [{"role": "user", "content": "分析宁德时代 300750 的走势"}],
    })
    attachment = response.get_json()["x_soda"]["attachments"][0]

    assert response.status_code == 200
    assert "/artifacts/" in attachment["fileUrl"]
    assert attachment["fileName"] not in attachment["fileUrl"]
    assert client.get(attachment["fileUrl"]).status_code == 200
    tampered = attachment["fileUrl"].replace("signature=", "signature=x")
    assert client.get(tampered).status_code == 403
