import json
import os
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.models import Comercio, ComercioMetodoEntrega, MetodosEntrega

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "comercio_metodos_entrega.json"
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
            metodo_ids = {
                codigo: id_
                for codigo, id_ in session.execute(select(MetodosEntrega.codigo, MetodosEntrega.id)).all()
            }
            existing_pairs = {
                (c, m)
                for c, m in session.execute(
                    select(ComercioMetodoEntrega.id_comercio, ComercioMetodoEntrega.id_metodo_entrega)
                ).all()
            }
            inserted = 0
            for row in rows:
                cuit = row["comercio_cuit"]
                codigo = row["metodo_entrega_codigo"]
                if cuit not in comercio_ids:
                    raise ValueError(f"comercio_cuit {cuit!r} not found in comercios")
                if codigo not in metodo_ids:
                    raise ValueError(f"metodo_entrega_codigo {codigo!r} not found in metodos_entrega")
                pair = (comercio_ids[cuit], metodo_ids[codigo])
                if pair in existing_pairs:
                    continue
                payload = {
                    "id_comercio": pair[0],
                    "id_metodo_entrega": pair[1],
                    "activo": row["activo"],
                    "orden": row["orden"],
                }
                session.add(ComercioMetodoEntrega(**payload))
                existing_pairs.add(pair)
                inserted += 1
            skipped = len(rows) - inserted

    print(f"target={url} inserted={inserted} skipped={skipped} total_in_json={len(rows)}")


if __name__ == "__main__":
    main()
