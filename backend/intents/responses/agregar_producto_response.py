from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.schemas.customer_response import CustomerResponse
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession
from backend.services.producto_query_service import ProductoQueryService

_CLARIFICATION_PREFIX = "Elegí entre:"
_APOLOGY_MESSAGE = "No pude procesar tu pedido, ¿podrías reformularlo?"
_RETRY_MESSAGE = "Tuve un problema técnico, ¿podrías intentarlo de nuevo en unos minutos?"
_CONFIRMATION_PREFIX = "Listo,"


def _safe_positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, int):
        return None
    if value < 1:
        return None
    return value


def _retry_response() -> CustomerResponse:
    return CustomerResponse(
        message=_RETRY_MESSAGE,
        intent="agregar_producto",
        status="failed",
    )


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
        if type(producto_presentacion_id) is not int:
            return _retry_response()

        has_modern_keys = "cantidad_agregada" in intent.resolved_data

        if has_modern_keys:
            cantidad_agregada = _safe_positive_int(
                intent.resolved_data.get("cantidad_agregada")
            )
            cantidad_final_modern = _safe_positive_int(
                intent.resolved_data.get("cantidad_final")
            )
            if (
                cantidad_agregada is None
                or cantidad_final_modern is None
                or cantidad_agregada > cantidad_final_modern
            ):
                return _retry_response()
            delta_clause_quantity = cantidad_agregada
            total_clause_quantity = (
                cantidad_final_modern
                if cantidad_agregada != cantidad_final_modern
                else None
            )
        else:
            legacy_quantity = _safe_positive_int(
                intent.resolved_data.get("cantidad_final")
            )
            if legacy_quantity is None:
                legacy_quantity = _safe_positive_int(
                    intent.resolved_data.get("cantidad")
                )
            if legacy_quantity is None:
                return _retry_response()
            delta_clause_quantity = legacy_quantity
            total_clause_quantity = None

        presentations = ProductoQueryService(db).list_presentaciones_by_ids(
            [producto_presentacion_id]
        )
        if not presentations:
            return _retry_response()
        presentation = presentations[0]
        label = f"{presentation['producto_nombre']} {presentation['presentacion_descripcion']}"
        if delta_clause_quantity == 1:
            delta_message = f"{_CONFIRMATION_PREFIX} agregué 1 {label}."
        else:
            delta_message = (
                f"{_CONFIRMATION_PREFIX} se agregaron {delta_clause_quantity} {label}."
            )
        if total_clause_quantity is None:
            message = delta_message
        else:
            message = f"{delta_message} Ahora tenés {total_clause_quantity}."
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
