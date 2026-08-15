from dataclasses import replace
from pathlib import Path

from qingyan_agent.app import create_app
from qingyan_agent.config import PROJECT_ROOT, Settings, project_path


def make_settings(tmp_path):
    return Settings(
        report_dir=tmp_path / "reports",
        cache_dir=tmp_path / "cache",
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
    assert response.get_json()["openai_compatible"] is True


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
    settings = Settings(report_dir=tmp_path / "reports", cache_dir=tmp_path / "cache", api_token="secret")
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


def test_generated_attachments_are_downloadable(tmp_path):
    app = create_app(make_settings(tmp_path))
    client = app.test_client()
    response = client.post("/v1/chat/completions", json={
        "model": "qingyan-liangce-agent",
        "messages": [{"role": "user", "content": "请说明你的研究能力"}],
    })
    assert response.status_code == 200
    attachments = response.get_json()["x_soda"]["attachments"]
    assert attachments
    for attachment in attachments:
        file_response = client.get(attachment["fileUrl"])
        assert file_response.status_code == 200
        assert len(file_response.data) == attachment["fileSize"]


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
    assert health["upstream_llm_model"] == "example-model"

    response = client.post("/v1/chat/completions", json={
        "model": "qingyan-liangce-agent",
        "messages": [{"role": "user", "content": "请说明你的研究能力"}],
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
        "messages": [{"role": "user", "content": "请说明你的研究能力"}],
    })
    assert response.status_code == 200
    content = response.get_json()["choices"][0]["message"]["content"]
    assert "暂未识别到明确 A 股标的" in content
    assert "合规提示" in content
