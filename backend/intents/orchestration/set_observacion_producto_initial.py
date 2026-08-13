"""Initial orchestration for ``set_observacion_producto``.

The orchestrator populates the active draft Pedido's order lines through
the existing service layer, runs the dedicated recognizer to obtain the
user-typed observation text + local ``set``/``clear`` action plus one
or more order-line candidates, and produces a ``ProcessedIntent`` with
one of three outcomes:

- ``ready`` (single unique candidate; auto-executes through the
  dedicated handler);
- ``pending_resolution`` (multiple candidates; assigns the
  ``order_line_selection`` context type and persists the resolved
  action/text so the next message is routed through the existing
  order-line refinement without reclassifying or re-parsing);
- ``rejected`` (no candidates, no active draft, or no usable text).

The orchestrator never ``commit``, ``rollback``, ``flush``, ``refresh``,
``expire``, ``begin``, or ``close`` the SQLAlchemy session; it never
parses the observation text beyond the local grammar; it never invokes
the LLM; and it never writes a customer-facing response.
"""
from __future__ import annotations

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.context.context_type_resolver import resolve_context_type
from backend.intents.context.pending_context_service import set_pending_intent
from backend.intents.handlers.set_observacion_producto_handler import (
    execute_set_observacion_producto,
)
from backend.intents.recognizers.set_observacion_producto_recognizer import (
    recognize_set_observacion_producto,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
from backend.models.session import EstadoSession
from backend.models.session import Session as ConversationSession


def _build_pending_requirements(
    observation_action: str,
) -> list[RequirementState]:
    return [
        RequirementState(
            name="pedido_producto_id",
            status="pending",
            value=None,
        ),
        RequirementState(
            name="observacion",
            status="completed",
            value=observation_action,
        ),
    ]


def _build_pending_intent(
    *,
    source_text: str,
    candidate_ids: list[int],
    observation_action: str,
    observation_text: str,
) -> ProcessedIntent:
    resolved_data: dict = {
        "observation_action": observation_action,
    }
    if observation_action == "set":
        resolved_data["observation_text"] = observation_text
    return ProcessedIntent(
        intent="set_observacion_producto",
        source_text=source_text,
        status="pending_resolution",
        recognizer="recognizer_set_observacion_producto",
        handler="set_observacion_producto",
        resolved_data=resolved_data,
        requirements=_build_pending_requirements(observation_action),
        candidate_ids=list(candidate_ids),
    )


def _build_ready_requirements(
    *,
    pedido_producto_id: int,
    observation_action: str,
) -> list[RequirementState]:
    return [
        RequirementState(
            name="pedido_producto_id",
            status="completed",
            value=pedido_producto_id,
        ),
        RequirementState(
            name="observacion",
            status="completed",
            value=observation_action,
        ),
    ]


def _build_ready_intent(
    *,
    source_text: str,
    pedido_producto_id: int,
    observation_action: str,
    observation_text: str,
) -> ProcessedIntent:
    resolved_data: dict = {
        "pedido_producto_id": pedido_producto_id,
        "observation_action": observation_action,
    }
    if observation_action == "set":
        resolved_data["observation_text"] = observation_text
    return ProcessedIntent(
        intent="set_observacion_producto",
        source_text=source_text,
        status="ready",
        recognizer="recognizer_set_observacion_producto",
        handler="set_observacion_producto",
        resolved_data=resolved_data,
        requirements=_build_ready_requirements(
            pedido_producto_id=pedido_producto_id,
            observation_action=observation_action,
        ),
        candidate_ids=[],
    )


def _build_rejected_intent(source_text: str) -> ProcessedIntent:
    return ProcessedIntent(
        intent="set_observacion_producto",
        source_text=source_text,
        status="rejected",
        recognizer="recognizer_set_observacion_producto",
        handler="set_observacion_producto",
    )


def process_initial_set_observacion_producto(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
) -> ProcessedIntent:
    """Resolve a single ``set_observacion_producto`` message.

    Returns ``rejected`` (no mutation) when the session is not active,
    when ``session.id_pedido`` is ``None``, or when the recognizer yields
    no candidates. Returns ``ready`` and auto-executes the dedicated
    handler when exactly one unique candidate is found. Returns
    ``pending_resolution`` with ``candidate_ids`` populated when more
    than one candidate matches and the resolved context type is
    ``order_line_selection``; the pending context is persisted so the
    next message is routed through the existing refinement resolver.
    """
    if getattr(session, "estado_session", None) != EstadoSession.ACTIVA:
        return _build_rejected_intent(source_text)

    if session.id_pedido is None:
        return _build_rejected_intent(source_text)

    recognized = recognize_set_observacion_producto(db, session, source_text)
    candidate_ids = sorted({int(cid) for cid in recognized.get("candidate_ids") or []})
    observation_action = recognized.get("observation_action") or "set"
    observation_text = recognized.get("observation_text") or ""

    if observation_action == "set" and not observation_text:
        return _build_rejected_intent(source_text)

    if len(candidate_ids) == 1:
        ready_intent = _build_ready_intent(
            source_text=source_text,
            pedido_producto_id=candidate_ids[0],
            observation_action=observation_action,
            observation_text=observation_text,
        )
        return execute_set_observacion_producto(db, session, ready_intent)

    if len(candidate_ids) > 1:
        pending_intent = _build_pending_intent(
            source_text=source_text,
            candidate_ids=candidate_ids,
            observation_action=observation_action,
            observation_text=observation_text,
        )
        if resolve_context_type(pending_intent) is not None:
            set_pending_intent(session, pending_intent)
        return pending_intent

    return _build_rejected_intent(source_text)


__all__ = ["process_initial_set_observacion_producto"]
