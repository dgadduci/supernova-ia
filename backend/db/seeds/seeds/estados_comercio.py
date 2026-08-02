import json
import os
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.models import EstadoComercio

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "estados.json"
DEFAULT_URL = "postgresql+psycopg:///supernova_test"


def main() -> None:
    url = os.environ.get("SUPERNOVA_DATABASE_URL", DEFAULT_URL)
    rows = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    engine = create_engine(url)
    with Session(engine) as session:
        with session.begin():
            existing = {
                estado for (estado,) in session.execute(select(EstadoComercio.estado)).all()
            }
            inserted = 0
            for row in rows:
                estado = row["estado"]
                if estado in existing:
                    continue
                session.add(EstadoComercio(estado=estado))
                existing.add(estado)
                inserted += 1
            skipped = len(rows) - inserted

    print(f"target={url} inserted={inserted} skipped={skipped} total_in_json={len(rows)}")


if __name__ == "__main__":
    main()
