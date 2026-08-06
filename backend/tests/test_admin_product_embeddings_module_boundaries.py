"""Module boundary tests for the local-admin product-embedding surface.

Subphase 4.7 mirrors the boundary tests already exercised by
``test_incoming_messages_endpoint.py::IncomingMessagesModuleBoundaryTest``.
The tests inspect the source of the new modules and assert that the
router, admin service, status repository, and Pydantic schemas respect
the documented boundaries:

- The router never imports SQLAlchemy, the embedding client, the
  indexer, the seeder, the repositories, the embeddings builder, or
  the scripts.
- The admin service never imports SQLAlchemy, FastAPI, or requests.
  It never calls ``commit``, ``rollback``, ``close``, or ``begin``.
- The status repository never imports HTTP, FastAPI, the embedding
  client, the indexer, the seeder, the admin service, or any router.
- The schemas module exposes exactly the seven expected names through
  ``__all__``.

The tests use AST to inspect actual ``import`` statements rather than
substring matches on the source so a docstring mention of a forbidden
module does not register as a violation.
"""
from __future__ import annotations

import ast
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


class RouterBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend.routers import admin_product_embeddings as router_module

        cls.path = Path(router_module.__file__)
        cls.source = cls.path.read_text(encoding="utf-8")
        cls.code = _code_without_docstring(cls.source)
        cls.code_full = _code_without_docstrings(cls.source)
        cls.imports = _imports(cls.source)

    def test_router_has_only_expected_decorators(self):
        self.assertEqual(self.code.count("@router.post("), 1)
        self.assertEqual(self.code.count("@router.get("), 1)
        for method in ("put", "patch", "delete"):
            with self.subTest(method=method):
                self.assertNotIn(f"@router.{method}", self.code)

    def test_router_does_not_import_forbidden_modules(self):
        forbidden = {
            "sqlalchemy",
            "backend.llm",
            "backend.repositories",
            "backend.embeddings",
            "backend.scripts",
            "backend.intents",
            "backend.models",
            "backend.llm.embedding_client",
            "backend.services.producto_presentacion_embedding_indexer",
            "backend.services.producto_presentacion_embedding_repository",
            "requests",
            "asyncio",
        }
        for module in sorted(forbidden):
            with self.subTest(module=module):
                self.assertNotIn(module, self.imports)

    def test_router_does_not_call_session_close(self):
        self.assertNotIn("session.close(", self.code)

    def test_router_does_not_import_sessionlocal(self):
        self.assertNotIn("_SessionLocal", self.code)

    def test_router_does_not_use_async_await_or_retry(self):
        for token in (
            "async def",
            "await ",
            "time.sleep",
            "logger.",
            "logging.",
            "print(",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, self.code)

    def test_router_module_all_is_limited(self):
        from backend.routers import admin_product_embeddings as router_module

        self.assertEqual(router_module.__all__, ["router"])


class AdminServiceBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend.services import (
            producto_presentacion_embedding_admin_service as admin_service,
        )

        cls.path = Path(admin_service.__file__)
        cls.source = cls.path.read_text(encoding="utf-8")
        cls.code = _code_without_docstring(cls.source)
        cls.imports = _imports(cls.source)

    def test_admin_service_does_not_import_forbidden_modules(self):
        forbidden = {
            "sqlalchemy",
            "fastapi",
            "flask",
            "requests",
            "asyncio",
        }
        for module in sorted(forbidden):
            with self.subTest(module=module):
                self.assertNotIn(module, self.imports)

    def test_admin_service_does_not_call_transactions(self):
        for token in (
            "commit",
            "rollback",
            "close",
            "begin",
        ):
            with self.subTest(token=token):
                self.assertNotIn(f"self._session.{token}(", self.code)
                self.assertNotIn(f"session.{token}(", self.code)

    def test_admin_service_imports_constructor_or_injects_dependencies(self):
        for token in (
            "OllamaEmbeddingClient",
            "ProductoPresentacionEmbeddingIndexer",
            "ProductoPresentacionEmbeddingSeeder",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.code)

    def test_admin_service_uses_dataclasses_replace(self):
        self.assertIn("dataclasses.replace", self.code)

    def test_admin_service_constructor_signature_preserves_ollama_client(self):
        import inspect

        from backend.llm.embedding_client import OllamaEmbeddingClient

        sig = inspect.signature(OllamaEmbeddingClient.__init__)
        params = [p.name for p in sig.parameters.values()]
        self.assertEqual(
            params[:4],
            ["self", "settings", "transport", "clock"],
        )


class StatusRepositoryBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend.repositories import (
            producto_presentacion_embedding_status_repository as status_repo,
        )

        cls.path = Path(status_repo.__file__)
        cls.source = cls.path.read_text(encoding="utf-8")
        cls.code = _code_without_docstring(cls.source)
        cls.imports = _imports(cls.source)

    def test_status_repository_does_not_import_forbidden_modules(self):
        forbidden = {
            "fastapi",
            "flask",
            "requests",
            "backend.llm",
            "backend.services.producto_presentacion_embedding_indexer",
            "backend.services.producto_presentacion_embedding_seeder",
            "backend.services.producto_presentacion_embedding_admin_service",
            "backend.routers",
            "backend.routers.admin_product_embeddings",
            "backend.scripts",
        }
        for module in sorted(forbidden):
            with self.subTest(module=module):
                self.assertNotIn(module, self.imports)

    def test_status_repository_does_not_call_transactions(self):
        for token in (
            "commit",
            "rollback",
            "close",
            "begin",
        ):
            with self.subTest(token=token):
                self.assertNotIn(f"self._session.{token}(", self.code)
                self.assertNotIn(f"session.{token}(", self.code)

    def test_status_repository_does_not_issue_writes(self):
        for token in ("insert(", "update(", "delete("):
            with self.subTest(token=token):
                self.assertNotIn(token, self.code)


class SchemasBoundaryTest(unittest.TestCase):
    def test_schemas_all_is_exact(self):
        from backend.schemas import product_embedding_admin as schema_module

        self.assertEqual(
            schema_module.__all__,
            [
                "PerPresentationOutcome",
                "ProductEmbeddingCounters",
                "ProductEmbeddingReindexRequest",
                "ProductEmbeddingReindexResponse",
                "ProductEmbeddingSourceTypeCounts",
                "ProductEmbeddingStatusCounts",
                "ProductEmbeddingStatusResponse",
            ],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
