"""Repository-supported inventory step for the calibration dataset.

Scope
-----
This script regenerates or validates the top-level ``seed_refs`` map used by
the new ``commerce_dynamic_database`` cases with ``id_comercio = 1``. It
queries the seeded database for ``id_comercio = 1`` only and resolves the
opaque symbolic keys declared by the dataset to the matching
``producto_presentacion_id`` values.

The script intentionally does NOT inspect, validate, or reinterpret the
preserved ``in_memory`` Subphase 4.11 cases. Those cases keep their
embedded fixtures and their non-1 ``id_comercio`` values.

Out of the runtime path
------------------------
The script lives outside the runtime code path. No runtime module imports
this script. The runner resolves ``seed_refs`` through its own validation
against the same SQLAlchemy session factory.

Modes
-----
``--mode regenerate``
    Writes the resolved mapping back into the dataset JSON under the
    top-level ``seed_refs`` key, preserving the existing case bodies and
    the optional ``eligibility`` block.

``--mode validate``
    Reads the existing ``seed_refs`` map and fails with a clear, structured
    message when any reference is missing, nonexistent, cross-commerce, or
    ambiguous.

Both modes exit non-zero with a clear, structured message per failure mode
on the first error encountered.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.models import (
    CategoriaProducto,
    Presentacion,
    Producto,
    ProductoPresentacion,
)
from backend.services.product_recognition_calibration_commerce_catalog import (
    fingerprint_commerce_catalog,
    load_commerce_catalog_from_database,
    validate_commerce_catalog_inventory_shape,
)

DEFAULT_URL = "postgresql+psycopg:///supernova_test"
DEFAULT_DATASET = "backend/data/product_recognition_calibration_cases.json"
TARGET_COMERCIO_ID = 1

_ARTICLES: tuple[str, ...] = ("de", "del", "la", "las", "el", "los", "y", "con", "sin", "a")



def _normalize(text: str) -> str:
    """Casefold, accent-strip, and collapse whitespace for fuzzy matching."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(
        char for char in decomposed if not unicodedata.combining(char)
    ).casefold().strip()


def _slug_token(text: str) -> str:
    cleaned = _normalize(text)
    return "".join(char if char.isalnum() else "" for char in cleaned)


def _symbolic_key(producto: Producto, presentacion: Presentacion) -> str:
    """Build the opaque symbolic key for a product presentation pair."""
    parts = producto.nombre.replace("-", " ").split()
    tokens = [
        _slug_token(part) for part in parts if part and _slug_token(part) not in _ARTICLES
    ]
    name_token = "_".join(tokens)
    code_token = _slug_token(presentacion.codigo)
    if "Pizza" in producto.nombre or _category_in(producto, "BEBIDAS"):
        return f"pp_{name_token}_{code_token}"
    return f"pp_{name_token}"


def _category_in(producto: Producto, expected: str) -> bool:
    categoria = getattr(producto, "categoria", None)
    if categoria is None:
        return False
    return _normalize(categoria.descripcion) == _normalize(expected)


def _presentations_by_key(
    session: Session, id_comercio: int
) -> dict[str, tuple[int, int, str, str]]:
    """Return ``symbolic_key -> (pp_id, id_comercio, producto, presentacion)``.

    Only presentations whose full activity chain is ``True`` are returned.
    """
    stmt = (
        select(ProductoPresentacion, Producto, Presentacion, CategoriaProducto)
        .join(Producto, Producto.id == ProductoPresentacion.id_producto)
        .join(Presentacion, Presentacion.id == ProductoPresentacion.id_presentacion)
        .join(CategoriaProducto, CategoriaProducto.id == Producto.id_categoria_producto)
        .where(CategoriaProducto.id_comercio == id_comercio)
        .where(Producto.activo.is_(True))
        .where(Producto.disponible.is_(True))
        .where(ProductoPresentacion.activo.is_(True))
        .where(Presentacion.activo.is_(True))
        .where(CategoriaProducto.activo.is_(True))
    )
    index: dict[str, tuple[int, int, str, str]] = {}
    for pp, producto, presentacion, categoria in session.execute(stmt).all():
        key = _symbolic_key(producto, presentacion)
        index[_normalize(key)] = (
            int(pp.id),
            int(categoria.id_comercio),
            str(producto.nombre),
            str(presentacion.codigo),
        )
    return index


def _load_dataset(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        dataset = json.load(file)
    if not isinstance(dataset, dict):
        raise TypeError(f"dataset at {path} must be a JSON object")
    return dataset


def _write_dataset(path: Path, dataset: dict) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(dataset, file, ensure_ascii=False, indent=2)
        file.write("\n")


def _required_symbolic_keys(dataset: dict, id_comercio: int) -> tuple[str, ...]:
    """Return the unique ``expected_producto_presentacion_id_ref`` values
    used by the new ``commerce_dynamic_database`` cases for ``id_comercio``.

    Other comercios and ``in_memory`` cases are excluded by design.
    """
    cases = dataset.get("cases", [])
    if not isinstance(cases, list):
        raise TypeError("dataset cases must be a list")
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            continue
        if case.get("catalog_scope") != "commerce_dynamic_database":
            continue
        if case.get("id_comercio") != id_comercio:
            continue
        ref = case.get("expected_producto_presentacion_id_ref")
        if isinstance(ref, str) and ref:
            seen.add(ref)
    return tuple(sorted(seen))


def _resolve_seed_refs(
    session: Session, dataset: dict, id_comercio: int
) -> dict[str, int]:
    """Resolve every required symbolic key to a unique ``producto_presentacion_id``.

    Raises ``RuntimeError`` with a clear, structured message describing the
    first failure mode encountered:

    - ``missing key`` when the key has no match in the database.
    - ``ambiguous key`` when the resolved symbolic key points to multiple
      presentations.
    """
    index = _presentations_by_key(session, id_comercio)
    inverse: dict[tuple[str, str], list[str]] = {}
    for key, (_, _, nombre, codigo) in index.items():
        inverse.setdefault((_normalize(nombre), _normalize(codigo)), []).append(key)

    resolved: dict[str, int] = {}
    for key in _required_symbolic_keys(dataset, id_comercio):
        target = index.get(_normalize(key))
        if target is None:
            raise RuntimeError(
                f"missing key={key!r} id_comercio={id_comercio}: "
                "no matching product presentation found"
            )
        pp_id, actual_comercio, nombre, codigo = target
        if actual_comercio != id_comercio:
            raise RuntimeError(
                f"cross_commerce key={key!r} id_comercio={id_comercio}: "
                f"resolved to id_comercio={actual_comercio}"
            )
        signature = (_normalize(nombre), _normalize(codigo))
        if len(inverse.get(signature, [])) > 1:
            raise RuntimeError(
                f"ambiguous key={key!r} id_comercio={id_comercio}: "
                f"producto={nombre!r} presentacion={codigo!r} "
                f"matches multiple symbolic keys={inverse[signature]}"
            )
        resolved[key] = int(pp_id)
    return resolved


def _validate_seed_refs(
    session: Session, dataset: dict, id_comercio: int
) -> None:
    """Validate the existing ``seed_refs`` map against the database.

    Fails with a clear, structured message identifying the offending key,
    the value, and the expected commerce scope.
    """
    seed_refs = dataset.get("seed_refs")
    if not isinstance(seed_refs, dict) or not seed_refs:
        raise RuntimeError(
            "missing seed_refs: dataset carries no top-level seed_refs map"
        )
    index = _presentations_by_key(session, id_comercio)
    for key, value in seed_refs.items():
        if not isinstance(key, str) or not key:
            raise RuntimeError(
                f"invalid seed_refs entry: key={key!r} value={value!r}"
            )
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(
                f"invalid seed_refs entry: key={key!r} value={value!r} "
                "(value must be a non-bool integer producto_presentacion_id)"
            )
        target = index.get(_normalize(key))
        if target is None:
            raise RuntimeError(
                f"nonexistent seed_refs value: key={key!r} value={value} "
                f"id_comercio={id_comercio}: no matching product presentation"
            )
        pp_id, actual_comercio, _nombre, _codigo = target
        if pp_id != value:
            raise RuntimeError(
                f"nonexistent seed_refs value: key={key!r} value={value} "
                f"id_comercio={id_comercio}: database pp_id={pp_id}"
            )
        if actual_comercio != id_comercio:
            raise RuntimeError(
                f"cross_commerce seed_refs value: key={key!r} value={value} "
                f"expected_id_comercio={id_comercio} actual_id_comercio={actual_comercio}"
            )
    inverse: dict[tuple[str, str], list[str]] = {}
    for key, (_, _, nombre, codigo) in index.items():
        inverse.setdefault((_normalize(nombre), _normalize(codigo)), []).append(key)
    for key in _required_symbolic_keys(dataset, id_comercio):
        if key not in seed_refs:
            raise RuntimeError(
                f"missing_allowed_key: allowed_key={key!r} "
                f"id_comercio={id_comercio}: not declared in dataset seed_refs"
            )


def _regenerate(
    session: Session, dataset_path: Path, id_comercio: int
) -> dict[str, int]:
    dataset = _load_dataset(dataset_path)
    resolved = _resolve_seed_refs(session, dataset, id_comercio)
    dataset["seed_refs"] = resolved
    _write_dataset(dataset_path, dataset)
    return resolved


def _regenerate_commerce_catalog(
    session: Session, dataset_path: Path, id_comercio: int
) -> tuple[int, str]:
    """Persist the per-commerce runtime-compatible catalog as reproducible evidence.

    The loader issues exactly one query per call and returns the full
    commerce catalog. The runner loads the same catalog at calibration
    time and compares its fingerprint against
    ``dataset["commerce_catalog_fingerprint"][str(id_comercio)]`` to
    detect drift. The persisted inventory is **evidence only** — the
    runner NEVER hands it to the recognizer.
    """
    dataset = _load_dataset(dataset_path)
    catalog = load_commerce_catalog_from_database(session, id_comercio)
    if not catalog.entries:
        raise RuntimeError(
            f"empty commerce catalog: id_comercio={id_comercio}: "
            "the loader returned no producto_presentacion rows"
        )
    payload = [dict(entry) for entry in catalog.entries]
    validate_commerce_catalog_inventory_shape(payload, id_comercio)
    fingerprint = fingerprint_commerce_catalog(catalog)
    inventory_block = dataset.get("commerce_catalog_inventory")
    if not isinstance(inventory_block, dict):
        inventory_block = {}
    inventory_block[str(id_comercio)] = payload
    dataset["commerce_catalog_inventory"] = inventory_block
    fingerprint_block = dataset.get("commerce_catalog_fingerprint")
    if not isinstance(fingerprint_block, dict):
        fingerprint_block = {}
    fingerprint_block[str(id_comercio)] = fingerprint
    dataset["commerce_catalog_fingerprint"] = fingerprint_block
    _write_dataset(dataset_path, dataset)
    return len(payload), fingerprint


def _validate(session: Session, dataset_path: Path, id_comercio: int) -> None:
    dataset = _load_dataset(dataset_path)
    _validate_seed_refs(session, dataset, id_comercio)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Regenerate or validate the seed_refs map for calibration."
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=("regenerate", "validate", "regenerate-commerce-catalog"),
        help=(
            "regenerate writes the resolved seed_refs map; "
            "regenerate-commerce-catalog persists the per-commerce "
            "runtime-compatible catalog as reproducible evidence; "
            "validate only checks seed_refs."
        ),
    )
    parser.add_argument(
        "--dataset",
        default=DEFAULT_DATASET,
        help="Path to the calibration dataset JSON file.",
    )
    parser.add_argument(
        "--id-comercio",
        type=int,
        default=TARGET_COMERCIO_ID,
        help="Target comercio id (default 1).",
    )
    parser.add_argument(
        "--commerce-id",
        type=int,
        dest="commerce_id",
        help="Alias of --id-comercio for the regenerate-commerce-catalog mode.",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("SUPERNOVA_DATABASE_URL", DEFAULT_URL),
        help="SQLAlchemy database URL.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"FAIL: dataset not found: {dataset_path}", file=sys.stderr)
        return 2
    target_comercio = args.id_comercio
    if args.commerce_id is not None:
        target_comercio = args.commerce_id
    engine = create_engine(args.database_url)
    try:
        with Session(engine) as session:
            if args.mode == "regenerate":
                resolved = _regenerate(session, dataset_path, target_comercio)
                print(
                    f"regenerate: id_comercio={target_comercio} "
                    f"seed_refs_count={len(resolved)} dataset={dataset_path}"
                )
            elif args.mode == "regenerate-commerce-catalog":
                count, fingerprint = _regenerate_commerce_catalog(
                    session, dataset_path, target_comercio
                )
                print(
                    f"regenerate-commerce-catalog: id_comercio={target_comercio} "
                    f"entries={count} fingerprint={fingerprint} dataset={dataset_path}"
                )
            else:
                _validate(session, dataset_path, target_comercio)
                print(
                    f"validate: id_comercio={target_comercio} "
                    f"seed_refs_ok=1 dataset={dataset_path}"
                )
        return 0
    except RuntimeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
