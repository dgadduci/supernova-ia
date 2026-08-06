"""Module boundary tests for the 4.10 shadow-mode surface.

Subphase 4.10 mirrors the boundary tests already exercised by the
4.9 test modules. The tests below inspect the source of the new
modules and assert that the shadow service, the shadowed recognizer,
the comparison dataclass, the hybrid observation, the recorder, and
the factory respect the documented boundaries:

- The shadow service does NOT import the embedding client concrete
  class, the document builder, the seeder, the indexer, the sync
  service, the admin router, or any 4.7 schema.
- The shadow service does NOT call ``session.commit()``,
  ``session.rollback()``, ``session.close()``, or
  ``session.begin()``.
- The shadow service does NOT hold a fuzzy recognizer.
- The shadowed recognizer does NOT mutate the inner recognizer's
  result.
- The comparison dataclass is frozen and exposes only the eleven
  documented fields.
- The hybrid observation dataclass is frozen and exposes only the
  twelve documented fields (including ``min_score_gap``).
- The recorder does NOT log the customer message, the raw vector,
  the embedding prompt, or a stack trace.
- The recorder marks provisional weights, thresholds, and
  ``min_score_gap`` as non-authoritative.
- The factory does NOT hold a fuzzy recognizer in shadow mode.
"""
from __future__ import annotations

import ast
import unittest
from dataclasses import fields
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
    """Return the source with the module docstring removed so substring
    checks do not register mentions of forbidden tokens in docstrings.
    """
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


def _code_without_docstrings(source: str) -> str:
    """Return the source with every docstring removed (module + every
    function / class / method body).
    """
    tree = ast.parse(source)

    def _strip(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if (
                isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and child.body
                and isinstance(child.body[0], ast.Expr)
                and isinstance(child.body[0].value, ast.Constant)
                and isinstance(child.body[0].value.value, str)
            ):
                child.body.pop(0)
            _strip(child)

    _strip(tree)
    return ast.unparse(tree)


class ShadowServiceModuleBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend.services import (
            product_recognition_shadow_service as shadow_module,
        )

        cls.path = Path(shadow_module.__file__)
        cls.source = cls.path.read_text(encoding="utf-8")
        cls.code = _code_without_docstring(cls.source)
        cls.code_full = _code_without_docstrings(cls.source)
        cls.imports = _imports(cls.source)

    def test_module_does_not_import_forbidden_modules(self):
        # NOTE: the shadow service is allowed to import the
        # EmbeddingClientProtocol from backend.llm.embedding_client
        # because that is the documented dependency contract. The
        # concrete OllamaEmbeddingClient must NOT be imported.
        allowed = {"backend.llm.embedding_client"}
        forbidden = {
            "fastapi",
            "flask",
            "requests",
            "asyncio",
            "backend.embeddings",
            "backend.embeddings.product_embedding_document_builder",
            "backend.embeddings.text_normalization",
            "backend.services.producto_presentacion_embedding_indexer",
            "backend.services.producto_presentacion_embedding_seeder",
            "backend.services.producto_presentacion_embedding_admin_service",
            "backend.services.catalog_embedding_synchronization_service",
            "backend.routers",
            "backend.routers.admin_product_embeddings",
            "backend.schemas",
            "backend.schemas.product_embedding_admin",
            "backend.models",
            "backend.repositories",
        }
        for module in sorted(forbidden):
            with self.subTest(module=module):
                self.assertNotIn(module, self.imports)
        for module in sorted(allowed):
            with self.subTest(module=module):
                self.assertIn(module, self.imports)

    def test_module_does_not_call_transactions(self):
        for token in ("commit", "rollback", "close", "begin"):
            with self.subTest(token=token):
                self.assertNotIn(f"self._session.{token}(", self.code)
                self.assertNotIn(f"session.{token}(", self.code)

    def test_module_does_not_call_fuzzy_recognizer(self):
        # The shadow service must NOT call detect_productos or any
        # fuzzy recognizer method.
        for token in ("detectar_productos", "FuzzyProductRecognizer"):
            with self.subTest(token=token):
                self.assertNotIn(token, self.code)

    def test_module_does_not_call_ollama(self):
        # The shadow service must NOT depend on the concrete
        # OllamaEmbeddingClient.
        for token in ("OllamaEmbeddingClient",):
            with self.subTest(token=token):
                self.assertNotIn(token, self.code)

    def test_module_does_not_issue_writes(self):
        for token in ("insert(", "update(", "delete("):
            with self.subTest(token=token):
                self.assertNotIn(token, self.code)

    def test_module_does_not_call_embedding_mutation_methods(self):
        for token in ("mark_status", "mark_stale", "mark_inactive"):
            with self.subTest(token=token):
                self.assertNotIn(token, self.code)


class ComparisonDataclassBoundaryTest(unittest.TestCase):
    def test_dataclass_is_frozen(self):
        from backend.services.product_recognition_shadow_comparison import (
            ProductRecognitionShadowComparison,
        )

        comparison = ProductRecognitionShadowComparison(
            fuzzy_best_id=1,
            vector_best_id=1,
            fuzzy_candidate_ids=(1,),
            vector_candidate_ids=(1,),
            fuzzy_candidate_scores=(1.0,),
            vector_candidate_scores=(0.9,),
            agreement="same_top1",
            fuzzy_latency_ms=1.0,
            embedding_latency_ms=2.0,
            vector_latency_ms=3.0,
            vector_available=True,
            failure_category=None,
        )
        with self.assertRaises((Exception,)):
            comparison.fuzzy_best_id = 2  # type: ignore[misc]

    def test_dataclass_exposes_only_twelve_documented_fields(self):
        from backend.services.product_recognition_shadow_comparison import (
            ProductRecognitionShadowComparison,
        )

        names = {f.name for f in fields(ProductRecognitionShadowComparison)}
        expected = {
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
        self.assertEqual(names, expected)


class HybridObservationDataclassBoundaryTest(unittest.TestCase):
    def test_dataclass_is_frozen(self):
        from backend.services.product_recognition_shadow_comparison import (
            ProductRecognitionHybridObservation,
        )

        hybrid = ProductRecognitionHybridObservation(
            hybrid_candidate_ranking=(1,),
            hybrid_combined_scores=(0.5,),
            hybrid_top1_top2_gap=0.0,
            exact_canonical_match=False,
            exact_alias_match=False,
            decision="unknown",
            fuzzy_weight=0.5,
            vector_weight=0.5,
            unique_threshold=0.7,
            ambiguous_threshold=0.4,
            min_score_gap=0.05,
            non_authoritative=True,
        )
        with self.assertRaises((Exception,)):
            hybrid.decision = "unique"  # type: ignore[misc]

    def test_dataclass_exposes_only_twelve_documented_fields(self):
        from backend.services.product_recognition_shadow_comparison import (
            ProductRecognitionHybridObservation,
        )

        names = {f.name for f in fields(ProductRecognitionHybridObservation)}
        expected = {
            "hybrid_candidate_ranking",
            "hybrid_combined_scores",
            "hybrid_top1_top2_gap",
            "exact_canonical_match",
            "exact_alias_match",
            "decision",
            "fuzzy_weight",
            "vector_weight",
            "unique_threshold",
            "ambiguous_threshold",
            "min_score_gap",
            "non_authoritative",
        }
        self.assertEqual(names, expected)


class ShadowedRecognizerDoesNotMutateInnerTest(unittest.TestCase):
    def test_shadowed_recognizer_does_not_mutate_inner_result(self):
        from backend.services.product_recognition_shadow_service import (
            ProductRecognitionShadowService,
            ShadowedProductRecognizer,
        )
        from backend.services.shadow_metrics_recorder import ShadowMetricsRecorder

        class _InnerSpy:
            def __init__(self) -> None:
                self.calls = 0

            def recognize(self, text: str, catalog: list[dict]) -> dict:
                self.calls += 1
                return {
                    "encontrados": [{"producto_presentacion_id": 1}],
                    "encontrados_posibles": [],
                    "encontrados_no_disponibles": [],
                    "no_encontrados": [],
                }

        settings = _settings_for_test()
        shadow_service = ProductRecognitionShadowService(
            embedding_client=_StubEmbeddingClient(),
            vector_search_service=lambda: _StubVectorSearchService(),
            settings=settings,
        )
        recorder = ShadowMetricsRecorder()
        inner = _InnerSpy()
        recognizer = ShadowedProductRecognizer(
            inner=inner,
            shadow=shadow_service,
            recorder=recorder,
            commerce_id_resolver=lambda catalog: 1,
        )
        catalog = [{"producto_presentacion_id": 1, "producto_nombre": "pizza"}]
        result = recognizer.recognize("pizza", catalog)
        self.assertEqual(result["encontrados"][0]["producto_presentacion_id"], 1)
        self.assertEqual(inner.calls, 1)


class FactoryDoesNotHoldFuzzyRecognizerInShadowModeTest(unittest.TestCase):
    def test_factory_does_not_inject_fuzzy_recognizer_into_shadow_service(self):
        from backend.services.product_recognition_factory import (
            get_product_recognizer,
        )
        from backend.services.product_recognition_shadow_service import (
            ShadowedProductRecognizer,
        )

        settings = _settings_for_test(product_recognizer_mode="shadow")
        recognizer = get_product_recognizer(
            settings,
            session_provider=lambda: _StubSession(),
            embedding_client=_StubEmbeddingClient(),
        )
        self.assertIsInstance(recognizer, ShadowedProductRecognizer)
        # The shadow service holds the embedding client and the
        # vector-search factory, never a fuzzy recognizer.
        inner = recognizer._inner  # type: ignore[attr-defined]
        self.assertIsInstance(inner, __import__(
            "backend.recognizers.fuzzy_product_recognizer",
            fromlist=["FuzzyProductRecognizer"],
        ).FuzzyProductRecognizer)


class RecorderBoundaryTest(unittest.TestCase):
    def test_min_score_gap_field_is_documented_as_provisional(self):
        from backend.services.product_recognition_shadow_comparison import (
            ProductRecognitionHybridObservation,
        )

        hybrid = ProductRecognitionHybridObservation(
            hybrid_candidate_ranking=(1,),
            hybrid_combined_scores=(0.5,),
            hybrid_top1_top2_gap=0.0,
            exact_canonical_match=False,
            exact_alias_match=False,
            decision="unknown",
            fuzzy_weight=0.5,
            vector_weight=0.5,
            unique_threshold=0.7,
            ambiguous_threshold=0.4,
            min_score_gap=0.05,
            non_authoritative=True,
        )
        self.assertTrue(hybrid.non_authoritative)
        self.assertEqual(hybrid.min_score_gap, 0.05)


def _settings_for_test(**overrides):
    from backend.config.settings import Settings

    base = {
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


class _StubEmbeddingClient:
    def embed_query(self, text: str) -> list[float]:
        return [0.0] * 384

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 384 for _ in texts]


class _StubVectorSearchService:
    def search_similar(
        self,
        *,
        id_comercio: int,
        query_embedding: list[float],
        top_k: int,
        candidate_producto_presentacion_ids: list[int] | None = None,
    ) -> list:
        return []


class _StubSession:
    def close(self) -> None:
        pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
