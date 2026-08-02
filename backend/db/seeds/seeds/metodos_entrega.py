import json
import os
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.models import MetodosEntrega

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "metodos_entrega.json"
DEFAULT_URL = "postgresql+psycopg:///supernova_test"


def main() -> None:
    url = os.environ.get("SUPERNOVA_DATABASE_URL", DEFAULT_URL)
    rows = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    engine = create_engine(url)
    with Session(engine) as session:
        with session.begin():
            existing = {
                codigo for (codigo,) in session.execute(select(MetodosEntrega.codigo)).all()
            }
            inserted = 0
            for row in rows:
                codigo = row["codigo"]
                if codigo in existing:
                    continue
                session.add(MetodosEntrega(**row))
                existing.add(codigo)
                inserted += 1
            skipped = len(rows) - inserted

    print(f"target={url} inserted={inserted} skipped={skipped} total_in_json={len(rows)}")


if __name__ == "__main__":
    main()
