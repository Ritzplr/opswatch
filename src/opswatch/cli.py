"""Command line interface: ``opswatch run | validate | init``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, state
from .config import ConfigError, load
from .notify import notify_all
from .report import RENDERERS, overall, render_text
from .runner import run_all

EXIT_OK, EXIT_WARN, EXIT_FAIL, EXIT_USAGE = 0, 1, 2, 3

EXAMPLE = Path(__file__).with_name("example.toml")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opswatch",
        description="Hands-off health checks. Exit code: 0 ok, 1 warning, 2 failing, 3 bad config.",
    )
    parser.add_argument("--version", action="version", version=f"opswatch {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run all checks once")
    run.add_argument("-c", "--config", required=True, help="path to a TOML config file")
    run.add_argument("-f", "--format", choices=sorted(RENDERERS), default="text")
    run.add_argument("-o", "--output", help="write the report to a file instead of stdout")
    run.add_argument("--notify", action="store_true", help="send alerts to configured channels")
    run.add_argument(
        "--state-file",
        help="remember the last result and alert only when it changes (new failure or recovery)",
    )

    validate = sub.add_parser("validate", help="check a config file without running anything")
    validate.add_argument("-c", "--config", required=True)

    sub.add_parser("init", help="print an example config to stdout")
    return parser


def _subject(current: dict[str, str], results) -> str:
    if not current:
        return "[opswatch] all checks recovered"
    worst = overall(results).label
    return f"[opswatch] {worst}: {len(current)} check(s) need attention"


def _cmd_run(args: argparse.Namespace) -> int:
    config = load(args.config)
    results = run_all(config.checks, config.settings)

    rendered = RENDERERS[args.format](results)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)

    if args.notify:
        current = state.problems(results)
        if args.state_file:
            should_send = state.should_notify(state.load(args.state_file), current)
            state.save(args.state_file, current)
        else:
            should_send = bool(current)
        if should_send:
            errors = notify_all(config.notify, _subject(current, results), render_text(results))
            for message in errors:
                print(f"opswatch: {message}", file=sys.stderr)

    return int(overall(results))


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "init":
            print(EXAMPLE.read_text(encoding="utf-8"), end="")
            return EXIT_OK
        if args.command == "validate":
            config = load(args.config)
            print(f"OK: {len(config.checks)} check(s) in {args.config}")
            return EXIT_OK
        return _cmd_run(args)
    except ConfigError as exc:
        print(f"opswatch: config error: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
