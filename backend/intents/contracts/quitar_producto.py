QUITAR_PRODUCTO_CONTRACT: dict = {
    "intent": "quitar_producto",
    "recognizer": "recognizer_quitar_producto",
    "handler": "quitar_producto",
    "requirements": {
        "pedido_producto_id": {"required": True, "default": None},
        "cantidad": {"required": False, "default": None},
    },
}


__all__ = ["QUITAR_PRODUCTO_CONTRACT"]