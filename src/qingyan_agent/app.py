"""Flask/OpenAI-compatible app for Qingxiaoda."""

from __future__ import annotations

import hmac
import logging
import os
import time
import uuid
from typing import Any

from flask import Flask, Response, g, jsonify, request, send_from_directory, stream_with_context
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

try:
    from flask_cors import CORS
except Exception:
    CORS = None

from .backtest import BacktestService
from .config import Settings, load_settings
from .conversation_store import ConversationStore
from .data_sources import AShareDataClient
from .file_reader import FileReader
from .llm_client import UpstreamLLMClient
from .protocol import completion_response, parse_request, stream_response, truncate_to_token_budget
from .reporting import ChartService, ReportService
from .research_agent import ResearchAgent
from .screening import StockScreener


LOGGER = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> Flask:
    cfg = settings or load_settings()
    app = Flask(__name__)
    app.json.ensure_ascii = False
    app.config["MAX_CONTENT_LENGTH"] = cfg.max_request_bytes
    if cfg.trusted_proxy_count:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=cfg.trusted_proxy_count,
            x_proto=cfg.trusted_proxy_count,
            x_host=cfg.trusted_proxy_count,
            x_port=cfg.trusted_proxy_count,
        )
    if CORS:
        origins = "*" if cfg.cors_origins == "*" else [item.strip() for item in cfg.cors_origins.split(",") if item.strip()]
        CORS(app, resources={r"/*": {"origins": origins}})

    data_client = AShareDataClient(cfg)
    screener = StockScreener(data_client)
    backtester = BacktestService(cfg)
    charts = ChartService(cfg)
    llm_client = UpstreamLLMClient(cfg)
    agent = ResearchAgent(data_client, screener, backtester, charts, llm_client)
    reader = FileReader(cfg)
    conversation_store = ConversationStore(cfg)

    @app.before_request
    def start_request() -> None:
        g.request_started_at = time.perf_counter()
        g.request_id = request.headers.get("X-Request-ID", "").strip()[:128] or uuid.uuid4().hex

    @app.after_request
    def finish_request(response: Response) -> Response:
        response.headers["X-Request-ID"] = getattr(g, "request_id", "")
        started_at = getattr(g, "request_started_at", None)
        if started_at is not None:
            response.headers["X-Process-Time-Ms"] = f"{(time.perf_counter() - started_at) * 1000:.1f}"
        return response

    @app.get("/")
    def index() -> Any:
        return jsonify({
            "service": "qingyan-liangce-agent",
            "model": "qingyan-liangce-agent",
            "openai_base_url": f"{request.url_root.rstrip('/')}/v1",
            "health": f"{request.url_root.rstrip('/')}/health",
        })

    @app.get("/health")
    def health() -> Any:
        return jsonify({
            "status": "ok",
            "service": "qingyan-liangce-agent",
            "openai_compatible": True,
            "qingxiaoda_attachments": True,
            "vision_image_url": True,
            "market_data_mode": "online_with_short_cache",
            "supported_a_share_markets": ["SSE", "SZSE", "BSE"],
            "market_quote_sources": ["tencent", "sina", "eastmoney"],
            "announcement_attachment_extraction": True,
            "announcement_attachment_max_files": cfg.announcement_attachment_max_files,
            "conversation_storage_enabled": cfg.save_conversations,
            "upstream_llm_configured": cfg.llm_configured,
            "upstream_llm_model": cfg.llm_model if cfg.llm_configured else "",
            "live_trading_enabled": cfg.live_trading_enabled,
        })

    @app.get("/ready")
    def ready() -> Any:
        checks = {
            "report_dir": directory_ready(cfg.report_dir),
            "cache_dir": directory_ready(cfg.cache_dir),
        }
        if cfg.save_conversations:
            checks["conversation_dir"] = conversation_store.ensure_ready()
        is_ready = all(checks.values())
        return jsonify({"status": "ready" if is_ready else "not_ready", "checks": checks}), 200 if is_ready else 503

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
        if not request.is_json:
            return api_error("Content-Type must be application/json", "invalid_request_error", 415)
        payload = request.get_json(silent=True)
        try:
            parsed = parse_request(payload)
        except ValueError as exc:
            return api_error(str(exc), "invalid_request_error", 400)

        # Qingxiaoda/OpenAI-compatible connection probes commonly use one token.
        # Keep the probe independent of external market-data availability.
        if parsed.max_tokens == 1:
            content = "好"
            if parsed.stream:
                response = Response(
                    stream_with_context(stream_response(parsed.model, parsed.prompt, content)),
                    mimetype="text/event-stream",
                )
                return configure_stream_response(response)
            return jsonify(completion_response(parsed.model, parsed.prompt, content))

        if len(parsed.files) + len(parsed.images) > cfg.max_files_per_request:
            return api_error(
                f"too many files or images; maximum is {cfg.max_files_per_request}",
                "invalid_request_error",
                400,
            )
        files = reader.read_all(parsed.files)
        images = reader.read_images(parsed.images)
        output, chart_paths = agent.run(parsed.prompt, files, images)
        attachments = output.attachments
        if output.report_enabled:
            report = ReportService(cfg, request.url_root.rstrip("/")).create(output.title, output.report_markdown, chart_paths)
            attachments = report.attachments
        answer = truncate_to_token_budget(output.answer, parsed.max_tokens)
        finish_reason = "length" if answer != output.answer else "stop"
        started_at = getattr(g, "request_started_at", None)
        processing_ms = (time.perf_counter() - started_at) * 1000 if started_at is not None else None
        stored_path = conversation_store.save(
            request_id=getattr(g, "request_id", uuid.uuid4().hex),
            parsed=parsed,
            response_text=answer,
            finish_reason=finish_reason,
            title=output.title,
            report_enabled=output.report_enabled,
            attachments=attachments,
            processing_ms=processing_ms,
        )
        if cfg.save_conversations and stored_path is None:
            LOGGER.warning(
                "Conversation persistence failed request_id=%s",
                getattr(g, "request_id", "unknown"),
            )
        if parsed.stream:
            response = Response(
                stream_with_context(stream_response(
                    parsed.model,
                    parsed.prompt,
                    answer,
                    attachments,
                    finish_reason,
                )),
                mimetype="text/event-stream",
            )
            return configure_stream_response(response)
        return jsonify(completion_response(
            parsed.model,
            parsed.prompt,
            answer,
            attachments,
            finish_reason,
        ))

    @app.post("/api/research/screen")
    def api_screen() -> Any:
        if not authorized(cfg):
            return unauthorized()
        result = screener.screen()
        return jsonify({"code": 0, "data": {"rows": result.rows, "statuses": [s.__dict__ for s in result.statuses]}})

    @app.get("/files/<path:filename>")
    def files(filename: str) -> Any:
        return send_from_directory(
            str(cfg.report_dir),
            filename,
            as_attachment=request.args.get("download") == "1",
        )

    @app.errorhandler(Exception)
    def error_handler(exc: Exception) -> Any:
        if isinstance(exc, HTTPException):
            return api_error(exc.description, "http_error", exc.code or 500)
        LOGGER.exception("Unhandled request error request_id=%s", getattr(g, "request_id", "unknown"))
        return api_error("Internal server error", "server_error", 500)

    return app


def authorized(settings: Settings) -> bool:
    if not settings.api_token:
        return True
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer":
        return False
    token = token.strip()
    return hmac.compare_digest(token, settings.api_token)


def unauthorized() -> tuple[Any, int]:
    response, status = api_error("Unauthorized", "authentication_error", 401)
    response.headers["WWW-Authenticate"] = "Bearer"
    return response, status


def api_error(message: str, error_type: str, status: int) -> tuple[Any, int]:
    return jsonify({
        "error": {
            "message": message,
            "type": error_type,
            "code": status,
            "request_id": getattr(g, "request_id", None),
        }
    }), status


def configure_stream_response(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Connection"] = "keep-alive"
    return response


def directory_ready(path: Any) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path.is_dir() and os.access(path, os.W_OK)
    except OSError:
        return False


def main() -> None:
    settings = load_settings()
    if not settings.api_token and settings.host not in {"127.0.0.1", "localhost", "::1"}:
        LOGGER.warning("QINGYAN_API_TOKEN is empty while the service listens on %s", settings.host)
    app = create_app(settings)
    app.run(host=settings.host, port=settings.port, debug=settings.debug, threaded=True)


if __name__ == "__main__":
    main()
