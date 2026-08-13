from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession
from backend.observability.events import (
    COMPONENT_PRODUCT_ADD_EXECUTION,
    EVENT_PRODUCT_ADD_EXECUTION,
    emit_event,
)
from backend.services.pedido_producto_service import PedidoProductoService
from backend.services.product_add_result import (
    STATUS_EXECUTED,
    STATUS_REJECTED,
)


def _with_status(intent: ProcessedIntent, status: str) -> ProcessedIntent:
    return intent.model_copy(update={"status": status})


def _safe_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, int):
        return None
    return value


def _emit_product_add_outcome(outcome: str) -> None:
    """Best-effort ``product_add_execution`` emission.

    ``outcome`` is one of the closed allowlist tokens documented in
    the proposal. Emission failure NEVER mutates the handler result
    or the database state; the helper swallows every exception
    (validation, IO, or any unexpected error) so the surrounding
    business flow keeps the same outcome.
    """
    try:
        emit_event(
            event=EVENT_PRODUCT_ADD_EXECUTION,
            component=COMPONENT_PRODUCT_ADD_EXECUTION,
            outcome=outcome,
        )
    except Exception:  # noqa: BLE001 - emission failure is best effort
        return


_REJECTED_REASON_TO_OUTCOME: dict[str, str] = {
    "rejected_invalid_input": "rejected_invalid_input",
    "rejected_session_or_pedido": "rejected_session_or_pedido",
    "rejected_not_editable": "rejected_not_editable",
    "rejected_missing_presentation": "rejected_missing_presentation",
    "rejected_price_unavailable": "rejected_price_unavailable",
}


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

    producto_presentacion_id = _safe_int(
        intent.resolved_data.get("producto_presentacion_id")
    )
    cantidad = _safe_int(intent.resolved_data.get("cantidad"))
    if (
        producto_presentacion_id is None
        or producto_presentacion_id <= 0
        or cantidad is None
        or cantidad <= 0
    ):
        _emit_product_add_outcome("rejected_invalid_input")
        return _with_status(intent, "rejected")

    pedido_id = conversation_session.id_pedido
    if pedido_id is None:
        _emit_product_add_outcome("rejected_session_or_pedido")
        return _with_status(intent, "rejected")

    result = PedidoProductoService(db).stage_add_or_increment_for_session(
        session_id=int(conversation_session.id),
        pedido_id=pedido_id,
        id_producto_presentacion=producto_presentacion_id,
        cantidad=cantidad,
    )

    if result.status == STATUS_REJECTED:
        outcome = _REJECTED_REASON_TO_OUTCOME.get(
            result.reason or "", "rejected_session_or_pedido"
        )
        _emit_product_add_outcome(outcome)
        return _with_status(intent, "rejected")

    if result.status == STATUS_EXECUTED:
        outcome = "created" if result.linea_creada else "incremented"
        _emit_product_add_outcome(outcome)
        resolved = dict(intent.resolved_data)
        resolved["cantidad_agregada"] = cantidad
        resolved["cantidad_final"] = result.cantidad_final
        resolved["linea_creada"] = bool(result.linea_creada)
        return intent.model_copy(
            update={"status": "executed", "resolved_data": resolved}
        )

    raise RuntimeError(
        f"unexpected ProductAddResult.status={result.status!r}"
    )


__all__ = ["execute_agregar_producto"]
