"""Modificar producto handler.

Consumes a ready `modificar_producto` `ProcessedIntent`, validates the
resolved `pedido_producto_origen_id`, `producto_presentacion_destino_id`,
and optional `cantidad`, then delegates the atomic mutation to
`PedidoProductoService.modify_product`. Translates the service's
`ModificationResult` into `executed`, `rejected`, or `failed` statuses.

The handler never issues SQLAlchemy queries directly (no SELECT, no
eager-load helpers, no repository imports), never performs source decrement and
destination increment manually, and never commits, rolls back, flushes,
refreshes, expires, begins, closes the session, or generates a customer-
facing response.

Source quantity re-read invariant: when the resolved intent carries
`cantidad is None`, the handler re-reads the current
`PedidoProducto.cantidad` for the resolved source line inside the same
transaction boundary, immediately before invoking the service. The
re-read value is the authoritative transfer quantity; the handler NEVER
substitutes `1` for an omitted quantity.
"""
from typing import Any

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models import PedidoProducto
from backend.models.session import Session as ConversationSession
from backend.services.exceptions import ModificationFailed
from backend.services.modification_result import ModificationResult
from backend.services.pedido_producto_service import PedidoProductoService


def _with_status(intent: ProcessedIntent, status: str) -> ProcessedIntent:
    return intent.model_copy(update={"status": status})


def _rejected_enriched(
    intent: ProcessedIntent,
    reason: str,
    *,
    cantidad_actual: int | None = None,
    producto_origen_nombre: str | None = None,
    presentacion_origen: str | None = None,
) -> ProcessedIntent:
    new_resolved_data = dict(intent.resolved_data)
    new_resolved_data["reason"] = reason
    if cantidad_actual is not None:
        new_resolved_data["cantidad_actual"] = cantidad_actual
    if producto_origen_nombre is not None:
        new_resolved_data["producto_origen_nombre"] = producto_origen_nombre
    if presentacion_origen is not None:
        new_resolved_data["presentacion_origen"] = presentacion_origen
    return intent.model_copy(
        update={"status": "rejected", "resolved_data": new_resolved_data}
    )


def _executed_enriched(
    intent: ProcessedIntent,
    result: ModificationResult,
) -> ProcessedIntent:
    new_resolved_data = dict(intent.resolved_data)
    new_resolved_data["producto_origen_nombre"] = result.producto_origen_nombre
    new_resolved_data["presentacion_origen"] = result.presentacion_origen
    new_resolved_data["producto_destino_nombre"] = result.producto_destino_nombre
    new_resolved_data["presentacion_destino"] = result.presentacion_destino
    new_resolved_data["cantidad_modificada"] = result.cantidad_modificada
    new_resolved_data["cantidad_origen_restante"] = result.cantidad_origen_restante
    new_resolved_data["cantidad_destino_final"] = result.cantidad_destino_final
    new_resolved_data["origen_eliminado"] = result.origen_eliminado
    new_resolved_data["destino_creado"] = result.destino_creado
    return intent.model_copy(
        update={"status": "executed", "resolved_data": new_resolved_data}
    )


def _reread_source_cantidad(
    db: DatabaseSession,
    pedido_id: int,
    pedido_producto_origen_id: int,
) -> int | None:
    """Re-read the current `PedidoProducto.cantidad` for the resolved source
    line inside the same transaction boundary.

    Returns the current quantity, or `None` when the line cannot be found
    in the supplied Pedido. This is the authoritative source quantity for
    the modify path; the handler never substitutes `1` for an omitted
    quantity.
    """
    source = db.get(PedidoProducto, int(pedido_producto_origen_id))
    if source is None:
        return None
    if getattr(source, "id_pedido", None) != int(pedido_id):
        return None
    return source.cantidad


def execute_modificar_producto(
    db: DatabaseSession,
    conversation_session: ConversationSession,
    intent: ProcessedIntent,
) -> ProcessedIntent:
    if (
        intent.intent != "modificar_producto"
        or intent.status != "ready"
        or intent.handler != "modificar_producto"
    ):
        return _with_status(intent, "rejected")

    source_id = intent.resolved_data.get("pedido_producto_origen_id")
    dest_id = intent.resolved_data.get("producto_presentacion_destino_id")

    if isinstance(source_id, bool) or not isinstance(source_id, int):
        return _with_status(intent, "rejected")
    if isinstance(dest_id, bool) or not isinstance(dest_id, int):
        return _with_status(intent, "rejected")

    cantidad = intent.resolved_data.get("cantidad")
    if cantidad is not None:
        if isinstance(cantidad, bool) or not isinstance(cantidad, int):
            return _with_status(intent, "rejected")
        if cantidad <= 0:
            return _with_status(intent, "rejected")

    pedido_id = conversation_session.id_pedido
    if pedido_id is None:
        return _with_status(intent, "rejected")

    effective_cantidad: Any = None
    if isinstance(cantidad, int):
        effective_cantidad = cantidad
    else:
        # Source quantity re-read invariant: when the user omits the
        # quantity, the handler re-reads the current source quantity inside
        # the same transaction boundary. The re-read value is the
        # authoritative transfer quantity; the handler NEVER substitutes
        # `1` for an omitted quantity. When the re-read yields nothing
        # (the source is missing or belongs to a different Pedido), the
        # handler passes `None` so the service can re-validate and the
        # caller receives a deterministic business rejection.
        reread = _reread_source_cantidad(db, int(pedido_id), int(source_id))
        if reread is not None:
            effective_cantidad = reread

    try:
        result = PedidoProductoService(db).modify_product(
            int(pedido_id),
            int(source_id),
            int(dest_id),
            effective_cantidad,
        )
    except ModificationFailed:
        return _with_status(intent, "failed")

    if result.status == "rejected":
        return _rejected_enriched(
            intent,
            result.reason or "rejected",
            cantidad_actual=result.cantidad_actual,
            producto_origen_nombre=result.producto_origen_nombre,
            presentacion_origen=result.presentacion_origen,
        )

    return _executed_enriched(intent, result)


__all__ = ["execute_modificar_producto"]


# Explicit guard: this module must never import the source/decrement helpers
# from the `quitar_producto` or `agregar_producto` handlers. The handler
# composes the modification in a single atomic service call only.
__forbidden_handlers__ = (
    "execute_quitar_producto",
    "execute_agregar_producto",
)
