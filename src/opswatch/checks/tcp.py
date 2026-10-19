"""TCP port reachability (databases, SFTP, message brokers)."""

from __future__ import annotations

import socket
import time

from ..models import Status
from . import register


@register("tcp")
def check_tcp(options: dict, timeout: float) -> tuple[Status, str]:
    host = options["host"]
    port = int(options["port"])
    timeout = float(options.get("timeout", timeout))
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError as exc:
        return Status.FAIL, f"cannot connect to {host}:{port}: {exc}"
    elapsed = (time.perf_counter() - started) * 1000
    return Status.OK, f"{host}:{port} reachable in {elapsed:.0f} ms"
