"""Quitar producto response builder.

Renders a single fixed Spanish `CustomerResponse` for every
`ProcessedIntent.status` outcome produced by the `quitar_producto` pipeline.
No LLM, no prompt construction, no technical detail in the rendered message.
"""
from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.schemas.customer_response import CustomerResponse
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession
from backend.services.pedido_producto_service import PedidoProductoService


_CLARIFICATION_PREFIX = "¿Cuál querés quitar:"
_ABSENT_MESSAGE = "Ese producto no está en tu pedido."
_FAILED_MESSAGE = "No pude procesar tu pedido. Intentá de nuevo en un momento."


def _format_candidate(label: dict) -> str | None:
    nombre = label.get("producto_nombre")
    codigo = label.get("presentacion_codigo")
    if not isinstance(nombre, str) or not isinstance(codigo, str):
        return None
    return f"{nombre} ({codigo})"


def _render_clarification(candidate_ids: list[int], labels_by_id: dict[int, dict]) -> str:
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


def _render_partial(intent: ProcessedIntent) -> str:
    data = intent.resolved_data
    producto_nombre = data.get("producto_nombre", "")
    presentacion_codigo = data.get("presentacion_codigo", "")
    cantidad_removida = data.get("cantidad_removida")
    cantidad_restante = data.get("cantidad_restante")
    if not isinstance(cantidad_removida, int) or not isinstance(cantidad_restante, int):
        return _FAILED_MESSAGE
    return (
        f"Quité {cantidad_removida} {producto_nombre} ({presentacion_codigo}). "
        f"Queda {cantidad_restante} en tu pedido."
    )


def _render_complete(intent: ProcessedIntent) -> str:
    data = intent.resolved_data
    producto_nombre = data.get("producto_nombre", "")
    presentacion_codigo = data.get("presentacion_codigo", "")
    return f"Quité {producto_nombre} ({presentacion_codigo}) de tu pedido."


def _render_excess_rejection(intent: ProcessedIntent) -> str:
    data = intent.resolved_data
    cantidad_actual = data.get("cantidad_actual")
    producto_nombre = data.get("producto_nombre", "")
    presentacion_codigo = data.get("presentacion_codigo", "")
    if not isinstance(cantidad_actual, int):
        return _ABSENT_MESSAGE
    return (
        f"Solo tenés {cantidad_actual} {producto_nombre} ({presentacion_codigo}) en el pedido."
    )


def _is_intent_quitar_producto(intent: ProcessedIntent) -> bool:
    return intent.intent == "quitar_producto"


def build_quitar_producto_response(
    db: DatabaseSession,
    session: ConversationSession,
    intent: ProcessedIntent,
) -> CustomerResponse:
    """Render the deterministic Spanish message for a `quitar_producto` intent.

    Returns a `CustomerResponse` whose `intent` is always `"quitar_producto"`
    and whose `status` mirrors the source `intent.status`.
    """
    if not _is_intent_quitar_producto(intent):
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent=intent.intent,
            status=intent.status,
        )

    if intent.status == "pending_resolution":
        pedido_id = session.id_pedido
        labels_by_id: dict[int, dict] = {}
        if pedido_id is not None:
            try:
                for pp in PedidoProductoService(db).list_by_pedido(pedido_id):
                    producto_presentacion = pp.producto_presentacion
                    presentacion = producto_presentacion.presentacion
                    producto = producto_presentacion.producto
                    labels_by_id[pp.id] = {
                        "producto_nombre": producto.nombre,
                        "presentacion_codigo": presentacion.codigo,
                    }
            except Exception:
                labels_by_id = {}
        message = _render_clarification(intent.candidate_ids, labels_by_id)
        return CustomerResponse(
            message=message,
            intent="quitar_producto",
            status="pending_resolution",
        )

    if intent.status == "executed":
        if intent.resolved_data.get("linea_eliminada") is True:
            message = _render_complete(intent)
        else:
            message = _render_partial(intent)
        return CustomerResponse(
            message=message,
            intent="quitar_producto",
            status="executed",
        )

    if intent.status == "rejected":
        data = intent.resolved_data
        if (
            "cantidad_actual" in data
            and isinstance(data.get("cantidad_actual"), int)
            and data.get("producto_nombre") is not None
            and data.get("presentacion_codigo") is not None
        ):
            message = _render_excess_rejection(intent)
        else:
            message = _ABSENT_MESSAGE
        return CustomerResponse(
            message=message,
            intent="quitar_producto",
            status="rejected",
        )

    if intent.status == "failed":
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent="quitar_producto",
            status="failed",
        )

    return CustomerResponse(
        message=_FAILED_MESSAGE,
        intent="quitar_producto",
        status=intent.status,
    )


__all__ = ["build_quitar_producto_response"]