#!/usr/bin/env python3
"""Portable command-line entry point for the Qingyan A-share research Skill."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import mimetypes
import os
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
VENDOR_DIR = SCRIPT_DIR / "vendor"
sys.path.insert(0, str(VENDOR_DIR))

MAX_LOCAL_FILE_BYTES = 25 * 1024 * 1024
MAX_LOCAL_IMAGE_BYTES = 10 * 1024 * 1024
SUPPORTED_FILES = {".pdf", ".docx", ".xlsx", ".xls", ".txt", ".md", ".csv", ".json"}
SUPPORTED_IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


class UsageError(ValueError):
    """An actionable input or dependency error."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run compliant, auditable A-share research and emit UTF-8 JSON.",
    )
    parser.add_argument("--question", help="Original natural-language research question.")
    parser.add_argument("--file", action="append", default=[], help="Local research attachment; repeatable.")
    parser.add_argument("--image", action="append", default=[], help="Local market image; repeatable.")
    parser.add_argument("--output-dir", default="qingyan-output", help="Directory for Markdown/PDF/PNG artifacts.")
    parser.add_argument("--fee-bps", type=float, default=0.0, help="Backtest one-way fee in basis points.")
    parser.add_argument("--slippage-bps", type=float, default=0.0, help="Backtest one-way slippage in basis points.")
    parser.add_argument("--risk-free-rate", type=float, default=0.0, help="Annualized risk-free rate as a decimal.")
    parser.add_argument("--timeout", type=int, default=12, help="External data-source timeout in seconds.")
    parser.add_argument("--self-test", action="store_true", help="Run deterministic checks without network access.")
    parser.add_argument("--version", action="version", version="qingyan-a-share-research 1.0.0")
    return parser


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default))


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


def require_runtime() -> None:
    try:
        import requests  # noqa: F401
    except ImportError as exc:
        raise UsageError(
            f"缺少最小依赖 requests；请执行: python3 -m pip install -r {SKILL_ROOT / 'requirements-minimal.txt'}"
        ) from exc


def validate_args(args: argparse.Namespace) -> None:
    if not args.self_test and not str(args.question or "").strip() and not args.image:
        raise UsageError("正常研究必须提供 --question；只有图片时也建议说明分析范围。")
    if not 0 <= args.fee_bps <= 500:
        raise UsageError("--fee-bps 必须在 0 到 500 之间。")
    if not 0 <= args.slippage_bps <= 500:
        raise UsageError("--slippage-bps 必须在 0 到 500 之间。")
    if not -0.1 <= args.risk_free_rate <= 0.3:
        raise UsageError("--risk-free-rate 必须在 -0.1 到 0.3 之间。")
    if not 1 <= args.timeout <= 120:
        raise UsageError("--timeout 必须在 1 到 120 秒之间。")
    if len(args.file) + len(args.image) > 10:
        raise UsageError("单次最多接收 10 个本地附件和图片。")


def safe_local_path(raw: str, suffixes: set[str], limit: int, kind: str) -> Path:
    path = Path(raw).expanduser().resolve()
    if not path.is_file() or path.is_symlink():
        raise UsageError(f"{kind}不是可读取的普通文件: {raw}")
    if path.suffix.lower() not in suffixes:
        raise UsageError(f"不支持的{kind}格式: {path.suffix or '无扩展名'}")
    size = path.stat().st_size
    if size > limit:
        raise UsageError(f"{kind}超过大小上限 {limit} bytes: {path.name}")
    return path


def read_local_files(raw_paths: list[str]) -> list[Any]:
    from qingyan_agent.file_reader import FileSummary, extract_text

    results = []
    for raw in raw_paths:
        path = safe_local_path(raw, SUPPORTED_FILES, MAX_LOCAL_FILE_BYTES, "附件")
        content = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        results.append(FileSummary(
            filename=path.name,
            status="ok",
            mime_type=mime,
            text=extract_text(content, path.name, mime),
            source_url=path.as_uri(),
        ))
    return results


def read_local_images(raw_paths: list[str]) -> list[Any]:
    from qingyan_agent.file_reader import ImageSummary, inspect_image

    results = []
    for raw in raw_paths:
        path = safe_local_path(raw, SUPPORTED_IMAGES, MAX_LOCAL_IMAGE_BYTES, "图片")
        content = path.read_bytes()
        try:
            mime, width, height = inspect_image(content)
        except ValueError as exc:
            raise UsageError(f"无效图片 {path.name}: {exc}") from exc
        results.append(ImageSummary(
            filename=path.name,
            status="ok",
            mime_type=mime,
            source_url=path.as_uri(),
            data_url=f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}",
            width=width,
            height=height,
        ))
    return results


def safe_output_dir(raw: str) -> Path:
    path = Path(raw).expanduser().resolve()
    if path.exists() and not path.is_dir():
        raise UsageError(f"--output-dir 不是目录: {path}")
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise UsageError("--output-dir 不能是符号链接。")
    return path


def configure_environment(output_dir: Path, args: argparse.Namespace) -> None:
    runtime_dir = output_dir / ".runtime"
    os.environ["QINGYAN_REPORT_DIR"] = str(output_dir)
    os.environ["QINGYAN_CACHE_DIR"] = str(runtime_dir / "cache")
    os.environ["QINGYAN_CONVERSATION_DIR"] = str(runtime_dir / "conversations")
    os.environ["QINGYAN_ARTIFACT_INDEX_PATH"] = str(runtime_dir / "artifacts" / "index.json")
    os.environ["QINGYAN_SAVE_CONVERSATIONS"] = "false"
    os.environ["QINGYAN_TRUSTED_PROXY_COUNT"] = "0"
    os.environ["QINGYAN_BACKTEST_FEE_BPS"] = str(args.fee_bps)
    os.environ["QINGYAN_BACKTEST_SLIPPAGE_BPS"] = str(args.slippage_bps)
    os.environ["QINGYAN_BACKTEST_RISK_FREE_RATE"] = str(args.risk_free_rate)
    os.environ["QINGYAN_REQUEST_TIMEOUT_SEC"] = str(args.timeout)


def build_agent(settings: Any) -> Any:
    from qingyan_agent.backtest import BacktestService
    from qingyan_agent.data_sources import AShareDataClient
    from qingyan_agent.llm_client import UpstreamLLMClient
    from qingyan_agent.research_agent import ResearchAgent
    from qingyan_agent.screening import StockScreener

    if importlib.util.find_spec("matplotlib") is not None:
        from qingyan_agent.reporting import ChartService
        chart_service: Any = ChartService(settings)
    else:
        chart_service = NoopChartService()

    data_client = AShareDataClient(settings)
    return ResearchAgent(
        data_client,
        StockScreener(data_client),
        BacktestService(settings),
        chart_service,
        UpstreamLLMClient(settings),
    )


class NoopChartService:
    """Keep the minimal dependency path quiet and explicitly chart-free."""

    def price_chart(self, *args: Any, **kwargs: Any) -> None:
        return None

    def screening_chart(self, *args: Any, **kwargs: Any) -> None:
        return None

    def backtest_chart(self, *args: Any, **kwargs: Any) -> None:
        return None


def write_artifacts(output: Any, chart_paths: list[Path], settings: Any) -> list[dict[str, Any]]:
    """Always write Markdown; add charts and PDF only when actually available."""
    from qingyan_agent.reporting import safe_name, write_pdf

    title_stem = safe_name(output.title) or "qingyan_research_report"
    fingerprint = hashlib.sha256(output.report_markdown.encode("utf-8")).hexdigest()[:10]
    markdown_path = settings.report_dir / f"{title_stem}_{fingerprint}.md"
    markdown_path.write_text(output.report_markdown, encoding="utf-8")

    artifact_paths: list[tuple[Path, str, str]] = [(markdown_path, "text", "text/markdown")]
    for chart_path in chart_paths:
        if chart_path.is_file():
            artifact_paths.append((chart_path.resolve(), "image", "image/png"))

    pdf_path = settings.report_dir / f"{title_stem}_{fingerprint}.pdf"
    if importlib.util.find_spec("reportlab") is not None:
        try:
            if write_pdf(pdf_path, output.report_markdown, chart_paths) and pdf_path.is_file():
                artifact_paths.insert(0, (pdf_path, "pdf", "application/pdf"))
        except Exception:
            pass

    seen = set()
    artifacts = []
    for path, file_type, mime_type in artifact_paths:
        resolved = path.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        artifacts.append({
            "path": str(resolved),
            "filename": resolved.name,
            "file_type": file_type,
            "mime_type": mime_type,
            "size": resolved.stat().st_size,
            "sha256": sha256_file(resolved),
        })
    return artifacts


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def research(args: argparse.Namespace) -> dict[str, Any]:
    require_runtime()
    output_dir = safe_output_dir(args.output_dir)
    configure_environment(output_dir, args)

    # Import config only after task-specific paths are set; Settings fields are
    # evaluated at module import time in the experimental core.
    from qingyan_agent.config import load_settings

    settings = load_settings()
    files = read_local_files(args.file)
    images = read_local_images(args.image)
    agent = build_agent(settings)
    output, charts = agent.run(str(args.question or ""), files, images)
    artifacts = write_artifacts(output, charts, settings) if output.report_enabled else []
    context = output.context
    return {
        "ok": True,
        "mode": "research",
        "skill": "qingyan-a-share-research",
        "title": output.title,
        "answer": output.answer,
        "artifacts": artifacts,
        "evidence_completeness": context.evidence_completeness if context else {},
        "missing_evidence": context.missing_evidence if context else [],
        "warnings": context.warnings if context else [],
        "data_statuses": context.data_statuses if context else [],
        "model_metadata": context.model_metadata if context else {},
    }


def synthetic_klines(count: int = 96) -> list[dict[str, Any]]:
    """Create deterministic oscillating prices that exercise indicators/crosses."""
    rows = []
    price = 100.0
    for index in range(count):
        segment = (index // 12) % 4
        delta = (0.7, -0.5, 0.9, -0.8)[segment]
        price = max(20.0, price + delta + ((index % 5) - 2) * 0.04)
        rows.append({
            "date": f"2025-{index // 28 + 1:02d}-{index % 28 + 1:02d}",
            "open": round(price - 0.2, 2),
            "close": round(price, 2),
            "high": round(price + 0.8, 2),
            "low": round(price - 0.9, 2),
            "volume": 1_000_000 + index * 7_000,
            "source": "self-test",
            "price_adjustment": "前复权",
        })
    return rows


def self_test() -> dict[str, Any]:
    require_runtime()
    checks: list[dict[str, Any]] = []

    def check(name: str, condition: bool, detail: str) -> None:
        if not condition:
            raise AssertionError(f"{name}: {detail}")
        checks.append({"name": name, "ok": True, "detail": detail})

    from qingyan_agent.backtest import local_ma_cross_backtest
    from qingyan_agent.compliance import guard_output
    from qingyan_agent.domain.indicators import technical_indicators
    from qingyan_agent.universe import infer_intent, infer_target

    rows = synthetic_klines()
    indicators = technical_indicators(rows)
    check("technical_indicators", indicators.get("sample_size") == len(rows), "96 rows processed")
    check("technical_metrics", indicators.get("rsi14") is not None, "RSI14 calculated")

    result = local_ma_cross_backtest(rows, fee_bps=3, slippage_bps=2)
    check("backtest", result.metrics.get("status") == "ok", "MA10/MA30 simulation completed")
    check("backtest_audit", "signal_assumption" in result.metrics, "look-ahead assumption disclosed")
    check(
        "backtest_period",
        bool(result.metrics.get("sample_start_date") and result.metrics.get("simulation_start_date")),
        "raw sample and post-warmup simulation dates disclosed",
    )

    prompt = "请对宁德时代300750做技术面与公告综合研究"
    target = infer_target(prompt)
    check("target_inference", bool(target and target.symbol == "300750"), "resolved 300750")
    check("intent_inference", infer_intent(prompt) == "full_research", "combined topic recognized")

    guarded = guard_output("我们可以代客理财，而且保证收益。")
    answer_body = guarded.partition("合规提示：")[0]
    check(
        "compliance_guard",
        "代客理财" not in answer_body and "保证收益" not in answer_body and "合规提示：" in guarded,
        "prohibited service/guarantee rewritten and notice appended",
    )

    return {
        "ok": True,
        "mode": "self-test",
        "skill": "qingyan-a-share-research",
        "version": "1.0.0",
        "network_used": False,
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        validate_args(args)
        payload = self_test() if args.self_test else research(args)
        emit(payload)
        return 0
    except UsageError as exc:
        print(f"qingyan skill input error: {exc}", file=sys.stderr)
        emit({"ok": False, "error_type": "usage_error", "error": str(exc)})
        return 2
    except KeyboardInterrupt:
        print("qingyan skill interrupted", file=sys.stderr)
        emit({"ok": False, "error_type": "interrupted", "error": "运行被中断。"})
        return 130
    except Exception as exc:
        message = f"{exc.__class__.__name__}: {str(exc)[:300]}"
        print(f"qingyan skill runtime error: {message}", file=sys.stderr)
        emit({"ok": False, "error_type": "runtime_error", "error": message})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
