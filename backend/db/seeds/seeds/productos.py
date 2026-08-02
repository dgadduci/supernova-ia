import json
import os
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend.models import CategoriaProducto, Comercio, Producto

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "productos.json"
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
            categoria_pairs = {
                (c, d.lower()): id_
                for c, d, id_ in session.execute(
                    select(CategoriaProducto.id_comercio, CategoriaProducto.descripcion, CategoriaProducto.id)
                ).all()
            }
            existing_pairs = {
                (c, n)
                for c, n in session.execute(
                    select(Producto.id_categoria_producto, Producto.nombre)
                ).all()
            }
            inserted = 0
            for row in rows:
                cuit = row["comercio_cuit"]
                if cuit not in comercio_ids:
                    raise ValueError(f"comercio_cuit {cuit!r} not found in comercios")
                categoria_key = (comercio_ids[cuit], row["categoria_descripcion"].lower())
                if categoria_key not in categoria_pairs:
                    raise ValueError(
                        f"categoria {row['categoria_descripcion']!r} not found for comercio {cuit!r}"
                    )
                pair = (categoria_pairs[categoria_key], row["nombre"])
                if pair in existing_pairs:
                    continue
                payload = {
                    "id_categoria_producto": pair[0],
                    "nombre": row["nombre"],
                    "descripcion": row["descripcion"],
                    "activo": row["activo"],
                    "disponible": row["disponible"],
                    "orden": row["orden"],
                }
                session.add(Producto(**payload))
                existing_pairs.add(pair)
                inserted += 1
            skipped = len(rows) - inserted

    print(f"target={url} inserted={inserted} skipped={skipped} total_in_json={len(rows)}")


if __name__ == "__main__":
    main()
