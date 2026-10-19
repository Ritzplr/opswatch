"""Backup freshness: is the newest matching file recent enough and not empty?

Works on any path you can mount or sync, so it also covers cloud backups pulled
down or exposed through a FUSE mount (gcsfuse, s3fs).
"""

from __future__ import annotations

import time
from pathlib import Path

from ..models import Status
from . import register


def _humanize(seconds: float) -> str:
    hours = seconds / 3600
    return f"{hours:.1f} h" if hours < 48 else f"{hours / 24:.1f} days"


@register("backup")
def check_backup(options: dict, timeout: float, now: float | None = None) -> tuple[Status, str]:
    folder = Path(options["path"])
    pattern = options["pattern"]
    max_age = float(options["max_age_hours"]) * 3600
    warn_age = float(options.get("warn_age_hours", options["max_age_hours"] * 0.75)) * 3600
    min_size = int(options.get("min_size_bytes", 1))
    now = time.time() if now is None else now

    if not folder.is_dir():
        return Status.FAIL, f"backup folder not found: {folder}"
    files = [p for p in folder.glob(pattern) if p.is_file()]
    if not files:
        return Status.FAIL, f"no files matching {pattern!r} in {folder}"

    newest = max(files, key=lambda p: p.stat().st_mtime)
    info = newest.stat()
    age = max(0.0, now - info.st_mtime)
    description = f"{newest.name} ({info.st_size:,} bytes, {_humanize(age)} old)"

    if info.st_size < min_size:
        return Status.FAIL, f"newest backup is too small: {description}"
    if age > max_age:
        return Status.FAIL, f"newest backup is stale: {description}"
    if age > warn_age:
        return Status.WARN, f"newest backup is getting old: {description}"
    return Status.OK, f"newest backup {description}"
