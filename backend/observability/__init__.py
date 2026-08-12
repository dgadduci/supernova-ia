"""Privacy-safe structured operational event helpers.

The ``backend.observability`` package owns the versioned allowlisted
schema used to emit operational events covering the provider worker,
outbound dispatch, Twilio callback, LLM/Ollama and database technical
boundaries. Emitters are pure side-effect-free validators that produce
a single JSON line on stdout.

The package is intentionally narrow:

* no SQLAlchemy session, no HTTP, no Twilio/LLM client;
* no inheritance, no plugin surface, no shared mutable state;
* no global logging handler - callers pass the destination stream.
"""
from backend.observability.events import (
    COMPONENT_CALLBACK,
    COMPONENT_DATABASE,
    COMPONENT_EMBEDDING,
    COMPONENT_LLM,
    COMPONENT_OBSERVABILITY,
    COMPONENT_OUTBOUND,
    COMPONENT_PRODUCT_RECOGNITION,
    COMPONENT_WORKER,
    EVENT_CALLBACK_OUTCOME,
    EVENT_DATABASE_TECHNICAL_FAILURE,
    EVENT_EMBEDDING_REQUEST,
    EVENT_LLM_REQUEST,
    EVENT_OBSERVABILITY_EMIT_FAILED,
    EVENT_OUTBOUND_OUTCOME,
    EVENT_SHADOW_PRODUCT_RECOGNITION,
    EVENT_WORKER_CYCLE,
    EVENT_WORKER_DISABLED,
    EVENT_WORKER_READINESS_TRANSITION,
    EVENT_WORKER_UNEXPECTED_FAILURE,
    SCHEMA_VERSION,
    EventValidationError,
    build_event,
    categorize_sqlalchemy_error,
    emit_event,
    parse_event,
)

__all__ = [
    "COMPONENT_CALLBACK",
    "COMPONENT_DATABASE",
    "COMPONENT_EMBEDDING",
    "COMPONENT_LLM",
    "COMPONENT_OBSERVABILITY",
    "COMPONENT_OUTBOUND",
    "COMPONENT_PRODUCT_RECOGNITION",
    "COMPONENT_WORKER",
    "EVENT_CALLBACK_OUTCOME",
    "EVENT_DATABASE_TECHNICAL_FAILURE",
    "EVENT_EMBEDDING_REQUEST",
    "EVENT_LLM_REQUEST",
    "EVENT_OBSERVABILITY_EMIT_FAILED",
    "EVENT_OUTBOUND_OUTCOME",
    "EVENT_SHADOW_PRODUCT_RECOGNITION",
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
