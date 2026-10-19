"""Disk usage."""

from __future__ import annotations

import shutil

from ..models import Status
from . import register


@register("disk")
def check_disk(options: dict, timeout: float) -> tuple[Status, str]:
    path = options["path"]
    usage = shutil.disk_usage(path)
    used_percent = usage.used / usage.total * 100
    free_gb = usage.free / 1024**3
    message = f"{path}: {used_percent:.1f}% used, {free_gb:.1f} GiB free"

    fail_at = float(options.get("max_used_percent", 90))
    warn_at = float(options.get("warn_used_percent", fail_at - 10))
    if used_percent >= fail_at:
        return Status.FAIL, f"{message} (limit {fail_at:g}%)"
    if used_percent >= warn_at:
        return Status.WARN, f"{message} (warning at {warn_at:g}%)"
    return Status.OK, message
