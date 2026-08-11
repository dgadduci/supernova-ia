"""Privacy-safe versioned operational event schema and emitter.

The module owns the single shared operational event contract used by
the provider worker, outbound dispatch, Twilio callback, LLM/Ollama
and database technical boundary. Every event is a single JSON line
on stdout and only contains allowlisted, reversible-free metadata.

The contract is enforced by :func:`build_event` / :func:`emit_event`:
callers supply a small typed mapping and any unknown field, missing
required field, unsafe string or out-of-range numeric is rejected
before emission. :func:`emit_event` also defends against formatter
failures by swallowing the error and writing a single safe
``observability_emit_failed`` event so a bad call never crashes the
surrounding business flow.

The format is intentionally simple: nothing in the event payload is
a sensitive customer/business value. The contract forbids:

* customer message text, E.164 addresses, provider SIDs, signatures,
  credentials, tokens, signed URLs, provider payloads, LLM prompts,
  LLM responses, raw exception messages, tracebacks.

The caller is responsible for picking the safe identifier at the
emission point. The helper does not scrub free-form strings; it only
validates shape and ranges.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = 1


COMPONENT_OUTBOUND = "outbound_dispatch"
COMPONENT_CALLBACK = "twilio_callback"
COMPONENT_WORKER = "provider_worker"
COMPONENT_LLM = "query_llm"
COMPONENT_EMBEDDING = "embedding_client"
COMPONENT_DATABASE = "database_technical_boundary"


EVENT_OUTBOUND_OUTCOME = "outbound_attempt_outcome"
EVENT_CALLBACK_OUTCOME = "twilio_callback_outcome"
EVENT_WORKER_CYCLE = "provider_worker_cycle"
EVENT_WORKER_UNEXPECTED_FAILURE = "provider_worker_unexpected_failure"
EVENT_WORKER_READINESS_TRANSITION = "provider_worker_readiness_transition"
EVENT_WORKER_DISABLED = "provider_worker_disabled"
EVENT_LLM_REQUEST = "llm_request"
EVENT_EMBEDDING_REQUEST = "embedding_request"
EVENT_DATABASE_TECHNICAL_FAILURE = "database_technical_failure"


_EVENT_CATALOGUE: dict[str, str] = {
    EVENT_OUTBOUND_OUTCOME: COMPONENT_OUTBOUND,
    EVENT_CALLBACK_OUTCOME: COMPONENT_CALLBACK,
    EVENT_WORKER_CYCLE: COMPONENT_WORKER,
    EVENT_WORKER_UNEXPECTED_FAILURE: COMPONENT_WORKER,
    EVENT_WORKER_READINESS_TRANSITION: COMPONENT_WORKER,
    EVENT_WORKER_DISABLED: COMPONENT_WORKER,
    EVENT_LLM_REQUEST: COMPONENT_LLM,
    EVENT_EMBEDDING_REQUEST: COMPONENT_EMBEDDING,
    EVENT_DATABASE_TECHNICAL_FAILURE: COMPONENT_DATABASE,
}


_OUTCOMES_BY_EVENT: dict[str, frozenset[str]] = {
    EVENT_OUTBOUND_OUTCOME: frozenset(
        {"accepted", "retryable", "terminal", "no_due_row", "late_acceptance"}
    ),
    EVENT_CALLBACK_OUTCOME: frozenset(
        {"applied", "duplicate", "unknown", "regression"}
    ),
    EVENT_WORKER_CYCLE: frozenset(
        {"completed", "skipped_inbound_not_ready"}
    ),
    EVENT_WORKER_READINESS_TRANSITION: frozenset({"ready", "not_ready"}),
    EVENT_WORKER_DISABLED: frozenset({"disabled"}),
    EVENT_LLM_REQUEST: frozenset({"started", "completed"}),
    EVENT_EMBEDDING_REQUEST: frozenset({"started", "completed"}),
}


_FAILURE_CATEGORIES_BY_EVENT: dict[str, frozenset[str]] = {
    EVENT_OUTBOUND_OUTCOME: frozenset(
        {
            "retryable_timeout",
            "retryable_429",
            "retryable_5xx",
            "terminal_4xx",
            "budget_exhausted",
        }
    ),
    EVENT_WORKER_UNEXPECTED_FAILURE: frozenset(
        {"worker_exception", "readiness_probe_exception"}
    ),
    EVENT_LLM_REQUEST: frozenset(
        {"timeout", "connection", "http_error", "response_error", "unexpected"}
    ),
    EVENT_EMBEDDING_REQUEST: frozenset(
        {"timeout", "connection", "http_error", "response_error", "unexpected"}
    ),
    EVENT_DATABASE_TECHNICAL_FAILURE: frozenset(
        {"connection", "integrity", "operational", "unexpected"}
    ),
}


_OPTIONAL_FIELDS_BY_EVENT: dict[str, frozenset[str]] = {
    EVENT_OUTBOUND_OUTCOME: frozenset(
        {"outbox_id", "attempt", "durable_state", "provider_code", "exception_type"}
    ),
    EVENT_CALLBACK_OUTCOME: frozenset({"outbox_id", "durable_state"}),
    EVENT_WORKER_CYCLE: frozenset({"elapsed_ms"}),
    EVENT_WORKER_UNEXPECTED_FAILURE: frozenset({"exception_type"}),
    EVENT_WORKER_READINESS_TRANSITION: frozenset({"elapsed_ms"}),
    EVENT_WORKER_DISABLED: frozenset(),
    EVENT_LLM_REQUEST: frozenset({"elapsed_ms", "http_status", "exception_type"}),
    EVENT_EMBEDDING_REQUEST: frozenset(
        {"elapsed_ms", "http_status", "exception_type"}
    ),
    EVENT_DATABASE_TECHNICAL_FAILURE: frozenset({"exception_type"}),
}


_ALLOWED_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {
        "event",
        "schema_version",
        "component",
        "timestamp",
        "outcome",
        "failure_category",
        "outbox_id",
        "correlation_id",
        "attempt",
        "durable_state",
        "provider_code",
        "http_status",
        "exception_type",
        "elapsed_ms",
    }
)


_MAX_STR = 128
_MAX_DURABLE_STATE = 32
_MAX_PROVIDER_CODE = 32
_MAX_CORRELATION_ID = 64
_MAX_HTTP_STATUS = 599
_MAX_EVENT_NAME = 64
_MAX_COMPONENT = 64
_MAX_OUTCOME = 32
_MAX_FAILURE_CATEGORY = 32
_MAX_ELAPSED_MS = 24 * 60 * 60 * 1000


class EventValidationError(ValueError):
    """Raised when a caller tries to build or emit an event that
    fails the catalogued contract."""


def _is_safe_short_string(value: Any, *, max_length: int) -> bool:
    if not isinstance(value, str):
        return False
    if len(value) == 0 or len(value) > max_length:
        return False
    return not any(ord(c) < 0x20 or ord(c) == 0x7F for c in value)


def _is_safe_event_name(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if len(value) == 0 or len(value) > _MAX_EVENT_NAME:
        return False
    if not value.replace("_", "").isalnum():
        return False
    return any(c.isalpha() for c in value)


def _is_safe_component(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return 0 < len(value) <= _MAX_COMPONENT and value.replace("_", "").isalnum()


def _is_safe_durable_state(value: Any) -> bool:
    if not _is_safe_short_string(value, max_length=_MAX_DURABLE_STATE):
        return False
    return value == value.lower()


def _is_safe_outcome_token(value: Any) -> bool:
    return _is_safe_short_string(value, max_length=_MAX_OUTCOME)


def _is_safe_failure_category_token(value: Any) -> bool:
    return _is_safe_short_string(value, max_length=_MAX_FAILURE_CATEGORY)


def _is_safe_optional_field(name: str, value: Any) -> bool:
    if name == "outbox_id":
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        return value >= 0
    if name == "attempt":
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        return value >= 0
    if name == "elapsed_ms":
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        return 0 <= value <= _MAX_ELAPSED_MS
    if name == "http_status":
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        return 100 <= value <= _MAX_HTTP_STATUS
    if name == "provider_code":
        return _is_safe_short_string(value, max_length=_MAX_PROVIDER_CODE)
    if name == "durable_state":
        return _is_safe_durable_state(value)
    if name == "exception_type":
        if not _is_safe_short_string(value, max_length=_MAX_STR):
            return False
        if "." in value or " " in value:
            return False
        return value[:1].isalpha() or value[:1] == "_"
    if name == "correlation_id":
        return _is_safe_short_string(value, max_length=_MAX_CORRELATION_ID)
    return False


def _validate_outcome(event: str, outcome: Any) -> None:
    allowed = _OUTCOMES_BY_EVENT.get(event)
    if allowed is None:
        raise EventValidationError(
            f"event {event!r} does not accept outcome"
        )
    if not _is_safe_outcome_token(outcome):
        raise EventValidationError(
            f"outcome must be a short alnum token (got {outcome!r})"
        )
    if outcome not in allowed:
        raise EventValidationError(
            f"outcome {outcome!r} not in catalogued allowlist for event {event!r}"
        )


def _validate_failure_category(event: str, failure_category: Any) -> None:
    allowed = _FAILURE_CATEGORIES_BY_EVENT.get(event)
    if allowed is None:
        raise EventValidationError(
            f"event {event!r} does not accept failure_category"
        )
    if not _is_safe_failure_category_token(failure_category):
        raise EventValidationError(
            "failure_category must be a short alnum token (got "
            f"{failure_category!r})"
        )
    if failure_category not in allowed:
        raise EventValidationError(
            f"failure_category {failure_category!r} not in catalogued "
            f"allowlist for event {event!r}"
        )


def build_event(
    *,
    event: str,
    component: str,
    outcome: str | None = None,
    failure_category: str | None = None,
    timestamp: str | None = None,
    outbox_id: int | None = None,
    correlation_id: str | None = None,
    attempt: int | None = None,
    durable_state: str | None = None,
    provider_code: str | None = None,
    http_status: int | None = None,
    exception_type: str | None = None,
    elapsed_ms: int | None = None,
) -> dict[str, Any]:
    """Validate the input and return the JSON-ready payload.

    The function is pure: it does not emit anything; it only
    constructs the payload. :func:`emit_event` wraps this and routes
    the serialized payload to the supplied stream.
    """
    if not _is_safe_event_name(event):
        raise EventValidationError(f"invalid event name: {event!r}")
    catalogued_component = _EVENT_CATALOGUE.get(event)
    if catalogued_component is None:
        raise EventValidationError(
            f"event {event!r} is not in the catalogued allowlist"
        )
    if not _is_safe_component(component):
        raise EventValidationError(f"invalid component: {component!r}")
    if component != catalogued_component:
        raise EventValidationError(
            f"event {event!r} requires component {catalogued_component!r}, "
            f"got {component!r}"
        )

    if outcome is None and failure_category is None:
        raise EventValidationError(
            "event must declare exactly one of outcome or failure_category"
        )
    if outcome is not None and failure_category is not None:
        raise EventValidationError(
            "event must declare exactly one of outcome or failure_category, "
            "not both"
        )
    if outcome is not None:
        _validate_outcome(event, outcome)
    else:
        _validate_failure_category(event, failure_category)

    has_outcome = outcome is not None

    payload: dict[str, Any] = {
        "event": event,
        "schema_version": int(SCHEMA_VERSION),
        "component": component,
        "timestamp": (
            timestamp if timestamp is not None
            else datetime.now(tz=timezone.utc).isoformat()
        ),
    }
    if has_outcome:
        payload["outcome"] = outcome
    else:
        payload["failure_category"] = failure_category

    allowed_optional = _OPTIONAL_FIELDS_BY_EVENT.get(event, frozenset())
    optional_values: dict[str, Any] = {
        "outbox_id": outbox_id,
        "correlation_id": correlation_id,
        "attempt": attempt,
        "durable_state": durable_state,
        "provider_code": provider_code,
        "http_status": http_status,
        "exception_type": exception_type,
        "elapsed_ms": elapsed_ms,
    }
    for field_name, value in optional_values.items():
        if value is None:
            continue
        if field_name not in allowed_optional:
            raise EventValidationError(
                f"field {field_name!r} is not catalogued for event {event!r}"
            )
        if not _is_safe_optional_field(field_name, value):
            raise EventValidationError(
                f"invalid value for field {field_name!r}: {value!r}"
            )
        payload[field_name] = value

    return payload


def parse_event(line: str) -> dict[str, Any]:
    """Parse a single JSON line and validate it round-trips through
    the catalogue.

    The parser is used by the Railway query CLI to reject any line
    that is not a known structured event. Lines that fail JSON
    decoding, that decode to a non-object, that carry unknown keys,
    that carry the wrong schema_version or that fail the catalogue
    raise :class:`EventValidationError`. The CLI converts that into
    a safe parse-failure category without printing the raw line.
    """
    if not isinstance(line, str):
        raise EventValidationError("event must be a string")
    stripped = line.strip()
    if not stripped:
        raise EventValidationError("event line is empty")
    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise EventValidationError(
            f"event line is not valid JSON: {type(exc).__name__}"
        ) from exc
    if not isinstance(decoded, dict):
        raise EventValidationError("event line must decode to a JSON object")
    unknown_keys = set(decoded.keys()) - _ALLOWED_PAYLOAD_KEYS
    if unknown_keys:
        raise EventValidationError(
            f"event line carries unknown keys: {sorted(unknown_keys)}"
        )

    event_name = decoded.get("event")
    component = decoded.get("component")
    schema_version = decoded.get("schema_version")
    timestamp = decoded.get("timestamp")
    outcome = decoded.get("outcome")
    failure_category = decoded.get("failure_category")

    if not isinstance(event_name, str):
        raise EventValidationError("event field missing or non-string")
    if not isinstance(component, str):
        raise EventValidationError("component field missing or non-string")
    if schema_version != int(SCHEMA_VERSION):
        raise EventValidationError(
            f"unsupported schema_version: {schema_version!r}"
        )
    if timestamp is not None and not isinstance(timestamp, str):
        raise EventValidationError("timestamp must be a string when present")
    if outcome is not None and not isinstance(outcome, str):
        raise EventValidationError("outcome must be a string when present")
    if failure_category is not None and not isinstance(
        failure_category, str
    ):
        raise EventValidationError(
            "failure_category must be a string when present"
        )

    return build_event(
        event=event_name,
        component=component,
        outcome=outcome,
        failure_category=failure_category,
        timestamp=timestamp if isinstance(timestamp, str) else None,
        outbox_id=decoded.get("outbox_id"),
        correlation_id=decoded.get("correlation_id"),
        attempt=decoded.get("attempt"),
        durable_state=decoded.get("durable_state"),
        provider_code=decoded.get("provider_code"),
        http_status=decoded.get("http_status"),
        exception_type=decoded.get("exception_type"),
        elapsed_ms=decoded.get("elapsed_ms"),
    )


def categorize_sqlalchemy_error(exc: BaseException) -> str:
    """Map a SQLAlchemy exception type to a safe failure_category.

    The function inspects the exception class name only; it never
    reads the message or any payload. ``OperationalError``,
    ``DBAPIError`` and connection-like interfaces resolve to
    ``connection``; ``IntegrityError`` resolves to ``integrity``;
    any other typed error resolves to ``operational``; an unrelated
    exception type resolves to ``unexpected`` so the operational
    surface stays bounded.
    """
    name = type(exc).__name__
    if name in (
        "OperationalError",
        "DBAPIError",
        "InterfaceError",
        "ConnectionError",
        "DisconnectionError",
        "TimeoutError",
        "WaitTimeoutError",
    ):
        return "connection"
    if name == "IntegrityError":
        return "integrity"
    if name == "SQLAlchemyError":
        return "operational"
    return "unexpected"


def emit_event(
    *,
    event: str,
    component: str,
    outcome: str | None = None,
    failure_category: str | None = None,
    timestamp: str | None = None,
    outbox_id: int | None = None,
    correlation_id: str | None = None,
    attempt: int | None = None,
    durable_state: str | None = None,
    provider_code: str | None = None,
    http_status: int | None = None,
    exception_type: str | None = None,
    elapsed_ms: int | None = None,
    stream: Any = None,
) -> bool:
    """Build and emit a single JSON event line to the supplied stream.

    Returns ``True`` when the event was emitted and ``False`` when
    validation failed. Validation failures NEVER raise and NEVER
    mutate business state - the caller is expected to keep its
    transaction / lease / retry semantics intact. The only side
    effect on failure is one safe degraded event written to the
    same stream so the operator can see the helper itself is
    misconfigured.

    ``stream`` defaults to ``sys.stdout``; tests pass a ``StringIO``
    to capture and assert.
    """
    sink = stream if stream is not None else sys.stdout
    try:
        payload = build_event(
            event=event,
            component=component,
            outcome=outcome,
            failure_category=failure_category,
            timestamp=timestamp,
            outbox_id=outbox_id,
            correlation_id=correlation_id,
            attempt=attempt,
            durable_state=durable_state,
            provider_code=provider_code,
            http_status=http_status,
            exception_type=exception_type,
            elapsed_ms=elapsed_ms,
        )
    except EventValidationError as exc:
        degraded = {
            "event": "observability_emit_failed",
            "schema_version": int(SCHEMA_VERSION),
            "component": (
                component if _is_safe_component(component) else "unknown"
            ),
            "failure_category": "validation",
            "exception_type": type(exc).__name__,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }
        try:
            sink.write(
                json.dumps(degraded, sort_keys=True, separators=(",", ":"))
                + "\n"
            )
        except (OSError, ValueError, TypeError):
            # Defensive: the formatter must never crash the surrounding
            # business flow, even if the destination stream is broken.
            return False
        return False

    try:
        sink.write(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        )
    except (OSError, ValueError, TypeError):
        return False
    return True


__all__ = [
    "COMPONENT_CALLBACK",
    "COMPONENT_DATABASE",
    "COMPONENT_EMBEDDING",
    "COMPONENT_LLM",
    "COMPONENT_OUTBOUND",
    "COMPONENT_WORKER",
    "EVENT_CALLBACK_OUTCOME",
    "EVENT_DATABASE_TECHNICAL_FAILURE",
    "EVENT_EMBEDDING_REQUEST",
    "EVENT_LLM_REQUEST",
    "EVENT_OUTBOUND_OUTCOME",
    "EVENT_WORKER_CYCLE",
    "EVENT_WORKER_DISABLED",
    "EVENT_WORKER_READINESS_TRANSITION",
    "EVENT_WORKER_UNEXPECTED_FAILURE",
    "SCHEMA_VERSION",
    "EventValidationError",
    "build_event",
    "categorize_sqlalchemy_error",
    "emit_event",
    "parse_event",
]
