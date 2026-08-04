"""Tests for the idempotent product alias seeder."""
from __future__ import annotations

import unittest
from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker

from backend.models import (
    CategoriaProducto,
    Comercio,
    Precio,
    Presentacion,
    Producto,
    ProductoAlias,
    ProductoPresentacion,
)
from backend.services.exceptions import UnsafeAliasSeederMapping
from backend.services.producto_alias_seeder import (
    PRODUCTO_WIDE_SEEDS,
    AliasSeed,
    SeederResult,
    run_seeder,
)
from backend.tests.test_producto_alias_model import (
    _delete_comercio,
    _estado_id_activo,
    _suffix,
)

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed_canonical_comercio(suffix: str | None = None) -> dict:
    """Create one comercio matching the seeder's canonical expectations."""
    suffix = suffix or _suffix()
    with TestingSessionLocal() as session, session.begin():
        comercio = Comercio(
            nombre_fantasia=f"Pizzería Test {suffix}",
            nombre_corto=f"PT {suffix}",
            razon_social=f"Pizzería Test SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+54911{suffix[:8]}",
            calle="Av. Test",
            numero="1234",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"pizzeria-test-{suffix}",
            estado_id=_estado_id_activo(),
        )
        session.add(comercio)
        session.flush()
        comercio_id = int(comercio.id)
        categoria = CategoriaProducto(
            id_comercio=comercio_id,
            descripcion="Pizzas",
            activo=True,
            orden=0,
        )
        session.add(categoria)
        session.flush()
        categoria_id = int(categoria.id)
        presentacion_unidad = Presentacion(
            id_comercio=comercio_id,
            codigo="unidad",
            descripcion="Unidad",
            activo=True,
            orden=0,
        )
        session.add(presentacion_unidad)
        session.flush()
        presentacion_id = int(presentacion_unidad.id)
        productos_data = (
            ("Pizza de Muzzarella", 0),
            ("Pizza Fugazzeta", 1),
            ("Pizza Napolitana", 2),
            ("Pizza Calabresa", 3),
        )
        producto_ids: dict[str, int] = {}
        for nombre, orden in productos_data:
            p = Producto(
                id_categoria_producto=categoria_id,
                nombre=nombre,
                descripcion=None,
                activo=True,
                disponible=True,
                orden=orden,
            )
            session.add(p)
            session.flush()
            producto_ids[nombre] = int(p.id)
        for nombre, pid in producto_ids.items():
            pp = ProductoPresentacion(
                id_producto=pid,
                id_presentacion=presentacion_id,
                activo=True,
                orden=0,
            )
            session.add(pp)
            session.flush()
            session.add(
                Precio(id_producto_presentacion=int(pp.id), precio=Decimal("100.00"))
            )
        session.commit()
    return {
        "comercio_id": comercio_id,
        "producto_ids": producto_ids,
        "short_name": f"PT {suffix}",
    }


class SeederResolutionTest(unittest.TestCase):
    def test_first_run_inserts_expected_aliases(self):
        suffix = _suffix()
        canonical = _seed_canonical_comercio(suffix)
        self.addCleanup(_delete_comercio, canonical["comercio_id"])
        with TestingSessionLocal() as session, session.begin():
            seeds: list[AliasSeed] = [
                AliasSeed(
                    comercio_nombre_corto=canonical["short_name"],
                    producto_nombre="Pizza de Muzzarella",
                    alias="muza",
                ),
                AliasSeed(
                    comercio_nombre_corto=canonical["short_name"],
                    producto_nombre="Pizza Fugazzeta",
                    alias="fugazeta",
                ),
                AliasSeed(
                    comercio_nombre_corto=canonical["short_name"],
                    producto_nombre="Pizza Calabresa",
                    alias="calabreza",
                ),
            ]
            result = run_seeder(session, seeds)
        self.assertEqual(result.inserted, 3)
        self.assertEqual(result.unchanged, 0)
        self.assertEqual(result.failed, 0)
        with TestingSessionLocal() as session:
            count = session.scalar(
                select(func.count()).select_from(ProductoAlias).where(
                    ProductoAlias.id_producto.in_(
                        list(canonical["producto_ids"].values())
                    )
                )
            )
        self.assertEqual(count, 3)

    def test_second_run_inserts_zero(self):
        suffix = _suffix()
        canonical = _seed_canonical_comercio(suffix)
        self.addCleanup(_delete_comercio, canonical["comercio_id"])
        seeds: list[AliasSeed] = [
            AliasSeed(
                comercio_nombre_corto=canonical["short_name"],
                producto_nombre="Pizza de Muzzarella",
                alias="muza",
            ),
            AliasSeed(
                comercio_nombre_corto=canonical["short_name"],
                producto_nombre="Pizza Napolitana",
                alias="napoli",
            ),
        ]
        with TestingSessionLocal() as session, session.begin():
            first = run_seeder(session, seeds)
        self.assertEqual(first.inserted, 2)
        with TestingSessionLocal() as session, session.begin():
            second = run_seeder(session, seeds)
        self.assertEqual(second.inserted, 0)
        self.assertEqual(second.unchanged, 2)
        self.assertEqual(second.failed, 0)

    def test_unsafe_required_mapping_raises_and_rolls_back(self):
        suffix = _suffix()
        canonical = _seed_canonical_comercio(suffix)
        self.addCleanup(_delete_comercio, canonical["comercio_id"])
        bad_seeds: list[AliasSeed] = [
            AliasSeed(
                comercio_nombre_corto=canonical["short_name"],
                producto_nombre="Pizza de Muzzarella",
                alias="muza",
            ),
            AliasSeed(
                comercio_nombre_corto=canonical["short_name"],
                producto_nombre="Producto Inexistente XYZ",
                alias="muzza",
            ),
        ]
        session = TestingSessionLocal()
        try:
            raised = False
            try:
                with session.begin():
                    run_seeder(session, bad_seeds)
            except UnsafeAliasSeederMapping:
                raised = True
            self.assertTrue(raised)
            session.rollback()
        finally:
            session.close()
        with TestingSessionLocal() as session2:
            rows = session2.scalars(
                select(ProductoAlias).where(
                    ProductoAlias.id_producto == canonical["producto_ids"]["Pizza de Muzzarella"]
                )
            ).all()
            self.assertEqual(rows, [])

    def test_failed_required_mapping_does_not_modify_unrelated_aliases(self):
        suffix = _suffix()
        canonical = _seed_canonical_comercio(suffix)
        self.addCleanup(_delete_comercio, canonical["comercio_id"])
        with TestingSessionLocal() as session, session.begin():
            session.add(
                ProductoAlias(
                    id_producto=canonical["producto_ids"]["Pizza Calabresa"],
                    id_producto_presentacion=None,
                    alias="independiente",
                    alias_normalizado="independiente",
                    activo=True,
                )
            )
        try:
            session = TestingSessionLocal()
            try:
                try:
                    with session.begin():
                        seeds: list[AliasSeed] = [
                            AliasSeed(
                                comercio_nombre_corto=canonical["short_name"],
                                producto_nombre="Pizza de Muzzarella",
                                alias="muza",
                            ),
                            AliasSeed(
                                comercio_nombre_corto=canonical["short_name"],
                                producto_nombre="Producto Inexistente XYZ",
                                alias="muzza",
                            ),
                        ]
                        run_seeder(session, seeds)
                except UnsafeAliasSeederMapping:
                    pass
                session.rollback()
            finally:
                session.close()
            with TestingSessionLocal() as session2:
                rows = session2.scalars(
                    select(ProductoAlias).where(
                        ProductoAlias.alias == "independiente"
                    )
                ).all()
                self.assertEqual(len(rows), 1)
        finally:
            with TestingSessionLocal() as session, session.begin():
                session.execute(
                    delete(ProductoAlias).where(ProductoAlias.alias == "independiente")
                )

    def test_zero_match_resolution_skips_silently(self):
        suffix = _suffix()
        canonical = _seed_canonical_comercio(suffix)
        self.addCleanup(_delete_comercio, canonical["comercio_id"])
        with TestingSessionLocal() as session, session.begin():
            seeds: list[AliasSeed] = [
                AliasSeed(
                    comercio_nombre_corto="Comercio Desconocido",
                    producto_nombre="Pizza de Muzzarella",
                    alias="muza",
                ),
            ]
            result = run_seeder(session, seeds)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.inserted, 0)

    def test_presentation_specific_seed_inserts_with_presentation(self):
        suffix = _suffix()
        canonical = _seed_canonical_comercio(suffix)
        self.addCleanup(_delete_comercio, canonical["comercio_id"])
        with TestingSessionLocal() as session, session.begin():
            seeds: list[AliasSeed] = [
                AliasSeed(
                    comercio_nombre_corto=canonical["short_name"],
                    producto_nombre="Pizza de Muzzarella",
                    alias="muzza-especial",
                    presentacion_codigo="unidad",
                ),
            ]
            result = run_seeder(session, seeds)
        self.assertEqual(result.inserted, 1)
        with TestingSessionLocal() as session:
            row = session.scalar(
                select(ProductoAlias).where(
                    ProductoAlias.alias == "muzza-especial"
                )
            )
            assert row is not None
            self.assertIsNotNone(row.id_producto_presentacion)
            self.assertEqual(row.alias_normalizado, "mozzarella especial")

    def test_canonical_seed_set_targets_known_comercios(self):
        seeds: Iterable[AliasSeed] = PRODUCTO_WIDE_SEEDS
        short_names = {seed.comercio_nombre_corto for seed in seeds}
        self.assertEqual(
            short_names,
            {
                "Pizzería Don Pepe",
                "El Hornero",
                "La Napoli",
                "Sole e Luna",
                "Forno Bravo",
            },
        )
        alias_count = sum(1 for seed in seeds if seed.alias in {"muza", "muzza"})
        self.assertEqual(alias_count, 10)


__all__ = ["SeederResult", "run_seeder"]


if __name__ == "__main__":
    unittest.main()
