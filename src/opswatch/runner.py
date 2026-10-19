"""Run checks concurrently, with retries for transient failures."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from .checks import REGISTRY
from .models import CheckResult, CheckSpec, Settings, Status


def run_one(
    spec: CheckSpec,
    settings: Settings,
    sleep: Callable[[float], None] = time.sleep,
) -> CheckResult:
    """Run a single check. FAIL results are retried; WARN and OK are final."""
    fn = REGISTRY[spec.type]
    attempts = 0
    started = time.perf_counter()
    status, message = Status.FAIL, "check did not run"
    for attempt in range(settings.retries + 1):
        attempts = attempt + 1
        try:
            status, message = fn(spec.options, settings.timeout)
        except Exception as exc:  # a broken check must never stop the run
            status, message = Status.FAIL, f"{type(exc).__name__}: {exc}"
        if status != Status.FAIL or attempt == settings.retries:
            break
        sleep(settings.retry_delay * (attempt + 1))
    duration_ms = (time.perf_counter() - started) * 1000
    return CheckResult(spec.name, spec.type, status, message, duration_ms, attempts)


def run_all(specs: list[CheckSpec], settings: Settings) -> list[CheckResult]:
    """Run every check in parallel and return results in config order."""
    with ThreadPoolExecutor(max_workers=settings.workers) as pool:
        futures = [pool.submit(run_one, spec, settings) for spec in specs]
        return [f.result() for f in futures]
