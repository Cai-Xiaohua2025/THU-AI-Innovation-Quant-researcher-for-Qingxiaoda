"""Runtime settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # Minimal Skill runtime: environment variables still work.
    def load_dotenv(*args, **kwargs):
        return False


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(minimum, min(maximum, parsed))


def env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return max(minimum, min(maximum, parsed))


def project_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("QINGYAN_HOST", "0.0.0.0")
    port: int = env_int("QINGYAN_PORT", 8787, minimum=1, maximum=65535)
    debug: bool = env_bool("QINGYAN_DEBUG")
    api_token: str = os.getenv("QINGYAN_API_TOKEN", "").strip()
    public_base_url: str = os.getenv("QINGYAN_PUBLIC_BASE_URL", "").rstrip("/")
    report_dir: Path = project_path(os.getenv("QINGYAN_REPORT_DIR", "outputs/reports"))
    cache_dir: Path = project_path(os.getenv("QINGYAN_CACHE_DIR", "outputs/cache"))
    conversation_dir: Path = project_path(os.getenv("QINGYAN_CONVERSATION_DIR", "outputs/conversations"))
    artifact_index_path: Path | None = (
        project_path(os.environ["QINGYAN_ARTIFACT_INDEX_PATH"])
        if os.getenv("QINGYAN_ARTIFACT_INDEX_PATH") else None
    )
    max_request_bytes: int = env_int("QINGYAN_MAX_REQUEST_BYTES", 2 * 1024 * 1024, minimum=1024, maximum=20 * 1024 * 1024)
    max_download_bytes: int = env_int("QINGYAN_MAX_DOWNLOAD_BYTES", 25 * 1024 * 1024, minimum=1024, maximum=100 * 1024 * 1024)
    max_image_bytes: int = env_int("QINGYAN_MAX_IMAGE_BYTES", 10 * 1024 * 1024, minimum=1024, maximum=25 * 1024 * 1024)
    max_files_per_request: int = env_int("QINGYAN_MAX_FILES_PER_REQUEST", 5, minimum=1, maximum=20)
    request_timeout_sec: int = env_int("QINGYAN_REQUEST_TIMEOUT_SEC", 12, minimum=1, maximum=120)
    data_collection_workers: int = env_int("QINGYAN_DATA_COLLECTION_WORKERS", 4, minimum=1, maximum=8)
    announcement_lookback_days: int = env_int("QINGYAN_ANNOUNCEMENT_LOOKBACK_DAYS", 180, minimum=1, maximum=3650)
    announcement_attachment_max_files: int = env_int("QINGYAN_ANNOUNCEMENT_ATTACHMENT_MAX_FILES", 3, minimum=0, maximum=8)
    announcement_attachment_max_bytes: int = env_int("QINGYAN_ANNOUNCEMENT_ATTACHMENT_MAX_BYTES", 8 * 1024 * 1024, minimum=64 * 1024, maximum=50 * 1024 * 1024)
    announcement_attachment_max_pages: int = env_int("QINGYAN_ANNOUNCEMENT_ATTACHMENT_MAX_PAGES", 20, minimum=1, maximum=100)
    announcement_attachment_max_chars: int = env_int("QINGYAN_ANNOUNCEMENT_ATTACHMENT_MAX_CHARS", 9000, minimum=1000, maximum=50000)
    backtest_gateway_url: str = os.getenv("QINGYAN_BACKTEST_GATEWAY_URL", "").rstrip("/")
    backtest_gateway_token: str = os.getenv("QINGYAN_BACKTEST_GATEWAY_TOKEN", "").strip()
    backtest_fee_bps: float = env_float("QINGYAN_BACKTEST_FEE_BPS", 0.0, minimum=0.0, maximum=500.0)
    backtest_slippage_bps: float = env_float("QINGYAN_BACKTEST_SLIPPAGE_BPS", 0.0, minimum=0.0, maximum=500.0)
    backtest_risk_free_rate: float = env_float("QINGYAN_BACKTEST_RISK_FREE_RATE", 0.0, minimum=-0.1, maximum=0.3)
    llm_base_url: str = os.getenv("QINGYAN_LLM_BASE_URL", "").strip().rstrip("/")
    llm_api_key: str = os.getenv("QINGYAN_LLM_API_KEY", "").strip()
    llm_model: str = os.getenv("QINGYAN_LLM_MODEL", "").strip()
    llm_timeout_sec: int = env_int("QINGYAN_LLM_TIMEOUT_SEC", 90, minimum=5, maximum=600)
    llm_max_tokens: int = env_int("QINGYAN_LLM_MAX_TOKENS", 3600, minimum=128, maximum=16000)
    llm_max_input_chars: int = env_int("QINGYAN_LLM_MAX_INPUT_CHARS", 60000, minimum=4000, maximum=500000)
    llm_temperature: float = env_float("QINGYAN_LLM_TEMPERATURE", 0.2, minimum=0.0, maximum=2.0)
    enable_akshare: bool = env_bool("QINGYAN_ENABLE_AKSHARE")
    allow_private_file_urls: bool = env_bool("QINGYAN_ALLOW_PRIVATE_FILE_URLS")
    require_file_auth: bool = env_bool("QINGYAN_REQUIRE_FILE_AUTH")
    sign_artifact_urls: bool = env_bool("QINGYAN_SIGN_ARTIFACT_URLS")
    artifact_signing_key: str = os.getenv("QINGYAN_ARTIFACT_SIGNING_KEY", "").strip()
    artifact_url_ttl_sec: int = env_int("QINGYAN_ARTIFACT_URL_TTL_SEC", 3600, minimum=60, maximum=604800)
    trusted_proxy_count: int = env_int("QINGYAN_TRUSTED_PROXY_COUNT", 0, minimum=0, maximum=10)
    cors_origins: str = os.getenv("QINGYAN_CORS_ORIGINS", "*").strip() or "*"
    save_conversations: bool = env_bool("QINGYAN_SAVE_CONVERSATIONS", True)
    conversation_max_chars: int = env_int("QINGYAN_CONVERSATION_MAX_CHARS", 200000, minimum=1000, maximum=2_000_000)
    cache_retention_days: int = env_int("QINGYAN_CACHE_RETENTION_DAYS", 0, minimum=0, maximum=3650)
    report_retention_days: int = env_int("QINGYAN_REPORT_RETENTION_DAYS", 0, minimum=0, maximum=3650)
    conversation_retention_days: int = env_int("QINGYAN_CONVERSATION_RETENTION_DAYS", 0, minimum=0, maximum=3650)
    live_trading_enabled: bool = False

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_model)


def load_settings() -> Settings:
    settings = Settings()
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    if settings.save_conversations:
        settings.conversation_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            settings.conversation_dir.chmod(0o700)
        except OSError:
            pass
    return settings
