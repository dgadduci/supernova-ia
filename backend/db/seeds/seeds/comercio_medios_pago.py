import json
import os
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.models import Comercio, ComercioMedioPago, MediosPago

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "comercio_medios_pago.json"
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
            medio_pago_ids = {
                codigo: id_
                for codigo, id_ in session.execute(select(MediosPago.codigo, MediosPago.id)).all()
            }
            existing_pairs = {
                (c, m)
                for c, m in session.execute(
                    select(ComercioMedioPago.id_comercio, ComercioMedioPago.id_medio_pago)
                ).all()
            }
            inserted = 0
            for row in rows:
                cuit = row["comercio_cuit"]
                codigo = row["medio_pago_codigo"]
                if cuit not in comercio_ids:
                    raise ValueError(f"comercio_cuit {cuit!r} not found in comercios")
                if codigo not in medio_pago_ids:
                    raise ValueError(f"medio_pago_codigo {codigo!r} not found in medios_pago")
                pair = (comercio_ids[cuit], medio_pago_ids[codigo])
                if pair in existing_pairs:
                    continue
                payload = {
                    "id_comercio": pair[0],
                    "id_medio_pago": pair[1],
                    "activo": row["activo"],
                    "titular": row["titular"],
                    "alias": row["alias"],
                }
                session.add(ComercioMedioPago(**payload))
                existing_pairs.add(pair)
                inserted += 1
            skipped = len(rows) - inserted

    print(f"target={url} inserted={inserted} skipped={skipped} total_in_json={len(rows)}")


if __name__ == "__main__":
    main()
