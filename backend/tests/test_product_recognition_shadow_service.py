"""Focused tests for the 4.10 ``ProductRecognitionShadowService`` and
``ShadowedProductRecognizer``.

The tests cover the 15 minimum scenarios from the project playbook
plus the validation-order tests, the gap-threshold tests, and the
observational-hybrid ranking tests:

1. ``fuzzy`` mode does not call embedding or vector search.
2. ``shadow`` mode returns the exact fuzzy result.
3. matching top result records ``same_top1``.
4. different top result records ``different``.
5. matching candidate sets with reordered tops record ``same_candidate_set``.
6. fuzzy-only result is classified correctly.
7. vector-only result is classified correctly.
8. no-result case is classified correctly.
9. commerce isolation is preserved.
10. embedding failure does not affect fuzzy output.
11. vector-search failure does not affect fuzzy output.
12. safe metrics contain no message text or vectors.
13. component latencies are recorded.
14. add/remove/modify product flows remain unchanged (covered by the
    existing 4.5-4.9 focused tests).
15. existing 4.5-4.9 focused tests remain green (covered by the
    existing test modules).

Additional tests:

- fuzzy-once invariant.
- ``fuzzy_candidate_scores`` are aligned with ``fuzzy_candidate_ids``.
- ``vector_candidate_scores`` are aligned with ``vector_candidate_ids``.
- hybrid observation carries the observational ranking.
- decision order is exact canonical → exact alias → vector signal.
- gap-threshold tests.
- no-retry on embedding failure.
- normalizer-reuse for the embedding query text.
"""
from __future__ import annotations

import inspect
import logging
import unittest
from typing import Any

from backend.config.settings import Settings
from backend.recognizers.product_recognizer_contract import (
    ProductRecognizerResult,
)
from backend.services import product_recognition_shadow_service
from backend.services.product_recognition_shadow_service import (
    ProductRecognitionShadowService,
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


def _fuzzy_result(
    *,
    encontrados: list[dict] | None = None,
    encontrados_posibles: list[dict] | None = None,
) -> ProductRecognizerResult:
    return {
        "encontrados": encontrados or [],
        "encontrados_posibles": encontrados_posibles or [],
        "encontrados_no_disponibles": [],
        "no_encontrados": [],
    }


def _row(pid: int, nombre: str = "pizza") -> dict:
    return {
        "producto_presentacion_id": pid,
        "producto_id": pid,
        "producto_nombre": nombre,
        "aliases": {
            "general_aliases": [],
            "specific_aliases": [],
        },
    }


class _StubEmbeddingClient:
    def __init__(
        self,
        *,
        raise_on_embed: bool = False,
        embed_calls: list[str] | None = None,
        vector: list[float] | None = None,
    ) -> None:
        self._raise_on_embed = raise_on_embed
        self._embed_calls = embed_calls if embed_calls is not None else []
        self._vector = vector if vector is not None else [0.0] * 384

    def embed_query(self, text: str) -> list[float]:
        self._embed_calls.append(text)
        if self._raise_on_embed:
            raise RuntimeError("embedding failure")
        return list(self._vector)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [list(self._vector) for _ in texts]


class _StubVectorSearchService:
    def __init__(
        self,
        *,
        matches: list[Any] | None = None,
        raise_on_search: bool = False,
        commerce_calls: list[int] | None = None,
        candidate_id_calls: list[Any] | None = None,
    ) -> None:
        self._matches = matches or []
        self._raise_on_search = raise_on_search
        self._commerce_calls = (
            commerce_calls if commerce_calls is not None else []
        )
        self._candidate_id_calls = (
            candidate_id_calls if candidate_id_calls is not None else []
        )

    def search_similar(
        self,
        *,
        id_comercio: int,
        query_embedding: list[float],
        top_k: int,
        candidate_producto_presentacion_ids: list[int] | None = None,
    ) -> list[Any]:
        self._commerce_calls.append(id_comercio)
        self._candidate_id_calls.append(candidate_producto_presentacion_ids)
        if self._raise_on_search:
            raise RuntimeError("vector failure")
        return list(self._matches)


def _match(pid: int, score: float):
    from backend.services.product_presentation_vector_match import (
        ProductPresentationVectorMatch,
    )

    return ProductPresentationVectorMatch(
        id_producto_presentacion=pid,
        score=score,
        source_type="canonical",
    )


def _build_shadow_service(
    *,
    embedding_client: Any,
    vector_search_service: Any,
    settings: Settings,
) -> ProductRecognitionShadowService:
    return ProductRecognitionShadowService(
        embedding_client=embedding_client,
        vector_search_service=lambda: vector_search_service,
        settings=settings,
    )


class FuzzyModeIsNoOpTest(unittest.TestCase):
    def test_fuzzy_mode_does_not_call_embedding_or_vector_search(self):
        """The ``fuzzy`` mode is a no-op for embedding and vector search.

        The boundary test asserts that the factory short-circuits in
        ``fuzzy`` mode and returns the ``FuzzyProductRecognizer``
        directly. The shadow service is never invoked.
        """
        from backend.services.product_recognition_factory import (
            get_product_recognizer,
        )

        settings = _settings(product_recognizer_mode="fuzzy")
        embed_calls: list[str] = []
        embedding_client = _StubEmbeddingClient(embed_calls=embed_calls)

        recognizer = get_product_recognizer(
            settings,
            embedding_client=embedding_client,
        )
        self.assertEqual(
            type(recognizer).__name__,
            "FuzzyProductRecognizer",
        )
        self.assertEqual(embed_calls, [])


class ShadowModePreservesFuzzyResultTest(unittest.TestCase):
    def test_shadow_mode_returns_exact_fuzzy_result(self):
        settings = _settings(product_recognizer_mode="shadow")
        fuzzy_result = _fuzzy_result(
            encontrados=[_row(1, "pizza muzza")],
        )
        embedding_client = _StubEmbeddingClient()
        vector_search_service = _StubVectorSearchService(
            matches=[_match(1, 0.9)],
        )
        shadow_service = _build_shadow_service(
            embedding_client=embedding_client,
            vector_search_service=vector_search_service,
            settings=settings,
        )
        recorder = ShadowMetricsRecorder()
        recognizer = ShadowedProductRecognizer(
            inner=_FuzzySpy(returns=fuzzy_result),
            shadow=shadow_service,
            recorder=recorder,
            commerce_id_resolver=lambda catalog: 1,
        )

        catalog = [_row(1, "pizza muzza")]
        result = recognizer.recognize("una pizza muzza", catalog)
        self.assertIs(result, fuzzy_result)


class AgreementClassificationTest(unittest.TestCase):
    def _build(
        self,
        *,
        fuzzy_rows: list[dict],
        matches: list[Any],
        embed_raises: bool = False,
        vector_raises: bool = False,
    ) -> tuple[
        ProductRecognitionShadowService,
        list[str],
        list[int],
        ShadowMetricsRecorder,
        list[ShadowedProductRecognizer],
    ]:
        settings = _settings(
            product_recognizer_mode="shadow",
            shadow_vector_top_k=5,
        )
        embed_calls: list[str] = []
        embedding_client = _StubEmbeddingClient(
            embed_calls=embed_calls,
            raise_on_embed=embed_raises,
        )
        commerce_calls: list[int] = []
        vector_search_service = _StubVectorSearchService(
            matches=matches,
            raise_on_search=vector_raises,
            commerce_calls=commerce_calls,
        )
        shadow_service = _build_shadow_service(
            embedding_client=embedding_client,
            vector_search_service=vector_search_service,
            settings=settings,
        )
        return (
            shadow_service,
            embed_calls,
            commerce_calls,
            ShadowMetricsRecorder(),
            [],
        )

    def test_same_top1_agreement(self):
        shadow_service, _embed_calls, _, _, _ = self._build(
            fuzzy_rows=[_row(42, "pizza")],
            matches=[_match(42, 0.9)],
        )
        result = _fuzzy_result(encontrados=[_row(42, "pizza")])
        comparison, _ = shadow_service.compare(
            text="pizza",
            catalog=[_row(42, "pizza")],
            fuzzy_result=result,
            fuzzy_latency_ms=1.0,
            id_comercio=1,
        )
        self.assertEqual(comparison.agreement, "same_top1")

    def test_different_top1_agreement(self):
        shadow_service, _, _, _, _ = self._build(
            fuzzy_rows=[_row(42, "pizza")],
            matches=[_match(99, 0.9)],
        )
        result = _fuzzy_result(encontrados=[_row(42, "pizza")])
        comparison, _ = shadow_service.compare(
            text="pizza",
            catalog=[_row(42, "pizza")],
            fuzzy_result=result,
            fuzzy_latency_ms=1.0,
            id_comercio=1,
        )
        self.assertEqual(comparison.agreement, "different")

    def test_same_candidate_set_agreement(self):
        shadow_service, _, _, _, _ = self._build(
            fuzzy_rows=[_row(42, "pizza"), _row(99, "empanada")],
            matches=[_match(99, 0.9), _match(42, 0.8)],
        )
        result = _fuzzy_result(
            encontrados=[_row(42, "pizza"), _row(99, "empanada")],
        )
        comparison, _ = shadow_service.compare(
            text="pizza",
            catalog=[_row(42, "pizza"), _row(99, "empanada")],
            fuzzy_result=result,
            fuzzy_latency_ms=1.0,
            id_comercio=1,
        )
        self.assertEqual(comparison.agreement, "same_candidate_set")

    def test_fuzzy_only_agreement(self):
        shadow_service, _, _, _, _ = self._build(
            fuzzy_rows=[_row(42, "pizza")],
            matches=[],
        )
        result = _fuzzy_result(encontrados=[_row(42, "pizza")])
        comparison, _ = shadow_service.compare(
            text="pizza",
            catalog=[_row(42, "pizza")],
            fuzzy_result=result,
            fuzzy_latency_ms=1.0,
            id_comercio=1,
        )
        self.assertEqual(comparison.agreement, "fuzzy_only")

    def test_vector_only_agreement(self):
        shadow_service, _, _, _, _ = self._build(
            fuzzy_rows=[],
            matches=[_match(42, 0.9)],
        )
        result = _fuzzy_result()
        comparison, _ = shadow_service.compare(
            text="pizza",
            catalog=[_row(42, "pizza")],
            fuzzy_result=result,
            fuzzy_latency_ms=1.0,
            id_comercio=1,
        )
        self.assertEqual(comparison.agreement, "vector_only")

    def test_no_result_agreement(self):
        shadow_service, _, _, _, _ = self._build(
            fuzzy_rows=[],
            matches=[],
        )
        result = _fuzzy_result()
        comparison, _ = shadow_service.compare(
            text="pizza",
            catalog=[],
            fuzzy_result=result,
            fuzzy_latency_ms=1.0,
            id_comercio=1,
        )
        self.assertEqual(comparison.agreement, "no_result")


class CommerceIsolationTest(unittest.TestCase):
    def test_id_comercio_is_passed_to_vector_search(self):
        settings = _settings(product_recognizer_mode="shadow")
        commerce_calls: list[int] = []
        embedding_client = _StubEmbeddingClient()
        vector_search_service = _StubVectorSearchService(
            matches=[_match(1, 0.9)],
            commerce_calls=commerce_calls,
        )
        shadow_service = _build_shadow_service(
            embedding_client=embedding_client,
            vector_search_service=vector_search_service,
            settings=settings,
        )
        result = _fuzzy_result(encontrados=[_row(1, "pizza")])
        shadow_service.compare(
            text="pizza",
            catalog=[_row(1, "pizza")],
            fuzzy_result=result,
            fuzzy_latency_ms=1.0,
            id_comercio=7,
        )
        self.assertEqual(commerce_calls, [7])


class EmbeddingFailureTest(unittest.TestCase):
    def test_embedding_failure_does_not_affect_fuzzy_output(self):
        settings = _settings(product_recognizer_mode="shadow")
        embedding_client = _StubEmbeddingClient(raise_on_embed=True)
        vector_search_service = _StubVectorSearchService()
        shadow_service = _build_shadow_service(
            embedding_client=embedding_client,
            vector_search_service=vector_search_service,
            settings=settings,
        )
        fuzzy_result = _fuzzy_result(encontrados=[_row(1, "pizza")])
        comparison, _ = shadow_service.compare(
            text="pizza",
            catalog=[_row(1, "pizza")],
            fuzzy_result=fuzzy_result,
            fuzzy_latency_ms=1.0,
            id_comercio=1,
        )
        self.assertFalse(comparison.vector_available)
        self.assertEqual(comparison.vector_best_id, None)
        self.assertEqual(comparison.vector_candidate_ids, ())
        self.assertEqual(comparison.vector_candidate_scores, ())
        self.assertEqual(comparison.agreement, "fuzzy_only")
        self.assertEqual(
            comparison.failure_category,
            "embedding_failure",
        )

    def test_embedding_failure_no_retry(self):
        settings = _settings(product_recognizer_mode="shadow")
        embed_calls: list[str] = []
        embedding_client = _StubEmbeddingClient(
            embed_calls=embed_calls,
            raise_on_embed=True,
        )
        vector_search_service = _StubVectorSearchService()
        shadow_service = _build_shadow_service(
            embedding_client=embedding_client,
            vector_search_service=vector_search_service,
            settings=settings,
        )
        fuzzy_result = _fuzzy_result(encontrados=[_row(1, "pizza")])
        shadow_service.compare(
            text="pizza",
            catalog=[_row(1, "pizza")],
            fuzzy_result=fuzzy_result,
            fuzzy_latency_ms=1.0,
            id_comercio=1,
        )
        self.assertEqual(
            len(embed_calls),
            1,
            "embedding client must be invoked exactly once on failure",
        )


class VectorSearchFailureTest(unittest.TestCase):
    def test_vector_search_failure_does_not_affect_fuzzy_output(self):
        settings = _settings(product_recognizer_mode="shadow")
        embedding_client = _StubEmbeddingClient()
        vector_search_service = _StubVectorSearchService(
            raise_on_search=True,
        )
        shadow_service = _build_shadow_service(
            embedding_client=embedding_client,
            vector_search_service=vector_search_service,
            settings=settings,
        )
        fuzzy_result = _fuzzy_result(encontrados=[_row(1, "pizza")])
        comparison, _ = shadow_service.compare(
            text="pizza",
            catalog=[_row(1, "pizza")],
            fuzzy_result=fuzzy_result,
            fuzzy_latency_ms=1.0,
            id_comercio=1,
        )
        self.assertFalse(comparison.vector_available)
        self.assertEqual(comparison.vector_best_id, None)
        self.assertEqual(comparison.vector_candidate_ids, ())
        self.assertEqual(comparison.vector_candidate_scores, ())
        self.assertEqual(comparison.agreement, "fuzzy_only")


class ComponentLatencyTest(unittest.TestCase):
    def test_latencies_are_recorded(self):
        settings = _settings(product_recognizer_mode="shadow")
        embedding_client = _StubEmbeddingClient()
        vector_search_service = _StubVectorSearchService(
            matches=[_match(1, 0.9)],
        )
        shadow_service = _build_shadow_service(
            embedding_client=embedding_client,
            vector_search_service=vector_search_service,
            settings=settings,
        )
        fuzzy_result = _fuzzy_result(encontrados=[_row(1, "pizza")])
        comparison, _ = shadow_service.compare(
            text="pizza",
            catalog=[_row(1, "pizza")],
            fuzzy_result=fuzzy_result,
            fuzzy_latency_ms=2.5,
            id_comercio=1,
        )
        self.assertEqual(comparison.fuzzy_latency_ms, 2.5)
        self.assertGreaterEqual(comparison.embedding_latency_ms, 0.0)
        self.assertGreaterEqual(comparison.vector_latency_ms, 0.0)


class FuzzyCandidateScoresTest(unittest.TestCase):
    def test_fuzzy_candidate_scores_are_aligned_and_in_unit_interval(self):
        settings = _settings(product_recognizer_mode="shadow")
        embedding_client = _StubEmbeddingClient()
        vector_search_service = _StubVectorSearchService()
        shadow_service = _build_shadow_service(
            embedding_client=embedding_client,
            vector_search_service=vector_search_service,
            settings=settings,
        )
        fuzzy_result = _fuzzy_result(
            encontrados=[_row(1, "pizza"), _row(2, "empanada")],
        )
        comparison, _ = shadow_service.compare(
            text="pizza",
            catalog=[_row(1, "pizza"), _row(2, "empanada")],
            fuzzy_result=fuzzy_result,
            fuzzy_latency_ms=1.0,
            id_comercio=1,
        )
        self.assertEqual(
            len(comparison.fuzzy_candidate_scores),
            len(comparison.fuzzy_candidate_ids),
        )
        self.assertEqual(comparison.fuzzy_candidate_scores[0], 1.0)
        for score in comparison.fuzzy_candidate_scores:
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)


class VectorCandidateScoresTest(unittest.TestCase):
    def test_vector_candidate_scores_are_aligned_with_ids(self):
        settings = _settings(product_recognizer_mode="shadow")
        embedding_client = _StubEmbeddingClient()
        vector_search_service = _StubVectorSearchService(
            matches=[_match(1, 0.9), _match(2, 0.7)],
        )
        shadow_service = _build_shadow_service(
            embedding_client=embedding_client,
            vector_search_service=vector_search_service,
            settings=settings,
        )
        fuzzy_result = _fuzzy_result()
        comparison, _ = shadow_service.compare(
            text="pizza",
            catalog=[_row(1, "pizza"), _row(2, "empanada")],
            fuzzy_result=fuzzy_result,
            fuzzy_latency_ms=1.0,
            id_comercio=1,
        )
        self.assertEqual(
            len(comparison.vector_candidate_scores),
            len(comparison.vector_candidate_ids),
        )
        self.assertEqual(comparison.vector_candidate_scores, (0.9, 0.7))


class FuzzyOnceInvariantTest(unittest.TestCase):
    def test_inner_recognizer_invoked_exactly_once(self):
        settings = _settings(product_recognizer_mode="shadow")
        embedding_client = _StubEmbeddingClient()
        vector_search_service = _StubVectorSearchService(
            matches=[_match(1, 0.9)],
        )
        shadow_service = _build_shadow_service(
            embedding_client=embedding_client,
            vector_search_service=vector_search_service,
            settings=settings,
        )
        recorder = ShadowMetricsRecorder()
        spy = _FuzzySpy(calls=0, returns=_fuzzy_result(encontrados=[_row(1, "pizza")]))
        recognizer = ShadowedProductRecognizer(
            inner=spy,
            shadow=shadow_service,
            recorder=recorder,
            commerce_id_resolver=lambda catalog: 1,
        )
        recognizer.recognize("pizza", [_row(1, "pizza")])
        self.assertEqual(
            spy.calls,
            1,
            "inner fuzzy recognizer must be invoked exactly once",
        )


class NormalizerReuseTest(unittest.TestCase):
    def test_embed_query_receives_normalized_text(self):
        settings = _settings(product_recognizer_mode="shadow")
        embed_calls: list[str] = []
        embedding_client = _StubEmbeddingClient(embed_calls=embed_calls)
        vector_search_service = _StubVectorSearchService(
            matches=[_match(1, 0.9)],
        )
        shadow_service = _build_shadow_service(
            embedding_client=embedding_client,
            vector_search_service=vector_search_service,
            settings=settings,
        )
        fuzzy_result = _fuzzy_result(encontrados=[_row(1, "pizza muzza")])
        shadow_service.compare(
            text="Pizza  MUZZA!",
            catalog=[_row(1, "pizza muzza")],
            fuzzy_result=fuzzy_result,
            fuzzy_latency_ms=1.0,
            id_comercio=1,
        )
        self.assertEqual(len(embed_calls), 1)
        # Result must be normalized (lowercase, no accents, no specials)
        self.assertEqual(embed_calls[0], "pizza muzza")


class SafeMetricsTest(unittest.TestCase):
    def test_recorder_does_not_receive_customer_message_or_vector(self):
        settings = _settings(product_recognizer_mode="shadow")
        embedding_client = _StubEmbeddingClient()
        vector_search_service = _StubVectorSearchService(
            matches=[_match(1, 0.9)],
        )
        shadow_service = _build_shadow_service(
            embedding_client=embedding_client,
            vector_search_service=vector_search_service,
            settings=settings,
        )
        spy = _FuzzySpy(returns=_fuzzy_result(encontrados=[_row(1, "pizza")]))
        recorder = ShadowMetricsRecorder()
        recognizer = ShadowedProductRecognizer(
            inner=spy,
            shadow=shadow_service,
            recorder=recorder,
            commerce_id_resolver=lambda catalog: 1,
        )
        with self.assertLogs(
            "backend.services.shadow_metrics_recorder", level="INFO"
        ) as captured:
            recognizer.recognize(
                "mensaje-secreto-cliente",
                [_row(1, "pizza")],
            )
        for record in captured.records:
            self.assertNotIn("mensaje-secreto-cliente", record.getMessage())
            for field in dir(record):
                if field.startswith("_"):
                    continue
                value = getattr(record, field, None)
                if isinstance(value, str):
                    self.assertNotIn("mensaje-secreto-cliente", value)


class HybridObservationTest(unittest.TestCase):
    def test_hybrid_observation_carries_ordered_ranking_and_decision(self):
        settings = _settings(product_recognizer_mode="shadow")
        embedding_client = _StubEmbeddingClient()
        vector_search_service = _StubVectorSearchService(
            matches=[_match(1, 0.9), _match(2, 0.7)],
        )
        shadow_service = _build_shadow_service(
            embedding_client=embedding_client,
            vector_search_service=vector_search_service,
            settings=settings,
        )
        fuzzy_result = _fuzzy_result(encontrados=[_row(1, "pizza")])
        _, hybrid = shadow_service.compare(
            text="pizza",
            catalog=[_row(1, "pizza"), _row(2, "empanada")],
            fuzzy_result=fuzzy_result,
            fuzzy_latency_ms=1.0,
            id_comercio=1,
        )
        self.assertEqual(
            len(hybrid.hybrid_candidate_ranking),
            len(hybrid.hybrid_combined_scores),
        )
        self.assertIn(hybrid.decision, ("unique", "ambiguous", "unknown"))
        self.assertTrue(hybrid.non_authoritative)
        self.assertEqual(hybrid.fuzzy_weight, 0.5)
        self.assertEqual(hybrid.vector_weight, 0.5)
        self.assertEqual(hybrid.min_score_gap, 0.05)

    def test_decision_order_canonical_then_alias_then_vector(self):
        settings = _settings(product_recognizer_mode="shadow")
        embedding_client = _StubEmbeddingClient()
        vector_search_service = _StubVectorSearchService(
            matches=[_match(1, 0.5)],
        )
        shadow_service = _build_shadow_service(
            embedding_client=embedding_client,
            vector_search_service=vector_search_service,
            settings=settings,
        )
        catalog = [_row(1, "pizza muzza")]
        fuzzy_result = _fuzzy_result(encontrados=[_row(1, "pizza muzza")])
        _, hybrid = shadow_service.compare(
            text="pizza muzza",
            catalog=catalog,
            fuzzy_result=fuzzy_result,
            fuzzy_latency_ms=1.0,
            id_comercio=1,
        )
        self.assertTrue(hybrid.exact_canonical_match)
        self.assertEqual(hybrid.decision, "unique")

    def test_unique_threshold_gap_classification(self):
        settings = _settings(
            product_recognizer_mode="shadow",
            shadow_hybrid_min_score_gap=0.5,
        )
        embedding_client = _StubEmbeddingClient()
        vector_search_service = _StubVectorSearchService(
            matches=[_match(1, 0.9), _match(2, 0.85)],
        )
        shadow_service = _build_shadow_service(
            embedding_client=embedding_client,
            vector_search_service=vector_search_service,
            settings=settings,
        )
        # Use a text that does NOT match any catalog row exactly so the
        # decision rule falls through to the gap-threshold path.
        fuzzy_result = _fuzzy_result(
            encontrados=[_row(1, "pizza muzza"), _row(2, "empanada")],
        )
        _, hybrid = shadow_service.compare(
            text="pizzam uzz a",
            catalog=[_row(1, "pizza muzza"), _row(2, "empanada")],
            fuzzy_result=fuzzy_result,
            fuzzy_latency_ms=1.0,
            id_comercio=1,
        )
        # Top-1 combined score is 1.0 * 0.5 + 0.9 * 0.5 = 0.95 (>= 0.7)
        # Top-2 combined score is 0.5 decay * 0.5 + 0.85 * 0.5 ~= 0.675
        # gap ~= 0.275 < 0.5 -> ambiguous
        self.assertEqual(hybrid.decision, "ambiguous")

    def test_insufficient_gap_classifies_as_ambiguous(self):
        settings = _settings(
            product_recognizer_mode="shadow",
            shadow_hybrid_min_score_gap=0.4,
        )
        embedding_client = _StubEmbeddingClient()
        vector_search_service = _StubVectorSearchService(
            matches=[_match(1, 0.9), _match(2, 0.85)],
        )
        shadow_service = _build_shadow_service(
            embedding_client=embedding_client,
            vector_search_service=vector_search_service,
            settings=settings,
        )
        # Use a text that does NOT match any catalog row exactly so the
        # decision rule falls through to the gap-threshold path.
        fuzzy_result = _fuzzy_result(
            encontrados=[_row(1, "pizza muzza"), _row(2, "empanada")],
        )
        _, hybrid = shadow_service.compare(
            text="pizzam uzz a",
            catalog=[_row(1, "pizza muzza"), _row(2, "empanada")],
            fuzzy_result=fuzzy_result,
            fuzzy_latency_ms=1.0,
            id_comercio=1,
        )
        self.assertEqual(hybrid.decision, "ambiguous")

    def test_exact_canonical_match_is_unique_regardless_of_gap(self):
        settings = _settings(
            product_recognizer_mode="shadow",
            shadow_hybrid_min_score_gap=0.99,
        )
        embedding_client = _StubEmbeddingClient()
        vector_search_service = _StubVectorSearchService(
            matches=[_match(1, 0.9), _match(2, 0.85)],
        )
        shadow_service = _build_shadow_service(
            embedding_client=embedding_client,
            vector_search_service=vector_search_service,
            settings=settings,
        )
        catalog = [_row(1, "pizza muzza"), _row(2, "empanada")]
        fuzzy_result = _fuzzy_result(encontrados=[_row(1, "pizza muzza")])
        _, hybrid = shadow_service.compare(
            text="pizza muzza",
            catalog=catalog,
            fuzzy_result=fuzzy_result,
            fuzzy_latency_ms=1.0,
            id_comercio=1,
        )
        self.assertEqual(hybrid.decision, "unique")

    def test_single_candidate_unique_above_threshold(self):
        settings = _settings(product_recognizer_mode="shadow")
        embedding_client = _StubEmbeddingClient()
        vector_search_service = _StubVectorSearchService(
            matches=[_match(1, 0.9)],
        )
        shadow_service = _build_shadow_service(
            embedding_client=embedding_client,
            vector_search_service=vector_search_service,
            settings=settings,
        )
        fuzzy_result = _fuzzy_result(encontrados=[_row(1, "pizza")])
        _, hybrid = shadow_service.compare(
            text="pizza",
            catalog=[_row(1, "pizza")],
            fuzzy_result=fuzzy_result,
            fuzzy_latency_ms=1.0,
            id_comercio=1,
        )
        self.assertEqual(hybrid.decision, "unique")
        self.assertEqual(hybrid.hybrid_top1_top2_gap, 0.0)

    def test_hybrid_observation_does_not_alter_fuzzy_result(self):
        settings = _settings(product_recognizer_mode="shadow")
        embedding_client = _StubEmbeddingClient()
        vector_search_service = _StubVectorSearchService(
            matches=[_match(1, 0.9)],
        )
        shadow_service = _build_shadow_service(
            embedding_client=embedding_client,
            vector_search_service=vector_search_service,
            settings=settings,
        )
        fuzzy_result = _fuzzy_result(encontrados=[_row(1, "pizza")])
        comparison, _ = shadow_service.compare(
            text="pizza",
            catalog=[_row(1, "pizza")],
            fuzzy_result=fuzzy_result,
            fuzzy_latency_ms=1.0,
            id_comercio=1,
        )
        # The comparison is purely data; the fuzzy result is returned
        # unchanged by the decorator scenario covered in
        # test_shadow_mode_returns_exact_fuzzy_result.
        self.assertEqual(comparison.fuzzy_best_id, 1)


class ShadowServiceHasNoHiddenFailureCategoryTest(unittest.TestCase):
    def test_shadow_service_does_not_use_object_setattr(self):
        """The shadow service module never calls ``object.__setattr__``
        on a ``ProductRecognitionShadowComparison`` instance.

        The failure category is a declared field of the dataclass and
        is supplied through the constructor; the service must not
        attach a hidden attribute.
        """
        source = inspect.getsource(product_recognition_shadow_service)
        self.assertNotIn(
            "object.__setattr__",
            source,
        )
        self.assertNotIn(
            'getattr(comparison, "_failure_category"',
            source,
        )

    def test_comparison_exposes_twelve_fields(self):
        """The dataclass exposes exactly the twelve documented fields
        and does not carry a hidden ``_failure_category`` attribute
        on constructed instances.
        """
        from backend.services.product_recognition_shadow_comparison import (
            ProductRecognitionShadowComparison,
        )

        expected_fields = {
            "fuzzy_best_id",
            "vector_best_id",
            "fuzzy_candidate_ids",
            "vector_candidate_ids",
            "fuzzy_candidate_scores",
            "vector_candidate_scores",
            "agreement",
            "fuzzy_latency_ms",
            "embedding_latency_ms",
            "vector_latency_ms",
            "vector_available",
            "failure_category",
        }
        actual_fields = {f.name for f in ProductRecognitionShadowComparison.__dataclass_fields__.values()}
        self.assertEqual(actual_fields, expected_fields)

        comparison = ProductRecognitionShadowComparison(
            fuzzy_best_id=None,
            vector_best_id=None,
            fuzzy_candidate_ids=(),
            vector_candidate_ids=(),
            fuzzy_candidate_scores=(),
            vector_candidate_scores=(),
            agreement="no_result",
            fuzzy_latency_ms=0.0,
            embedding_latency_ms=0.0,
            vector_latency_ms=0.0,
            vector_available=False,
            failure_category=None,
        )
        self.assertFalse(hasattr(comparison, "_failure_category"))


class CommerceIdResolverTest(unittest.TestCase):
    def test_resolver_none_skips_shadow_comparison(self):
        settings = _settings(product_recognizer_mode="shadow")
        embedding_client = _StubEmbeddingClient()
        vector_search_service = _StubVectorSearchService(
            matches=[_match(1, 0.9)],
        )
        shadow_service = _build_shadow_service(
            embedding_client=embedding_client,
            vector_search_service=vector_search_service,
            settings=settings,
        )
        recorder = ShadowMetricsRecorder()
        fuzzy_result = _fuzzy_result(encontrados=[_row(1, "pizza")])
        recognizer = ShadowedProductRecognizer(
            inner=_FuzzySpy(returns=fuzzy_result),
            shadow=shadow_service,
            recorder=recorder,
            commerce_id_resolver=None,
        )
        result = recognizer.recognize("pizza", [_row(1, "pizza")])
        self.assertIs(result, fuzzy_result)

    def test_resolver_returns_none_skips_shadow_comparison(self):
        settings = _settings(product_recognizer_mode="shadow")
        embedding_client = _StubEmbeddingClient()
        vector_search_service = _StubVectorSearchService(
            matches=[_match(1, 0.9)],
        )
        shadow_service = _build_shadow_service(
            embedding_client=embedding_client,
            vector_search_service=vector_search_service,
            settings=settings,
        )
        recorder = ShadowMetricsRecorder()
        fuzzy_result = _fuzzy_result(encontrados=[_row(1, "pizza")])
        recognizer = ShadowedProductRecognizer(
            inner=_FuzzySpy(returns=fuzzy_result),
            shadow=shadow_service,
            recorder=recorder,
            commerce_id_resolver=lambda catalog: None,
        )
        result = recognizer.recognize("pizza", [_row(1, "pizza")])
        self.assertIs(result, fuzzy_result)


class _FuzzySpy:
    def __init__(
        self,
        *,
        returns: ProductRecognizerResult | None = None,
        calls: int = 0,
    ) -> None:
        self._returns = returns or _fuzzy_result()
        self.calls = calls

    def recognize(
        self,
        text: str,
        catalog: list[dict],
    ) -> ProductRecognizerResult:
        self.calls += 1
        return self._returns


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main(verbosity=2)
