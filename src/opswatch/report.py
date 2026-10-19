"""Render results as text, JSON, Markdown or a self-contained HTML page."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone

from .models import CheckResult, Status

ICON = {Status.OK: "OK  ", Status.WARN: "WARN", Status.FAIL: "FAIL"}


def overall(results: list[CheckResult]) -> Status:
    return max((r.status for r in results), default=Status.OK)


def summary(results: list[CheckResult]) -> dict:
    counts = {s.label: sum(1 for r in results if r.status == s) for s in Status}
    return {"overall": overall(results).label, "total": len(results), **counts}


def _stamp(now: datetime | None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S UTC")


def render_text(results: list[CheckResult], now: datetime | None = None) -> str:
    s = summary(results)
    lines = [f"opswatch report, {_stamp(now)}", ""]
    width = max((len(r.name) for r in results), default=0)
    for r in results:
        lines.append(f"[{ICON[r.status]}] {r.name:<{width}}  {r.message}")
    lines += ["", f"{s['overall']}: {s['OK']} ok, {s['WARN']} warning, {s['FAIL']} failing of {s['total']}"]
    return "\n".join(lines)


def render_json(results: list[CheckResult], now: datetime | None = None) -> str:
    payload = {
        "generated_at": _stamp(now),
        "summary": summary(results),
        "results": [r.to_dict() for r in results],
    }
    return json.dumps(payload, indent=2)


def render_markdown(results: list[CheckResult], now: datetime | None = None) -> str:
    s = summary(results)
    lines = [
        f"# opswatch report: {s['overall']}",
        "",
        f"_{_stamp(now)}_: {s['OK']} ok, {s['WARN']} warning, {s['FAIL']} failing of {s['total']}",
        "",
        "| Status | Check | Detail |",
        "|---|---|---|",
    ]
    for r in results:
        detail = r.message.replace("|", "\\|")
        lines.append(f"| {r.status.label} | {r.name} | {detail} |")
    return "\n".join(lines)


_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>opswatch report</title>
<style>
:root{{--bg:#f6f8fa;--card:#fff;--fg:#1f2328;--muted:#59636e;--line:#d1d9e0;--ok:#1a7f37;--warn:#9a6700;--fail:#cf222e}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0d1117;--card:#151b23;--fg:#e6edf3;--muted:#9198a1;--line:#30363d;--ok:#3fb950;--warn:#d29922;--fail:#f85149}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px}}
main{{max-width:860px;margin:0 auto}}
h1{{font-size:1.4rem;margin:0 0 4px}} .sub{{color:var(--muted);margin:0 0 16px}}
table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line)}}
th,td{{text-align:left;padding:8px 12px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--muted);font-size:.8rem;text-transform:uppercase;letter-spacing:.04em}}
.pill{{font-weight:600;font-size:.8rem;padding:2px 8px;border-radius:999px;border:1px solid currentColor}}
.OK{{color:var(--ok)}} .WARN{{color:var(--warn)}} .FAIL{{color:var(--fail)}}
</style></head><body><main>
<h1>Overall: <span class="{overall}">{overall}</span></h1>
<p class="sub">{stamp}. {ok} ok, {warn} warning, {fail} failing of {total}.</p>
<table><thead><tr><th>Status</th><th>Check</th><th>Detail</th></tr></thead><tbody>
{rows}
</tbody></table></main></body></html>
"""


def render_html(results: list[CheckResult], now: datetime | None = None) -> str:
    s = summary(results)
    rows = "\n".join(
        f'<tr><td><span class="pill {r.status.label}">{r.status.label}</span></td>'
        f"<td>{html.escape(r.name)}</td><td>{html.escape(r.message)}</td></tr>"
        for r in results
    )
    return _HTML.format(
        overall=s["overall"], stamp=_stamp(now), ok=s["OK"], warn=s["WARN"],
        fail=s["FAIL"], total=s["total"], rows=rows,
    )


RENDERERS = {"text": render_text, "json": render_json, "md": render_markdown, "html": render_html}
