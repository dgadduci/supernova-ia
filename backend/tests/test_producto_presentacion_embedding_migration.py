"""Migration integrity tests for the per-document embedding table.

Subphase 4.6 evolves the persistence boundary from one aggregate row
per ``(id_producto_presentacion, modelo)`` to one row per semantic
document. These tests cover the schema after ``alembic upgrade head``:

- the new columns exist;
- the legacy unique constraint is gone;
- the two partial unique indexes exist (one for ``source_record_id IS
  NULL``, one for ``source_record_id IS NOT NULL``);
- all seven ``CHECK`` constraints exist (including
  ``embedding_status_chk``);
- ``vector`` is nullable.

Document-level uniqueness, vector nullability, and the closed value
sets are also exercised through direct INSERTs / failing inserts.
"""
from __future__ import annotations

import unittest

from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from backend.config.settings import load_settings
from backend.models import (
    ProductoPresentacionEmbedding,
)
from backend.tests.test_producto_alias_model import (
    _delete_comercio,
    _seed_comercio_with_catalogo,
)

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _schema_available() -> bool:
    try:
        with engine.connect() as connection:
            table = connection.execute(
                text(
                    "SELECT to_regclass('public.producto_presentacion_embeddings')"
                )
            ).scalar_one()
            return bool(table)
    except SQLAlchemyError:
        return False


def _hash(*values: object) -> str:
    """Create a deterministic 64-char lowercase hex digest."""
    import hashlib

    raw = "\x1f".join(str(v) for v in values)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@unittest.skipUnless(
    _schema_available(),
    "PostgreSQL embedding table is required",
)
class ProductoPresentacionEmbeddingMigrationTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.dimension = load_settings().embedding_dimension
        self.default_hash = _hash("test", "canonical", "none", "text")

    def test_schema_exposes_new_columns_and_drops_legacy_unique(self):
        with engine.connect() as connection:
            column_names = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'producto_presentacion_embeddings'"
                    )
                )
            }
            expected_columns = {
                "id",
                "id_producto_presentacion",
                "vector",
                "modelo",
                "source_type",
                "source_record_id",
                "source_text",
                "normalized_text",
                "content_hash",
                "embedding_status",
                "activo",
                "last_error",
                "fecha_alta",
                "fecha_ultima_modificacion",
            }
            self.assertTrue(expected_columns.issubset(column_names))
            index_names = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE tablename = 'producto_presentacion_embeddings'"
                    )
                )
            }
            self.assertIn("uq_embedding_doc_null_source", index_names)
            self.assertIn("uq_embedding_doc_alias", index_names)
            self.assertNotIn(
                "producto_presentacion_embedding_unico", index_names
            )
            check_names = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid = 'producto_presentacion_embeddings'::regclass "
                        "AND contype = 'c'"
                    )
                )
            }
            expected_checks = {
                "source_type_chk",
                "source_record_id_alias_chk",
                "ready_vector_chk",
                "content_hash_chk",
                "source_text_nonempty_chk",
                "normalized_text_nonempty_chk",
                "embedding_status_chk",
            }
            self.assertTrue(expected_checks.issubset(check_names))
            vector_nullable = connection.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'producto_presentacion_embeddings' "
                    "AND column_name = 'vector'"
                )
            ).scalar_one()
            self.assertEqual(vector_nullable, "YES")

    def test_partial_unique_indexes_for_null_source_record_id(self):
        pp_id = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin():
            session.add(
                ProductoPresentacionEmbedding(
                    id_producto_presentacion=pp_id,
                    modelo="all-minilm:latest",
                    source_type="canonical",
                    source_record_id=None,
                    source_text="Pizza de Muzzarella Chica",
                    normalized_text="pizza de muzzarella chica",
                    content_hash=self.default_hash,
                    vector=[0.1] * self.dimension,
                    embedding_status="ready",
                    activo=True,
                )
            )
        with TestingSessionLocal() as session, session.begin(), self.assertRaises(IntegrityError):
                session.add(
                    ProductoPresentacionEmbedding(
                        id_producto_presentacion=pp_id,
                        modelo="all-minilm:latest",
                        source_type="canonical",
                        source_record_id=None,
                        source_text="Otra cosa",
                        normalized_text="otra cosa",
                        content_hash=_hash("test", "canonical", "none", "duplicate"),
                        vector=[0.2] * self.dimension,
                        embedding_status="ready",
                        activo=True,
                    )
                )
                session.flush()

    def test_partial_unique_index_for_alias_source_record_id(self):
        pp_id = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin():
            session.add(
                ProductoPresentacionEmbedding(
                    id_producto_presentacion=pp_id,
                    modelo="all-minilm:latest",
                    source_type="alias",
                    source_record_id=17,
                    source_text="Pizza de Muzzarella Chica alias 17",
                    normalized_text="pizza de muzzarella chica alias 17",
                    content_hash=_hash("alias", 17, "text"),
                    vector=[0.3] * self.dimension,
                    embedding_status="ready",
                    activo=True,
                )
            )
        with TestingSessionLocal() as session, session.begin(), self.assertRaises(IntegrityError):
                session.add(
                    ProductoPresentacionEmbedding(
                        id_producto_presentacion=pp_id,
                        modelo="all-minilm:latest",
                        source_type="alias",
                        source_record_id=17,
                        source_text="Otra cosa",
                        normalized_text="otra cosa",
                        content_hash=_hash("alias", 17, "duplicate"),
                        vector=[0.4] * self.dimension,
                        embedding_status="ready",
                        activo=True,
                    )
                )
                session.flush()

    def test_canonical_and_alias_coexist_for_same_presentation(self):
        pp_id = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin():
            session.add(
                ProductoPresentacionEmbedding(
                    id_producto_presentacion=pp_id,
                    modelo="all-minilm:latest",
                    source_type="canonical",
                    source_record_id=None,
                    source_text="Pizza de Muzzarella Chica",
                    normalized_text="pizza de muzzarella chica",
                    content_hash=_hash("canonical", "coexist"),
                    vector=[0.5] * self.dimension,
                    embedding_status="ready",
                    activo=True,
                )
            )
            session.add(
                ProductoPresentacionEmbedding(
                    id_producto_presentacion=pp_id,
                    modelo="all-minilm:latest",
                    source_type="alias",
                    source_record_id=17,
                    source_text="Muzza Chica",
                    normalized_text="muzza chica",
                    content_hash=_hash("alias", 17, "coexist"),
                    vector=[0.6] * self.dimension,
                    embedding_status="ready",
                    activo=True,
                )
            )
        with TestingSessionLocal() as session:
            rows = session.scalars(
                select(ProductoPresentacionEmbedding).where(
                    ProductoPresentacionEmbedding.id_producto_presentacion == pp_id
                )
            ).all()
            self.assertEqual(len(rows), 2)

    def test_failed_row_with_null_vector_persists(self):
        pp_id = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin():
            session.add(
                ProductoPresentacionEmbedding(
                    id_producto_presentacion=pp_id,
                    modelo="all-minilm:latest",
                    source_type="canonical",
                    source_record_id=None,
                    source_text="Pizza de Muzzarella Chica",
                    normalized_text="pizza de muzzarella chica",
                    content_hash=_hash("failed", "null-vector"),
                    vector=None,
                    embedding_status="failed",
                    activo=True,
                    last_error="embedding timeout",
                )
            )
        with TestingSessionLocal() as session:
            row = session.scalar(
                select(ProductoPresentacionEmbedding).where(
                    ProductoPresentacionEmbedding.id_producto_presentacion == pp_id,
                    ProductoPresentacionEmbedding.source_type == "canonical",
                )
            )
            self.assertIsNotNone(row)
            self.assertIsNone(row.vector)
            self.assertEqual(row.embedding_status, "failed")

    def test_ready_row_with_null_vector_is_rejected(self):
        pp_id = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin(), self.assertRaises(IntegrityError):
                session.add(
                    ProductoPresentacionEmbedding(
                        id_producto_presentacion=pp_id,
                        modelo="all-minilm:latest",
                        source_type="canonical",
                        source_record_id=None,
                        source_text="Pizza de Muzzarella Chica",
                        normalized_text="pizza de muzzarella chica",
                        content_hash=_hash("ready", "null-vector"),
                        vector=None,
                        embedding_status="ready",
                        activo=True,
                    )
                )
                session.flush()

    def test_source_type_chk_rejects_unknown_value(self):
        pp_id = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin(), self.assertRaises(IntegrityError):
                session.add(
                    ProductoPresentacionEmbedding(
                        id_producto_presentacion=pp_id,
                        modelo="all-minilm:latest",
                        source_type="unknown",
                        source_record_id=None,
                        source_text="Pizza",
                        normalized_text="pizza",
                        content_hash=_hash("unknown", "source-type"),
                        vector=[0.5] * self.dimension,
                        embedding_status="ready",
                        activo=True,
                    )
                )
                session.flush()

    def test_source_record_id_alias_chk_rejects_alias_without_record_id(self):
        pp_id = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin(), self.assertRaises(IntegrityError):
                session.add(
                    ProductoPresentacionEmbedding(
                        id_producto_presentacion=pp_id,
                        modelo="all-minilm:latest",
                        source_type="alias",
                        source_record_id=None,
                        source_text="Pizza",
                        normalized_text="pizza",
                        content_hash=_hash("alias", "no-record-id"),
                        vector=[0.5] * self.dimension,
                        embedding_status="ready",
                        activo=True,
                    )
                )
                session.flush()

    def test_source_record_id_alias_chk_rejects_canonical_with_record_id(self):
        pp_id = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin(), self.assertRaises(IntegrityError):
                session.add(
                    ProductoPresentacionEmbedding(
                        id_producto_presentacion=pp_id,
                        modelo="all-minilm:latest",
                        source_type="canonical",
                        source_record_id=5,
                        source_text="Pizza",
                        normalized_text="pizza",
                        content_hash=_hash("canonical", "with-record-id"),
                        vector=[0.5] * self.dimension,
                        embedding_status="ready",
                        activo=True,
                    )
                )
                session.flush()

    def test_content_hash_chk_rejects_uppercase(self):
        pp_id = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin(), self.assertRaises(IntegrityError):
                session.add(
                    ProductoPresentacionEmbedding(
                        id_producto_presentacion=pp_id,
                        modelo="all-minilm:latest",
                        source_type="canonical",
                        source_record_id=None,
                        source_text="Pizza",
                        normalized_text="pizza",
                        content_hash="A" * 64,
                        vector=[0.5] * self.dimension,
                        embedding_status="ready",
                        activo=True,
                    )
                )
                session.flush()

    def test_content_hash_chk_rejects_wrong_length(self):
        pp_id = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin(), self.assertRaises(IntegrityError):
                session.add(
                    ProductoPresentacionEmbedding(
                        id_producto_presentacion=pp_id,
                        modelo="all-minilm:latest",
                        source_type="canonical",
                        source_record_id=None,
                        source_text="Pizza",
                        normalized_text="pizza",
                        content_hash="a" * 63,
                        vector=[0.5] * self.dimension,
                        embedding_status="ready",
                        activo=True,
                    )
                )
                session.flush()

    def test_content_hash_chk_rejects_non_hex(self):
        pp_id = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin(), self.assertRaises(IntegrityError):
                session.add(
                    ProductoPresentacionEmbedding(
                        id_producto_presentacion=pp_id,
                        modelo="all-minilm:latest",
                        source_type="canonical",
                        source_record_id=None,
                        source_text="Pizza",
                        normalized_text="pizza",
                        content_hash="g" * 64,
                        vector=[0.5] * self.dimension,
                        embedding_status="ready",
                        activo=True,
                    )
                )
                session.flush()

    def test_source_text_nonempty_chk_rejects_whitespace(self):
        pp_id = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin(), self.assertRaises(IntegrityError):
                session.add(
                    ProductoPresentacionEmbedding(
                        id_producto_presentacion=pp_id,
                        modelo="all-minilm:latest",
                        source_type="canonical",
                        source_record_id=None,
                        source_text="   ",
                        normalized_text="pizza",
                        content_hash=_hash("whitespace", "source-text"),
                        vector=[0.5] * self.dimension,
                        embedding_status="ready",
                        activo=True,
                    )
                )
                session.flush()

    def test_normalized_text_nonempty_chk_rejects_whitespace(self):
        pp_id = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin(), self.assertRaises(IntegrityError):
                session.add(
                    ProductoPresentacionEmbedding(
                        id_producto_presentacion=pp_id,
                        modelo="all-minilm:latest",
                        source_type="canonical",
                        source_record_id=None,
                        source_text="Pizza",
                        normalized_text="   ",
                        content_hash=_hash("whitespace", "normalized-text"),
                        vector=[0.5] * self.dimension,
                        embedding_status="ready",
                        activo=True,
                    )
                )
                session.flush()

    def test_embedding_status_chk_rejects_unknown_value(self):
        pp_id = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin(), self.assertRaises(IntegrityError):
                session.add(
                    ProductoPresentacionEmbedding(
                        id_producto_presentacion=pp_id,
                        modelo="all-minilm:latest",
                        source_type="canonical",
                        source_record_id=None,
                        source_text="Pizza",
                        normalized_text="pizza",
                        content_hash=_hash("unknown", "embedding-status"),
                        vector=[0.5] * self.dimension,
                        embedding_status="unknown",
                        activo=True,
                    )
                )
                session.flush()


if __name__ == "__main__":
    unittest.main()
