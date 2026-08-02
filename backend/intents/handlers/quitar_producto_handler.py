"""Quitar producto handler.

Consumes a ready `quitar_producto` `ProcessedIntent`, validates the resolved
`pedido_producto_id` and optional `cantidad`, and decrements or deletes the
matching `PedidoProducto` row through the existing `PedidoProductoService`.
Translates outcomes into `executed`, `rejected`, or `failed` statuses.

The handler:
- never queries SQLAlchemy directly or accesses the repository;
- never raises HTTP errors or catches broad `Exception` to translate it;
- never commits, rolls back, flushes, closes, or generates a response;
- never clears pending context or promotes queues.
"""
from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession
from backend.services.exceptions import (
    PedidoNotFound,
    PedidoProductoNotEditable,
    PedidoProductoNotFound,
)
from backend.services.pedido_producto_service import PedidoProductoService


def _with_status(intent: ProcessedIntent, status: str) -> ProcessedIntent:
    return intent.model_copy(update={"status": status})


def _enrich_resolved_data(
    intent: ProcessedIntent,
    *,
    producto_nombre: str,
    presentacion_codigo: str,
    presentacion_descripcion: str,
    cantidad_removida: int,
    cantidad_restante: int,
    linea_eliminada: bool,
) -> dict:
    return {
        **intent.resolved_data,
        "producto_nombre": producto_nombre,
        "presentacion_codigo": presentacion_codigo,
        "presentacion_descripcion": presentacion_descripcion,
        "cantidad_removida": cantidad_removida,
        "cantidad_restante": cantidad_restante,
        "linea_eliminada": linea_eliminada,
    }


def execute_quitar_producto(
    db: DatabaseSession,
    conversation_session: ConversationSession,
    intent: ProcessedIntent,
) -> ProcessedIntent:
    if (
        intent.intent != "quitar_producto"
        or intent.status != "ready"
        or intent.handler != "quitar_producto"
    ):
        return _with_status(intent, "rejected")

    raw_pedido_producto_id = intent.resolved_data.get("pedido_producto_id")
    if isinstance(raw_pedido_producto_id, bool) or not isinstance(
        raw_pedido_producto_id, int
    ):
        return _with_status(intent, "rejected")

    cantidad_value = intent.resolved_data.get("cantidad")
    if cantidad_value is not None:
        if isinstance(cantidad_value, bool) or not isinstance(cantidad_value, int):
            return _with_status(intent, "rejected")
        if cantidad_value <= 0:
            return _with_status(intent, "rejected")

    pedido_id = conversation_session.id_pedido
    if pedido_id is None:
        return _with_status(intent, "rejected")

    try:
        current = PedidoProductoService(db).get_for_pedido(
            pedido_id, raw_pedido_producto_id
        )
    except (PedidoProductoNotFound, PedidoNotFound):
        return _with_status(intent, "rejected")
    except Exception:
        return _with_status(intent, "failed")

    producto_presentacion = current.producto_presentacion
    presentacion = producto_presentacion.presentacion
    producto = producto_presentacion.producto
    producto_nombre = producto.nombre
    presentacion_codigo = presentacion.codigo
    presentacion_descripcion = presentacion.descripcion
    current_cantidad = current.cantidad

    if cantidad_value is None or cantidad_value == current_cantidad:
        try:
            PedidoProductoService(db).delete(current.id)
        except (PedidoProductoNotFound, PedidoNotFound, PedidoProductoNotEditable):
            return _with_status(intent, "rejected")
        except Exception:
            return _with_status(intent, "failed")

        enriched = _enrich_resolved_data(
            intent,
            producto_nombre=producto_nombre,
            presentacion_codigo=presentacion_codigo,
            presentacion_descripcion=presentacion_descripcion,
            cantidad_removida=current_cantidad,
            cantidad_restante=0,
            linea_eliminada=True,
        )
        return intent.model_copy(
            update={"status": "executed", "resolved_data": enriched}
        )

    if cantidad_value < current_cantidad:
        try:
            PedidoProductoService(db).update(
                current.id,
                cantidad=current_cantidad - cantidad_value,
                observaciones=None,
            )
        except (PedidoProductoNotFound, PedidoNotFound, PedidoProductoNotEditable):
            return _with_status(intent, "rejected")
        except Exception:
            return _with_status(intent, "failed")

        enriched = _enrich_resolved_data(
            intent,
            producto_nombre=producto_nombre,
            presentacion_codigo=presentacion_codigo,
            presentacion_descripcion=presentacion_descripcion,
            cantidad_removida=cantidad_value,
            cantidad_restante=current_cantidad - cantidad_value,
            linea_eliminada=False,
        )
        return intent.model_copy(
            update={"status": "executed", "resolved_data": enriched}
        )

    enriched = {
        **intent.resolved_data,
        "cantidad_actual": current_cantidad,
        "producto_nombre": producto_nombre,
        "presentacion_codigo": presentacion_codigo,
        "presentacion_descripcion": presentacion_descripcion,
    }
    return intent.model_copy(
        update={"status": "rejected", "resolved_data": enriched}
    )


__all__ = ["execute_quitar_producto"]