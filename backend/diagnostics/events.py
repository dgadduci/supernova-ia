from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import cast

from .serializer import serialize


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class ClassifierCallStarted:
    call_id: str = ""
    turn_id: int = 1
    component: str = "classifier"
    method: str = "query"
    timestamp: str = field(default_factory=_timestamp)
    raw_message: object = None
    normalized_message: object = None
    active_context_type: object = None
    has_active_pending_intent: bool = False
    active_pending_intent: object = None
    queued_intent_count: int = 0
    classifier_class: str = "IntentClassifier"
    classifier_method: str = "query"
    prompt_name: object = None
    model: object = None
    prompt_template_version: str = ""
    prompt_fingerprint: str = ""
    phase: str = field(default="classifier", init=False)
    sequence: int = 0

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], serialize(self))


@dataclass(slots=True)
class ClassifierCallCompleted:
    call_id: str = ""
    turn_id: int = 1
    component: str = "classifier"
    method: str = "query"
    timestamp: str = field(default_factory=_timestamp)
    result: object = None
    intent_count: int = 0
    unknown_fragments: list[object] = field(default_factory=list)
    raw_response_metadata: object = None
    parse_errors: list[object] = field(default_factory=list)
    fallback_state: object = None
    classified_intents: list[object] = field(default_factory=list)
    validation_category: str = ""
    prompt_template_version: str = ""
    prompt_fingerprint: str = ""
    effective_model: object = None
    phase: str = field(default="classifier", init=False)
    sequence: int = 0

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], serialize(self))


@dataclass(slots=True)
class ResolverCallStarted:
    call_id: str = ""
    turn_id: int = 1
    component: str = "resolver"
    method: str = "resolve"
    resolver_class: str = ""
    resolver_method: str = "resolve"
    resolver_purpose: str = ""
    session_id: object = None
    context_type: object = None
    incoming_text: object = None
    normalized_text: object = None
    intent: object = None
    source_text: object = None
    quantity: object = None
    status_before: object = None
    requirements_before: object = None
    resolved_data_before: object = None
    candidate_ids_before: list[object] = field(default_factory=list)
    candidate_count: int = 0
    candidate_catalog: list[object] = field(default_factory=list)
    queued_intent_count: int = 0
    timestamp: str = field(default_factory=_timestamp)
    phase: str = field(default="resolver", init=False)
    sequence: int = 0

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], serialize(self))


@dataclass(slots=True)
class ResolverCallCompleted:
    call_id: str = ""
    turn_id: int = 1
    component: str = "resolver"
    method: str = "resolve"
    result_type: str = ""
    status_after: object = None
    selected_candidate_id: object = None
    selected_product: object = None
    quantity_after: object = None
    requirements_after: object = None
    resolved_data_after: object = None
    candidate_ids_after: list[object] = field(default_factory=list)
    candidate_count_after: int = 0
    rejection_reason: object = None
    clarification_message: object = None
    raw_result: object = None
    matches: list[object] = field(default_factory=list)
    resolved_context_type: object = None
    clarification_required: object = None
    ready_for_execution: object = None
    timestamp: str = field(default_factory=_timestamp)
    phase: str = field(default="resolver", init=False)
    sequence: int = 0

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], serialize(self))


@dataclass(slots=True)
class PendingStateSnapshot:
    call_id: str = ""
    turn_id: int = 1
    snapshot_phase: str = ""
    active_intent: object = None
    active_status: object = None
    active_source_text: object = None
    active_quantity: object = None
    active_candidate_ids: list[object] = field(default_factory=list)
    queue_length: int = 0
    queue_intents: list[object] = field(default_factory=list)
    queue_sources: list[object] = field(default_factory=list)
    context_type: object = None
    timestamp: str = field(default_factory=_timestamp)
    phase: str = field(default="pending", init=False)
    sequence: int = 0

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], serialize(self))


DiagnosticEvent = (
    ClassifierCallStarted
    | ClassifierCallCompleted
    | ResolverCallStarted
    | ResolverCallCompleted
    | PendingStateSnapshot
)


__all__ = [
    "ClassifierCallCompleted",
    "ClassifierCallStarted",
    "DiagnosticEvent",
    "PendingStateSnapshot",
    "ResolverCallCompleted",
    "ResolverCallStarted",
]
