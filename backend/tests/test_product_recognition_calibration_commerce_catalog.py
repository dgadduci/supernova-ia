"""Focused unit tests for the per-commerce catalog loader.

The loader is the runtime source of truth for the Subphase 4.11.4
calibration environment: it issues exactly one SQL query per call and
returns the full runtime-compatible commerce catalog — every
commerce-scoped ``producto_presentacion`` entry, active and inactive
alike, with the documented runtime field set. The runner caches the
result on ``self._commerce_catalog_cache``; the inventory regeneration
step reads the catalog through the same loader and persists it as
reproducible evidence alongside its SHA-256 fingerprint.

These tests cover the loader surface independently of the runner and
the SQLAlchemy session. They:

- assert the entries are sorted by ``producto_presentacion_id``
  ascending and deduped;
- assert the fingerprint is deterministic for fixed inputs and
  changes when any field changes;
- assert cross-commerce queries return only the requested commerce;
- assert the documented runtime field set is required and the loader
  rejects malformed entries with a deterministic error;
- assert the persisted-inventory shape validator refuses
  unsorted/duplicate/malformed blocks;
- assert the ``StaleCommerceCatalogError`` refusal carries the
  documented fields and a deterministic message.
"""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any

import pytest

from backend.services.product_recognition_calibration_commerce_catalog import (
    RUNTIME_FIELDS,
    CommerceCatalog,
    CommerceCatalogError,
    MalformedCommerceCatalogError,
    StaleCommerceCatalogError,
    fingerprint_commerce_catalog,
    load_commerce_catalog_from_database,
    validate_commerce_catalog_inventory_shape,
)


def _entry(
    producto_presentacion_id: int,
    *,
    id_comercio: int = 1,
    activo: bool = True,
    producto_activo: bool = True,
    presentacion_activo: bool = True,
    disponible: bool = True,
    producto_nombre: str = "Empanada de Pollo",
    presentacion_codigo: str = "UNIDAD",
) -> dict[str, Any]:
    return {
        "producto_presentacion_id": producto_presentacion_id,
        "producto_id": producto_presentacion_id,
        "presentacion_id": producto_presentacion_id,
        "categoria_id": 1,
        "producto_nombre": producto_nombre,
        "categoria_nombre": "Empanadas",
        "presentacion_codigo": presentacion_codigo,
        "presentacion_descripcion": "Unidad",
        "activo": activo,
        "producto_activo": producto_activo,
        "presentacion_activo": presentacion_activo,
        "disponible": disponible,
    }


class _FakeRow:
    def __init__(self, pp_id: int, id_comercio: int, **overrides: Any) -> None:
        categoria = SimpleNamespace(
            id=1,
            descripcion="Empanadas",
            id_comercio=id_comercio,
        )
        producto = SimpleNamespace(
            id=pp_id,
            nombre=overrides.get("producto_nombre", "Empanada de Pollo"),
            activo=overrides.get("producto_activo", True),
            disponible=overrides.get("disponible", True),
            categoria=categoria,
        )
        presentacion = SimpleNamespace(
            id=pp_id,
            codigo=overrides.get("presentacion_codigo", "UNIDAD"),
            descripcion="Unidad",
            activo=overrides.get("presentacion_activo", True),
        )
        self.id = pp_id
        self.activo = overrides.get("activo", True)
        self.producto = producto
        self.presentacion = presentacion


class _FakeExecuteResult:
    def __init__(self, rows: list[_FakeRow]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[_FakeRow, object, object, object]]:
        return [(row, row.producto, row.presentacion, row.producto.categoria) for row in self._rows]


class _FakeSession:
    def __init__(self, rows: list[_FakeRow]) -> None:
        self._rows = rows
        self.calls: int = 0

    def execute(self, _stmt: Any) -> _FakeExecuteResult:
        self.calls += 1
        return _FakeExecuteResult(self._rows)


class _FakeFilteringSession:
    """Simulates the ``WHERE CategoriaProducto.id_comercio == id_comercio`` filter."""

    def __init__(self, rows: list[_FakeRow]) -> None:
        self._rows = rows
        self.calls: int = 0

    def execute(self, _stmt: Any) -> _FakeExecuteResult:
        self.calls += 1
        return _FakeExecuteResult(self._rows)


def test_runtime_fields_is_frozen_tuple():
    assert isinstance(RUNTIME_FIELDS, tuple)
    assert set(RUNTIME_FIELDS) == {
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
    }


def test_commerce_catalog_is_frozen_and_rejects_mutation():
    catalog = CommerceCatalog(id_comercio=1, entries=(_entry(1),))
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        catalog.entries = (_entry(2),)  # type: ignore[misc]


def test_load_commerce_catalog_from_database_issues_exactly_one_query():
    rows = [_FakeRow(pp_id, 1) for pp_id in (3, 1, 2)]
    session = _FakeSession(rows)
    catalog = load_commerce_catalog_from_database(session, 1)
    assert isinstance(catalog, CommerceCatalog)
    assert session.calls == 1
    assert [entry["producto_presentacion_id"] for entry in catalog.entries] == [1, 2, 3]


def test_load_commerce_catalog_dedupes_repeated_rows():
    rows = [_FakeRow(1, 1), _FakeRow(1, 1), _FakeRow(2, 1)]
    session = _FakeSession(rows)
    catalog = load_commerce_catalog_from_database(session, 1)
    assert [entry["producto_presentacion_id"] for entry in catalog.entries] == [1, 2]


def test_load_commerce_catalog_preserves_availability_flags():
    rows = [
        _FakeRow(1, 1, activo=True, producto_activo=True, presentacion_activo=True, disponible=True),
        _FakeRow(2, 1, activo=False, producto_activo=True, presentacion_activo=True, disponible=True),
        _FakeRow(3, 1, activo=True, producto_activo=False, presentacion_activo=True, disponible=True),
        _FakeRow(4, 1, activo=True, producto_activo=True, presentacion_activo=False, disponible=True),
        _FakeRow(5, 1, activo=True, producto_activo=True, presentacion_activo=True, disponible=False),
    ]
    session = _FakeSession(rows)
    catalog = load_commerce_catalog_from_database(session, 1)
    flags = {
        entry["producto_presentacion_id"]: (
            entry["activo"],
            entry["producto_activo"],
            entry["presentacion_activo"],
            entry["disponible"],
        )
        for entry in catalog.entries
    }
    assert flags[1] == (True, True, True, True)
    assert flags[2] == (False, True, True, True)
    assert flags[3] == (True, False, True, True)
    assert flags[4] == (True, True, False, True)
    assert flags[5] == (True, True, True, False)


def test_load_commerce_catalog_ignores_rows_from_other_comercios():
    """The runtime SQL filter ensures only ``id_comercio`` rows surface;
    this test simulates that filter via the session and confirms the
    catalog contains only rows belonging to ``id_comercio == 1``."""
    rows = [_FakeRow(1, 1), _FakeRow(2, 2), _FakeRow(3, 1)]
    filtered = [row for row in rows if row.producto.categoria.id_comercio == 1]
    session = _FakeSession(filtered)
    catalog = load_commerce_catalog_from_database(session, 1)
    assert [entry["producto_presentacion_id"] for entry in catalog.entries] == [1, 3]


def test_load_commerce_catalog_rejects_non_int_id_comercio():
    session = _FakeSession([])
    with pytest.raises(CommerceCatalogError):
        load_commerce_catalog_from_database(session, "1")  # type: ignore[arg-type]


def test_fingerprint_is_deterministic_for_identical_inputs():
    rows = [_FakeRow(pp_id, 1) for pp_id in (1, 2, 3)]
    catalog_a = load_commerce_catalog_from_database(_FakeSession(rows), 1)
    catalog_b = load_commerce_catalog_from_database(_FakeSession(rows), 1)
    assert fingerprint_commerce_catalog(catalog_a) == fingerprint_commerce_catalog(catalog_b)


def test_fingerprint_changes_when_entry_changes():
    base_rows = [_FakeRow(pp_id, 1) for pp_id in (1, 2)]
    base_catalog = load_commerce_catalog_from_database(_FakeSession(base_rows), 1)
    altered_rows = [
        _FakeRow(1, 1, producto_nombre="Empanada de Carne"),
        _FakeRow(2, 1),
    ]
    altered_catalog = load_commerce_catalog_from_database(_FakeSession(altered_rows), 1)
    assert fingerprint_commerce_catalog(base_catalog) != fingerprint_commerce_catalog(altered_catalog)


def test_fingerprint_changes_when_availability_flag_changes():
    base_rows = [_FakeRow(1, 1, disponible=True), _FakeRow(2, 1, disponible=True)]
    base_catalog = load_commerce_catalog_from_database(_FakeSession(base_rows), 1)
    altered_rows = [_FakeRow(1, 1, disponible=True), _FakeRow(2, 1, disponible=False)]
    altered_catalog = load_commerce_catalog_from_database(_FakeSession(altered_rows), 1)
    assert fingerprint_commerce_catalog(base_catalog) != fingerprint_commerce_catalog(altered_catalog)


def test_fingerprint_changes_when_comercio_differs():
    rows_one = [_FakeRow(1, 1)]
    catalog_one = load_commerce_catalog_from_database(_FakeSession(rows_one), 1)
    rows_two = [_FakeRow(1, 2)]
    catalog_two = load_commerce_catalog_from_database(_FakeSession(rows_two), 2)
    assert fingerprint_commerce_catalog(catalog_one) != fingerprint_commerce_catalog(catalog_two)


def test_validate_commerce_catalog_inventory_shape_accepts_well_formed_block():
    block = [_entry(1), _entry(2), _entry(3)]
    validate_commerce_catalog_inventory_shape(block, 1)


def test_validate_commerce_catalog_inventory_shape_rejects_non_list():
    with pytest.raises(MalformedCommerceCatalogError):
        validate_commerce_catalog_inventory_shape({"entries": [_entry(1)]}, 1)


def test_validate_commerce_catalog_inventory_shape_rejects_unsorted():
    block = [_entry(3), _entry(1), _entry(2)]
    with pytest.raises(MalformedCommerceCatalogError):
        validate_commerce_catalog_inventory_shape(block, 1)


def test_validate_commerce_catalog_inventory_shape_rejects_duplicates():
    block = [_entry(1), _entry(1), _entry(2)]
    with pytest.raises(MalformedCommerceCatalogError):
        validate_commerce_catalog_inventory_shape(block, 1)


def test_validate_commerce_catalog_inventory_shape_rejects_missing_field():
    block = [{**_entry(1), "activo": True, "disponible": True}]
    del block[0]["producto_activo"]
    with pytest.raises(MalformedCommerceCatalogError):
        validate_commerce_catalog_inventory_shape(block, 1)


def test_validate_commerce_catalog_inventory_shape_rejects_wrong_type():
    block = [{**_entry(1), "activo": 1}]
    with pytest.raises(MalformedCommerceCatalogError):
        validate_commerce_catalog_inventory_shape(block, 1)


def test_stale_commerce_catalog_error_uses_documented_message():
    error = StaleCommerceCatalogError(
        id_comercio=1,
        expected_fingerprint="deadbeef",
        actual_fingerprint="feedface",
    )
    message = str(error)
    assert "id_comercio=1" in message
    assert "expected_fingerprint=deadbeef" in message
    assert "actual_fingerprint=feedface" in message
    assert error.id_comercio == 1
    assert error.expected_fingerprint == "deadbeef"
    assert error.actual_fingerprint == "feedface"


def test_stale_commerce_catalog_error_uses_missing_for_absent_persisted_fingerprint():
    error = StaleCommerceCatalogError(
        id_comercio=1,
        expected_fingerprint=None,
        actual_fingerprint="feedface",
    )
    message = str(error)
    assert "expected_fingerprint=missing" in message
    assert "actual_fingerprint=feedface" in message


def test_stale_commerce_catalog_error_carries_no_case_catalog_fields():
    error = StaleCommerceCatalogError(
        id_comercio=1,
        expected_fingerprint="deadbeef",
        actual_fingerprint="feedface",
    )
    forbidden = (
        "allowed_candidate_ids",
        "restricted_candidate_ids",
        "expected_decision",
        "expected_producto_presentacion_id",
    )
    payload = vars(error)
    for name in forbidden:
        assert name not in payload
