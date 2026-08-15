"""Pure deterministic Spanish response builders for the informational
commerce queries handled by
:mod:`backend.intents.orchestration.informational_commerce_queries`.

The builders are intentionally pure: they only inspect a
:class:`ProcessedIntent` (and never the raw classified message), they
do not import the database, the LLM, the classifier, the session or
any handler / recognizer, and they never log raw customer text or
rendered text.

The rendered message is a single fixed Spanish string per
``(intent, status, reason)`` tuple so local and provider traffic share
the same deterministic output. No DB IDs, technical detail, raw
message content or other implementation traces appear in the
rendered text.
"""
from __future__ import annotations

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.orchestration.informational_commerce_queries import (
    INFORMATIONAL_COMMERCE_HANDLER,
)
from backend.intents.schemas.customer_response import CustomerResponse
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession

_NO_MENU_MESSAGE = (
    "Por ahora no tengo productos disponibles para mostrarte. "
    "Volvé a consultar más tarde."
)

_NO_MATCH_MESSAGE = (
    "No encontré ese producto en el menú. "
    "Decime cuál de los disponibles te interesa."
)
_AMBIGUOUS_PRODUCT_MESSAGE = (
    "Encontré varios productos con ese nombre. "
    "Decime cuál querés que te detalle."
)

_NO_PAYMENT_OPTIONS_MESSAGE = (
    "Por ahora no tengo medios de pago configurados para este comercio."
)

_NO_DELIVERY_OPTIONS_MESSAGE = (
    "Por ahora no tengo métodos de entrega configurados para este comercio."
)

_HOURS_NOT_CONFIGURED_MESSAGE = (
    "Por el momento no tenemos horarios de atención configurados. "
    "Contactanos para coordinar."
)

_FAILED_MESSAGE = (
    "Tuve un problema técnico, ¿podrías intentarlo de nuevo en unos minutos?"
)


def _format_menu_item(item: dict) -> str | None:
    nombre = item.get("producto_nombre")
    codigo = item.get("presentacion_codigo")
    if not isinstance(nombre, str) or not isinstance(codigo, str):
        return None
    return f"{nombre} ({codigo})"


def _format_option(opcion: dict) -> str | None:
    codigo = opcion.get("codigo")
    descripcion = opcion.get("descripcion")
    if not isinstance(codigo, str) or not isinstance(descripcion, str):
        return None
    return f"{codigo} ({descripcion})"


def _format_options_list(options: list[dict]) -> list[str]:
    formatted: list[str] = []
    for option in options:
        text = _format_option(option)
        if text is not None:
            formatted.append(text)
    return formatted


def _render_options_text(prompt: str, options: list[dict]) -> str:
    formatted = _format_options_list(options)
    if not formatted:
        return f"{prompt} (sin opciones disponibles)"
    if len(formatted) == 1:
        return f"{prompt} {formatted[0]}"
    if len(formatted) == 2:
        return f"{prompt} {formatted[0]} o {formatted[1]}"
    return f"{prompt} {', '.join(formatted[:-1])} o {formatted[-1]}"


def _build_menu_message(items: list[dict]) -> str:
    lines: list[str] = ["Menú disponible:"]
    current_categoria: str | None = None
    for item in items:
        categoria = item.get("categoria_nombre") if isinstance(item, dict) else None
        if not isinstance(categoria, str):
            categoria = ""
        if categoria != current_categoria:
            current_categoria = categoria
            if categoria:
                lines.append("")
                lines.append(f"{categoria}:")
        formatted = _format_menu_item(item)
        if formatted is not None:
            lines.append(f"- {formatted}")
    return "\n".join(lines)


def _build_selected_category_menu_message(
    items: list[dict],
    categoria_nombre: str,
) -> str:
    lines: list[str] = [f"{categoria_nombre} disponibles:"]
    for item in items:
        formatted = _format_menu_item(item)
        if formatted is not None:
            lines.append(f"- {formatted}")
    return "\n".join(lines)


def _build_product_message(resolved_data: dict) -> str:
    nombre = resolved_data.get("producto_nombre")
    categoria = resolved_data.get("categoria_nombre")
    presentaciones = resolved_data.get("presentaciones") or []
    if not isinstance(nombre, str):
        return _FAILED_MESSAGE
    lines: list[str] = [nombre]
    if isinstance(categoria, str) and categoria:
        lines.append(f"Categoría: {categoria}")
    lines.append("Presentaciones:")
    if not isinstance(presentaciones, list) or not presentaciones:
        lines.append("- (sin presentaciones disponibles)")
        return "\n".join(lines)
    for presentacion in presentaciones:
        if not isinstance(presentacion, dict):
            continue
        codigo = presentacion.get("presentacion_codigo")
        descripcion = presentacion.get("presentacion_descripcion")
        precio = presentacion.get("precio")
        if isinstance(codigo, str) and isinstance(descripcion, str) and descripcion:
            head = f"{codigo} ({descripcion})"
        elif isinstance(codigo, str):
            head = codigo
        else:
            continue
        if isinstance(precio, str) and precio:
            lines.append(f"- {head} — ${precio}")
        else:
            lines.append(f"- {head}")
    return "\n".join(lines)


def _build_domicilio_message(resolved_data: dict) -> str:
    calle = resolved_data.get("calle")
    numero = resolved_data.get("numero")
    piso = resolved_data.get("piso_departamento")
    localidad = resolved_data.get("localidad")
    provincia = resolved_data.get("provincia")
    codigo_postal = resolved_data.get("codigo_postal")
    if not isinstance(calle, str) or not isinstance(numero, str):
        return _FAILED_MESSAGE
    primera = f"{calle} {numero}"
    if isinstance(piso, str) and piso.strip():
        primera = f"{primera}, {piso}"
    segunda_parts: list[str] = []
    if isinstance(localidad, str) and localidad:
        segunda_parts.append(localidad)
    if isinstance(provincia, str) and provincia:
        segunda_parts.append(provincia)
    segunda = ", ".join(segunda_parts)
    lines: list[str] = ["Dirección del comercio:", primera]
    if segunda:
        lines.append(segunda)
    if isinstance(codigo_postal, str) and codigo_postal.strip():
        lines.append(f"CP {codigo_postal}")
    return "\n".join(lines)


def build_informational_commerce_response(
    db: DatabaseSession,
    session: ConversationSession,
    intent: ProcessedIntent,
) -> CustomerResponse:
    """Render the deterministic Spanish message for one informational
    commerce query.

    The function is pure with respect to ``db`` and ``session``; they
    are accepted only for parity with the other response builders.
    The only fields inspected are ``intent.intent``, ``intent.status``
    and ``intent.resolved_data``.
    """
    del db
    del session

    intent_name = intent.intent
    status = intent.status
    resolved_data = intent.resolved_data or {}

    if status == "failed":
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent=intent_name,
            status="failed",
        )

    if intent_name == "ver_menu":
        if status == "executed":
            items = resolved_data.get("items") or []
            if not isinstance(items, list) or not items:
                return CustomerResponse(
                    message=_NO_MENU_MESSAGE,
                    intent=intent_name,
                    status="executed",
                )
            categoria_nombre = resolved_data.get("categoria_nombre")
            if (
                isinstance(categoria_nombre, str)
                and categoria_nombre
                and all(
                    isinstance(item, dict)
                    and item.get("categoria_nombre") == categoria_nombre
                    for item in items
                )
            ):
                return CustomerResponse(
                    message=_build_selected_category_menu_message(
                        items, categoria_nombre
                    ),
                    intent=intent_name,
                    status="executed",
                )
            return CustomerResponse(
                message=_build_menu_message(items),
                intent=intent_name,
                status="executed",
            )
        if status == "rejected":
            reason = resolved_data.get("reason")
            if reason == "no_items":
                return CustomerResponse(
                    message=_NO_MENU_MESSAGE,
                    intent=intent_name,
                    status="rejected",
                )
            return CustomerResponse(
                message=_FAILED_MESSAGE,
                intent=intent_name,
                status="rejected",
            )
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent=intent_name,
            status=status,
        )

    if intent_name == "consultar_producto":
        if status == "executed":
            return CustomerResponse(
                message=_build_product_message(resolved_data),
                intent=intent_name,
                status="executed",
            )
        if status == "rejected":
            reason = resolved_data.get("reason")
            opciones = resolved_data.get("opciones") or []
            if not isinstance(opciones, list):
                opciones = []
            if reason == "no_match":
                return CustomerResponse(
                    message=_render_options_text(_NO_MATCH_MESSAGE, opciones),
                    intent=intent_name,
                    status="rejected",
                )
            if reason == "ambiguous":
                return CustomerResponse(
                    message=_render_options_text(
                        _AMBIGUOUS_PRODUCT_MESSAGE, opciones
                    ),
                    intent=intent_name,
                    status="rejected",
                )
            return CustomerResponse(
                message=_FAILED_MESSAGE,
                intent=intent_name,
                status="rejected",
            )
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent=intent_name,
            status=status,
        )

    if intent_name == "ver_metodos_de_pago":
        if status == "executed":
            opciones = resolved_data.get("opciones") or []
            if not isinstance(opciones, list) or not opciones:
                return CustomerResponse(
                    message=_NO_PAYMENT_OPTIONS_MESSAGE,
                    intent=intent_name,
                    status="executed",
                )
            return CustomerResponse(
                message=_render_options_text(
                    "Medios de pago disponibles:", opciones
                ),
                intent=intent_name,
                status="executed",
            )
        if status == "rejected":
            reason = resolved_data.get("reason")
            if reason == "no_options":
                return CustomerResponse(
                    message=_NO_PAYMENT_OPTIONS_MESSAGE,
                    intent=intent_name,
                    status="rejected",
                )
            return CustomerResponse(
                message=_FAILED_MESSAGE,
                intent=intent_name,
                status="rejected",
            )
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent=intent_name,
            status=status,
        )

    if intent_name == "ver_metodos_de_entrega":
        if status == "executed":
            opciones = resolved_data.get("opciones") or []
            if not isinstance(opciones, list) or not opciones:
                return CustomerResponse(
                    message=_NO_DELIVERY_OPTIONS_MESSAGE,
                    intent=intent_name,
                    status="executed",
                )
            return CustomerResponse(
                message=_render_options_text(
                    "Métodos de entrega disponibles:", opciones
                ),
                intent=intent_name,
                status="executed",
            )
        if status == "rejected":
            reason = resolved_data.get("reason")
            if reason == "no_options":
                return CustomerResponse(
                    message=_NO_DELIVERY_OPTIONS_MESSAGE,
                    intent=intent_name,
                    status="rejected",
                )
            return CustomerResponse(
                message=_FAILED_MESSAGE,
                intent=intent_name,
                status="rejected",
            )
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent=intent_name,
            status=status,
        )

    if intent_name == "consultar_domicilio_comercio":
        if status == "executed":
            return CustomerResponse(
                message=_build_domicilio_message(resolved_data),
                intent=intent_name,
                status="executed",
            )
        if status == "rejected":
            return CustomerResponse(
                message=_FAILED_MESSAGE,
                intent=intent_name,
                status="rejected",
            )
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent=intent_name,
            status=status,
        )

    if intent_name == "consultar_horarios_comercio":
        return CustomerResponse(
            message=_HOURS_NOT_CONFIGURED_MESSAGE,
            intent=intent_name,
            status=status if status in {"executed", "rejected", "failed"} else "executed",
        )

    return CustomerResponse(
        message=_FAILED_MESSAGE,
        intent=intent_name,
        status=status,
    )


__all__ = [
    "INFORMATIONAL_COMMERCE_HANDLER",
    "build_informational_commerce_response",
]
