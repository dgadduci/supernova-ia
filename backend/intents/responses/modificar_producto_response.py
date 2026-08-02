"""Modificar producto response builder.

Renders a single fixed Spanish `CustomerResponse` for every
`ProcessedIntent.status` outcome produced by the `modificar_producto`
pipeline. No LLM, no prompt construction, no technical detail, no DB IDs
in the rendered message.

Deterministic message matrix:
- Executed full transfer (omitted quantity): `Cambié <cantidad> <origen_nombre> por <cantidad> <destino_nombre>.`
- Executed partial explicit-quantity transfer: `Cambié <cantidad> <origen_nombre> por <cantidad> de <destino_nombre>. Quedan <cantidad_origen_restante> <origen_nombre>.`
- Executed consolidated: `Cambié <cantidad_modificada> <origen_nombre> por <destino_nombre>. Ahora tenés <cantidad_destino_final> <destino_nombre>.`
- Unknown destination: `No encontré el producto de reemplazo. Tu pedido no fue modificado.`
- Unavailable destination: `El producto de reemplazo no está disponible. Tu pedido no fue modificado.`
- Excess quantity: `Solo tenés <cantidad_actual> <origen_nombre> para cambiar. Tu pedido no fue modificado.`
"""
from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.schemas.customer_response import CustomerResponse
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession
from backend.services.pedido_producto_service import PedidoProductoService
from backend.services.producto_query_service import ProductoQueryService


_SOURCE_PROMPT = "¿Cuál producto querés cambiar:"
_DESTINATION_PROMPT = "¿Cuál querés como reemplazo:"
_ABSENT_MESSAGE = "Ese producto no está en tu pedido."
_UNAVAILABLE_MESSAGE = "Ese producto no está disponible como reemplazo."
_UNKNOWN_DESTINATION_MESSAGE = (
    "No encontré el producto de reemplazo. Tu pedido no fue modificado."
)
_EQUIVALENT_MESSAGE = "Ese producto ya tiene esa presentación en tu pedido."
_FAILED_MESSAGE = "No pude procesar tu pedido. Intentá de nuevo en un momento."


def _format_candidate(label: dict) -> str | None:
    nombre = label.get("producto_nombre")
    codigo = label.get("presentacion_codigo")
    if not isinstance(nombre, str) or not isinstance(codigo, str):
        return None
    return f"{nombre} ({codigo})"


def _join_options(formatted: list[str]) -> str:
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]} o {formatted[1]}"
    return f"{', '.join(formatted[:-1])} o {formatted[-1]}"


def _render_clarification(
    prompt: str,
    candidate_ids: list[int],
    labels_by_id: dict[int, dict],
    fallback_message: str,
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
        return fallback_message
    return f"{prompt} {_join_options(formatted)}?"


def _load_source_labels(
    db: DatabaseSession,
    session: ConversationSession,
) -> dict[int, dict]:
    labels_by_id: dict[int, dict] = {}
    pedido_id = session.id_pedido
    if pedido_id is None:
        return labels_by_id
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
        return {}
    return labels_by_id


def _load_destination_labels(
    db: DatabaseSession,
    candidate_ids: list[int],
) -> dict[int, dict]:
    if not candidate_ids:
        return {}
    try:
        entries = ProductoQueryService(db).list_presentaciones_by_ids(candidate_ids)
    except Exception:
        return {}
    labels_by_id: dict[int, dict] = {}
    for entry in entries:
        pp_id = entry.get("producto_presentacion_id")
        if isinstance(pp_id, int):
            labels_by_id[pp_id] = {
                "producto_nombre": str(entry.get("producto_nombre", "")),
                "presentacion_codigo": str(entry.get("presentacion_codigo", "")),
            }
    return labels_by_id


def _render_full_line(intent: ProcessedIntent) -> str:
    """Render a full-line executed swap with the quantity on both sides.

    Spec: `Cambié <cantidad_modificada> <origen_nombre> por <cantidad_modificada> <destino_nombre>.`
    """
    data = intent.resolved_data
    cantidad_modificada = data.get("cantidad_modificada")
    if not isinstance(cantidad_modificada, int):
        return _FAILED_MESSAGE
    return (
        f"Cambié {cantidad_modificada} "
        f"{data.get('producto_origen_nombre', '')} "
        f"por {cantidad_modificada} "
        f"{data.get('producto_destino_nombre', '')}."
    )


def _render_partial(intent: ProcessedIntent) -> str:
    """Render a partial explicit-quantity transfer.

    Spec: `Cambié <cantidad_modificada> <origen_nombre> por <cantidad_modificada> de <destino_nombre>. Quedan <cantidad_origen_restante> <origen_nombre>.`
    """
    data = intent.resolved_data
    cantidad_modificada = data.get("cantidad_modificada")
    cantidad_origen_restante = data.get("cantidad_origen_restante")
    if not isinstance(cantidad_modificada, int) or not isinstance(
        cantidad_origen_restante, int
    ):
        return _FAILED_MESSAGE
    return (
        f"Cambié {cantidad_modificada} "
        f"{data.get('producto_origen_nombre', '')} "
        f"por {cantidad_modificada} de "
        f"{data.get('producto_destino_nombre', '')}. "
        f"Quedan {cantidad_origen_restante} "
        f"{data.get('producto_origen_nombre', '')}."
    )


def _render_consolidated(intent: ProcessedIntent) -> str:
    """Render a consolidated destination increment.

    The existing pre-correction message is preserved; the spec keeps the
    consolidated invariant unchanged.
    """
    data = intent.resolved_data
    cantidad_modificada = data.get("cantidad_modificada")
    cantidad_destino_final = data.get("cantidad_destino_final")
    if not isinstance(cantidad_modificada, int) or not isinstance(
        cantidad_destino_final, int
    ):
        return _FAILED_MESSAGE
    return (
        f"Cambié {cantidad_modificada} "
        f"{data.get('producto_origen_nombre', '')} "
        f"por {data.get('producto_destino_nombre', '')}. "
        f"Ahora tenés {cantidad_destino_final} "
        f"{data.get('producto_destino_nombre', '')}."
    )


def _render_excess(intent: ProcessedIntent) -> str:
    """Render an excess-quantity rejection with explicit Pedido-preserved confirmation.

    Spec: `Solo tenés <cantidad_actual> <origen_nombre> para cambiar. Tu pedido no fue modificado.`
    """
    data = intent.resolved_data
    cantidad_actual = data.get("cantidad_actual")
    if not isinstance(cantidad_actual, int):
        return _ABSENT_MESSAGE
    return (
        f"Solo tenés {cantidad_actual} "
        f"{data.get('producto_origen_nombre', '')} "
        f"para cambiar. Tu pedido no fue modificado."
    )


def _render_unavailable(intent: ProcessedIntent) -> str:
    """Render an unavailable-destination rejection with explicit Pedido-preserved confirmation.

    Spec: `El producto de reemplazo no está disponible. Tu pedido no fue modificado.`
    """
    return (
        "El producto de reemplazo no está disponible. "
        "Tu pedido no fue modificado."
    )


def _render_unknown_destination(intent: ProcessedIntent) -> str:
    """Render the unknown-destination rejection.

    Spec: `No encontré el producto de reemplazo. Tu pedido no fue modificado.`
    """
    return _UNKNOWN_DESTINATION_MESSAGE


def build_modificar_producto_response(
    db: DatabaseSession,
    session: ConversationSession,
    intent: ProcessedIntent,
) -> CustomerResponse:
    """Render the deterministic Spanish message for a `modificar_producto` intent."""
    if intent.intent != "modificar_producto":
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent=intent.intent,
            status=intent.status,
        )

    if intent.status == "pending_resolution":
        resolved_data = intent.resolved_data or {}
        source_candidate_ids = list(
            resolved_data.get("source_candidate_ids") or []
        )
        destination_candidate_ids = list(
            resolved_data.get("destination_candidate_ids") or []
        )
        if intent.stage == "destination_selection":
            labels = _load_destination_labels(db, destination_candidate_ids)
            message = _render_clarification(
                _DESTINATION_PROMPT,
                destination_candidate_ids,
                labels,
                _UNAVAILABLE_MESSAGE,
            )
        else:
            labels = _load_source_labels(db, session)
            message = _render_clarification(
                _SOURCE_PROMPT,
                source_candidate_ids,
                labels,
                _ABSENT_MESSAGE,
            )
        return CustomerResponse(
            message=message,
            intent="modificar_producto",
            status="pending_resolution",
        )

    if intent.status == "executed":
        data = intent.resolved_data
        destino_creado = data.get("destino_creado")
        origen_eliminado = data.get("origen_eliminado")
        if destino_creado is True and origen_eliminado is True:
            message = _render_full_line(intent)
        elif destino_creado is False:
            message = _render_consolidated(intent)
        else:
            message = _render_partial(intent)
        return CustomerResponse(
            message=message,
            intent="modificar_producto",
            status="executed",
        )

    if intent.status == "rejected":
        reason = intent.resolved_data.get("reason")
        if reason == "quantity_exceeds_source":
            message = _render_excess(intent)
        elif reason == "source_not_in_pedido":
            message = _ABSENT_MESSAGE
        elif reason == "no_destination_candidates":
            message = _render_unknown_destination(intent)
        elif reason in ("destination_unavailable", "destination_price_missing"):
            message = _render_unavailable(intent)
        elif reason == "destination_foreign_comercio":
            message = _render_unavailable(intent)
        elif reason == "equivalent_modification":
            message = _EQUIVALENT_MESSAGE
        else:
            message = _ABSENT_MESSAGE
        return CustomerResponse(
            message=message,
            intent="modificar_producto",
            status="rejected",
        )

    if intent.status == "failed":
        return CustomerResponse(
            message=_FAILED_MESSAGE,
            intent="modificar_producto",
            status="failed",
        )

    return CustomerResponse(
        message=_FAILED_MESSAGE,
        intent="modificar_producto",
        status=intent.status,
    )


__all__ = ["build_modificar_producto_response"]
