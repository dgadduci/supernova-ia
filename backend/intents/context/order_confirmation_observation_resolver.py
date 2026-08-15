"""Order-confirmation observation resolver.

This resolver is the dedicated two-turn confirmation flow for the
explicit ``confirmar_pedido`` intent. The first turn is the explicit
``confirmar_pedido`` request itself: the existing closure orchestrator
runs the active-session / own-draft / non-empty-lines / payment /
delivery preconditions and, when those pass, creates a
``pending_resolution`` confirmation intent with a single
``observacion_pedido`` pending requirement and ``session.context_type``
set to :class:`~backend.sessions.enums.context_type.ContextType.ORDER_CONFIRMATION_OBSERVATION`.

The next inbound message is the capture turn. It is routed through
this resolver instead of the initial classifier. The resolver:

* normalizes the captured text (NFKC + strip + whitespace collapse);
* treats the exact normalized ``"no"`` as an explicit skip that
  finalizes confirmation without touching ``Pedido.observaciones``;
* treats any other non-empty value in the closed interval
  ``[1, 500]`` code points as the new ``Pedido.observaciones``
  value and finalizes confirmation in the same caller-owned
  transaction;
* preserves the pending context when the captured text is empty,
  whitespace-only or longer than 500 code points and returns a fixed
  retry-prompt response.

The resolver returns the in-memory, non-serialized
:class:`OrderConfirmationCaptureOutcome` so the observation text
never leaves the resolver scope as a ``ProcessedIntent`` field, a
``RequirementState.value`` or a pending JSON value. The dedicated
``order_confirmation_observation`` branch of
:func:`backend.intents.orchestration.pending_context_dispatcher.dispatch_pending_context`
consumes the outcome and forwards the text only as a local argument
to :func:`finalize_confirmar_pedido`.

The resolver never invokes the LLM, the intent classifier, the
product recognizer, the catalog, the order-line fuzzy recognizer, the
hybrid recognizer, any session-control method
(``commit`` / ``rollback`` / ``flush`` / ``refresh`` / ``begin`` /
``close``) or any module that mutates a ``PedidoProducto`` row. The
final confirmation write is performed by the existing
``process_initial_confirmar_pedido`` finalizer which is the only
authority allowed to mutate ``pedido.estado_pedido`` for the
confirmation transaction.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy.orm import Session as DatabaseSession

from backend.diagnostics import (
    NoopDiagnosticSink,
    ResolverCallCompleted,
    ResolverCallStarted,
)
from backend.diagnostics.sink import DiagnosticSink
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession
from backend.sessions.enums.context_type import ContextType

ORDER_CONFIRMATION_OBSERVATION_PROMPT = (
    "¿Querés agregar alguna observación al pedido? "
    "Escribila ahora o respondé “no”."
)
ORDER_CONFIRMATION_OBSERVATION_RETRY_PROMPT = (
    "Por favor, escribí la observación del pedido (1 a 500 caracteres) "
    "o respondé “no” para confirmar sin observación."
)
_SKIP_NORMALIZED = "no"

_MAX_LENGTH = 500


@dataclass(slots=True, frozen=True)
class OrderConfirmationCaptureOutcome:
    """In-memory outcome of the bounded capture turn.

    The dataclass is the closed contract between the resolver and
    :func:`backend.intents.orchestration.pending_context_dispatcher.dispatch_pending_context`.
    It never reaches the diagnostic sink, the pending JSON, the
    response builder payload or any other serializable surface.

    * :attr:`skip` is ``True`` when the customer replied with the
      exact normalized ``"no"``: the dispatcher forwards the skip to
      the finalizer so the prior ``Pedido.observaciones`` value is
      preserved.
    * :attr:`accepted_text` is the normalized 1..500 code-point text
      when the customer supplied valid free text. The string exists
      only as a local argument to the finalizer; the resolver keeps
      it inside the dataclass and the dispatcher reads it once.
    * :attr:`accepted_length` exposes the code-point length for the
      finalizer to populate the ``observation_accepted_length``
      closed metadata.
    * :attr:`retry` is ``True`` when the captured text was empty or
      longer than 500 code points. The dispatcher then preserves the
      original pending intent with a closed ``capture_outcome`` label
      and never persists the raw text.
    """

    skip: bool = False
    accepted_text: str | None = None
    accepted_length: int = 0
    retry: bool = False
    retry_reason: str = "invalid_capture_length"


__all__ = [
    "ORDER_CONFIRMATION_OBSERVATION_PROMPT",
    "ORDER_CONFIRMATION_OBSERVATION_RETRY_PROMPT",
    "OrderConfirmationCaptureOutcome",
    "resolve_order_confirmation_observation",
]


def _normalize_capture(text: str) -> str:
    """Normalize the captured capture text.

    The function applies the deterministic normalization documented in
    the proposal: NFKC folding, strip and Unicode whitespace collapse.
    The lowercase normalized form is also returned so the resolver can
    detect the exact ``"no"`` skip in a case-insensitive way without
    persisting the lowercased text. The stored length is measured in
    code points.
    """
    normalized = unicodedata.normalize("NFKC", text)
    stripped = normalized.strip()
    folded = re.sub(r"\s+", " ", stripped, flags=re.UNICODE)
    return folded


def _normalize_skip_check(text: str) -> str:
    """Return the lowercase normalized form used only to detect the
    exact ``"no"`` skip.

    The function applies NFKC folding, accent stripping (via the
    same NFD + combining-mark removal the rest of the project uses
    for keyword matching), strip, Unicode whitespace collapse and a
    final ``str.lower()``. The function is read-only and never
    persisted.
    """
    lowered = unicodedata.normalize("NFKC", text).lower()
    decomposed = unicodedata.normalize("NFD", lowered)
    stripped = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    cleaned = re.sub(r"\s+", " ", stripped, flags=re.UNICODE)
    return cleaned.strip()


def resolve_order_confirmation_observation(
    db: DatabaseSession,
    session: ConversationSession,
    message: str,
    active: ProcessedIntent,
    *,
    sink: DiagnosticSink | None = None,
) -> OrderConfirmationCaptureOutcome:
    """Resolve the capture turn of the order-confirmation observation.

    The resolver never invokes the LLM, the intent classifier, the
    product recognizer, the catalog, the order-line fuzzy recognizer
    or hybrid recognition. It only normalizes the captured text and
    returns one closed :class:`OrderConfirmationCaptureOutcome`. The
    observation text lives only inside the dataclass instance and is
    consumed once by the dispatcher branch as a local argument to the
    finalizer.

    The diagnostic events emitted through ``sink`` deliberately drop
    the captured message, its normalized form, the database
    identifiers and any pending JSON. They carry only closed metadata
    (intent, status, context kind, candidate count).
    """
    del db
    del session
    diagnostic_sink: DiagnosticSink = sink if sink is not None else NoopDiagnosticSink()
    started = ResolverCallStarted(
        resolver_class=type(active).__name__,
        resolver_method="resolve_order_confirmation_observation",
        resolver_purpose="order_confirmation_observation_capture",
        context_type=ContextType.ORDER_CONFIRMATION_OBSERVATION.value,
        intent=active.intent,
        status_before=active.status,
        candidate_ids_before=list(active.candidate_ids),
    )
    diagnostic_sink.on_resolver_started(started)
    try:
        normalized = _normalize_capture(message or "")
        skip_check = _normalize_skip_check(message or "")
        length = len(normalized)

        if skip_check == _SKIP_NORMALIZED:
            outcome = OrderConfirmationCaptureOutcome(skip=True)
        elif length < 1 or length > _MAX_LENGTH:
            outcome = OrderConfirmationCaptureOutcome(
                retry=True,
                retry_reason="invalid_capture_length",
            )
        else:
            outcome = OrderConfirmationCaptureOutcome(
                accepted_text=normalized,
                accepted_length=length,
            )
    finally:
        completed = ResolverCallCompleted(
            result_type=type(active).__name__,
            status_after=active.status,
            candidate_ids_after=list(active.candidate_ids),
        )
        diagnostic_sink.on_resolver_completed(completed)

    return outcome
