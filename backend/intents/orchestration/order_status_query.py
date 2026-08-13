from __future__ import annotations

import re
import unicodedata

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.pedido import Pedido
from backend.models.session import Session as ConversationSession

_INTENT = "consultar_estado_pedido"
_RECOGNIZER = "order_status_query"
_HANDLER = _INTENT

_STATUS_QUERY_FORMS: frozenset[str] = frozenset(
    {
        "estado de mi pedido",
        "cual es el estado de mi pedido",
        "como va mi pedido",
        "donde esta mi pedido",
    }
)


def _normalize_status_query_text(text: str) -> str:
    """Lowercase, accent-strip, collapse non-alphanumeric to spaces, trim.

    Mirrors the deterministic normalization used by the closed
    confirmation and status vocabularies so ``Cuál es el estado de mi
    pedido``, ``cual es el estado de mi pedido`` and ``¿Cual es el
    estado de mi pedido?`` all compare on the same canonical form.
    """
    lowered = text.lower()
    decomposed = unicodedata.normalize("NFD", lowered)
    stripped = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    cleaned = re.sub(r"[^a-z0-9ñ\s]", " ", stripped)
    return re.sub(r"\s+", " ", cleaned).strip()


def is_explicit_order_status_query(text: str) -> bool:
    """Return ``True`` when ``text`` is a closed Spanish status query.

    The predicate is read-only, side-effect free and intentionally narrow:
    it only matches the four canonical forms enumerated by
    ``_STATUS_QUERY_FORMS`` after the deterministic normalization.
    Anything else - product names, quantities, delivery, greetings,
    confirmations, cancelations - returns ``False`` so the existing
    pending resolver keeps priority over the status interruption.
    """
    if not isinstance(text, str):
        return False
    return _normalize_status_query_text(text) in _STATUS_QUERY_FORMS


def _rejected(
    source_text: str,
    reason: str,
) -> ProcessedIntent:
    return ProcessedIntent(
        intent=_INTENT,
        source_text=source_text,
        status="rejected",
        recognizer=_RECOGNIZER,
        handler=_HANDLER,
        resolved_data={"reason": reason},
    )


def process_initial_order_status_query(
    db: DatabaseSession,
    session: ConversationSession,
    source_text: str,
) -> ProcessedIntent:
    pedido_id = session.id_pedido
    if pedido_id is None:
        return _rejected(source_text, "no_pedido_asociado")

    pedido = db.get(Pedido, int(pedido_id))
    if pedido is None:
        return _rejected(source_text, "no_pedido_asociado")
    if pedido.id_session != session.id:
        return _rejected(source_text, "session_mismatch")

    return ProcessedIntent(
        intent=_INTENT,
        source_text=source_text,
        status="executed",
        recognizer=_RECOGNIZER,
        handler=_HANDLER,
        resolved_data={"estado_pedido": pedido.estado_pedido.value},
    )


__all__ = ["is_explicit_order_status_query", "process_initial_order_status_query"]
