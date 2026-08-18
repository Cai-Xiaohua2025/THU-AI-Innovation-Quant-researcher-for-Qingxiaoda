"""Shared HTTP client with per-thread sessions and bounded retries."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


TRANSIENT_STATUS_CODES = (429, 502, 503, 504)
LOGGER = logging.getLogger(__name__)


class ResilientHttpClient:
    def __init__(self, *, user_agent: str = "Qingyan-Liangce-Agent/0.3", retries: int = 2) -> None:
        self.user_agent = user_agent
        self.retries = max(0, retries)
        self._local = threading.local()

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("User-Agent", self.user_agent)
        safe_target = safe_request_target(url)
        started_at = time.perf_counter()
        try:
            response = self._session().request(method, url, headers=headers, **kwargs)
            LOGGER.debug(
                "HTTP %s %s status=%s latency_ms=%.1f",
                method.upper(),
                safe_target,
                response.status_code,
                (time.perf_counter() - started_at) * 1000,
            )
            return response
        except requests.RequestException as exc:
            LOGGER.warning(
                "HTTP %s %s failed error=%s latency_ms=%.1f",
                method.upper(),
                safe_target,
                exc.__class__.__name__,
                (time.perf_counter() - started_at) * 1000,
            )
            raise

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is not None:
            return session
        retry = Retry(
            total=self.retries,
            connect=self.retries,
            read=self.retries,
            status=self.retries,
            backoff_factor=0.25,
            status_forcelist=TRANSIENT_STATUS_CODES,
            allowed_methods=frozenset({"GET", "HEAD", "OPTIONS", "POST"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=16)
        session = requests.Session()
        session.trust_env = False
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        self._local.session = session
        return session


def safe_request_target(url: str) -> str:
    """Return scheme/host/path only, deliberately dropping credentials and query data."""
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return f"{parsed.scheme}://{host}{parsed.path}"
