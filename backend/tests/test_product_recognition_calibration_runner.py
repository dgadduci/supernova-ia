import json
from pathlib import Path

import pytest

from backend.services.product_presentation_vector_match import (
    ProductPresentationVectorMatch,
)
from backend.services.product_recognition_calibration_policy import HybridDecisionPolicy
from backend.services.product_recognition_calibration_runner import (
    ProductRecognitionCalibrationRunner,
)

DATASET_PATH = Path(__file__).parent.parent / "data" / "product_recognition_calibration_cases.json"


class FakeRecognizer:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def recognize(self, text, catalog):
        self.calls.append(text)
        return self.results[text]


class FakeEmbedding:
    def __init__(self, failures=()):
        self.calls = []
        self.failures = set(failures)

    def embed_query(self, text):
        self.calls.append(text)
        if text in self.failures:
            raise RuntimeError("secret embedding failure")
        return [text]


class FakeVector:
    def __init__(self, matches_by_text, failures=()):
        self.matches_by_text = matches_by_text
        self.failures = set(failures)
        self.calls = []

    def search_similar(self, *, id_comercio, query_embedding, top_k, candidate_producto_presentacion_ids=None):
        self.calls.append((id_comercio, top_k, tuple(candidate_producto_presentacion_ids or ())))
        text = str(query_embedding[0])
        if text in self.failures:
            raise RuntimeError("secret vector failure")
        return self.matches_by_text.get(text, [])


def dataset():
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def minimal_case(case_id, text, expected, allowed, category="baseline"):
    return {
        "case_id": case_id,
        "id_comercio": 7,
        "input_text": text,
        "expected_decision": expected,
        "expected_producto_presentacion_id": expected == "unique" and allowed[0] or None,
        "allowed_candidate_ids": allowed,
        "restricted_candidate_ids": [],
        "match_expectation": "neither",
        "presentation_resolution_expectation": "resolved" if expected == "unique" else expected,
        "category": category,
        "catalog_fixture": "fixture",
    }


def fixture_dataset(cases):
    return {"schema_version": 1, "catalogs": {"fixture": {"entries": []}}, "cases": cases}


def test_runner_calls_each_infrastructure_once_and_preserves_boundaries():
    cases = [minimal_case("one", "one", "unique", [1]), minimal_case("two", "two", "unknown", [2], "restricted")]
    recognizer = FakeRecognizer({"one": {"encontrados": [{"producto_presentacion_id": 1}], "encontrados_posibles": []}, "two": {"encontrados": [], "encontrados_posibles": []}})
    embedding = FakeEmbedding()
    vector = FakeVector({})
    vector.matches_by_text = {"one": [ProductPresentationVectorMatch(1, 0.99, "canonical")], "two": []}
    runner = ProductRecognitionCalibrationRunner(recognizer=recognizer, embedding_client=embedding, vector_search_factory=lambda: vector)
    report = runner.run(fixture_dataset(cases), policies=[HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 3)])
    assert recognizer.calls == ["one", "two"]
    assert embedding.calls == ["one", "two"]
    assert len(vector.calls) == 2
    assert all(call[0] == 7 for call in vector.calls)
    assert report["case_count"] == 2
    assert report["failed_case_ids"] == []


def test_runner_continues_after_vector_failure_and_reports_sanitized_id():
    cases = [minimal_case("failed", "failed", "unknown", [1]), minimal_case("ok", "ok", "unique", [2])]
    recognizer = FakeRecognizer({"failed": {"encontrados": [], "encontrados_posibles": []}, "ok": {"encontrados": [{"producto_presentacion_id": 2}], "encontrados_posibles": []}})
    embedding = FakeEmbedding()
    vector = FakeVector({"failed": []}, failures={"failed"})
    vector.matches_by_text = {"ok": [ProductPresentationVectorMatch(2, 0.99, "canonical")]}
    runner = ProductRecognitionCalibrationRunner(recognizer=recognizer, embedding_client=embedding, vector_search_factory=lambda: vector)
    report = runner.run(fixture_dataset(cases), policies=[HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 3)])
    assert report["failed_case_ids"] == ["failed"]
    assert report["infrastructure_failures"] == 1
    assert "secret" not in json.dumps(report)


def test_runner_detects_total_hybrid_failure():
    case = minimal_case("only", "only", "unknown", [1])
    recognizer = FakeRecognizer({"only": {"encontrados": [], "encontrados_posibles": []}})
    runner = ProductRecognitionCalibrationRunner(
        recognizer=recognizer,
        embedding_client=FakeEmbedding(failures={"only"}),
        vector_search_factory=lambda: FakeVector({}),
    )
    with pytest.raises(RuntimeError, match="no evaluable hybrid cases"):
        runner.run(fixture_dataset([case]), policies=[HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 3)])


def test_dynamic_baseline_case_is_present_in_calibration_dataset():
    loaded = dataset()
    case_ids = {case["case_id"] for case in loaded["cases"]}
    assert "multi-word-jamon-queso-dynamic" in case_ids
    dynamic = next(case for case in loaded["cases"] if case["case_id"] == "multi-word-jamon-queso-dynamic")
    assert dynamic["expected_producto_presentacion_id_ref"] == "pp_empanada_jamon_queso"
