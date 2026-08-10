"""Deterministic confirmation resolver for ``order_clear_confirmation``.

While the session is in the ``order_clear_confirmation`` context, the next
customer message is evaluated exclusively by this resolver before any
initial intent classification runs. The resolver normalizes the customer
text (lowercase, accent-stripped, collapsed whitespace, terminal
punctuation stripped) and recognizes only an approved finite vocabulary:

* ``"si"`` → ready confirmation with ``confirmacion=True`` (the
  ``execute_ready_pending_context`` primitive will route the ready
  intent to the ``vaciar_pedido`` handler, which performs the
  transaction-neutral all-lines clear).
* ``"no"`` → ready confirmation with ``confirmacion=False`` (the
  ``vaciar_pedido`` handler returns a rejected cancellation outcome
  without mutating any row; the primitive then clears the pending
  context).
* Any other text → the same ``pending_resolution`` intent is returned
  unchanged so the next turn re-prompts. The resolver NEVER invokes
  the initial classifier, an LLM, a catalog recognizer, or any
  order/product resolver while the confirmation is active.

The resolver is intentionally a small pure function with no SQLAlchemy
dependencies. It never commits, rolls back, flushes, refreshes, begins,
expires, or closes a session.
"""
from __future__ import annotations

import re
import unicodedata

from backend.diagnostics import (
    NoopDiagnosticSink,
    ResolverCallCompleted,
    ResolverCallStarted,
)
from backend.diagnostics.sink import DiagnosticSink
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState


_AFFIRMATIVE_NORMALIZED = "si"
_NEGATIVE_NORMALIZED = "no"


def _normalize_confirmation_text(text: str) -> str:
    """Lowercase, accent-strip, replace non-alphanumeric with space, collapse.

    The normalization mirrors the established project pattern used by
    ``backend.intents.orchestration.draft_order_closure._normalize_choice``
    so the confirmation vocabulary compares on the same canonical form
    as the rest of the pipeline. ``ñ`` is preserved.
    """
    lowered = text.lower()
    decomposed = unicodedata.normalize("NFD", lowered)
    stripped = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    cleaned = re.sub(r"[^a-z0-9ñ\s]", " ", stripped)
    return re.sub(r"\s+", " ", cleaned).strip()


def _build_ready_intent(
    active_intent: ProcessedIntent,
    confirmacion: bool,
) -> ProcessedIntent:
    resolved_data = dict(active_intent.resolved_data or {})
    resolved_data["confirmacion"] = bool(confirmacion)
    new_requirements = [
        RequirementState(
            name="confirmacion",
            status="completed",
            value=bool(confirmacion),
        )
    ]
    for req in active_intent.requirements:
        if req.name == "confirmacion":
            continue
        new_requirements.append(req)
    return ProcessedIntent(
        intent=active_intent.intent,
        source_text=active_intent.source_text,
        status="ready",
        recognizer=active_intent.recognizer,
        handler=active_intent.handler,
        stage=active_intent.stage,
        resolved_data=resolved_data,
        requirements=new_requirements,
        candidate_ids=[],
    )


def resolve_order_clear_confirmation(
    db: object,
    session: object,
    message: str,
    active_intent: ProcessedIntent,
    *,
    sink: DiagnosticSink | None = None,
) -> ProcessedIntent:
    """Refine an active ``vaciar_pedido`` pending_resolution intent.

    Returns a ``ready`` intent (with ``confirmacion=True`` or ``False``)
    when the normalized text is exactly ``"si"`` or ``"no"``; otherwise
    returns the same ``active_intent`` unchanged so the pending context
    is preserved.
    """
    del db, session
    diagnostic_sink: DiagnosticSink = sink if sink is not None else NoopDiagnosticSink()
    normalized = _normalize_confirmation_text(message or "")
    started = ResolverCallStarted(
        resolver_class=type(active_intent).__name__,
        resolver_method="resolve_order_clear_confirmation",
        resolver_purpose="order_clear_confirmation",
        intent=active_intent.intent,
        source_text=active_intent.source_text,
        quantity=None,
        status_before=active_intent.status,
        requirements_before=list(active_intent.requirements),
        resolved_data_before=dict(active_intent.resolved_data or {}),
        candidate_ids_before=list(active_intent.candidate_ids),
        incoming_text=message,
        normalized_text=normalized,
    )
    diagnostic_sink.on_resolver_started(started)
    try:
        if active_intent.status != "pending_resolution":
            return active_intent
        if active_intent.intent != "vaciar_pedido":
            return active_intent

        if normalized == _AFFIRMATIVE_NORMALIZED:
            return _build_ready_intent(active_intent, confirmacion=True)
        if normalized == _NEGATIVE_NORMALIZED:
            return _build_ready_intent(active_intent, confirmacion=False)
        return active_intent
    finally:
        completed = ResolverCallCompleted(
            result_type=type(active_intent).__name__,
            status_after=active_intent.status,
            quantity_after=None,
            requirements_after=list(active_intent.requirements),
            resolved_data_after=dict(active_intent.resolved_data or {}),
            candidate_ids_after=list(active_intent.candidate_ids),
        )
        diagnostic_sink.on_resolver_completed(completed)


__all__ = ["resolve_order_clear_confirmation"]
