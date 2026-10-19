"""Load and validate the TOML config."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .models import CheckSpec, Settings

# Per check type: (required options, optional options)
SCHEMA: dict[str, tuple[set[str], set[str]]] = {
    "http": (
        {"url"},
        {"expect_status", "contains", "latency_warn_ms", "cert_warn_days", "timeout"},
    ),
    "tcp": ({"host", "port"}, {"timeout"}),
    "disk": ({"path"}, {"warn_used_percent", "max_used_percent"}),
    "backup": (
        {"path", "pattern", "max_age_hours"},
        {"min_size_bytes", "warn_age_hours"},
    ),
}


class ConfigError(ValueError):
    """Raised for any problem in the config file."""


@dataclass(frozen=True)
class Config:
    settings: Settings
    checks: list[CheckSpec]
    notify: dict = field(default_factory=dict)


def _validate_check(index: int, raw: dict) -> CheckSpec:
    where = f"checks[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} must be a table")
    name = raw.get("name")
    ctype = raw.get("type")
    if not name or not isinstance(name, str):
        raise ConfigError(f"{where}: 'name' is required")
    if ctype not in SCHEMA:
        known = ", ".join(sorted(SCHEMA))
        raise ConfigError(f"{where} ('{name}'): unknown type {ctype!r}, expected one of: {known}")
    required, optional = SCHEMA[ctype]
    options = {k: v for k, v in raw.items() if k not in ("name", "type")}
    missing = required - options.keys()
    if missing:
        raise ConfigError(f"{where} ('{name}'): missing {', '.join(sorted(missing))}")
    unknown = options.keys() - required - optional
    if unknown:
        raise ConfigError(f"{where} ('{name}'): unknown option(s) {', '.join(sorted(unknown))}")
    return CheckSpec(name=name, type=ctype, options=options)


def parse(data: dict) -> Config:
    raw_settings = data.get("settings", {})
    allowed = {"timeout", "retries", "retry_delay", "workers"}
    unknown = raw_settings.keys() - allowed
    if unknown:
        raise ConfigError(f"settings: unknown option(s) {', '.join(sorted(unknown))}")
    settings = Settings(**raw_settings)
    if settings.retries < 0 or settings.workers < 1 or settings.timeout <= 0:
        raise ConfigError("settings: retries must be >= 0, workers >= 1 and timeout > 0")

    raw_checks = data.get("checks", [])
    if not raw_checks:
        raise ConfigError("no [[checks]] defined")
    checks = [_validate_check(i, c) for i, c in enumerate(raw_checks)]
    names = [c.name for c in checks]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ConfigError(f"duplicate check name(s): {', '.join(sorted(dupes))}")
    return Config(settings=settings, checks=checks, notify=data.get("notify", {}))


def load(path: str | Path) -> Config:
    try:
        # utf-8-sig tolerates the byte-order mark that Windows editors often add.
        text = Path(path).read_text(encoding="utf-8-sig")
        data = tomllib.loads(text)
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc
    return parse(data)
