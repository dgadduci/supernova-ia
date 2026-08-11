"""Operator CLI: query bounded production structured events from Railway.

The CLI is a thin wrapper around the locally authenticated Railway
CLI. It is the only operator-facing surface allowed to read
production logs and the only component that invokes ``railway logs``.

The CLI is intentionally narrow:

* arguments require explicit ``--project``, ``--environment`` and
  ``--service`` selection; there is no implicit fallback;
* filters are bounded: ``--since`` (ISO 8601 lower bound),
  ``--event`` (exact match), ``--level`` (info or error) and
  ``--limit`` (1..max, default 100, max 1000);
* output is a single JSON object with a bounded ``events`` array; the
  CLI never prints raw Railway lines, never reflects argument
  values back into the output, and never accepts credentials;
* the CLI never opens a database session, never calls Twilio or
  Ollama directly, and never modifies Railway state.

Exit codes:

* ``0`` success - the JSON output is printed (empty ``events``
  means "no results matching the filters");
* ``2`` invalid arguments or configuration;
* ``3`` Railway CLI invocation failure (binary missing, timeout or
  non-zero exit code);
* ``4`` unparseable provider output - the CLI never prints the raw
  failing line; it only reports the category.
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from backend.observability import (
    SCHEMA_VERSION,
    EventValidationError,
    parse_event,
)

logger = logging.getLogger(__name__)


DEFAULT_LIMIT = 100
MAX_LIMIT = 1000
RAILWAY_TIMEOUT_SECONDS = 30
RAILWAY_BINARY = "railway"
RAILWAY_LOGS_SUBCOMMAND = "logs"

LEVEL_INFO = "info"
LEVEL_ERROR = "error"
ALLOWED_LEVELS: frozenset[str] = frozenset({LEVEL_INFO, LEVEL_ERROR})

EXIT_OK = 0
EXIT_INVALID_ARGUMENTS = 2
EXIT_RAILWAY_INVOCATION_FAILED = 3
EXIT_RAILWAY_UNPARSEABLE = 4


class RailwayInvocationError(RuntimeError):
    """Raised when the Railway CLI cannot be invoked or exits non-zero."""


class UnparseableRailwayOutputError(RuntimeError):
    """Raised when a line from Railway is not a valid structured event."""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.cli.query_production_logs",
        description=(
            "Query bounded production structured events from Railway. "
            "Requires an authenticated local Railway CLI and explicit "
            "project/environment/service selection. Never prints raw "
            "provider lines on parse failure."
        ),
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Railway project id (required, explicit selection)",
    )
    parser.add_argument(
        "--environment",
        required=True,
        help="Railway environment id (required, explicit selection)",
    )
    parser.add_argument(
        "--service",
        required=True,
        help="Railway service id (required, explicit selection)",
    )
    parser.add_argument(
        "--since",
        default=None,
        help=(
            "ISO 8601 lower bound; only events with timestamp >= this "
            "value are returned"
        ),
    )
    parser.add_argument(
        "--event",
        default=None,
        help="Only return events with this exact name",
    )
    parser.add_argument(
        "--level",
        default=None,
        choices=sorted(ALLOWED_LEVELS),
        help=(
            "info: events with outcome; error: events with failure_category. "
            "When omitted, both kinds are returned."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=(
            "Maximum number of events returned "
            f"(default {DEFAULT_LIMIT}, max {MAX_LIMIT})"
        ),
    )
    return parser


def _is_valid_iso8601(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _validate_args(args: argparse.Namespace) -> None:
    if not args.project or not args.environment or not args.service:
        print(
            "invalid_arguments: --project, --environment and --service "
            "are required identifiers",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_INVALID_ARGUMENTS)
    if not (1 <= args.limit <= MAX_LIMIT):
        print(
            f"invalid_arguments: --limit must be between 1 and {MAX_LIMIT} "
            f"(got {args.limit})",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_INVALID_ARGUMENTS)
    if args.since is not None and not _is_valid_iso8601(args.since):
        print(
            f"invalid_arguments: --since must be ISO 8601 "
            f"(got {args.since!r})",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_INVALID_ARGUMENTS)
    if args.event is not None and not args.event:
        print(
            "invalid_arguments: --event must be a non-empty string",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_INVALID_ARGUMENTS)


def _build_railway_command(args: argparse.Namespace) -> list[str]:
    return [
        RAILWAY_BINARY,
        RAILWAY_LOGS_SUBCOMMAND,
        "--project",
        str(args.project),
        "--environment",
        str(args.environment),
        "--service",
        str(args.service),
        "--json",
    ]


def _match_event(event: dict[str, Any], args: argparse.Namespace) -> bool:
    if args.event is not None and event.get("event") != args.event:
        return False
    if args.level == LEVEL_INFO and "outcome" not in event:
        return False
    if args.level == LEVEL_ERROR and "failure_category" not in event:
        return False
    if args.since is not None:
        ts = event.get("timestamp")
        if not isinstance(ts, str) or ts < args.since:
            return False
    return True


def _extract_event_from_line(line: str) -> dict[str, Any]:
    """Extract a single structured event from a Railway log line.

    Supports two envelope shapes:

    * the line IS the structured event (the application emits raw
      JSON to stdout and Railway does not envelope it); or
    * the line is a Railway JSON envelope whose ``message`` field
      contains the structured event JSON.

    The envelope inspection is bounded to the ``message`` field and
    never reflects the envelope itself into the output.
    """
    try:
        envelope = json.loads(line)
    except json.JSONDecodeError as exc:
        raise UnparseableRailwayOutputError(
            "railway line is not valid JSON"
        ) from exc
    if not isinstance(envelope, dict):
        raise UnparseableRailwayOutputError(
            "railway JSON envelope must be an object"
        )
    if (
        envelope.get("schema_version") == int(SCHEMA_VERSION)
        and isinstance(envelope.get("event"), str)
    ):
        try:
            return parse_event(line)
        except EventValidationError as exc:
            raise UnparseableRailwayOutputError(
                "railway line is not a valid structured event"
            ) from exc
    message = envelope.get("message")
    if not isinstance(message, str):
        raise UnparseableRailwayOutputError(
            "railway envelope has no valid message field"
        )
    try:
        return parse_event(message)
    except EventValidationError as exc:
        raise UnparseableRailwayOutputError(
            "railway envelope message is not a valid structured event"
        ) from exc


def _run_railway(
    args: argparse.Namespace,
    *,
    runner: Callable[..., Any] | None = None,
) -> Any:
    """Invoke the Railway CLI and return the completed process.

    ``runner`` defaults to :func:`subprocess.run`; tests substitute a
    stub. The function raises :class:`RailwayInvocationError` for
    every documented failure mode (binary missing, timeout, non-zero
    exit code).
    """
    run = runner if runner is not None else subprocess.run
    cmd = _build_railway_command(args)
    try:
        completed = run(
            cmd,
            capture_output=True,
            text=True,
            timeout=RAILWAY_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RailwayInvocationError(
            f"railway binary not found: {type(exc).__name__}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RailwayInvocationError(
            f"railway CLI timed out: {type(exc).__name__}"
        ) from exc
    except Exception as exc:
        raise RailwayInvocationError(
            f"railway CLI invocation failed: {type(exc).__name__}"
        ) from exc

    if completed.returncode != 0:
        raise RailwayInvocationError(
            f"railway CLI exited with code {completed.returncode}"
        )
    return completed


def _parse_lines_into_events(completed: Any) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        events.append(_extract_event_from_line(line))
    return events


def _apply_filters(
    events: list[dict[str, Any]], args: argparse.Namespace
) -> list[dict[str, Any]]:
    filtered = [event for event in events if _match_event(event, args)]
    return filtered[: int(args.limit)]


def _format_output(
    filtered: list[dict[str, Any]], args: argparse.Namespace
) -> str:
    payload = {
        "schema_version": int(SCHEMA_VERSION),
        "count": len(filtered),
        "limit": int(args.limit),
        "events": filtered,
        "filter": {
            "since": args.since,
            "event": args.event,
            "level": args.level,
        },
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Callable[..., Any] | None = None,
    now: Callable[[], datetime] | None = None,
) -> int:
    """Run the query CLI.

    All side effects are bounded to the local Railway CLI invocation
    and a single JSON line on stdout. The CLI never opens a database
    session, never calls Twilio or Ollama directly, and never
    mutates Railway state.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    _validate_args(args)

    try:
        completed = _run_railway(args, runner=runner)
    except RailwayInvocationError as exc:
        print(
            f"railway_invocation_failed: {type(exc).__name__}",
            file=sys.stderr,
        )
        return EXIT_RAILWAY_INVOCATION_FAILED

    try:
        events = _parse_lines_into_events(completed)
    except UnparseableRailwayOutputError as exc:
        print(
            f"railway_unparseable_output: {type(exc).__name__}",
            file=sys.stderr,
        )
        return EXIT_RAILWAY_UNPARSEABLE

    filtered = _apply_filters(events, args)
    print(_format_output(filtered, args))
    return EXIT_OK


__all__ = [
    "ALLOWED_LEVELS",
    "DEFAULT_LIMIT",
    "EXIT_INVALID_ARGUMENTS",
    "EXIT_OK",
    "EXIT_RAILWAY_INVOCATION_FAILED",
    "EXIT_RAILWAY_UNPARSEABLE",
    "LEVEL_ERROR",
    "LEVEL_INFO",
    "MAX_LIMIT",
    "RAILWAY_BINARY",
    "RAILWAY_LOGS_SUBCOMMAND",
    "RAILWAY_TIMEOUT_SECONDS",
    "RailwayInvocationError",
    "UnparseableRailwayOutputError",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
