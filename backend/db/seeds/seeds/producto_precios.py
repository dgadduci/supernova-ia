import json
import os
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.models import Precio, ProductoPresentacion

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "precios.json"
DEFAULT_URL = "postgresql+psycopg:///supernova_test"
MAX_PRECIO = Decimal("9999999999.99")


def main() -> None:
    url = os.environ.get("SUPERNOVA_DATABASE_URL", DEFAULT_URL)
    rows = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    engine = create_engine(url)
    with Session(engine) as session:
        with session.begin():
            producto_presentacion_ids = set(
                session.execute(select(ProductoPresentacion.id)).scalars()
            )
            existing_ids = set(
                session.execute(select(Precio.id_producto_presentacion)).scalars()
            )

            inserted = 0
            for row in rows:
                producto_presentacion_id = row["id_producto_presentacion"]
                if producto_presentacion_id not in producto_presentacion_ids:
                    raise ValueError(
                        "id_producto_presentacion "
                        f"{producto_presentacion_id!r} not found in producto_presentaciones"
                    )

                raw_precio = str(row["precio"])
                precio = Decimal(raw_precio)
                if precio < 0 or precio > MAX_PRECIO:
                    raise ValueError(f"precio {precio!r} is outside Numeric(12, 2)")
                decimal_places = len(raw_precio.partition(".")[2])
                if decimal_places > 2:
                    raise ValueError(f"precio {precio!r} has more than two decimal places")

                if producto_presentacion_id in existing_ids:
                    continue

                session.add(
                    Precio(
                        id_producto_presentacion=producto_presentacion_id,
                        precio=precio.quantize(Decimal("0.01")),
                    )
                )
                existing_ids.add(producto_presentacion_id)
                inserted += 1

            skipped = len(rows) - inserted

    print(f"target={url} inserted={inserted} skipped={skipped} total_in_json={len(rows)}")


if __name__ == "__main__":
    main()
