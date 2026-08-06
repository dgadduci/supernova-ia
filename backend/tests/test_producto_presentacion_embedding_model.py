import unittest

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import CheckConstraint, DateTime, Index, String, Text

from backend.config.settings import load_settings
from backend.models import EmbeddingStatus, ProductoPresentacion, ProductoPresentacionEmbedding


class ProductoPresentacionEmbeddingMetadataTest(unittest.TestCase):
    def test_table_and_columns(self):
        table = ProductoPresentacionEmbedding.__table__
        self.assertEqual(table.name, "producto_presentacion_embeddings")
        self.assertEqual(
            set(table.columns.keys()),
            {
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
            },
        )
        self.assertIsInstance(table.c.vector.type, VECTOR)
        self.assertEqual(
            table.c.vector.type.dim,
            load_settings().embedding_dimension,
        )
        self.assertIs(table.c.vector.nullable, True)
        self.assertIs(table.c.modelo.nullable, False)
        self.assertIs(table.c.id_producto_presentacion.nullable, False)
        self.assertIs(table.c.source_type.nullable, False)
        self.assertIs(table.c.source_record_id.nullable, True)
        self.assertIs(table.c.source_text.nullable, False)
        self.assertIs(table.c.normalized_text.nullable, False)
        self.assertIs(table.c.content_hash.nullable, False)
        self.assertIs(table.c.embedding_status.nullable, False)
        self.assertIs(table.c.activo.nullable, False)
        self.assertIs(table.c.last_error.nullable, True)

    def test_foreign_key_and_indexes(self):
        column = ProductoPresentacionEmbedding.__table__.c.id_producto_presentacion
        foreign_key = next(iter(column.foreign_keys))
        self.assertEqual(str(foreign_key.target_fullname), "producto_presentaciones.id")
        self.assertEqual(foreign_key.ondelete, "CASCADE")
        index_names = {
            index.name for index in ProductoPresentacionEmbedding.__table__.indexes
        }
        self.assertIn(
            "ix_producto_presentacion_embeddings_id_producto_presentacion",
            index_names,
        )
        self.assertIn("ix_producto_presentacion_embeddings_modelo", index_names)
        self.assertIn("uq_embedding_doc_null_source", index_names)
        self.assertIn("uq_embedding_doc_alias", index_names)

    def test_timestamps_check_constraints_and_status_enum(self):
        table = ProductoPresentacionEmbedding.__table__
        self.assertIsInstance(table.c.fecha_alta.type, DateTime)
        self.assertTrue(table.c.fecha_alta.type.timezone)
        self.assertTrue(table.c.fecha_alta.server_default is not None)
        self.assertTrue(table.c.fecha_ultima_modificacion.type.timezone)
        self.assertTrue(table.c.fecha_ultima_modificacion.server_default is not None)
        self.assertTrue(table.c.fecha_ultima_modificacion.onupdate is not None)
        check_constraint_names = {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
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
        self.assertTrue(expected_checks.issubset(check_constraint_names))
        self.assertEqual(
            EmbeddingStatus.READY,
            "ready",
        )
        self.assertEqual(EmbeddingStatus.READY.value, "ready")
        self.assertEqual(
            {status.value for status in EmbeddingStatus},
            {"pending", "ready", "failed", "stale", "inactive"},
        )

    def test_no_legacy_unique_constraint(self):
        table = ProductoPresentacionEmbedding.__table__
        unique_constraint_names = {
            index.name for index in table.indexes if isinstance(index, Index)
        }
        self.assertNotIn(
            "producto_presentacion_embedding_unico", unique_constraint_names
        )

    def test_parent_relationship_uses_cascade(self):
        relationship = ProductoPresentacion.__mapper__.relationships["embeddings"]
        self.assertEqual(relationship.back_populates, "producto_presentacion")
        self.assertTrue(relationship.cascade.delete)
        self.assertTrue(relationship.cascade.delete_orphan)
        self.assertTrue(relationship.passive_deletes)


if __name__ == "__main__":
    unittest.main()
