"""Focused tests for the 4.10 ``ShadowMetricsRecorder``.

The recorder routes every observation through the single
``backend.observability.events`` shared boundary as the
``shadow_product_recognition`` event belonging to the
``product_recognition`` component. The tests below verify:

- The recorder emits exactly one catalogued event per call and the
  payload round-trips through the catalogue.
- The payload carries the documented safe operational fields
  (configured / effective mode, authoritative strategy, hybrid
  decision, fallback boolean / category, bounded aggregate
  latencies) and never reflects sensitive decision inputs.
- Hybrid ``unique`` / ``ambiguous`` / ``unknown`` are valid
  business observations and never claim a technical fallback.
- Technical fallback is emitted only with the sanitized
  allowlisted categories (``embedding_failure``,
  ``vector_failure``, ``malformed_response``,
  ``unexpected_technical_failure``, ``invalid_mode``); an
  unavailable vector without an explicit category must NOT mark a
  fallback.
- Invalid configured mode is sanitized to ``invalid_mode``.
- The recorder is module-boundary clean: it does NOT import
  FastAPI, HTTP, the embedding client module, the vector search
  service module, the sync service, the admin router, or any
  persistence model. It does NOT commit, rollback, close or begin
  any database session.
- The recorder does NOT emit customer text, raw vectors, prompts,
  exception text, tracebacks or any sensitive identifier.
"""
from __future__ import annotations

import ast
import io
import json
import unittest
from pathlib import Path


def _imports(source: str) -> set[str]:
    tree = ast.parse(source)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module is not None:
                imports.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
    return imports


def _code_without_docstring(source: str) -> str:
    tree = ast.parse(source)
    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        tree.body.pop(0)
        return ast.unparse(tree)
    return source


def _make_comparison(
    *,
    vector_available: bool = True,
    fuzzy_candidate_ids: tuple[int, ...] = (1, 2),
    fuzzy_candidate_scores: tuple[float, ...] = (1.0, 0.8),
    vector_candidate_ids: tuple[int, ...] = (1, 2),
    vector_candidate_scores: tuple[float, ...] = (0.9, 0.7),
    agreement: str = "same_top1",
    fuzzy_best_id: int | None = 1,
    vector_best_id: int | None = 1,
    fuzzy_latency_ms: float = 12.7,
    embedding_latency_ms: float = 200.4,
    vector_latency_ms: float = 15.1,
    failure_category: str | None = None,
    fallback: bool = False,
):
    from backend.services.product_recognition_shadow_comparison import (
        ProductRecognitionShadowComparison,
    )

    return ProductRecognitionShadowComparison(
        fuzzy_best_id=fuzzy_best_id,
        vector_best_id=vector_best_id,
        fuzzy_candidate_ids=fuzzy_candidate_ids,
        vector_candidate_ids=vector_candidate_ids,
        fuzzy_candidate_scores=fuzzy_candidate_scores,
        vector_candidate_scores=vector_candidate_scores,
        agreement=agreement,
        fuzzy_latency_ms=fuzzy_latency_ms,
        embedding_latency_ms=embedding_latency_ms,
        vector_latency_ms=vector_latency_ms,
        vector_available=vector_available,
        failure_category=failure_category,
        fallback=fallback,
    )


def _make_hybrid(*, decision: str = "unique"):
    from backend.services.product_recognition_shadow_comparison import (
        ProductRecognitionHybridObservation,
    )

    return ProductRecognitionHybridObservation(
        hybrid_candidate_ranking=(1, 2),
        hybrid_combined_scores=(0.95, 0.75),
        hybrid_top1_top2_gap=0.2,
        exact_canonical_match=False,
        exact_alias_match=False,
        decision=decision,
        fuzzy_weight=0.5,
        vector_weight=0.5,
        unique_threshold=0.7,
        ambiguous_threshold=0.4,
        min_score_gap=0.05,
        non_authoritative=True,
    )


def _capture_event(recorder_call):
    sink = io.StringIO()
    recorder_call(sink)
    line = sink.getvalue().strip()
    assert line, "recorder did not emit any line"
    return json.loads(line)


class RecorderEmitsCataloguedEventTest(unittest.TestCase):
    def test_record_emits_exactly_one_event(self):
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        recorder = ShadowMetricsRecorder()
        comparison = _make_comparison()
        hybrid = _make_hybrid()

        sink = io.StringIO()
        recorder.record(
            comparison,
            hybrid_observation=hybrid,
            id_comercio=7,
            intent="agregar_producto",
            correlation_id="corr-abc",
            configured_mode="shadow",
            effective_mode="shadow",
            authoritative_strategy="fuzzy",
            stream=sink,
        )
        line = sink.getvalue().strip()
        self.assertEqual(len(line.splitlines()), 1)
        event = json.loads(line)
        self.assertEqual(event["event"], "shadow_product_recognition")
        self.assertEqual(event["component"], "product_recognition")
        self.assertEqual(event["schema_version"], 1)
        self.assertEqual(event["configured_mode"], "shadow")
        self.assertEqual(event["effective_mode"], "shadow")
        self.assertEqual(event["authoritative_strategy"], "fuzzy")
        self.assertEqual(event["hybrid_decision"], "unique")
        self.assertFalse(event["fallback"])
        self.assertEqual(event["fuzzy_latency_ms"], 13)
        self.assertEqual(event["embedding_latency_ms"], 200)
        self.assertEqual(event["vector_latency_ms"], 15)

    def test_recorder_omits_fallback_category_when_no_fallback(self):
        # An unavailable vector without an explicit failure category
        # is a semantic hybrid outcome; the recorder MUST emit
        # ``fallback=false`` and MUST NOT manufacture a fallback
        # category.
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        comparison = _make_comparison(
            vector_available=False,
            vector_best_id=None,
            vector_candidate_ids=(),
            vector_candidate_scores=(),
            vector_latency_ms=0.0,
            failure_category=None,
            fallback=False,
        )
        hybrid = _make_hybrid(decision="unknown")

        event = _capture_event(
            lambda sink: ShadowMetricsRecorder().record(
                comparison,
                hybrid_observation=hybrid,
                id_comercio=1,
                intent=None,
                correlation_id="c",
                configured_mode="shadow",
                effective_mode="shadow",
                authoritative_strategy="fuzzy",
                stream=sink,
            )
        )
        self.assertFalse(event["fallback"])
        self.assertNotIn("fallback_category", event)
        self.assertEqual(event["hybrid_decision"], "unknown")

    def test_recorder_emits_technical_fallback_with_category(self):
        # ``comparison.fallback=True`` plus a sanitized technical
        # ``failure_category`` MUST surface as ``fallback=true`` with
        # the documented ``fallback_category``.
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        comparison = _make_comparison(
            vector_available=False,
            failure_category="embedding_failure",
            fallback=True,
        )
        hybrid = _make_hybrid(decision="unknown")

        event = _capture_event(
            lambda sink: ShadowMetricsRecorder().record(
                comparison,
                hybrid_observation=hybrid,
                id_comercio=1,
                intent=None,
                correlation_id="c",
                configured_mode="hybrid_authoritative",
                effective_mode="hybrid_authoritative",
                authoritative_strategy="hybrid",
                stream=sink,
            )
        )
        self.assertTrue(event["fallback"])
        self.assertEqual(event["fallback_category"], "embedding_failure")
        self.assertEqual(event["hybrid_decision"], "unknown")

    def test_recorder_downgrades_fallback_when_category_unsanitized(self):
        # Defensive: a caller that supplies a non-sanitized fallback
        # category MUST NOT produce ``fallback=true``. The recorder
        # drops the fallback to keep the closed-shape contract.
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        comparison = _make_comparison(
            vector_available=False,
            failure_category="unknown",
            fallback=True,
        )
        hybrid = _make_hybrid(decision="unknown")

        event = _capture_event(
            lambda sink: ShadowMetricsRecorder().record(
                comparison,
                hybrid_observation=hybrid,
                id_comercio=1,
                intent=None,
                correlation_id="c",
                configured_mode="hybrid_authoritative",
                effective_mode="hybrid_authoritative",
                authoritative_strategy="hybrid",
                stream=sink,
            )
        )
        self.assertFalse(event["fallback"])
        self.assertNotIn("fallback_category", event)

    def test_recorder_rounds_latencies_to_bounded_integers(self):
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        comparison = _make_comparison(
            fuzzy_latency_ms=12.49,
            embedding_latency_ms=0.4,
            vector_latency_ms=15.51,
        )
        hybrid = _make_hybrid()

        event = _capture_event(
            lambda sink: ShadowMetricsRecorder().record(
                comparison,
                hybrid_observation=hybrid,
                id_comercio=1,
                intent=None,
                correlation_id="c",
                configured_mode="shadow",
                effective_mode="shadow",
                authoritative_strategy="fuzzy",
                stream=sink,
            )
        )
        self.assertEqual(event["fuzzy_latency_ms"], 12)
        self.assertEqual(event["embedding_latency_ms"], 0)
        self.assertEqual(event["vector_latency_ms"], 16)

    def test_recorder_sanitizes_invalid_configured_mode(self):
        # Operator-typed ``"banana"`` is sanitized to the closed
        # ``invalid_mode`` token; ``effective_mode`` keeps the
        # runtime truth (``fuzzy``) and the fallback is recorded
        # with the ``invalid_mode`` category.
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        comparison = _make_comparison(
            vector_available=False,
            vector_best_id=None,
            vector_candidate_ids=(),
            vector_candidate_scores=(),
            vector_latency_ms=0.0,
            fallback=True,
        )
        hybrid = _make_hybrid(decision="not_evaluated")

        event = _capture_event(
            lambda sink: ShadowMetricsRecorder().record(
                comparison,
                hybrid_observation=hybrid,
                id_comercio=0,
                intent=None,
                correlation_id="",
                configured_mode="banana",
                effective_mode="fuzzy",
                authoritative_strategy="fuzzy",
                fallback_category="invalid_mode",
                mode="fuzzy",
                stream=sink,
            )
        )
        self.assertEqual(event["configured_mode"], "invalid_mode")
        self.assertEqual(event["effective_mode"], "fuzzy")
        self.assertTrue(event["fallback"])
        self.assertEqual(event["fallback_category"], "invalid_mode")
        self.assertEqual(event["hybrid_decision"], "not_evaluated")


class RecorderExcludesSensitiveDataTest(unittest.TestCase):
    def test_recorder_does_not_emit_sensitive_decision_inputs(self):
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        recorder = ShadowMetricsRecorder()
        comparison = _make_comparison()
        hybrid = _make_hybrid()

        sink = io.StringIO()
        recorder.record(
            comparison,
            hybrid_observation=hybrid,
            id_comercio=1,
            intent="agregar_producto",
            correlation_id="c",
            configured_mode="shadow",
            effective_mode="shadow",
            authoritative_strategy="fuzzy",
            stream=sink,
        )
        line = sink.getvalue()
        forbidden = (
            "mensaje-secreto",
            "raw-vector-payload",
            "embedding-prompt",
            "+5491100000000",
            "secret-auth-token-value",
            "AC000000000000000000000000000000",
            "Bearer abc",
            "https://provider.example?token=abc",
            "X-Twilio-Signature=abc",
        )
        for token in forbidden:
            self.assertNotIn(token, line)
        event = json.loads(line.strip())
        self.assertNotIn("id_comercio", event)
        self.assertNotIn("intent", event)
        self.assertNotIn("correlation_id", event)
        self.assertNotIn("fuzzy_best_id", event)
        self.assertNotIn("vector_best_id", event)
        self.assertNotIn("fuzzy_candidate_count", event)
        self.assertNotIn("vector_candidate_count", event)
        self.assertNotIn("fuzzy_candidate_scores", event)
        self.assertNotIn("vector_candidate_scores", event)
        self.assertNotIn("hybrid_candidate_ranking", event)
        self.assertNotIn("hybrid_combined_scores", event)
        self.assertNotIn("hybrid_top1_top2_gap", event)
        self.assertNotIn("exact_canonical_match", event)
        self.assertNotIn("exact_alias_match", event)
        self.assertNotIn("hybrid_fuzzy_weight", event)
        self.assertNotIn("hybrid_vector_weight", event)
        self.assertNotIn("hybrid_unique_threshold", event)
        self.assertNotIn("hybrid_ambiguous_threshold", event)
        self.assertNotIn("hybrid_min_score_gap", event)
        self.assertNotIn("hybrid_non_authoritative", event)
        self.assertNotIn("scores", event)
        self.assertNotIn("intent", event)

    def test_recorder_payload_is_closed_recognition_shape(self):
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        sink = io.StringIO()
        ShadowMetricsRecorder().record(
            _make_comparison(),
            hybrid_observation=_make_hybrid(),
            id_comercio=1,
            intent=None,
            correlation_id="c",
            configured_mode="shadow",
            effective_mode="shadow",
            authoritative_strategy="fuzzy",
            stream=sink,
        )
        event = json.loads(sink.getvalue().strip())
        self.assertEqual(
            set(event.keys()),
            {
                "event",
                "schema_version",
                "component",
                "timestamp",
                "configured_mode",
                "effective_mode",
                "authoritative_strategy",
                "hybrid_decision",
                "fallback",
                "fuzzy_latency_ms",
                "embedding_latency_ms",
                "vector_latency_ms",
            },
        )


class RecorderNoSideEffectsTest(unittest.TestCase):
    def test_recorder_does_not_call_transactions(self):
        from backend.services import shadow_metrics_recorder as recorder_module

        source = Path(recorder_module.__file__).read_text(encoding="utf-8")
        code = _code_without_docstring(source)
        for token in ("commit", "rollback", "close", "begin"):
            with self.subTest(token=token):
                self.assertNotIn(f"session.{token}(", code)

    def test_recorder_does_not_import_forbidden_modules(self):
        from backend.services import shadow_metrics_recorder as recorder_module

        source = Path(recorder_module.__file__).read_text(encoding="utf-8")
        imports = _imports(source)
        forbidden = {
            "fastapi",
            "flask",
            "requests",
            "asyncio",
            "backend.llm",
            "backend.llm.embedding_client",
            "backend.embeddings",
            "backend.embeddings.product_embedding_document_builder",
            "backend.embeddings.text_normalization",
            "backend.services.product_presentation_vector_search_service",
            "backend.services.producto_presentacion_embedding_indexer",
            "backend.services.producto_presentacion_embedding_seeder",
            "backend.services.producto_presentacion_embedding_admin_service",
            "backend.services.catalog_embedding_synchronization_service",
            "backend.routers",
            "backend.routers.admin_product_embeddings",
            "backend.schemas",
            "backend.models",
            "backend.repositories",
        }
        for module in sorted(forbidden):
            with self.subTest(module=module):
                self.assertNotIn(module, imports)

    def test_recorder_routes_through_observability_emitter(self):
        from backend.services import shadow_metrics_recorder as recorder_module

        source = Path(recorder_module.__file__).read_text(encoding="utf-8")
        self.assertIn(
            "backend.observability.events", source
        )
        self.assertIn("emit_event", source)


class RecorderModeArgumentTest(unittest.TestCase):
    def test_fuzzy_mode_emits_not_evaluated(self):
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        comparison = _make_comparison()
        hybrid = _make_hybrid()

        event = _capture_event(
            lambda sink: ShadowMetricsRecorder().record(
                comparison,
                hybrid_observation=hybrid,
                id_comercio=1,
                intent=None,
                correlation_id="c",
                configured_mode="fuzzy",
                effective_mode="fuzzy",
                authoritative_strategy="fuzzy",
                mode="fuzzy",
                stream=sink,
            )
        )
        self.assertEqual(event["configured_mode"], "fuzzy")
        self.assertEqual(event["effective_mode"], "fuzzy")
        self.assertEqual(event["authoritative_strategy"], "fuzzy")
        self.assertEqual(event["hybrid_decision"], "not_evaluated")
        self.assertFalse(event["fallback"])

    def test_shadow_mode_uses_hybrid_decision(self):
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        comparison = _make_comparison()
        hybrid = _make_hybrid(decision="ambiguous")

        event = _capture_event(
            lambda sink: ShadowMetricsRecorder().record(
                comparison,
                hybrid_observation=hybrid,
                id_comercio=1,
                intent=None,
                correlation_id="c",
                configured_mode="shadow",
                effective_mode="shadow",
                authoritative_strategy="fuzzy",
                mode="shadow",
                stream=sink,
            )
        )
        self.assertEqual(event["hybrid_decision"], "ambiguous")
        self.assertEqual(event["authoritative_strategy"], "fuzzy")
        self.assertFalse(event["fallback"])

    def test_hybrid_authoritative_mode_uses_hybrid_strategy(self):
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        comparison = _make_comparison()
        hybrid = _make_hybrid(decision="unknown")

        event = _capture_event(
            lambda sink: ShadowMetricsRecorder().record(
                comparison,
                hybrid_observation=hybrid,
                id_comercio=1,
                intent=None,
                correlation_id="c",
                configured_mode="hybrid_authoritative",
                effective_mode="hybrid_authoritative",
                authoritative_strategy="hybrid",
                mode="hybrid_authoritative",
                stream=sink,
            )
        )
        self.assertEqual(event["authoritative_strategy"], "hybrid")
        self.assertEqual(event["hybrid_decision"], "unknown")
        self.assertFalse(event["fallback"])


class RecorderReadsExplicitFailureCategoryTest(unittest.TestCase):
    def test_recorder_reads_comparison_failure_category(self):
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        comparison = _make_comparison(
            vector_available=False,
            failure_category="embedding_failure",
            fallback=True,
        )
        hybrid = _make_hybrid(decision="unknown")

        event = _capture_event(
            lambda sink: ShadowMetricsRecorder().record(
                comparison,
                hybrid_observation=hybrid,
                id_comercio=1,
                intent=None,
                correlation_id="c",
                configured_mode="hybrid_authoritative",
                effective_mode="hybrid_authoritative",
                authoritative_strategy="hybrid",
                stream=sink,
            )
        )
        self.assertTrue(event["fallback"])
        self.assertEqual(event["fallback_category"], "embedding_failure")


class RecorderCataloguedRoundTripTest(unittest.TestCase):
    def test_emit_event_round_trips_through_catalogue(self) -> None:
        from backend.observability import parse_event
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        sink = io.StringIO()
        ShadowMetricsRecorder().record(
            _make_comparison(),
            hybrid_observation=_make_hybrid(),
            id_comercio=1,
            intent=None,
            correlation_id="c",
            configured_mode="shadow",
            effective_mode="shadow",
            authoritative_strategy="fuzzy",
            stream=sink,
        )
        line = sink.getvalue().strip()
        parsed = parse_event(line)
        self.assertEqual(parsed["event"], "shadow_product_recognition")
        self.assertEqual(parsed["component"], "product_recognition")
        self.assertFalse(parsed["fallback"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
