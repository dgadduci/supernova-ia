import os
import unittest

from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from backend.config.settings import load_settings
from backend.models import Precio, ProductoPresentacion, ProductoPresentacionEmbedding
from backend.services.exceptions import (
    InvalidProductoPresentacionEmbedding,
    ProductoPresentacionNotFound,
)
from backend.services.producto_presentacion_embedding_service import (
    ProductoPresentacionEmbeddingService,
)
from backend.tests.test_producto_alias_model import (
    _delete_comercio,
    _seed_comercio_with_catalogo,
)

TEST_URL = os.environ.get(
    "SUPERNOVA_DATABASE_URL",
    "postgresql+psycopg:///supernova_test",
)
engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _schema_available() -> bool:
    try:
        with engine.connect() as connection:
            extension = connection.execute(
                text(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
                    ")"
                )
            ).scalar_one()
            table = connection.execute(
                text(
                    "SELECT to_regclass('public.producto_presentacion_embeddings')"
                )
            ).scalar_one()
            return bool(extension and table)
    except SQLAlchemyError:
        return False


@unittest.skipUnless(
    _schema_available(),
    "PostgreSQL vector extension and embedding table are required",
)
class ProductoPresentacionEmbeddingIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.dimension = load_settings().embedding_dimension

    def test_schema_exposes_vector_extension_constraints_and_indexes(self):
        with engine.connect() as connection:
            extension = connection.execute(
                text(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
                    ")"
                )
            ).scalar_one()
            vector_type = connection.execute(
                text(
                    "SELECT format_type(atttypid, atttypmod) "
                    "FROM pg_attribute "
                    "WHERE attrelid = "
                    "'producto_presentacion_embeddings'::regclass "
                    "AND attname = 'vector'"
                )
            ).scalar_one()
            indexes = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE tablename = 'producto_presentacion_embeddings'"
                    )
                )
            }
        self.assertTrue(extension)
        self.assertEqual(vector_type, f"vector({self.dimension})")
        self.assertIn(
            "ix_producto_presentacion_embeddings_id_producto_presentacion",
            indexes,
        )
        self.assertIn("ix_producto_presentacion_embeddings_modelo", indexes)
        self.assertIn("producto_presentacion_embedding_unico", indexes)

    def test_upsert_replaces_vector_without_duplicate(self):
        pp_id = self.fixtures["pp_a_chica_id"]
        first_vector = [0.1] * self.dimension
        second_vector = [0.2] * self.dimension
        with TestingSessionLocal() as session, session.begin():
            service = ProductoPresentacionEmbeddingService(session)
            first = service.upsert(pp_id, first_vector, "all-minilm:latest")
            first_id = first.id
            first_created = first.fecha_alta
        with TestingSessionLocal() as session, session.begin():
            service = ProductoPresentacionEmbeddingService(session)
            second = service.upsert(pp_id, second_vector, "all-minilm:latest")
            self.assertEqual(second.id, first_id)
            self.assertEqual(second.vector, second_vector)
            self.assertGreaterEqual(second.fecha_ultima_modificacion, first_created)
            count = session.scalar(
                select(func.count()).select_from(ProductoPresentacionEmbedding).where(
                    ProductoPresentacionEmbedding.id_producto_presentacion == pp_id,
                    ProductoPresentacionEmbedding.modelo == "all-minilm:latest",
                )
            )
            self.assertEqual(count, 1)
            retrieved = service.get_by_producto_presentacion_and_model(
                pp_id,
                "all-minilm:latest",
            )
            self.assertEqual(retrieved.id, first_id)
            self.assertEqual(retrieved.vector, second_vector)

    def test_different_models_can_coexist(self):
        pp_id = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin():
            service = ProductoPresentacionEmbeddingService(session)
            first = service.upsert(pp_id, [0.1] * self.dimension, "model-a")
            second = service.upsert(pp_id, [0.2] * self.dimension, "model-b")
            self.assertNotEqual(first.id, second.id)
            self.assertEqual(len(service.list_by_producto_presentacion(pp_id)), 2)

    def test_wrong_dimension_is_rejected_before_persistence(self):
        pp_id = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin():
            service = ProductoPresentacionEmbeddingService(session)
            with self.assertRaises(InvalidProductoPresentacionEmbedding):
                service.upsert(pp_id, [0.0] * (self.dimension - 1), "model")
            count = session.scalar(
                select(func.count()).select_from(ProductoPresentacionEmbedding).where(
                    ProductoPresentacionEmbedding.id_producto_presentacion == pp_id
                )
            )
            self.assertEqual(count, 0)

    def test_missing_product_presentation_is_rejected(self):
        with TestingSessionLocal() as session, session.begin():
            missing_id = max(self.fixtures["pp_a_chica_id"], self.fixtures["pp_a_grande_id"]) + 100000
            service = ProductoPresentacionEmbeddingService(session)
            with self.assertRaises(ProductoPresentacionNotFound):
                service.upsert(missing_id, [0.0] * self.dimension, "model")

    def test_product_presentation_delete_cascades_to_embeddings(self):
        pp_id = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin():
            service = ProductoPresentacionEmbeddingService(session)
            service.upsert(pp_id, [0.3] * self.dimension, "model")
            session.execute(
                delete(Precio).where(Precio.id_producto_presentacion == pp_id)
            )
            session.execute(
                delete(ProductoPresentacion).where(ProductoPresentacion.id == pp_id)
            )
        with TestingSessionLocal() as session:
            remaining = session.scalar(
                select(func.count()).select_from(ProductoPresentacionEmbedding).where(
                    ProductoPresentacionEmbedding.id_producto_presentacion == pp_id
                )
            )
            self.assertEqual(remaining, 0)


if __name__ == "__main__":
    unittest.main()
