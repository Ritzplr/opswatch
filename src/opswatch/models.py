"""Shared data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class Status(IntEnum):
    """Ordered so that max() over results gives the overall status."""

    OK = 0
    WARN = 1
    FAIL = 2

    @property
    def label(self) -> str:
        return self.name


@dataclass(frozen=True)
class CheckSpec:
    """One configured check, as read from the config file."""

    name: str
    type: str
    options: dict = field(default_factory=dict)


@dataclass
class CheckResult:
    name: str
    type: str
    status: Status
    message: str
    duration_ms: float = 0.0
    attempts: int = 1

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "status": self.status.label,
            "message": self.message,
            "duration_ms": round(self.duration_ms, 1),
            "attempts": self.attempts,
        }


@dataclass(frozen=True)
class Settings:
    timeout: float = 5.0
    retries: int = 2
    retry_delay: float = 1.0
    workers: int = 8
