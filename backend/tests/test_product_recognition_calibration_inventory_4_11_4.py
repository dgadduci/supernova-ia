"""Regression tests for the Subphase 4.11.4 ``--mode regenerate-commerce-catalog`` step.

The new subcommand persists the per-commerce runtime-compatible catalog
as reproducible evidence alongside its SHA-256 fingerprint. The
regeneration MUST be idempotent (running it twice against an unchanged
database produces byte-identical outputs) and any field mutation
MUST update the fingerprint.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backend.scripts.calibration_inventory import (
    _regenerate_commerce_catalog,
)


class _FakeSession:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows
        self.calls = 0

    def execute(self, _stmt: Any) -> SimpleNamespace:
        self.calls += 1
        result_rows = [
            (row, row.producto, row.presentacion, row.producto.categoria)
            for row in self._rows
        ]
        return SimpleNamespace(all=lambda: list(result_rows))


def _fake_row(
    pp_id: int,
    id_comercio: int,
    *,
    producto_nombre: str = "Empanada de Pollo",
    activo: bool = True,
    producto_activo: bool = True,
    presentacion_activo: bool = True,
    disponible: bool = True,
) -> SimpleNamespace:
    categoria = SimpleNamespace(id=1, descripcion="Empanadas", id_comercio=id_comercio)
    producto = SimpleNamespace(
        id=pp_id,
        nombre=producto_nombre,
        activo=producto_activo,
        disponible=disponible,
        categoria=categoria,
    )
    presentacion = SimpleNamespace(
        id=pp_id,
        codigo="UNIDAD",
        descripcion="Unidad",
        activo=presentacion_activo,
    )
    return SimpleNamespace(
        id=pp_id,
        activo=activo,
        producto=producto,
        presentacion=presentacion,
    )


def _write_dataset(path: Path) -> None:
    path.write_text(
        json.dumps({"schema_version": 3, "cases": [], "catalogs": {}}),
        encoding="utf-8",
    )


def test_regenerate_commerce_catalog_persists_block_and_fingerprint(tmp_path: Path):
    rows = [_fake_row(1, 1), _fake_row(2, 1), _fake_row(3, 1)]
    dataset_path = tmp_path / "dataset.json"
    _write_dataset(dataset_path)
    session = _FakeSession(rows)
    count, fingerprint = _regenerate_commerce_catalog(session, dataset_path, 1)
    assert count == 3
    assert len(fingerprint) == 64
    persisted = json.loads(dataset_path.read_text(encoding="utf-8"))
    assert "commerce_catalog_inventory" in persisted
    assert "1" in persisted["commerce_catalog_inventory"]
    assert persisted["commerce_catalog_fingerprint"]["1"] == fingerprint
    inventory = persisted["commerce_catalog_inventory"]["1"]
    assert [entry["producto_presentacion_id"] for entry in inventory] == [1, 2, 3]


def test_regenerate_commerce_catalog_is_idempotent(tmp_path: Path):
    rows = [_fake_row(pp_id, 1) for pp_id in (1, 2, 3)]
    dataset_path = tmp_path / "dataset.json"
    _write_dataset(dataset_path)
    session = _FakeSession(rows)
    _regenerate_commerce_catalog(session, dataset_path, 1)
    first_bytes = dataset_path.read_bytes()
    session = _FakeSession(rows)
    _regenerate_commerce_catalog(session, dataset_path, 1)
    second_bytes = dataset_path.read_bytes()
    assert first_bytes == second_bytes


def test_regenerate_commerce_catalog_changes_fingerprint_on_field_mutation(tmp_path: Path):
    dataset_path = tmp_path / "dataset.json"
    _write_dataset(dataset_path)
    rows_one = [_fake_row(1, 1, producto_nombre="Empanada de Pollo"), _fake_row(2, 1)]
    session = _FakeSession(rows_one)
    _regenerate_commerce_catalog(session, dataset_path, 1)
    first_fingerprint = json.loads(dataset_path.read_text(encoding="utf-8"))["commerce_catalog_fingerprint"]["1"]
    rows_two = [_fake_row(1, 1, producto_nombre="Empanada de Carne"), _fake_row(2, 1)]
    session = _FakeSession(rows_two)
    _regenerate_commerce_catalog(session, dataset_path, 1)
    second_fingerprint = json.loads(dataset_path.read_text(encoding="utf-8"))["commerce_catalog_fingerprint"]["1"]
    assert first_fingerprint != second_fingerprint


def test_regenerate_commerce_catalog_preserves_existing_seed_refs_and_fingerprint(tmp_path: Path):
    rows = [_fake_row(1, 1), _fake_row(2, 1)]
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "seed_refs": {"pp_empanada_pollo": 1},
                "inventory_fingerprint": "seed-fingerprint",
                "cases": [],
                "catalogs": {},
            }
        ),
        encoding="utf-8",
    )
    session = _FakeSession(rows)
    _regenerate_commerce_catalog(session, dataset_path, 1)
    persisted = json.loads(dataset_path.read_text(encoding="utf-8"))
    assert persisted["seed_refs"] == {"pp_empanada_pollo": 1}
    assert persisted["inventory_fingerprint"] == "seed-fingerprint"
    assert "1" in persisted["commerce_catalog_inventory"]
    assert "1" in persisted["commerce_catalog_fingerprint"]


def test_regenerate_commerce_catalog_rejects_empty_catalog(tmp_path: Path):
    dataset_path = tmp_path / "dataset.json"
    _write_dataset(dataset_path)
    session = _FakeSession([])
    with pytest.raises(RuntimeError, match="empty commerce catalog"):
        _regenerate_commerce_catalog(session, dataset_path, 1)
