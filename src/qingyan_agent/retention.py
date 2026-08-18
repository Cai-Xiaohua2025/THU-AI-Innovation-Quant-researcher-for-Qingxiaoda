"""Explicit, opt-in retention policies for locally generated data."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from .artifacts import ArtifactRegistry
from .config import Settings


LOGGER = logging.getLogger(__name__)
PROTECTED_SUFFIXES = {".orig", ".rej"}
PROTECTED_NAMES = {".env"}


@dataclass
class RetentionResult:
    removed: dict[str, list[str]] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)

    @property
    def removed_count(self) -> int:
        return sum(len(paths) for paths in self.removed.values())


class RetentionManager:
    """Remove only known generated file types after an explicit age threshold."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def apply(self, *, now: float | None = None) -> RetentionResult:
        current = time.time() if now is None else now
        result = RetentionResult()
        policies = (
            ("cache", self.settings.cache_dir, self.settings.cache_retention_days, {".json"}),
            ("reports", self.settings.report_dir, self.settings.report_retention_days, {".md", ".pdf", ".png"}),
            (
                "conversations",
                self.settings.conversation_dir,
                self.settings.conversation_retention_days,
                {".json"},
            ),
        )
        for name, root, days, suffixes in policies:
            removed, skipped = cleanup_generated_files(root, days, suffixes, current)
            result.removed[name] = removed
            result.skipped[name] = skipped
        if result.removed.get("reports"):
            ArtifactRegistry(self.settings).prune_missing()
        if result.removed_count:
            LOGGER.info(
                "Retention removed generated files cache=%d reports=%d conversations=%d",
                len(result.removed["cache"]),
                len(result.removed["reports"]),
                len(result.removed["conversations"]),
            )
        return result


def cleanup_generated_files(
    root: Path,
    retention_days: int,
    allowed_suffixes: set[str],
    now: float,
) -> tuple[list[str], int]:
    if retention_days <= 0 or not root.is_dir() or root.is_symlink():
        return [], 0
    cutoff = now - retention_days * 86400
    removed: list[str] = []
    skipped = 0
    try:
        candidates = list(root.rglob("*"))
    except OSError:
        return [], 1
    for path in candidates:
        try:
            if path.is_symlink() or not path.is_file():
                if path.is_symlink():
                    skipped += 1
                continue
            if path.name in PROTECTED_NAMES or path.suffix.lower() in PROTECTED_SUFFIXES:
                skipped += 1
                continue
            if path.suffix.lower() not in allowed_suffixes:
                skipped += 1
                continue
            if path.stat().st_mtime >= cutoff:
                continue
            relative = path.relative_to(root).as_posix()
            path.unlink()
            removed.append(relative)
        except (OSError, ValueError):
            skipped += 1
    return removed, skipped
