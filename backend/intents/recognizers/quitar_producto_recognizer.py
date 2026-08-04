"""Quitar producto recognizer.

Builds the candidate catalog exclusively from the active draft Pedido's
`PedidoProducto` rows, runs the legacy fuzzy product matcher against the
constructed catalog (formatted to look like the commerce-catalog entries the
recognizer expects), and extracts an explicit positive integer quantity
from the user message when present.

The recognizer never queries the global commerce catalog and never
mutates `session`, the Pedido, or any persisted state.
"""
from typing import cast

from sqlalchemy.orm import Session as DatabaseSession

from backend.models import Session as ConversationSession
from backend.recognizers.fuzzy_product_recognizer import FuzzyProductRecognizer
from backend.recognizers.product_recognizer import (
    PALABRAS_CANTIDAD,
    _normalizar_texto,
)
from backend.recognizers.product_recognizer_contract import ProductRecognizerProtocol
from backend.services.pedido_producto_service import PedidoProductoService

_product_recognizer: ProductRecognizerProtocol = FuzzyProductRecognizer()
detectar_productos = _product_recognizer.recognize


def _build_order_line_catalog(
    pedido_productos,
) -> list[dict]:
    """Convert `PedidoProducto` rows to the catalog dict format the fuzzy
    recognizer expects (`producto_presentacion_id`, `producto_nombre`,
    `presentacion_codigo`, etc.).
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
                return int(anterior) * 12
            if anterior in PALABRAS_CANTIDAD:
                return int(PALABRAS_CANTIDAD[anterior]) * 12

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


def _attach_pedido_producto_id(encontrados: list[dict], catalog: list[dict]) -> list[dict]:
    by_pp_id = {entry["producto_presentacion_id"]: entry["pedido_producto_id"] for entry in catalog}
    out: list[dict] = []
    for entry in encontrados:
        pid = entry.get("producto_presentacion_id")
        pp_id = by_pp_id.get(pid)
        out.append({**entry, "pedido_producto_id": pp_id})
    return out


def _attach_pedido_producto_id_to_posibles(
    encontrados_posibles: list[dict],
    catalog: list[dict],
) -> list[dict]:
    by_pp_id = {entry["producto_presentacion_id"]: entry["pedido_producto_id"] for entry in catalog}
    out: list[dict] = []
    for group in encontrados_posibles:
        new_products = []
        for product in group.get("productos", []):
            pid = product.get("producto_presentacion_id")
            pp_id = by_pp_id.get(pid)
            new_products.append({**product, "pedido_producto_id": pp_id})
        out.append({**group, "productos": new_products})
    return out


def recognize_quitar_producto(
    db: DatabaseSession,
    session: ConversationSession,
    message: str,
) -> dict:
    """Recognize which `PedidoProducto` line(s) the user wants to remove.

    Returns a dict mirroring the shape produced by `detectar_productos`:
        {
            "encontrados": list of candidate dicts (each carries
                           `pedido_producto_id` and the optional `cantidad`),
            "encontrados_posibles": list of ambiguous groups (each group
                           carries a list of products, each with
                           `pedido_producto_id`),
            "encontrados_no_disponibles": [],
            "no_encontrados": list of unmatched message fragments,
            "cantidad": explicit quantity extracted from the message (or None),
        }
    """
    pedido_id = session.id_pedido
    recognized: dict = {
        "encontrados": [],
        "encontrados_posibles": [],
        "encontrados_no_disponibles": [],
        "no_encontrados": [],
        "cantidad": None,
    }

    if pedido_id is None:
        recognized["no_encontrados"].append({"texto_origen": message})
        return recognized

    pedido_productos = PedidoProductoService(db).list_by_pedido(pedido_id)
    if not pedido_productos:
        recognized["no_encontrados"].append({"texto_origen": message})
        return recognized

    catalog = _build_order_line_catalog(pedido_productos)

    detected = cast(dict, detectar_productos(message, catalog))
    encontrados = _attach_pedido_producto_id(detected.get("encontrados") or [], catalog)
    encontrados_posibles = _attach_pedido_producto_id_to_posibles(
        detected.get("encontrados_posibles") or [],
        catalog,
    )

    quantity = _extract_quantity(message)

    for entry in encontrados:
        if quantity is not None:
            entry["cantidad"] = quantity
    for group in encontrados_posibles:
        for product in group.get("productos", []):
            if quantity is not None:
                product["cantidad"] = quantity

    recognized["encontrados"] = encontrados
    recognized["encontrados_posibles"] = encontrados_posibles
    recognized["encontrados_no_disponibles"] = detected.get("encontrados_no_disponibles") or []
    recognized["no_encontrados"] = detected.get("no_encontrados") or []
    recognized["cantidad"] = quantity
    return recognized


__all__ = ["recognize_quitar_producto"]