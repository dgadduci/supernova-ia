"""Static contract for the `modificar_producto` intent.

Mirrors the shape of `AGREGAR_PRODUCTO_CONTRACT` and `QUITAR_PRODUCTO_CONTRACT`:
a `dict` literal exposing `intent`, `recognizer`, `handler`, and `requirements`,
where each requirement entry carries `required` and `default` flags.
"""

MODIFICAR_PRODUCTO_CONTRACT: dict = {
    "intent": "modificar_producto",
    "recognizer": "modificar_producto_recognizer",
    "handler": "modificar_producto",
    "requirements": {
        "pedido_producto_origen_id": {"required": True, "default": None},
        "producto_presentacion_destino_id": {"required": True, "default": None},
        "cantidad": {"required": False, "default": None},
    },
}


__all__ = ["MODIFICAR_PRODUCTO_CONTRACT"]
