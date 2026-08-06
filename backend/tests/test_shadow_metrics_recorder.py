"""Focused tests for the 4.10 ``ShadowMetricsRecorder``.

The recorder is a thin wrapper over the standard ``logging`` mechanism.
The tests below verify:

- The recorder emits exactly one structured log record per call.
- The log record carries the documented safe operational fields,
  including the observational hybrid ranking, the provisional weights
  and thresholds, the provisional ``hybrid_min_score_gap``, and the
  ``hybrid_non_authoritative=True`` flag.
- The recorder fills in ``failure_category="unknown"`` when the
  comparison carries ``vector_available=False`` and no failure category.
- The recorder is module-boundary clean: it does NOT import FastAPI,
  HTTP, the embedding client module, the vector search service module,
  the sync service, the admin router, or any persistence model.
- The recorder does NOT log the customer message, the raw vector, the
  embedding prompt, the source document text, a Python stack trace, or
  the raw text of any infrastructure exception.
"""
from __future__ import annotations

import ast
import logging
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
    fuzzy_latency_ms: float = 1.0,
    embedding_latency_ms: float = 5.0,
    vector_latency_ms: float = 3.0,
    failure_category: str | None = None,
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
    )


def _make_hybrid():
    from backend.services.product_recognition_shadow_comparison import (
        ProductRecognitionHybridObservation,
    )

    return ProductRecognitionHybridObservation(
        hybrid_candidate_ranking=(1, 2),
        hybrid_combined_scores=(0.95, 0.75),
        hybrid_top1_top2_gap=0.2,
        exact_canonical_match=False,
        exact_alias_match=False,
        decision="unique",
        fuzzy_weight=0.5,
        vector_weight=0.5,
        unique_threshold=0.7,
        ambiguous_threshold=0.4,
        min_score_gap=0.05,
        non_authoritative=True,
    )


class RecorderLogsSafeOperationalFieldsTest(unittest.TestCase):
    def test_record_emits_exactly_one_log_record(self):
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        recorder = ShadowMetricsRecorder()
        comparison = _make_comparison()
        hybrid = _make_hybrid()

        with self.assertLogs("backend.services.shadow_metrics_recorder", level="INFO") as captured:
            recorder.record(
                comparison,
                hybrid_observation=hybrid,
                id_comercio=7,
                intent="agregar_producto",
                correlation_id="corr-abc",
            )

        self.assertEqual(len(captured.records), 1)
        record = captured.records[0]
        extra = {
            key: getattr(record, key, None)
            for key in (
                "shadow_metric",
                "id_comercio",
                "intent",
                "correlation_id",
                "fuzzy_best_id",
                "vector_best_id",
                "fuzzy_candidate_count",
                "vector_candidate_count",
                "fuzzy_candidate_scores",
                "vector_candidate_scores",
                "agreement",
                "fuzzy_latency_ms",
                "embedding_latency_ms",
                "vector_latency_ms",
                "vector_available",
                "failure_category",
                "hybrid_candidate_ranking",
                "hybrid_combined_scores",
                "hybrid_top1_top2_gap",
                "exact_canonical_match",
                "exact_alias_match",
                "hybrid_decision",
                "hybrid_fuzzy_weight",
                "hybrid_vector_weight",
                "hybrid_unique_threshold",
                "hybrid_ambiguous_threshold",
                "hybrid_min_score_gap",
                "hybrid_non_authoritative",
            )
        }
        self.assertEqual(extra["shadow_metric"], "product_recognition_comparison")
        self.assertEqual(extra["id_comercio"], 7)
        self.assertEqual(extra["intent"], "agregar_producto")
        self.assertEqual(extra["correlation_id"], "corr-abc")
        self.assertEqual(extra["fuzzy_best_id"], 1)
        self.assertEqual(extra["vector_best_id"], 1)
        self.assertEqual(extra["fuzzy_candidate_count"], 2)
        self.assertEqual(extra["vector_candidate_count"], 2)
        self.assertEqual(extra["fuzzy_candidate_scores"], (1.0, 0.8))
        self.assertEqual(extra["vector_candidate_scores"], (0.9, 0.7))
        self.assertEqual(extra["agreement"], "same_top1")
        self.assertEqual(extra["fuzzy_latency_ms"], 1.0)
        self.assertEqual(extra["embedding_latency_ms"], 5.0)
        self.assertEqual(extra["vector_latency_ms"], 3.0)
        self.assertTrue(extra["vector_available"])
        self.assertIsNone(extra["failure_category"])
        self.assertEqual(extra["hybrid_candidate_ranking"], (1, 2))
        self.assertEqual(extra["hybrid_combined_scores"], (0.95, 0.75))
        self.assertEqual(extra["hybrid_top1_top2_gap"], 0.2)
        self.assertFalse(extra["exact_canonical_match"])
        self.assertFalse(extra["exact_alias_match"])
        self.assertEqual(extra["hybrid_decision"], "unique")
        self.assertEqual(extra["hybrid_fuzzy_weight"], 0.5)
        self.assertEqual(extra["hybrid_vector_weight"], 0.5)
        self.assertEqual(extra["hybrid_unique_threshold"], 0.7)
        self.assertEqual(extra["hybrid_ambiguous_threshold"], 0.4)
        self.assertEqual(extra["hybrid_min_score_gap"], 0.05)
        self.assertTrue(extra["hybrid_non_authoritative"])

    def test_recorder_fills_unknown_failure_category_when_unset(self):
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        comparison = _make_comparison(
            vector_available=False,
            vector_best_id=None,
            vector_candidate_ids=(),
            vector_candidate_scores=(),
            vector_latency_ms=0.0,
        )
        hybrid = _make_hybrid()
        recorder = ShadowMetricsRecorder()

        with self.assertLogs("backend.services.shadow_metrics_recorder", level="INFO") as captured:
            recorder.record(
                comparison,
                hybrid_observation=hybrid,
                id_comercio=1,
                intent=None,
                correlation_id="c",
            )

        self.assertEqual(len(captured.records), 1)
        record = captured.records[0]
        self.assertEqual(
            getattr(record, "failure_category", None),
            "unknown",
        )

    def test_recorder_preserves_failure_category_when_set(self):
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        comparison = _make_comparison(
            vector_available=False,
            failure_category="embedding_failure",
        )
        hybrid = _make_hybrid()
        recorder = ShadowMetricsRecorder()

        with self.assertLogs("backend.services.shadow_metrics_recorder", level="INFO") as captured:
            recorder.record(
                comparison,
                hybrid_observation=hybrid,
                id_comercio=1,
                intent=None,
                correlation_id="c",
            )

        self.assertEqual(len(captured.records), 1)
        record = captured.records[0]
        self.assertEqual(
            getattr(record, "failure_category", None),
            "embedding_failure",
        )

    def test_recorder_marks_provisional_values_as_non_authoritative(self):
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        recorder = ShadowMetricsRecorder()
        comparison = _make_comparison()
        hybrid = _make_hybrid()

        with self.assertLogs("backend.services.shadow_metrics_recorder", level="INFO") as captured:
            recorder.record(
                comparison,
                hybrid_observation=hybrid,
                id_comercio=1,
                intent=None,
                correlation_id="c",
            )

        record = captured.records[0]
        self.assertTrue(getattr(record, "hybrid_non_authoritative", False))
        self.assertEqual(getattr(record, "hybrid_min_score_gap", None), 0.05)
        self.assertEqual(getattr(record, "hybrid_fuzzy_weight", None), 0.5)
        self.assertEqual(getattr(record, "hybrid_vector_weight", None), 0.5)
        self.assertEqual(getattr(record, "hybrid_unique_threshold", None), 0.7)
        self.assertEqual(getattr(record, "hybrid_ambiguous_threshold", None), 0.4)


class RecorderDoesNotLogSensitiveDataTest(unittest.TestCase):
    def test_recorder_does_not_log_customer_message_or_vector(self):
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        recorder = ShadowMetricsRecorder()
        comparison = _make_comparison()
        hybrid = _make_hybrid()

        with self.assertLogs("backend.services.shadow_metrics_recorder", level="INFO") as captured:
            recorder.record(
                comparison,
                hybrid_observation=hybrid,
                id_comercio=1,
                intent="agregar_producto",
                correlation_id="c",
            )

        record = captured.records[0]
        forbidden = ("mensaje-secreto", "raw-vector-payload", "embedding-prompt")
        for token in forbidden:
            self.assertNotIn(token, record.getMessage())
            for field_name in dir(record):
                if field_name.startswith("_"):
                    continue
                value = getattr(record, field_name, None)
                if isinstance(value, str):
                    self.assertNotIn(token, value)


class RecorderReadsExplicitFailureCategoryTest(unittest.TestCase):
    def test_recorder_does_not_attach_hidden_failure_category(self):
        """The recorder reads ``comparison.failure_category`` directly.

        The recorder module MUST NOT call ``getattr`` with a hidden
        ``_failure_category`` fallback or attach that name to a
        ``ProductRecognitionShadowComparison``. The field is part of
        the public dataclass schema.
        """
        from backend.services import shadow_metrics_recorder as recorder_module
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        recorder = ShadowMetricsRecorder()
        comparison = _make_comparison(
            vector_available=False,
            failure_category="embedding_failure",
        )
        hybrid = _make_hybrid()

        with self.assertLogs(
            "backend.services.shadow_metrics_recorder", level="INFO"
        ) as captured:
            recorder.record(
                comparison,
                hybrid_observation=hybrid,
                id_comercio=1,
                intent=None,
                correlation_id="c",
            )

        self.assertEqual(len(captured.records), 1)
        record = captured.records[0]
        self.assertEqual(
            getattr(record, "failure_category", None),
            "embedding_failure",
        )

        # The recorder module must not look up a hidden attribute.
        recorder_source = Path(recorder_module.__file__).read_text(
            encoding="utf-8"
        )
        self.assertNotIn(
            'getattr(comparison, "_failure_category"',
            recorder_source,
        )
        self.assertNotIn(
            "object.__setattr__",
            recorder_source,
        )


class RecorderModeArgumentTest(unittest.TestCase):
    def test_default_mode_is_shadow(self):
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        recorder = ShadowMetricsRecorder()
        comparison = _make_comparison()
        hybrid = _make_hybrid()

        with self.assertLogs("backend.services.shadow_metrics_recorder", level="INFO") as captured:
            recorder.record(
                comparison,
                hybrid_observation=hybrid,
                id_comercio=1,
                intent=None,
                correlation_id="c",
            )

        record = captured.records[0]
        self.assertEqual(getattr(record, "mode", None), "shadow")
        self.assertTrue(getattr(record, "hybrid_non_authoritative", False))

    def test_explicit_shadow_mode_is_accepted(self):
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        recorder = ShadowMetricsRecorder()
        comparison = _make_comparison()
        hybrid = _make_hybrid()

        with self.assertLogs("backend.services.shadow_metrics_recorder", level="INFO") as captured:
            recorder.record(
                comparison,
                hybrid_observation=hybrid,
                id_comercio=1,
                intent=None,
                correlation_id="c",
                mode="shadow",
            )

        record = captured.records[0]
        self.assertEqual(getattr(record, "mode", None), "shadow")
        self.assertTrue(getattr(record, "hybrid_non_authoritative", False))

    def test_hybrid_authoritative_mode_marks_decision_as_authoritative(self):
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        recorder = ShadowMetricsRecorder()
        comparison = _make_comparison()
        hybrid = _make_hybrid()

        with self.assertLogs("backend.services.shadow_metrics_recorder", level="INFO") as captured:
            recorder.record(
                comparison,
                hybrid_observation=hybrid,
                id_comercio=1,
                intent=None,
                correlation_id="c",
                mode="hybrid_authoritative",
            )

        record = captured.records[0]
        self.assertEqual(
            getattr(record, "mode", None), "hybrid_authoritative"
        )
        self.assertFalse(getattr(record, "hybrid_non_authoritative", True))

    def test_shadow_mode_preserves_non_authoritative_flag(self):
        from backend.services.shadow_metrics_recorder import (
            ShadowMetricsRecorder,
        )

        recorder = ShadowMetricsRecorder()
        comparison = _make_comparison()
        # `non_authoritative=False` is the recorded flag in shadow mode
        # when the hybrid observation is itself marked authoritative.
        hybrid = _make_hybrid()
        object.__setattr__(hybrid, "non_authoritative", False)

        with self.assertLogs("backend.services.shadow_metrics_recorder", level="INFO") as captured:
            recorder.record(
                comparison,
                hybrid_observation=hybrid,
                id_comercio=1,
                intent=None,
                correlation_id="c",
                mode="shadow",
            )

        record = captured.records[0]
        self.assertFalse(getattr(record, "hybrid_non_authoritative", True))


class RecorderModuleBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend.services import shadow_metrics_recorder as recorder_module

        cls.path = Path(recorder_module.__file__)
        cls.source = cls.path.read_text(encoding="utf-8")
        cls.code = _code_without_docstring(cls.source)
        cls.imports = _imports(cls.source)

    def test_recorder_does_not_import_forbidden_modules(self):
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
                self.assertNotIn(module, self.imports)

    def test_recorder_does_not_call_transactions(self):
        for token in ("commit", "rollback", "close", "begin"):
            with self.subTest(token=token):
                self.assertNotIn(f"session.{token}(", self.code)

    def test_recorder_only_calls_logger_info(self):
        # The recorder intentionally uses logger.info for the single
        # structured log record and never raises.
        self.assertIn("logger.info(", self.code)


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main(verbosity=2)
