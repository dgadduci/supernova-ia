"""Run every seed in dependency order against the configured database.

This script is the single entry point for bring-up of a development or test
database. Each individual seed under ``backend/db/seeds/seeds/`` is idempotent
and prints its own ``inserted=N skipped=M`` line; this orchestrator just runs
them in the correct order so the FK chain is satisfied.

Dependency order::

    estados_comercio          -> no deps
    medios_pago               -> no deps
    metodos_entrega           -> no deps
    presentaciones            -> no deps
    comercios                 -> estados_comercio
    comercio_medios_pago      -> comercios, medios_pago
    comercio_metodos_entrega  -> comercios, metodos_entrega
    categorias_productos      -> comercios
    productos                 -> categorias_productos, comercios
    producto_presentaciones   -> productos, presentaciones
    producto_precios          -> producto_presentaciones

Usage::

    PYTHONPATH=. ./venv/bin/python -m backend.db.seeds.setup_all
    SUPERNOVA_DATABASE_URL=postgresql+psycopg:///supernova \
        PYTHONPATH=. ./venv/bin/python -m backend.db.seeds.setup_all
"""
from __future__ import annotations

import os
import runpy
import sys
import traceback
from pathlib import Path


_SEEDS_DIR = Path(__file__).resolve().parent / "seeds"

_SEED_PLAN: tuple[str, ...] = (
    "estados_comercio",
    "medios_pago",
    "metodos_entrega",
    "presentaciones",
    "comercios",
    "comercio_medios_pago",
    "comercio_metodos_entrega",
    "categorias_productos",
    "productos",
    "producto_presentaciones",
    "producto_precios",
)


def _run_one(name: str) -> None:
    script_path = _SEEDS_DIR / f"{name}.py"
    if not script_path.exists():
        raise FileNotFoundError(f"seed script missing: {script_path}")
    namespace = runpy.run_path(str(script_path), run_name="__main__")
    main = namespace.get("main")
    if main is None:
        raise RuntimeError(f"seed {name!r} does not expose a main() callable")
    main()


def main() -> None:
    url = os.environ.get("SUPERNOVA_DATABASE_URL", "postgresql+psycopg:///supernova_test")
    print(f"target={url}")
    print(f"plan={len(_SEED_PLAN)} seeds")
    for name in _SEED_PLAN:
        print(f"--> {name}")
        try:
            _run_one(name)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
            print(f"FAIL seed={name} sys_exit={code}", file=sys.stderr)
            sys.exit(code)
        except Exception as exc:
            print(f"FAIL seed={name} error={type(exc).__name__}: {exc}", file=sys.stderr)
            traceback.print_exc()
            sys.exit(1)
    print("done")


__all__ = ["main"]


if __name__ == "__main__":
    main()
