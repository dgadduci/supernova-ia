"""Set product-line observation recognizer.

The recognizer reuses the existing order-line fuzzy recognizer to
discover one or more candidate ``PedidoProducto`` rows from the active
conversation session's own ``Pedido``. It never queries the commerce
catalog, never modifies ``session``, the ``Pedido``, or any persisted
state, and never invokes the LLM. The recognizer additionally exposes a
local deterministic grammar that classifies the supplied classified
message into a ``set`` or ``clear`` action.
"""
from __future__ import annotations

import re
import unicodedata

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.recognizers.quitar_producto_recognizer import (
    recognize_quitar_producto,
)
from backend.models.session import Session as ConversationSession

_CLEAR_VERBS: tuple[str, ...] = (
    "quitar",
    "quito",
    "quita",
    "quitas",
    "quite",
    "quites",
    "quitemos",
    "quitan",
    "quitamos",
    "quitando",
    "sacame",
    "sacamos",
    "sacamela",
    "sacala",
    "sacalo",
    "sacarlas",
    "sacarlos",
    "sacar",
    "saco",
    "saca",
    "sacas",
    "saquemos",
    "sacan",
    "sacando",
    "eliminar",
    "elimino",
    "elimina",
    "eliminas",
    "eliminamos",
    "eliminan",
    "eliminando",
    "borrar",
    "borro",
    "borra",
    "borras",
    "borramos",
    "borran",
    "borrando",
)

_CLEAR_NOUNS: tuple[str, ...] = (
    "observacion",
    "observaciones",
    "aclaracion",
    "aclaraciones",
)

_CLEAR_EXACT_PHRASES: tuple[str, ...] = (
    "sin observacion",
    "sin aclaracion",
)


def _normalize_for_clear(text: str) -> str:
    lowered = text.lower()
    decomposed = unicodedata.normalize("NFD", lowered)
    stripped = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    cleaned = re.sub(r"[^a-z0-9ñ\s]", " ", stripped)
    return re.sub(r"\s+", " ", cleaned).strip()


def is_clear_observation_message(text: str) -> bool:
    """Return ``True`` when the trimmed normalized text matches the local
    explicit clear grammar.

    A clear message must either be the exact phrase ``"sin observación"``
    (or ``"sin aclaración"`` after normalization) or contain both an
    observation/aclaración noun (in plural or singular) and a supported
    clear verb (in any of the supported inflections). The grammar is
    intentionally narrow; any non-empty input that does not match
    defaults to a ``set`` action with the trimmed source text.
    """
    normalized = _normalize_for_clear(text)
    if not normalized:
        return False
    if normalized in _CLEAR_EXACT_PHRASES:
        return True
    tokens = set(normalized.split())
    if not any(noun in tokens for noun in _CLEAR_NOUNS):
        return False
    return any(verb in tokens for verb in _CLEAR_VERBS)


def _flatten_candidate_ids(recognized: dict) -> list[int]:
    candidates: list[int] = []
    for entry in recognized.get("encontrados") or []:
        pp_id = entry.get("pedido_producto_id")
        if pp_id is not None:
            candidates.append(int(pp_id))
    for group in recognized.get("encontrados_posibles") or []:
        if group.get("kind") == "category":
            continue
        for product in group.get("productos") or []:
            pp_id = product.get("pedido_producto_id")
            if pp_id is not None:
                candidates.append(int(pp_id))
    return candidates


def recognize_set_observacion_producto(
    db: DatabaseSession,
    session: ConversationSession,
    message: str,
) -> dict:
    """Build the order-line candidate set for ``set_observacion_producto``.

    The function delegates fuzzy product recognition to the existing
    order-line recognizer (which is the only place that touches the
    catalog and is restricted to the active session's own draft pedido
    lines). It then returns a deterministic shape containing the unique
    sorted ``pedido_producto_id`` candidates and the local
    ``observation_action`` decision: ``"clear"`` when the trimmed
    classified message matches the local explicit clear grammar, else
    ``"set"``. The recognizer never inspects the commerce catalog,
    never modifies ``session`` or the pedido, and never touches
    persisted state.
    """
    pedido_id = session.id_pedido
    if pedido_id is None:
        return {
            "candidate_ids": [],
            "observation_action": (
                "clear" if is_clear_observation_message(message) else "set"
            ),
            "observation_text": "",
            "no_pedido": True,
        }

    recognized = recognize_quitar_producto(db, session, message)
    raw_ids = _flatten_candidate_ids(recognized)
    unique_ids = sorted(set(raw_ids))

    observation_action = (
        "clear" if is_clear_observation_message(message) else "set"
    )
    observation_text = message.strip() if observation_action == "set" else ""

    return {
        "candidate_ids": unique_ids,
        "observation_action": observation_action,
        "observation_text": observation_text,
        "no_pedido": False,
    }


__all__ = [
    "is_clear_observation_message",
    "recognize_set_observacion_producto",
]
