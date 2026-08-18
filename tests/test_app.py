from dataclasses import replace

from qingyan_agent.app import create_app
from qingyan_agent.config import PROJECT_ROOT, Settings, project_path


def make_settings(tmp_path):
    return Settings(
        report_dir=tmp_path / "reports",
        cache_dir=tmp_path / "cache",
        conversation_dir=tmp_path / "conversations",
        request_timeout_sec=1,
        api_token="",
        public_base_url="",
        llm_base_url="",
        llm_api_key="",
        llm_model="",
    )


def test_health(tmp_path):
    app = create_app(make_settings(tmp_path))
    client = app.test_client()
    response = client.get("/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["openai_compatible"] is True
    assert data["market_data_mode"] == "online_with_short_cache"
    assert data["supported_a_share_markets"] == ["SSE", "SZSE", "BSE"]
    assert data["streaming_mode"] == "progress_sse_buffered_content"
    assert data["research_progress_events"] is True
    assert data["upstream_token_passthrough"] is False
    assert data["file_auth_required"] is False
    assert data["artifact_signing_ready"] is True


def test_ready_rejects_enabled_artifact_signing_without_a_key(tmp_path):
    settings = replace(
        make_settings(tmp_path),
        sign_artifact_urls=True,
        artifact_signing_key="",
        api_token="",
    )
    response = create_app(settings).test_client().get("/ready")

    assert response.status_code == 503
    assert response.get_json()["checks"]["artifact_signing"] is False


def test_relative_runtime_paths_resolve_from_project_root():
    assert project_path("outputs/reports") == PROJECT_ROOT / "outputs" / "reports"


def test_chat_completion_single_stock(tmp_path):
    app = create_app(make_settings(tmp_path))
    client = app.test_client()
    response = client.post("/v1/chat/completions", json={
        "model": "qingyan-liangce-agent",
        "messages": [{"role": "user", "content": "请分析宁德时代 300750 的走势和风险"}],
    })
    assert response.status_code == 200
    data = response.get_json()
    assert "合规提示" in data["choices"][0]["message"]["content"]
    assert "市场快照与核心指标" in data["choices"][0]["message"]["content"]
    assert "关键价位与情景推演" in data["choices"][0]["message"]["content"]
    assert "数据质量与方法说明" in data["choices"][0]["message"]["content"]
    assert "## 接下来可以继续" in data["choices"][0]["message"]["content"]
    assert "宁德时代 300750" in data["choices"][0]["message"]["content"]
    assert "近期公告" in data["choices"][0]["message"]["content"]
    assert data["x_soda"]["attachments"]


def test_chat_completion_screening(tmp_path):
    app = create_app(make_settings(tmp_path))
    client = app.test_client()
    response = client.post("/v1/chat/completions", json={
        "model": "qingyan-liangce-agent",
        "messages": [{"role": "user", "content": "请做一个选股候选股票池"}],
    })
    assert response.status_code == 200
    assert "候选股票池" in response.get_json()["choices"][0]["message"]["content"]


def test_token_auth(tmp_path):
    settings = Settings(
        report_dir=tmp_path / "reports",
        cache_dir=tmp_path / "cache",
        conversation_dir=tmp_path / "conversations",
        api_token="secret",
    )
    app = create_app(settings)
    client = app.test_client()
    assert client.get("/v1/models").status_code == 401
    assert client.get("/v1/models", headers={"Authorization": "Bearer secret"}).status_code == 200


def test_connection_probe_streaming(tmp_path):
    app = create_app(make_settings(tmp_path))
    client = app.test_client()
    response = client.post("/v1/chat/completions", json={
        "model": "qingyan-liangce-agent",
        "stream": True,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "ping"}],
    })
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert response.content_type.startswith("text/event-stream")
    assert '"object": "chat.completion.chunk"' in body
    assert body.endswith("data: [DONE]\n\n")
    assert list((tmp_path / "conversations").glob("*/*.json")) == []


def test_generated_attachments_are_downloadable(tmp_path):
    app = create_app(make_settings(tmp_path))
    client = app.test_client()
    response = client.post("/v1/chat/completions", json={
        "model": "qingyan-liangce-agent",
        "messages": [{"role": "user", "content": "请分析宁德时代 300750 的走势和风险"}],
    })
    assert response.status_code == 200
    payload = response.get_json()
    attachments = payload["x_soda"]["attachments"]
    assert attachments
    answer = payload["choices"][0]["message"]["content"]
    pdf_attachment = next(item for item in attachments if item["mimeType"] == "application/pdf")
    assert "下载 PDF 研报" in answer
    assert pdf_attachment["fileUrl"] in answer
    for attachment in attachments:
        file_response = client.get(attachment["fileUrl"])
        assert file_response.status_code == 200
        assert len(file_response.data) == attachment["fileSize"]
        if attachment["fileType"] == "pdf":
            assert file_response.content_type == "application/pdf"
            assert "attachment" not in file_response.headers.get("Content-Disposition", "").lower()
            download_response = client.get(attachment["fileUrl"] + "?download=1")
            assert "attachment" in download_response.headers.get("Content-Disposition", "").lower()


def test_file_download_can_optionally_require_bearer_auth(tmp_path):
    settings = replace(
        make_settings(tmp_path),
        api_token="secret",
        require_file_auth=True,
    )
    client = create_app(settings).test_client()
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer secret"},
        json={
            "model": "qingyan-liangce-agent",
            "messages": [{"role": "user", "content": "请分析宁德时代 300750 的走势"}],
        },
    )
    attachment_url = response.get_json()["x_soda"]["attachments"][0]["fileUrl"]

    assert client.get(attachment_url).status_code == 401
    assert client.get(attachment_url, headers={"Authorization": "Bearer secret"}).status_code == 200



def test_greeting_explains_capabilities_without_report(tmp_path):
    app = create_app(make_settings(tmp_path))
    client = app.test_client()
    response = client.post("/v1/chat/completions", json={
        "model": "qingyan-liangce-agent",
        "messages": [{"role": "user", "content": "你好"}],
    })
    assert response.status_code == 200
    data = response.get_json()
    content = data["choices"][0]["message"]["content"]
    assert "单股走势研究" in content
    assert "公告与事件解读" in content
    assert "策略回测" in content
    assert "分析长江电力 600900" in content
    assert data["x_soda"]["attachments"] == []


def test_successful_chat_is_saved_to_local_conversation_folder(tmp_path):
    app = create_app(make_settings(tmp_path))
    response = app.test_client().post("/v1/chat/completions", json={
        "model": "qingyan-liangce-agent",
        "messages": [{"role": "user", "content": "你好"}],
    })
    assert response.status_code == 200
    stored = list((tmp_path / "conversations").glob("*/*.json"))
    assert len(stored) == 1
    import json
    record = json.loads(stored[0].read_text(encoding="utf-8"))
    assert record["request"]["prompt"] == "user: 你好"
    assert "单股走势研究" in record["response"]["content"]
    assert record["response"]["report_enabled"] is False


def test_successful_streaming_chat_is_saved_to_local_conversation_folder(tmp_path):
    app = create_app(make_settings(tmp_path))
    response = app.test_client().post("/v1/chat/completions", json={
        "model": "qingyan-liangce-agent",
        "stream": True,
        "messages": [{"role": "user", "content": "你好"}],
    })
    assert response.status_code == 200
    assert response.get_data(as_text=True).endswith("data: [DONE]\n\n")
    stored = list((tmp_path / "conversations").glob("*/*.json"))
    assert len(stored) == 1
    import json
    record = json.loads(stored[0].read_text(encoding="utf-8"))
    assert record["request"]["stream"] is True
    assert "单股走势研究" in record["response"]["content"]


def test_streaming_chat_establishes_sse_before_research_and_emits_progress(tmp_path):
    app = create_app(make_settings(tmp_path))
    response = app.test_client().post("/v1/chat/completions", buffered=False, json={
        "model": "qingyan-liangce-agent",
        "stream": True,
        "messages": [{"role": "user", "content": "你好"}],
    })
    iterator = iter(response.response)
    first = next(iterator).decode("utf-8")

    assert response.status_code == 200
    assert '"stage": "accepted"' in first
    assert list((tmp_path / "conversations").glob("*/*.json")) == []

    body = first + "".join(chunk.decode("utf-8") for chunk in iterator)
    assert '"stage": "reading_attachments"' in body
    assert '"stage": "researching"' in body
    assert '"stage": "completed"' in body
    assert body.endswith("data: [DONE]\n\n")
    assert len(list((tmp_path / "conversations").glob("*/*.json"))) == 1


def test_configured_upstream_llm_is_used(monkeypatch, tmp_path):
    class Response:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "## 研究结论摘要\n上游模型已参与综合。\n\n## 关键证据\n- 仅使用证据包。\n\n## 风险与待验证事项\n- 数据仍需核验。",
                    }
                }]
            }

    monkeypatch.setattr("qingyan_agent.llm_client.requests.post", lambda *args, **kwargs: Response())
    settings = replace(
        make_settings(tmp_path),
        llm_base_url="https://gateway.example.com/v1",
        llm_api_key="secret",
        llm_model="example-model",
    )
    app = create_app(settings)
    client = app.test_client()

    health = client.get("/health").get_json()
    assert health["upstream_llm_configured"] is True
    assert health["fundamentals_enabled"] is False
    assert health["fundamentals_provider"] == "disabled"
    assert health["upstream_llm_model"] == "example-model"

    response = client.post("/v1/chat/completions", json={
        "model": "qingyan-liangce-agent",
        "messages": [{"role": "user", "content": "请分析宁德时代 300750 的走势和风险"}],
    })
    assert response.status_code == 200
    content = response.get_json()["choices"][0]["message"]["content"]
    assert "上游模型已参与综合" in content
    assert "合规提示" in content


def test_upstream_llm_failure_keeps_deterministic_answer(monkeypatch, tmp_path):
    import requests

    def fail_post(*args, **kwargs):
        raise requests.Timeout("test timeout")

    monkeypatch.setattr("qingyan_agent.llm_client.requests.post", fail_post)
    settings = replace(
        make_settings(tmp_path),
        llm_base_url="https://gateway.example.com/v1",
        llm_model="example-model",
    )
    app = create_app(settings)
    client = app.test_client()
    response = client.post("/v1/chat/completions", json={
        "model": "qingyan-liangce-agent",
        "messages": [{"role": "user", "content": "请分析宁德时代 300750 的走势和风险"}],
    })
    assert response.status_code == 200
    content = response.get_json()["choices"][0]["message"]["content"]
    assert "研究对象：宁德时代" in content
    assert "合规提示" in content
