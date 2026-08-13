"""Set product-line observation response builder.

Renders a single fixed Spanish ``CustomerResponse`` for every
``ProcessedIntent.status`` outcome produced by the
``set_observacion_producto`` pipeline. The builder never reproduces the
stored observation text, the database identifier, the session id, or
any raw classifier / LLM output. It reads the order-line product
display labels only from the active ``Pedido`` and only for
clarification prompts.
"""
from __future__ import annotations

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.schemas.customer_response import CustomerResponse
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession
from backend.services.exceptions import PedidoNotFound
from backend.services.pedido_producto_service import PedidoProductoService

_CLARIFICATION_PREFIX = "¿Cuál querés modificar:"
_ABSENT_MESSAGE = "Ese producto no está en tu pedido."
_FAILED_MESSAGE = "No pude procesar tu pedido. Intentá de nuevo en un momento."


def _format_candidate(label: dict) -> str | None:
    nombre = label.get("producto_nombre")
    codigo = label.get("presentacion_codigo")
    if not isinstance(nombre, str) or not isinstance(codigo, str):
        return None
    return f"{nombre} ({codigo})"


def _render_clarification(
    candidate_ids: list[int], labels_by_id: dict[int, dict]
) -> str:
    formatted: list[str] = []
    for cid in candidate_ids:
        label = labels_by_id.get(cid)
        if label is None:
            continue
        candidate_text = _format_candidate(label)
        if candidate_text is not None:
            formatted.append(candidate_text)
    if not formatted:
        return _ABSENT_MESSAGE
    if len(formatted) == 1:
        return f"{_CLARIFICATION_PREFIX} {formatted[0]}?"
    return f"{_CLARIFICATION_PREFIX} {' o '.join(formatted)}?"


def _load_pending_labels(
    db: DatabaseSession, pedido_id: int | None
) -> dict[int, dict]:
    """Return ``pedido_producto_id -> {producto_nombre, presentacion_codigo}``
    for the active pedido, or ``{}`` when nothing can be loaded.

    The lookup is intentionally restricted to the active session's own
    draft pedido and silently degrades to an empty dict when the
    pedido does not exist or the service raises a known domain error;
    no broader broad-exception catch is performed.
    """
    if pedido_id is None:
        return {}
    labels_by_id: dict[int, dict] = {}
    try:
        for pp in PedidoProductoService(db).list_by_pedido(pedido_id):
            producto_presentacion = pp.producto_presentacion
            presentacion = producto_presentacion.presentacion
            producto = producto_presentacion.producto
            labels_by_id[pp.id] = {
                "producto_nombre": producto.nombre,
                "presentacion_codigo": presentacion.codigo,
            }
    except PedidoNotFound:
        labels_by_id = {}
    return labels_by_id


def _is_target_intent(intent: ProcessedIntent) -> bool:
    return intent.intent == "set_observacion_producto"


def build_set_observacion_producto_response(
    db: DatabaseSession,
    session: ConversationSession,
    intent: ProcessedIntent,
) -> CustomerResponse:
    """Render the deterministic Spanish message for the
    ``set_observacion_producto`` intent.

    The rendered ``intent`` is always ``"set_observacion_producto"`` and
    the ``status`` mirrors the source ``intent.status``. The message
    never includes the observation text, the pedido line id, the
    session id, or any diagnostic detail.
    """
    if not _is_target_intent(intent):
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent=intent.intent,
            status=intent.status,
        )

    if intent.status == "pending_resolution":
        labels_by_id = _load_pending_labels(db, session.id_pedido)
        message = _render_clarification(intent.candidate_ids, labels_by_id)
        return CustomerResponse(
            message=message,
            intent="set_observacion_producto",
            status="pending_resolution",
        )

    if intent.status == "executed":
        data = intent.resolved_data
        producto_nombre = data.get("producto_nombre")
        presentacion_codigo = data.get("presentacion_codigo")
        observation_action = data.get("observation_action")
        if (
            isinstance(producto_nombre, str)
            and isinstance(presentacion_codigo, str)
        ):
            if observation_action == "clear":
                message = (
                    f"Eliminé la aclaración de {producto_nombre} "
                    f"({presentacion_codigo})."
                )
            else:
                message = (
                    f"Actualicé la aclaración de {producto_nombre} "
                    f"({presentacion_codigo})."
                )
        else:
            message = _FAILED_MESSAGE
        return CustomerResponse(
            message=message,
            intent="set_observacion_producto",
            status="executed",
        )

    if intent.status == "rejected":
        return CustomerResponse(
            message=_ABSENT_MESSAGE,
            intent="set_observacion_producto",
            status="rejected",
        )

    if intent.status == "failed":
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent="set_observacion_producto",
            status="failed",
        )

    return CustomerResponse(
        message=_FAILED_MESSAGE,
        intent="set_observacion_producto",
        status=intent.status,
    )


__all__ = ["build_set_observacion_producto_response"]
