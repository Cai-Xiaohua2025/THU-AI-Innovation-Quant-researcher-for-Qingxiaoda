from __future__ import annotations

import json
import os
import time

from qingyan_agent.infrastructure.cache import CACHE_SCHEMA_VERSION, FileCacheStore
from qingyan_agent.infrastructure.http import ResilientHttpClient, TRANSIENT_STATUS_CODES, safe_request_target


def test_file_cache_store_writes_atomically_and_reads_without_internal_schema(tmp_path):
    store = FileCacheStore(tmp_path)

    assert store.write("quote.json", {"symbol": "600000", "price": 10.0}) is True
    assert store.read("quote.json") == {"symbol": "600000", "price": 10.0}
    raw = json.loads((tmp_path / "quote.json").read_text(encoding="utf-8"))
    assert raw["_cache_schema_version"] == CACHE_SCHEMA_VERSION
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


def test_file_cache_store_rejects_corrupt_json_and_reads_legacy_cache(tmp_path):
    store = FileCacheStore(tmp_path)
    (tmp_path / "corrupt.json").write_text("{not-json", encoding="utf-8")
    (tmp_path / "legacy.json").write_text('{"symbol":"600000"}', encoding="utf-8")

    assert store.read("corrupt.json") is None
    assert store.read("legacy.json") == {"symbol": "600000"}


def test_file_cache_store_honors_ttl(tmp_path):
    store = FileCacheStore(tmp_path)
    store.write("expired.json", {"value": 1})
    old = time.time() - 120
    os.utime(tmp_path / "expired.json", (old, old))

    assert store.read("expired.json", max_age_sec=60) is None
    assert store.read("expired.json") == {"value": 1}


def test_http_client_reuses_session_and_configures_bounded_transient_retries():
    client = ResilientHttpClient(retries=2)
    first = client._session()
    second = client._session()
    retry = first.get_adapter("https://").max_retries

    assert first is second
    assert retry.total == 2
    assert set(TRANSIENT_STATUS_CODES).issubset(set(retry.status_forcelist))
    assert 400 not in retry.status_forcelist


def test_safe_request_target_drops_credentials_query_and_fragment():
    target = safe_request_target("https://user:secret@example.com:8443/path?q=token#fragment")

    assert target == "https://example.com:8443/path"
    assert "secret" not in target
    assert "token" not in target
