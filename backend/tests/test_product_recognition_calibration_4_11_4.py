"""Focused tests for Subphase 4.11.4 (per-commerce catalog caching and staleness).

The runner MUST load the full runtime-compatible commerce catalog from
PostgreSQL for each ``id_comercio`` it encounters at most once per
calibration run. The catalog is the fresh DB catalog — never the
persisted ``commerce_catalog_inventory`` block. The runner compares the
fresh DB fingerprint against the persisted
``commerce_catalog_fingerprint`` and refuses to start with
``StaleCommerceCatalogError`` on mismatch.

The tests use a fake session that returns a deterministic catalog and
records the number of database calls so the caching invariants are
pinned down. No real PostgreSQL is required.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.orm import Session

from backend.services.product_presentation_vector_match import (
    ProductPresentationVectorMatch,
)
from backend.services.product_recognition_calibration_commerce_catalog import (
    StaleCommerceCatalogError,
    fingerprint_commerce_catalog,
    load_commerce_catalog_from_database,
)
from backend.services.product_recognition_calibration_policy import (
    HybridDecisionPolicy,
    validate_dataset,
)
from backend.services.product_recognition_calibration_runner import (
    ProductRecognitionCalibrationRunner,
)


class _FakeComercioSession:
    """Simulates a SQLAlchemy session for the per-commerce catalog loader.

    The first ``execute`` call (the runner's
    ``_build_id_commerce_index``) returns 2-tuples ``(pp_id, id_comercio)``.
    Subsequent calls (the per-commerce catalog loader) return 4-tuples
    matching the SQLAlchemy join order: ``(pp, producto, presentacion, categoria)``.
    The session tracks the total number of ``execute`` calls so the
    runner's caching invariants can be asserted.
    """

    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = list(rows)
        self.calls: int = 0

    def execute(self, _stmt: Any) -> SimpleNamespace:
        self.calls += 1
        if self.calls == 1:
            payload = [
                (int(row.id), int(row.producto.categoria.id_comercio))
                for row in self._rows
            ]
        else:
            payload = [
                (row, row.producto, row.presentacion, row.producto.categoria)
                for row in self._rows
            ]
        return SimpleNamespace(all=lambda: list(payload))


def _compute_expected_fingerprint(rows: list[SimpleNamespace]) -> str:
    """Compute the fingerprint using a dedicated one-shot session."""
    class _FourTupleSession:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, _stmt: Any) -> SimpleNamespace:
            self.calls += 1
            payload = [
                (row, row.producto, row.presentacion, row.producto.categoria)
                for row in rows
            ]
            return SimpleNamespace(all=lambda: list(payload))

    fingerprint_session = cast(Session, _FourTupleSession())
    catalog = load_commerce_catalog_from_database(fingerprint_session, 1)
    return fingerprint_commerce_catalog(catalog)


def _catalog_row(
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


class _StatefulRecognizer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[int, ...]]] = []

    def recognize(self, text: str, catalog: list[dict]) -> dict[str, Any]:
        ids = tuple(entry["producto_presentacion_id"] for entry in catalog)
        self.calls.append((text, ids))
        if not catalog:
            return {
                "encontrados": [],
                "encontrados_posibles": [],
                "encontrados_no_disponibles": [],
                "no_encontrados": [],
            }
        target = catalog[0]
        return {
            "encontrados": [
                {
                    "producto_presentacion_id": target["producto_presentacion_id"],
                    "producto_nombre": target["producto_nombre"],
                    "cantidad": 1,
                    "texto_origen": text,
                }
            ],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }


class _StaticEmbedding:
    def embed_query(self, text: str) -> list[float]:
        return [0.0] * 4


class _AlwaysVector:
    def __init__(self, target_id: int) -> None:
        self.target_id = target_id

    def search_similar(self, **kwargs: Any) -> list[ProductPresentationVectorMatch]:
        return [ProductPresentationVectorMatch(self.target_id, 0.9, "canonical")]


def _build_runner(
    session: _FakeComercioSession,
    *,
    target_id: int = 1,
) -> ProductRecognitionCalibrationRunner:
    runner = ProductRecognitionCalibrationRunner(
        recognizer=cast(Any, _StatefulRecognizer()),
        embedding_client=cast(Any, _StaticEmbedding()),
        vector_search_factory=lambda: _AlwaysVector(target_id),
        session=cast(Session, session),
    )
    return runner


def _v3_dynamic_dataset(
    *,
    commerce_catalog_inventory: dict | None = None,
    commerce_catalog_fingerprint: dict | None = None,
    extra_case_overrides: dict | None = None,
) -> dict:
    dataset: dict = {
        "schema_version": 3,
        "cases": [
            {
                "case_id": "c1-dynamic",
                "catalog_fixture": "modificar_producto_real_flow_dynamic",
                "catalog_scope": "commerce_dynamic_database",
                "reason": "commerce_dynamic_database case at comercio 1",
                "expected_producto_presentacion_id": 1,
                "expected_quantity": 1,
                "id_comercio": 1,
                "input_text": "empanada",
                "expected_decision": "unique",
                "allowed_candidate_ids": [1, 2],
                "restricted_candidate_ids": [],
                "match_expectation": "canonical",
                "presentation_resolution_expectation": "resolved",
                "category": "canonical",
            },
            {
                "case_id": "c1-dynamic-2",
                "catalog_fixture": "modificar_producto_real_flow_dynamic",
                "catalog_scope": "commerce_dynamic_database",
                "reason": "second commerce_dynamic_database case at comercio 1",
                "expected_producto_presentacion_id": 2,
                "expected_quantity": 1,
                "id_comercio": 1,
                "input_text": "pollo",
                "expected_decision": "unique",
                "allowed_candidate_ids": [1, 2],
                "restricted_candidate_ids": [],
                "match_expectation": "canonical",
                "presentation_resolution_expectation": "resolved",
                "category": "canonical",
            },
        ],
        "catalogs": {
            "modificar_producto_real_flow_dynamic": {
                "scope": "commerce_dynamic_database",
                "entries": [],
            }
        },
    }
    if extra_case_overrides:
        for key, value in extra_case_overrides.items():
            dataset["cases"][0][key] = value
    if commerce_catalog_inventory is not None:
        dataset["commerce_catalog_inventory"] = commerce_catalog_inventory
    if commerce_catalog_fingerprint is not None:
        dataset["commerce_catalog_fingerprint"] = commerce_catalog_fingerprint
    return dataset


def test_runner_uses_fresh_db_catalog_for_commerce_dynamic_database_case():
    rows = [_catalog_row(1, 1), _catalog_row(2, 1)]
    session = _FakeComercioSession(rows)
    expected_fingerprint = _compute_expected_fingerprint(rows)

    session.calls = 0
    dataset = _v3_dynamic_dataset(commerce_catalog_fingerprint={"1": expected_fingerprint})
    runner = _build_runner(session, target_id=1)
    policy = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 3)
    runner.run(dataset, policies=[policy])
    recognizer = runner._recognizer  # type: ignore[attr-defined]
    first_case_catalog = recognizer.calls[0][1]
    second_case_catalog = recognizer.calls[1][1]
    assert first_case_catalog == (1, 2)
    assert first_case_catalog == second_case_catalog
    assert runner.commerce_catalog_cache_size() == 1
    # The runner's first SQL call is _build_id_commerce_index (validation
    # step); the second SQL call is the commerce catalog loader. The
    # catalog loader is the only call to the per-commerce catalog code
    # path, and the second case at the same commerce MUST hit the cache.
    assert session.calls == 2


def test_runner_uses_cached_fresh_db_catalog_not_persisted_inventory():
    """The catalog handed to the recognizer is the fresh DB catalog,
    even when the persisted ``commerce_catalog_inventory`` is present
    and contains the same entries. The persisted inventory is
    reproducible evidence only; the runner does not hand it to the
    recognizer."""
    rows = [_catalog_row(1, 1), _catalog_row(2, 1)]
    session = _FakeComercioSession(rows)
    expected_fingerprint = _compute_expected_fingerprint(rows)

    session.calls = 0
    persisted_inventory = {
        "1": [
            {
                "producto_presentacion_id": 1,
                "producto_id": 1,
                "presentacion_id": 1,
                "categoria_id": 1,
                "producto_nombre": "DIFFERENT",
                "categoria_nombre": "X",
                "presentacion_codigo": "X",
                "presentacion_descripcion": "",
                "activo": True,
                "producto_activo": True,
                "presentacion_activo": True,
                "disponible": True,
            },
        ]
    }
    dataset = _v3_dynamic_dataset(
        commerce_catalog_inventory=persisted_inventory,
        commerce_catalog_fingerprint={"1": expected_fingerprint},
    )
    runner = _build_runner(session, target_id=1)
    policy = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 3)
    runner.run(dataset, policies=[policy])
    recognizer = runner._recognizer  # type: ignore[attr-defined]
    first_case_catalog = recognizer.calls[0][1]
    assert first_case_catalog == (1, 2)


def test_runner_preserves_in_memory_cases_verbatim():
    """The 11 preserved in-memory cases continue to use their embedded catalog."""
    rows = [_catalog_row(1, 1), _catalog_row(2, 1)]
    session = _FakeComercioSession(rows)
    expected_fingerprint = _compute_expected_fingerprint(rows)

    dataset: dict = {
        "schema_version": 3,
        "cases": [
            {
                "case_id": "in-mem-case",
                "catalog_fixture": "empanada_pollo",
                "catalog_scope": "in_memory",
                "reason": "in_memory case keeps its embedded catalog",
                "expected_producto_presentacion_id": 1,
                "expected_quantity": 1,
                "id_comercio": 1,
                "input_text": "empanada de pollo",
                "expected_decision": "unique",
                "allowed_candidate_ids": [1],
                "restricted_candidate_ids": [],
                "match_expectation": "canonical",
                "presentation_resolution_expectation": "resolved",
                "category": "canonical",
            }
        ],
        "catalogs": {
            "empanada_pollo": {
                "scope": "in_memory",
                "entries": [
                    {
                        "producto_presentacion_id": 1,
                        "producto_id": 1,
                        "presentacion_id": 1,
                        "categoria_id": 1,
                        "producto_nombre": "Empanada de Pollo",
                        "categoria_nombre": "Empanadas",
                        "presentacion_codigo": "UNIDAD",
                        "presentacion_descripcion": "Unidad",
                        "activo": True,
                        "producto_activo": True,
                        "presentacion_activo": True,
                        "disponible": True,
                    }
                ],
            }
        },
        "commerce_catalog_fingerprint": {"1": expected_fingerprint},
    }
    runner = _build_runner(session, target_id=1)
    policy = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 3)
    runner.run(dataset, policies=[policy])
    recognizer = runner._recognizer  # type: ignore[attr-defined]
    first_case_catalog = recognizer.calls[0][1]
    assert first_case_catalog == (1,)
    assert runner.commerce_catalog_cache_size() == 0


def test_runner_does_not_change_catalog_when_allowed_candidate_ids_change():
    rows = [_catalog_row(1, 1), _catalog_row(2, 1), _catalog_row(3, 1)]
    session = _FakeComercioSession(rows)
    expected_fingerprint = _compute_expected_fingerprint(rows)

    dataset = _v3_dynamic_dataset(commerce_catalog_fingerprint={"1": expected_fingerprint})
    dataset["cases"][0]["allowed_candidate_ids"] = [1]
    dataset["cases"][1]["allowed_candidate_ids"] = [2, 3]
    runner = _build_runner(session, target_id=1)
    policy = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 3)
    runner.run(dataset, policies=[policy])
    recognizer = runner._recognizer  # type: ignore[attr-defined]
    assert recognizer.calls[0][1] == recognizer.calls[1][1] == (1, 2, 3)


def test_runner_does_not_change_catalog_when_expected_id_changes():
    rows = [_catalog_row(1, 1), _catalog_row(2, 1)]
    session = _FakeComercioSession(rows)
    expected_fingerprint = _compute_expected_fingerprint(rows)

    dataset = _v3_dynamic_dataset(commerce_catalog_fingerprint={"1": expected_fingerprint})
    dataset["cases"][0]["expected_producto_presentacion_id"] = 1
    dataset["cases"][1]["expected_producto_presentacion_id"] = 2
    runner = _build_runner(session, target_id=1)
    policy = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 3)
    runner.run(dataset, policies=[policy])
    recognizer = runner._recognizer  # type: ignore[attr-defined]
    assert recognizer.calls[0][1] == recognizer.calls[1][1] == (1, 2)


def test_runner_keeps_restricted_candidate_in_catalog():
    rows = [_catalog_row(1, 1), _catalog_row(2, 1), _catalog_row(3, 1)]
    session = _FakeComercioSession(rows)
    expected_fingerprint = _compute_expected_fingerprint(rows)

    dataset = _v3_dynamic_dataset(commerce_catalog_fingerprint={"1": expected_fingerprint})
    dataset["cases"][0]["restricted_candidate_ids"] = [3]
    dataset["cases"][0]["allowed_candidate_ids"] = [1, 2]
    dataset["cases"][1]["restricted_candidate_ids"] = [3]
    dataset["cases"][1]["allowed_candidate_ids"] = [1, 2]
    runner = _build_runner(session, target_id=1)
    policy = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 3)
    runner.run(dataset, policies=[policy])
    recognizer = runner._recognizer  # type: ignore[attr-defined]
    first_case_catalog = recognizer.calls[0][1]
    assert first_case_catalog == (1, 2, 3)


def test_runner_fails_closed_on_stale_commerce_catalog_fingerprint():
    rows = [_catalog_row(1, 1), _catalog_row(2, 1)]
    session = _FakeComercioSession(rows)
    dataset = _v3_dynamic_dataset(commerce_catalog_fingerprint={"1": "stale-fingerprint"})
    runner = _build_runner(session, target_id=1)
    policy = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 3)
    with pytest.raises(StaleCommerceCatalogError) as exc:
        runner.run(dataset, policies=[policy])
    assert exc.value.id_comercio == 1
    assert exc.value.expected_fingerprint == "stale-fingerprint"
    assert isinstance(exc.value.actual_fingerprint, str) and len(exc.value.actual_fingerprint) == 64


def test_runner_fails_closed_on_missing_commerce_catalog_fingerprint():
    rows = [_catalog_row(1, 1), _catalog_row(2, 1)]
    session = _FakeComercioSession(rows)
    dataset = _v3_dynamic_dataset()
    runner = _build_runner(session, target_id=1)
    policy = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 3)
    with pytest.raises(StaleCommerceCatalogError) as exc:
        runner.run(dataset, policies=[policy])
    assert exc.value.id_comercio == 1
    assert exc.value.expected_fingerprint is None
    assert isinstance(exc.value.actual_fingerprint, str)


def test_runner_preserves_inactive_and_unavailable_entries_with_flags():
    rows = [
        _catalog_row(1, 1, activo=False, producto_activo=True, presentacion_activo=True, disponible=True),
        _catalog_row(2, 1, activo=True, producto_activo=False, presentacion_activo=True, disponible=True),
        _catalog_row(3, 1, activo=True, producto_activo=True, presentacion_activo=False, disponible=True),
        _catalog_row(4, 1, activo=True, producto_activo=True, presentacion_activo=True, disponible=False),
        _catalog_row(5, 1, activo=True, producto_activo=True, presentacion_activo=True, disponible=True),
    ]
    session = _FakeComercioSession(rows)
    expected_fingerprint = _compute_expected_fingerprint(rows)

    dataset = _v3_dynamic_dataset(commerce_catalog_fingerprint={"1": expected_fingerprint})
    dataset["cases"][0]["allowed_candidate_ids"] = [1, 2, 3, 4, 5]
    dataset["cases"][1]["allowed_candidate_ids"] = [1, 2, 3, 4, 5]
    runner = _build_runner(session, target_id=1)
    policy = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 3)
    runner.run(dataset, policies=[policy])
    recognizer = runner._recognizer  # type: ignore[attr-defined]
    first_case_catalog = recognizer.calls[0][1]
    assert first_case_catalog == (1, 2, 3, 4, 5)


def test_runner_cache_is_loaded_lazily_per_commerce():
    rows_one = [_catalog_row(1, 1), _catalog_row(2, 1)]
    session_one = _FakeComercioSession(rows_one)
    fp_one = _compute_expected_fingerprint(rows_one)
    runner = _build_runner(session_one, target_id=1)
    dataset = _v3_dynamic_dataset(commerce_catalog_fingerprint={"1": fp_one})
    policy = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 3)
    runner.run(dataset, policies=[policy])
    assert runner.commerce_catalog_cache_size() == 1
    cached = runner._commerce_catalog_cache[1]
    second = runner._resolve_commerce_catalog(dataset, 1)
    assert second is cached
    # The runner's first SQL call is _build_id_commerce_index; the
    # second is the catalog loader. The second ``_resolve_commerce_catalog``
    # call above MUST hit the cache and not increment the counter.
    assert session_one.calls == 2


def test_runner_emits_commerce_catalog_cache_size_in_report():
    rows = [_catalog_row(1, 1), _catalog_row(2, 1)]
    session = _FakeComercioSession(rows)
    expected_fingerprint = _compute_expected_fingerprint(rows)

    dataset = _v3_dynamic_dataset(commerce_catalog_fingerprint={"1": expected_fingerprint})
    runner = _build_runner(session, target_id=1)
    policy = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 3)
    report = runner.run(dataset, policies=[policy])
    assert report["commerce_catalog_cache_size"] == 1


def test_runner_fails_closed_on_stale_fingerprint_with_deterministic_message():
    rows = [_catalog_row(1, 1), _catalog_row(2, 1)]
    session = _FakeComercioSession(rows)
    dataset = _v3_dynamic_dataset(commerce_catalog_fingerprint={"1": "deadbeef"})
    runner = _build_runner(session, target_id=1)
    policy = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 3)
    with pytest.raises(StaleCommerceCatalogError) as exc:
        runner.run(dataset, policies=[policy])
    assert "id_comercio=1" in str(exc.value)
    assert "expected_fingerprint=deadbeef" in str(exc.value)
    assert "actual_fingerprint=" in str(exc.value)


def test_runner_validates_dataset_before_invoking_loader():
    from backend.services.product_recognition_calibration_policy import (
        CalibrationDatasetError,
    )

    rows = [_catalog_row(1, 1)]
    session = _FakeComercioSession(rows)
    runner = _build_runner(session, target_id=1)
    policy = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 3)
    with pytest.raises(CalibrationDatasetError):
        runner.run({"schema_version": 99, "cases": [], "catalogs": {}}, policies=[policy])
    assert session.calls == 0


def test_runner_competing_product_is_present_in_catalog():
    """The catalog handed to the recognizer contains the competing product
    outside ``allowed_candidate_ids``. The recognizer MAY return it as
    a candidate; the boundary check is applied in the evaluator
    afterwards."""
    rows = [
        _catalog_row(1, 1, producto_nombre="Pizza Muzzarella"),
        _catalog_row(9, 1, producto_nombre="Pizza Muzzarella"),
        _catalog_row(39, 1, producto_nombre="Pizza Muzzarella Chica"),
        _catalog_row(40, 1, producto_nombre="Pizza Muzzarella Especial"),
    ]
    session = _FakeComercioSession(rows)
    expected_fingerprint = _compute_expected_fingerprint(rows)
    dataset = _v3_dynamic_dataset(commerce_catalog_fingerprint={"1": expected_fingerprint})
    dataset["cases"][0]["allowed_candidate_ids"] = [1, 9, 39]
    dataset["cases"][0]["restricted_candidate_ids"] = []
    dataset["cases"][0]["expected_producto_presentacion_id"] = 1
    dataset["cases"][1]["allowed_candidate_ids"] = [1, 9, 39]
    dataset["cases"][1]["restricted_candidate_ids"] = []
    dataset["cases"][1]["expected_producto_presentacion_id"] = 9
    runner = _build_runner(session, target_id=1)
    policy = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 3)
    runner.run(dataset, policies=[policy])
    recognizer = runner._recognizer  # type: ignore[attr-defined]
    first_case_catalog = recognizer.calls[0][1]
    assert 40 in first_case_catalog


def test_validate_dataset_accepts_optional_commerce_catalog_inventory():
    payload = {
        "schema_version": 3,
        "cases": [
            {
                "case_id": "c1",
                "id_comercio": 1,
                "input_text": "x",
                "expected_decision": "unknown",
                "allowed_candidate_ids": [],
                "restricted_candidate_ids": [],
                "match_expectation": "neither",
                "presentation_resolution_expectation": "unknown",
                "category": "baseline",
                "catalog_fixture": "f",
            }
        ],
        "catalogs": {"f": {"entries": []}},
        "commerce_catalog_inventory": {
            "1": [
                {
                    "producto_presentacion_id": 1,
                    "producto_id": 1,
                    "presentacion_id": 1,
                    "categoria_id": 1,
                    "producto_nombre": "X",
                    "categoria_nombre": "X",
                    "presentacion_codigo": "X",
                    "presentacion_descripcion": "",
                    "activo": True,
                    "producto_activo": True,
                    "presentacion_activo": True,
                    "disponible": True,
                }
            ]
        },
        "commerce_catalog_fingerprint": {"1": "abc"},
    }
    assert validate_dataset(payload) is payload


def test_validate_dataset_accepts_legacy_dataset_without_commerce_catalog_blocks():
    payload = {
        "schema_version": 3,
        "cases": [
            {
                "case_id": "c1",
                "id_comercio": 1,
                "input_text": "x",
                "expected_decision": "unknown",
                "allowed_candidate_ids": [],
                "restricted_candidate_ids": [],
                "match_expectation": "neither",
                "presentation_resolution_expectation": "unknown",
                "category": "baseline",
                "catalog_fixture": "f",
            }
        ],
        "catalogs": {"f": {"entries": []}},
    }
    assert validate_dataset(payload) is payload


def test_validate_dataset_rejects_malformed_commerce_catalog_inventory():
    payload = {
        "schema_version": 3,
        "cases": [],
        "catalogs": {},
        "commerce_catalog_inventory": {"1": "not-a-list"},
    }
    from backend.services.product_recognition_calibration_policy import (
        CalibrationDatasetError,
    )
    with pytest.raises(CalibrationDatasetError):
        validate_dataset(payload)
