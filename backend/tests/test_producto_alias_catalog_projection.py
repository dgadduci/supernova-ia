"""Catalog projection tests for persisted product aliases.

Verifies that the commerce-wide and restricted-catalog projections attach
only the active aliases applicable to the requested product /
product-presentation IDs, exclude other-commerce and inactive aliases,
and batch the underlying query so no per-row DB access occurs.
"""
from __future__ import annotations

import unittest
from decimal import Decimal
from typing import Any
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import (
    CategoriaProducto,
    Comercio,
    Precio,
    Presentacion,
    Producto,
    ProductoPresentacion,
)
from backend.services.producto_alias_service import ProductoAliasService
from backend.services.producto_query_service import ProductoQueryService
from backend.tests.test_producto_alias_model import (
    _delete_comercio,
    _estado_id_activo,
    _suffix,
)

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed_paired_comercios(suffix: str | None = None) -> dict:
    """Seed two comercios with the same canonical product names."""
    suffix = suffix or _suffix()
    summary: dict[str, Any] = {"suffix": suffix, "comercios": []}
    for short_label, fantasia_label in (("A", "Comercio A"), ("B", "Comercio B")):
        with TestingSessionLocal() as session, session.begin():
            comercio = Comercio(
                nombre_fantasia=f"{fantasia_label} {suffix}",
                nombre_corto=f"{short_label} {suffix}",
                razon_social=f"{fantasia_label} SRL {suffix}",
                cuit=f"30-{suffix[:8]}-{short_label}",
                whatsapp=f"+54911{suffix[:8]}{short_label}",
                calle="Av. Alias",
                numero="100",
                piso_departamento=None,
                localidad="CABA",
                provincia="Buenos Aires",
                codigo_postal="C1000",
                slug=f"{short_label.lower()}-{suffix}",
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
            pc_id = int(presentacion_chica.id)
            pg_id = int(presentacion_grande.id)
            p = Producto(
                id_categoria_producto=categoria_id,
                nombre="Pizza de Muzzarella",
                descripcion=None,
                activo=True,
                disponible=True,
                orden=0,
            )
            session.add(p)
            session.flush()
            producto_id = int(p.id)
            pp_chica = ProductoPresentacion(
                id_producto=producto_id,
                id_presentacion=pc_id,
                activo=True,
                orden=0,
            )
            pp_grande = ProductoPresentacion(
                id_producto=producto_id,
                id_presentacion=pg_id,
                activo=True,
                orden=1,
            )
            session.add(pp_chica)
            session.add(pp_grande)
            session.flush()
            chica_pp_id = int(pp_chica.id)
            grande_pp_id = int(pp_grande.id)
            session.add(
                Precio(id_producto_presentacion=chica_pp_id, precio=Decimal("100.00"))
            )
            session.add(
                Precio(id_producto_presentacion=grande_pp_id, precio=Decimal("200.00"))
            )
        summary["comercios"].append(
            {
                "comercio_id": comercio_id,
                "producto_id": producto_id,
                "pp_chica_id": chica_pp_id,
                "pp_grande_id": grande_pp_id,
            }
        )
    return summary


class CatalogProjectionTest(unittest.TestCase):
    def setUp(self):
        self.summary = _seed_paired_comercios()
        for c in self.summary["comercios"]:
            self.addCleanup(_delete_comercio, c["comercio_id"])

    def test_commerce_wide_catalog_excludes_other_commerce_aliases(self):
        primary = self.summary["comercios"][0]
        other = self.summary["comercios"][1]
        with TestingSessionLocal() as session, session.begin():
            alias_service = ProductoAliasService(session)
            alias_service.create(
                id_producto=primary["producto_id"], alias="muzza"
            )
            alias_service.create(
                id_producto=other["producto_id"], alias="otra-muzza"
            )
        with TestingSessionLocal() as session, session.begin():
            service = ProductoQueryService(session)
            catalog = service.list_recognizer_catalog(primary["comercio_id"])
        for row in catalog:
            aliases = row.get("aliases") or {}
            self.assertEqual(
                aliases.get("general_aliases", []),
                ["mozzarella"],
                f"unexpected general aliases: {aliases}",
            )
            self.assertEqual(aliases.get("specific_aliases", []), [])

    def test_restricted_catalog_attaches_only_presentation_specific_aliases(self):
        primary = self.summary["comercios"][0]
        with TestingSessionLocal() as session, session.begin():
            alias_service = ProductoAliasService(session)
            alias_service.create(
                id_producto=primary["producto_id"],
                alias="chica-muzza",
                id_producto_presentacion=primary["pp_chica_id"],
            )
            alias_service.create(
                id_producto=primary["producto_id"], alias="muzza"
            )
        with TestingSessionLocal() as session, session.begin():
            service = ProductoQueryService(session)
            restricted = service.list_presentaciones_by_ids(
                [primary["pp_chica_id"]]
            )
        self.assertEqual(len(restricted), 1)
        aliases = restricted[0].get("aliases") or {}
        self.assertEqual(aliases.get("specific_aliases"), ["chica mozzarella"])
        self.assertEqual(aliases.get("general_aliases"), ["mozzarella"])

    def test_inactive_alias_excluded_from_projection(self):
        primary = self.summary["comercios"][0]
        with TestingSessionLocal() as session, session.begin():
            alias_service = ProductoAliasService(session)
            alias_service.create(
                id_producto=primary["producto_id"], alias="muzza"
            )
            inactive = alias_service.create(
                id_producto=primary["producto_id"], alias="muzzarella-inactiva"
            )
            inactive.activo = False
            session.flush()
        with TestingSessionLocal() as session, session.begin():
            service = ProductoQueryService(session)
            catalog = service.list_recognizer_catalog(primary["comercio_id"])
        for row in catalog:
            aliases = row.get("aliases") or {}
            self.assertEqual(aliases.get("general_aliases"), ["mozzarella"])

    def test_alias_loading_is_batched(self):
        primary = self.summary["comercios"][0]
        with TestingSessionLocal() as session, session.begin():
            ProductoAliasService(session).create(
                id_producto=primary["producto_id"], alias="muzza"
            )
        with TestingSessionLocal() as session, session.begin():
            service = ProductoQueryService(session)
            with patch.object(
                ProductoAliasService,
                "project_recognition_data",
                wraps=service._alias_service.project_recognition_data,
            ) as spy:
                service.list_recognizer_catalog(primary["comercio_id"])
                self.assertEqual(spy.call_count, 1)

    def test_catalog_without_aliases_supports_legacy_consumers(self):
        with TestingSessionLocal() as session, session.begin():
            service = ProductoQueryService(session)
            catalog = service.list_recognizer_catalog(
                self.summary["comercios"][0]["comercio_id"]
            )
            from backend.recognizers.fuzzy_product_recognizer import (
                FuzzyProductRecognizer,
            )

            recognizer = FuzzyProductRecognizer()
            result = recognizer.recognize("pizza muzza", catalog)
            self.assertIn("encontrados", result)
            self.assertIn("encontrados_posibles", result)
            self.assertIn("encontrados_no_disponibles", result)
            self.assertIn("no_encontrados", result)


if __name__ == "__main__":
    unittest.main()
