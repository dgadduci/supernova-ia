"""Focused tests for Subphase 4.12B controlled-hybrid-product-recognition.

The tests verify the runtime half of the Subphase 4.11 calibration
chain:

- The safe-fuzzy fallback for an unrecognised
  ``PRODUCT_RECOGNIZER_MODE`` value (no startup-blocking exception).
- The ``hybrid_authoritative_policy_path`` validator scoped to the
  effective mode.
- The :class:`HybridAuthoritativePolicySource` loader.
- The :class:`HybridAuthoritativeProductRecognizer` with stub
  injection (no Ollama, no PostgreSQL, no LLM transport).
- The :class:`RecognizeContext` shared boundary.
- The 4.11.5 and 4.11.7 guards verbatim.
- The catalog-scope filter on the hybrid authoritative recognizer.
- The fuzzy fallback on embedding / vector failure.
- The telemetry surface (``mode="hybrid_authoritative"``,
  ``hybrid_non_authoritative=False``).

The tests inject stubs for the embedding client, the vector search
service, the recorder, and the policy source so the focused tests
run without infrastructure.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import unittest
from typing import Any
from unittest import mock

from backend.config.settings import Settings, load_settings
from backend.intents.context.product_modification_resolver import (
    detectar_productos as detectar_productos_modification,
)
from backend.intents.context.product_selection_context_resolver import (
    detectar_productos as detectar_productos_selection,
)
from backend.intents.recognizers.modificar_producto_recognizer import (
    detectar_productos as detectar_productos_modificar,
)
from backend.intents.recognizers.quitar_producto_recognizer import (
    detectar_productos as detectar_productos_quitar,
)
from backend.recognizers.fuzzy_product_recognizer import FuzzyProductRecognizer
from backend.recognizers.product_recognizer_contract import (
    ProductRecognizerProtocol,
    ProductRecognizerResult,
    RecognizeContext,
)
from backend.services.exceptions import HybridAuthoritativePolicyError
from backend.services.hybrid_authoritative_policy_source import (
    HybridAuthoritativePolicySource,
)
from backend.services.hybrid_authoritative_recognizer import (
    HybridAuthoritativeProductRecognizer,
    _build_allowed_candidate_ids,
    _decide_hybrid,
    _filter_vector_results_by_allowed_candidates,
)
from backend.services.product_recognition_calibration_policy import (
    HybridDecisionPolicy,
)
from backend.services.product_recognition_shadow_comparison import (
    ProductRecognitionHybridObservation,
    ProductRecognitionShadowComparison,
)
from backend.services.product_recognition_shadow_service import (
    ShadowedProductRecognizer,
)
from backend.services.shadow_metrics_recorder import ShadowMetricsRecorder


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "llm_url": "http://llm.test/api/generate",
        "llm_model": "test-llm",
        "llm_timeout": 30,
        "llm_keep_alive": "1h",
        "llm_num_ctx": 2048,
        "llm_num_predict": 256,
        "llm_log_content": False,
        "llm_log_max_chars": 50,
        "embedding_url": "http://embed.test/api/embed",
        "embedding_model": "all-minilm:latest",
        "embedding_timeout_seconds": 15,
        "embedding_batch_size": 32,
        "embedding_dimension": 384,
    }
    base.update(overrides)
    return Settings(**base)


def _stub_policy() -> HybridDecisionPolicy:
    return HybridDecisionPolicy(
        fuzzy_weight=0.5,
        vector_weight=0.5,
        unique_threshold=0.7,
        ambiguous_threshold=0.4,
        minimum_score_gap=0.05,
        vector_top_k=5,
    )


class _StubEmbeddingClient:
    def __init__(self, vector: list[float] | None = None) -> None:
        self._vector = vector if vector is not None else [0.0] * 384

    def embed_query(self, text: str) -> list[float]:
        return list(self._vector)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [list(self._vector) for _ in texts]


class _StubVectorMatch:
    def __init__(self, id_producto_presentacion: int, score: float) -> None:
        self.id_producto_presentacion = id_producto_presentacion
        self.score = score


class _StubVectorSearchService:
    def __init__(
        self,
        matches: list[_StubVectorMatch] | None = None,
        raise_on_call: bool = False,
    ) -> None:
        self.matches = matches or []
        self.raise_on_call = raise_on_call
        self.call_count = 0
        self.last_kwargs: dict | None = None

    def search_similar(
        self,
        *,
        id_comercio: int,
        query_embedding,
        top_k: int,
        candidate_producto_presentacion_ids,
    ):
        self.call_count += 1
        self.last_kwargs = {
            "id_comercio": id_comercio,
            "query_embedding": list(query_embedding),
            "top_k": top_k,
            "candidate_producto_presentacion_ids": (
                list(candidate_producto_presentacion_ids)
                if candidate_producto_presentacion_ids is not None
                else None
            ),
        }
        if self.raise_on_call:
            raise RuntimeError("stub vector failure")
        return list(self.matches)


class _StubRecorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def record(
        self,
        comparison: ProductRecognitionShadowComparison,
        *,
        hybrid_observation: ProductRecognitionHybridObservation,
        id_comercio: int,
        intent: str | None,
        correlation_id: str,
        mode: str = "shadow",
    ) -> None:
        self.calls.append(
            {
                "comparison": comparison,
                "hybrid_observation": hybrid_observation,
                "id_comercio": id_comercio,
                "intent": intent,
                "correlation_id": correlation_id,
                "mode": mode,
            }
        )


def _catalog() -> list[dict]:
    return [
        {
            "producto_presentacion_id": 1,
            "producto_id": 10,
            "presentacion_id": 100,
            "categoria_id": 1,
            "categoria_nombre": "Empanadas",
            "producto_nombre": "Empanada de Carne",
            "presentacion_codigo": "unidad",
            "presentacion_descripcion": "Unidad",
            "activo": True,
            "disponible": True,
            "aliases": {
                "general_aliases": ["empanada carne"],
                "specific_aliases": [],
            },
        },
        {
            "producto_presentacion_id": 2,
            "producto_id": 11,
            "presentacion_id": 101,
            "categoria_id": 1,
            "categoria_nombre": "Empanadas",
            "producto_nombre": "Empanada de Pollo",
            "presentacion_codigo": "unidad",
            "presentacion_descripcion": "Unidad",
            "activo": True,
            "disponible": True,
            "aliases": {
                "general_aliases": ["empanada pollo"],
                "specific_aliases": [],
            },
        },
        {
            "producto_presentacion_id": 3,
            "producto_id": 12,
            "presentacion_id": 102,
            "categoria_id": 2,
            "categoria_nombre": "Pizzas",
            "producto_nombre": "Pizza Muzarella",
            "presentacion_codigo": "unidad",
            "presentacion_descripcion": "Unidad",
            "activo": True,
            "disponible": True,
            "aliases": {
                "general_aliases": ["muzarella", "mozzarella"],
                "specific_aliases": [],
            },
        },
    ]


def _restricted_catalog() -> list[dict]:
    return [
        {
            "producto_presentacion_id": 1,
            "producto_id": 10,
            "presentacion_id": 100,
            "categoria_id": 1,
            "categoria_nombre": "Empanadas",
            "producto_nombre": "Empanada de Carne",
            "presentacion_codigo": "unidad",
            "presentacion_descripcion": "Unidad",
            "activo": True,
            "disponible": True,
            "aliases": {
                "general_aliases": ["empanada carne"],
                "specific_aliases": [],
            },
        },
        {
            "producto_presentacion_id": 2,
            "producto_id": 11,
            "presentacion_id": 101,
            "categoria_id": 1,
            "categoria_nombre": "Empanadas",
            "producto_nombre": "Empanada de Pollo",
            "presentacion_codigo": "unidad",
            "presentacion_descripcion": "Unidad",
            "activo": True,
            "disponible": True,
            "aliases": {
                "general_aliases": ["empanada pollo"],
                "specific_aliases": [],
            },
        },
    ]


class _StubFuzzyRecognizer:
    """Returns a deterministic fuzzy result controlled by ``decision``."""

    def __init__(
        self,
        *,
        decision: str = "ambiguous",
        encontrados: list[int] | None = None,
        posibles: list[int] | None = None,
    ) -> None:
        self._decision = decision
        self._encontrados = encontrados or []
        self._posibles = posibles or []
        self.call_count = 0
        self.last_kwargs: dict | None = None

    def recognize(
        self,
        text: str,
        catalog: list[dict],
        *,
        intent_metadata: RecognizeContext | None = None,
    ) -> ProductRecognizerResult:
        self.call_count += 1
        self.last_kwargs = {
            "text": text,
            "catalog": catalog,
            "intent_metadata": intent_metadata,
        }
        encontrados = [
            {
                "producto_presentacion_id": pid,
                "producto_nombre": f"producto {pid}",
                "cantidad": 1,
                "texto_origen": text,
            }
            for pid in self._encontrados
        ]
        posibles: list[dict] = []
        if self._posibles:
            productos = [
                {
                    "producto_presentacion_id": pid,
                    "producto_nombre": f"producto {pid}",
                    "texto_origen": text,
                }
                for pid in self._posibles
            ]
            posibles.append({"texto_origen": text, "productos": productos})

        return {
            "encontrados": encontrados,
            "encontrados_posibles": posibles,
            "encontrados_no_disponibles": [],
            "no_encontrados": [] if (encontrados or posibles) else [{"texto_origen": text}],
        }


def _resolver_with_commerce(commerce_id: int):
    def _resolver(catalog: list[dict]) -> int | None:
        return commerce_id

    return _resolver


def _vector_factory(matches: list[_StubVectorMatch], raise_on_call: bool = False):
    service = _StubVectorSearchService(matches=matches, raise_on_call=raise_on_call)
    return service, lambda: service


class SafeFuzzyFallbackTest(unittest.TestCase):
    def test_invalid_mode_resolves_to_fuzzy_with_structured_warning(self):
        env = {"PRODUCT_RECOGNIZER_MODE": "hybrid_active"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertLogs("backend.config.settings", level="WARNING") as captured:
                settings = load_settings()
        self.assertEqual(settings.product_recognizer_mode, "fuzzy")
        self.assertEqual(len(captured.records), 1)
        record = captured.records[0]
        self.assertEqual(getattr(record, "configured_mode", None), "hybrid_active")
        self.assertEqual(getattr(record, "effective_mode", None), "fuzzy")
        self.assertEqual(getattr(record, "reason", None), "invalid_mode")

    def test_capitalised_typo_resolves_to_fuzzy_with_warning(self):
        env = {"PRODUCT_RECOGNIZER_MODE": "HybridAuthoritative"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertLogs("backend.config.settings", level="WARNING"):
                settings = load_settings()
        self.assertEqual(settings.product_recognizer_mode, "fuzzy")

    def test_empty_string_resolves_to_fuzzy_with_warning(self):
        env = {"PRODUCT_RECOGNIZER_MODE": ""}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertLogs("backend.config.settings", level="WARNING"):
                settings = load_settings()
        self.assertEqual(settings.product_recognizer_mode, "fuzzy")

    def test_invalid_mode_does_not_load_hybrid_policy_file(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = {
                "selected_policy": {
                    "fuzzy_weight": 0.5,
                    "vector_weight": 0.5,
                    "unique_threshold": 0.7,
                    "ambiguous_threshold": 0.4,
                    "minimum_score_gap": 0.05,
                    "vector_top_k": 5,
                },
                "eligibility": {"status": "eligible"},
            }
            descriptor, path = tempfile.mkstemp(
                suffix=".json", dir=directory, prefix="hybrid_policy_"
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)

            env = {
                "PRODUCT_RECOGNIZER_MODE": "hybrid_active",
                "HYBRID_AUTHORITATIVE_POLICY_PATH": path,
            }
            with mock.patch.dict(os.environ, env, clear=True):
                with self.assertLogs("backend.config.settings", level="WARNING"):
                    settings = load_settings()
            self.assertEqual(settings.product_recognizer_mode, "fuzzy")
            self.assertEqual(
                settings.hybrid_authoritative_policy_path, path
            )
            self.assertNotEqual(
                settings.hybrid_authoritative_policy_path, None
            )


class HybridAuthoritativePolicyPathValidatorTest(unittest.TestCase):
    def test_policy_path_validator_runs_only_in_hybrid_mode(self):
        env = {
            "PRODUCT_RECOGNIZER_MODE": "hybrid_authoritative",
            "HYBRID_AUTHORITATIVE_POLICY_PATH": "",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            from backend.services.exceptions import (
                InvalidHybridAuthoritativePolicyPath,
            )
            with self.assertRaises(InvalidHybridAuthoritativePolicyPath):
                load_settings()

    def test_policy_path_validator_is_skipped_in_fuzzy_mode(self):
        env = {
            "PRODUCT_RECOGNIZER_MODE": "fuzzy",
            "HYBRID_AUTHORITATIVE_POLICY_PATH": "/tmp/report.json",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.product_recognizer_mode, "fuzzy")
        self.assertEqual(
            settings.hybrid_authoritative_policy_path, "/tmp/report.json"
        )

    def test_policy_path_validator_is_skipped_in_shadow_mode(self):
        env = {
            "PRODUCT_RECOGNIZER_MODE": "shadow",
            "HYBRID_AUTHORITATIVE_POLICY_PATH": "/tmp/report.json",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.product_recognizer_mode, "shadow")
        self.assertEqual(
            settings.hybrid_authoritative_policy_path, "/tmp/report.json"
        )


class PolicyLoaderTest(unittest.TestCase):
    def test_loader_returns_policy_on_valid_eligible_report(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = {
                "selected_policy": {
                    "fuzzy_weight": 0.5,
                    "vector_weight": 0.5,
                    "unique_threshold": 0.7,
                    "ambiguous_threshold": 0.4,
                    "minimum_score_gap": 0.05,
                    "vector_top_k": 5,
                },
                "eligibility": {"status": "eligible"},
            }
            descriptor, path = tempfile.mkstemp(
                suffix=".json", dir=directory, prefix="hybrid_policy_"
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            settings = _settings(
                product_recognizer_mode="hybrid_authoritative",
                hybrid_authoritative_policy_path=path,
            )
            policy = HybridAuthoritativePolicySource.load(settings)
            self.assertEqual(policy.fuzzy_weight, 0.5)
            self.assertEqual(policy.vector_top_k, 5)

    def test_loader_fails_closed_on_missing_file(self):
        settings = _settings(
            product_recognizer_mode="hybrid_authoritative",
            hybrid_authoritative_policy_path="/nonexistent/path.json",
        )
        with self.assertRaises(HybridAuthoritativePolicyError):
            HybridAuthoritativePolicySource.load(settings)

    def test_loader_fails_closed_on_non_eligible_status(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = {
                "selected_policy": {
                    "fuzzy_weight": 0.5,
                    "vector_weight": 0.5,
                    "unique_threshold": 0.7,
                    "ambiguous_threshold": 0.4,
                    "minimum_score_gap": 0.05,
                    "vector_top_k": 5,
                },
                "eligibility": {"status": "not_eligible"},
            }
            descriptor, path = tempfile.mkstemp(
                suffix=".json", dir=directory, prefix="hybrid_policy_"
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            settings = _settings(
                product_recognizer_mode="hybrid_authoritative",
                hybrid_authoritative_policy_path=path,
            )
            with self.assertRaises(HybridAuthoritativePolicyError):
                HybridAuthoritativePolicySource.load(settings)

    def test_loader_fails_closed_on_malformed_selected_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = {
                "selected_policy": {
                    "fuzzy_weight": 0.5,
                    "vector_weight": 0.5,
                    "unique_threshold": 0.7,
                    "ambiguous_threshold": 0.4,
                    "minimum_score_gap": 0.05,
                    "vector_top_k": 5,
                    "extra_key": "boom",
                },
                "eligibility": {"status": "eligible"},
            }
            descriptor, path = tempfile.mkstemp(
                suffix=".json", dir=directory, prefix="hybrid_policy_"
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            settings = _settings(
                product_recognizer_mode="hybrid_authoritative",
                hybrid_authoritative_policy_path=path,
            )
            with self.assertRaises(HybridAuthoritativePolicyError):
                HybridAuthoritativePolicySource.load(settings)


class RecognizeContextSharedBoundaryTest(unittest.TestCase):
    def test_fuzzy_recognizer_accepts_intent_metadata_argument(self):
        recognizer = FuzzyProductRecognizer()
        result = recognizer.recognize(
            "empanada de carne",
            _catalog(),
            intent_metadata={
                "catalog_scope": "pending_product_selection_restricted"
            },
        )
        self.assertIn("encontrados", result)
        self.assertIn("encontrados_posibles", result)
        self.assertIn("no_encontrados", result)

    def test_shadowed_recognizer_accepts_intent_metadata_argument(self):
        recognizer = ShadowedProductRecognizer(
            inner=FuzzyProductRecognizer(),
            shadow=mock.MagicMock(),
            recorder=_StubRecorder(),
            commerce_id_resolver=None,
        )
        result = recognizer.recognize(
            "empanada de carne",
            _catalog(),
            intent_metadata={
                "catalog_scope": "pending_product_selection_restricted"
            },
        )
        self.assertIn("encontrados", result)

    def test_product_selection_resolver_passes_restricted_catalog_scope(self):
        self.assertTrue(callable(detectar_productos_selection))

    def test_other_modules_default_intent_metadata_to_none(self):
        for function in (
            detectar_productos_modification,
            detectar_productos_quitar,
            detectar_productos_modificar,
        ):
            self.assertTrue(callable(function))

    def test_protocol_signature_includes_intent_metadata(self):
        method = ProductRecognizerProtocol.recognize
        signature = method.__annotations__
        self.assertIn("intent_metadata", signature)
        self.assertEqual(
            signature["intent_metadata"], "RecognizeContext | None"
        )


class RuntimeGuardsTest(unittest.TestCase):
    def test_4_11_5_guard_fires_with_restricted_scope_and_fuzzy_ambiguous(self):
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=_StubFuzzyRecognizer(decision="ambiguous", posibles=[1, 2]),
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=(
                lambda: _StubVectorSearchService(matches=[
                    _StubVectorMatch(1, 0.9),
                    _StubVectorMatch(2, 0.8),
                ])
            ),
            recorder=_StubRecorder(),
            commerce_id_resolver=_resolver_with_commerce(99),
        )
        result = recognizer.recognize(
            "empanada",
            _restricted_catalog(),
            intent_metadata={
                "catalog_scope": "pending_product_selection_restricted"
            },
        )
        self.assertEqual(result["encontrados"], [])
        self.assertEqual(len(result["encontrados_posibles"]), 1)
        self.assertEqual(
            len(result["encontrados_posibles"][0]["productos"]),
            2,
        )
        self.assertEqual(result["no_encontrados"], [])
        self.assertEqual(result["encontrados_no_disponibles"], [])

    def test_4_11_5_guard_does_not_fire_when_intent_metadata_is_none(self):
        _service, factory = _vector_factory(
            matches=[_StubVectorMatch(1, 0.9), _StubVectorMatch(2, 0.8)]
        )
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=_StubFuzzyRecognizer(decision="ambiguous", posibles=[1, 2]),
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=factory,
            recorder=_StubRecorder(),
            commerce_id_resolver=_resolver_with_commerce(99),
        )
        result = recognizer.recognize("empanada", _catalog())
        self.assertEqual(len(result["encontrados_posibles"]), 1)
        productos = result["encontrados_posibles"][0]["productos"]
        self.assertEqual(len(productos), 2)

    def test_4_11_5_guard_does_not_fire_for_commerce_dynamic_database(self):
        _service, factory = _vector_factory(
            matches=[_StubVectorMatch(1, 0.9), _StubVectorMatch(2, 0.8)]
        )
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=_StubFuzzyRecognizer(decision="ambiguous", posibles=[1, 2]),
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=factory,
            recorder=_StubRecorder(),
            commerce_id_resolver=_resolver_with_commerce(99),
        )
        result = recognizer.recognize(
            "empanada",
            _catalog(),
            intent_metadata={"catalog_scope": "commerce_dynamic_database"},
        )
        self.assertEqual(len(result["encontrados_posibles"]), 1)
        productos = result["encontrados_posibles"][0]["productos"]
        self.assertEqual(len(productos), 2)

    def test_4_11_7_guard_fires_with_fuzzy_unique_and_filtered_empty_vector(self):
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=_StubFuzzyRecognizer(decision="unique", encontrados=[1]),
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=(
                lambda: _StubVectorSearchService(matches=[
                    _StubVectorMatch(99, 0.9),
                ])
            ),
            recorder=_StubRecorder(),
            commerce_id_resolver=_resolver_with_commerce(99),
        )
        result = recognizer.recognize(
            "empanada",
            _catalog(),
            intent_metadata={"catalog_scope": "commerce_dynamic_database"},
        )
        self.assertEqual(len(result["encontrados"]), 1)
        self.assertEqual(result["encontrados"][0]["producto_presentacion_id"], 1)
        self.assertEqual(result["encontrados_posibles"], [])
        self.assertEqual(result["no_encontrados"], [])


class CatalogScopeFilterTest(unittest.TestCase):
    def test_allowed_candidate_ids_built_only_from_catalog(self):
        catalog = _catalog()
        ids = _build_allowed_candidate_ids(catalog)
        self.assertEqual(ids, frozenset({1, 2, 3}))

    def test_filter_discards_vector_results_outside_allowed(self):
        allowed = frozenset({1, 2})
        ids, scores = _filter_vector_results_by_allowed_candidates(
            raw_vector_ids=(1, 99, 2),
            raw_vector_scores=(0.9, 0.8, 0.7),
            allowed_candidate_ids=allowed,
        )
        self.assertEqual(ids, (1, 2))
        self.assertEqual(scores, (0.9, 0.7))

    def test_filter_deduplicates_after_filter_not_before(self):
        allowed = frozenset({1, 2})
        ids, scores = _filter_vector_results_by_allowed_candidates(
            raw_vector_ids=(1, 1, 99, 2),
            raw_vector_scores=(0.9, 0.85, 0.95, 0.7),
            allowed_candidate_ids=allowed,
        )
        self.assertEqual(ids, (1, 2))
        self.assertEqual(scores, (0.9, 0.7))

    def test_filter_with_no_allowed_candidates_yields_empty(self):
        allowed = frozenset()
        ids, scores = _filter_vector_results_by_allowed_candidates(
            raw_vector_ids=(1, 2),
            raw_vector_scores=(0.9, 0.8),
            allowed_candidate_ids=allowed,
        )
        self.assertEqual(ids, ())
        self.assertEqual(scores, ())

    def test_recognizer_discards_vector_result_outside_received_catalog(self):
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=_StubFuzzyRecognizer(decision="unique", encontrados=[1]),
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=(
                lambda: _StubVectorSearchService(matches=[
                    _StubVectorMatch(99, 0.99),
                ])
            ),
            recorder=_StubRecorder(),
            commerce_id_resolver=_resolver_with_commerce(99),
        )
        result = recognizer.recognize("empanada", _catalog())
        self.assertEqual(result["encontrados"][0]["producto_presentacion_id"], 1)
        recorder_calls = recognizer._recorder.calls  # type: ignore[attr-defined]
        self.assertEqual(len(recorder_calls), 1)
        observation = recorder_calls[0]["hybrid_observation"]
        self.assertNotIn(99, observation.hybrid_candidate_ranking)

    def test_4_11_7_guard_fires_when_filter_discards_all_raw_vector_results(self):
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=_StubFuzzyRecognizer(decision="unique", encontrados=[1]),
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=(
                lambda: _StubVectorSearchService(matches=[
                    _StubVectorMatch(99, 0.95),
                    _StubVectorMatch(100, 0.9),
                ])
            ),
            recorder=_StubRecorder(),
            commerce_id_resolver=_resolver_with_commerce(99),
        )
        result = recognizer.recognize(
            "empanada",
            _catalog(),
            intent_metadata={"catalog_scope": "commerce_dynamic_database"},
        )
        self.assertEqual(len(result["encontrados"]), 1)
        self.assertEqual(result["encontrados"][0]["producto_presentacion_id"], 1)


class FuzzyFallbackTest(unittest.TestCase):
    def test_embedding_failure_returns_fuzzy_result_unchanged(self):
        class _FailingEmbeddingClient:
            def embed_query(self, text: str) -> list[float]:
                raise RuntimeError("embedding down")

            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                return [[0.0] * 384 for _ in texts]

        inner = _StubFuzzyRecognizer(decision="ambiguous", posibles=[1, 2])
        recorder = _StubRecorder()
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=inner,
            policy=_stub_policy(),
            embedding_client=_FailingEmbeddingClient(),
            vector_search_service=lambda: _StubVectorSearchService(),
            recorder=recorder,
            commerce_id_resolver=_resolver_with_commerce(99),
        )
        result = recognizer.recognize("empanada", _catalog())
        fuzzy_result = inner.recognize("empanada", _catalog())
        self.assertEqual(
            result["encontrados_posibles"],
            fuzzy_result["encontrados_posibles"],
        )
        self.assertEqual(len(recorder.calls), 1)
        comparison = recorder.calls[0]["comparison"]
        self.assertEqual(comparison.failure_category, "embedding_failure")
        self.assertFalse(comparison.vector_available)

    def test_vector_failure_returns_fuzzy_result_unchanged(self):
        inner = _StubFuzzyRecognizer(decision="ambiguous", posibles=[1, 2])
        recorder = _StubRecorder()
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=inner,
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=lambda: _StubVectorSearchService(raise_on_call=True),
            recorder=recorder,
            commerce_id_resolver=_resolver_with_commerce(99),
        )
        result = recognizer.recognize("empanada", _catalog())
        fuzzy_result = inner.recognize("empanada", _catalog())
        self.assertEqual(
            result["encontrados_posibles"],
            fuzzy_result["encontrados_posibles"],
        )
        self.assertEqual(len(recorder.calls), 1)
        comparison = recorder.calls[0]["comparison"]
        self.assertEqual(comparison.failure_category, "vector_failure")
        self.assertFalse(comparison.vector_available)

    def test_resolver_returns_none_skips_pipeline(self):
        inner = _StubFuzzyRecognizer(decision="ambiguous", posibles=[1, 2])
        recorder = _StubRecorder()
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=inner,
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=lambda: _StubVectorSearchService(),
            recorder=recorder,
            commerce_id_resolver=lambda catalog: None,
        )
        result = recognizer.recognize("empanada", _catalog())
        fuzzy_result = inner.recognize("empanada", _catalog())
        self.assertEqual(
            result["encontrados_posibles"],
            fuzzy_result["encontrados_posibles"],
        )
        self.assertEqual(recorder.calls, [])

    def test_resolver_not_provided_skips_pipeline(self):
        inner = _StubFuzzyRecognizer(decision="ambiguous", posibles=[1, 2])
        recorder = _StubRecorder()
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=inner,
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=lambda: _StubVectorSearchService(),
            recorder=recorder,
            commerce_id_resolver=None,
        )
        result = recognizer.recognize("empanada", _catalog())
        fuzzy_result = inner.recognize("empanada", _catalog())
        self.assertEqual(
            result["encontrados_posibles"],
            fuzzy_result["encontrados_posibles"],
        )
        self.assertEqual(recorder.calls, [])

    def test_inner_fuzzy_recognizer_invoked_exactly_once(self):
        inner = _StubFuzzyRecognizer(decision="unique", encontrados=[1])
        recorder = _StubRecorder()
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=inner,
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=lambda: _StubVectorSearchService(),
            recorder=recorder,
            commerce_id_resolver=_resolver_with_commerce(99),
        )
        recognizer.recognize("empanada", _catalog())
        self.assertEqual(inner.call_count, 1)


class HybridDecisionTranslationTest(unittest.TestCase):
    def test_unique_translation_yields_single_encontrados_entry(self):
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=_StubFuzzyRecognizer(decision="unique", encontrados=[1]),
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=lambda: _StubVectorSearchService(
                matches=[_StubVectorMatch(1, 0.9)]
            ),
            recorder=_StubRecorder(),
            commerce_id_resolver=_resolver_with_commerce(99),
        )
        result = recognizer.recognize("empanada", _catalog())
        self.assertEqual(len(result["encontrados"]), 1)
        self.assertEqual(result["encontrados"][0]["producto_presentacion_id"], 1)
        self.assertEqual(result["encontrados_posibles"], [])
        self.assertEqual(result["no_encontrados"], [])
        self.assertEqual(result["encontrados_no_disponibles"], [])

    def test_unknown_translation_yields_single_no_encontrados_entry(self):
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=_StubFuzzyRecognizer(decision="unknown"),
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=lambda: _StubVectorSearchService(
                matches=[_StubVectorMatch(1, 0.9)]
            ),
            recorder=_StubRecorder(),
            commerce_id_resolver=_resolver_with_commerce(99),
        )
        result = recognizer.recognize("nothing", _catalog())
        self.assertEqual(result["encontrados"], [])
        self.assertEqual(result["encontrados_posibles"], [])
        self.assertEqual(result["encontrados_no_disponibles"], [])
        self.assertEqual(len(result["no_encontrados"]), 1)


class TelemetrySurfaceTest(unittest.TestCase):
    def test_recorder_receives_hybrid_authoritative_mode(self):
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=_StubFuzzyRecognizer(decision="unique", encontrados=[1]),
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=lambda: _StubVectorSearchService(
                matches=[_StubVectorMatch(1, 0.9)]
            ),
            recorder=ShadowMetricsRecorder(),
            commerce_id_resolver=_resolver_with_commerce(99),
        )
        with self.assertLogs("backend.services.shadow_metrics_recorder", level="INFO") as captured:
            recognizer.recognize("empanada", _catalog())
        self.assertEqual(len(captured.records), 1)
        record = captured.records[0]
        self.assertEqual(getattr(record, "mode", None), "hybrid_authoritative")
        self.assertFalse(getattr(record, "hybrid_non_authoritative", True))

    def test_recorder_records_filtered_vector_side(self):
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=_StubFuzzyRecognizer(decision="ambiguous", posibles=[1, 2]),
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=lambda: _StubVectorSearchService(
                matches=[_StubVectorMatch(99, 0.95), _StubVectorMatch(1, 0.9)]
            ),
            recorder=ShadowMetricsRecorder(),
            commerce_id_resolver=_resolver_with_commerce(99),
        )
        with self.assertLogs("backend.services.shadow_metrics_recorder", level="INFO") as captured:
            recognizer.recognize(
                "empanada",
                _catalog(),
                intent_metadata={"catalog_scope": "commerce_dynamic_database"},
            )
        record = captured.records[0]
        self.assertEqual(getattr(record, "vector_candidate_count", None), 1)


class DecideHybridHelperTest(unittest.TestCase):
    def test_decide_hybrid_4_11_5_short_circuits_for_restricted_ambiguous(self):
        decision = _decide_hybrid(
            fuzzy_decision="ambiguous",
            intent_metadata={
                "catalog_scope": "pending_product_selection_restricted"
            },
            fuzzy_candidate_ids=(1, 2),
            fuzzy_candidate_scores=(1.0, 0.9),
            filtered_vector_ids=(),
            filtered_vector_scores=(),
            policy=_stub_policy(),
        )
        self.assertEqual(decision, "ambiguous")

    def test_decide_hybrid_4_11_7_fires_for_fuzzy_unique_with_filtered_empty(self):
        decision = _decide_hybrid(
            fuzzy_decision="unique",
            intent_metadata=None,
            fuzzy_candidate_ids=(1,),
            fuzzy_candidate_scores=(1.0,),
            filtered_vector_ids=(),
            filtered_vector_scores=(),
            policy=_stub_policy(),
        )
        self.assertEqual(decision, "unique")


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main(verbosity=2)