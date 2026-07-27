from pathlib import Path

from qingyan_agent.app import create_app
from qingyan_agent.config import Settings


def make_settings(tmp_path):
    return Settings(report_dir=tmp_path / "reports", cache_dir=tmp_path / "cache", request_timeout_sec=1)


def test_health(tmp_path):
    app = create_app(make_settings(tmp_path))
    client = app.test_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json()["openai_compatible"] is True


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
