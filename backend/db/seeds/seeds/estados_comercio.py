import json
import os
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.models import EstadoComercio
from backend.models.estado_comercio import EstadoComercioModoOperacion

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "estados.json"
DEFAULT_URL = "postgresql+psycopg:///supernova_test"


def _build_estado(row: dict) -> EstadoComercio:
    modo_value = row["modo_operacion"]
    try:
        modo_enum = EstadoComercioModoOperacion(modo_value)
    except ValueError as exc:
        raise ValueError(
            f"estado_comercio seed row {row.get('codigo')!r} has invalid "
            f"modo_operacion {modo_value!r}"
        ) from exc
    return EstadoComercio(
        codigo=row["codigo"],
        descripcion=row["descripcion"],
        modo_operacion=modo_enum,
        seleccionable=bool(row.get("seleccionable", False)),
    )


def main() -> None:
    url = os.environ.get("SUPERNOVA_DATABASE_URL", DEFAULT_URL)
    rows = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    engine = create_engine(url)
    with Session(engine) as session:
        with session.begin():
            existing = {
                codigo
                for (codigo,) in session.execute(
                    select(EstadoComercio.codigo)
                ).all()
            }
            inserted = 0
            for row in rows:
                codigo = row["codigo"]
                if codigo in existing:
                    session.execute(
                        EstadoComercio.__table__.update()
                        .where(EstadoComercio.codigo == codigo)
                        .values(
                            descripcion=row["descripcion"],
                            modo_operacion=_build_estado(row).modo_operacion,
                            seleccionable=bool(
                                row.get("seleccionable", False)
                            ),
                        )
                    )
                    existing.add(codigo)
                    continue
                session.add(_build_estado(row))
                existing.add(codigo)
                inserted += 1
            skipped = len(rows) - inserted

    print(f"target={url} inserted={inserted} skipped={skipped} total_in_json={len(rows)}")


if __name__ == "__main__":
    main()