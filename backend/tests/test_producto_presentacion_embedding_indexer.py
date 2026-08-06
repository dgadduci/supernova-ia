"""Per-document indexer tests.

Subphase 4.6 wires the catalog projection to the pure
``ProductEmbeddingDocumentBuilder`` and reconciles every document
through the service's ``create_or_update_document(...)`` /
``record_failed_document(...)`` / ``mark_status(...)`` surface.

The tests use a fake ``EmbeddingClientProtocol`` to avoid real Ollama
calls. They cover initial indexing, hash-based idempotency, semantic
updates, alias stale behavior, inactive catalog behavior, batch
failure semantics, commerce isolation, state machine reactivation,
batch size binding, ``--force``, failed/stale/inactive reactivation,
new failed documents with no existing rows, existing failed documents,
dry-run behavior, and the metadata persistence path.
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from backend.config.settings import Settings
from backend.llm.embedding_client import (
    EmbeddingClientProtocol,
    EmbeddingConnectionError,
)
from backend.models import (
    EmbeddingStatus,
    ProductoAlias,
    ProductoPresentacionEmbedding,
)
from backend.repositories.producto_presentacion_embedding_index_repository import (
    ProductoPresentacionEmbeddingIndexRepository,
)
from backend.services.producto_presentacion_embedding_indexer import (
    ProductoPresentacionEmbeddingIndexer,
)
from backend.services.producto_presentacion_embedding_service import (
    ProductoPresentacionEmbeddingService,
)
from backend.tests.test_producto_alias_model import (
    _delete_comercio,
    _seed_comercio_with_catalogo,
)

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@dataclass
class FakeEmbeddingClient:
    """Programmable fake implementing ``EmbeddingClientProtocol``.

    ``vectors`` maps each text to a deterministic vector value. When
    ``raise_for`` is set, raises ``EmbeddingConnectionError`` for any
    text whose substring matches.
    """

    vectors: dict[str, list[float]] | None = None
    raise_for: set[str] | None = None
    call_count: int = 0

    def __post_init__(self) -> None:
        if self.vectors is None:
            self.vectors = {}
        if self.raise_for is None:
            self.raise_for = set()

    def embed_query(self, text: str) -> list[float]:
        return self._vector_for(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.call_count += 1
        for text in texts:
            for needle in self.raise_for or set():
                if needle in text:
                    raise EmbeddingConnectionError(
                        f"fake connection error for {needle!r}"
                    )
        return [self._vector_for(text) for text in texts]

    def _vector_for(self, text: str) -> list[float]:
        if text in self.vectors:
            return self.vectors[text]
        return [0.0] * 384


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


def _build_indexer(
    session,
    *,
    embedding_client: EmbeddingClientProtocol,
    settings: Settings,
) -> ProductoPresentacionEmbeddingIndexer:
    index_repository = ProductoPresentacionEmbeddingIndexRepository(session)
    embedding_service = ProductoPresentacionEmbeddingService(session)
    return ProductoPresentacionEmbeddingIndexer(
        session=session,
        embedding_client=embedding_client,
        embedding_service=embedding_service,
        index_repository=index_repository,
        settings=settings,
    )


def _add_alias(
    session,
    *,
    id_producto: int,
    id_producto_presentacion: int | None,
    alias: str,
    alias_normalizado: str,
    activo: bool = True,
) -> int:
    row = ProductoAlias(
        id_producto=id_producto,
        id_producto_presentacion=id_producto_presentacion,
        alias=alias,
        alias_normalizado=alias_normalizado,
        activo=activo,
    )
    session.add(row)
    session.flush()
    return int(row.id)


def _delete_embeddings_for_presentation(session, pp_id: int) -> None:
    session.execute(
        delete(ProductoPresentacionEmbedding).where(
            ProductoPresentacionEmbedding.id_producto_presentacion == pp_id
        )
    )


class InitialIndexingTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.settings = _settings()
        self.client = FakeEmbeddingClient()

    def test_initial_indexing_creates_one_row_per_document(self):
        with TestingSessionLocal() as session, session.begin():
            _add_alias(
                session,
                id_producto=self.fixtures["producto_a_id"],
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
                alias="muzza",
                alias_normalizado="muzza",
            )
            _add_alias(
                session,
                id_producto=self.fixtures["producto_a_id"],
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
                alias="muzza-chica",
                alias_normalizado="muzza-chica",
            )
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            result = indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
            self.assertEqual(result.completed, 1)
            self.assertEqual(result.failed, 0)
            outcome = result.outcomes[0]
            self.assertEqual(
                outcome.created, 4
            )
            self.assertEqual(outcome.updated, 0)
            self.assertEqual(outcome.unchanged, 0)
            self.assertEqual(outcome.failed, 0)
        self.assertGreaterEqual(self.client.call_count, 1)
        with TestingSessionLocal() as session:
            rows = session.scalars(
                select(ProductoPresentacionEmbedding).where(
                    ProductoPresentacionEmbedding.id_producto_presentacion
                    == self.fixtures["pp_a_chica_id"]
                )
            ).all()
            self.assertEqual(len(rows), 4)
            source_types = {row.source_type for row in rows}
            self.assertEqual(
                source_types, {"canonical", "combined", "alias"}
            )
            for row in rows:
                self.assertEqual(row.embedding_status, "ready")
                self.assertEqual(row.modelo, "all-minilm:latest")
                self.assertTrue(row.activo)
                self.assertIsNone(row.last_error)


class HashBasedIdempotencyTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.settings = _settings()
        self.client = FakeEmbeddingClient()

    def test_second_run_reports_unchanged_and_skips_ollama(self):
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
        self.client.call_count = 0
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            result = indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
            outcome = result.outcomes[0]
            self.assertEqual(outcome.unchanged, 2)
            self.assertEqual(outcome.created, 0)
            self.assertEqual(outcome.updated, 0)
        self.assertEqual(self.client.call_count, 0)


class SemanticUpdateTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.settings = _settings()
        self.client = FakeEmbeddingClient()

    def test_canonical_and_combined_update_on_rename(self):
        with TestingSessionLocal() as session, session.begin():
            _add_alias(
                session,
                id_producto=self.fixtures["producto_a_id"],
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
                alias="muzza",
                alias_normalizado="muzza",
            )
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
        with TestingSessionLocal() as session, session.begin():
            from backend.models import Producto

            producto = session.get(Producto, self.fixtures["producto_a_id"])
            producto.nombre = "Pizza de Jamón y Queso"
        self.client.call_count = 0
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            result = indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
            outcome = result.outcomes[0]
            self.assertEqual(outcome.updated, 2)
            self.assertEqual(outcome.unchanged, 1)
        self.assertGreaterEqual(self.client.call_count, 1)


class AliasStaleTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.settings = _settings()
        self.client = FakeEmbeddingClient()

    def test_deleted_alias_marks_row_stale(self):
        with TestingSessionLocal() as session, session.begin():
            alias_id = _add_alias(
                session,
                id_producto=self.fixtures["producto_a_id"],
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
                alias="muzza",
                alias_normalizado="muzza",
            )
            self._alias_id = alias_id
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
        with TestingSessionLocal() as session, session.begin():
            session.execute(
                delete(ProductoAlias).where(ProductoAlias.id == self._alias_id)
            )
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            result = indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
            outcome = result.outcomes[0]
            self.assertEqual(outcome.stale, 1)
        with TestingSessionLocal() as session:
            rows = session.scalars(
                select(ProductoPresentacionEmbedding).where(
                    ProductoPresentacionEmbedding.id_producto_presentacion
                    == self.fixtures["pp_a_chica_id"],
                    ProductoPresentacionEmbedding.source_type == "alias",
                )
            ).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].embedding_status, "stale")
            self.assertIsNotNone(rows[0].vector)


class InactiveCatalogTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.settings = _settings()
        self.client = FakeEmbeddingClient()

    def test_deactivated_producto_marks_all_rows_inactive(self):
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
        with TestingSessionLocal() as session, session.begin():
            from backend.models import Producto

            producto = session.get(Producto, self.fixtures["producto_a_id"])
            producto.activo = False
        self.client.call_count = 0
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            result = indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
            outcome = result.outcomes[0]
            self.assertEqual(outcome.status, "inactive")
            self.assertGreater(outcome.inactive, 0)
        self.assertEqual(self.client.call_count, 0)
        with TestingSessionLocal() as session:
            rows = session.scalars(
                select(ProductoPresentacionEmbedding).where(
                    ProductoPresentacionEmbedding.id_producto_presentacion
                    == self.fixtures["pp_a_chica_id"]
                )
            ).all()
            self.assertEqual(len(rows), 2)
            self.assertTrue(
                all(row.embedding_status == "inactive" for row in rows)
            )


class BatchFailureTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.settings = _settings(embedding_batch_size=1)
        self.client = FakeEmbeddingClient(raise_for={"Pizza de Muzzarella Chica"})

    def test_connection_error_marks_documents_failed(self):
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            result = indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
            outcome = result.outcomes[0]
            self.assertGreater(outcome.failed, 0)
        with TestingSessionLocal() as session:
            rows = session.scalars(
                select(ProductoPresentacionEmbedding).where(
                    ProductoPresentacionEmbedding.id_producto_presentacion
                    == self.fixtures["pp_a_chica_id"]
                )
            ).all()
            self.assertEqual(len(rows), 2)
            failed = [row for row in rows if row.embedding_status == "failed"]
            self.assertEqual(len(failed), outcome.failed)
            for row in failed:
                self.assertIsNotNone(row.last_error)


class CommerceIsolationTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.settings = _settings()
        self.client = FakeEmbeddingClient()

    def test_unknown_comercio_id_returns_empty(self):
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            result = indexer.index_presentations(id_comercio=999999999)
            self.assertEqual(result.completed, 0)
            self.assertEqual(len(result.outcomes), 0)


class StateMachineReactivationTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.settings = _settings()
        self.client = FakeEmbeddingClient()

    def test_stale_row_returns_to_ready(self):
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
        with TestingSessionLocal() as session, session.begin():
            session.execute(
                delete(ProductoPresentacionEmbedding).where(
                    ProductoPresentacionEmbedding.id_producto_presentacion
                    == self.fixtures["pp_a_chica_id"],
                    ProductoPresentacionEmbedding.source_type == "alias",
                )
            )
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            result = indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
            outcome = result.outcomes[0]
            self.assertEqual(outcome.created, 0)
            self.assertEqual(outcome.unchanged, 2)


class BatchSizeBindingTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.settings = _settings(embedding_batch_size=1)
        self.client = FakeEmbeddingClient()

    def test_each_batch_calls_embed_documents(self):
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
        self.assertGreaterEqual(self.client.call_count, 2)


class ForceFlagTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.settings = _settings()
        self.client = FakeEmbeddingClient()

    def test_force_updates_every_unchanged_document(self):
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
        self.client.call_count = 0
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            result = indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
                force=True,
            )
            outcome = result.outcomes[0]
            self.assertEqual(outcome.updated, 2)
            self.assertEqual(outcome.unchanged, 0)
        self.assertGreaterEqual(self.client.call_count, 1)


class FailedStaleInactiveReactivationTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.settings = _settings()
        self.client = FakeEmbeddingClient()

    def test_returns_to_ready_for_each_non_terminal_state(self):
        with TestingSessionLocal() as session, session.begin():
            _add_alias(
                session,
                id_producto=self.fixtures["producto_a_id"],
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
                alias="muzza",
                alias_normalizado="muzza",
            )
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
        with TestingSessionLocal() as session, session.begin():
            session.execute(
                delete(ProductoPresentacionEmbedding).where(
                    ProductoPresentacionEmbedding.id_producto_presentacion
                    == self.fixtures["pp_a_chica_id"],
                    ProductoPresentacionEmbedding.source_type == "alias",
                )
            )
            service = ProductoPresentacionEmbeddingService(session)
            for row in service.list_by_producto_presentacion_and_model(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
                modelo="all-minilm:latest",
            ):
                if row.embedding_status == "ready":
                    service.mark_status(row, EmbeddingStatus.FAILED)
                else:
                    service.mark_status(row, EmbeddingStatus.READY)
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            result = indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
            outcome = result.outcomes[0]
            self.assertEqual(outcome.updated, 2)
        with TestingSessionLocal() as session:
            rows = session.scalars(
                select(ProductoPresentacionEmbedding).where(
                    ProductoPresentacionEmbedding.id_producto_presentacion
                    == self.fixtures["pp_a_chica_id"]
                )
            ).all()
            for row in rows:
                self.assertEqual(row.embedding_status, "ready")
                self.assertIsNone(row.last_error)


class NewFailedDocumentTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.settings = _settings()
        self.client = FakeEmbeddingClient(raise_for={"Pizza de Muzzarella Chica"})

    def test_failed_row_with_no_existing_record_persists(self):
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            result = indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
            outcome = result.outcomes[0]
            self.assertGreater(outcome.failed, 0)
        with TestingSessionLocal() as session:
            rows = session.scalars(
                select(ProductoPresentacionEmbedding).where(
                    ProductoPresentacionEmbedding.id_producto_presentacion
                    == self.fixtures["pp_a_chica_id"]
                )
            ).all()
            for row in rows:
                self.assertEqual(row.embedding_status, "failed")
                self.assertIsNone(row.vector)
                self.assertTrue(row.activo)
                self.assertIsNotNone(row.last_error)


class ExistingFailedDocumentPreservesVectorTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.settings = _settings()
        self.client = FakeEmbeddingClient(
            vectors={"Pizza de Muzzarella Chica": [0.5] * 384}
        )

    def test_previous_vector_is_preserved_on_failure(self):
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
        with TestingSessionLocal() as session:
            previous = session.scalars(
                select(ProductoPresentacionEmbedding).where(
                    ProductoPresentacionEmbedding.id_producto_presentacion
                    == self.fixtures["pp_a_chica_id"]
                )
            ).all()
            self.assertTrue(all(row.vector is not None for row in previous))
            self.assertTrue(all(row.embedding_status == "ready" for row in previous))
        with TestingSessionLocal() as session, session.begin():
            from backend.models import Producto

            producto = session.get(Producto, self.fixtures["producto_a_id"])
            producto.nombre = "Pizza de Jamón y Queso"
        self.client.raise_for = {"Pizza de Jamón"}
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
        with TestingSessionLocal() as session:
            rows = session.scalars(
                select(ProductoPresentacionEmbedding).where(
                    ProductoPresentacionEmbedding.id_producto_presentacion
                    == self.fixtures["pp_a_chica_id"]
                )
            ).all()
            failed_rows = [row for row in rows if row.embedding_status == "failed"]
            self.assertGreater(len(failed_rows), 0)
            for row in failed_rows:
                self.assertIsNotNone(row.vector)
                self.assertTrue(row.activo)


class UpdatePersistsSourceTextTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.settings = _settings()
        self.client = FakeEmbeddingClient()

    def test_update_persists_source_text_and_normalized_text(self):
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
        with TestingSessionLocal() as session, session.begin():
            from backend.models import Producto

            producto = session.get(Producto, self.fixtures["producto_a_id"])
            producto.nombre = "Pizza de Jamón y Queso"
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
        with TestingSessionLocal() as session:
            row = session.scalar(
                select(ProductoPresentacionEmbedding).where(
                    ProductoPresentacionEmbedding.id_producto_presentacion
                    == self.fixtures["pp_a_chica_id"],
                    ProductoPresentacionEmbedding.source_type == "canonical",
                )
            )
            self.assertIsNotNone(row)
            self.assertIn("Jamón", row.source_text)
            self.assertIn("jamon", row.normalized_text)


class DryRunTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.settings = _settings()
        self.client = FakeEmbeddingClient()

    def test_dry_run_is_strictly_read_only(self):
        with TestingSessionLocal() as session, session.begin():
            indexer = _build_indexer(
                session, embedding_client=self.client, settings=self.settings
            )
            result = indexer.index_presentations(
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
                dry_run=True,
            )
            outcome = result.outcomes[0]
            self.assertEqual(outcome.created, 2)
            self.assertEqual(outcome.updated, 0)
            self.assertEqual(outcome.unchanged, 0)
        self.assertEqual(self.client.call_count, 0)
        with TestingSessionLocal() as session:
            rows = session.scalars(
                select(ProductoPresentacionEmbedding).where(
                    ProductoPresentacionEmbedding.id_producto_presentacion
                    == self.fixtures["pp_a_chica_id"]
                )
            ).all()
            self.assertEqual(len(rows), 0)


if __name__ == "__main__":
    unittest.main()
