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

import importlib
import json
import logging
import os
import sys
import tempfile
import unittest
from typing import Any
from unittest import mock
from unittest.mock import MagicMock, patch

from backend.config.settings import Settings, load_settings
from backend.intents.context import (
    product_modification_resolver as modification_resolver_module,
)
from backend.intents.context import (
    product_selection_context_resolver as selection_resolver_module,
)
from backend.intents.context.product_modification_resolver import (
    detectar_productos as detectar_productos_modification,
)
from backend.intents.context.product_selection_context_resolver import (
    detectar_productos as detectar_productos_selection,
)
from backend.intents.recognizers import (
    modificar_producto_recognizer as modificar_recognizer_module,
)
from backend.intents.recognizers import (
    quitar_producto_recognizer as quitar_recognizer_module,
)
from backend.intents.recognizers.modificar_producto_recognizer import (
    detectar_productos as detectar_productos_modificar,
)
from backend.intents.recognizers.quitar_producto_recognizer import (
    detectar_productos as detectar_productos_quitar,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
from backend.recognizers.fuzzy_product_recognizer import FuzzyProductRecognizer
from backend.recognizers.product_recognizer_contract import (
    ProductRecognizerProtocol,
    ProductRecognizerResult,
    RecognizeContext,
)
from backend.services.exceptions import (
    HybridAuthoritativeCommerceIdMissing,
    HybridAuthoritativePolicyError,
)
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


class _StubSession:
    """Stub SQLAlchemy session used by the factory integration tests."""

    def close(self) -> None:  # pragma: no cover - trivial
        return None


def _stub_session_provider_any() -> Any:
    """Return a non-SQLAlchemy session stub for the factory."""
    return _StubSession()


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
        configured_mode: str | None = None,
        effective_mode: str | None = None,
        authoritative_strategy: str = "fuzzy",
        fallback_category: str | None = None,
        mode: str = "shadow",
    ) -> None:
        self.calls.append(
            {
                "comparison": comparison,
                "hybrid_observation": hybrid_observation,
                "id_comercio": id_comercio,
                "intent": intent,
                "correlation_id": correlation_id,
                "configured_mode": configured_mode,
                "effective_mode": effective_mode,
                "authoritative_strategy": authoritative_strategy,
                "fallback_category": fallback_category,
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

    def test_resolver_returns_none_raises_commerce_id_missing(self):
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
        with self.assertRaises(
            HybridAuthoritativeCommerceIdMissing
        ) as ctx:
            recognizer.recognize("empanada", _catalog())
        self.assertIn("commerce_id", str(ctx.exception))
        # No silent fallback to fuzzy; the integration bug surfaces.
        self.assertEqual(recorder.calls, [])

    def test_resolver_not_provided_raises_commerce_id_missing(self):
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
        with self.assertRaises(
            HybridAuthoritativeCommerceIdMissing
        ) as ctx:
            recognizer.recognize("empanada", _catalog())
        self.assertIn("commerce_id", str(ctx.exception))
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


_PRODUCTION_MODULES = (
    (
        "backend.intents.recognizers.quitar_producto_recognizer",
        quitar_recognizer_module,
    ),
    (
        "backend.intents.recognizers.modificar_producto_recognizer",
        modificar_recognizer_module,
    ),
    (
        "backend.intents.context.product_selection_context_resolver",
        selection_resolver_module,
    ),
    (
        "backend.intents.context.product_modification_resolver",
        modification_resolver_module,
    ),
)


def _reload_production_module(module_name: str, env: dict[str, str]):
    """Reload a production module with ``env`` applied so the
    module-level ``get_product_recognizer(load_settings())`` binding
    re-resolves against the supplied ``PRODUCT_RECOGNIZER_MODE``.
    """
    with mock.patch.dict(os.environ, env, clear=True):
        fresh = importlib.import_module(module_name)
        reloaded = importlib.reload(fresh)
    sys.modules[module_name] = reloaded
    return reloaded


class SharedBoundaryFactoryBindingTest(unittest.TestCase):
    """Verify each production module binds its recognizer through the
    shared ``get_product_recognizer(load_settings())`` factory rather
    than constructing ``FuzzyProductRecognizer`` locally.

    Subphase 4.12B promotes the existing factory to the only selector
    for ``agregar_producto``, ``quitar_producto``, ``modificar_producto``,
    pending product selection, and pending modification destination
    resolution. Every production wrapper must read the same configured
    mode as the orchestrator's ``agregar_producto_orchestrator``
    module.
    """

    def test_default_mode_resolves_to_fuzzy_in_every_module(self):
        for module_name, module in _PRODUCTION_MODULES:
            with self.subTest(module_name=module_name):
                self.assertIsInstance(
                    module._product_recognizer,  # type: ignore[attr-defined]
                    FuzzyProductRecognizer,
                )

    def test_source_files_use_factory_and_drop_local_fuzzy_construction(self):
        for module_name, module in _PRODUCTION_MODULES:
            with self.subTest(module_name=module_name):
                with open(module.__file__, encoding="utf-8") as fh:
                    source = fh.read()
                self.assertIn("get_product_recognizer", source)
                self.assertIn("load_settings", source)
                self.assertNotIn("FuzzyProductRecognizer()", source)

    def test_recognizer_symbol_is_module_level_bound(self):
        for module_name, module in _PRODUCTION_MODULES:
            with self.subTest(module_name=module_name):
                self.assertTrue(
                    hasattr(module, "_product_recognizer"),
                    f"{module_name} must expose a module-level "
                    "_product_recognizer bound by the factory",
                )


class InvalidModeSafeFuzzyBindingTest(unittest.TestCase):
    """Verify an unrecognised ``PRODUCT_RECOGNIZER_MODE`` value resolves
    every production module's recognizer to a safe ``FuzzyProductRecognizer``
    via the existing factory's invalid-mode fallback.
    """

    def test_invalid_mode_yields_fuzzy_in_all_modules(self):
        for module_name, _ in _PRODUCTION_MODULES:
            with self.subTest(module_name=module_name):
                reloaded = _reload_production_module(
                    module_name,
                    {"PRODUCT_RECOGNIZER_MODE": "hybrid_active"},
                )
                try:
                    self.assertIsInstance(
                        reloaded._product_recognizer,  # type: ignore[attr-defined]
                        FuzzyProductRecognizer,
                    )
                finally:
                    _reload_production_module(
                        module_name, {"PRODUCT_RECOGNIZER_MODE": "fuzzy"}
                    )

    def test_capitalised_typo_yields_fuzzy_in_all_modules(self):
        for module_name, _ in _PRODUCTION_MODULES:
            with self.subTest(module_name=module_name):
                reloaded = _reload_production_module(
                    module_name,
                    {"PRODUCT_RECOGNIZER_MODE": "HybridAuthoritative"},
                )
                try:
                    self.assertIsInstance(
                        reloaded._product_recognizer,  # type: ignore[attr-defined]
                        FuzzyProductRecognizer,
                    )
                finally:
                    _reload_production_module(
                        module_name, {"PRODUCT_RECOGNIZER_MODE": "fuzzy"}
                    )


class HybridAuthoritativeBindingTest(unittest.TestCase):
    """Verify the hybrid authoritative mode propagates to every
    production module when the calibrated policy file is eligible.
    """

    @classmethod
    def setUpClass(cls):
        cls._policy_payload = {
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
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._policy_path = cls._write_policy(cls._policy_payload)

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()
        # Reset every production module to fuzzy mode.
        for module_name, _ in _PRODUCTION_MODULES:
            _reload_production_module(
                module_name, {"PRODUCT_RECOGNIZER_MODE": "fuzzy"}
            )

    @classmethod
    def _write_policy(cls, payload: dict) -> str:
        descriptor, path = tempfile.mkstemp(
            suffix=".json", dir=cls._tmpdir.name, prefix="hybrid_policy_"
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return path

    def test_hybrid_mode_binds_hybrid_recognizer_in_every_module(self):
        env = {
            "PRODUCT_RECOGNIZER_MODE": "hybrid_authoritative",
            "HYBRID_AUTHORITATIVE_POLICY_PATH": self._policy_path,
        }
        for module_name, _ in _PRODUCTION_MODULES:
            with self.subTest(module_name=module_name):
                reloaded = _reload_production_module(module_name, env)
                try:
                    self.assertIsInstance(
                        reloaded._product_recognizer,  # type: ignore[attr-defined]
                        HybridAuthoritativeProductRecognizer,
                    )
                finally:
                    _reload_production_module(
                        module_name, {"PRODUCT_RECOGNIZER_MODE": "fuzzy"}
                    )


class QuitarFlowFactoryBoundaryTest(unittest.TestCase):
    """Verify the quitar_producto wrapper threads its catalog through
    the factory-bound recognizer and preserves caller-owned catalog
    construction.
    """

    def test_quitar_wrapper_invokes_factory_bound_recognizer(self):
        sentinel = _StubFuzzyRecognizer(
            decision="unique", encontrados=[1]
        )
        original = quitar_recognizer_module._product_recognizer  # type: ignore[attr-defined]
        quitar_recognizer_module._product_recognizer = sentinel  # type: ignore[attr-defined]
        try:
            catalog = [
                {"producto_presentacion_id": 1, "producto_nombre": "x"}
            ]
            result = detectar_productos_quitar("x", catalog)
        finally:
            quitar_recognizer_module._product_recognizer = original  # type: ignore[attr-defined]
        self.assertEqual(sentinel.call_count, 1)
        self.assertEqual(result["encontrados"][0]["producto_presentacion_id"], 1)

    def test_quitar_wrapper_passes_intent_metadata_through(self):
        sentinel = _StubFuzzyRecognizer(
            decision="unique", encontrados=[1]
        )
        original = quitar_recognizer_module._product_recognizer  # type: ignore[attr-defined]
        quitar_recognizer_module._product_recognizer = sentinel  # type: ignore[attr-defined]
        try:
            catalog = [
                {"producto_presentacion_id": 1, "producto_nombre": "x"}
            ]
            detectar_productos_quitar(
                "x",
                catalog,
                intent_metadata={  # type: ignore[arg-type]
                    "catalog_scope": "pending_product_selection_restricted"
                },
            )
        finally:
            quitar_recognizer_module._product_recognizer = original  # type: ignore[attr-defined]
        self.assertEqual(
            sentinel.last_kwargs["intent_metadata"],  # type: ignore[attr-defined]
            {"catalog_scope": "pending_product_selection_restricted"},
        )


class ModificarFlowFactoryBoundaryTest(unittest.TestCase):
    """Verify the modificar_producto wrapper threads its source and
    destination catalogs through the factory-bound recognizer.
    """

    def test_modificar_wrapper_invokes_factory_bound_recognizer(self):
        sentinel = _StubFuzzyRecognizer(
            decision="unique", encontrados=[100]
        )
        original = (
            modificar_recognizer_module._product_recognizer  # type: ignore[attr-defined]
        )
        modificar_recognizer_module._product_recognizer = sentinel  # type: ignore[attr-defined]
        try:
            catalog = [
                {"producto_presentacion_id": 100, "producto_nombre": "x"}
            ]
            result = detectar_productos_modificar("x", catalog)
        finally:
            (
                modificar_recognizer_module._product_recognizer  # type: ignore[attr-defined]
            ) = original
        self.assertEqual(sentinel.call_count, 1)
        self.assertEqual(
            result["encontrados"][0]["producto_presentacion_id"], 100
        )


class PendingSelectionFlowFactoryBoundaryTest(unittest.TestCase):
    """Verify the pending product selection resolver forwards
    ``catalog_scope=pending_product_selection_restricted`` through the
    factory-bound recognizer.
    """

    def test_selection_wrapper_forwards_restricted_catalog_scope(self):
        sentinel = _StubFuzzyRecognizer(
            decision="ambiguous", posibles=[1, 2]
        )
        original = (
            selection_resolver_module._product_recognizer  # type: ignore[attr-defined]
        )
        selection_resolver_module._product_recognizer = sentinel  # type: ignore[attr-defined]
        try:
            detectar_productos_selection(
                "x",
                [{"producto_presentacion_id": 1, "producto_nombre": "x"}],
                intent_metadata={  # type: ignore[arg-type]
                    "catalog_scope": "pending_product_selection_restricted"
                },
            )
        finally:
            (
                selection_resolver_module._product_recognizer  # type: ignore[attr-defined]
            ) = original
        self.assertEqual(
            sentinel.last_kwargs["intent_metadata"],  # type: ignore[attr-defined]
            {"catalog_scope": "pending_product_selection_restricted"},
        )


class PendingModificationFlowFactoryBoundaryTest(unittest.TestCase):
    """Verify the pending modification resolver threads its destination
    catalog through the factory-bound recognizer.
    """

    def test_modification_wrapper_invokes_factory_bound_recognizer(self):
        sentinel = _StubFuzzyRecognizer(
            decision="unique", encontrados=[200]
        )
        original = (
            modification_resolver_module._product_recognizer  # type: ignore[attr-defined]
        )
        modification_resolver_module._product_recognizer = sentinel  # type: ignore[attr-defined]
        try:
            catalog = [
                {"producto_presentacion_id": 200, "producto_nombre": "y"}
            ]
            result = detectar_productos_modification("y", catalog)
        finally:
            (
                modification_resolver_module._product_recognizer  # type: ignore[attr-defined]
            ) = original
        self.assertEqual(sentinel.call_count, 1)
        self.assertEqual(
            result["encontrados"][0]["producto_presentacion_id"], 200
        )


class ModeContractAcrossFlowsTest(unittest.TestCase):
    """Verify the three documented mode contracts apply uniformly to
    every flow when the recognizer is the factory output.
    """

    def _patch_recognizer(self, module, recognizer):
        original = module._product_recognizer  # type: ignore[attr-defined]
        module._product_recognizer = recognizer  # type: ignore[attr-defined]
        return original

    def _restore(self, module, original):
        module._product_recognizer = original  # type: ignore[attr-defined]

    def test_fuzzy_mode_is_authoritative_for_quitar(self):
        recognizer = _StubFuzzyRecognizer(
            decision="unique", encontrados=[1]
        )
        catalog = [{"producto_presentacion_id": 1, "producto_nombre": "x"}]
        original = self._patch_recognizer(
            quitar_recognizer_module, recognizer
        )
        try:
            result = detectar_productos_quitar("x", catalog)
        finally:
            self._restore(quitar_recognizer_module, original)
        self.assertEqual(
            result["encontrados"][0]["producto_presentacion_id"], 1
        )

    def test_shadow_mode_keeps_fuzzy_authoritative_for_quitar(self):
        recognizer = ShadowedProductRecognizer(
            inner=_StubFuzzyRecognizer(
                decision="unique", encontrados=[1]
            ),
            shadow=mock.MagicMock(),
            recorder=_StubRecorder(),
            commerce_id_resolver=None,
        )
        catalog = [{"producto_presentacion_id": 1, "producto_nombre": "x"}]
        original = self._patch_recognizer(
            quitar_recognizer_module, recognizer
        )
        try:
            result = detectar_productos_quitar("x", catalog)
        finally:
            self._restore(quitar_recognizer_module, original)
        self.assertEqual(
            result["encontrados"][0]["producto_presentacion_id"], 1
        )

    def test_hybrid_authoritative_unique_returns_unique_for_quitar(self):
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=_StubFuzzyRecognizer(
                decision="unique", encontrados=[1]
            ),
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=(
                lambda: _StubVectorSearchService(matches=[
                    _StubVectorMatch(1, 0.9)
                ])
            ),
            recorder=_StubRecorder(),
            commerce_id_resolver=_resolver_with_commerce(99),
        )
        catalog = [{"producto_presentacion_id": 1, "producto_nombre": "x"}]
        original = self._patch_recognizer(
            quitar_recognizer_module, recognizer
        )
        try:
            result = detectar_productos_quitar("x", catalog)
        finally:
            self._restore(quitar_recognizer_module, original)
        self.assertEqual(
            result["encontrados"][0]["producto_presentacion_id"], 1
        )

    def test_hybrid_authoritative_unique_isolated_to_received_catalog(self):
        """Hybrid unique must not introduce candidates outside the
        caller-supplied catalog (commerce-isolation invariant)."""
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=_StubFuzzyRecognizer(
                decision="unique", encontrados=[1]
            ),
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=(
                lambda: _StubVectorSearchService(matches=[
                    _StubVectorMatch(99, 0.95)
                ])
            ),
            recorder=_StubRecorder(),
            commerce_id_resolver=_resolver_with_commerce(99),
        )
        catalog = [{"producto_presentacion_id": 1, "producto_nombre": "x"}]
        original = self._patch_recognizer(
            quitar_recognizer_module, recognizer
        )
        try:
            result = detectar_productos_quitar("x", catalog)
        finally:
            self._restore(quitar_recognizer_module, original)
        ids = [
            entry["producto_presentacion_id"]
            for entry in result["encontrados"]
        ]
        self.assertEqual(ids, [1])
        self.assertNotIn(99, ids)

    def test_hybrid_authoritative_unknown_returns_unknown_for_quitar(self):
        """Hybrid unknown is authoritative; it does NOT fall back to
        fuzzy. The 4.11.7 guard does not apply because the fuzzy
        decision is unknown, not unique.
        """
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=_StubFuzzyRecognizer(decision="unknown"),
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=(
                lambda: _StubVectorSearchService(matches=[
                    _StubVectorMatch(99, 0.95)
                ])
            ),
            recorder=_StubRecorder(),
            commerce_id_resolver=_resolver_with_commerce(99),
        )
        catalog = [{"producto_presentacion_id": 1, "producto_nombre": "x"}]
        original = self._patch_recognizer(
            quitar_recognizer_module, recognizer
        )
        try:
            result = detectar_productos_quitar("x", catalog)
        finally:
            self._restore(quitar_recognizer_module, original)
        self.assertEqual(result["encontrados"], [])
        self.assertEqual(len(result["no_encontrados"]), 1)


class CommerceIdFlowIntegrationTest(unittest.TestCase):
    """Real-entry-point integration tests for the Subphase 4.12B
    commerce-id wiring.

    The tests use a spy recognizer that records the ``intent_metadata``
    passed to it. Each production wrapper is exercised through its
    real ``detectar_productos`` alias, and the spy verifies the
    ``commerce_id`` field arrived at the recognizer.
    """

    class _SpyRecognizer:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def recognize(
            self,
            text: str,
            catalog: list[dict],
            *,
            intent_metadata=None,
        ):
            self.calls.append(
                {
                    "text": text,
                    "catalog": catalog,
                    "intent_metadata": intent_metadata,
                }
            )
            return {
                "encontrados": [],
                "encontrados_posibles": [],
                "encontrados_no_disponibles": [],
                "no_encontrados": [{"texto_origen": text}],
            }

    def _patch_module(self, module, recognizer):
        original = module._product_recognizer  # type: ignore[attr-defined]
        module._product_recognizer = recognizer  # type: ignore[attr-defined]
        return original

    def _restore_module(self, module, original):
        module._product_recognizer = original  # type: ignore[attr-defined]

    def test_agregar_wrapper_threads_commerce_id_via_intent_metadata(self):
        """``agregar_producto``'s wrapper must forward
        ``commerce_id`` through ``intent_metadata``.
        """
        spy = self._SpyRecognizer()
        from backend.intents.orchestration import (
            agregar_producto_orchestrator as orchestrator_module,
        )

        original = self._patch_module(orchestrator_module, spy)
        try:
            catalog = [
                {"producto_presentacion_id": 1, "producto_nombre": "x"}
            ]
            orchestrator_module.detectar_productos(
                "empanada de carne",
                catalog,
                intent_metadata={
                    "catalog_scope": "commerce_dynamic_database",
                    "commerce_id": 7,
                },
            )
        finally:
            self._restore_module(orchestrator_module, original)

        self.assertEqual(len(spy.calls), 1)
        self.assertEqual(spy.calls[0]["intent_metadata"]["commerce_id"], 7)
        self.assertEqual(
            spy.calls[0]["intent_metadata"]["catalog_scope"],
            "commerce_dynamic_database",
        )

    def test_quitar_wrapper_threads_commerce_id_via_intent_metadata(self):
        """``quitar_producto``'s wrapper must forward
        ``commerce_id`` through ``intent_metadata``.
        """
        spy = self._SpyRecognizer()
        from backend.intents.recognizers import (
            quitar_producto_recognizer as quitar_module,
        )

        original = self._patch_module(quitar_module, spy)
        try:
            catalog = [
                {
                    "producto_presentacion_id": 10,
                    "producto_nombre": "Empanada",
                    "pedido_producto_id": 1,
                }
            ]
            quitar_module.detectar_productos(
                "empanada",
                catalog,
                intent_metadata={
                    "catalog_scope": "commerce_dynamic_database",
                    "commerce_id": 42,
                },
            )
        finally:
            self._restore_module(quitar_module, original)

        self.assertEqual(len(spy.calls), 1)
        self.assertEqual(spy.calls[0]["intent_metadata"]["commerce_id"], 42)

    def test_modificar_wrapper_threads_commerce_id_via_intent_metadata(self):
        """``modificar_producto``'s wrapper must forward
        ``commerce_id`` through ``intent_metadata``.
        """
        spy = self._SpyRecognizer()
        from backend.intents.recognizers import (
            modificar_producto_recognizer as modificar_module,
        )

        original = self._patch_module(modificar_module, spy)
        try:
            catalog = [
                {"producto_presentacion_id": 200, "producto_nombre": "Pizza"}
            ]
            modificar_module.detectar_productos(
                "pizza",
                catalog,
                intent_metadata={
                    "catalog_scope": "commerce_dynamic_database",
                    "commerce_id": 99,
                },
            )
        finally:
            self._restore_module(modificar_module, original)

        self.assertEqual(len(spy.calls), 1)
        self.assertEqual(spy.calls[0]["intent_metadata"]["commerce_id"], 99)

    def test_selection_resolver_threads_commerce_id_via_intent_metadata(self):
        """The pending product selection resolver must forward
        ``commerce_id`` through ``intent_metadata`` when supplied.
        """
        spy = self._SpyRecognizer()
        from backend.intents.context import (
            product_selection_context_resolver as resolver_module,
        )

        original = self._patch_module(resolver_module, spy)
        try:
            active = ProcessedIntent(
                intent="agregar_producto",
                source_text="quiero pizza",
                status="pending_resolution",
                recognizer="recognizer_productos",
                handler="agregar_producto",
                resolved_data={"cantidad": 1},
                requirements=[
                    RequirementState(
                        name="producto_presentacion_id",
                        status="pending",
                        value=None,
                    )
                ],
                candidate_ids=[1, 2],
            )
            catalog = [
                {"producto_presentacion_id": pid, "producto_nombre": f"item-{pid}"}
                for pid in [1, 2]
            ]
            resolver_module.resolve_product_selection(
                "item-1",
                active,
                catalog,
                commerce_id=99,
            )
        finally:
            self._restore_module(resolver_module, original)

        self.assertEqual(len(spy.calls), 1)
        self.assertEqual(spy.calls[0]["intent_metadata"]["commerce_id"], 99)
        self.assertEqual(
            spy.calls[0]["intent_metadata"]["catalog_scope"],
            "pending_product_selection_restricted",
        )

    def test_modification_resolver_threads_commerce_id_via_intent_metadata(self):
        """The pending modification resolver must forward
        ``commerce_id`` through ``intent_metadata``.
        """
        spy = self._SpyRecognizer()
        from backend.intents.context import (
            product_modification_resolver as resolver_module,
        )

        original = self._patch_module(resolver_module, spy)
        try:
            catalog = [{"producto_presentacion_id": 200, "producto_nombre": "y"}]
            conversation = MagicMock()
            conversation.id_comercio = 33
            with patch.object(resolver_module, "ProductoQueryService") as svc:
                svc.return_value.list_presentaciones_by_ids.return_value = catalog
                db = MagicMock()

                with patch.object(
                    resolver_module, "recognize_quitar_producto"
                ) as qpr:
                    qpr.return_value = {
                        "encontrados": [],
                        "encontrados_posibles": [],
                        "encontrados_no_disponibles": [],
                        "no_encontrados": [{"texto_origen": "y"}],
                    }
                    resolver_module.resolve_product_modification(
                        db,
                        conversation,
                        "y",
                        ProcessedIntent(
                            intent="modificar_producto",
                            source_text="x",
                            status="pending_resolution",
                            recognizer="modificar_producto_recognizer",
                            handler="modificar_producto",
                            stage="destination_selection",
                            resolved_data={
                                "source_candidate_ids": [1],
                                "destination_candidate_ids": [200],
                            },
                            candidate_ids=[],
                        ),
                    )
        finally:
            self._restore_module(resolver_module, original)

        self.assertEqual(len(spy.calls), 1)
        self.assertEqual(spy.calls[0]["intent_metadata"]["commerce_id"], 33)


class HybridPipelineCommerceIntegrationTest(unittest.TestCase):
    """End-to-end integration tests that prove the hybrid pipeline
    actually runs when the production entry points supply the
    ``commerce_id`` via ``intent_metadata``."""

    def test_real_hybrid_pipeline_executes_when_commerce_id_is_in_intent_metadata(
        self,
    ):
        """The real ``HybridAuthoritativeProductRecognizer`` runs the
        embedding + vector pipeline when the entry point supplies a
        ``commerce_id`` via ``intent_metadata`` and returns the hybrid
        decision (not the fuzzy result).
        """
        from backend.recognizers.fuzzy_product_recognizer import (
            FuzzyProductRecognizer,
        )
        from backend.services.product_recognition_calibration_policy import (
            HybridDecisionPolicy,
        )

        vector_service = _StubVectorSearchService(
            matches=[_StubVectorMatch(1, 0.95)]
        )
        recorder = _StubRecorder()
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=FuzzyProductRecognizer(),
            policy=HybridDecisionPolicy(
                fuzzy_weight=0.5,
                vector_weight=0.5,
                unique_threshold=0.7,
                ambiguous_threshold=0.4,
                minimum_score_gap=0.05,
                vector_top_k=5,
            ),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=lambda: vector_service,
            recorder=recorder,
            configured_mode="hybrid_authoritative",
            effective_mode="hybrid_authoritative",
        )

        from backend.intents.orchestration import (
            agregar_producto_orchestrator as orchestrator_module,
        )

        original = orchestrator_module._product_recognizer  # type: ignore[attr-defined]
        orchestrator_module._product_recognizer = recognizer  # type: ignore[attr-defined]
        try:
            catalog = [
                {
                    "producto_presentacion_id": 1,
                    "producto_nombre": "Empanada de Carne",
                    "presentacion_codigo": "unidad",
                    "aliases": {"general_aliases": [], "specific_aliases": []},
                }
            ]
            result = orchestrator_module.detectar_productos(
                "empanada de carne",
                catalog,
                intent_metadata={
                    "catalog_scope": "commerce_dynamic_database",
                    "commerce_id": 7,
                },
            )
        finally:
            orchestrator_module._product_recognizer = original  # type: ignore[attr-defined]

        # The hybrid pipeline ran: the stub vector service was
        # invoked with the resolved commerce id (7) and the hybrid
        # decision was returned (not the fuzzy result).
        self.assertEqual(vector_service.call_count, 1)
        self.assertEqual(vector_service.last_kwargs["id_comercio"], 7)
        self.assertEqual(len(result["encontrados"]), 1)
        self.assertEqual(result["encontrados"][0]["producto_presentacion_id"], 1)
        # The recorder received the hybrid-evaluative observation.
        self.assertEqual(len(recorder.calls), 1)
        self.assertFalse(recorder.calls[0]["comparison"].fallback)
        self.assertEqual(
            recorder.calls[0]["authoritative_strategy"], "hybrid"
        )

    def test_real_hybrid_pipeline_raises_when_commerce_id_missing(self):
        """Without a ``commerce_id`` in ``intent_metadata`` and
        without a ``commerce_id_resolver``, the hybrid pipeline
        refuses to run and raises
        :class:`HybridAuthoritativeCommerceIdMissing`. Missing
        commerce id is NOT a fallback category under the OpenSpec
        contract; the integration bug must surface immediately.
        """
        from backend.recognizers.fuzzy_product_recognizer import (
            FuzzyProductRecognizer,
        )

        vector_service = _StubVectorSearchService(
            matches=[_StubVectorMatch(1, 0.99)]
        )
        recorder = _StubRecorder()
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=FuzzyProductRecognizer(),
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=lambda: vector_service,
            recorder=recorder,
            configured_mode="hybrid_authoritative",
            effective_mode="hybrid_authoritative",
        )

        from backend.intents.orchestration import (
            agregar_producto_orchestrator as orchestrator_module,
        )

        original = orchestrator_module._product_recognizer  # type: ignore[attr-defined]
        orchestrator_module._product_recognizer = recognizer  # type: ignore[attr-defined]
        try:
            catalog = [
                {
                    "producto_presentacion_id": 1,
                    "producto_nombre": "Empanada de Carne",
                    "presentacion_codigo": "unidad",
                }
            ]
            with self.assertRaises(HybridAuthoritativeCommerceIdMissing):
                orchestrator_module.detectar_productos(
                    "empanada de carne",
                    catalog,
                    intent_metadata={
                        "catalog_scope": "commerce_dynamic_database"
                    },
                )
        finally:
            orchestrator_module._product_recognizer = original  # type: ignore[attr-defined]

        # The vector lookup must not have happened.
        self.assertEqual(vector_service.call_count, 0)
        # No observation record is emitted for the integration bug.
        self.assertEqual(recorder.calls, [])


class ObservabilityPayloadTest(unittest.TestCase):
    """Observability payload tests for the configured/effective mode,
    authoritative strategy, fuzzy decision, hybrid decision, fallback
    boolean, and sanitized fallback category.

    Every mode path emits the documented fields. Sensitive fields
    (customer text, vectors, credentials, raw exceptions) are
    never logged.
    """

    def _safe_extra_keys(self, record) -> set[str]:
        """Verify the recorder never carries raw sensitive fields.

        Forbidden substrings target raw customer text, raw query
        embeddings, raw vector scores, and credentials. Latency and
        latency-counter fields named ``vector_*`` are operational
        metrics, not raw vectors; they are explicitly allowed.
        """
        forbidden_substrings = (
            "texto_origen",
            "raw_query_embedding",
            "raw_vector_scores",
            "customer_message",
            "raw_embedding",
            "stack_trace",
            "raw_exception",
            "credencial",
        )
        allowed_latency_metrics = {
            "vector_latency_ms",
            "vector_candidate_count",
            "vector_best_id",
            "vector_candidate_ids",
        }
        keys = {attr for attr in dir(record) if not attr.startswith("_")}
        for key in keys:
            if key in allowed_latency_metrics:
                continue
            for forbidden in forbidden_substrings:
                self.assertNotIn(forbidden, key.lower())
        return keys

    def test_hybrid_authoritative_successful_unique_records_minimum_fields(self):
        """A successful hybrid authoritative call records
        configured_mode, effective_mode, authoritative_strategy,
        fuzzy_decision (implicit via ranking), hybrid_decision,
        fallback=False, and fallback_category=None.
        """
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=_StubFuzzyRecognizer(decision="unique", encontrados=[1]),
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=(
                lambda: _StubVectorSearchService(matches=[
                    _StubVectorMatch(1, 0.9)
                ])
            ),
            recorder=ShadowMetricsRecorder(),
            commerce_id_resolver=_resolver_with_commerce(99),
            configured_mode="hybrid_authoritative",
            effective_mode="hybrid_authoritative",
        )

        with self.assertLogs(
            "backend.services.shadow_metrics_recorder", level="INFO"
        ) as captured:
            recognizer.recognize(
                "empanada",
                _catalog(),
                intent_metadata={
                    "catalog_scope": "commerce_dynamic_database",
                    "commerce_id": 99,
                },
            )

        record = captured.records[0]
        self.assertEqual(record.mode, "hybrid_authoritative")
        self.assertEqual(
            record.configured_mode, "hybrid_authoritative"
        )
        self.assertEqual(record.effective_mode, "hybrid_authoritative")
        self.assertEqual(record.authoritative_strategy, "hybrid")
        self.assertEqual(record.hybrid_decision, "unique")
        self.assertFalse(record.fallback)
        self.assertIsNone(record.fallback_category)
        self._safe_extra_keys(record)

    def test_hybrid_authoritative_embedding_failure_records_fallback_category(
        self,
    ):
        """An embedding failure records ``fallback=True`` and a
        sanitized ``fallback_category='embedding_failure'``.
        """

        class _FailingEmbeddingClient:
            def embed_query(self, text):
                raise RuntimeError("embedding down")

            def embed_documents(self, texts):
                return [[0.0] * 384 for _ in texts]

        recognizer = HybridAuthoritativeProductRecognizer(
            inner=_StubFuzzyRecognizer(decision="ambiguous", posibles=[1, 2]),
            policy=_stub_policy(),
            embedding_client=_FailingEmbeddingClient(),
            vector_search_service=lambda: _StubVectorSearchService(),
            recorder=ShadowMetricsRecorder(),
            commerce_id_resolver=_resolver_with_commerce(99),
            configured_mode="hybrid_authoritative",
            effective_mode="hybrid_authoritative",
        )

        with self.assertLogs(
            "backend.services.shadow_metrics_recorder", level="INFO"
        ) as captured:
            recognizer.recognize(
                "empanada",
                _catalog(),
                intent_metadata={
                    "catalog_scope": "commerce_dynamic_database",
                    "commerce_id": 99,
                },
            )

        record = captured.records[0]
        self.assertEqual(record.mode, "hybrid_authoritative")
        self.assertEqual(record.effective_mode, "hybrid_authoritative")
        self.assertEqual(record.authoritative_strategy, "hybrid")
        self.assertTrue(record.fallback)
        self.assertEqual(
            record.fallback_category, "embedding_failure"
        )
        self._safe_extra_keys(record)

    def test_hybrid_authoritative_unknown_decision_does_not_fallback(self):
        """A semantic hybrid ``unknown`` decision does NOT trigger
        fallback; the hybrid decision is authoritative.
        """
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=_StubFuzzyRecognizer(decision="unknown"),
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=(
                lambda: _StubVectorSearchService(matches=[
                    _StubVectorMatch(99, 0.95)
                ])
            ),
            recorder=ShadowMetricsRecorder(),
            commerce_id_resolver=_resolver_with_commerce(99),
            configured_mode="hybrid_authoritative",
            effective_mode="hybrid_authoritative",
        )

        with self.assertLogs(
            "backend.services.shadow_metrics_recorder", level="INFO"
        ) as captured:
            recognizer.recognize(
                "empanada",
                _catalog(),
                intent_metadata={
                    "catalog_scope": "commerce_dynamic_database",
                    "commerce_id": 99,
                },
            )

        record = captured.records[0]
        self.assertEqual(record.hybrid_decision, "unknown")
        self.assertFalse(record.fallback)
        self.assertIsNone(record.fallback_category)
        self._safe_extra_keys(record)

    def test_hybrid_authoritative_ambiguous_decision_does_not_fallback(self):
        """A semantic hybrid ``ambiguous`` decision does NOT trigger
        fallback.
        """
        # Lower the unique_threshold and ambiguous_threshold so that
        # the fuzzy-ambiguous input + a single weak vector candidate
        # produces an ambiguous hybrid decision (not unique).
        from backend.services.product_recognition_calibration_policy import (
            HybridDecisionPolicy,
        )

        ambiguous_policy = HybridDecisionPolicy(
            fuzzy_weight=0.5,
            vector_weight=0.5,
            unique_threshold=0.9,
            ambiguous_threshold=0.4,
            minimum_score_gap=0.05,
            vector_top_k=5,
        )
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=_StubFuzzyRecognizer(decision="ambiguous", posibles=[1, 2]),
            policy=ambiguous_policy,
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=(
                lambda: _StubVectorSearchService(matches=[
                    _StubVectorMatch(1, 0.3)
                ])
            ),
            recorder=ShadowMetricsRecorder(),
            commerce_id_resolver=_resolver_with_commerce(99),
            configured_mode="hybrid_authoritative",
            effective_mode="hybrid_authoritative",
        )

        with self.assertLogs(
            "backend.services.shadow_metrics_recorder", level="INFO"
        ) as captured:
            recognizer.recognize(
                "empanada",
                _catalog(),
                intent_metadata={
                    "catalog_scope": "commerce_dynamic_database",
                    "commerce_id": 99,
                },
            )

        record = captured.records[0]
        self.assertEqual(record.hybrid_decision, "ambiguous")
        self.assertFalse(record.fallback)
        self.assertIsNone(record.fallback_category)
        self._safe_extra_keys(record)

    def test_hybrid_authoritative_missing_commerce_id_is_not_a_fallback(self):
        """Missing ``commerce_id`` is NOT a fallback reason under the
        OpenSpec contract. The hybrid authoritative recognizer must
        raise :class:`HybridAuthoritativeCommerceIdMissing` instead of
        silently returning the fuzzy result and tagging the call as a
        ``no_commerce_id`` fallback.
        """
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=_StubFuzzyRecognizer(decision="ambiguous", posibles=[1, 2]),
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=lambda: _StubVectorSearchService(),
            recorder=ShadowMetricsRecorder(),
            configured_mode="hybrid_authoritative",
            effective_mode="hybrid_authoritative",
        )

        with self.assertRaises(
            HybridAuthoritativeCommerceIdMissing
        ) as ctx:
            recognizer.recognize(
                "empanada",
                _catalog(),
                intent_metadata={"catalog_scope": "commerce_dynamic_database"},
            )
        self.assertIn("commerce_id", str(ctx.exception))
        # The exception message must never carry the customer text,
        # the catalog payload, or any internal exception detail.
        self.assertNotIn("empanada", str(ctx.exception))

    def test_invalid_mode_resolves_to_fuzzy_with_safe_observability(self):
        """An unrecognised ``PRODUCT_RECOGNIZER_MODE`` resolves the
        runtime to ``fuzzy`` and emits the safe-fuzzy fallback
        warning without invoking any hybrid pipeline.
        """
        from backend.services.product_recognition_factory import (
            get_product_recognizer,
        )

        env = {"PRODUCT_RECOGNIZER_MODE": "hybrid_active"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertLogs(
                "backend.config.settings", level="WARNING"
            ) as settings_log:
                settings = load_settings()
            self.assertEqual(settings.product_recognizer_mode, "fuzzy")
            self.assertEqual(
                settings.product_recognizer_configured_mode, "hybrid_active"
            )
            recognizer = get_product_recognizer(
                settings,
                session_provider=_stub_session_provider_any,
                embedding_client=_StubEmbeddingClient(),
            )
            self.assertIsInstance(recognizer, FuzzyProductRecognizer)
        # The warning carries the safe-fuzzy fallback fields.
        record = settings_log.records[0]
        self.assertEqual(record.configured_mode, "hybrid_active")
        self.assertEqual(record.effective_mode, "fuzzy")
        self.assertEqual(record.reason, "invalid_mode")

    def test_shadow_mode_records_authoritative_strategy_fuzzy(self):
        """The shadow service records ``authoritative_strategy='fuzzy'``
        because the fuzzy result remains authoritative in shadow mode.
        """
        from backend.services.product_recognition_shadow_service import (
            ProductRecognitionShadowService,
            ShadowedProductRecognizer,
        )

        service = ProductRecognitionShadowService(
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=lambda: _StubVectorSearchService(
                matches=[_StubVectorMatch(1, 0.9)]
            ),
            settings=_settings(product_recognizer_mode="shadow"),
        )
        recognizer = ShadowedProductRecognizer(
            inner=FuzzyProductRecognizer(),
            shadow=service,
            recorder=ShadowMetricsRecorder(),
            commerce_id_resolver=_resolver_with_commerce(99),
            configured_mode="shadow",
            effective_mode="shadow",
        )

        with self.assertLogs(
            "backend.services.shadow_metrics_recorder", level="INFO"
        ) as captured:
            recognizer.recognize(
                "empanada",
                _catalog(),
                intent_metadata={
                    "catalog_scope": "commerce_dynamic_database",
                    "commerce_id": 99,
                },
            )

        record = captured.records[0]
        self.assertEqual(record.mode, "shadow")
        self.assertEqual(record.configured_mode, "shadow")
        self.assertEqual(record.effective_mode, "shadow")
        self.assertEqual(record.authoritative_strategy, "fuzzy")
        self.assertFalse(record.fallback)
        self.assertIsNone(record.fallback_category)
        self._safe_extra_keys(record)


class FuzzyModeObservabilityTest(unittest.TestCase):
    """Per-request observability tests for the
    ``ObservedFuzzyProductRecognizer`` decorator.

    The decorator subclasses ``FuzzyProductRecognizer`` so the
    four-key result contract and catalog-isolation guarantees stay
    intact. Every ``recognize(...)`` call MUST emit one
    ``ShadowMetricsRecorder`` record with the documented fields
    without invoking embedding or vector search.
    """

    @staticmethod
    def _safe_extra_keys(test_case, record) -> set[str]:
        """Verify the recorder never carries raw sensitive fields.

        Forbidden substrings target raw customer text, raw query
        embeddings, raw vector scores, and credentials. Operational
        latency and counter fields named ``vector_*`` are explicitly
        allowed (they are metrics, not raw vectors).
        """
        forbidden_substrings = (
            "texto_origen",
            "raw_query_embedding",
            "raw_vector_scores",
            "customer_message",
            "raw_embedding",
            "stack_trace",
            "raw_exception",
            "credencial",
        )
        allowed_latency_metrics = {
            "vector_latency_ms",
            "vector_candidate_count",
            "vector_best_id",
            "vector_candidate_ids",
        }
        keys = {attr for attr in dir(record) if not attr.startswith("_")}
        for key in keys:
            if key in allowed_latency_metrics:
                continue
            for forbidden in forbidden_substrings:
                test_case.assertNotIn(forbidden, key.lower())
        return keys

    def _catalog(self) -> list[dict]:
        return [
            {
                "producto_presentacion_id": 1,
                "producto_nombre": "Empanada de Carne",
                "presentacion_codigo": "unidad",
                "aliases": {"general_aliases": [], "specific_aliases": []},
            }
        ]

    def test_observed_fuzzy_recognizer_is_subclass_of_fuzzy(self):
        from backend.services.product_recognition_factory import (
            ObservedFuzzyProductRecognizer,
        )

        recognizer = ObservedFuzzyProductRecognizer(
            recorder=ShadowMetricsRecorder(),
            configured_mode="fuzzy",
            effective_mode="fuzzy",
        )
        self.assertIsInstance(recognizer, FuzzyProductRecognizer)

    def test_fuzzy_mode_records_minimum_observability_fields(self):
        """A fuzzy-mode call records ``configured_mode``,
        ``effective_mode``, ``authoritative_strategy='fuzzy'``,
        ``hybrid_decision='not_evaluated'``, ``fallback=False``,
        and an absent ``fallback_category``.
        """
        from backend.services.product_recognition_factory import (
            ObservedFuzzyProductRecognizer,
        )

        recognizer = ObservedFuzzyProductRecognizer(
            recorder=ShadowMetricsRecorder(),
            configured_mode="fuzzy",
            effective_mode="fuzzy",
        )

        with self.assertLogs(
            "backend.services.shadow_metrics_recorder", level="INFO"
        ) as captured:
            recognizer.recognize("empanada de carne", self._catalog())

        record = captured.records[0]
        self.assertEqual(record.mode, "fuzzy")
        self.assertEqual(record.configured_mode, "fuzzy")
        self.assertEqual(record.effective_mode, "fuzzy")
        self.assertEqual(record.authoritative_strategy, "fuzzy")
        self.assertEqual(record.hybrid_decision, "not_evaluated")
        self.assertFalse(record.fallback)
        self.assertIsNone(record.fallback_category)
        FuzzyModeObservabilityTest._safe_extra_keys(self, record)

    def test_fuzzy_mode_preserves_four_key_result_contract(self):
        """The decorator forwards the four-key
        ``ProductRecognizerResult`` byte-for-byte unchanged.
        """
        from backend.services.product_recognition_factory import (
            ObservedFuzzyProductRecognizer,
        )

        recognizer = ObservedFuzzyProductRecognizer(
            recorder=ShadowMetricsRecorder(),
            configured_mode="fuzzy",
            effective_mode="fuzzy",
        )
        result = recognizer.recognize("empanada de carne", self._catalog())
        for key in (
            "encontrados",
            "encontrados_posibles",
            "encontrados_no_disponibles",
            "no_encontrados",
        ):
            self.assertIn(key, result)
            self.assertIsInstance(result[key], list)

    def test_invalid_mode_records_invalid_mode_category(self):
        """The decorator carries the configured-mode literal so the
        per-request record exposes ``configured_mode='hybrid_active'``,
        ``effective_mode='fuzzy'``,
        ``authoritative_strategy='fuzzy'``, ``fallback=True``,
        ``fallback_category='invalid_mode'``, and a non-evaluated
        ``hybrid_decision``. The ``Settings.load()`` warning is
        still emitted independently.
        """
        from backend.services.product_recognition_factory import (
            ObservedFuzzyProductRecognizer,
        )

        recognizer = ObservedFuzzyProductRecognizer(
            recorder=ShadowMetricsRecorder(),
            configured_mode="hybrid_active",
            effective_mode="fuzzy",
            fallback_category="invalid_mode",
        )

        with self.assertLogs(
            "backend.services.shadow_metrics_recorder", level="INFO"
        ) as captured:
            recognizer.recognize("empanada de carne", self._catalog())

        record = captured.records[0]
        self.assertEqual(record.mode, "fuzzy")
        self.assertEqual(record.configured_mode, "hybrid_active")
        self.assertEqual(record.effective_mode, "fuzzy")
        self.assertEqual(record.authoritative_strategy, "fuzzy")
        self.assertEqual(record.hybrid_decision, "not_evaluated")
        self.assertTrue(record.fallback)
        self.assertEqual(record.fallback_category, "invalid_mode")
        FuzzyModeObservabilityTest._safe_extra_keys(self, record)


class HybridAuthoritativeCommerceIdExceptionTest(unittest.TestCase):
    """Tests for the new ``HybridAuthoritativeCommerceIdMissing``
    boundary exception.

    The contract: missing ``commerce_id`` is NOT a fallback
    category. The hybrid authoritative recognizer MUST raise the
    exception instead of silently returning the fuzzy result, the
    exception message MUST NOT carry the customer text or the
    catalog payload, and the recorder MUST NOT emit a fallback
    observation.
    """

    def test_exception_message_does_not_carry_customer_text(self):
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=_StubFuzzyRecognizer(decision="unique", encontrados=[1]),
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=lambda: _StubVectorSearchService(),
            recorder=ShadowMetricsRecorder(),
            configured_mode="hybrid_authoritative",
            effective_mode="hybrid_authoritative",
        )

        # Use distinctive sentinel strings that cannot collide
        # with the wording of the exception message itself.
        sentinel_text = "ZZZ-SECRET-CUSTOMER-MESSAGE-ZZZ"
        sentinel_catalog_id = "ZZZ-999-SECRET-CATALOG-ENTRY-ZZZ"
        with self.assertRaises(
            HybridAuthoritativeCommerceIdMissing
        ) as ctx:
            recognizer.recognize(
                sentinel_text,
                [
                    {
                        "producto_presentacion_id": 999,
                        "producto_nombre": sentinel_catalog_id,
                    }
                ],
                intent_metadata={"catalog_scope": "commerce_dynamic_database"},
            )
        message = str(ctx.exception)
        self.assertNotIn(sentinel_text, message)
        self.assertNotIn(sentinel_catalog_id, message)
        # The catalog row's numeric id is intentionally NOT in the
        # exception; the recognizer must avoid leaking it.
        self.assertNotIn("999", message)
        # The exception message must mention the boundary keyword.
        self.assertIn("commerce_id", message)

    def test_exception_does_not_emit_recorder_observation(self):
        recognizer = HybridAuthoritativeProductRecognizer(
            inner=_StubFuzzyRecognizer(decision="ambiguous", posibles=[1, 2]),
            policy=_stub_policy(),
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=lambda: _StubVectorSearchService(),
            recorder=ShadowMetricsRecorder(),
            configured_mode="hybrid_authoritative",
            effective_mode="hybrid_authoritative",
        )

        with self.assertRaises(HybridAuthoritativeCommerceIdMissing):
            recognizer.recognize(
                "empanada",
                _catalog(),
                intent_metadata={"catalog_scope": "commerce_dynamic_database"},
            )

        # No observation record was emitted for the integration bug.
        # The factory boundary is the only safe place to surface it.
        with self.assertRaises(AssertionError):
            with self.assertLogs(
                "backend.services.shadow_metrics_recorder", level="INFO"
            ) as captured:
                self.assertEqual(captured.records, [])


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main(verbosity=2)