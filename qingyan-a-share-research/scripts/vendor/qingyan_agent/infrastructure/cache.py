"""Atomic filesystem JSON cache with backwards-compatible reads."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any


CACHE_SCHEMA_VERSION = 1


class FileCacheStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path_for(self, key: str) -> Path:
        return self.directory / key

    def read(self, key: str, *, max_age_sec: int | None = None) -> Any:
        path = self.path_for(key)
        try:
            if not path.exists():
                return None
            if max_age_sec is not None and time.time() - path.stat().st_mtime > max_age_sec:
                return None
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                value.pop("_cache_schema_version", None)
            return value
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def write(self, key: str, value: Any) -> bool:
        temporary: Path | None = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            stored_value = dict(value) if isinstance(value, dict) else value
            if isinstance(stored_value, dict):
                stored_value.setdefault("_cache_schema_version", CACHE_SCHEMA_VERSION)
            path = self.path_for(key)
            temporary = self.directory / f".{path.name}.{uuid.uuid4().hex}.tmp"
            temporary.write_text(
                json.dumps(stored_value, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            os.replace(temporary, path)
            return True
        except (OSError, TypeError, ValueError):
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            return False

