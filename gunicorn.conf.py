"""Gunicorn production settings for Qingyan Agent."""

from __future__ import annotations

import os


bind = os.getenv("QINGYAN_GUNICORN_BIND", "127.0.0.1:18787")
workers = int(os.getenv("QINGYAN_GUNICORN_WORKERS", "2"))
threads = int(os.getenv("QINGYAN_GUNICORN_THREADS", "4"))
worker_class = "gthread"
timeout = int(os.getenv("QINGYAN_GUNICORN_TIMEOUT", "180"))
graceful_timeout = 30
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
preload_app = True
accesslog = "-"
errorlog = "-"
capture_output = True

