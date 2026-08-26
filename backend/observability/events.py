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
COMPONENT_PRODUCT_RECOGNITION = "product_recognition"
COMPONENT_OBSERVABILITY = "observability_helper"
COMPONENT_PENDING_CONTEXT = "pending_context"
COMPONENT_PRODUCT_ADD_EXECUTION = "product_add_execution"
COMPONENT_OUTBOUND_STYLE = "outbound_styler"
COMPONENT_COMMERCE_INSTALLATION_INGRESS = "commerce_installation_ingress"
COMPONENT_COMMERCE_INSTALLATION_ADAPTER = "commerce_installation_adapter"
COMPONENT_TWILIO_EMULATOR = "twilio_emulator"
COMPONENT_ADMIN_PILOT_EMULATOR = "admin_pilot_emulator"


EVENT_OUTBOUND_OUTCOME = "outbound_attempt_outcome"
EVENT_CALLBACK_OUTCOME = "twilio_callback_outcome"
EVENT_WORKER_CYCLE = "provider_worker_cycle"
EVENT_WORKER_LIVENESS = "provider_worker_liveness"
EVENT_WORKER_UNEXPECTED_FAILURE = "provider_worker_unexpected_failure"
EVENT_WORKER_READINESS_TRANSITION = "provider_worker_readiness_transition"
EVENT_WORKER_DISABLED = "provider_worker_disabled"
EVENT_LLM_REQUEST = "llm_request"
EVENT_LLM_REQUEST_TRANSPORT_PHASE = "llm_request_transport_phase"
EVENT_EMBEDDING_REQUEST = "embedding_request"
EVENT_DATABASE_TECHNICAL_FAILURE = "database_technical_failure"
EVENT_SHADOW_PRODUCT_RECOGNITION = "shadow_product_recognition"
EVENT_OBSERVABILITY_EMIT_FAILED = "observability_emit_failed"
EVENT_PENDING_CONTEXT_TRANSITION = "pending_context_transition"
EVENT_PRODUCT_ADD_EXECUTION = "product_add_execution"
EVENT_OUTBOUND_STYLE = "outbound_style_attempt"
EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME = (
    "commerce_installation_inbound_outcome"
)
EVENT_TWILIO_EMULATOR_OUTBOUND_OUTCOME = "twilio_emulator_outbound_outcome"
EVENT_ADMIN_PILOT_EMULATOR_OUTCOME = "admin_pilot_emulator_outcome"
EVENT_PROCESSING_OUTCOME = "provider_inbound_processing_outcome"
EVENT_PROVIDER_INBOUND_STAGE = "provider_inbound_stage"


# ``EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME`` is emitted by BOTH
# the core isolated ingress router and the T-C adapter so Railway
# operators can grep both services with the same event name. The
# adapter does NOT import ``backend.*``; it builds its JSON line
# locally and only the catalogue rule accepts the bounded adapter
# component alongside the core component.
_EVENT_CATALOGUE: dict[str, str | frozenset[str]] = {
    EVENT_OUTBOUND_OUTCOME: COMPONENT_OUTBOUND,
    EVENT_CALLBACK_OUTCOME: COMPONENT_CALLBACK,
    EVENT_WORKER_CYCLE: COMPONENT_WORKER,
    EVENT_WORKER_LIVENESS: COMPONENT_WORKER,
    EVENT_WORKER_UNEXPECTED_FAILURE: COMPONENT_WORKER,
    EVENT_WORKER_READINESS_TRANSITION: COMPONENT_WORKER,
    EVENT_WORKER_DISABLED: COMPONENT_WORKER,
    EVENT_LLM_REQUEST: COMPONENT_LLM,
    EVENT_LLM_REQUEST_TRANSPORT_PHASE: COMPONENT_LLM,
    EVENT_EMBEDDING_REQUEST: COMPONENT_EMBEDDING,
    EVENT_DATABASE_TECHNICAL_FAILURE: COMPONENT_DATABASE,
    EVENT_SHADOW_PRODUCT_RECOGNITION: COMPONENT_PRODUCT_RECOGNITION,
    EVENT_OBSERVABILITY_EMIT_FAILED: COMPONENT_OBSERVABILITY,
    EVENT_PENDING_CONTEXT_TRANSITION: COMPONENT_PENDING_CONTEXT,
    EVENT_PRODUCT_ADD_EXECUTION: COMPONENT_PRODUCT_ADD_EXECUTION,
    EVENT_OUTBOUND_STYLE: COMPONENT_OUTBOUND_STYLE,
    EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME: frozenset(
        {
            COMPONENT_COMMERCE_INSTALLATION_INGRESS,
            COMPONENT_COMMERCE_INSTALLATION_ADAPTER,
        }
    ),
    EVENT_TWILIO_EMULATOR_OUTBOUND_OUTCOME: COMPONENT_TWILIO_EMULATOR,
    EVENT_ADMIN_PILOT_EMULATOR_OUTCOME: COMPONENT_ADMIN_PILOT_EMULATOR,
    EVENT_PROCESSING_OUTCOME: COMPONENT_WORKER,
    EVENT_PROVIDER_INBOUND_STAGE: COMPONENT_WORKER,
}


# Closed reason allowlist for the
# ``commerce_installation_inbound_outcome`` event. The vocabulary is
# the same on both edges so Railway operators can group failures
# without parsing free-form text. The contract forbids arbitrary
# reason tokens, identifiers, body fragments, exception types or
# provider codes.
_COMMERCE_INSTALLATION_REASONS: frozenset[str] = frozenset(
    {
        "signature_rejected",
        "invalid_form",
        "missing_comercio_id",
        "core_http_failure",
        "core_invalid_response",
        "unknown_destination",
        "shared_channel_not_supported",
        "channel_commerce_mismatch",
        "unknown_client",
        "unavailable_commerce",
        "invalid_context",
    }
)


# Pending-context observation allowlists (closed, sanitized). Every
# ``pending_context_transition`` event MUST declare exactly the six
# documented fields; ``context_kind`` and the ``status_before`` /
# ``status_after`` pair are restricted to closed allowlists derived
# from the supported pending contexts and the
# ``ProcessedIntent.status`` literal type. The candidate counts are
# bounded non-negative integers (0..200) and ``context_cleared`` is a
# strict boolean. The contract intentionally forbids free-form
# identifiers, IDs, names, labels, prompt or model payloads,
# exceptions or correlation fields.
_PENDING_CONTEXT_KINDS: frozenset[str] = frozenset(
    {
        "product_selection",
        "order_line_selection",
        "product_modification",
        "order_clear_confirmation",
    }
)
_PENDING_CONTEXT_STATUSES: frozenset[str] = frozenset(
    {
        "pending_resolution",
        "ready",
        "executed",
        "rejected",
        "failed",
    }
)
_PENDING_CONTEXT_OUTCOMES: frozenset[str] = frozenset(
    {
        "pending_preserved",
        "ready_executed",
        "rejected_cleared",
        "status_interrupted",
        "invalid_state_cleared",
    }
)

# Per-outcome constraints for ``invalid_state_cleared``: the dispatcher
# surfaces the persisted ``context_type`` when it is a supported kind,
# admits the ``none`` / ``unsupported`` sentinels only when the
# persisted value is empty or unknown, and pins ``status_after`` to
# ``rejected``. Other outcomes retain the previous, narrower allowlists
# (no ``none`` / ``unsupported`` sentinels).
_INVALID_STATE_CLEARED_CONTEXT_KINDS: frozenset[str] = frozenset(
    _PENDING_CONTEXT_KINDS | {"none", "unsupported"}
)
_INVALID_STATE_CLEARED_STATUS_BEFORE: frozenset[str] = frozenset(
    _PENDING_CONTEXT_STATUSES | {"none"}
)
_INVALID_STATE_CLEARED_STATUS_AFTER: frozenset[str] = frozenset({"rejected"})


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
    EVENT_WORKER_LIVENESS: frozenset(
        {
            "cycle_started",
            "phase_started",
            "phase_completed",
            "phase_failed",
            "cycle_completed",
        }
    ),
    EVENT_WORKER_READINESS_TRANSITION: frozenset({"ready", "not_ready"}),
    EVENT_WORKER_DISABLED: frozenset({"disabled"}),
    EVENT_LLM_REQUEST: frozenset({"started", "completed"}),
    EVENT_EMBEDDING_REQUEST: frozenset({"started", "completed"}),
    EVENT_PENDING_CONTEXT_TRANSITION: _PENDING_CONTEXT_OUTCOMES,
    EVENT_PRODUCT_ADD_EXECUTION: frozenset(
        {
            "created",
            "incremented",
            "rejected_invalid_input",
            "rejected_session_or_pedido",
            "rejected_not_editable",
            "rejected_missing_presentation",
            "rejected_price_unavailable",
        }
    ),
    EVENT_OUTBOUND_STYLE: frozenset(
        {"not_attempted", "applied", "fallback"}
    ),
    EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME: frozenset(
        {"accepted", "duplicate", "rejected", "unreachable"}
    ),
    EVENT_TWILIO_EMULATOR_OUTBOUND_OUTCOME: frozenset(
        {"accepted", "rejected"}
    ),
    EVENT_ADMIN_PILOT_EMULATOR_OUTCOME: frozenset(
        {"submitted", "rejected", "unavailable"}
    ),
    EVENT_PROCESSING_OUTCOME: frozenset(
        {
            "processed_with_response",
            "processed_without_response",
            "retry_scheduled",
            "failed_terminal",
            "lease_lost",
            "unavailable",
        }
    ),
    EVENT_PROVIDER_INBOUND_STAGE: frozenset(
        {"started", "completed", "failed"}
    ),
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
    EVENT_WORKER_LIVENESS: frozenset({"worker_exception"}),
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
    EVENT_OBSERVABILITY_EMIT_FAILED: frozenset(
        {"validation", "internal"}
    ),
    EVENT_OUTBOUND_STYLE: frozenset(
        {
            "timeout",
            "connection",
            "http_error",
            "response_error",
            "malformed_batch",
            "wrapper_invalid",
            "wrapper_claim_guard",
            "wrapper_shape_invalid",
            "empty_wrapper",
            "unexpected",
        }
    ),
    EVENT_PROCESSING_OUTCOME: frozenset(
        {
            "pipeline_error",
            "database_error",
            "budget_exhausted",
            "terminal_processor_error",
            "unavailable_commerce",
        }
    ),
}


# Recognition observation allowlists (closed, sanitized). The
# ``shadow_product_recognition`` event is an observation: hybrid
# ``unique`` / ``ambiguous`` / ``unknown`` are valid business
# outcomes, NEVER technical fallback. Only existing sanitized
# technical categories plus ``invalid_mode`` may mark fallback.
_RECOGNITION_CONFIGURED_MODES: frozenset[str] = frozenset(
    {"fuzzy", "shadow", "hybrid_authoritative", "invalid_mode"}
)
_RECOGNITION_EFFECTIVE_MODES: frozenset[str] = frozenset(
    {"fuzzy", "shadow", "hybrid_authoritative"}
)
_RECOGNITION_AUTHORITATIVE_STRATEGIES: frozenset[str] = frozenset(
    {"fuzzy", "hybrid"}
)
_RECOGNITION_HYBRID_DECISIONS: frozenset[str] = frozenset(
    {"unique", "ambiguous", "unknown", "not_evaluated"}
)
_RECOGNITION_FALLBACK_CATEGORIES: frozenset[str] = frozenset(
    {
        "embedding_failure",
        "vector_failure",
        "malformed_response",
        "unexpected_technical_failure",
        "invalid_mode",
    }
)


_EVENTS_WITHOUT_OUTCOME_OR_FAILURE: frozenset[str] = frozenset(
    {EVENT_SHADOW_PRODUCT_RECOGNITION, EVENT_LLM_REQUEST_TRANSPORT_PHASE}
)
_EVENTS_WITH_RECOGNITION_FIELDS: frozenset[str] = frozenset(
    {EVENT_SHADOW_PRODUCT_RECOGNITION}
)
_EVENTS_WITH_PENDING_CONTEXT_FIELDS: frozenset[str] = frozenset(
    {EVENT_PENDING_CONTEXT_TRANSITION}
)
_EVENTS_WITH_PRODUCT_ADD_FIELDS: frozenset[str] = frozenset(
    {EVENT_PRODUCT_ADD_EXECUTION}
)
_EVENTS_WITH_COMMERCE_INSTALLATION_FIELDS: frozenset[str] = frozenset(
    {EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME}
)


# Closed phase allowlist for the ``provider_worker_liveness`` event.
# The vocabulary is shared between the worker orchestration seam and the
# bounded production-log parser so Railway operators can group cycles by
# the last phase that began. The contract forbids arbitrary phase tokens,
# provider/customers identifiers, runner names or caller-supplied
# labels.
_LIVENESS_PHASES: frozenset[str] = frozenset(
    {
        "readiness",
        "inbound",
        "inbound_runner",
        "outbound",
        "cycle_summary",
        "sleep",
    }
)
_LIVENESS_PHASE_OUTCOMES: frozenset[str] = frozenset(
    {"phase_started", "phase_completed", "phase_failed"}
)
_LIVENESS_CYCLE_OUTCOMES: frozenset[str] = frozenset(
    {"cycle_started", "cycle_completed"}
)


# Closed phase allowlist for the ``llm_request_transport_phase`` event.
# The vocabulary is shared between the existing ``QueryLlm`` boundary
# and the bounded production-log parser so Railway operators can
# determine the last client-side transport phase reached during a
# request/response cycle (Ollama 200 vs client timeout gap). The
# contract forbids arbitrary phase tokens, prompt/response fragments,
# URLs, proxy values, headers, credentials, customer/provider
# identifiers and exception text. The four SOCKS-boundary tokens
# (``socks_connect_started`` / ``socks_connect_completed`` /
# ``request_write_started`` / ``request_write_completed``) are only
# emitted by the QueryLlm-scoped Requests observer when the
# configured ``OLLAMA_PROXY_URL`` selects the SOCKS scheme; they
# never carry ``http_status``, ``response_bytes`` or ``chunk_count``
# because those values are not available at the SOCKS connect and
# HTTP-writer seams and the contract forbids fabrication.
_LLM_REQUEST_TRANSPORT_PHASES: frozenset[str] = frozenset(
    {
        "request_started",
        "socks_connect_started",
        "socks_connect_completed",
        "request_write_started",
        "request_write_completed",
        "response_headers_received",
        "first_body_chunk",
        "body_completed",
        "response_received",
        "json_extracted",
        "result_parsed",
    }
)


_EVENTS_WITH_LIVENESS_FIELDS: frozenset[str] = frozenset(
    {EVENT_WORKER_LIVENESS}
)
_EVENTS_WITH_PROCESSING_OUTCOME_FIELDS: frozenset[str] = frozenset(
    {EVENT_PROCESSING_OUTCOME}
)
_EVENTS_WITH_PROVIDER_INBOUND_STAGE_FIELDS: frozenset[str] = frozenset(
    {EVENT_PROVIDER_INBOUND_STAGE}
)
_EVENTS_WITH_LLM_REQUEST_TRANSPORT_PHASE_FIELDS: frozenset[str] = frozenset(
    {EVENT_LLM_REQUEST_TRANSPORT_PHASE}
)
_PROCESSING_OUTCOME_PROCESSED_VALUES: frozenset[str] = frozenset(
    {"processed_with_response", "processed_without_response"}
)
_PROCESSING_OUTCOME_FAILURE_VALUES: frozenset[str] = frozenset(
    {"retry_scheduled", "failed_terminal", "lease_lost", "unavailable"}
)
_PHASE_ACCEPTING_EVENTS: frozenset[str] = frozenset(
    {EVENT_WORKER_LIVENESS, EVENT_LLM_REQUEST_TRANSPORT_PHASE}
)

# Closed stage allowlist for the ``provider_inbound_stage`` event.
# The vocabulary mirrors the bounded coordinator seams and is
# shared with the production-log parser so Railway operators can
# group one leased inbound turn by the last reached boundary
# without parsing free-form labels. The contract forbids
# arbitrary stage tokens, provider/customer identifiers, runner
# names or caller-supplied labels.
_PROVIDER_INBOUND_STAGE_STAGES: frozenset[str] = frozenset(
    {
        "availability",
        "session_order",
        "business_pipeline",
        "outbound_staging",
        "processing_finalization",
    }
)


_OPTIONAL_FIELDS_BY_EVENT: dict[str, frozenset[str]] = {
    EVENT_OUTBOUND_OUTCOME: frozenset(
        {"outbox_id", "attempt", "durable_state", "provider_code", "exception_type"}
    ),
    EVENT_CALLBACK_OUTCOME: frozenset({"outbox_id", "durable_state"}),
    EVENT_WORKER_CYCLE: frozenset({"elapsed_ms"}),
    EVENT_WORKER_LIVENESS: frozenset(
        {"phase", "cycle_index", "elapsed_ms", "exception_type"}
    ),
    EVENT_WORKER_UNEXPECTED_FAILURE: frozenset({"exception_type"}),
    EVENT_WORKER_READINESS_TRANSITION: frozenset({"elapsed_ms"}),
    EVENT_WORKER_DISABLED: frozenset(),
    EVENT_LLM_REQUEST: frozenset(
        {"elapsed_ms", "http_status", "exception_type", "correlation_id"}
    ),
    EVENT_LLM_REQUEST_TRANSPORT_PHASE: frozenset(
        {
            "phase",
            "elapsed_ms",
            "http_status",
            "response_bytes",
            "chunk_count",
            "correlation_id",
        }
    ),
    EVENT_EMBEDDING_REQUEST: frozenset(
        {"elapsed_ms", "http_status", "exception_type", "correlation_id"}
    ),
    EVENT_DATABASE_TECHNICAL_FAILURE: frozenset({"exception_type"}),
    EVENT_OBSERVABILITY_EMIT_FAILED: frozenset({"exception_type"}),
    EVENT_PENDING_CONTEXT_TRANSITION: frozenset(),
    EVENT_PRODUCT_ADD_EXECUTION: frozenset(),
    EVENT_OUTBOUND_STYLE: frozenset(
        {
            "flavor_code",
            "eligible_count",
            "applied_count",
            "elapsed_ms",
            "exception_type",
            "outbound_style_prompt_template_version",
            "outbound_style_prompt_template_hash",
        }
    ),
    EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME: frozenset(
        {"reason", "http_status"}
    ),
    EVENT_TWILIO_EMULATOR_OUTBOUND_OUTCOME: frozenset({"reason"}),
    EVENT_ADMIN_PILOT_EMULATOR_OUTCOME: frozenset({"reason"}),
    EVENT_PROCESSING_OUTCOME: frozenset(
        {"response_count", "outbox_row_count", "correlation_id"}
    ),
    EVENT_PROVIDER_INBOUND_STAGE: frozenset(
        {"stage", "elapsed_ms", "exception_type", "correlation_id"}
    ),
}


_EMULATOR_REASONS: frozenset[str] = frozenset(
    {
        "auth",
        "invalid",
        "transport",
        "unavailable_commerce",
        "inactive_installation",
        "cross_commerce_mismatch",
        "emulator_disabled",
    }
)


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
        "phase",
        "cycle_index",
        "configured_mode",
        "effective_mode",
        "authoritative_strategy",
        "hybrid_decision",
        "fallback",
        "fallback_category",
        "fuzzy_latency_ms",
        "embedding_latency_ms",
        "vector_latency_ms",
        "context_kind",
        "status_before",
        "status_after",
        "candidate_count_before",
        "candidate_count_after",
        "context_cleared",
        "flavor_code",
        "eligible_count",
        "applied_count",
        "outbound_style_prompt_template_version",
        "outbound_style_prompt_template_hash",
        "reason",
        "response_count",
        "outbox_row_count",
        "stage",
        "response_bytes",
        "chunk_count",
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
_MAX_PENDING_CONTEXT_KIND = 32
_MAX_PENDING_CONTEXT_STATUS = 32
_MAX_PENDING_CONTEXT_CANDIDATE_COUNT = 200
_MAX_TEMPLATE_VERSION = 64
_MAX_SHA256_HEX = 64
_MAX_CYCLE_INDEX = 2**31 - 1
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_MAX_CHUNK_COUNT = 100_000


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
    if name == "phase":
        return _is_safe_short_string(value, max_length=_MAX_OUTCOME) and (
            value in _LIVENESS_PHASES
        )
    if name == "cycle_index":
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        return 1 <= value <= _MAX_CYCLE_INDEX
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
    if name == "flavor_code":
        if not _is_safe_short_string(value, max_length=_MAX_STR):
            return False
        return value == value.lower() and any(c.isalnum() for c in value)
    if name == "eligible_count":
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        return 0 <= value <= _MAX_PENDING_CONTEXT_CANDIDATE_COUNT
    if name == "applied_count":
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        return 0 <= value <= _MAX_PENDING_CONTEXT_CANDIDATE_COUNT
    if name == "outbound_style_prompt_template_version":
        if not isinstance(value, str):
            return False
        if len(value) == 0 or len(value) > _MAX_TEMPLATE_VERSION:
            return False
        if any(ord(c) < 0x20 or ord(c) == 0x7F for c in value):
            return False
        allowed_chars = set("abcdefghijklmnopqrstuvwxyz0123456789-_./")
        return all(c in allowed_chars for c in value) and any(
            c.isalpha() for c in value
        )
    if name == "outbound_style_prompt_template_hash":
        if not isinstance(value, str):
            return False
        if len(value) != _MAX_SHA256_HEX:
            return False
        return all(c in "0123456789abcdef" for c in value)
    if name == "reason":
        if not isinstance(value, str):
            return False
        if len(value) == 0 or len(value) > _MAX_STR:
            return False
        if value in _COMMERCE_INSTALLATION_REASONS:
            return True
        return value in _EMULATOR_REASONS
    if name == "response_count":
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        return 0 <= value <= _MAX_PENDING_CONTEXT_CANDIDATE_COUNT
    if name == "outbox_row_count":
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        return 0 <= value <= _MAX_PENDING_CONTEXT_CANDIDATE_COUNT
    if name == "response_bytes":
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        return 0 <= value <= _MAX_RESPONSE_BYTES
    if name == "chunk_count":
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        return 0 <= value <= _MAX_CHUNK_COUNT
    if name == "stage":
        if not _is_safe_short_string(value, max_length=_MAX_OUTCOME):
            return False
        return value in _PROVIDER_INBOUND_STAGE_STAGES
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


def _is_safe_recognition_mode_token(value: Any) -> bool:
    return _is_safe_short_string(value, max_length=_MAX_OUTCOME)


def _is_safe_recognition_strategy_token(value: Any) -> bool:
    return _is_safe_short_string(value, max_length=_MAX_OUTCOME)


def _is_safe_recognition_decision_token(value: Any) -> bool:
    return _is_safe_short_string(value, max_length=_MAX_OUTCOME)


def _is_safe_recognition_fallback_category_token(value: Any) -> bool:
    return _is_safe_short_string(value, max_length=_MAX_FAILURE_CATEGORY)


def _is_safe_recognition_latency_ms(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return 0 <= value <= _MAX_ELAPSED_MS


def _validate_recognition_event_fields(
    *,
    configured_mode: Any,
    effective_mode: Any,
    authoritative_strategy: Any,
    hybrid_decision: Any,
    fallback: Any,
    fallback_category: Any,
    fuzzy_latency_ms: Any,
    embedding_latency_ms: Any,
    vector_latency_ms: Any,
) -> dict[str, Any]:
    """Validate the closed recognition observation fields.

    Returns the validated field dict. The shape enforces:

    * ``configured_mode``, ``effective_mode``, ``authoritative_strategy``,
      ``hybrid_decision``, ``fallback`` are REQUIRED for the
      ``shadow_product_recognition`` event.
    * ``fallback_category`` is REQUIRED when ``fallback`` is ``True``
      and MUST NOT be present when ``fallback`` is ``False``.
    * ``fuzzy_latency_ms``, ``embedding_latency_ms`` and
      ``vector_latency_ms`` are OPTIONAL and, when present, must be
      bounded non-negative integers.
    """
    fields: dict[str, Any] = {}

    if not _is_safe_recognition_mode_token(configured_mode):
        raise EventValidationError(
            "configured_mode must be a short alnum token "
            f"(got {configured_mode!r})"
        )
    if configured_mode not in _RECOGNITION_CONFIGURED_MODES:
        raise EventValidationError(
            f"configured_mode {configured_mode!r} not in recognition allowlist"
        )
    fields["configured_mode"] = configured_mode

    if not _is_safe_recognition_mode_token(effective_mode):
        raise EventValidationError(
            "effective_mode must be a short alnum token "
            f"(got {effective_mode!r})"
        )
    if effective_mode not in _RECOGNITION_EFFECTIVE_MODES:
        raise EventValidationError(
            f"effective_mode {effective_mode!r} not in recognition allowlist"
        )
    fields["effective_mode"] = effective_mode

    if not _is_safe_recognition_strategy_token(authoritative_strategy):
        raise EventValidationError(
            "authoritative_strategy must be a short alnum token "
            f"(got {authoritative_strategy!r})"
        )
    if authoritative_strategy not in _RECOGNITION_AUTHORITATIVE_STRATEGIES:
        raise EventValidationError(
            f"authoritative_strategy {authoritative_strategy!r} "
            "not in recognition allowlist"
        )
    fields["authoritative_strategy"] = authoritative_strategy

    if not _is_safe_recognition_decision_token(hybrid_decision):
        raise EventValidationError(
            "hybrid_decision must be a short alnum token "
            f"(got {hybrid_decision!r})"
        )
    if hybrid_decision not in _RECOGNITION_HYBRID_DECISIONS:
        raise EventValidationError(
            f"hybrid_decision {hybrid_decision!r} not in recognition allowlist"
        )
    fields["hybrid_decision"] = hybrid_decision

    if not isinstance(fallback, bool):
        raise EventValidationError(
            f"fallback must be a boolean (got {type(fallback).__name__})"
        )
    fields["fallback"] = fallback

    if fallback:
        if not _is_safe_recognition_fallback_category_token(fallback_category):
            raise EventValidationError(
                "fallback_category must be a short alnum token when "
                f"fallback=true (got {fallback_category!r})"
            )
        if fallback_category not in _RECOGNITION_FALLBACK_CATEGORIES:
            raise EventValidationError(
                f"fallback_category {fallback_category!r} "
                "not in recognition allowlist"
            )
        fields["fallback_category"] = fallback_category
    elif fallback_category is not None:
        raise EventValidationError(
            "fallback_category must be absent when fallback=false "
            f"(got {fallback_category!r})"
        )

    for field_name, value in (
        ("fuzzy_latency_ms", fuzzy_latency_ms),
        ("embedding_latency_ms", embedding_latency_ms),
        ("vector_latency_ms", vector_latency_ms),
    ):
        if value is None:
            continue
        if not _is_safe_recognition_latency_ms(value):
            raise EventValidationError(
                f"{field_name} must be a non-negative integer "
                f"<= {_MAX_ELAPSED_MS} (got {value!r})"
            )
        fields[field_name] = value

    return fields


def _validate_pending_context_event_fields(
    *,
    outcome: Any,
    context_kind: Any,
    status_before: Any,
    status_after: Any,
    candidate_count_before: Any,
    candidate_count_after: Any,
    context_cleared: Any,
) -> dict[str, Any]:
    """Validate the closed pending-context observation fields.

    Every ``pending_context_transition`` event MUST carry exactly the
    six documented fields. ``context_kind`` must be one of the four
    closed context kinds, ``status_before`` and ``status_after`` must
    come from the closed ``ProcessedIntent.status`` literal allowlist,
    ``candidate_count_before`` / ``candidate_count_after`` must be
    integers in ``[0, 200]``, and ``context_cleared`` must be a strict
    boolean. The contract intentionally forbids free-form identifiers,
    customer text, labels, prompt or model payloads, exceptions or
    correlation fields; any of those will fail this validator.

    The ``invalid_state_cleared`` outcome admits a wider allowlist for
    ``context_kind`` and ``status_before`` (so the closed ``none`` and
    ``unsupported`` sentinels are surfaced) but pins ``status_after``
    to exactly ``rejected`` so the recovery contract stays closed.
    All other outcomes keep the original narrower allowlists.
    """
    fields: dict[str, Any] = {}

    if outcome == "invalid_state_cleared":
        allowed_kinds = _INVALID_STATE_CLEARED_CONTEXT_KINDS
        allowed_status_before = _INVALID_STATE_CLEARED_STATUS_BEFORE
        allowed_status_after = _INVALID_STATE_CLEARED_STATUS_AFTER
    else:
        allowed_kinds = _PENDING_CONTEXT_KINDS
        allowed_status_before = _PENDING_CONTEXT_STATUSES
        allowed_status_after = _PENDING_CONTEXT_STATUSES

    if not isinstance(context_kind, str) or not context_kind:
        raise EventValidationError(
            "context_kind is required for pending_context_transition "
            f"and must be a non-empty string (got {context_kind!r})"
        )
    if context_kind not in allowed_kinds:
        raise EventValidationError(
            f"context_kind {context_kind!r} not in pending-context allowlist "
            f"{sorted(allowed_kinds)}"
        )
    fields["context_kind"] = context_kind

    if not isinstance(status_before, str) or not status_before:
        raise EventValidationError(
            "status_before is required for pending_context_transition "
            f"and must be a non-empty string (got {status_before!r})"
        )
    if status_before not in allowed_status_before:
        raise EventValidationError(
            f"status_before {status_before!r} not in pending-context status "
            f"allowlist {sorted(allowed_status_before)}"
        )
    fields["status_before"] = status_before

    if not isinstance(status_after, str) or not status_after:
        raise EventValidationError(
            "status_after is required for pending_context_transition "
            f"and must be a non-empty string (got {status_after!r})"
        )
    if status_after not in allowed_status_after:
        raise EventValidationError(
            f"status_after {status_after!r} not in pending-context status "
            f"allowlist {sorted(allowed_status_after)}"
        )
    fields["status_after"] = status_after

    if isinstance(candidate_count_before, bool) or not isinstance(
        candidate_count_before, int
    ):
        raise EventValidationError(
            "candidate_count_before is required for pending_context_transition "
            "and must be an integer in [0, 200] "
            f"(got {type(candidate_count_before).__name__}: {candidate_count_before!r})"
        )
    if not 0 <= candidate_count_before <= _MAX_PENDING_CONTEXT_CANDIDATE_COUNT:
        raise EventValidationError(
            "candidate_count_before must be in [0, "
            f"{_MAX_PENDING_CONTEXT_CANDIDATE_COUNT}] "
            f"(got {candidate_count_before!r})"
        )
    fields["candidate_count_before"] = candidate_count_before

    if isinstance(candidate_count_after, bool) or not isinstance(
        candidate_count_after, int
    ):
        raise EventValidationError(
            "candidate_count_after is required for pending_context_transition "
            "and must be an integer in [0, 200] "
            f"(got {type(candidate_count_after).__name__}: {candidate_count_after!r})"
        )
    if not 0 <= candidate_count_after <= _MAX_PENDING_CONTEXT_CANDIDATE_COUNT:
        raise EventValidationError(
            "candidate_count_after must be in [0, "
            f"{_MAX_PENDING_CONTEXT_CANDIDATE_COUNT}] "
            f"(got {candidate_count_after!r})"
        )
    fields["candidate_count_after"] = candidate_count_after

    if not isinstance(context_cleared, bool):
        raise EventValidationError(
            "context_cleared is required for pending_context_transition "
            f"and must be a boolean (got {type(context_cleared).__name__})"
        )
    fields["context_cleared"] = context_cleared

    return fields


def _validate_commerce_installation_event_fields(
    *,
    outcome: Any,
    reason: Any,
    http_status: Any,
    component: Any,
) -> dict[str, Any]:
    """Validate the closed ``commerce_installation_inbound_outcome``
    payload.

    The contract enforces:

    * ``reason`` is REQUIRED for ``rejected`` and ``unreachable`` and
      MUST come from the closed ``_COMMERCE_INSTALLATION_REASONS``
      allowlist. ``reason`` MUST be ABSENT for ``accepted`` and
      ``duplicate``;
    * ``http_status`` is only allowed on the T-C adapter
      (``commerce_installation_adapter``) ``unreachable`` outcome so
      transport failures can be correlated without leaking PII from
      the core. The core MUST NOT include ``http_status``; it MUST be
      a bounded integer ``[100, 599]`` when present.

    Free-form reason text, sensitive values, identifiers or
    exception types fail this validator.
    """
    fields: dict[str, Any] = {}

    if outcome in {"rejected", "unreachable"}:
        if not isinstance(reason, str):
            raise EventValidationError(
                "reason is required for commerce_installation_inbound_outcome "
                f"with outcome {outcome!r} and must be a string "
                f"(got {type(reason).__name__}: {reason!r})"
            )
        if reason not in _COMMERCE_INSTALLATION_REASONS:
            raise EventValidationError(
                f"reason {reason!r} is not in the catalogued "
                "commerce_installation_inbound_outcome allowlist"
            )
        fields["reason"] = reason
    else:
        if reason is not None:
            raise EventValidationError(
                "reason must be absent for "
                f"commerce_installation_inbound_outcome with outcome "
                f"{outcome!r} (got {reason!r})"
            )

    if http_status is None:
        return fields

    if component != COMPONENT_COMMERCE_INSTALLATION_ADAPTER:
        raise EventValidationError(
            "http_status is only allowed for the T-C adapter component "
            f"({COMPONENT_COMMERCE_INSTALLATION_ADAPTER!r}); got "
            f"component {component!r}"
        )
    if outcome != "unreachable":
        raise EventValidationError(
            "http_status is only allowed for outcome 'unreachable' on "
            f"commerce_installation_inbound_outcome (got {outcome!r})"
        )
    if isinstance(http_status, bool) or not isinstance(http_status, int):
        raise EventValidationError(
            "http_status must be a bounded integer "
            f"(got {type(http_status).__name__}: {http_status!r})"
        )
    if not 100 <= http_status <= _MAX_HTTP_STATUS:
        raise EventValidationError(
            f"http_status must be in [100, {_MAX_HTTP_STATUS}] "
            f"(got {http_status!r})"
        )
    fields["http_status"] = http_status

    return fields


def _validate_liveness_event_fields(
    *,
    outcome: Any,
    phase: Any,
    cycle_index: Any,
) -> dict[str, Any]:
    """Validate the closed ``provider_worker_liveness`` payload.

    The contract enforces:

    * ``cycle_index`` is REQUIRED for every liveness event, must be a
      strictly positive integer bounded by :data:`_MAX_CYCLE_INDEX`,
      and MUST be a process-local counter (never a correlation or
      customer identifier).
    * ``phase`` is REQUIRED for the phase outcomes
      (``phase_started``, ``phase_completed``, ``phase_failed``) and
      MUST come from :data:`_LIVENESS_PHASES`.
    * ``phase`` MUST be ABSENT for the cycle outcomes
      (``cycle_started``, ``cycle_completed``).

    Free-form phase tokens, runner names, customer or provider
    identifiers fail this validator.
    """
    fields: dict[str, Any] = {}

    if cycle_index is None:
        raise EventValidationError(
            "cycle_index is required for provider_worker_liveness "
            "and must be a positive integer"
        )
    if isinstance(cycle_index, bool) or not isinstance(cycle_index, int):
        raise EventValidationError(
            "cycle_index must be an integer in "
            f"[1, {_MAX_CYCLE_INDEX}] "
            f"(got {type(cycle_index).__name__}: {cycle_index!r})"
        )
    if not 1 <= cycle_index <= _MAX_CYCLE_INDEX:
        raise EventValidationError(
            f"cycle_index must be in [1, {_MAX_CYCLE_INDEX}] "
            f"(got {cycle_index!r})"
        )
    fields["cycle_index"] = cycle_index

    if outcome in _LIVENESS_PHASE_OUTCOMES:
        if phase is None:
            raise EventValidationError(
                "phase is required for provider_worker_liveness with "
                f"outcome {outcome!r} and must be one of "
                f"{sorted(_LIVENESS_PHASES)}"
            )
        if not _is_safe_short_string(phase, max_length=_MAX_OUTCOME):
            raise EventValidationError(
                "phase must be a short alnum token (got "
                f"{type(phase).__name__}: {phase!r})"
            )
        if phase not in _LIVENESS_PHASES:
            raise EventValidationError(
                f"phase {phase!r} not in liveness allowlist "
                f"{sorted(_LIVENESS_PHASES)}"
            )
        fields["phase"] = phase
    elif outcome in _LIVENESS_CYCLE_OUTCOMES:
        if phase is not None:
            raise EventValidationError(
                "phase must be absent for provider_worker_liveness "
                f"with outcome {outcome!r} (got {phase!r})"
            )
    else:
        raise EventValidationError(
            f"unknown liveness outcome {outcome!r}"
        )

    return fields


def _validate_provider_inbound_stage_event_fields(
    *,
    outcome: Any,
    stage: Any,
    elapsed_ms: Any,
    exception_type: Any,
    correlation_id: Any,
) -> dict[str, Any]:
    """Validate the closed ``provider_inbound_stage`` payload.

    The contract enforces:

    * ``stage`` is REQUIRED for every provider-inbound-stage event
      and MUST come from :data:`_PROVIDER_INBOUND_STAGE_STAGES`.
    * ``outcome`` is REQUIRED and MUST come from the closed
      ``started`` / ``completed`` / ``failed`` allowlist.
    * ``elapsed_ms`` is REQUIRED for ``completed`` and ``failed``
      and MUST be a bounded non-negative integer; it MUST be
      ABSENT on ``started`` because the boundary has not returned.
    * ``exception_type`` is REQUIRED for ``failed`` and MUST come
      from the catalogued safe exception-type contract; it MUST
      be ABSENT on ``started`` and ``completed``.
    * ``correlation_id`` is OPTIONAL and, when present, MUST be
      the existing opaque provider synthetic identifier (already
      bounded by ``_MAX_CORRELATION_ID``). A missing value is
      permitted only outside the provider-scoped evidence path.
    """
    fields: dict[str, Any] = {}

    if not isinstance(stage, str) or not stage:
        raise EventValidationError(
            "stage is required for provider_inbound_stage "
            "and must be a non-empty string (got "
            f"{type(stage).__name__}: {stage!r})"
        )
    if not _is_safe_short_string(stage, max_length=_MAX_OUTCOME):
        raise EventValidationError(
            "stage must be a short alnum token (got "
            f"{type(stage).__name__}: {stage!r})"
        )
    if stage not in _PROVIDER_INBOUND_STAGE_STAGES:
        raise EventValidationError(
            f"stage {stage!r} not in provider_inbound_stage allowlist "
            f"{sorted(_PROVIDER_INBOUND_STAGE_STAGES)}"
        )
    fields["stage"] = stage

    if outcome == "failed":
        if elapsed_ms is None:
            raise EventValidationError(
                "event 'provider_inbound_stage' with outcome 'failed' "
                "requires 'elapsed_ms'"
            )
        if (
            isinstance(elapsed_ms, bool)
            or not isinstance(elapsed_ms, int)
            or not 0 <= elapsed_ms <= _MAX_ELAPSED_MS
        ):
            raise EventValidationError(
                "elapsed_ms must be in [0, "
                f"{_MAX_ELAPSED_MS}] for provider_inbound_stage "
                f"(got {elapsed_ms!r})"
            )
        fields["elapsed_ms"] = int(elapsed_ms)
        if exception_type is None:
            raise EventValidationError(
                "event 'provider_inbound_stage' with outcome 'failed' "
                "requires 'exception_type'"
            )
        if not _is_safe_optional_field("exception_type", exception_type):
            raise EventValidationError(
                f"invalid value for field 'exception_type': {exception_type!r}"
            )
        fields["exception_type"] = exception_type
    elif outcome == "completed":
        if elapsed_ms is None:
            raise EventValidationError(
                "event 'provider_inbound_stage' with outcome 'completed' "
                "requires 'elapsed_ms'"
            )
        if (
            isinstance(elapsed_ms, bool)
            or not isinstance(elapsed_ms, int)
            or not 0 <= elapsed_ms <= _MAX_ELAPSED_MS
        ):
            raise EventValidationError(
                "elapsed_ms must be in [0, "
                f"{_MAX_ELAPSED_MS}] for provider_inbound_stage "
                f"(got {elapsed_ms!r})"
            )
        fields["elapsed_ms"] = int(elapsed_ms)
        if exception_type is not None:
            raise EventValidationError(
                "event 'provider_inbound_stage' with outcome 'completed' "
                "does not accept 'exception_type'; "
                "'exception_type' is reserved for outcome 'failed'"
            )
    elif outcome == "started":
        if elapsed_ms is not None:
            raise EventValidationError(
                "event 'provider_inbound_stage' with outcome 'started' "
                "does not accept 'elapsed_ms'; "
                "'elapsed_ms' is reserved for completed/failed outcomes"
            )
        if exception_type is not None:
            raise EventValidationError(
                "event 'provider_inbound_stage' with outcome 'started' "
                "does not accept 'exception_type'; "
                "'exception_type' is reserved for outcome 'failed'"
            )
    else:
        raise EventValidationError(
            f"unknown provider_inbound_stage outcome {outcome!r}"
        )

    if correlation_id is not None:
        if not _is_safe_optional_field("correlation_id", correlation_id):
            raise EventValidationError(
                f"invalid value for field 'correlation_id': {correlation_id!r}"
            )
        fields["correlation_id"] = correlation_id

    return fields


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
    configured_mode: str | None = None,
    effective_mode: str | None = None,
    authoritative_strategy: str | None = None,
    hybrid_decision: str | None = None,
    fallback: bool | None = None,
    fallback_category: str | None = None,
    fuzzy_latency_ms: int | None = None,
    embedding_latency_ms: int | None = None,
    vector_latency_ms: int | None = None,
    context_kind: str | None = None,
    status_before: str | None = None,
    status_after: str | None = None,
    candidate_count_before: int | None = None,
    candidate_count_after: int | None = None,
    context_cleared: bool | None = None,
    flavor_code: str | None = None,
    eligible_count: int | None = None,
    applied_count: int | None = None,
    outbound_style_prompt_template_version: str | None = None,
    outbound_style_prompt_template_hash: str | None = None,
    reason: str | None = None,
    phase: str | None = None,
    cycle_index: int | None = None,
    response_count: int | None = None,
    outbox_row_count: int | None = None,
    stage: str | None = None,
    response_bytes: int | None = None,
    chunk_count: int | None = None,
) -> dict[str, Any]:
    """Validate the input and return the JSON-ready payload.

    The function is pure: it does not emit anything; it only
    constructs the payload. :func:`emit_event` wraps this and routes
    the serialized payload to the supplied stream.
    """
    if not _is_safe_event_name(event):
        raise EventValidationError(f"invalid event name: {event!r}")

    if event not in _PHASE_ACCEPTING_EVENTS:
        if phase is not None:
            raise EventValidationError(
                f"event {event!r} does not accept 'phase'; "
                "'phase' is reserved for events in "
                f"{sorted(_PHASE_ACCEPTING_EVENTS)}"
            )
        if cycle_index is not None:
            raise EventValidationError(
                f"event {event!r} does not accept 'cycle_index'; "
                "'cycle_index' is reserved for "
                f"{EVENT_WORKER_LIVENESS!r}"
            )

    catalogued_component = _EVENT_CATALOGUE.get(event)
    if catalogued_component is None:
        raise EventValidationError(
            f"event {event!r} is not in the catalogued allowlist"
        )
    if not _is_safe_component(component):
        raise EventValidationError(f"invalid component: {component!r}")
    if isinstance(catalogued_component, frozenset):
        if component not in catalogued_component:
            raise EventValidationError(
                f"event {event!r} requires one of "
                f"{sorted(catalogued_component)} components, "
                f"got {component!r}"
            )
    elif component != catalogued_component:
        raise EventValidationError(
            f"event {event!r} requires component {catalogued_component!r}, "
            f"got {component!r}"
        )

    is_recognition_event = event in _EVENTS_WITH_RECOGNITION_FIELDS
    is_liveness_event = event in _EVENTS_WITH_LIVENESS_FIELDS
    is_processing_outcome_event = (
        event in _EVENTS_WITH_PROCESSING_OUTCOME_FIELDS
    )
    is_provider_inbound_stage_event = (
        event in _EVENTS_WITH_PROVIDER_INBOUND_STAGE_FIELDS
    )
    allows_no_outcome_or_failure = (
        event in _EVENTS_WITHOUT_OUTCOME_OR_FAILURE
    )

    if is_recognition_event or allows_no_outcome_or_failure:
        if outcome is not None:
            raise EventValidationError(
                f"event {event!r} does not accept outcome"
            )
        if failure_category is not None:
            raise EventValidationError(
                f"event {event!r} does not accept failure_category"
            )
    elif is_liveness_event:
        if outcome is None:
            raise EventValidationError(
                f"event {event!r} requires an outcome"
            )
        _validate_outcome(event, outcome)
        if failure_category is not None:
            _validate_failure_category(event, failure_category)
        if (
            exception_type is not None
            and not _is_safe_optional_field(
                "exception_type", exception_type
            )
        ):
            raise EventValidationError(
                f"invalid value for field 'exception_type': "
                f"{exception_type!r}"
            )
        if outcome == "phase_failed":
            if failure_category is None:
                raise EventValidationError(
                    f"event {event!r} with outcome 'phase_failed' "
                    "requires 'failure_category'"
                )
            if exception_type is None:
                raise EventValidationError(
                    f"event {event!r} with outcome 'phase_failed' "
                    "requires 'exception_type'"
                )
        else:
            if failure_category is not None:
                raise EventValidationError(
                    f"event {event!r} does not accept "
                    f"'failure_category' with outcome {outcome!r}; "
                    "'failure_category' is reserved for outcome "
                    "'phase_failed'"
                )
            if exception_type is not None:
                raise EventValidationError(
                    f"event {event!r} does not accept "
                    f"'exception_type' with outcome {outcome!r}; "
                    "'exception_type' is reserved for outcome "
                    "'phase_failed'"
                )
    elif is_processing_outcome_event:
        if outcome is None:
            raise EventValidationError(
                f"event {event!r} requires an outcome"
            )
        _validate_outcome(event, outcome)
        if outcome in _PROCESSING_OUTCOME_PROCESSED_VALUES:
            if failure_category is not None:
                raise EventValidationError(
                    f"event {event!r} with outcome {outcome!r} "
                    "does not accept 'failure_category'; "
                    "'failure_category' is reserved for "
                    "retry/terminal/lease-loss/unavailable outcomes"
                )
            if response_count is None:
                raise EventValidationError(
                    f"event {event!r} with outcome {outcome!r} "
                    "requires 'response_count'"
                )
            if outbox_row_count is None:
                raise EventValidationError(
                    f"event {event!r} with outcome {outcome!r} "
                    "requires 'outbox_row_count'"
                )
        elif outcome in _PROCESSING_OUTCOME_FAILURE_VALUES:
            if response_count is not None:
                raise EventValidationError(
                    f"event {event!r} with outcome {outcome!r} "
                    "does not accept 'response_count'; "
                    "'response_count' is reserved for "
                    "processed outcomes"
                )
            if outbox_row_count is not None:
                raise EventValidationError(
                    f"event {event!r} with outcome {outcome!r} "
                    "does not accept 'outbox_row_count'; "
                    "'outbox_row_count' is reserved for "
                    "processed outcomes"
                )
            if failure_category is not None:
                _validate_failure_category(event, failure_category)
        else:
            raise EventValidationError(
                f"unknown processing outcome {outcome!r}"
            )
    elif is_provider_inbound_stage_event:
        if outcome is None:
            raise EventValidationError(
                f"event {event!r} requires an outcome"
            )
        _validate_outcome(event, outcome)
        if failure_category is not None:
            raise EventValidationError(
                f"event {event!r} does not accept 'failure_category'; "
                "'failure_category' is reserved for technical boundary "
                "events, not for the closed provider_inbound_stage event"
            )
    else:
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

    payload: dict[str, Any] = {
        "event": event,
        "schema_version": int(SCHEMA_VERSION),
        "component": component,
        "timestamp": (
            timestamp if timestamp is not None
            else datetime.now(tz=timezone.utc).isoformat()
        ),
    }
    if not is_recognition_event and not allows_no_outcome_or_failure:
        if (
            is_liveness_event
            or is_processing_outcome_event
            or is_provider_inbound_stage_event
        ):
            payload["outcome"] = outcome
            if failure_category is not None:
                payload["failure_category"] = failure_category
        elif outcome is not None:
            payload["outcome"] = outcome
        else:
            payload["failure_category"] = failure_category

    if is_recognition_event:
        recognition_fields = _validate_recognition_event_fields(
            configured_mode=configured_mode,
            effective_mode=effective_mode,
            authoritative_strategy=authoritative_strategy,
            hybrid_decision=hybrid_decision,
            fallback=fallback,
            fallback_category=fallback_category,
            fuzzy_latency_ms=fuzzy_latency_ms,
            embedding_latency_ms=embedding_latency_ms,
            vector_latency_ms=vector_latency_ms,
        )
        payload.update(recognition_fields)
    else:
        if any(
            value is not None
            for value in (
                configured_mode,
                effective_mode,
                authoritative_strategy,
                hybrid_decision,
                fallback,
                fallback_category,
                fuzzy_latency_ms,
                embedding_latency_ms,
                vector_latency_ms,
            )
        ):
            raise EventValidationError(
                f"event {event!r} does not accept recognition fields"
            )

    is_pending_context_event = event in _EVENTS_WITH_PENDING_CONTEXT_FIELDS

    if is_pending_context_event:
        if any(
            value is not None
            for value in (
                outbox_id,
                correlation_id,
                attempt,
                durable_state,
                provider_code,
                http_status,
                exception_type,
                elapsed_ms,
            )
        ):
            raise EventValidationError(
                f"event {event!r} does not accept optional fields; only the "
                "closed pending-context payload is allowed"
            )
        pending_context_fields = _validate_pending_context_event_fields(
            outcome=outcome,
            context_kind=context_kind,
            status_before=status_before,
            status_after=status_after,
            candidate_count_before=candidate_count_before,
            candidate_count_after=candidate_count_after,
            context_cleared=context_cleared,
        )
        payload.update(pending_context_fields)
        return payload

    is_product_add_event = event in _EVENTS_WITH_PRODUCT_ADD_FIELDS

    if is_product_add_event:
        if any(
            value is not None
            for value in (
                outbox_id,
                correlation_id,
                attempt,
                durable_state,
                provider_code,
                http_status,
                exception_type,
                elapsed_ms,
                context_kind,
                status_before,
                status_after,
                candidate_count_before,
                candidate_count_after,
                context_cleared,
            )
        ):
            raise EventValidationError(
                f"event {event!r} does not accept optional fields; only the "
                "closed product-add outcome is allowed"
            )
        return payload

    is_commerce_installation_event = (
        event in _EVENTS_WITH_COMMERCE_INSTALLATION_FIELDS
    )

    if is_commerce_installation_event:
        if any(
            value is not None
            for value in (
                outbox_id,
                correlation_id,
                attempt,
                durable_state,
                provider_code,
                exception_type,
                elapsed_ms,
                configured_mode,
                effective_mode,
                authoritative_strategy,
                hybrid_decision,
                fallback,
                fallback_category,
                fuzzy_latency_ms,
                embedding_latency_ms,
                vector_latency_ms,
                context_kind,
                status_before,
                status_after,
                candidate_count_before,
                candidate_count_after,
                context_cleared,
                flavor_code,
                eligible_count,
                applied_count,
                outbound_style_prompt_template_version,
                outbound_style_prompt_template_hash,
            )
        ):
            raise EventValidationError(
                f"event {event!r} does not accept extra fields; only "
                "the closed reason/http_status pair is allowed"
            )
        commerce_installation_fields = (
            _validate_commerce_installation_event_fields(
                outcome=outcome,
                reason=reason,
                http_status=http_status,
                component=component,
            )
        )
        payload.update(commerce_installation_fields)
        return payload

    if is_liveness_event:
        if any(
            value is not None
            for value in (
                outbox_id,
                correlation_id,
                attempt,
                durable_state,
                provider_code,
                http_status,
                configured_mode,
                effective_mode,
                authoritative_strategy,
                hybrid_decision,
                fallback,
                fallback_category,
                fuzzy_latency_ms,
                embedding_latency_ms,
                vector_latency_ms,
                context_kind,
                status_before,
                status_after,
                candidate_count_before,
                candidate_count_after,
                context_cleared,
                flavor_code,
                eligible_count,
                applied_count,
                outbound_style_prompt_template_version,
                outbound_style_prompt_template_hash,
                reason,
            )
        ):
            raise EventValidationError(
                f"event {event!r} does not accept extra fields; only the "
                "closed phase/cycle_index/elapsed_ms/exception_type "
                "payload is allowed"
            )
        liveness_fields = _validate_liveness_event_fields(
            outcome=outcome,
            phase=phase,
            cycle_index=cycle_index,
        )
        payload.update(liveness_fields)
        if elapsed_ms is not None:
            if (
                isinstance(elapsed_ms, bool)
                or not isinstance(elapsed_ms, int)
                or not 0 <= elapsed_ms <= _MAX_ELAPSED_MS
            ):
                raise EventValidationError(
                    f"elapsed_ms must be in [0, {_MAX_ELAPSED_MS}] "
                    f"(got {elapsed_ms!r})"
                )
            payload["elapsed_ms"] = elapsed_ms
        if exception_type is not None:
            payload["exception_type"] = exception_type
        return payload

    if is_provider_inbound_stage_event:
        if any(
            value is not None
            for value in (
                outbox_id,
                attempt,
                durable_state,
                provider_code,
                http_status,
                configured_mode,
                effective_mode,
                authoritative_strategy,
                hybrid_decision,
                fallback,
                fallback_category,
                fuzzy_latency_ms,
                embedding_latency_ms,
                vector_latency_ms,
                context_kind,
                status_before,
                status_after,
                candidate_count_before,
                candidate_count_after,
                context_cleared,
                flavor_code,
                eligible_count,
                applied_count,
                outbound_style_prompt_template_version,
                outbound_style_prompt_template_hash,
                reason,
                response_count,
                outbox_row_count,
                phase,
                cycle_index,
            )
        ):
            raise EventValidationError(
                f"event {event!r} does not accept extra fields; only the "
                "closed stage/outcome/elapsed_ms/exception_type/"
                "correlation_id payload is allowed"
            )
        stage_fields = _validate_provider_inbound_stage_event_fields(
            outcome=outcome,
            stage=stage,
            elapsed_ms=elapsed_ms,
            exception_type=exception_type,
            correlation_id=correlation_id,
        )
        payload.update(stage_fields)
        return payload

    is_llm_transport_phase_event = (
        event in _EVENTS_WITH_LLM_REQUEST_TRANSPORT_PHASE_FIELDS
    )

    if is_llm_transport_phase_event:
        if any(
            value is not None
            for value in (
                outbox_id,
                attempt,
                durable_state,
                provider_code,
                configured_mode,
                effective_mode,
                authoritative_strategy,
                hybrid_decision,
                fallback,
                fallback_category,
                fuzzy_latency_ms,
                embedding_latency_ms,
                vector_latency_ms,
                context_kind,
                status_before,
                status_after,
                candidate_count_before,
                candidate_count_after,
                context_cleared,
                flavor_code,
                eligible_count,
                applied_count,
                outbound_style_prompt_template_version,
                outbound_style_prompt_template_hash,
                reason,
                response_count,
                outbox_row_count,
                cycle_index,
                stage,
            )
        ):
            raise EventValidationError(
                f"event {event!r} does not accept extra fields; only the "
                "closed phase/elapsed_ms/http_status/response_bytes/"
                "correlation_id payload is allowed"
            )
        if phase is None:
            raise EventValidationError(
                f"event {event!r} requires 'phase' from "
                f"{sorted(_LLM_REQUEST_TRANSPORT_PHASES)}"
            )
        if not isinstance(phase, str):
            raise EventValidationError(
                f"phase must be a short alnum token (got {type(phase).__name__})"
            )
        if not _is_safe_short_string(phase, max_length=_MAX_OUTCOME):
            raise EventValidationError(
                f"phase must be a short alnum token (got {phase!r})"
            )
        if phase not in _LLM_REQUEST_TRANSPORT_PHASES:
            raise EventValidationError(
                f"phase {phase!r} not in llm_request_transport_phase "
                f"allowlist {sorted(_LLM_REQUEST_TRANSPORT_PHASES)}"
            )
        payload["phase"] = phase
        # The four SOCKS-boundary phases carry only ``elapsed_ms`` and
        # the existing opaque correlation; ``http_status``,
        # ``response_bytes`` and ``chunk_count`` are not produced at the
        # SOCKS connect or HTTP writer seams and the contract forbids
        # fabricating them. ``request_started`` is also a start
        # observation with no body data, so the same restriction
        # applies (the historical implementation already omits those
        # fields on the start event, the closed rule formalises it).
        if phase in (
            "socks_connect_started",
            "socks_connect_completed",
            "request_write_started",
            "request_write_completed",
            "request_started",
        ):
            _forbidden_start_seam_fields = {
                "http_status": http_status,
                "response_bytes": response_bytes,
                "chunk_count": chunk_count,
            }
            for field_name, field_value in _forbidden_start_seam_fields.items():
                if field_value is not None:
                    raise EventValidationError(
                        f"phase {phase!r} does not accept {field_name!r} "
                        "because the closed SOCKS / writer start or "
                        "request-start seam does not observe body or "
                        "response metadata"
                    )

    if any(
        value is not None
        for value in (
            context_kind,
            status_before,
            status_after,
            candidate_count_before,
            candidate_count_after,
            context_cleared,
        )
    ):
        raise EventValidationError(
            f"event {event!r} does not accept pending-context fields"
        )

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
        "flavor_code": flavor_code,
        "eligible_count": eligible_count,
        "applied_count": applied_count,
        "outbound_style_prompt_template_version": outbound_style_prompt_template_version,
        "outbound_style_prompt_template_hash": outbound_style_prompt_template_hash,
        "response_count": response_count,
        "outbox_row_count": outbox_row_count,
        "response_bytes": response_bytes,
        "chunk_count": chunk_count,
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
        configured_mode=decoded.get("configured_mode"),
        effective_mode=decoded.get("effective_mode"),
        authoritative_strategy=decoded.get("authoritative_strategy"),
        hybrid_decision=decoded.get("hybrid_decision"),
        fallback=decoded.get("fallback"),
        fallback_category=decoded.get("fallback_category"),
        fuzzy_latency_ms=decoded.get("fuzzy_latency_ms"),
        embedding_latency_ms=decoded.get("embedding_latency_ms"),
        vector_latency_ms=decoded.get("vector_latency_ms"),
        context_kind=decoded.get("context_kind"),
        status_before=decoded.get("status_before"),
        status_after=decoded.get("status_after"),
        candidate_count_before=decoded.get("candidate_count_before"),
        candidate_count_after=decoded.get("candidate_count_after"),
        context_cleared=decoded.get("context_cleared"),
        flavor_code=decoded.get("flavor_code"),
        eligible_count=decoded.get("eligible_count"),
        applied_count=decoded.get("applied_count"),
        outbound_style_prompt_template_version=decoded.get(
            "outbound_style_prompt_template_version"
        ),
        outbound_style_prompt_template_hash=decoded.get(
            "outbound_style_prompt_template_hash"
        ),
        reason=decoded.get("reason"),
        phase=decoded.get("phase"),
        cycle_index=decoded.get("cycle_index"),
        response_count=decoded.get("response_count"),
        outbox_row_count=decoded.get("outbox_row_count"),
        stage=decoded.get("stage"),
        response_bytes=decoded.get("response_bytes"),
        chunk_count=decoded.get("chunk_count"),
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
    configured_mode: str | None = None,
    effective_mode: str | None = None,
    authoritative_strategy: str | None = None,
    hybrid_decision: str | None = None,
    fallback: bool | None = None,
    fallback_category: str | None = None,
    fuzzy_latency_ms: int | None = None,
    embedding_latency_ms: int | None = None,
    vector_latency_ms: int | None = None,
    context_kind: str | None = None,
    status_before: str | None = None,
    status_after: str | None = None,
    candidate_count_before: int | None = None,
    candidate_count_after: int | None = None,
    context_cleared: bool | None = None,
    flavor_code: str | None = None,
    eligible_count: int | None = None,
    applied_count: int | None = None,
    outbound_style_prompt_template_version: str | None = None,
    outbound_style_prompt_template_hash: str | None = None,
    reason: str | None = None,
    phase: str | None = None,
    cycle_index: int | None = None,
    response_count: int | None = None,
    outbox_row_count: int | None = None,
    stage: str | None = None,
    response_bytes: int | None = None,
    chunk_count: int | None = None,
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
            configured_mode=configured_mode,
            effective_mode=effective_mode,
            authoritative_strategy=authoritative_strategy,
            hybrid_decision=hybrid_decision,
            fallback=fallback,
            fallback_category=fallback_category,
            fuzzy_latency_ms=fuzzy_latency_ms,
            embedding_latency_ms=embedding_latency_ms,
            vector_latency_ms=vector_latency_ms,
            context_kind=context_kind,
            status_before=status_before,
            status_after=status_after,
            candidate_count_before=candidate_count_before,
            candidate_count_after=candidate_count_after,
            context_cleared=context_cleared,
            flavor_code=flavor_code,
            eligible_count=eligible_count,
            applied_count=applied_count,
            outbound_style_prompt_template_version=outbound_style_prompt_template_version,
            outbound_style_prompt_template_hash=outbound_style_prompt_template_hash,
            reason=reason,
            phase=phase,
            cycle_index=cycle_index,
            response_count=response_count,
            outbox_row_count=outbox_row_count,
            stage=stage,
            response_bytes=response_bytes,
            chunk_count=chunk_count,
        )
    except EventValidationError as exc:
        try:
            degraded_payload = build_event(
                event=EVENT_OBSERVABILITY_EMIT_FAILED,
                component=COMPONENT_OBSERVABILITY,
                failure_category="validation",
                exception_type=type(exc).__name__,
            )
        except EventValidationError:
            return False
        try:
            sink.write(
                json.dumps(
                    degraded_payload, sort_keys=True, separators=(",", ":")
                )
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
    "COMPONENT_ADMIN_PILOT_EMULATOR",
    "COMPONENT_CALLBACK",
    "COMPONENT_COMMERCE_INSTALLATION_ADAPTER",
    "COMPONENT_COMMERCE_INSTALLATION_INGRESS",
    "COMPONENT_DATABASE",
    "COMPONENT_EMBEDDING",
    "COMPONENT_LLM",
    "COMPONENT_OBSERVABILITY",
    "COMPONENT_OUTBOUND",
    "COMPONENT_OUTBOUND_STYLE",
    "COMPONENT_PENDING_CONTEXT",
    "COMPONENT_PRODUCT_ADD_EXECUTION",
    "COMPONENT_PRODUCT_RECOGNITION",
    "COMPONENT_TWILIO_EMULATOR",
    "COMPONENT_WORKER",
    "EVENT_ADMIN_PILOT_EMULATOR_OUTCOME",
    "EVENT_CALLBACK_OUTCOME",
    "EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME",
    "EVENT_DATABASE_TECHNICAL_FAILURE",
    "EVENT_EMBEDDING_REQUEST",
    "EVENT_LLM_REQUEST",
    "EVENT_OBSERVABILITY_EMIT_FAILED",
    "EVENT_OUTBOUND_OUTCOME",
    "EVENT_OUTBOUND_STYLE",
    "EVENT_PENDING_CONTEXT_TRANSITION",
    "EVENT_PRODUCT_ADD_EXECUTION",
    "EVENT_PROVIDER_INBOUND_STAGE",
    "EVENT_SHADOW_PRODUCT_RECOGNITION",
    "EVENT_TWILIO_EMULATOR_OUTBOUND_OUTCOME",
    "EVENT_WORKER_CYCLE",
    "EVENT_WORKER_DISABLED",
    "EVENT_WORKER_LIVENESS",
    "EVENT_WORKER_READINESS_TRANSITION",
    "EVENT_WORKER_UNEXPECTED_FAILURE",
    "SCHEMA_VERSION",
    "EventValidationError",
    "build_event",
    "categorize_sqlalchemy_error",
    "emit_event",
    "parse_event",
]
