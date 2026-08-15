"""Focused tests for ``ComunicacionFlavorService``.

The service is the single application boundary that mutates
``Comercio.flavor_comunicacion_id``. These tests focus on:

* the selected flavor must be a known and active global flavor;
* the target comercio must exist;
* the same global flavor can be re-applied idempotently without
  triggering a flush on the unrelated session state;
* any unknown or inactive flavor is rejected without mutating the
  comercio;
* the service retains the existing caller-owned transaction
  contract: ``commit`` and ``rollback`` are NEVER called by the
  service itself.
"""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import MagicMock

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from backend.models import Comercio, FlavorComunicacion
from backend.repositories.comercio_repository import ComercioRepository
from backend.repositories.flavor_comunicacion_repository import (
    FlavorComunicacionRepository,
)
from backend.services.comunicacion_flavor_service import (
    ComunicacionFlavorService,
)
from backend.services.exceptions import (
    ComercioNotFound,
    FlavorComunicacionInactivo,
    FlavorComunicacionNotFound,
)

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False
)


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _estado_id_activo() -> int:
    with engine.connect() as conn:
        row = conn.execute(
            __import__("sqlalchemy").text(
                "SELECT id FROM estado_comercio WHERE estado = 'ACTIVO'"
            )
        ).first()
    if row is None:
        raise RuntimeError("estado ACTIVO not seeded")
    return int(row[0])


def _seed_comercio(suffix: str) -> int:
    with TestingSessionLocal() as session, session.begin():
        neutro_id = session.execute(
            select(FlavorComunicacion.id).where(
                FlavorComunicacion.codigo == "neutro"
            )
        ).scalar_one()
        comercio = Comercio(
            nombre_fantasia=f"Flavor Service {suffix}",
            nombre_corto=f"FS {suffix}",
            razon_social=f"Flavor Service SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+54916{suffix[:8]}",
            calle="Av. Flavor",
            numero="100",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"flavor-service-{suffix}",
            estado_id=_estado_id_activo(),
            flavor_comunicacion_id=neutro_id,
        )
        session.add(comercio)
        session.flush()
        comercio_id = int(comercio.id)
    return comercio_id


def _delete_comercio(comercio_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(delete(Comercio).where(Comercio.id == comercio_id))


def _add_temporary_inactive_flavor() -> int:
    with TestingSessionLocal() as session, session.begin():
        flavor = FlavorComunicacion(
            codigo=f"inactivo-{_suffix()}",
            nombre="Inactivo",
            descripcion="Inactivo",
            instruccion_llm="Inactivo",
            activo=False,
            version=1,
        )
        session.add(flavor)
        session.flush()
        flavor_id = int(flavor.id)
    return flavor_id


def _delete_temporary_flavor(flavor_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(FlavorComunicacion).where(
                FlavorComunicacion.id == flavor_id
            )
        )


class ComunicacionFlavorServiceActivationTest(unittest.TestCase):
    """Active selection: a known active global flavor replaces the
    current ``flavor_comunicacion_id`` for the target comercio and
    leaves every other comercio untouched."""

    def setUp(self) -> None:
        self.suffix = _suffix()
        self.comercio_id = _seed_comercio(self.suffix)
        self.addCleanup(_delete_comercio, self.comercio_id)

    def test_assign_active_flavor_updates_only_target(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            service = ComunicacionFlavorService(session)
            serio_id = session.execute(
                select(FlavorComunicacion.id).where(
                    FlavorComunicacion.codigo == "serio"
                )
            ).scalar_one()
            previous_other = session.execute(
                select(Comercio.flavor_comunicacion_id).where(
                    Comercio.id != self.comercio_id
                ).limit(1)
            ).first()
            result_comercio_id, result_flavor_codigo = service.assign_to_comercio(
                self.comercio_id, int(serio_id)
            )[0].id, service.assign_to_comercio(
                self.comercio_id, int(serio_id)
            )[1].codigo
        self.assertEqual(result_comercio_id, self.comercio_id)
        self.assertEqual(result_flavor_codigo, "serio")
        with engine.connect() as conn:
            stored = conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT flavor_comunicacion_id FROM comercios "
                    "WHERE id = :id"
                ),
                {"id": self.comercio_id},
            ).scalar_one()
            other = conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT flavor_comunicacion_id FROM comercios "
                    "WHERE id <> :id LIMIT 1"
                ),
                {"id": self.comercio_id},
            ).first()
        self.assertEqual(int(stored), int(serio_id))
        if previous_other is not None and other is not None:
            self.assertEqual(int(previous_other[0]), int(other[0]))

    def test_assign_same_active_flavor_is_idempotent(self) -> None:
        captured: list[tuple[int, str]] = []
        with TestingSessionLocal() as session, session.begin():
            service = ComunicacionFlavorService(session)
            serio_id = session.execute(
                select(FlavorComunicacion.id).where(
                    FlavorComunicacion.codigo == "serio"
                )
            ).scalar_one()
            first = service.assign_to_comercio(self.comercio_id, int(serio_id))
            captured.append((int(first[0].id), str(first[1].codigo)))
            second = service.assign_to_comercio(self.comercio_id, int(serio_id))
            captured.append((int(second[0].id), str(second[1].codigo)))
        self.assertEqual(captured[0][0], captured[1][0])
        self.assertEqual(captured[0][1], "serio")
        self.assertEqual(captured[1][1], "serio")


class ComunicacionFlavorServiceRejectionTest(unittest.TestCase):
    """The service rejects unknown or inactive flavors without
    mutating the commerce."""

    def setUp(self) -> None:
        self.suffix = _suffix()
        self.comercio_id = _seed_comercio(self.suffix)
        self.addCleanup(_delete_comercio, self.comercio_id)

    def test_unknown_flavor_id_is_rejected(self) -> None:
        with TestingSessionLocal() as session:
            service = ComunicacionFlavorService(session)
            with self.assertRaises(FlavorComunicacionNotFound):
                service.assign_to_comercio(self.comercio_id, 999_999_999)
        with engine.connect() as conn:
            stored = conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT flavor_comunicacion_id FROM comercios "
                    "WHERE id = :id"
                ),
                {"id": self.comercio_id},
            ).scalar_one()
        neutro_id = None
        with engine.connect() as conn:
            neutro_id = conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT id FROM flavors_comunicacion "
                    "WHERE codigo = 'neutro'"
                )
            ).scalar_one()
        self.assertEqual(int(stored), int(neutro_id))

    def test_inactive_flavor_id_is_rejected(self) -> None:
        inactive_id = _add_temporary_inactive_flavor()
        self.addCleanup(_delete_temporary_flavor, inactive_id)
        with TestingSessionLocal() as session:
            service = ComunicacionFlavorService(session)
            with self.assertRaises(FlavorComunicacionInactivo):
                service.assign_to_comercio(self.comercio_id, inactive_id)
        with engine.connect() as conn:
            stored = conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT flavor_comunicacion_id FROM comercios "
                    "WHERE id = :id"
                ),
                {"id": self.comercio_id},
            ).scalar_one()
        with engine.connect() as conn:
            neutro_id = conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT id FROM flavors_comunicacion "
                    "WHERE codigo = 'neutro'"
                )
            ).scalar_one()
        self.assertEqual(int(stored), int(neutro_id))

    def test_unknown_comercio_is_rejected(self) -> None:
        with TestingSessionLocal() as session:
            service = ComunicacionFlavorService(session)
            serio_id = session.execute(
                select(FlavorComunicacion.id).where(
                    FlavorComunicacion.codigo == "serio"
                )
            ).scalar_one()
            with self.assertRaises(ComercioNotFound):
                service.assign_to_comercio(999_999_999, int(serio_id))


class ComunicacionFlavorServiceTransactionBoundaryTest(unittest.TestCase):
    """The service must never commit or roll back. The caller owns
    the transaction."""

    def test_assign_does_not_commit_or_rollback(self) -> None:
        session = MagicMock()
        service = ComunicacionFlavorService(session)
        service._flavor_repo = MagicMock()
        service._comercio_repo = MagicMock()
        service._flavor_repo.get_by_id.return_value = MagicMock(
            id=7, activo=True, codigo="serio"
        )
        service._comercio_repo.get_by_id.return_value = MagicMock(
            id=1, flavor_comunicacion_id=2
        )
        service.assign_to_comercio(1, 7)
        session.commit.assert_not_called()
        session.rollback.assert_not_called()

    def test_rejection_does_not_commit_or_rollback(self) -> None:
        session = MagicMock()
        service = ComunicacionFlavorService(session)
        service._flavor_repo = MagicMock()
        service._comercio_repo = MagicMock()
        service._comercio_repo.get_by_id.return_value = MagicMock(id=1)
        service._flavor_repo.get_by_id.return_value = None
        with self.assertRaises(FlavorComunicacionNotFound):
            service.assign_to_comercio(1, 99)
        session.commit.assert_not_called()
        session.rollback.assert_not_called()

    def test_list_active_does_not_commit_or_rollback(self) -> None:
        session = MagicMock()
        service = ComunicacionFlavorService(session)
        service._flavor_repo = MagicMock()
        service._flavor_repo.list_active.return_value = []
        service.list_active_flavors()
        session.commit.assert_not_called()
        session.rollback.assert_not_called()


class ComunicacionFlavorRepositoryReadOnlyTest(unittest.TestCase):
    """The repository is read-only; no method commits or rolls back."""

    def test_repository_methods_are_read_only(self) -> None:
        session = MagicMock()
        repo = FlavorComunicacionRepository(session)
        repo.list_active()
        repo.get_by_id(1)
        repo.get_by_codigo("neutro")
        session.commit.assert_not_called()
        session.rollback.assert_not_called()

    def test_comercio_repository_assignment_only_flushes(self) -> None:
        session = MagicMock()
        repo = ComercioRepository(session)
        comercio = MagicMock()
        repo.set_flavor_comunicacion(comercio, 5)
        comercio.flavor_comunicacion_id = 5
        session.flush.assert_called_once()
        session.commit.assert_not_called()
        session.rollback.assert_not_called()


class ComunicacionFlavorSafeExposureTest(unittest.TestCase):
    """The service exposes only ``id``, ``codigo``, ``nombre``,
    ``descripcion``, ``version`` and ``activo`` through the response
    schemas. The internal ``instruccion_llm`` must never be returned
    by the active listing endpoint."""

    def test_active_listing_excludes_instruccion_llm(self) -> None:
        from backend.schemas.comunicacion_flavor import (
            FlavorComunicacionResponse,
        )

        with TestingSessionLocal() as session:
            service = ComunicacionFlavorService(session)
            flavors = service.list_active_flavors()
            self.assertGreater(len(flavors), 0)
            for flavor in flavors:
                payload = FlavorComunicacionResponse.model_validate(flavor)
                dumped = payload.model_dump()
                self.assertNotIn("instruccion_llm", dumped)
                self.assertEqual(
                    set(dumped.keys()),
                    {
                        "id",
                        "codigo",
                        "nombre",
                        "descripcion",
                        "version",
                        "activo",
                    },
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
