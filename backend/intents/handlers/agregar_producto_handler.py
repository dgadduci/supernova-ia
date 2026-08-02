from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession
from backend.repositories.pedido_producto_repository import PedidoProductoRepository
from backend.services.exceptions import (
    InvalidCantidad,
    PedidoNotEditable,
    PedidoNotFound,
    PedidoProductoNotEditable,
    PrecioNotFound,
    ProductoPresentacionNotFound,
)
from backend.services.pedido_producto_service import PedidoProductoService


def _with_status(intent: ProcessedIntent, status: str) -> ProcessedIntent:
    return intent.model_copy(update={"status": status})


def execute_agregar_producto(
    db: DatabaseSession,
    conversation_session: ConversationSession,
    intent: ProcessedIntent,
) -> ProcessedIntent:
    if (
        intent.intent != "agregar_producto"
        or intent.status != "ready"
        or intent.handler != "agregar_producto"
    ):
        return _with_status(intent, "rejected")

    producto_presentacion_id = intent.resolved_data.get("producto_presentacion_id")
    cantidad = intent.resolved_data.get("cantidad")
    if (
        isinstance(producto_presentacion_id, bool)
        or not isinstance(producto_presentacion_id, int)
        or isinstance(cantidad, bool)
        or not isinstance(cantidad, int)
        or cantidad <= 0
    ):
        return _with_status(intent, "rejected")

    pedido_id = conversation_session.id_pedido
    if pedido_id is None:
        return _with_status(intent, "rejected")

    existing = PedidoProductoRepository(db).get_by_pedido_and_producto_presentacion(
        pedido_id,
        producto_presentacion_id,
    )
    try:
        row = PedidoProductoService(db).add_or_increment(
            pedido_id,
            producto_presentacion_id,
            cantidad,
            None,
        )
    except (
        PedidoNotFound,
        PedidoNotEditable,
        PedidoProductoNotEditable,
        PrecioNotFound,
        ProductoPresentacionNotFound,
        InvalidCantidad,
    ):
        return _with_status(intent, "rejected")
    except Exception:
        return _with_status(intent, "failed")

    resolved = dict(intent.resolved_data)
    resolved["cantidad_agregada"] = cantidad
    resolved["cantidad_final"] = row.cantidad
    resolved["linea_creada"] = existing is None
    return intent.model_copy(update={"status": "executed", "resolved_data": resolved})


__all__ = ["execute_agregar_producto"]
