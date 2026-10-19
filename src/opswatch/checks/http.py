"""HTTP(S) availability, latency, content and certificate expiry."""

from __future__ import annotations

import socket
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

from ..models import Status
from . import register

USER_AGENT = "opswatch/0.1 (+https://github.com/Ritzplr/opswatch)"


def days_until(not_after: str, now: datetime | None = None) -> float:
    """Days from ``now`` until a certificate's notAfter string (as ssl reports it)."""
    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), tz=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (expires - now).total_seconds() / 86400


def cert_days_left(host: str, port: int, timeout: float) -> float:
    context = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with context.wrap_socket(sock, server_hostname=host) as tls:
            return days_until(tls.getpeercert()["notAfter"])


@register("http")
def check_http(options: dict, timeout: float) -> tuple[Status, str]:
    url = options["url"]
    timeout = float(options.get("timeout", timeout))
    expect = int(options.get("expect_status", 200))
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status_code = response.status
            body = response.read(1_000_000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        body = ""
        exc.close()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return Status.FAIL, f"request failed: {reason}"
    latency_ms = (time.perf_counter() - started) * 1000

    if status_code != expect:
        return Status.FAIL, f"expected HTTP {expect}, got {status_code}"

    needle = options.get("contains")
    if needle and needle not in body:
        return Status.FAIL, f"HTTP {status_code} but response does not contain {needle!r}"

    status = Status.OK
    parts = [f"HTTP {status_code} in {latency_ms:.0f} ms"]

    warn_ms = options.get("latency_warn_ms")
    if warn_ms is not None and latency_ms > float(warn_ms):
        status = Status.WARN
        parts.append(f"slower than {warn_ms} ms")

    warn_days = options.get("cert_warn_days")
    parsed = urlparse(url)
    if warn_days is not None and parsed.scheme == "https":
        left = cert_days_left(parsed.hostname, parsed.port or 443, timeout)
        parts.append(f"certificate valid for {left:.0f} more days")
        if left < 0:
            return Status.FAIL, "; ".join(parts[:-1] + ["certificate has expired"])
        if left < float(warn_days):
            status = max(status, Status.WARN)

    return status, "; ".join(parts)
