"""Check registry.

A check is a function ``(options: dict, timeout: float) -> (Status, message)``.
It should return FAIL for a problem it detects and may raise for anything
unexpected; the runner turns exceptions into FAIL results.
"""

from __future__ import annotations

from collections.abc import Callable

from ..models import Status

CheckFn = Callable[[dict, float], tuple[Status, str]]

REGISTRY: dict[str, CheckFn] = {}


def register(name: str) -> Callable[[CheckFn], CheckFn]:
    def decorator(fn: CheckFn) -> CheckFn:
        REGISTRY[name] = fn
        return fn

    return decorator


# Importing the modules registers their checks.
from . import backup, disk, http, tcp  # noqa: E402,F401
