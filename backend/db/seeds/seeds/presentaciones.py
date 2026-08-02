import json
import os
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.models import Comercio, Presentacion

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "presentaciones.json"
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
            existing_pairs = {
                (c, cod)
                for c, cod in session.execute(
                    select(Presentacion.id_comercio, Presentacion.codigo)
                ).all()
            }
            inserted = 0
            for row in rows:
                cuit = row["comercio_cuit"]
                if cuit not in comercio_ids:
                    raise ValueError(f"comercio_cuit {cuit!r} not found in comercios")
                pair = (comercio_ids[cuit], row["codigo"])
                if pair in existing_pairs:
                    continue
                payload = {
                    "id_comercio": pair[0],
                    "codigo": row["codigo"],
                    "descripcion": row["descripcion"],
                    "activo": row["activo"],
                    "orden": row["orden"],
                }
                session.add(Presentacion(**payload))
                existing_pairs.add(pair)
                inserted += 1
            skipped = len(rows) - inserted

    print(f"target={url} inserted={inserted} skipped={skipped} total_in_json={len(rows)}")


if __name__ == "__main__":
    main()
