"""Focused tests for the persisted product alias workflow.

Covers the model, the migration integrity, the repository, and the service
boundaries. Uses the live ``supernova_test`` PostgreSQL database and
creates/removes a per-test comercio so unrelated rows are never modified.
"""
from __future__ import annotations

import unittest
import uuid
from decimal import Decimal

from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import sessionmaker

from backend.models import (
    CategoriaProducto,
    Comercio,
    EstadoComercio,
    Precio,
    Presentacion,
    Producto,
    ProductoAlias,
    ProductoPresentacion,
)
from backend.repositories.producto_alias_repository import (
    ProductoAliasRepository,
)
from backend.services.exceptions import (
    DuplicateProductoAlias,
    InvalidProductoAlias,
    ProductoAliasPresentationMismatch,
)
from backend.services.producto_alias_service import ProductoAliasService

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _estado_id_activo() -> int:
    with engine.connect() as c:
        row = c.execute(
            select(EstadoComercio.id).where(EstadoComercio.codigo == "ACTIVO")
        ).first()
        if row is None:
            raise RuntimeError("estado ACTIVO not seeded in supernova_test")
        return row[0]


def _seed_comercio_with_catalogo(suffix: str | None = None) -> dict:
    """Create one isolated comercio with two productos and presentations.

    Returns a dict of stable IDs the tests can reference. Always wraps the
    setup in a single transaction so partial failures roll back.
    """
    suffix = suffix or _suffix()
    with TestingSessionLocal() as session, session.begin():
        comercio = Comercio(
            nombre_fantasia=f"Alias Test {suffix}",
            nombre_corto=f"AT {suffix}",
            razon_social=f"Alias Test SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+54911{suffix[:8]}",
            calle="Av. Alias",
            numero="123",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"alias-test-{suffix}",
            estado_id=_estado_id_activo(),
        )
        session.add(comercio)
        session.flush()
        comercio_id = int(comercio.id)
        categoria = CategoriaProducto(
            id_comercio=comercio_id,
            descripcion=f"Pizzas {suffix}",
            activo=True,
            orden=0,
        )
        session.add(categoria)
        session.flush()
        categoria_id = int(categoria.id)
        presentacion_chica = Presentacion(
            id_comercio=comercio_id,
            codigo="chica",
            descripcion="Chica",
            activo=True,
            orden=0,
        )
        presentacion_grande = Presentacion(
            id_comercio=comercio_id,
            codigo="grande",
            descripcion="Grande",
            activo=True,
            orden=1,
        )
        session.add(presentacion_chica)
        session.add(presentacion_grande)
        session.flush()
        presentacion_chica_id = int(presentacion_chica.id)
        presentacion_grande_id = int(presentacion_grande.id)
        producto_a = Producto(
            id_categoria_producto=categoria_id,
            nombre="Pizza de Muzzarella",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        producto_b = Producto(
            id_categoria_producto=categoria_id,
            nombre="Pizza Fugazzeta",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=1,
        )
        session.add(producto_a)
        session.add(producto_b)
        session.flush()
        producto_a_id = int(producto_a.id)
        producto_b_id = int(producto_b.id)
        pp_a_chica = ProductoPresentacion(
            id_producto=producto_a_id,
            id_presentacion=presentacion_chica_id,
            activo=True,
            orden=0,
        )
        pp_a_grande = ProductoPresentacion(
            id_producto=producto_a_id,
            id_presentacion=presentacion_grande_id,
            activo=True,
            orden=1,
        )
        session.add(pp_a_chica)
        session.add(pp_a_grande)
        session.flush()
        pp_a_chica_id = int(pp_a_chica.id)
        pp_a_grande_id = int(pp_a_grande.id)
        session.add(Precio(id_producto_presentacion=pp_a_chica_id, precio=Decimal("100.00")))
        session.add(Precio(id_producto_presentacion=pp_a_grande_id, precio=Decimal("200.00")))
        session.commit()
    return {
        "comercio_id": comercio_id,
        "categoria_id": categoria_id,
        "producto_a_id": producto_a_id,
        "producto_b_id": producto_b_id,
        "pp_a_chica_id": pp_a_chica_id,
        "pp_a_grande_id": pp_a_grande_id,
        "presentacion_chica_id": presentacion_chica_id,
        "presentacion_grande_id": presentacion_grande_id,
        "suffix": suffix,
    }


def _delete_comercio(comercio_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        from backend.models import ProductoAlias, ProductoPresentacion

        producto_ids_subquery = select(Producto.id).where(
            Producto.id_categoria_producto.in_(
                select(CategoriaProducto.id).where(
                    CategoriaProducto.id_comercio == comercio_id
                )
            )
        )
        presentacion_ids_subquery = select(ProductoPresentacion.id).where(
            ProductoPresentacion.id_producto.in_(producto_ids_subquery)
        )
        session.execute(
            delete(ProductoAlias).where(
                ProductoAlias.id_producto.in_(producto_ids_subquery)
            )
        )
        session.execute(
            delete(Precio).where(
                Precio.id_producto_presentacion.in_(presentacion_ids_subquery)
            )
        )
        session.execute(
            delete(ProductoPresentacion).where(
                ProductoPresentacion.id_producto.in_(producto_ids_subquery)
            )
        )
        session.execute(delete(Producto).where(Producto.id.in_(producto_ids_subquery)))
        session.execute(
            delete(CategoriaProducto).where(
                CategoriaProducto.id_comercio == comercio_id
            )
        )
        session.execute(
            delete(Presentacion).where(Presentacion.id_comercio == comercio_id)
        )
        session.execute(delete(Comercio).where(Comercio.id == comercio_id))


class ProductoAliasSchemaTest(unittest.TestCase):
    def test_table_and_required_columns_exist(self):
        with engine.connect() as c:
            rows = c.execute(
                text(
                    "SELECT column_name, data_type, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'producto_aliases' "
                    "ORDER BY ordinal_position"
                )
            ).all()
        names = {row[0] for row in rows}
        self.assertEqual(
            names,
            {
                "id",
                "id_producto",
                "id_producto_presentacion",
                "alias",
                "alias_normalizado",
                "activo",
                "fecha_alta",
                "fecha_ultima_modificacion",
            },
        )
        for name, data_type, is_nullable in rows:
            if name in {"id", "id_producto", "alias", "alias_normalizado", "activo"}:
                self.assertEqual(is_nullable, "NO", f"{name} should be NOT NULL")

    def test_required_indexes_present(self):
        with engine.connect() as c:
            rows = c.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'producto_aliases'"
                )
            ).all()
        names = {row[0] for row in rows}
        self.assertIn("ix_producto_aliases_id_producto", names)
        self.assertIn("ix_producto_aliases_id_producto_presentacion", names)
        self.assertIn("ix_producto_aliases_alias_normalizado", names)
        self.assertIn("ix_producto_aliases_activo", names)
        self.assertIn("producto_alias_general_unique", names)
        self.assertIn("producto_alias_presentacion_unique", names)

    def test_partial_unique_indexes_are_partial(self):
        with engine.connect() as c:
            partial = c.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE tablename = 'producto_aliases' "
                    "AND indexname IN ("
                    "'producto_alias_general_unique', "
                    "'producto_alias_presentacion_unique'"
                    ")"
                )
            ).all()
        for _name, definition in partial:
            self.assertIn("WHERE", definition)


class ProductoAliasPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])

    def test_general_alias_persists(self):
        with TestingSessionLocal() as session, session.begin():
            service = ProductoAliasService(session)
            row = service.create(
                id_producto=self.fixtures["producto_a_id"],
                alias="muzza",
            )
            self.assertIsNotNone(row.id)
            self.assertIsNone(row.id_producto_presentacion)
            self.assertEqual(row.alias_normalizado, "mozzarella")
            self.assertTrue(row.activo)

    def test_presentation_specific_alias_persists(self):
        with TestingSessionLocal() as session, session.begin():
            service = ProductoAliasService(session)
            row = service.create(
                id_producto=self.fixtures["producto_a_id"],
                alias="muzza-chica",
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
            self.assertIsNotNone(row.id)
            self.assertEqual(
                row.id_producto_presentacion,
                self.fixtures["pp_a_chica_id"],
            )
            self.assertEqual(row.alias_normalizado, "mozzarella chica")

    def test_empty_normalized_alias_is_rejected(self):
        with TestingSessionLocal() as session, session.begin():
            service = ProductoAliasService(session)
            with self.assertRaises(InvalidProductoAlias):
                service.create(
                    id_producto=self.fixtures["producto_a_id"],
                    alias="   ",
                )

    def test_presentation_ownership_mismatch_rejected(self):
        with TestingSessionLocal() as session, session.begin():
            service = ProductoAliasService(session)
            with self.assertRaises(ProductoAliasPresentationMismatch):
                service.create(
                    id_producto=self.fixtures["producto_b_id"],
                    alias="muzza-en-b",
                    id_producto_presentacion=self.fixtures["pp_a_chica_id"],
                )

    def test_duplicate_general_alias_rejected(self):
        with TestingSessionLocal() as session, session.begin():
            service = ProductoAliasService(session)
            service.create(
                id_producto=self.fixtures["producto_a_id"],
                alias="muzza",
            )
            with self.assertRaises(DuplicateProductoAlias):
                service.create(
                    id_producto=self.fixtures["producto_a_id"],
                    alias="muzzarela",
                )

    def test_duplicate_presentation_alias_rejected(self):
        with TestingSessionLocal() as session, session.begin():
            service = ProductoAliasService(session)
            service.create(
                id_producto=self.fixtures["producto_a_id"],
                alias="muzza-chica",
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
            with self.assertRaises(DuplicateProductoAlias):
                service.create(
                    id_producto=self.fixtures["producto_a_id"],
                    alias="muzzarela-chica",
                    id_producto_presentacion=self.fixtures["pp_a_chica_id"],
                )

    def test_shared_alias_across_products_allowed(self):
        with TestingSessionLocal() as session, session.begin():
            service = ProductoAliasService(session)
            row_a = service.create(
                id_producto=self.fixtures["producto_a_id"],
                alias="tradicional",
            )
            row_b = service.create(
                id_producto=self.fixtures["producto_b_id"],
                alias="tradicional",
            )
            self.assertNotEqual(row_a.id, row_b.id)
            self.assertEqual(row_a.alias_normalizado, "tradicional")
            self.assertEqual(row_b.alias_normalizado, "tradicional")

    def test_same_alias_different_scopes_allowed(self):
        with TestingSessionLocal() as session, session.begin():
            service = ProductoAliasService(session)
            general = service.create(
                id_producto=self.fixtures["producto_a_id"],
                alias="muzza",
            )
            specific = service.create(
                id_producto=self.fixtures["producto_a_id"],
                alias="muzza",
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
            self.assertNotEqual(general.id, specific.id)
            self.assertEqual(general.alias_normalizado, specific.alias_normalizado)


class ProductoAliasRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])

    def test_list_active_by_producto_ids_excludes_inactive(self):
        with TestingSessionLocal() as session, session.begin():
            service = ProductoAliasService(session)
            active = service.create(
                id_producto=self.fixtures["producto_a_id"],
                alias="muzza",
            )
            inactive = service.create(
                id_producto=self.fixtures["producto_a_id"],
                alias="fugazzeta-relativa",
            )
            inactive.activo = False
            session.flush()
            rows = ProductoAliasRepository(session).list_active_by_producto_ids(
                [self.fixtures["producto_a_id"]]
            )
            self.assertEqual([row.id for row in rows], [active.id])

    def test_list_active_by_producto_presentacion_ids_isolates_siblings(self):
        with TestingSessionLocal() as session, session.begin():
            service = ProductoAliasService(session)
            chica = service.create(
                id_producto=self.fixtures["producto_a_id"],
                alias="muzza-chica",
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
            grande = service.create(
                id_producto=self.fixtures["producto_a_id"],
                alias="muzza-grande",
                id_producto_presentacion=self.fixtures["pp_a_grande_id"],
            )
            session.flush()
            repo = ProductoAliasRepository(session)
            chica_rows = repo.list_active_by_producto_presentacion_ids(
                [self.fixtures["pp_a_chica_id"]]
            )
            grande_rows = repo.list_active_by_producto_presentacion_ids(
                [self.fixtures["pp_a_grande_id"]]
            )
            self.assertEqual([row.id for row in chica_rows], [chica.id])
            self.assertEqual([row.id for row in grande_rows], [grande.id])

    def test_recognition_data_batches_general_and_specific(self):
        with TestingSessionLocal() as session, session.begin():
            service = ProductoAliasService(session)
            service.create(
                id_producto=self.fixtures["producto_a_id"],
                alias="muzza",
            )
            service.create(
                id_producto=self.fixtures["producto_a_id"],
                alias="muzza-chica",
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
            session.flush()
            rows = ProductoAliasRepository(session).list_recognition_data(
                id_producto_values=[self.fixtures["producto_a_id"]],
                id_producto_presentacion_values=[
                    self.fixtures["pp_a_chica_id"],
                    self.fixtures["pp_a_grande_id"],
                ],
            )
            self.assertEqual(len(rows), 2)
            self.assertEqual(
                {row.alias_normalizado for row in rows},
                {"mozzarella", "mozzarella chica"},
            )

    def test_find_canonical_producto_in_comercio_is_exact(self):
        with TestingSessionLocal() as session, session.begin():
            repo = ProductoAliasRepository(session)
            match = repo.find_canonical_producto_in_comercio(
                self.fixtures["comercio_id"], "Pizza de Muzzarella"
            )
            self.assertIsNotNone(match)
            self.assertEqual(match.id, self.fixtures["producto_a_id"])
            miss = repo.find_canonical_producto_in_comercio(
                self.fixtures["comercio_id"], "pizza de muzzarella"
            )
            self.assertIsNone(miss)

    def test_cross_commerce_isolation(self):
        other_fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, other_fixtures["comercio_id"])
        with TestingSessionLocal() as session, session.begin():
            service = ProductoAliasService(session)
            service.create(
                id_producto=other_fixtures["producto_a_id"],
                alias="muzza",
            )
            session.flush()
            repo = ProductoAliasRepository(session)
            rows = repo.list_active_by_producto_ids(
                [self.fixtures["producto_a_id"]]
            )
            self.assertEqual(rows, [])


class ProductoAliasServiceOwnershipTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])

    def test_service_does_not_commit_or_rollback(self):
        with TestingSessionLocal() as session, session.begin():
            service = ProductoAliasService(session)
            initial_id: int | None = None
            service.create(
                id_producto=self.fixtures["producto_a_id"],
                alias="muzza",
            )
            session.flush()
            first = session.scalar(
                select(ProductoAlias).where(
                    ProductoAlias.id_producto == self.fixtures["producto_a_id"]
                )
            )
            self.assertIsNotNone(first)
            initial_id = first.id
            with self.assertRaises(DuplicateProductoAlias):
                service.create(
                    id_producto=self.fixtures["producto_a_id"],
                    alias="muzzarella",
                )
            rows = session.scalars(
                select(ProductoAlias).where(
                    ProductoAlias.id_producto == self.fixtures["producto_a_id"]
                )
            ).all()
            self.assertEqual([row.id for row in rows], [initial_id])


class ProductoAliasProjectionTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])

    def test_projection_groups_general_and_specific_aliases(self):
        with TestingSessionLocal() as session, session.begin():
            service = ProductoAliasService(session)
            service.create(
                id_producto=self.fixtures["producto_a_id"],
                alias="muzza",
            )
            service.create(
                id_producto=self.fixtures["producto_a_id"],
                alias="muzza-chica",
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
            )
            session.flush()
            catalog = [
                {
                    "producto_presentacion_id": self.fixtures["pp_a_chica_id"],
                    "producto_id": self.fixtures["producto_a_id"],
                },
                {
                    "producto_presentacion_id": self.fixtures["pp_a_grande_id"],
                    "producto_id": self.fixtures["producto_a_id"],
                },
            ]
            projection = service.project_recognition_data(catalog)
            chica = projection[
                (self.fixtures["producto_a_id"], self.fixtures["pp_a_chica_id"])
            ]
            grande = projection[
                (self.fixtures["producto_a_id"], self.fixtures["pp_a_grande_id"])
            ]
            self.assertEqual(chica.general_aliases, ("mozzarella",))
            self.assertEqual(chica.specific_aliases, ("mozzarella chica",))
            self.assertEqual(grande.general_aliases, ("mozzarella",))
            self.assertEqual(grande.specific_aliases, ())

    def test_projection_excludes_other_commerce(self):
        other = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, other["comercio_id"])
        with TestingSessionLocal() as session, session.begin():
            service = ProductoAliasService(session)
            service.create(
                id_producto=other["producto_a_id"],
                alias="muzza",
            )
            session.flush()
            catalog = [
                {
                    "producto_presentacion_id": self.fixtures["pp_a_chica_id"],
                    "producto_id": self.fixtures["producto_a_id"],
                }
            ]
            projection = service.project_recognition_data(catalog)
            row = projection[
                (self.fixtures["producto_a_id"], self.fixtures["pp_a_chica_id"])
            ]
            self.assertEqual(row.general_aliases, ())
            self.assertEqual(row.specific_aliases, ())


if __name__ == "__main__":
    unittest.main()
