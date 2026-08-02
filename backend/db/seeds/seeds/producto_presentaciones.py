import json
import os
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.models import (
    CategoriaProducto,
    Comercio,
    Presentacion,
    Producto,
    ProductoPresentacion,
)

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "producto_presentaciones.json"
DEFAULT_URL = "postgresql+psycopg:///supernova_test"


def main() -> None:
    url = os.environ.get("SUPERNOVA_DATABASE_URL", DEFAULT_URL)
    rows = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    engine = create_engine(url)
    with Session(engine) as session:
        with session.begin():
            comercio_ids = {
                cuit: id_ for cuit, id_ in session.execute(select(Comercio.cuit, Comercio.id)).all()
            }
            categoria_by_comercio = {}
            for id_comercio, descripcion, id_ in session.execute(
                select(CategoriaProducto.id_comercio, CategoriaProducto.descripcion, CategoriaProducto.id)
            ).all():
                categoria_by_comercio[(id_comercio, descripcion.lower())] = id_
            producto_by_cat = {}
            for id_categoria_producto, nombre in session.execute(
                select(Producto.id_categoria_producto, Producto.nombre)
            ).all():
                producto_by_cat[(id_categoria_producto, nombre)] = True
            presentacion_by_comercio = {}
            for id_comercio, codigo, id_ in session.execute(
                select(Presentacion.id_comercio, Presentacion.codigo, Presentacion.id)
            ).all():
                presentacion_by_comercio[(id_comercio, codigo)] = id_
            existing_pairs = {
                (p, pr)
                for p, pr in session.execute(
                    select(ProductoPresentacion.id_producto, ProductoPresentacion.id_presentacion)
                ).all()
            }

            inserted = 0
            for row in rows:
                cuit = row["comercio_cuit"]
                if cuit not in comercio_ids:
                    raise ValueError(f"comercio_cuit {cuit!r} not found in comercios")
                id_comercio = comercio_ids[cuit]

                cat_key = (id_comercio, row["categoria_descripcion"].lower())
                if cat_key not in categoria_by_comercio:
                    raise ValueError(
                        f"categoria {row['categoria_descripcion']!r} not found for comercio {cuit!r}"
                    )
                id_categoria = categoria_by_comercio[cat_key]

                prod_key = (id_categoria, row["producto_nombre"])
                if prod_key not in producto_by_cat:
                    raise ValueError(
                        f"producto {row['producto_nombre']!r} not found in categoria "
                        f"{row['categoria_descripcion']!r} for comercio {cuit!r}"
                    )
                id_producto_rows = session.execute(
                    select(Producto.id).where(
                        Producto.id_categoria_producto == id_categoria,
                        Producto.nombre == row["producto_nombre"],
                    )
                ).all()
                id_producto = id_producto_rows[0][0]

                pres_key = (id_comercio, row["presentacion_codigo"])
                if pres_key not in presentacion_by_comercio:
                    raise ValueError(
                        f"presentacion {row['presentacion_codigo']!r} not found for comercio {cuit!r}"
                    )
                id_presentacion = presentacion_by_comercio[pres_key]

                pair = (id_producto, id_presentacion)
                if pair in existing_pairs:
                    continue
                session.add(
                    ProductoPresentacion(
                        id_producto=id_producto,
                        id_presentacion=id_presentacion,
                        activo=True,
                        orden=0,
                    )
                )
                existing_pairs.add(pair)
                inserted += 1
            skipped = len(rows) - inserted

    print(f"target={url} inserted={inserted} skipped={skipped} total_in_json={len(rows)}")


if __name__ == "__main__":
    main()
