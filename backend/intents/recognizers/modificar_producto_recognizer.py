"""Modificar producto recognizer.

Detects `modificar_producto` source candidates among the active draft Pedido's
`PedidoProducto` lines and destination candidates among the comercio's active
and available `ProductoPresentacion` rows, plus an optional explicit positive
integer quantity.

The two identifier domains (`PedidoProducto.id` for source and
`ProductoPresentacion.id` for destination) are emitted in distinct fields and
are never broadened beyond their respective catalogs. The recognizer is
read-only: it never commits, rolls back, adds, deletes, or generates a
customer-facing response.
"""
from sqlalchemy.orm import Session as DatabaseSession

from backend.models import Session as ConversationSession
from backend.recognizers.product_recognizer import (
    PALABRAS_CANTIDAD,
    _normalizar_texto,
    detectar_productos,
)
from backend.services.pedido_producto_service import PedidoProductoService
from backend.services.producto_query_service import ProductoQueryService


def _build_order_line_catalog(pedido_productos) -> list[dict]:
    """Convert `PedidoProducto` rows to the catalog dict format the fuzzy
    recognizer expects.
    """
    catalog: list[dict] = []
    for pp in pedido_productos:
        producto_presentacion = pp.producto_presentacion
        presentacion = producto_presentacion.presentacion
        producto = producto_presentacion.producto
        catalog.append(
            {
                "producto_presentacion_id": pp.id_producto_presentacion,
                "pedido_producto_id": pp.id,
                "producto_id": producto_presentacion.id_producto,
                "presentacion_id": producto_presentacion.id_presentacion,
                "categoria_id": producto.id_categoria_producto,
                "producto_nombre": producto.nombre,
                "categoria_nombre": None,
                "presentacion_codigo": presentacion.codigo,
                "presentacion_descripcion": presentacion.descripcion,
                "producto_activo": bool(producto.activo),
                "presentacion_activo": bool(presentacion.activo),
                "activo": bool(producto_presentacion.activo),
                "disponible": bool(producto.disponible),
                "cantidad_actual": pp.cantidad,
            }
        )
    return catalog


def _extract_quantity(message: str) -> int | None:
    """Return an explicit positive integer quantity if present, else None."""
    texto = _normalizar_texto(message)
    palabras = texto.split()
    if not palabras:
        return None

    for i, palabra in enumerate(palabras):
        if palabra in ("docena", "docenas"):
            anterior = palabras[i - 1] if i > 0 else ""
            if anterior.isdigit():
                n = int(anterior) * 12
                if n > 0:
                    return n
            if anterior in PALABRAS_CANTIDAD:
                n = int(PALABRAS_CANTIDAD[anterior]) * 12
                if n > 0:
                    return n

    for palabra in palabras:
        if palabra.isdigit():
            n = int(palabra)
            if n > 0:
                return n
        if palabra in PALABRAS_CANTIDAD:
            n = int(PALABRAS_CANTIDAD[palabra])
            if n > 0:
                return n

    return None


def _flatten_pedido_producto_ids(recognized: dict) -> list[int]:
    ids: list[int] = []
    for entry in recognized.get("encontrados") or []:
        pp_id = entry.get("pedido_producto_id")
        if pp_id is not None:
            ids.append(int(pp_id))
    for group in recognized.get("encontrados_posibles") or []:
        for product in group.get("productos") or []:
            pp_id = product.get("pedido_producto_id")
            if pp_id is not None:
                ids.append(int(pp_id))
    return ids


def _flatten_producto_presentacion_ids(recognized: dict) -> list[int]:
    ids: list[int] = []
    for entry in recognized.get("encontrados") or []:
        pid = entry.get("producto_presentacion_id")
        if pid is not None:
            ids.append(int(pid))
    for group in recognized.get("encontrados_posibles") or []:
        for product in group.get("productos") or []:
            pid = product.get("producto_presentacion_id")
            if pid is not None:
                ids.append(int(pid))
    return ids


def _split_on_por(message: str) -> tuple[str, str | None]:
    """Split the message on the word `por` to separate the source reference
    (before) from the destination reference (after). Returns the full message
    and `None` for the destination part when no `por` is present.
    """
    texto = _normalizar_texto(message)
    palabras = texto.split()
    for i, palabra in enumerate(palabras):
        if palabra == "por":
            source_part = " ".join(palabras[:i])
            dest_part = " ".join(palabras[i + 1 :])
            return source_part or message, dest_part or None
    return message, None


_MODIFY_VERBS = {
    "cambia", "cambia", "modifica", "modifica",
    "sustituye", "reemplaza",
    "cambiar", "modificar", "sustituir", "reemplazar",
}


def _strip_modify_verbs(message: str) -> str:
    texto = _normalizar_texto(message)
    palabras = texto.split()
    filtered = [p for p in palabras if p not in _MODIFY_VERBS]
    return " ".join(filtered) or message


def recognize_modificar_producto(
    db: DatabaseSession,
    session: ConversationSession,
    message: str,
) -> dict:
    """Recognize source and destination candidates for `modificar_producto`.

    Returns a `dict` with the shape:
        {
            "source_candidate_ids": list[int],   # PedidoProducto.id values
            "destination_candidate_ids": list[int],  # ProductoPresentacion.id values
            "source_pp_id": int | None,           # unique source PedidoProducto.id
            "destination_pp_id": int | None,     # unique ProductoPresentacion.id
            "cantidad": int | None,               # explicit positive quantity or None
        }
    """
    source_candidate_ids: list[int] = []
    destination_candidate_ids: list[int] = []
    source_pp_id: int | None = None
    destination_pp_id: int | None = None

    source_message, dest_message = _split_on_por(message)
    source_message = _strip_modify_verbs(source_message)

    pedido_id = session.id_pedido
    comercio_id = session.id_comercio

    if pedido_id is not None:
        pedido_productos = PedidoProductoService(db).list_by_pedido(pedido_id)
        if pedido_productos:
            source_catalog = _build_order_line_catalog(pedido_productos)
            source_detected = detectar_productos(source_message, source_catalog)
            source_candidate_ids = sorted(set(_flatten_pedido_producto_ids(source_detected)))
            if len(source_candidate_ids) == 1:
                source_pp_id = source_candidate_ids[0]

    if comercio_id is not None:
        catalog = ProductoQueryService(db).list_recognizer_catalog(comercio_id)
        active_catalog = [
            entry
            for entry in catalog
            if entry.get("activo")
            and entry.get("producto_activo")
            and entry.get("presentacion_activo")
            and entry.get("disponible")
        ]
        target_message = (
            _strip_modify_verbs(dest_message)
            if dest_message
            else _strip_modify_verbs(message)
        )
        dest_detected = detectar_productos(target_message, active_catalog)
        destination_candidate_ids = sorted(
            set(_flatten_producto_presentacion_ids(dest_detected))
        )
        if len(destination_candidate_ids) == 1:
            destination_pp_id = destination_candidate_ids[0]

    cantidad = _extract_quantity(message)

    return {
        "source_candidate_ids": source_candidate_ids,
        "destination_candidate_ids": destination_candidate_ids,
        "source_pp_id": source_pp_id,
        "destination_pp_id": destination_pp_id,
        "cantidad": cantidad,
    }


__all__ = ["recognize_modificar_producto"]
