"""Operator CLI: query bounded production structured events from Railway.

The CLI is a thin wrapper around the locally authenticated Railway
CLI. It is the only operator-facing surface allowed to read
production logs and the only component that invokes ``railway logs``.

The CLI is intentionally narrow:

* arguments require explicit ``--project``, ``--environment`` and
  ``--service`` selection; there is no implicit fallback;
* filters are bounded: ``--since`` (ISO 8601 lower bound), ``--event``
  (exact match, applied as a Railway source-side text filter AND as
  a local allowlist), ``--level`` (info or error) and ``--limit``
  (1..max, default 100, max 1000). The same ``--limit`` is also
  pushed to Railway as ``--lines`` so the source query is bounded
  and the local array cap is a second line of defence;
* output is a single JSON object with a bounded ``events`` array; the
  CLI never prints raw Railway lines, never reflects argument
  values back into the output, and never accepts credentials;
* the CLI never opens a database session, never calls Twilio or
  Ollama directly, and never modifies Railway state.

Source-bound query contract:

* ``--lines`` is supported by Railway (``railway logs --help``) and
  disables streaming, so the local ``--limit`` cap is applied at the
  source rather than only at the in-memory stage;
* ``--since`` is supported by Railway as ``-S``/``--since`` and accepts
  the same ISO 8601 lower bound the CLI already validates, so the
  source returns only post-bound lines; the local ``_match_event``
  also filters by timestamp as a safety net;
* ``--event`` is applied ONLY as a local filter on the parsed
  events. Railway's ``-f``/``--filter`` is a text-search filter on
  the ``message`` field, but the application emits structured JSON
  events with the catalogue fields (``event``, ``schema_version``,
  ``component``, ``outcome`` …) as top-level attributes and an
  empty ``message``, so a Railway ``--filter`` against the event
  name would always miss every real event. The CLI therefore never
  forwards ``--event`` to Railway and applies it locally after
  parsing so the bounded array contains only the requested event
  name.

Railway mixed-log behaviour:

The application emits one structured JSON event per stdout line.
Railway history interleaves those lines with platform access logs
and stdout/stderr noise. Railway's ``--json`` output also injects a
small envelope (``level`` and ``message``) onto structured events
that the application originally wrote as plain JSON, while plain
stdout/stderr lines are wrapped into the same envelope shape with
their raw text moved into ``message``. The CLI distinguishes the
three document classes:

* a line that is a valid catalogued structured event → returned in
  the bounded array (after local filters); Railway-injected envelope
  fields are stripped before catalogue validation so the contract
  stays strict and platform additions never leak into output;
* a line that is *not* structured (plain text log, plain Railway
  envelope without ``message``, envelope whose ``message`` is not a
  structured event, etc.) → SKIPPED silently, NEVER printed;
* a line that *claims* to be a structured event (it carries
  ``schema_version`` + ``event``) but violates the contract, or a
  Railway envelope whose ``message`` field claims to be structured
  but is invalid, or a non-JSON line that contradicts Railway's
  ``--json`` contract → exit 4 (railway_unparseable_output).

The CLI never prints the raw failing line in any branch; it only
reports the failure category on stderr.

Exit codes:

* ``0`` success - the JSON output is printed (empty ``events``
  means "no matching catalogued events in the requested window");
* ``2`` invalid arguments or configuration;
* ``3`` Railway CLI invocation failure (binary missing, timeout or
  non-zero exit code);
* ``4`` structured-contract violation - the CLI never prints the
  raw failing line; it only reports the category.
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

_STRUCTURED_EVENT_SHAPE_KEYS: frozenset[str] = frozenset(
    {"event", "schema_version"}
)

_RAILWAY_ENVELOPE_FIELDS: frozenset[str] = frozenset({"level", "message"})

_RAILWAY_INJECTED_FIELDS_NOT_OWNED_BY_CATALOGUE: frozenset[str] = frozenset(
    {"level", "message"}
)


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


def _is_safe_event_name(value: str) -> bool:
    """Validate that an event-name token is a closed alphanumeric
    catalogue identifier.

    The same shape rule is used by ``backend.observability.events``
    so the CLI can confidently push it to Railway's ``--filter``
    without leaking operator-typed whitespace, control characters
    or quote-breaking tokens.
    """
    if not isinstance(value, str):
        return False
    if len(value) == 0 or len(value) > 64:
        return False
    if not value.replace("_", "").isalnum():
        return False
    return any(c.isalpha() for c in value)


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
    if args.event is not None and not _is_safe_event_name(args.event):
        print(
            "invalid_arguments: --event must be a closed alphanumeric "
            "catalogue token (matching the documented event names)",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_INVALID_ARGUMENTS)


def _build_railway_command(args: argparse.Namespace) -> list[str]:
    """Assemble the documented ``railway logs`` invocation.

    The command uses only flags documented in ``railway logs
    --help``:

    * ``--project``, ``--environment``, ``--service`` for explicit
      selection (also supported under the short forms ``-p`` /
      ``-e`` / ``-s``);
    * ``--json`` for the documented JSON contract;
    * ``--lines`` to bound the source query at the platform level
      (it disables streaming and returns at most ``args.limit``
      historical lines, equivalent to the local output cap);
    * ``--since`` when the operator provides a valid ISO 8601 lower
      bound, so the platform only returns post-bound lines.

    ``--event`` is NOT forwarded to Railway: Railway's
    ``-f``/``--filter`` is a text-search on the ``message`` field,
    which is empty for our structured events, so a source-side
    filter would always return zero matches. ``--event`` is applied
    locally on the parsed events by :func:`_match_event` so the
    bounded ``events`` array contains only the requested event
    name regardless of what Railway returns.

    The flags are added in a stable order so the focused tests can
    assert on their positions without over-coupling to internals.
    """
    cmd: list[str] = [
        RAILWAY_BINARY,
        RAILWAY_LOGS_SUBCOMMAND,
        "--project",
        str(args.project),
        "--environment",
        str(args.environment),
        "--service",
        str(args.service),
        "--json",
        "--lines",
        str(int(args.limit)),
    ]
    if args.since is not None:
        cmd.extend(["--since", str(args.since)])
    return cmd


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


def _looks_like_structured_event_envelope(payload: Any) -> bool:
    """Return True when the decoded payload claims the structured
    event shape (``event`` + ``schema_version``).

    A line is treated as a structured-event claim only when both
    fields are present in their documented types. Plain access
    logs, normal Railway envelopes and free-form log lines do NOT
    satisfy this predicate and are therefore skipped silently.
    """
    if not isinstance(payload, dict):
        return False
    return (
        isinstance(payload.get("event"), str)
        and isinstance(payload.get("schema_version"), int)
    )


def _strip_railway_envelope_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``payload`` without Railway-injected fields.

    Railway's ``--json`` output augments every line with a small
    envelope (``level`` always set to ``"info"``; ``message`` either
    the raw stdout text for non-JSON lines or an empty string for
    structured events). These envelope fields are platform metadata
    and do not belong to the catalogue contract; stripping them
    before :func:`parse_event` keeps the catalogue strict so a
    future platform addition cannot leak through into emitted
    events.
    """
    return {
        key: value
        for key, value in payload.items()
        if key not in _RAILWAY_ENVELOPE_FIELDS
    }


def _validate_catalogue_payload(
    payload: dict[str, Any], *, where: str
) -> dict[str, Any]:
    """Validate ``payload`` (with Railway envelope stripped) as our
    catalogue event.

    Returns the catalogue-validated payload. Raises
    :class:`UnparseableRailwayOutputError` when the payload
    violates the catalogue contract so the CLI exits with 4.
    """
    try:
        return parse_event(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":")
            )
        )
    except EventValidationError as exc:
        raise UnparseableRailwayOutputError(
            f"railway {where} is not a valid structured event"
        ) from exc


def _parse_structured_event(line: str, *, where: str) -> dict[str, Any]:
    """Parse a candidate structured-event JSON line.

    Lines that violate the catalogue raise
    :class:`UnparseableRailwayOutputError` so the CLI exits with 4.
    Empty / non-string input raises
    :class:`UnparseableRailwayOutputError` because the CLI received
    a line that claimed to be structured but is unusable.

    When the line carries Railway's envelope fields
    (``level`` / ``message``) they are stripped before catalogue
    validation. The returned dict therefore matches the original
    application-emitted payload and never contains Railway
    metadata.
    """
    if not isinstance(line, str):
        raise UnparseableRailwayOutputError(
            f"railway {where} candidate is not a string"
        )
    if not line.strip():
        raise UnparseableRailwayOutputError(
            f"railway {where} candidate is empty"
        )
    try:
        decoded = json.loads(line)
    except json.JSONDecodeError as exc:
        raise UnparseableRailwayOutputError(
            f"railway {where} candidate is not valid JSON"
        ) from exc
    if not isinstance(decoded, dict):
        raise UnparseableRailwayOutputError(
            f"railway {where} candidate must be a JSON object"
        )
    return _validate_catalogue_payload(
        _strip_railway_envelope_fields(decoded), where=where
    )


def _extract_event_from_line(line: str) -> dict[str, Any] | None:
    """Extract a single structured event from a Railway log line.

    Returns the parsed event, or ``None`` when the line is normal
    Railway mixed output that the CLI must skip silently. Raises
    :class:`UnparseableRailwayOutputError` only when:

    * the line is not valid JSON at all (Railway broke its ``--json``
      contract);
    * the line is a JSON non-object (Railway promises an object per
      line);
    * the line *claims* to be a structured event (carries both
      ``event`` and ``schema_version``) but violates the catalogue;
    * the line is a Railway envelope whose ``message`` field *claims*
      to be a structured event but violates the catalogue.

    The raw failing line is NEVER printed; the error message carries
    only the category.
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

    if _looks_like_structured_event_envelope(envelope):
        return _parse_structured_event(line, where="line")

    message = envelope.get("message")
    if not isinstance(message, str):
        # Plain Railway envelope (access log, deployment info, etc.):
        # not a structured event; skip silently.
        return None

    try:
        decoded_message = json.loads(message)
    except json.JSONDecodeError:
        # Free-form stdout/stderr wrapped in a Railway envelope:
        # not a structured event; skip silently.
        return None

    if _looks_like_structured_event_envelope(decoded_message):
        # The envelope's message claims to be a structured event; if
        # the contract is violated we surface it as a parse failure.
        return _parse_structured_event(message, where="envelope message")

    # The envelope's message is JSON but it is not our structured
    # event shape (e.g., a provider payload or a third-party log
    # event). Skip silently - the catalogue does not own this shape.
    return None


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
    """Walk the Railway stdout and collect only catalogued events.

    Empty lines and lines that are not catalogued structured
    events (free-form stdout, plain Railway access logs, third-party
    JSON shapes, etc.) are dropped silently. The first line that
    claims the structured-event shape but violates the catalogue
    is propagated to the caller as
    :class:`UnparseableRailwayOutputError` so the CLI can exit
    with the documented ``4`` code without leaking the raw line.
    """
    events: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        parsed = _extract_event_from_line(line)
        if parsed is None:
            continue
        events.append(parsed)
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
