import unittest

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import DateTime, UniqueConstraint

from backend.config.settings import load_settings
from backend.models import ProductoPresentacion, ProductoPresentacionEmbedding


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
                "fecha_alta",
                "fecha_ultima_modificacion",
            },
        )
        self.assertIsInstance(table.c.vector.type, VECTOR)
        self.assertEqual(
            table.c.vector.type.dim,
            load_settings().embedding_dimension,
        )
        self.assertIs(table.c.vector.nullable, False)
        self.assertIs(table.c.modelo.nullable, False)
        self.assertIs(table.c.id_producto_presentacion.nullable, False)

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

    def test_timestamps_and_uniqueness(self):
        table = ProductoPresentacionEmbedding.__table__
        self.assertIsInstance(table.c.fecha_alta.type, DateTime)
        self.assertTrue(table.c.fecha_alta.type.timezone)
        self.assertTrue(table.c.fecha_alta.server_default is not None)
        self.assertTrue(table.c.fecha_ultima_modificacion.type.timezone)
        self.assertTrue(table.c.fecha_ultima_modificacion.server_default is not None)
        self.assertTrue(table.c.fecha_ultima_modificacion.onupdate is not None)
        constraints = [
            constraint
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        ]
        self.assertTrue(
            any(
                constraint.name == "producto_presentacion_embedding_unico"
                and [column.name for column in constraint.columns]
                == ["id_producto_presentacion", "modelo"]
                for constraint in constraints
            )
        )

    def test_parent_relationship_uses_cascade(self):
        relationship = ProductoPresentacion.__mapper__.relationships["embeddings"]
        self.assertEqual(relationship.back_populates, "producto_presentacion")
        self.assertTrue(relationship.cascade.delete)
        self.assertTrue(relationship.cascade.delete_orphan)
        self.assertTrue(relationship.passive_deletes)


if __name__ == "__main__":
    unittest.main()
