"""Module boundary tests for the 4.9 product-presentation vector search.

Subphase 4.9 mirrors the boundary tests already exercised by
``test_admin_product_embeddings_module_boundaries.py``. The tests
inspect the source of the new modules and assert that the service,
repository, and result dataclass respect the documented boundaries:

- The service does NOT import the embedding client, the document
  builder, the seeder, the indexer, the sync service, the admin
  router, or any 4.7 schema.
- The repository does NOT import FastAPI, HTTP, the embedding client,
  the document builder, the seeder, the indexer, the sync service, or
  any router.
- The service and repository do NOT call ``session.commit()``,
  ``session.rollback()``, ``session.close()``, or ``session.begin()``.
- The result dataclass is frozen and exposes only the three documented
  fields.

The tests use AST to inspect actual ``import`` statements rather than
substring matches on the source so a docstring mention of a forbidden
module does not register as a violation.
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


class ServiceBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend.services import (
            product_presentation_vector_search_service as service_module,
        )

        cls.path = Path(service_module.__file__)
        cls.source = cls.path.read_text(encoding="utf-8")
        cls.code = _code_without_docstring(cls.source)
        cls.code_full = _code_without_docstrings(cls.source)
        cls.imports = _imports(cls.source)

    def test_service_signature_is_keyword_only(self):
        import inspect

        from backend.services.product_presentation_vector_search_service import (
            ProductPresentationVectorSearchService,
        )

        sig = inspect.signature(
            ProductPresentationVectorSearchService.search_similar
        )
        for name, param in sig.parameters.items():
            if name == "self":
                continue
            with self.subTest(parameter=name):
                self.assertEqual(
                    param.kind,
                    inspect.Parameter.KEYWORD_ONLY,
                    f"search_similar parameter {name!r} must be keyword-only",
                )

    def test_service_does_not_import_forbidden_modules(self):
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
            "backend.services.producto_presentacion_embedding_indexer",
            "backend.services.producto_presentacion_embedding_seeder",
            "backend.services.producto_presentacion_embedding_admin_service",
            "backend.services.catalog_embedding_synchronization_service",
            "backend.routers",
            "backend.routers.admin_product_embeddings",
            "backend.schemas",
            "backend.schemas.product_embedding_admin",
        }
        for module in sorted(forbidden):
            with self.subTest(module=module):
                self.assertNotIn(module, self.imports)

    def test_service_does_not_call_transactions(self):
        for token in ("commit", "rollback", "close", "begin"):
            with self.subTest(token=token):
                self.assertNotIn(f"self._session.{token}(", self.code)
                self.assertNotIn(f"session.{token}(", self.code)

    def test_service_does_not_call_ollama(self):
        for token in (
            "OllamaEmbeddingClient",
            "embed_query",
            "embed_documents",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, self.code)

    def test_service_does_not_call_embedding_mutation_methods(self):
        for token in (
            "mark_status",
            "mark_stale",
            "mark_inactive",
            "record_failed_document",
            "create_or_update_document",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, self.code)

    def test_service_does_not_issue_writes(self):
        for token in ("insert(", "update(", "delete("):
            with self.subTest(token=token):
                self.assertNotIn(token, self.code)

    def test_service_validation_order_top_k_first(self):
        import re

        topk_check = re.search(r"top_k\s*<=\s*0", self.code)
        dimension_check = re.search(
            r"len\(query_embedding\)\s*!=\s*self\._settings\.embedding_dimension",
            self.code,
        )
        empty_candidate_check = re.search(
            r"len\(candidate_producto_presentacion_ids\)\s*==\s*0",
            self.code,
        )
        self.assertIsNotNone(topk_check)
        self.assertIsNotNone(dimension_check)
        self.assertIsNotNone(empty_candidate_check)
        assert topk_check is not None
        assert dimension_check is not None
        assert empty_candidate_check is not None
        self.assertLess(
            topk_check.start(),
            dimension_check.start(),
            "top_k validation must appear before dimension validation",
        )
        self.assertLess(
            dimension_check.start(),
            empty_candidate_check.start(),
            "dimension validation must appear before empty-candidate "
            "short-circuit",
        )

    def test_service_search_similar_raises_top_k_first(self):
        from unittest.mock import MagicMock

        from backend.config.settings import Settings
        from backend.services.product_presentation_vector_search_service import (
            ProductPresentationVectorSearchService,
        )

        settings = Settings(
            llm_url="http://x",
            llm_model="x",
            llm_timeout=1,
            llm_keep_alive="1h",
            llm_num_ctx=1,
            llm_num_predict=1,
            llm_log_content=False,
            llm_log_max_chars=1,
            embedding_dimension=384,
        )
        session = MagicMock(name="session")
        service = ProductPresentationVectorSearchService(session, settings)
        with self.assertRaises(Exception) as ctx:
            service.search_similar(
                id_comercio=1,
                query_embedding=[0.1, 0.2],
                top_k=0,
            )
        from backend.services.exceptions import InvalidVectorSearchTopK

        self.assertIsInstance(ctx.exception, InvalidVectorSearchTopK)
        session.execute.assert_not_called()


class RepositoryBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend.repositories import (
            producto_presentacion_embedding_search_repository as repo_module,
        )

        cls.path = Path(repo_module.__file__)
        cls.source = cls.path.read_text(encoding="utf-8")
        cls.code = _code_without_docstring(cls.source)
        cls.imports = _imports(cls.source)

    def test_repository_does_not_import_forbidden_modules(self):
        forbidden = {
            "fastapi",
            "flask",
            "requests",
            "backend.llm",
            "backend.llm.embedding_client",
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
        }
        for module in sorted(forbidden):
            with self.subTest(module=module):
                self.assertNotIn(module, self.imports)

    def test_repository_does_not_call_transactions(self):
        for token in ("commit", "rollback", "close", "begin"):
            with self.subTest(token=token):
                self.assertNotIn(f"self._session.{token}(", self.code)
                self.assertNotIn(f"session.{token}(", self.code)

    def test_repository_does_not_issue_writes(self):
        for token in ("insert(", "update(", "delete("):
            with self.subTest(token=token):
                self.assertNotIn(token, self.code)


class ResultDataclassBoundaryTest(unittest.TestCase):
    def test_dataclass_is_frozen(self):
        from dataclasses import FrozenInstanceError

        from backend.services.product_presentation_vector_match import (
            ProductPresentationVectorMatch,
        )

        match = ProductPresentationVectorMatch(
            id_producto_presentacion=1,
            score=0.5,
            source_type="canonical",
        )
        with self.assertRaises(FrozenInstanceError):
            match.score = 0.9  # type: ignore[misc]

    def test_dataclass_exposes_only_three_fields(self):
        from backend.services.product_presentation_vector_match import (
            ProductPresentationVectorMatch,
        )

        names = {f.name for f in fields(ProductPresentationVectorMatch)}
        self.assertEqual(
            names,
            {"id_producto_presentacion", "score", "source_type"},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)