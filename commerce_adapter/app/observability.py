"""Backend-independent bounded JSON-line emitter for the T-C adapter.

The module owns the adapter-side observability contract for the
isolated inbound webhook. The adapter is the observability owner for
the transport boundary; it must not import ``backend.*`` and must
build the line locally so Railway operators can grep both services
with the same event name.

The contract is intentionally narrow:

* the event name, schema version, component, timestamp, outcome and
  bounded reason are the only documented payload fields;
* the closed outcome vocabulary is ``accepted``, ``duplicate``,
  ``rejected`` and ``unreachable``;
* the closed reason vocabulary is the same allowlist used by the
  core catalogue so Railway queries can group both services without
  parsing free-form text;
* ``reason`` is required for ``rejected`` and ``unreachable`` and
  must be absent for ``accepted`` and ``duplicate``;
* ``http_status`` may only appear on the adapter
  ``unreachable`` outcome as a bounded integer;
* the emitter swallows validation, serialization and write errors
  so the surrounding request is never altered;
* no sensitive fallback is emitted; if the event is invalid the
  function simply returns ``False`` and the webhook keeps its
  existing response path.
"""
from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION: int = 1

EVENT_NAME: str = "commerce_installation_inbound_outcome"
COMPONENT: str = "commerce_installation_adapter"

OUTCOME_ACCEPTED: str = "accepted"
OUTCOME_DUPLICATE: str = "duplicate"
OUTCOME_REJECTED: str = "rejected"
OUTCOME_UNREACHABLE: str = "unreachable"

OUTCOMES: frozenset[str] = frozenset(
    {OUTCOME_ACCEPTED, OUTCOME_DUPLICATE, OUTCOME_REJECTED, OUTCOME_UNREACHABLE}
)

REASON_SIGNATURE_REJECTED: str = "signature_rejected"
REASON_INVALID_FORM: str = "invalid_form"
REASON_MISSING_COMERCIO_ID: str = "missing_comercio_id"
REASON_CORE_HTTP_FAILURE: str = "core_http_failure"
REASON_CORE_INVALID_RESPONSE: str = "core_invalid_response"
REASON_UNKNOWN_DESTINATION: str = "unknown_destination"
REASON_SHARED_CHANNEL_NOT_SUPPORTED: str = "shared_channel_not_supported"
REASON_CHANNEL_COMMERCE_MISMATCH: str = "channel_commerce_mismatch"
REASON_UNKNOWN_CLIENT: str = "unknown_client"
REASON_UNAVAILABLE_COMMERCE: str = "unavailable_commerce"
REASON_INVALID_CONTEXT: str = "invalid_context"

REASONS: frozenset[str] = frozenset(
    {
        REASON_SIGNATURE_REJECTED,
        REASON_INVALID_FORM,
        REASON_MISSING_COMERCIO_ID,
        REASON_CORE_HTTP_FAILURE,
        REASON_CORE_INVALID_RESPONSE,
        REASON_UNKNOWN_DESTINATION,
        REASON_SHARED_CHANNEL_NOT_SUPPORTED,
        REASON_CHANNEL_COMMERCE_MISMATCH,
        REASON_UNKNOWN_CLIENT,
        REASON_UNAVAILABLE_COMMERCE,
        REASON_INVALID_CONTEXT,
    }
)

_MIN_HTTP_STATUS: int = 100
_MAX_HTTP_STATUS: int = 599

WriteSink = Callable[[str], None]


class InboundOutcomeEventError(ValueError):
    """Raised when the caller tries to build an invalid event.

    The exception is intentionally narrow. :func:`emit` swallows it
    so the surrounding request path never sees an observability
    failure; the exception remains useful for focused tests.
    """


def _now_iso_utc() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _is_safe_outcome(value: Any) -> bool:
    return isinstance(value, str) and value in OUTCOMES


def _is_safe_reason(value: Any) -> bool:
    return isinstance(value, str) and value in REASONS


def _is_safe_http_status(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return _MIN_HTTP_STATUS <= value <= _MAX_HTTP_STATUS


def build_payload(
    *,
    outcome: str,
    reason: str | None = None,
    http_status: int | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Validate the input and return the JSON-ready payload.

    The function is pure: it does not emit anything. It mirrors the
    bounded catalogue rules so a malformed event is rejected before
    any sink write is attempted.
    """
    if not _is_safe_outcome(outcome):
        raise InboundOutcomeEventError(
            f"outcome must be one of {sorted(OUTCOMES)} (got {outcome!r})"
        )

    payload: dict[str, Any] = {
        "event": EVENT_NAME,
        "schema_version": int(SCHEMA_VERSION),
        "component": COMPONENT,
        "timestamp": (
            timestamp if isinstance(timestamp, str) and timestamp else _now_iso_utc()
        ),
        "outcome": outcome,
    }

    if outcome in {OUTCOME_ACCEPTED, OUTCOME_DUPLICATE}:
        if reason is not None:
            raise InboundOutcomeEventError(
                f"outcome {outcome!r} must not carry a reason "
                f"(got {reason!r})"
            )
        if http_status is not None:
            raise InboundOutcomeEventError(
                f"outcome {outcome!r} must not carry http_status "
                f"(got {http_status!r})"
            )
        return payload

    if not _is_safe_reason(reason):
        raise InboundOutcomeEventError(
            f"reason is required for outcome {outcome!r} and must be "
            f"one of {sorted(REASONS)} (got {reason!r})"
        )
    payload["reason"] = reason

    if http_status is None:
        return payload

    if outcome != OUTCOME_UNREACHABLE:
        raise InboundOutcomeEventError(
            "http_status is only allowed for outcome "
            f"{OUTCOME_UNREACHABLE!r} (got {outcome!r})"
        )
    if not _is_safe_http_status(http_status):
        raise InboundOutcomeEventError(
            f"http_status must be an integer in "
            f"[{_MIN_HTTP_STATUS}, {_MAX_HTTP_STATUS}] "
            f"(got {type(http_status).__name__}: {http_status!r})"
        )
    payload["http_status"] = int(http_status)
    return payload


def _default_sink(line: str) -> None:
    sys.stdout.write(line)


def emit(
    *,
    outcome: str,
    reason: str | None = None,
    http_status: int | None = None,
    timestamp: str | None = None,
    sink: WriteSink | None = None,
) -> bool:
    """Build and write exactly one JSON line to ``sink``.

    The function NEVER raises. Validation, serialization and sink
    write errors are swallowed so the surrounding business request
    keeps its documented behavior. ``sink`` defaults to writing to
    ``sys.stdout``; tests pass a custom callable that records the
    line in memory.

    The function returns ``True`` when the event was written and
    ``False`` otherwise. The return value exists for tests and
    must not be used to drive a retry or to abort the request.
    """
    try:
        payload = build_payload(
            outcome=outcome,
            reason=reason,
            http_status=http_status,
            timestamp=timestamp,
        )
    except InboundOutcomeEventError:
        return False

    try:
        line = (
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        )
    except (TypeError, ValueError):
        return False

    writer = sink if sink is not None else _default_sink
    try:
        writer(line)
    except (OSError, ValueError, TypeError):
        return False
    return True


__all__ = [
    "COMPONENT",
    "EVENT_NAME",
    "OUTCOMES",
    "OUTCOME_ACCEPTED",
    "OUTCOME_DUPLICATE",
    "OUTCOME_REJECTED",
    "OUTCOME_UNREACHABLE",
    "REASONS",
    "REASON_CHANNEL_COMMERCE_MISMATCH",
    "REASON_CORE_HTTP_FAILURE",
    "REASON_CORE_INVALID_RESPONSE",
    "REASON_INVALID_CONTEXT",
    "REASON_INVALID_FORM",
    "REASON_MISSING_COMERCIO_ID",
    "REASON_SHARED_CHANNEL_NOT_SUPPORTED",
    "REASON_SIGNATURE_REJECTED",
    "REASON_UNAVAILABLE_COMMERCE",
    "REASON_UNKNOWN_CLIENT",
    "REASON_UNKNOWN_DESTINATION",
    "SCHEMA_VERSION",
    "InboundOutcomeEventError",
    "build_payload",
    "emit",
]