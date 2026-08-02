from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.schemas.customer_response import CustomerResponse
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession
from backend.services.producto_query_service import ProductoQueryService

_CLARIFICATION_PREFIX = "Elegí entre:"
_APOLOGY_MESSAGE = "No pude procesar tu pedido, ¿podrías reformularlo?"
_RETRY_MESSAGE = "Tuve un problema técnico, ¿podrías intentarlo de nuevo en unos minutos?"
_CONFIRMATION_PREFIX = "Listo,"


def build_agregar_producto_response(
    db: DatabaseSession,
    session: ConversationSession,
    intent: ProcessedIntent,
) -> CustomerResponse:
    if intent.intent != "agregar_producto":
        return CustomerResponse(
            message=_APOLOGY_MESSAGE,
            intent=intent.intent,
            status=intent.status,
        )

    if intent.status == "pending_resolution":
        if not intent.candidate_ids:
            return CustomerResponse(
                message=_APOLOGY_MESSAGE,
                intent="agregar_producto",
                status="pending_resolution",
            )
        presentations = ProductoQueryService(db).list_presentaciones_by_ids(
            intent.candidate_ids
        )
        labels = [
            f"{presentation['producto_nombre']} {presentation['presentacion_descripcion']}"
            for presentation in presentations
        ]
        if not labels:
            return CustomerResponse(
                message=_APOLOGY_MESSAGE,
                intent="agregar_producto",
                status="pending_resolution",
            )
        options = labels[0] if len(labels) == 1 else f"{', '.join(labels[:-1])} o {labels[-1]}"
        return CustomerResponse(
            message=f"{_CLARIFICATION_PREFIX} {options}",
            intent="agregar_producto",
            status="pending_resolution",
        )

    if intent.status == "executed":
        producto_presentacion_id = intent.resolved_data.get("producto_presentacion_id")
        cantidad_final = intent.resolved_data.get("cantidad_final")
        if type(cantidad_final) is not int:
            cantidad_final = intent.resolved_data.get("cantidad")
        cantidad = cantidad_final
        if (
            type(producto_presentacion_id) is not int
            or type(cantidad) is not int
            or cantidad < 1
        ):
            return CustomerResponse(
                message=_RETRY_MESSAGE,
                intent="agregar_producto",
                status="failed",
            )
        presentations = ProductoQueryService(db).list_presentaciones_by_ids(
            [producto_presentacion_id]
        )
        if not presentations:
            return CustomerResponse(
                message=_RETRY_MESSAGE,
                intent="agregar_producto",
                status="failed",
            )
        presentation = presentations[0]
        label = f"{presentation['producto_nombre']} {presentation['presentacion_descripcion']}"
        if cantidad == 1:
            message = f"{_CONFIRMATION_PREFIX} agregué 1 {label}."
        else:
            message = f"{_CONFIRMATION_PREFIX} se agregaron {cantidad} {label}."
        return CustomerResponse(
            message=message,
            intent="agregar_producto",
            status="executed",
        )

    if intent.status == "failed":
        return CustomerResponse(
            message=_RETRY_MESSAGE,
            intent="agregar_producto",
            status="failed",
        )

    return CustomerResponse(
        message=_APOLOGY_MESSAGE,
        intent="agregar_producto",
        status=intent.status,
    )


__all__ = ["build_agregar_producto_response"]
