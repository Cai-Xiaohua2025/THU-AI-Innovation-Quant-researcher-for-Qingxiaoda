"""Artifact metadata index and optional HMAC-signed download URLs."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote, urlencode

from .config import Settings


LOGGER = logging.getLogger(__name__)
SCHEMA_VERSION = 1


class ArtifactRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.index_path = settings.artifact_index_path or settings.report_dir.parent / "artifacts" / "index.json"

    def register(self, path: Path, file_type: str, mime_type: str) -> dict[str, Any]:
        report_root = self.settings.report_dir.resolve()
        resolved = path.resolve()
        if resolved.parent != report_root or path.is_symlink():
            raise ValueError("artifact must be a regular file directly inside report_dir")
        stat = resolved.stat()
        created_unix = int(time.time())
        expires_unix = created_unix + self.settings.artifact_url_ttl_sec
        record = {
            "artifact_id": uuid.uuid4().hex,
            "filename": resolved.name,
            "file_type": file_type,
            "mime_type": mime_type,
            "file_size": stat.st_size,
            "sha256": sha256_file(resolved),
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "created_unix": created_unix,
            "expires_unix": expires_unix,
            "schema_version": SCHEMA_VERSION,
        }
        with self._index_lock():
            index = self._read_index_unlocked()
            index["artifacts"][record["artifact_id"]] = record
            self._write_index_unlocked(index)
        return record

    def attachment(self, record: dict[str, Any], base_url: str) -> dict[str, Any]:
        artifact_id = str(record["artifact_id"])
        if self.settings.sign_artifact_urls:
            expires = int(record["expires_unix"])
            signature = self.signature(artifact_id, expires)
            query = urlencode({"expires": expires, "signature": signature})
            file_url = f"{base_url}/artifacts/{artifact_id}?{query}"
        else:
            file_url = f"{base_url}/files/{quote(str(record['filename']))}"
        return {
            "fileUrl": file_url,
            "fileName": record["filename"],
            "fileType": record["file_type"],
            "mimeType": record["mime_type"],
            "fileSize": record["file_size"],
            "artifactId": artifact_id,
            "createdAt": record["created_at"],
            "expiresAt": datetime.fromtimestamp(
                int(record["expires_unix"]),
            ).astimezone().isoformat(timespec="seconds"),
            "sha256": record["sha256"],
        }

    def resolve(
        self,
        artifact_id: str,
        expires: str = "",
        signature: str = "",
    ) -> tuple[dict[str, Any] | None, str]:
        record = self.get(artifact_id)
        if not record:
            return None, "not_found"
        if self.settings.sign_artifact_urls:
            try:
                expires_unix = int(expires)
            except (TypeError, ValueError):
                return None, "invalid_signature"
            if expires_unix != int(record.get("expires_unix") or 0):
                return None, "invalid_signature"
            if expires_unix < int(time.time()):
                return None, "expired"
            expected = self.signature(artifact_id, expires_unix)
            if not signature or not hmac.compare_digest(signature, expected):
                return None, "invalid_signature"
        filename = str(record.get("filename") or "")
        path = self.settings.report_dir / filename
        try:
            if not filename or path.is_symlink() or path.resolve().parent != self.settings.report_dir.resolve():
                return None, "not_found"
            if not path.is_file():
                return None, "not_found"
        except OSError:
            return None, "not_found"
        return record, "ok"

    def get(self, artifact_id: str) -> dict[str, Any] | None:
        if not artifact_id or len(artifact_id) > 128:
            return None
        index = self._read_index()
        record = index.get("artifacts", {}).get(artifact_id)
        return record if isinstance(record, dict) else None

    def prune_missing(self) -> int:
        """Drop index rows whose report files no longer exist; never delete files."""
        with self._index_lock():
            index = self._read_index_unlocked()
            artifacts = index.get("artifacts", {})
            retained = {}
            for artifact_id, record in artifacts.items():
                if not isinstance(record, dict):
                    continue
                filename = str(record.get("filename") or "")
                path = self.settings.report_dir / filename
                try:
                    valid = (
                        bool(filename)
                        and not path.is_symlink()
                        and path.resolve().parent == self.settings.report_dir.resolve()
                        and path.is_file()
                    )
                except OSError:
                    valid = False
                if valid:
                    retained[artifact_id] = record
            removed = len(artifacts) - len(retained)
            if removed:
                index["artifacts"] = retained
                self._write_index_unlocked(index)
            return removed

    def signature(self, artifact_id: str, expires: int) -> str:
        key = self.settings.artifact_signing_key or self.settings.api_token
        if not key:
            raise ValueError("artifact signing requires QINGYAN_ARTIFACT_SIGNING_KEY or QINGYAN_API_TOKEN")
        message = f"{artifact_id}:{expires}".encode("utf-8")
        return hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()

    def _read_index(self) -> dict[str, Any]:
        try:
            return self._read_index_unlocked()
        except Exception:
            return {"schema_version": SCHEMA_VERSION, "artifacts": {}}

    def _read_index_unlocked(self) -> dict[str, Any]:
        if not self.index_path.exists():
            return {"schema_version": SCHEMA_VERSION, "artifacts": {}}
        try:
            value = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            LOGGER.warning("Artifact index is unreadable; preserving file and starting an empty in-memory view")
            return {"schema_version": SCHEMA_VERSION, "artifacts": {}}
        if value.get("schema_version") != SCHEMA_VERSION or not isinstance(value.get("artifacts"), dict):
            return {"schema_version": SCHEMA_VERSION, "artifacts": {}}
        return value

    def _write_index_unlocked(self, value: dict[str, Any]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.index_path.parent / f".{self.index_path.name}.{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.index_path)
            os.chmod(self.index_path, 0o600)
        finally:
            if temporary.exists():
                temporary.unlink()

    @contextmanager
    def _index_lock(self) -> Iterator[None]:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.index_path.with_suffix(self.index_path.suffix + ".lock")
        with lock_path.open("a+b") as handle:
            try:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            try:
                yield
            finally:
                try:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except (ImportError, OSError):
                    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
