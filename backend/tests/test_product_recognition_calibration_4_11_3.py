"""Focused tests for Subphase 4.11.3 (calibration evaluation mismatch).

Covers:

- The closed mismatch-category taxonomy and the documented evaluation order
  of ``classify_mismatch``.
- The ``normalize_canonical_id`` helper refuses non-canonical identifier
  representations.
- The diagnostic CLI writes its evidence file atomically and the JSON
  payload is byte-identical across deterministic re-runs.
- The runner refuses to start when the dataset's ``seed_refs`` has changed
  since ``inventory_fingerprint`` was committed.
- The dataset validator accepts the optional ``correction_evidence`` object
  without rejecting uncorrected cases.
- Each documented mismatch category has a synthetic classifier test so the
  closed set is verified.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.cli.calibrate_product_recognizer import build_parser
from backend.services.product_presentation_vector_match import (
    ProductPresentationVectorMatch,
)
from backend.services.product_recognition_calibration_diagnosis import (
    MISMATCH_CATEGORIES,
    MISMATCH_CATEGORY,
    classify_mismatch,
    normalize_canonical_id,
    write_diagnostic_atomic,
)
from backend.services.product_recognition_calibration_policy import (
    HybridDecisionPolicy,
    validate_dataset,
)
from backend.services.product_recognition_calibration_report import (
    write_diagnostic_atomic as report_write_diagnostic_atomic,
)
from backend.services.product_recognition_calibration_runner import (
    ProductRecognitionCalibrationRunner,
    SeedReferenceError,
    _seed_refs_fingerprint,
)


def _fake_recognizer_factory():
    class _Recognizer:
        def recognize(self, text, catalog):
            return {
                "encontrados": [],
                "encontrados_posibles": [],
                "encontrados_no_disponibles": [],
                "no_encontrados": [],
            }

    return _Recognizer()


def _fake_embedding_factory():
    class _Embedding:
        def embed_query(self, text):
            return [0.0] * 4

    return _Embedding()


def _fake_vector_factory(target_id: int = 1):
    class _Vector:
        def search_similar(self, *, id_comercio, query_embedding, top_k, candidate_producto_presentacion_ids=None):
            return [ProductPresentationVectorMatch(target_id, 0.9, "canonical")]

    return _Vector()


def _build_runner(target_id: int = 1) -> ProductRecognitionCalibrationRunner:
    from backend.recognizers.product_recognizer_contract import (
        ProductRecognizerProtocol,
        ProductRecognizerResult,
    )

    class _ProtocolRecognizer(ProductRecognizerProtocol):
        def recognize(self, text, catalog) -> ProductRecognizerResult:
            return {
                "encontrados": [],
                "encontrados_posibles": [],
                "encontrados_no_disponibles": [],
                "no_encontrados": [],
            }

    return ProductRecognitionCalibrationRunner(
        recognizer=_ProtocolRecognizer(),
        embedding_client=_fake_embedding_factory(),
        vector_search_factory=lambda: _fake_vector_factory(target_id),
    )


def _v3_dataset(extra: dict | None = None) -> dict:
    dataset: dict = {
        "schema_version": 3,
        "catalogs": {"fixture": {"entries": []}},
        "cases": [
            {
                "case_id": "c1",
                "id_comercio": 1,
                "input_text": "x",
                "expected_decision": "unique",
                "expected_producto_presentacion_id": 1,
                "allowed_candidate_ids": [1],
                "restricted_candidate_ids": [],
                "match_expectation": "canonical",
                "presentation_resolution_expectation": "resolved",
                "category": "canonical",
                "catalog_fixture": "fixture",
            }
        ],
    }
    if extra:
        dataset = {**dataset, **extra}
    return dataset


def test_mismatch_category_enum_is_closed_set():
    assert set(MISMATCH_CATEGORIES) == {
        "invalid_dataset_expectation",
        "stale_seed_reference",
        "commerce_scope_mismatch",
        "product_id_mismatch",
        "presentation_id_mismatch",
        "output_normalization_mismatch",
        "decision_mapping_mismatch",
        "real_fuzzy_recognizer_failure",
        "real_hybrid_recognizer_failure",
        "other_with_evidence",
    }
    assert all(isinstance(value, str) for value in MISMATCH_CATEGORIES)
    assert MISMATCH_CATEGORIES == tuple(c.value for c in MISMATCH_CATEGORY)


def test_normalize_canonical_id_returns_numeric_id():
    assert normalize_canonical_id(5) == 5
    assert normalize_canonical_id({"producto_presentacion_id": 9}) == 9
    assert normalize_canonical_id([{"producto_presentacion_id": 11}]) == 11
    assert normalize_canonical_id({"id_producto_presentacion": 17}) == 17


@pytest.mark.parametrize(
    "value",
    [
        None,
        "UNIDAD",
        {"presentacion_codigo": "UNIDAD"},
        {"presentacion_id": 1},
        {"presentacion_descripcion": "Unidad"},
        3.14,
    ],
)
def test_normalize_canonical_id_rejects_non_canonical_inputs(value):
    with pytest.raises(ValueError):
        normalize_canonical_id(value)


def _classify(**overrides) -> MISMATCH_CATEGORY:
    record = {
        "expected_decision": "unique",
        "expected_producto_presentacion_id": 5,
        "actual_fuzzy_decision": "unique",
        "actual_fuzzy_producto_presentacion_id": 5,
        "actual_hybrid_decision": "unique",
        "actual_hybrid_producto_presentacion_id": 5,
        "id_comercio": 1,
        "actual_id_comercio": 1,
        "fuzzy_correct": False,
        "hybrid_correct": False,
    }
    record.update(overrides)
    return classify_mismatch(record)


def test_classify_mismatch_commerce_scope_takes_precedence():
    category = _classify(actual_id_comercio=2, actual_fuzzy_decision="unique", actual_fuzzy_producto_presentacion_id=5, actual_hybrid_decision="unique", actual_hybrid_producto_presentacion_id=5)
    assert category is MISMATCH_CATEGORY.COMMERCE_SCOPE_MISMATCH


def test_classify_mismatch_product_id_mismatch():
    category = _classify(
        expected_producto_id=10,
        actual_fuzzy_producto_id=11,
        expected_presentacion_id=20,
        actual_fuzzy_presentacion_id=20,
    )
    assert category is MISMATCH_CATEGORY.PRODUCT_ID_MISMATCH


def test_classify_mismatch_presentation_id_mismatch():
    category = _classify(
        expected_producto_id=10,
        actual_fuzzy_producto_id=10,
        expected_presentacion_id=20,
        actual_fuzzy_presentacion_id=21,
    )
    assert category is MISMATCH_CATEGORY.PRESENTATION_ID_MISMATCH


def test_classify_mismatch_output_normalization_mismatch():
    category = _classify(
        expected_producto_id=10,
        actual_fuzzy_producto_id=10,
        expected_presentacion_id=20,
        actual_fuzzy_presentacion_id=20,
        normalization_mismatch=True,
    )
    assert category is MISMATCH_CATEGORY.OUTPUT_NORMALIZATION_MISMATCH


def test_classify_mismatch_decision_mapping_mismatch():
    category = _classify(
        expected_producto_id=10,
        actual_fuzzy_producto_id=10,
        expected_presentacion_id=20,
        actual_fuzzy_presentacion_id=20,
        decision_mapping_mismatch=True,
    )
    assert category is MISMATCH_CATEGORY.DECISION_MAPPING_MISMATCH


def test_classify_mismatch_invalid_dataset_expectation():
    category = _classify(
        expected_producto_id=10,
        actual_fuzzy_producto_id=10,
        expected_presentacion_id=20,
        actual_fuzzy_presentacion_id=20,
        dataset_expectation_mismatch=True,
    )
    assert category is MISMATCH_CATEGORY.INVALID_DATASET_EXPECTATION


def test_classify_mismatch_stale_seed_reference():
    category = _classify(
        expected_producto_id=10,
        actual_fuzzy_producto_id=10,
        expected_presentacion_id=20,
        actual_fuzzy_presentacion_id=20,
        seed_reference_mismatch=True,
    )
    assert category is MISMATCH_CATEGORY.STALE_SEED_REFERENCE


def test_classify_mismatch_real_fuzzy_failure():
    category = _classify(actual_fuzzy_producto_presentacion_id=99)
    assert category is MISMATCH_CATEGORY.REAL_FUZZY_RECOGNIZER_FAILURE


def test_classify_mismatch_real_hybrid_failure():
    category = _classify(
        actual_fuzzy_producto_presentacion_id=5,
        actual_hybrid_producto_presentacion_id=7,
    )
    assert category is MISMATCH_CATEGORY.REAL_HYBRID_RECOGNIZER_FAILURE


def test_classify_mismatch_other_with_evidence_when_undocumented():
    category = _classify(
        actual_fuzzy_decision="unique",
        actual_hybrid_decision="unique",
        actual_fuzzy_producto_presentacion_id=5,
        actual_hybrid_producto_presentacion_id=5,
    )
    assert category is MISMATCH_CATEGORY.OTHER_WITH_EVIDENCE


def test_classify_mismatch_evaluation_order_matches_documented_taxonomy():
    order = (
        MISMATCH_CATEGORY.COMMERCE_SCOPE_MISMATCH,
        MISMATCH_CATEGORY.PRODUCT_ID_MISMATCH,
        MISMATCH_CATEGORY.PRESENTATION_ID_MISMATCH,
        MISMATCH_CATEGORY.OUTPUT_NORMALIZATION_MISMATCH,
        MISMATCH_CATEGORY.DECISION_MAPPING_MISMATCH,
        MISMATCH_CATEGORY.INVALID_DATASET_EXPECTATION,
        MISMATCH_CATEGORY.STALE_SEED_REFERENCE,
        MISMATCH_CATEGORY.REAL_FUZZY_RECOGNIZER_FAILURE,
        MISMATCH_CATEGORY.REAL_HYBRID_RECOGNIZER_FAILURE,
        MISMATCH_CATEGORY.OTHER_WITH_EVIDENCE,
    )
    assert tuple(c.value for c in order) == MISMATCH_CATEGORIES


def test_diagnostic_atomic_writer_creates_file(tmp_path: Path):
    records = [{"case_id": "a", "mismatch_category": "correct", "evidence": ""}]
    output = tmp_path / "diagnose.json"
    write_diagnostic_atomic(records, output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == {"cases": records}


def test_diagnostic_writer_is_byte_identical(tmp_path: Path):
    records = [
        {"case_id": "a", "mismatch_category": "real_fuzzy_recognizer_failure", "evidence": ""},
        {"case_id": "b", "mismatch_category": "correct", "evidence": ""},
    ]
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    write_diagnostic_atomic(records, first)
    write_diagnostic_atomic(records, second)
    assert first.read_bytes() == second.read_bytes()


def test_diagnostic_writer_strips_forbidden_fields(tmp_path: Path):
    from backend.services.product_recognition_calibration_report import (
        write_diagnostic_atomic as report_helper,
    )
    output = tmp_path / "diagnostic.json"
    report_helper(
        [{"case_id": "a", "input_text": "secret", "mismatch_category": "correct", "evidence": ""}],
        output,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "input_text" not in payload["cases"][0]
    assert payload["cases"][0]["case_id"] == "a"


def test_report_diagnostic_writer_is_byte_identical(tmp_path: Path):
    records = [
        {"case_id": "a", "mismatch_category": "real_fuzzy_recognizer_failure", "evidence": ""},
    ]
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    report_write_diagnostic_atomic(records, first)
    report_write_diagnostic_atomic(records, second)
    assert first.read_bytes() == second.read_bytes()


def test_cli_parser_accepts_diagnose_flags():
    parser = build_parser()
    args = parser.parse_args([
        "--dataset", "ds.json",
        "--output", "out.json",
        "--diagnose",
        "--diagnose-output", "custom.json",
    ])
    assert args.diagnose is True
    assert args.diagnose_output == "custom.json"


def test_cli_parser_omits_diagnose_by_default():
    parser = build_parser()
    args = parser.parse_args(["--dataset", "ds.json", "--output", "out.json"])
    assert args.diagnose is False
    assert args.diagnose_output is None


def test_runner_refuses_stale_inventory_fingerprint():
    dataset = _v3_dataset({"seed_refs": {"ref-a": 1, "ref-b": 2}})
    dataset["inventory_fingerprint"] = "stale"
    runner = _build_runner()
    with pytest.raises(SeedReferenceError):
        runner.run(dataset, policies=[HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 3)])


def test_runner_runs_when_inventory_fingerprint_matches():
    dataset = _v3_dataset({"seed_refs": {"ref-a": 1, "ref-b": 2}})
    dataset["inventory_fingerprint"] = _seed_refs_fingerprint(dataset["seed_refs"])
    runner = _build_runner()
    report = runner.run(dataset, policies=[HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 3)])
    assert report["case_count"] == 1
    assert "mismatch_category_counts" in report


def test_runner_resolves_expected_id_from_seed_refs():
    dataset = _v3_dataset()
    dataset["seed_refs"] = {"ref-c1": 1}
    dataset["cases"][0].pop("expected_producto_presentacion_id", None)
    dataset["cases"][0]["expected_producto_presentacion_id_ref"] = "ref-c1"
    dataset["inventory_fingerprint"] = _seed_refs_fingerprint(dataset["seed_refs"])
    runner = _build_runner()
    report = runner.run(dataset, policies=[HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 3)])
    assert report["case_results"][0]["expected_producto_presentacion_id"] == 1


def test_validate_dataset_accepts_correction_evidence_object():
    case = {
        "case_id": "c1",
        "id_comercio": 1,
        "input_text": "x",
        "expected_decision": "unique",
        "expected_producto_presentacion_id": 1,
        "allowed_candidate_ids": [1],
        "restricted_candidate_ids": [],
        "match_expectation": "canonical",
        "presentation_resolution_expectation": "resolved",
        "category": "canonical",
        "catalog_fixture": "fixture",
        "correction_evidence": {
            "mismatch_category": "product_id_mismatch",
            "reason": "wrong expectation",
            "catalog_reference": "pp_xxx",
        },
    }
    dataset = {"schema_version": 3, "catalogs": {"fixture": {"entries": []}}, "cases": [case]}
    assert validate_dataset(dataset) is dataset


def test_validate_dataset_rejects_correction_evidence_missing_fields():
    case = {
        "case_id": "c1",
        "id_comercio": 1,
        "input_text": "x",
        "expected_decision": "unique",
        "expected_producto_presentacion_id": 1,
        "allowed_candidate_ids": [1],
        "restricted_candidate_ids": [],
        "match_expectation": "canonical",
        "presentation_resolution_expectation": "resolved",
        "category": "canonical",
        "catalog_fixture": "fixture",
        "correction_evidence": {"mismatch_category": "x"},
    }
    dataset = {"schema_version": 3, "catalogs": {"fixture": {"entries": []}}, "cases": [case]}
    from backend.services.product_recognition_calibration_policy import (
        CalibrationDatasetError,
    )
    with pytest.raises(CalibrationDatasetError):
        validate_dataset(dataset)


def test_runner_emits_correct_category_when_evaluator_matches():
    dataset = _v3_dataset()
    dataset["cases"][0]["expected_decision"] = "unknown"
    runner = _build_runner()
    report = runner.run(dataset, policies=[HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 3)])
    assert report["case_results"][0]["mismatch_category"] == "correct"
    assert report["mismatch_category_counts"]["total"] == 0


def test_runner_emits_per_case_diagnostic_records():
    dataset = _v3_dataset()
    dataset["cases"][0]["expected_decision"] = "unknown"
    runner = _build_runner()
    report = runner.run(dataset, policies=[HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 3)])
    record = report["case_results"][0]
    for key in (
        "case_id",
        "expected_decision",
        "expected_producto_presentacion_id",
        "actual_fuzzy_decision",
        "actual_fuzzy_producto_presentacion_id",
        "actual_fuzzy_candidate_ids",
        "actual_hybrid_decision",
        "actual_hybrid_producto_presentacion_id",
        "actual_hybrid_candidate_ids",
        "normalized_id_used_by_evaluator",
        "presentation_resolution_result",
        "mismatch_category",
    ):
        assert key in record
