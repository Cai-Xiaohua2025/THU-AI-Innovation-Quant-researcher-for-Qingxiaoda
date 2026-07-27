"""Flask/OpenAI-compatible app for Qingxiaoda."""

from __future__ import annotations

import hmac
from typing import Any

from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context

try:
    from flask_cors import CORS
except Exception:
    CORS = None

from .backtest import BacktestService
from .config import Settings, load_settings
from .data_sources import AShareDataClient
from .file_reader import FileReader
from .protocol import completion_response, parse_request, stream_response
from .reporting import ChartService, ReportService
from .research_agent import ResearchAgent
from .screening import StockScreener


def create_app(settings: Settings | None = None) -> Flask:
    cfg = settings or load_settings()
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False
    if CORS:
        CORS(app)

    data_client = AShareDataClient(cfg)
    screener = StockScreener(data_client)
    backtester = BacktestService(cfg)
    charts = ChartService(cfg)
    agent = ResearchAgent(data_client, screener, backtester, charts)
    reader = FileReader(cfg)

    @app.get("/health")
    def health() -> Any:
        return jsonify({
            "status": "ok",
            "service": "qingyan-liangce-agent",
            "openai_compatible": True,
            "qingxiaoda_attachments": True,
            "live_trading_enabled": cfg.live_trading_enabled,
        })

    @app.get("/v1/models")
    def models() -> Any:
        if not authorized(cfg):
            return unauthorized()
        return jsonify({
            "object": "list",
            "data": [{"id": "qingyan-liangce-agent", "object": "model", "owned_by": "qingyan-team"}],
        })

    @app.post("/v1/chat/completions")
    def chat_completions() -> Any:
        if not authorized(cfg):
            return unauthorized()
        payload = request.get_json(silent=True) or {}
        parsed = parse_request(payload)
        files = reader.read_all(parsed.files)
        output, chart_paths = agent.run(parsed.prompt, files)
        report = ReportService(cfg, request.url_root.rstrip("/")).create(output.title, output.report_markdown, chart_paths)
        if parsed.stream:
            return Response(
                stream_with_context(stream_response(parsed.model, output.answer, report.attachments)),
                mimetype="text/event-stream",
            )
        return jsonify(completion_response(parsed.model, output.answer, report.attachments))

    @app.post("/api/research/screen")
    def api_screen() -> Any:
        if not authorized(cfg):
            return unauthorized()
        result = screener.screen()
        return jsonify({"code": 0, "data": {"rows": result.rows, "statuses": [s.__dict__ for s in result.statuses]}})

    @app.get("/files/<path:filename>")
    def files(filename: str) -> Any:
        return send_from_directory(str(cfg.report_dir), filename, as_attachment=True)

    @app.errorhandler(Exception)
    def error_handler(exc: Exception) -> Any:
        return jsonify({"error": {"message": str(exc), "type": exc.__class__.__name__}}), 500

    return app


def authorized(settings: Settings) -> bool:
    if not settings.api_token:
        return True
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    return hmac.compare_digest(token, settings.api_token)


def unauthorized() -> tuple[Any, int]:
    return jsonify({"error": {"message": "Unauthorized", "type": "auth_error"}}), 401


def main() -> None:
    settings = load_settings()
    app = create_app(settings)
    app.run(host=settings.host, port=settings.port, debug=settings.debug, threaded=True)


if __name__ == "__main__":
    main()
