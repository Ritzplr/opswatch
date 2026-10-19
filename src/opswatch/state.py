"""Remember what was failing last time so alerts fire on change, not every run."""

from __future__ import annotations

import json
from pathlib import Path

from .models import CheckResult, Status


def problems(results: list[CheckResult]) -> dict[str, str]:
    """Map check name -> status label for everything that is not OK."""
    return {r.name: r.status.label for r in results if r.status != Status.OK}


def load(path: str | Path) -> dict[str, str]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(path: str | Path, current: dict[str, str]) -> None:
    Path(path).write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")


def should_notify(previous: dict[str, str], current: dict[str, str]) -> bool:
    """True when the set of problems, or any problem's severity, changed.

    That covers new failures, escalations and recoveries (including all clear).
    """
    return previous != current
