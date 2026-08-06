"""Per-commerce runtime-compatible catalog loader for the calibration runner.

The fuzzy product recognizer (``backend.recognizers.product_recognizer``) is
handed its catalog by the caller. At runtime every resolver
(``backend.intents.context.product_selection_context_resolver``,
``backend.intents.context.product_modification_resolver``,
``backend.intents.recognizers.quitar_producto_recognizer``,
``backend.intents.recognizers.modificar_producto_recognizer``) and the
manual loader at ``backend/tests/manual_product_recognizer.py`` build a
catalog of ``producto_presentacion`` dicts with the documented runtime
field set::

    {
        "producto_presentacion_id": int,
        "producto_id": int,
        "presentacion_id": int,
        "categoria_id": int,
        "producto_nombre": str,
        "categoria_nombre": str,
        "presentacion_codigo": str,
        "presentacion_descripcion": str,
        "activo": bool,
        "producto_activo": bool,
        "presentacion_activo": bool,
        "disponible": bool,
    }

The Subphase 4.11 calibration runner (pre-4.11.4) hands the fuzzy
recognizer the embedded ``dataset["catalogs"][<fixture>].entries`` which,
for ``catalog_scope: "commerce_dynamic_database"`` cases, is empty by
design (Subphase 4.11.1 contract). The empty catalog masks the
recognizer's real behavior for the 29 fuzzy cases bucketed under
``real_fuzzy_recognizer_failure`` in Subphase 4.11.3.

Subphase 4.11.4 corrects the calibration environment: the runner MUST
load the full runtime-compatible commerce catalog from PostgreSQL once
per commerce per calibration run. The loader lives here so it can be
shared with the inventory regeneration step
(``backend.scripts.calibration_inventory``) and exercised independently
by focused tests.

The loader issues exactly one query per call. The runner caches the
result on ``self._commerce_catalog_cache``; the inventory step reads the
catalog through the same loader and persists the result as reproducible
evidence alongside its SHA-256 fingerprint. The persisted block is
**evidence only** — the runner NEVER hands the persisted inventory to
the recognizer.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import (
    CategoriaProducto,
    Presentacion,
    Producto,
    ProductoPresentacion,
)
from backend.services.product_recognition_calibration_policy import canonical_json

RUNTIME_FIELDS: tuple[str, ...] = (
    "producto_presentacion_id",
    "producto_id",
    "presentacion_id",
    "categoria_id",
    "producto_nombre",
    "categoria_nombre",
    "presentacion_codigo",
    "presentacion_descripcion",
    "activo",
    "producto_activo",
    "presentacion_activo",
    "disponible",
)


class CommerceCatalogError(ValueError):
    """Base class for catalog loader errors."""


class MalformedCommerceCatalogError(CommerceCatalogError):
    """Raised when a catalog entry does not match the documented runtime field set."""


class CrossCommerceCatalogError(CommerceCatalogError):
    """Raised when a loader result leaks rows from another comercio."""


class StaleCommerceCatalogError(CommerceCatalogError):
    """Raised when the fresh DB catalog fingerprint disagrees with the persisted evidence.

    The runner uses this refusal to fail closed: the CLI returns non-zero
    and no calibration report is emitted. The exception carries the
    ``id_comercio`` plus the expected (persisted) and actual (fresh DB)
    fingerprints so the operator can localise drift without re-running
    the inventory step. The expected fingerprint is ``None`` when the
    persisted block omits the entry for the visited ``id_comercio``.
    """

    def __init__(
        self,
        *,
        id_comercio: int,
        expected_fingerprint: str | None,
        actual_fingerprint: str,
    ) -> None:
        expected_repr = expected_fingerprint if expected_fingerprint is not None else "missing"
        message = (
            f"stale commerce catalog: id_comercio={id_comercio} "
            f"expected_fingerprint={expected_repr} "
            f"actual_fingerprint={actual_fingerprint}"
        )
        super().__init__(message)
        self.id_comercio = id_comercio
        self.expected_fingerprint = expected_fingerprint
        self.actual_fingerprint = actual_fingerprint


@dataclass(frozen=True)
class CommerceCatalog:
    """A deterministic snapshot of one commerce's runtime-compatible catalog.

    The dataclass is frozen; callers MUST NOT mutate the entries tuple.
    The tuple ordering is the canonical ascending order by
    ``producto_presentacion_id`` — see ``_canonicalize_entries``.
    """

    id_comercio: int
    entries: tuple[dict[str, Any], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.id_comercio, int) or isinstance(self.id_comercio, bool):
            raise CommerceCatalogError("id_comercio must be an int")
        if not isinstance(self.entries, tuple):
            raise CommerceCatalogError("entries must be a tuple of dicts")
        for entry in self.entries:
            if not isinstance(entry, dict):
                raise CommerceCatalogError("entries must be dicts")
        _validate_entry_shape(self.entries, self.id_comercio)


def _build_entry(pp: ProductoPresentacion) -> dict[str, Any]:
    producto: Producto = pp.producto
    presentacion: Presentacion = pp.presentacion
    categoria: CategoriaProducto = producto.categoria
    return {
        "producto_presentacion_id": int(pp.id),
        "producto_id": int(producto.id),
        "presentacion_id": int(presentacion.id),
        "categoria_id": int(categoria.id),
        "producto_nombre": str(producto.nombre),
        "categoria_nombre": str(categoria.descripcion),
        "presentacion_codigo": str(presentacion.codigo),
        "presentacion_descripcion": str(presentacion.descripcion),
        "activo": bool(pp.activo),
        "producto_activo": bool(producto.activo),
        "presentacion_activo": bool(presentacion.activo),
        "disponible": bool(producto.disponible),
    }


def _canonicalize_entries(
    entries: Iterable[dict[str, Any]], id_comercio: int
) -> tuple[dict[str, Any], ...]:
    """Return the entries sorted by ``producto_presentacion_id`` ascending and deduped.

    The function also rejects cross-commerce leaks: every entry MUST
    come from the requested ``id_comercio``. The runtime assembly path
    filters on the comercio via the join, so cross-commerce rows are a
    loader bug, not a runtime condition.
    """
    deduped: dict[int, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise MalformedCommerceCatalogError(
                f"id_comercio={id_comercio}: catalog entry must be a dict, got {type(entry).__name__}"
            )
        pp_id = entry.get("producto_presentacion_id")
        if not isinstance(pp_id, int) or isinstance(pp_id, bool):
            raise MalformedCommerceCatalogError(
                f"id_comercio={id_comercio}: producto_presentacion_id must be an int"
            )
        if pp_id in deduped:
            continue
        deduped[pp_id] = entry
    return tuple(entry for _, entry in sorted(deduped.items()))


def _validate_entry_shape(
    entries: tuple[dict[str, Any], ...], id_comercio: int
) -> None:
    """Reject entries that do not carry the documented runtime field set."""
    int_fields = (
        "producto_presentacion_id",
        "producto_id",
        "presentacion_id",
        "categoria_id",
    )
    str_fields = (
        "producto_nombre",
        "categoria_nombre",
        "presentacion_codigo",
        "presentacion_descripcion",
    )
    bool_fields = (
        "activo",
        "producto_activo",
        "presentacion_activo",
        "disponible",
    )
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise MalformedCommerceCatalogError(
                f"id_comercio={id_comercio} index={index}: entry must be a dict"
            )
        for key in int_fields + str_fields + bool_fields:
            if key not in entry:
                raise MalformedCommerceCatalogError(
                    f"id_comercio={id_comercio} index={index}: missing field {key!r}"
                )
            value = entry[key]
            if key in int_fields:
                if not isinstance(value, int) or isinstance(value, bool):
                    raise MalformedCommerceCatalogError(
                        f"id_comercio={id_comercio} index={index}: {key} must be a non-bool int"
                    )
            elif key in str_fields:
                if not isinstance(value, str):
                    raise MalformedCommerceCatalogError(
                        f"id_comercio={id_comercio} index={index}: {key} must be a str"
                    )
            else:
                if not isinstance(value, bool):
                    raise MalformedCommerceCatalogError(
                        f"id_comercio={id_comercio} index={index}: {key} must be a bool"
                    )


def load_commerce_catalog_from_database(
    session: Session, id_comercio: int
) -> CommerceCatalog:
    """Load the full runtime-compatible catalog for ``id_comercio`` from PostgreSQL.

    The query joins ``ProductoPresentacion`` with ``Producto`` and
    ``Presentacion`` (and ``CategoriaProducto``) filtered to
    ``id_comercio == id_comercio``, mirroring the runtime assembly at
    ``backend/tests/manual_product_recognizer.py::_load_catalog``. No
    availability filtering is applied: entries whose ``activo`` /
    ``producto_activo`` / ``presentacion_activo`` / ``disponible`` flag
    is ``False`` remain in the catalog with their original flags
    preserved exactly so the recognizer's existing
    ``disponibles`` / ``encontrados_no_disponibles`` split
    (``backend/recognizers/product_recognizer.py:543-561``) can route
    them. Inactive entries are NOT silently removed.

    The function executes exactly one SQL query per call. The runner
    caches the result on ``self._commerce_catalog_cache`` and reuses it
    for every ``commerce_dynamic_database`` case at that commerce; the
    inventory regeneration step reads the catalog through the same
    loader so the persisted evidence is byte-identical to the fresh DB
    catalog.
    """
    if not isinstance(id_comercio, int) or isinstance(id_comercio, bool):
        raise CommerceCatalogError("id_comercio must be a non-bool int")
    stmt = (
        select(ProductoPresentacion, Producto, Presentacion, CategoriaProducto)
        .join(Producto, Producto.id == ProductoPresentacion.id_producto)
        .join(Presentacion, Presentacion.id == ProductoPresentacion.id_presentacion)
        .join(CategoriaProducto, CategoriaProducto.id == Producto.id_categoria_producto)
        .where(CategoriaProducto.id_comercio == id_comercio)
    )
    raw_entries: list[dict[str, Any]] = []
    for pp, _producto, _presentacion, _categoria in session.execute(stmt).all():
        raw_entries.append(_build_entry(pp))
    entries = _canonicalize_entries(raw_entries, id_comercio)
    return CommerceCatalog(id_comercio=id_comercio, entries=entries)


def validate_commerce_catalog_inventory_shape(
    inventory: Any, id_comercio: int
) -> None:
    """Confirm the persisted ``commerce_catalog_inventory[<id>]`` block is well-formed.

    The function is **evidence-only**: it does NOT return the inventory,
    it does NOT load from the database, and the runner NEVER hands its
    result to the recognizer. The runner uses the function only to assert
    that the persisted block is sorted, deduped, and carries the
    documented runtime field set — so the fingerprint comparison in
    :func:`fingerprint_commerce_catalog` is meaningful.

    Raises ``MalformedCommerceCatalogError`` on any structural defect.
    """
    if not isinstance(inventory, list):
        raise MalformedCommerceCatalogError(
            f"id_comercio={id_comercio}: persisted inventory must be a list"
        )
    for index, entry in enumerate(inventory):
        if not isinstance(entry, dict):
            raise MalformedCommerceCatalogError(
                f"id_comercio={id_comercio} index={index}: persisted inventory entry must be a dict"
            )
    observed = [entry.get("producto_presentacion_id") for entry in inventory]
    if any(not isinstance(value, int) or isinstance(value, bool) for value in observed):
        raise MalformedCommerceCatalogError(
            f"id_comercio={id_comercio}: persisted inventory entries must carry a non-bool int producto_presentacion_id"
        )
    observed_ints = [int(value) for value in observed]
    if observed_ints != sorted(observed_ints):
        raise MalformedCommerceCatalogError(
            f"id_comercio={id_comercio}: persisted inventory is not sorted by "
            "producto_presentacion_id ascending"
        )
    if len(observed_ints) != len(set(observed_ints)):
        raise MalformedCommerceCatalogError(
            f"id_comercio={id_comercio}: persisted inventory contains duplicate producto_presentacion_id values"
        )
    canonical = _canonicalize_entries(inventory, id_comercio)
    _validate_entry_shape(canonical, id_comercio)


def fingerprint_commerce_catalog(catalog: CommerceCatalog) -> str:
    """Return the SHA-256 fingerprint (lowercase hex) of the catalog entries.

    The fingerprint is computed over the canonical JSON of the entries
    tuple — sorted object keys, stable list order, finite JSON values.
    Two catalogs that contain the same entries in the same order produce
    the same fingerprint. The id_comercio is excluded from the digest:
    the same commerce catalog shared between two datasets with different
    ``id_comercio`` annotations would otherwise produce a divergent
    fingerprint, which is not what the staleness check is for.

    The persisted ``commerce_catalog_fingerprint[<id_comercio>]`` is the
    reproducible evidence of the database snapshot the change was
    authored against; at calibration time the runner loads the fresh
    DB catalog and compares this fingerprint to detect drift.
    """
    payload = {
        "id_comercio": catalog.id_comercio,
        "entries": list(catalog.entries),
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


__all__ = [
    "RUNTIME_FIELDS",
    "CommerceCatalog",
    "CommerceCatalogError",
    "CrossCommerceCatalogError",
    "MalformedCommerceCatalogError",
    "StaleCommerceCatalogError",
    "fingerprint_commerce_catalog",
    "load_commerce_catalog_from_database",
    "validate_commerce_catalog_inventory_shape",
]
