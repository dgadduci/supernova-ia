"""Real-database coverage of the commerce catalog view's
isolation against inconsistent ``ProductoPresentacion`` rows.

The catalog query joins ``Producto`` -> ``CategoriaProducto`` to
verify that the product's category belongs to the requested
``comercio_id``. A naive query that only filters on
``Presentacion.id_comercio`` would let an inconsistent
``ProductoPresentacion`` row that joins a category-A product with a
commerce-B presentation leak a category-A product name into
commerce B's catalog. This module seeds the inconsistency
directly against the live ``supernova_test`` database and proves
that the view loader drops it for both commerces.
"""
from __future__ import annotations

import unittest
import uuid

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from backend.models import (
    CategoriaProducto,
    Comercio,
    EstadoComercio,
    Presentacion,
    Producto,
    ProductoPresentacion,
)
from backend.services.pilot_order_operations_view_service import (
    PilotOrderOperationsViewService,
)

TEST_URL = "postgresql+psycopg:///supernova_test"
engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False
)


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _estado_id_activo() -> int:
    with engine.connect() as c:
        row = c.execute(
            select(EstadoComercio.id).where(EstadoComercio.estado == "ACTIVO")
        ).first()
        if row is None:
            raise RuntimeError("estado ACTIVO not seeded in supernova_test")
        return row[0]


def _seed_two_comercios(suffix: str) -> dict[str, int]:
    """Create two distinct active comercios and return their ids."""
    estado_id = _estado_id_activo()
    with TestingSessionLocal() as session, session.begin():
        comercio_a = Comercio(
            nombre_fantasia=f"CrossA {suffix}",
            nombre_corto=f"CrossA {suffix}",
            razon_social=f"CrossA SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+54981{suffix[:8]}",
            calle="Av. CrossA",
            numero="1",
            piso_departamento=None,
            localidad="CABA",
            provincia="BA",
            codigo_postal="C1000",
            slug=f"crossa-{suffix}",
            estado_id=estado_id,
        )
        session.add(comercio_a)
        session.flush()

        comercio_b = Comercio(
            nombre_fantasia=f"CrossB {suffix}",
            nombre_corto=f"CrossB {suffix}",
            razon_social=f"CrossB SRL {suffix}",
            cuit=f"31-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+54982{suffix[:8]}",
            calle="Av. CrossB",
            numero="1",
            piso_departamento=None,
            localidad="CABA",
            provincia="BA",
            codigo_postal="C1000",
            slug=f"crossb-{suffix}",
            estado_id=estado_id,
        )
        session.add(comercio_b)
        session.flush()

        return {
            "comercio_a_id": int(comercio_a.id),
            "comercio_b_id": int(comercio_b.id),
        }


def _seed_inconsistent_assoc(
    *, comercio_a_id: int, comercio_b_id: int
) -> dict[str, int]:
    """Seed a ``CategoriaProducto`` (A) + ``Producto`` (A) +
    ``Presentacion`` (B) triplet and link them through a
    ``ProductoPresentacion`` row.

    This is the inconsistent catalog state that the view's
    isolation guards must drop.
    """
    s = _suffix()
    with TestingSessionLocal() as session, session.begin():
        categoria_a = CategoriaProducto(
            id_comercio=comercio_a_id,
            descripcion=f"CatA {s}",
            activo=True,
            orden=0,
        )
        session.add(categoria_a)
        session.flush()

        producto_a = Producto(
            id_categoria_producto=categoria_a.id,
            nombre="SECRETO-A",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        session.add(producto_a)
        session.flush()

        presentacion_b = Presentacion(
            id_comercio=comercio_b_id,
            codigo=f"PXB_{s[:6]}",
            descripcion=f"PresB {s}",
            activo=True,
            orden=0,
        )
        session.add(presentacion_b)
        session.flush()

        assoc = ProductoPresentacion(
            id_producto=producto_a.id,
            id_presentacion=presentacion_b.id,
            activo=True,
            orden=0,
        )
        session.add(assoc)
        session.flush()

        return {
            "pp_id": int(assoc.id),
            "producto_a_id": int(producto_a.id),
            "presentacion_b_id": int(presentacion_b.id),
            "categoria_a_id": int(categoria_a.id),
        }


def _delete_comercio(comercio_id: int) -> None:
    from sqlalchemy import text

    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(ProductoPresentacion).where(
                ProductoPresentacion.id_producto.in_(
                    select(Producto.id).where(
                        Producto.id_categoria_producto.in_(
                            select(CategoriaProducto.id).where(
                                CategoriaProducto.id_comercio == comercio_id
                            )
                        )
                    )
                )
            )
        )
        session.execute(
            delete(ProductoPresentacion).where(
                ProductoPresentacion.id_presentacion.in_(
                    select(Presentacion.id).where(
                        Presentacion.id_comercio == comercio_id
                    )
                )
            )
        )
        session.execute(
            delete(Producto).where(
                Producto.id_categoria_producto.in_(
                    select(CategoriaProducto.id).where(
                        CategoriaProducto.id_comercio == comercio_id
                    )
                )
            )
        )
        session.execute(
            delete(CategoriaProducto).where(
                CategoriaProducto.id_comercio == comercio_id
            )
        )
        session.execute(
            delete(Presentacion).where(
                Presentacion.id_comercio == comercio_id
            )
        )
        session.execute(
            text(
                "SELECT 1"
            )
        )
        session.execute(delete(Comercio).where(Comercio.id == comercio_id))


class CrossCommerceCatalogIsolationTest(unittest.TestCase):
    """Prove the catalog view drops cross-commerce associations.

    The fixture seeds an inconsistent ``ProductoPresentacion``
    row that joins a category-A product with a commerce-B
    presentation. The view loader MUST exclude this row from
    both commerce A's and commerce B's catalog because:

    * the ``Producto`` belongs to comercio A's category, so
      querying comercio B must not surface the A product name;
    * the ``Presentacion`` belongs to comercio B, so querying
      comercio A must not surface the B presentation row.
    """

    def setUp(self) -> None:
        suffix = _suffix()
        ids = _seed_two_comercios(suffix)
        self.comercio_a_id = ids["comercio_a_id"]
        self.comercio_b_id = ids["comercio_b_id"]
        assoc = _seed_inconsistent_assoc(
            comercio_a_id=self.comercio_a_id,
            comercio_b_id=self.comercio_b_id,
        )
        self.pp_id = assoc["pp_id"]
        self.addCleanup(_delete_comercio, self.comercio_a_id)
        self.addCleanup(_delete_comercio, self.comercio_b_id)

    def test_commerce_b_catalog_excludes_cross_commerce_row(self) -> None:
        with TestingSessionLocal() as session:
            view = (
                PilotOrderOperationsViewService(session)
                .get_commerce_catalog_price_availability(
                    self.comercio_b_id
                )
            )
        self.assertIsNotNone(view)
        assert view is not None
        for row in view.rows:
            self.assertNotIn(
                "SECRETO-A", row.producto_nombre
            )

    def test_commerce_a_catalog_excludes_cross_commerce_row(self) -> None:
        with TestingSessionLocal() as session:
            view = (
                PilotOrderOperationsViewService(session)
                .get_commerce_catalog_price_availability(
                    self.comercio_a_id
                )
            )
        self.assertIsNotNone(view)
        assert view is not None
        for row in view.rows:
            self.assertNotIn(
                "SECRETO-A", row.producto_nombre
            )


if __name__ == "__main__":
    unittest.main()