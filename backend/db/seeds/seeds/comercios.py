import json
import os
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.models import Comercio, EstadoComercio

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "comercio.json"
DEFAULT_URL = "postgresql+psycopg:///supernova_test"


def main() -> None:
    url = os.environ.get("SUPERNOVA_DATABASE_URL", DEFAULT_URL)
    rows = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    engine = create_engine(url)
    with Session(engine) as session:
        with session.begin():
            estado_ids = {
                estado: id_
                for estado, id_ in session.execute(select(EstadoComercio.estado, EstadoComercio.id)).all()
            }
            existing_cuits = {
                cuit for (cuit,) in session.execute(select(Comercio.cuit)).all()
            }
            inserted = 0
            for row in rows:
                cuit = row["cuit"]
                if cuit in existing_cuits:
                    continue
                estado_codigo = row["estado_codigo"]
                if estado_codigo not in estado_ids:
                    raise ValueError(f"estado_codigo {estado_codigo!r} not found in estado_comercio")
                payload = {k: v for k, v in row.items() if k != "estado_codigo"}
                payload["estado_id"] = estado_ids[estado_codigo]
                session.add(Comercio(**payload))
                existing_cuits.add(cuit)
                inserted += 1
            skipped = len(rows) - inserted

    print(f"target={url} inserted={inserted} skipped={skipped} total_in_json={len(rows)}")


if __name__ == "__main__":
    main()
