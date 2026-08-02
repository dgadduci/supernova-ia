AGREGAR_PRODUCTO_CONTRACT: dict = {
    "intent": "agregar_producto",
    "recognizer": "recognizer_productos",
    "handler": "agregar_producto",
    "requirements": {
        "producto_presentacion_id": {"required": True, "default": None},
        "cantidad": {"required": True, "default": 1},
    },
}
