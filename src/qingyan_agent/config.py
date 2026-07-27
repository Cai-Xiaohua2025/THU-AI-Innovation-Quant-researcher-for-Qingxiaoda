"""Runtime settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("QINGYAN_HOST", "0.0.0.0")
    port: int = int(os.getenv("QINGYAN_PORT", "8787"))
    debug: bool = os.getenv("QINGYAN_DEBUG", "false").lower() in {"1", "true", "yes", "on"}
    api_token: str = os.getenv("QINGYAN_API_TOKEN", "").strip()
    public_base_url: str = os.getenv("QINGYAN_PUBLIC_BASE_URL", "").rstrip("/")
    report_dir: Path = Path(os.getenv("QINGYAN_REPORT_DIR", str(PROJECT_ROOT / "outputs" / "reports")))
    cache_dir: Path = Path(os.getenv("QINGYAN_CACHE_DIR", str(PROJECT_ROOT / "outputs" / "cache")))
    max_download_bytes: int = int(os.getenv("QINGYAN_MAX_DOWNLOAD_BYTES", str(25 * 1024 * 1024)))
    request_timeout_sec: int = int(os.getenv("QINGYAN_REQUEST_TIMEOUT_SEC", "12"))
    announcement_lookback_days: int = int(os.getenv("QINGYAN_ANNOUNCEMENT_LOOKBACK_DAYS", "180"))
    backtest_gateway_url: str = os.getenv("QINGYAN_BACKTEST_GATEWAY_URL", "").rstrip("/")
    backtest_gateway_token: str = os.getenv("QINGYAN_BACKTEST_GATEWAY_TOKEN", "").strip()
    enable_akshare: bool = os.getenv("QINGYAN_ENABLE_AKSHARE", "false").lower() in {"1", "true", "yes", "on"}
    live_trading_enabled: bool = False


def load_settings() -> Settings:
    settings = Settings()
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    return settings
