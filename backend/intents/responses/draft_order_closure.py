"""Guided draft-order closure response builders.

Each builder renders a single fixed Spanish `CustomerResponse` for every
`ProcessedIntent.status` outcome produced by the
`backend.intents.orchestration.draft_order_closure` orchestrators. No LLM,
no prompt construction, no technical detail, no DB IDs in the rendered
message. Missing/ambiguous/inactive/foreign outcomes are non-mutating
business responses that ask for a single scoped choice.
"""
from __future__ import annotations

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.schemas.customer_response import CustomerResponse
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession

_FAILED_MESSAGE = "Tuve un problema técnico, ¿podrías intentarlo de nuevo en unos minutos?"
_NO_DRAFT_MESSAGE = "Todavía no tenés un pedido activo."
_NOT_BORRADOR_MESSAGE = "Tu pedido ya fue confirmado y no se puede modificar."
_EMPTY_DRAFT_MESSAGE = "Tu pedido está vacío. Agregá productos antes de confirmarlo."
_MISSING_PAYMENT_MESSAGE = "Elegí un medio de pago antes de confirmar el pedido."
_MISSING_DELIVERY_MESSAGE = "Elegí un método de entrega antes de confirmar el pedido."
_FOREIGN_PAYMENT_MESSAGE = (
    "Ese medio de pago ya no está disponible para este comercio. "
    "Elegí uno habilitado."
)
_FOREIGN_DELIVERY_MESSAGE = (
    "Ese método de entrega ya no está disponible para este comercio. "
    "Elegí uno habilitado."
)
_AMBIGUOUS_PAYMENT_PROMPT = "Indicá un único medio de pago. Opciones disponibles:"
_AMBIGUOUS_DELIVERY_PROMPT = "Indicá un único método de entrega. Opciones disponibles:"
_PAYMENT_MISSING_PROMPT = (
    "Indicá el medio de pago que querés usar. Opciones disponibles:"
)
_DELIVERY_MISSING_PROMPT = (
    "Indicá el método de entrega que querés usar. Opciones disponibles:"
)
_PAYMENT_NOT_ACTIVE_MESSAGE = (
    "Ese medio de pago no está disponible. Elegí uno habilitado para este comercio."
)
_DELIVERY_NOT_ACTIVE_MESSAGE = (
    "Ese método de entrega no está disponible. Elegí uno habilitado para este comercio."
)


def _format_option(opcion: dict) -> str | None:
    codigo = opcion.get("codigo")
    descripcion = opcion.get("descripcion")
    if not isinstance(codigo, str) or not isinstance(descripcion, str):
        return None
    return f"{codigo} ({descripcion})"


def _join_options(opciones: list[dict]) -> list[str]:
    formatted: list[str] = []
    for opcion in opciones:
        text = _format_option(opcion)
        if text is not None:
            formatted.append(text)
    return formatted


def _render_options_list(prompt: str, opciones: list[dict]) -> str:
    formatted = _join_options(opciones)
    if not formatted:
        return f"{prompt} (sin opciones disponibles)"
    if len(formatted) == 1:
        return f"{prompt} {formatted[0]}"
    if len(formatted) == 2:
        return f"{prompt} {formatted[0]} o {formatted[1]}"
    return f"{prompt} {', '.join(formatted[:-1])} o {formatted[-1]}"


def _extract_opciones(intent: ProcessedIntent) -> list[dict]:
    opciones = intent.resolved_data.get("opciones") or []
    return [op for op in opciones if isinstance(op, dict)]


def build_consultar_resumen_pedido_response(
    db: DatabaseSession,
    session: ConversationSession,
    intent: ProcessedIntent,
) -> CustomerResponse:
    if intent.intent != "consultar_resumen_pedido":
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent=intent.intent,
            status=intent.status,
        )
    if intent.status == "rejected":
        reason = intent.resolved_data.get("reason")
        if reason == "no_draft":
            message = _NO_DRAFT_MESSAGE
        elif reason == "pedido_not_borrador":
            message = _NOT_BORRADOR_MESSAGE
        else:
            message = _FAILED_MESSAGE
        return CustomerResponse(
            message=message,
            intent="consultar_resumen_pedido",
            status="rejected",
        )
    if intent.status == "executed":
        if not bool(intent.resolved_data.get("tiene_lineas")):
            return CustomerResponse(
                message=_EMPTY_DRAFT_MESSAGE,
                intent="consultar_resumen_pedido",
                status="executed",
            )
        lineas = intent.resolved_data.get("lineas") or []
        bullet_lines: list[str] = []
        for line in lineas:
            nombre = line.get("producto_nombre") if isinstance(line, dict) else None
            codigo = line.get("presentacion_codigo") if isinstance(line, dict) else None
            cantidad = line.get("cantidad") if isinstance(line, dict) else None
            if (
                not isinstance(nombre, str)
                or not isinstance(codigo, str)
                or not isinstance(cantidad, int)
            ):
                continue
            bullet_lines.append(f"- {cantidad} {nombre} ({codigo})")
        medio_pago = intent.resolved_data.get("medio_pago")
        metodo_entrega = intent.resolved_data.get("metodo_entrega")
        if not bullet_lines:
            return CustomerResponse(
                message=_EMPTY_DRAFT_MESSAGE,
                intent="consultar_resumen_pedido",
                status="executed",
            )
        parts: list[str] = ["Tu pedido:"]
        parts.extend(bullet_lines)
        if isinstance(medio_pago, str):
            parts.append(f"Pago: {medio_pago}")
        if isinstance(metodo_entrega, str):
            parts.append(f"Entrega: {metodo_entrega}")
        return CustomerResponse(
            message="\n".join(parts),
            intent="consultar_resumen_pedido",
            status="executed",
        )
    if intent.status == "failed":
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent="consultar_resumen_pedido",
            status="failed",
        )
    return CustomerResponse(
        message=_FAILED_MESSAGE,
        intent="consultar_resumen_pedido",
        status=intent.status,
    )


def _build_set_choice_response(
    intent: ProcessedIntent,
    *,
    intent_name: str,
    missing_prompt: str,
    ambiguous_prompt: str,
    not_active_message: str,
    not_borrador_message: str,
    confirmation_prefix: str,
) -> CustomerResponse:
    if intent.status == "rejected":
        reason = intent.resolved_data.get("reason")
        if reason == "no_draft":
            message = _NO_DRAFT_MESSAGE
        elif reason == "pedido_not_borrador":
            message = not_borrador_message
        elif reason == "missing":
            message = _render_options_list(
                missing_prompt, _extract_opciones(intent)
            )
        elif reason == "ambiguous":
            message = _render_options_list(
                ambiguous_prompt, _extract_opciones(intent)
            )
        elif reason in ("not_active", "inactive_for_comercio"):
            message = not_active_message
        else:
            message = _FAILED_MESSAGE
        return CustomerResponse(
            message=message,
            intent=intent_name,
            status="rejected",
        )
    if intent.status == "executed":
        codigo = intent.resolved_data.get("codigo")
        descripcion = intent.resolved_data.get("descripcion")
        if isinstance(codigo, str) and isinstance(descripcion, str):
            message = f"{confirmation_prefix} {codigo} ({descripcion})."
        else:
            message = _FAILED_MESSAGE
        return CustomerResponse(
            message=message,
            intent=intent_name,
            status="executed",
        )
    if intent.status == "failed":
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent=intent_name,
            status="failed",
        )
    return CustomerResponse(
        message=_FAILED_MESSAGE,
        intent=intent_name,
        status=intent.status,
    )


def build_set_metodo_de_pago_response(
    db: DatabaseSession,
    session: ConversationSession,
    intent: ProcessedIntent,
) -> CustomerResponse:
    if intent.intent != "set_metodo_de_pago":
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent=intent.intent,
            status=intent.status,
        )
    return _build_set_choice_response(
        intent,
        intent_name="set_metodo_de_pago",
        missing_prompt=_PAYMENT_MISSING_PROMPT,
        ambiguous_prompt=_AMBIGUOUS_PAYMENT_PROMPT,
        not_active_message=_PAYMENT_NOT_ACTIVE_MESSAGE,
        not_borrador_message=_NOT_BORRADOR_MESSAGE,
        confirmation_prefix="Listo, medio de pago elegido:",
    )


def build_set_metodo_de_entrega_response(
    db: DatabaseSession,
    session: ConversationSession,
    intent: ProcessedIntent,
) -> CustomerResponse:
    if intent.intent != "set_metodo_de_entrega":
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent=intent.intent,
            status=intent.status,
        )
    return _build_set_choice_response(
        intent,
        intent_name="set_metodo_de_entrega",
        missing_prompt=_DELIVERY_MISSING_PROMPT,
        ambiguous_prompt=_AMBIGUOUS_DELIVERY_PROMPT,
        not_active_message=_DELIVERY_NOT_ACTIVE_MESSAGE,
        not_borrador_message=_NOT_BORRADOR_MESSAGE,
        confirmation_prefix="Listo, método de entrega elegido:",
    )


def build_confirmar_pedido_response(
    db: DatabaseSession,
    session: ConversationSession,
    intent: ProcessedIntent,
) -> CustomerResponse:
    if intent.intent != "confirmar_pedido":
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent=intent.intent,
            status=intent.status,
        )
    if intent.status == "rejected":
        reason = intent.resolved_data.get("reason")
        if reason == "no_draft":
            message = _NO_DRAFT_MESSAGE
        elif reason == "pedido_not_borrador":
            message = _NOT_BORRADOR_MESSAGE
        elif reason == "empty_draft":
            message = _EMPTY_DRAFT_MESSAGE
        elif reason == "missing_payment":
            message = _MISSING_PAYMENT_MESSAGE
        elif reason == "missing_delivery":
            message = _MISSING_DELIVERY_MESSAGE
        elif reason == "payment_not_active_for_comercio":
            message = _FOREIGN_PAYMENT_MESSAGE
        elif reason == "delivery_not_active_for_comercio":
            message = _FOREIGN_DELIVERY_MESSAGE
        else:
            message = _FAILED_MESSAGE
        return CustomerResponse(
            message=message,
            intent="confirmar_pedido",
            status="rejected",
        )
    if intent.status == "executed":
        return CustomerResponse(
            message="Listo, confirmamos tu pedido.",
            intent="confirmar_pedido",
            status="executed",
        )
    if intent.status == "failed":
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent="confirmar_pedido",
            status="failed",
        )
    return CustomerResponse(
        message=_FAILED_MESSAGE,
        intent="confirmar_pedido",
        status=intent.status,
    )


_OBSERVATION_SUCCESS_MESSAGE = "Listo, guardé tu observación."
_OBSERVATION_REJECTION_MESSAGE = (
    "No pude guardar tu observación. Tu pedido no fue modificado."
)


def build_set_observacion_pedido_response(
    db: DatabaseSession,
    session: ConversationSession,
    intent: ProcessedIntent,
) -> CustomerResponse:
    if intent.intent != "set_observacion_pedido":
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent=intent.intent,
            status=intent.status,
        )
    if intent.status == "rejected":
        return CustomerResponse(
            message=_OBSERVATION_REJECTION_MESSAGE,
            intent="set_observacion_pedido",
            status="rejected",
        )
    if intent.status == "executed":
        return CustomerResponse(
            message=_OBSERVATION_SUCCESS_MESSAGE,
            intent="set_observacion_pedido",
            status="executed",
        )
    if intent.status == "failed":
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent="set_observacion_pedido",
            status="failed",
        )
    return CustomerResponse(
        message=_FAILED_MESSAGE,
        intent="set_observacion_pedido",
        status=intent.status,
    )


__all__ = [
    "build_confirmar_pedido_response",
    "build_consultar_resumen_pedido_response",
    "build_set_metodo_de_entrega_response",
    "build_set_metodo_de_pago_response",
    "build_set_observacion_pedido_response",
]
