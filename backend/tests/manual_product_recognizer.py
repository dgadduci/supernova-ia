"""Manual test script for the product recognizer.

Loads the product-presentations catalog from the supernova_test database
(joined across producto_presentaciones, productos, presentaciones, and
categorias_productos), then enters an interactive loop that calls
detectar_productos on user input and prints the result as JSON.

Run from the project root with the active virtual environment:

    PYTHONPATH=. venv/bin/python backend/tests/manual_product_recognizer.py
"""
from __future__ import annotations

import json
import sys
import traceback

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.dependencies import _SessionLocal, _engine
from backend.models import (
    CategoriaProducto,
    Presentacion,
    Producto,
    ProductoPresentacion,
)
from backend.recognizers.product_recognizer import detectar_productos


def _load_catalog(session: Session) -> list[dict]:
    stmt = (
        select(ProductoPresentacion)
        .options(
            joinedload(ProductoPresentacion.producto).joinedload(Producto.categoria),
            joinedload(ProductoPresentacion.presentacion),
        )
    )
    catalog: list[dict] = []
    for pp in session.scalars(stmt).all():
        catalog.append(
            {
                "producto_presentacion_id": pp.id,
                "producto_id": pp.id_producto,
                "presentacion_id": pp.id_presentacion,
                "categoria_id": pp.producto.id_categoria_producto,
                "producto_nombre": pp.producto.nombre,
                "categoria_nombre": pp.producto.categoria.descripcion,
                "presentacion_codigo": pp.presentacion.codigo,
                "presentacion_descripcion": pp.presentacion.descripcion,
                "activo": bool(pp.activo),
                "producto_activo": bool(pp.producto.activo),
                "presentacion_activo": bool(pp.presentacion.activo),
                "disponible": bool(pp.producto.disponible),
            }
        )
    return catalog


def main() -> int:
    session = _SessionLocal()
    try:
        try:
            productos_presentaciones = _load_catalog(session)
        except Exception as exc:
            print(
                f"ERROR: no se pudo cargar el catálogo desde la base de datos: {exc}",
                file=sys.stderr,
            )
            traceback.print_exc()
            return 1

        if not productos_presentaciones:
            print(
                "ERROR: el catálogo está vacío. ¿Se ejecutaron los seeds?",
                file=sys.stderr,
            )
            return 1

        print(
            f"Catálogo cargado: {len(productos_presentaciones)} producto-presentaciones.",
            file=sys.stderr,
        )

        while True:
            try:
                message = input("Ingrese mensaje (o 'exit' para salir): ")
            except EOFError:
                print()
                break

            if message.strip().lower() == "exit":
                break

            try:
                result = detectar_productos(message, productos_presentaciones)
            except Exception as exc:
                print(f"ERROR: no se pudo procesar el mensaje: {exc}", file=sys.stderr)
                traceback.print_exc()
                continue

            print(json.dumps(result, ensure_ascii=False, indent=2))
            print()

        return 0
    finally:
        session.close()
        _engine.dispose()


if __name__ == "__main__":
    sys.exit(main())