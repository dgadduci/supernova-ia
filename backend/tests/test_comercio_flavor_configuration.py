"""Focused tests for the ``/flavors-comunicacion`` and
``/comercios/{comercio_id}/flavor-comunicacion`` administrative
endpoints.

The Phase-1 contract for the assignment endpoint is:

* the endpoint is authenticated by the existing admin header token;
* the payload accepts only ``flavor_comunicacion_id`` (a global flavor
  ID);
* active global flavors replace the target comercio's selection and
  leave every other comercio untouched;
* unknown or inactive global flavor IDs are rejected, the
  comercio's FK is preserved, and the response is the documented
  status code (``404`` for unknown flavor, ``409`` for inactive,
  ``404`` for unknown comercio);
* the response is the standard ``ComercioResponse``, which embeds
  the safe flavor summary (no ``instruccion_llm``).

The Phase-1 contract for the administrative listing endpoint is:

* the endpoint is authenticated by the existing admin header token;
* the response lists every active global flavor and includes the
  persisted ``instruccion_llm`` exactly, bounded by the catalog
  column shape (non-empty, max 2000 characters);
* inactive flavors remain absent from the listing;
* the listing performs no mutation and does not control the session
  transaction;
* the listing is the only surface that exposes
  ``instruccion_llm``; every commerce and configuration read keeps
  the safe ``FlavorComunicacionSummary`` projection.
"""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

import backend.dependencies as dependencies_module
import backend.routers.flavors_comunicacion as router_module
from backend.config import settings as settings_module
from backend.config.settings import Settings
from backend.dependencies import get_session, require_admin_token
from backend.models import Comercio, FlavorComunicacion
from backend.services.comunicacion_flavor_service import (
    ComunicacionFlavorService,
)
from backend.services.exceptions import (
    ComercioNotFound,
    FlavorComunicacionInactivo,
    FlavorComunicacionNotFound,
)

CONFIGURED_TOKEN = "flavor-selection-test-token"

TEST_URL = "postgresql+psycopg:///supernova_test"
engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False
)


def _settings(token: str | None = CONFIGURED_TOKEN) -> Settings:
    base = settings_module.load_settings()
    return Settings(**{**base.__dict__, "order_management_admin_token": token})


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _estado_id_activo() -> int:
    with engine.connect() as c:
        row = c.execute(
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
            nombre_fantasia=f"Flavor Config {suffix}",
            nombre_corto=f"FC {suffix}",
            razon_social=f"Flavor Config SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+54917{suffix[:8]}",
            calle="Av. Flavor",
            numero="100",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"flavor-config-{suffix}",
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


def _flavor_id(codigo: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT id FROM flavors_comunicacion "
                    "WHERE codigo = :codigo"
                ),
                {"codigo": codigo},
            ).scalar_one()
        )


def _stored_flavor(comercio_id: int) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT flavor_comunicacion_id FROM comercios "
                    "WHERE id = :id"
                ),
                {"id": comercio_id},
            ).scalar_one()
        )


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router_module.router)
    return app


def _override_session() -> object:
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


class AssignFlavorRuntimeTest(unittest.TestCase):
    """Uses the live database to verify the in-route behaviour."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = _build_app()
        cls.app.dependency_overrides[get_session] = _override_session
        cls.app.dependency_overrides[require_admin_token] = lambda: None
        cls.client = TestClient(cls.app)

    def setUp(self) -> None:
        self.suffix = _suffix()
        self.comercio_id = _seed_comercio(self.suffix)
        self.addCleanup(_delete_comercio, self.comercio_id)
        self.inactive_flavor_id = _add_temporary_inactive_flavor()
        self.addCleanup(
            _delete_temporary_flavor, self.inactive_flavor_id
        )

    def test_assign_active_flavor_updates_only_target(self) -> None:
        serio_id = _flavor_id("serio")
        with engine.connect() as conn:
            other_id = conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT id FROM comercios "
                    "WHERE id <> :id LIMIT 1"
                ),
                {"id": self.comercio_id},
            ).first()
            previous_other: int | None = None
            if other_id is not None:
                previous_other = int(
                    conn.execute(
                        __import__("sqlalchemy").text(
                            "SELECT flavor_comunicacion_id FROM comercios "
                            "WHERE id = :id"
                        ),
                        {"id": int(other_id[0])},
                    ).scalar_one()
                )
        response = self.client.put(
            f"/comercios/{self.comercio_id}/flavor-comunicacion",
            json={"flavor_comunicacion_id": serio_id},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["flavor_comunicacion"]["codigo"], "serio")
        self.assertEqual(_stored_flavor(self.comercio_id), serio_id)
        if other_id is not None and previous_other is not None:
            with engine.connect() as conn:
                after_other = int(
                    conn.execute(
                        __import__("sqlalchemy").text(
                            "SELECT flavor_comunicacion_id FROM comercios "
                            "WHERE id = :id"
                        ),
                        {"id": int(other_id[0])},
                    ).scalar_one()
                )
            self.assertEqual(previous_other, after_other)

    def test_unknown_flavor_is_rejected_without_mutation(self) -> None:
        previous = _stored_flavor(self.comercio_id)
        response = self.client.put(
            f"/comercios/{self.comercio_id}/flavor-comunicacion",
            json={"flavor_comunicacion_id": 999_999_999},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(_stored_flavor(self.comercio_id), previous)

    def test_inactive_flavor_is_rejected_without_mutation(self) -> None:
        previous = _stored_flavor(self.comercio_id)
        response = self.client.put(
            f"/comercios/{self.comercio_id}/flavor-comunicacion",
            json={"flavor_comunicacion_id": self.inactive_flavor_id},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(_stored_flavor(self.comercio_id), previous)

    def test_unknown_comercio_is_rejected(self) -> None:
        response = self.client.put(
            "/comercios/999999999/flavor-comunicacion",
            json={"flavor_comunicacion_id": _flavor_id("serio")},
        )
        self.assertEqual(response.status_code, 404)

    def test_payload_rejects_descripcion(self) -> None:
        response = self.client.put(
            f"/comercios/{self.comercio_id}/flavor-comunicacion",
            json={
                "flavor_comunicacion_id": _flavor_id("serio"),
                "descripcion": "algo",
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_payload_rejects_instruccion_llm(self) -> None:
        response = self.client.put(
            f"/comercios/{self.comercio_id}/flavor-comunicacion",
            json={
                "flavor_comunicacion_id": _flavor_id("serio"),
                "instruccion_llm": "algo",
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_response_never_contains_instruccion_llm(self) -> None:
        response = self.client.put(
            f"/comercios/{self.comercio_id}/flavor-comunicacion",
            json={"flavor_comunicacion_id": _flavor_id("serio")},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn("instruccion_llm", payload)
        self.assertNotIn("instruccion_llm", payload["flavor_comunicacion"])
        self.assertEqual(
            set(payload["flavor_comunicacion"].keys()),
            {"id", "codigo", "nombre", "descripcion", "version", "activo"},
        )


class AssignFlavorAuthTest(unittest.TestCase):
    """The endpoint must remain behind the existing admin header
    token. When the token is missing or wrong, the router returns
    the documented 401 / 503 without invoking the service."""

    def setUp(self) -> None:
        self.app = _build_app()
        self.app.dependency_overrides[get_session] = _override_session
        self.client = TestClient(self.app)

    def test_missing_token_yields_401(self) -> None:
        with patch.object(
            dependencies_module, "load_settings", return_value=_settings()
        ):
            response = self.client.put(
                "/comercios/1/flavor-comunicacion",
                json={"flavor_comunicacion_id": 1},
            )
        self.assertEqual(response.status_code, 401)

    def test_wrong_token_yields_401(self) -> None:
        with patch.object(
            dependencies_module, "load_settings", return_value=_settings()
        ):
            response = self.client.put(
                "/comercios/1/flavor-comunicacion",
                json={"flavor_comunicacion_id": 1},
                headers={"X-Admin-Token": "wrong-token"},
            )
        self.assertEqual(response.status_code, 401)

    def test_missing_admin_config_yields_503(self) -> None:
        with patch.object(
            dependencies_module, "load_settings", return_value=_settings(None)
        ):
            response = self.client.put(
                "/comercios/1/flavor-comunicacion",
                json={"flavor_comunicacion_id": 1},
                headers={"X-Admin-Token": "anything"},
            )
        self.assertEqual(response.status_code, 503)


class ListFlavorsAuthTest(unittest.TestCase):
    """The ``GET /flavors-comunicacion`` listing must remain behind
    the existing admin header token. When the token is missing or
    wrong, the router returns the documented 401 / 503 without
    invoking the service or returning any catalog data."""

    def setUp(self) -> None:
        self.app = _build_app()
        self.app.dependency_overrides[get_session] = _override_session
        self.client = TestClient(self.app)

    def test_missing_token_yields_401_without_service(self) -> None:
        with patch.object(
            router_module, "ComunicacionFlavorService"
        ) as service_cls:
            with patch.object(
                dependencies_module,
                "load_settings",
                return_value=_settings(),
            ):
                response = self.client.get("/flavors-comunicacion")
        self.assertEqual(response.status_code, 401)
        service_cls.assert_not_called()

    def test_wrong_token_yields_401_without_service(self) -> None:
        with patch.object(
            router_module, "ComunicacionFlavorService"
        ) as service_cls:
            with patch.object(
                dependencies_module,
                "load_settings",
                return_value=_settings(),
            ):
                response = self.client.get(
                    "/flavors-comunicacion",
                    headers={"X-Admin-Token": "wrong-token"},
                )
        self.assertEqual(response.status_code, 401)
        service_cls.assert_not_called()

    def test_missing_admin_config_yields_503(self) -> None:
        with patch.object(
            dependencies_module, "load_settings", return_value=_settings(None)
        ):
            response = self.client.get(
                "/flavors-comunicacion",
                headers={"X-Admin-Token": "anything"},
            )
        self.assertEqual(response.status_code, 503)


class ListFlavorsAuthenticatedTest(unittest.TestCase):
    """With the matching admin token the listing returns each active
    flavor's persisted ``instruccion_llm`` exactly, matches the
    historical active-only behaviour, and never mutates the catalog."""

    def setUp(self) -> None:
        self.app = _build_app()
        self.app.dependency_overrides[get_session] = _override_session
        self.client = TestClient(self.app)
        self.inactive_flavor_id = _add_temporary_inactive_flavor()
        self.addCleanup(
            _delete_temporary_flavor, self.inactive_flavor_id
        )

    def test_listing_includes_instruccion_llm_for_active_flavors(self) -> None:
        with patch.object(
            dependencies_module, "load_settings", return_value=_settings()
        ):
            response = self.client.get(
                "/flavors-comunicacion",
                headers={"X-Admin-Token": CONFIGURED_TOKEN},
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsInstance(body, list)
        self.assertGreater(len(body), 0)
        for item in body:
            self.assertIn("instruccion_llm", item)
            self.assertGreater(len(item["instruccion_llm"]), 0)
            self.assertLessEqual(len(item["instruccion_llm"]), 2000)
            self.assertEqual(
                set(item.keys()),
                {
                    "id",
                    "codigo",
                    "nombre",
                    "descripcion",
                    "instruccion_llm",
                    "version",
                    "activo",
                },
            )

    def test_listing_excludes_inactive_flavor(self) -> None:
        with patch.object(
            dependencies_module, "load_settings", return_value=_settings()
        ):
            response = self.client.get(
                "/flavors-comunicacion",
                headers={"X-Admin-Token": CONFIGURED_TOKEN},
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        ids = [int(item["id"]) for item in body]
        self.assertNotIn(self.inactive_flavor_id, ids)
        self.assertTrue(all(item["activo"] for item in body))

    def test_listing_does_not_mutate_session(self) -> None:
        with patch.object(
            dependencies_module, "load_settings", return_value=_settings()
        ):
            with engine.connect() as conn:
                neutros = conn.execute(
                    __import__("sqlalchemy").text(
                        "SELECT id, length(instruccion_llm) "
                        "FROM flavors_comunicacion"
                    )
                ).all()
            before_snapshot = {
                int(row[0]): int(row[1]) for row in neutros
            }
            response = self.client.get(
                "/flavors-comunicacion",
                headers={"X-Admin-Token": CONFIGURED_TOKEN},
            )
        self.assertEqual(response.status_code, 200)
        with engine.connect() as conn:
            now = conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT id, length(instruccion_llm) "
                    "FROM flavors_comunicacion"
                )
            ).all()
        after_snapshot = {int(row[0]): int(row[1]) for row in now}
        self.assertEqual(before_snapshot, after_snapshot)

    def test_listing_instruccion_llm_matches_persisted_value(self) -> None:
        with patch.object(
            dependencies_module, "load_settings", return_value=_settings()
        ):
            response = self.client.get(
                "/flavors-comunicacion",
                headers={"X-Admin-Token": CONFIGURED_TOKEN},
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        ids = [int(item["id"]) for item in body]
        with engine.connect() as conn:
            rows = conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT id, instruccion_llm FROM flavors_comunicacion "
                    "WHERE id = ANY(:ids) AND activo = true"
                ),
                {"ids": ids},
            ).all()
        persisted = {int(row[0]): str(row[1]) for row in rows}
        for item in body:
            self.assertEqual(
                item["instruccion_llm"],
                persisted[int(item["id"])],
            )


class AssignFlavorServiceBoundaryTest(unittest.TestCase):
    """Uses the live database to verify the router delegates the
    mutation to the service and never short-circuits it."""

    def setUp(self) -> None:
        self.suffix = _suffix()
        self.comercio_id = _seed_comercio(self.suffix)
        self.addCleanup(_delete_comercio, self.comercio_id)

    def test_router_invokes_service_with_payload(self) -> None:
        capturado: dict[str, object] = {}

        def _factory(session: object) -> object:
            service = ComunicacionFlavorService(session)
            original = service.assign_to_comercio

            def _spy(c_id: int, f_id: int) -> object:
                capturado["comercio_id"] = c_id
                capturado["flavor_id"] = f_id
                return original(c_id, f_id)

            service.assign_to_comercio = _spy  # type: ignore[method-assign]
            return service

        app = _build_app()
        app.dependency_overrides[get_session] = _override_session
        app.dependency_overrides[require_admin_token] = lambda: None
        client = TestClient(app)
        serio_id = _flavor_id("serio")
        with patch.object(
            router_module, "ComunicacionFlavorService", side_effect=_factory
        ):
            response = client.put(
                f"/comercios/{self.comercio_id}/flavor-comunicacion",
                json={"flavor_comunicacion_id": serio_id},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(capturado.get("comercio_id"), self.comercio_id)
        self.assertEqual(capturado.get("flavor_id"), serio_id)
        self.assertEqual(_stored_flavor(self.comercio_id), serio_id)


class AssignFlavorServiceDomainTest(unittest.TestCase):
    """Coverage for the layered service/router mapping using stubs
    so the test does not depend on the live database."""

    def test_service_unknown_flavor_raises(self) -> None:
        session = MagicMock()
        service = ComunicacionFlavorService(session)
        service._flavor_repo = MagicMock()
        service._comercio_repo = MagicMock()
        service._comercio_repo.get_by_id.return_value = MagicMock(id=1)
        service._flavor_repo.get_by_id.return_value = None
        with self.assertRaises(FlavorComunicacionNotFound):
            service.assign_to_comercio(1, 99)

    def test_service_inactive_flavor_raises(self) -> None:
        session = MagicMock()
        service = ComunicacionFlavorService(session)
        service._flavor_repo = MagicMock()
        service._comercio_repo = MagicMock()
        service._comercio_repo.get_by_id.return_value = MagicMock(id=1)
        service._flavor_repo.get_by_id.return_value = MagicMock(
            id=5, activo=False
        )
        with self.assertRaises(FlavorComunicacionInactivo):
            service.assign_to_comercio(1, 5)

    def test_service_unknown_comercio_raises(self) -> None:
        session = MagicMock()
        service = ComunicacionFlavorService(session)
        service._flavor_repo = MagicMock()
        service._comercio_repo = MagicMock()
        service._comercio_repo.get_by_id.return_value = None
        with self.assertRaises(ComercioNotFound):
            service.assign_to_comercio(1, 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
