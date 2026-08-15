"""Set product-line observation recognizer.

The recognizer reuses the existing order-line fuzzy recognizer to
discover one or more candidate ``PedidoProducto`` rows from the active
conversation session's own ``Pedido``. It never queries the commerce
catalog, never modifies ``session``, the ``Pedido``, or any persisted
state, and never invokes the LLM. The recognizer additionally exposes a
local deterministic grammar that classifies the supplied classified
message into a ``set`` or ``clear`` action.

When the bounded order-line fuzzy path yields zero candidates, the
recognizer runs a narrow identity-evidence recovery against the SAME
active draft line catalog. Recovery uses only the already-projected
``producto_nombre``, ``presentacion_codigo``, ``presentacion_descripcion``
and ``categoria_nombre`` fields; it never introduces a new alias
source, never consults the commerce catalog, never widens the candidate
set to other pedidos, never invokes the LLM, and never splits or
rewrites the raw observation text. The full literal message remains the
``observation_text`` returned to the orchestrator.

Identity evidence is matched as **contiguous subsequences**, not as
token-set membership: a ``product_match`` requires the full normalized
product name to appear in order in the message, and a ``strict_match``
requires the contiguous run ``<producto> <código o descripción de
presentación>``. A presentation word that only appears elsewhere in the
message (for example as part of a free-text condition such as
``con salsa grande``) is never accepted as disambiguating evidence.
"""
from __future__ import annotations

import re
import unicodedata

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.recognizers.quitar_producto_recognizer import (
    recognize_quitar_producto,
)
from backend.models.session import Session as ConversationSession
from backend.services.pedido_producto_service import PedidoProductoService

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


def _line_tokens(text: str) -> list[str]:
    """Return the normalized, space-split tokens for ``text``.

    The normalization mirrors the recognizer's local clear grammar so the
    identity-evidence comparison uses the same tokenization used by the
    rest of this module: lower-case, diacritics stripped (except ``ñ``),
    non-alphanumeric characters replaced by spaces, collapsed whitespace.
    """
    if not text:
        return []
    normalized = _normalize_for_clear(text)
    return normalized.split() if normalized else []


def _find_contiguous_subsequence(
    haystack: list[str],
    needle: list[str],
) -> bool:
    """Return ``True`` when ``needle`` appears in ``haystack`` as a
    contiguous subsequence, in order.

    Token-set membership is intentionally not used here: a presentation
    word that appears elsewhere in the message must not be allowed to
    disambiguate a line. Only an adjacent ``<producto> <presentación>``
    run can do that.
    """
    if not needle:
        return False
    n = len(needle)
    if n > len(haystack):
        return False
    for i in range(len(haystack) - n + 1):
        if haystack[i : i + n] == needle:
            return True
    return False


def _presentation_phrases(presentacion) -> list[list[str]]:
    """Return the token sequences for the codigo and descripcion of
    ``presentacion``. Each non-empty normalized phrase is a candidate
    presentation phrase for the strict match check.
    """
    phrases: list[list[str]] = []
    if presentacion is None:
        return phrases
    for text in (
        getattr(presentacion, "codigo", "") or "",
        getattr(presentacion, "descripcion", "") or "",
    ):
        tokens = _line_tokens(text)
        if tokens:
            phrases.append(tokens)
    return phrases


def _recover_candidates_by_identity(
    pedido_productos,
    message: str,
) -> list[int]:
    """Bounded identity-evidence recovery for the active draft lines.

    Used only when the existing fuzzy recognizer produces zero
    candidates for an already-classified observation. The recovery is
    deterministic, read-only and runs against the SAME
    ``PedidoProductoService.list_by_pedido`` rows as the fuzzy path.
    It compares normalized full-token evidence already projected on
    those lines (product name, presentation codigo/description,
    category description) against the full raw classified message; it
    never splits the message on a verb or condition word, never
    consults the commerce catalog, never queries another pedido, never
    invokes an LLM, and never widens the candidate universe.

    Matching rules:

    1. ``product_match``: the full normalized product name must appear
       in the message as a contiguous subsequence, in order. Token-set
       membership alone is never sufficient. Category evidence alone
       is never sufficient (it does not enter the comparison).
    2. ``strict_match``: the line is a strict match only when its
       product name and a presentation phrase (codigo or description)
       appear in the message as the contiguous subsequence
       ``<nombre de producto> <código o descripción de presentación>``.
       A presentation word that appears elsewhere in the message is
       never accepted as disambiguating evidence.
    3. When at least one strict match exists, strict matches are the
       candidate set. When none exists, product-only matches are the
       candidate set, so an insufficient presentation disambiguation
       flows into the existing pending order-line selection path.
    4. The function returns a sorted list of unique
       ``pedido_producto_id`` values; ``[]`` when no identity
       evidence survives.
    """
    message_tokens = _line_tokens(message)
    if not message_tokens:
        return []

    product_matches: list[int] = []
    strict_matches: list[int] = []

    for pp in pedido_productos or []:
        pp_id = getattr(pp, "id", None)
        if pp_id is None:
            continue
        producto_presentacion = getattr(pp, "producto_presentacion", None)
        producto = (
            getattr(producto_presentacion, "producto", None)
            if producto_presentacion
            else None
        )
        presentacion = (
            getattr(producto_presentacion, "presentacion", None)
            if producto_presentacion
            else None
        )

        product_tokens = _line_tokens(getattr(producto, "nombre", "") or "")
        if not product_tokens:
            continue
        if not _find_contiguous_subsequence(message_tokens, product_tokens):
            continue
        product_matches.append(int(pp_id))

        for phrase in _presentation_phrases(presentacion):
            combined = product_tokens + phrase
            if _find_contiguous_subsequence(message_tokens, combined):
                strict_matches.append(int(pp_id))
                break

    if strict_matches:
        return sorted(set(strict_matches))
    return sorted(set(product_matches))


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

    When the bounded fuzzy path yields zero ``pedido_producto_id``
    candidates for an already-classified observation, the recognizer
    runs the deterministic identity-evidence recovery
    (``_recover_candidates_by_identity``) against the SAME active draft
    ``PedidoProducto`` rows. The full raw message remains the
    ``observation_text`` returned to the orchestrator; the recovery
    never alters, splits, or rewrites it.
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

    if not unique_ids:
        pedido_productos = PedidoProductoService(db).list_by_pedido(pedido_id)
        if pedido_productos:
            recovered_ids = _recover_candidates_by_identity(
                pedido_productos, message
            )
            unique_ids = recovered_ids

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
