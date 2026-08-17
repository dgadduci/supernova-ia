"""Focused tests for the typed ``ComercioService.update`` boundary.

The tests cover the documented contract of the
``add-commerce-admin`` change:

* The service accepts only the closed set of permitted basic fields
  (profile, address, ``estado_id``, ``zona_horaria``, ``moneda``,
  ``idioma``). Any value submitted under the routing-identifier keys
  (``whatsapp`` / ``slug``) is rejected with ``ValueError`` BEFORE
  any database call.
* The service resolves the exact commerce and verifies the
  ``estado_id`` exists; unknown commerce / unknown status are
  rejected with the documented domain exceptions.
* The service owns the commit / rollback boundary. The repository
  never commits / rolls back. On any exception during staging the
  service rolls back the entire attempt so the prior ``Comercio``
  row remains unchanged.
* Routing identifiers, flavor assignment, association tables,
  catalog and any other ORM-managed attribute are NEVER mutated by
  the update path. The tests stub the repository and assert the
  exact field set it was asked to mutate.

The tests mock the repository so no real database or embedding
provider is touched.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.services.comercio_service import ComercioService
from backend.services.exceptions import (
    ComercioNotFound,
    DuplicateSlug,
    DuplicateWhatsapp,
    EstadoComercioNotFound,
)


class _FakeComercio:
    """In-memory stand-in for :class:`backend.models.Comercio`."""

    def __init__(
        self,
        *,
        id: int,
        whatsapp: str = "+5491100000000",
        slug: str = "comercio-base",
        estado_id: int = 1,
        flavor_comunicacion_id: int | None = 2,
        flavor_comunicacion: object = None,
    ) -> None:
        self.id = id
        self.whatsapp = whatsapp
        self.slug = slug
        self.estado_id = estado_id
        self.flavor_comunicacion_id = flavor_comunicacion_id
        self.flavor_comunicacion = flavor_comunicacion
        self.nombre_fantasia = "Base"
        self.nombre_corto = "B"
        self.razon_social = "Base SRL"
        self.cuit = "30-12345678-9"
        self.calle = "Calle 1"
        self.numero = "100"
        self.piso_departamento = None
        self.localidad = "CABA"
        self.provincia = "CABA"
        self.codigo_postal = None
        self.zona_horaria = "America/Argentina/Buenos_Aires"
        self.moneda = "ARS"
        self.idioma = "es-AR"
        self.fecha_alta = "2026-01-01T00:00:00Z"
        self.fecha_ultima_modificacion = "2026-01-01T00:00:00Z"
        self.fecha_baja = None


def _build_service(
    *,
    comercio: _FakeComercio | None,
    estado_exists: bool = True,
) -> tuple[ComercioService, MagicMock, MagicMock]:
    """Build a ``ComercioService`` with mocked session + repository."""
    repo = MagicMock(name="ComercioRepository")
    repo.get_by_id.return_value = comercio
    repo.estado_exists.return_value = estado_exists
    repo.update_profile = MagicMock(return_value=None)

    session: MagicMock = MagicMock(name="DatabaseSession")
    session.flush = MagicMock()
    session.refresh = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()

    service = ComercioService(session)
    service._repo = repo  # type: ignore[attr-defined]
    return service, session, repo


class ComercioServiceUpdateTest(unittest.TestCase):
    def test_update_rejects_whatsapp_in_payload_before_repo(self) -> None:
        service, _, repo = _build_service(comercio=_FakeComercio(id=1))
        with self.assertRaises(ValueError) as ctx:
            service.update(
                1,
                {
                    "nombre_fantasia": "X",
                    "nombre_corto": "X",
                    "razon_social": "X",
                    "cuit": "30-12345678-9",
                    "calle": "C",
                    "numero": "1",
                    "localidad": "CABA",
                    "provincia": "CABA",
                    "estado_id": 1,
                    "zona_horaria": "America/Argentina/Buenos_Aires",
                    "moneda": "ARS",
                    "idioma": "es-AR",
                    "whatsapp": "+5491199999999",
                },
            )
        self.assertIn("inmutables", str(ctx.exception).lower())
        repo.update_profile.assert_not_called()

    def test_update_rejects_slug_in_payload_before_repo(self) -> None:
        service, _, repo = _build_service(comercio=_FakeComercio(id=1))
        with self.assertRaises(ValueError):
            service.update(
                1,
                {
                    "nombre_fantasia": "X",
                    "nombre_corto": "X",
                    "razon_social": "X",
                    "cuit": "30-12345678-9",
                    "calle": "C",
                    "numero": "1",
                    "localidad": "CABA",
                    "provincia": "CABA",
                    "estado_id": 1,
                    "zona_horaria": "America/Argentina/Buenos_Aires",
                    "moneda": "ARS",
                    "idioma": "es-AR",
                    "slug": "renombrado",
                },
            )
        repo.update_profile.assert_not_called()

    def test_update_calls_repository_with_permitted_field_set_only(self) -> None:
        comercio = _FakeComercio(id=1)
        service, session, repo = _build_service(comercio=comercio)
        result = service.update(
            1,
            {
                "nombre_fantasia": "Editado",
                "nombre_corto": "E",
                "razon_social": "Editado SRL",
                "cuit": "30-98765432-1",
                "calle": "Nueva Calle",
                "numero": "200",
                "piso_departamento": "2B",
                "localidad": "Córdoba",
                "provincia": "Córdoba",
                "codigo_postal": "5000",
                "estado_id": 2,
                "zona_horaria": "America/Argentina/Cordoba",
                "moneda": "USD",
                "idioma": "en-US",
            },
        )
        self.assertIs(result, comercio)
        repo.update_profile.assert_called_once()
        kwargs = repo.update_profile.call_args.kwargs
        for forbidden in ("whatsapp", "slug", "flavor_comunicacion_id", "id"):
            self.assertNotIn(forbidden, kwargs)
        self.assertEqual(kwargs["nombre_fantasia"], "Editado")
        self.assertEqual(kwargs["estado_id"], 2)
        self.assertEqual(kwargs["moneda"], "USD")
        session.commit.assert_called_once()
        session.rollback.assert_not_called()

    def test_update_rolls_back_on_repository_failure(self) -> None:
        comercio = _FakeComercio(id=1)
        service, session, repo = _build_service(comercio=comercio)
        repo.update_profile.side_effect = RuntimeError("db boom")
        with self.assertRaises(RuntimeError):
            service.update(
                1,
                {
                    "nombre_fantasia": "X",
                    "nombre_corto": "X",
                    "razon_social": "X",
                    "cuit": "30-12345678-9",
                    "calle": "C",
                    "numero": "1",
                    "localidad": "CABA",
                    "provincia": "CABA",
                    "estado_id": 1,
                    "zona_horaria": "America/Argentina/Buenos_Aires",
                    "moneda": "ARS",
                    "idioma": "es-AR",
                },
            )
        session.rollback.assert_called_once()
        session.commit.assert_not_called()

    def test_update_rejects_unknown_comercio(self) -> None:
        service, session, repo = _build_service(comercio=None)
        with self.assertRaises(ComercioNotFound):
            service.update(
                999,
                {
                    "nombre_fantasia": "X",
                    "nombre_corto": "X",
                    "razon_social": "X",
                    "cuit": "30-12345678-9",
                    "calle": "C",
                    "numero": "1",
                    "localidad": "CABA",
                    "provincia": "CABA",
                    "estado_id": 1,
                    "zona_horaria": "America/Argentina/Buenos_Aires",
                    "moneda": "ARS",
                    "idioma": "es-AR",
                },
            )
        repo.update_profile.assert_not_called()
        session.commit.assert_not_called()

    def test_update_rejects_unknown_estado(self) -> None:
        comercio = _FakeComercio(id=1)
        service, session, repo = _build_service(comercio=comercio, estado_exists=False)
        with self.assertRaises(EstadoComercioNotFound):
            service.update(
                1,
                {
                    "nombre_fantasia": "X",
                    "nombre_corto": "X",
                    "razon_social": "X",
                    "cuit": "30-12345678-9",
                    "calle": "C",
                    "numero": "1",
                    "localidad": "CABA",
                    "provincia": "CABA",
                    "estado_id": 99,
                    "zona_horaria": "America/Argentina/Buenos_Aires",
                    "moneda": "ARS",
                    "idioma": "es-AR",
                },
            )
        repo.update_profile.assert_not_called()
        session.commit.assert_not_called()

    def test_update_rejects_blank_required_field(self) -> None:
        comercio = _FakeComercio(id=1)
        service, session, repo = _build_service(comercio=comercio)
        with self.assertRaises(ValueError):
            service.update(
                1,
                {
                    "nombre_fantasia": "   ",
                    "nombre_corto": "X",
                    "razon_social": "X",
                    "cuit": "30-12345678-9",
                    "calle": "C",
                    "numero": "1",
                    "localidad": "CABA",
                    "provincia": "CABA",
                    "estado_id": 1,
                    "zona_horaria": "America/Argentina/Buenos_Aires",
                    "moneda": "ARS",
                    "idioma": "es-AR",
                },
            )
        repo.update_profile.assert_not_called()
        session.commit.assert_not_called()

    def test_update_rejects_non_integer_estado(self) -> None:
        comercio = _FakeComercio(id=1)
        service, session, repo = _build_service(comercio=comercio)
        with self.assertRaises(ValueError):
            service.update(
                1,
                {
                    "nombre_fantasia": "X",
                    "nombre_corto": "X",
                    "razon_social": "X",
                    "cuit": "30-12345678-9",
                    "calle": "C",
                    "numero": "1",
                    "localidad": "CABA",
                    "provincia": "CABA",
                    "estado_id": "not-int",
                    "zona_horaria": "America/Argentina/Buenos_Aires",
                    "moneda": "ARS",
                    "idioma": "es-AR",
                },
            )
        repo.update_profile.assert_not_called()
        session.commit.assert_not_called()


class ComercioServiceCreateRegressionTest(unittest.TestCase):
    """The ``create`` boundary must not be weakened by the new
    ``update`` boundary. The OpenSpec change authorises both
    operations; ``create`` continues to own duplicate detection and
    the post-create ``refresh`` of ``flavor_comunicacion``."""

    def test_create_still_rejects_duplicate_whatsapp_before_repo(self) -> None:
        service, _, repo = _build_service(comercio=None)
        repo.get_by_whatsapp.return_value = _FakeComercio(id=2)
        with self.assertRaises(DuplicateWhatsapp):
            service.create(
                {
                    "nombre_fantasia": "X",
                    "nombre_corto": "X",
                    "razon_social": "X",
                    "cuit": "30-12345678-9",
                    "whatsapp": "+5491100000000",
                    "calle": "C",
                    "numero": "1",
                    "localidad": "CABA",
                    "provincia": "CABA",
                    "slug": "nuevo",
                    "estado_id": 1,
                }
            )
        repo.create.assert_not_called()

    def test_create_still_rejects_duplicate_slug_before_repo(self) -> None:
        service, _, repo = _build_service(comercio=None)
        repo.get_by_whatsapp.return_value = None
        repo.get_by_slug.return_value = _FakeComercio(id=2)
        with self.assertRaises(DuplicateSlug):
            service.create(
                {
                    "nombre_fantasia": "X",
                    "nombre_corto": "X",
                    "razon_social": "X",
                    "cuit": "30-12345678-9",
                    "whatsapp": "+5491100000001",
                    "calle": "C",
                    "numero": "1",
                    "localidad": "CABA",
                    "provincia": "CABA",
                    "slug": "existente",
                    "estado_id": 1,
                }
            )
        repo.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
