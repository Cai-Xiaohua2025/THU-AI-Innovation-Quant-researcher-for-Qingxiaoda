from __future__ import annotations

import os
import time

from qingyan_agent.config import Settings
from qingyan_agent.retention import RetentionManager


def make_settings(tmp_path, **changes):
    values = {
        "report_dir": tmp_path / "reports",
        "cache_dir": tmp_path / "cache",
        "conversation_dir": tmp_path / "conversations",
        "artifact_index_path": tmp_path / "artifacts" / "index.json",
        "api_token": "",
        "llm_base_url": "",
        "llm_api_key": "",
        "llm_model": "",
    }
    values.update(changes)
    return Settings(**values)


def make_old(path, now):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("generated", encoding="utf-8")
    os.utime(path, (now - 10 * 86400, now - 10 * 86400))


def test_retention_is_disabled_by_default_and_removes_nothing(tmp_path):
    settings = make_settings(tmp_path)
    old = settings.cache_dir / "old.json"
    make_old(old, time.time())

    result = RetentionManager(settings).apply()

    assert old.exists()
    assert result.removed_count == 0


def test_retention_removes_only_expired_known_generated_files(tmp_path):
    now = time.time()
    settings = make_settings(
        tmp_path,
        cache_retention_days=5,
        report_retention_days=5,
        conversation_retention_days=5,
    )
    old_cache = settings.cache_dir / "old.json"
    old_report = settings.report_dir / "old.pdf"
    old_conversation = settings.conversation_dir / "2026-01-01" / "old.json"
    protected = settings.cache_dir / "keep.orig"
    unknown = settings.report_dir / "keep.txt"
    fresh = settings.report_dir / "fresh.md"
    for path in (old_cache, old_report, old_conversation, protected, unknown):
        make_old(path, now)
    fresh.parent.mkdir(parents=True, exist_ok=True)
    fresh.write_text("fresh", encoding="utf-8")

    result = RetentionManager(settings).apply(now=now)

    assert not old_cache.exists()
    assert not old_report.exists()
    assert not old_conversation.exists()
    assert protected.exists() and unknown.exists() and fresh.exists()
    assert result.removed_count == 3


def test_retention_does_not_follow_symlinks(tmp_path):
    now = time.time()
    settings = make_settings(tmp_path, report_retention_days=1)
    outside = tmp_path / "outside.pdf"
    make_old(outside, now)
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    link = settings.report_dir / "linked.pdf"
    link.symlink_to(outside)

    result = RetentionManager(settings).apply(now=now)

    assert link.is_symlink()
    assert outside.exists()
    assert result.removed_count == 0
    assert result.skipped["reports"] >= 1
