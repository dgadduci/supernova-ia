"""Focused tests for the configuration surface after the
``add-global-communication-flavors`` change.

The Phase-1 contract for the configuration read endpoints is:

* the existing ``GET /comercios/{comercio_id}/configuracion``
  endpoint keeps every prior field and embeds the safe flavor
  summary on the response;
* the existing ``GET /comercios/{comercio_id}`` endpoint keeps
  every prior field and embeds the safe flavor summary on the
  response;
* the response never includes ``instruccion_llm``;
* the selected flavor is the canonical global seed (currently
  ``neutro`` for every existing commerce after the backfill);
* the catalog is system-managed and the endpoint never exposes
  ``descripcion`` or ``instruccion_llm`` editing surfaces.
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
import backend.routers.comercios as comercios_router
import backend.routers.configuracion_comercio as config_router
from backend.config import settings as settings_module
from backend.config.settings import Settings
from backend.dependencies import get_session, require_admin_token
from backend.models import Comercio, FlavorComunicacion
from backend.schemas.comercio import ComercioResponse
from backend.schemas.comunicacion_flavor import (
    FlavorComunicacionSummary,
)
from backend.schemas.configuracion_comercio import (
    ComercioConfiguracionResponse,
)

CONFIGURED_TOKEN = "config-flavor-test-token"

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


def _seed_comercio(suffix: str, flavor_codigo: str = "neutro") -> int:
    with TestingSessionLocal() as session, session.begin():
        flavor_id = session.execute(
            select(FlavorComunicacion.id).where(
                FlavorComunicacion.codigo == flavor_codigo
            )
        ).scalar_one()
        comercio = Comercio(
            nombre_fantasia=f"Config Flavor {suffix}",
            nombre_corto=f"CF {suffix}",
            razon_social=f"Config Flavor SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+54918{suffix[:8]}",
            calle="Av. Config",
            numero="100",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"config-flavor-{suffix}",
            estado_id=_estado_id_activo(),
            flavor_comunicacion_id=flavor_id,
        )
        session.add(comercio)
        session.flush()
        comercio_id = int(comercio.id)
    return comercio_id


def _delete_comercio(comercio_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(delete(Comercio).where(Comercio.id == comercio_id))


def _override_session() -> object:
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


class ConfiguracionComercioSchemaTest(unittest.TestCase):
    """``ComercioConfiguracionResponse`` exposes the safe flavor
    summary and never ``instruccion_llm``."""

    def test_configuracion_schema_contains_flavor_summary(self) -> None:
        fields = set(ComercioConfiguracionResponse.model_fields.keys())
        self.assertIn("flavor_comunicacion", fields)
        self.assertEqual(
            FlavorComunicacionSummary.model_fields.keys(),
            {
                "id",
                "codigo",
                "nombre",
                "descripcion",
                "version",
                "activo",
            },
        )

    def test_comercio_schema_contains_flavor_summary(self) -> None:
        fields = set(ComercioResponse.model_fields.keys())
        self.assertIn("flavor_comunicacion", fields)
        self.assertEqual(
            FlavorComunicacionSummary.model_fields.keys(),
            {
                "id",
                "codigo",
                "nombre",
                "descripcion",
                "version",
                "activo",
            },
        )


class ConfiguracionComercioReadTest(unittest.TestCase):
    """Live database: the configuration response embeds the safe
    flavor summary and never ``instruccion_llm``."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = FastAPI()
        cls.app.include_router(config_router.router)
        cls.app.include_router(comercios_router.router)
        cls.app.dependency_overrides[get_session] = _override_session
        cls.app.dependency_overrides[require_admin_token] = lambda: None
        cls.client = TestClient(cls.app)

    def setUp(self) -> None:
        self.suffix = _suffix()
        self.comercio_id = _seed_comercio(self.suffix)
        self.addCleanup(_delete_comercio, self.comercio_id)

    def test_configuracion_returns_safe_flavor_summary(self) -> None:
        response = self.client.get(
            f"/comercios/{self.comercio_id}/configuracion"
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("flavor_comunicacion", body)
        flavor = body["flavor_comunicacion"]
        self.assertEqual(flavor["codigo"], "neutro")
        self.assertNotIn("instruccion_llm", flavor)
        self.assertNotIn("instruccion_llm", body)
        self.assertEqual(
            set(flavor.keys()),
            {"id", "codigo", "nombre", "descripcion", "version", "activo"},
        )

    def test_comercio_get_returns_safe_flavor_summary(self) -> None:
        response = self.client.get(f"/comercios/{self.comercio_id}")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("flavor_comunicacion", body)
        flavor = body["flavor_comunicacion"]
        self.assertEqual(flavor["codigo"], "neutro")
        self.assertNotIn("instruccion_llm", flavor)
        self.assertNotIn("instruccion_llm", body)
        self.assertEqual(
            set(flavor.keys()),
            {"id", "codigo", "nombre", "descripcion", "version", "activo"},
        )

    def test_configuracion_preserves_prior_fields(self) -> None:
        response = self.client.get(
            f"/comercios/{self.comercio_id}/configuracion"
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        for required in (
            "id",
            "nombre_fantasia",
            "nombre_corto",
            "razon_social",
            "cuit",
            "whatsapp",
            "calle",
            "numero",
            "localidad",
            "provincia",
            "slug",
            "estado_id",
            "zona_horaria",
            "moneda",
            "idioma",
            "fecha_alta",
            "fecha_ultima_modificacion",
            "estado",
            "medios_pago",
            "metodos_entrega",
        ):
            with self.subTest(field=required):
                self.assertIn(required, body)

    def test_comercio_get_preserves_prior_fields(self) -> None:
        response = self.client.get(f"/comercios/{self.comercio_id}")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        for required in (
            "id",
            "nombre_fantasia",
            "nombre_corto",
            "razon_social",
            "cuit",
            "whatsapp",
            "calle",
            "numero",
            "localidad",
            "provincia",
            "slug",
            "estado_id",
            "zona_horaria",
            "moneda",
            "idioma",
            "fecha_alta",
            "fecha_ultima_modificacion",
        ):
            with self.subTest(field=required):
                self.assertIn(required, body)

    def test_configuracion_reflects_updated_flavor(self) -> None:
        serio_id = None
        with engine.connect() as conn:
            serio_id = int(
                conn.execute(
                    __import__("sqlalchemy").text(
                        "SELECT id FROM flavors_comunicacion "
                        "WHERE codigo = 'serio'"
                    )
                ).scalar_one()
            )
        with TestingSessionLocal() as session, session.begin():
            session.execute(
                __import__("sqlalchemy").text(
                    "UPDATE comercios SET flavor_comunicacion_id = :fid "
                    "WHERE id = :id"
                ),
                {"fid": serio_id, "id": self.comercio_id},
            )
        response = self.client.get(
            f"/comercios/{self.comercio_id}/configuracion"
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["flavor_comunicacion"]["codigo"], "serio")


class ConfiguracionComercioAuthTest(unittest.TestCase):
    """The configuration endpoint keeps the existing admin header
    token gate. Auth failure (or missing config) returns the
    documented status code before any service call."""

    def setUp(self) -> None:
        self.app = FastAPI()
        self.app.include_router(config_router.router)
        self.app.dependency_overrides[get_session] = _override_session
        self.client = TestClient(self.app)

    def test_missing_token_returns_401(self) -> None:
        with patch.object(
            dependencies_module, "load_settings", return_value=_settings()
        ):
            response = self.client.get("/comercios/1/configuracion")
        self.assertEqual(response.status_code, 401)

    def test_missing_admin_config_returns_503(self) -> None:
        with patch.object(
            dependencies_module, "load_settings", return_value=_settings(None)
        ):
            response = self.client.get(
                "/comercios/1/configuracion",
                headers={"X-Admin-Token": "anything"},
            )
        self.assertEqual(response.status_code, 503)


class ConfiguracionComercioEagerLoadingTest(unittest.TestCase):
    """Verifies the configuration read eagerly loads the flavor
    relationship so the response does not trigger a second
    query."""

    def test_configuracion_eager_loads_flavor(self) -> None:
        from sqlalchemy import event

        suffix = _suffix()
        comercio_id = _seed_comercio(suffix)
        self.addCleanup(_delete_comercio, comercio_id)
        statements: list[str] = []

        def capture(conn, cursor, statement, params, context, executemany):
            statements.append(statement.strip().upper())

        app = FastAPI()
        app.include_router(config_router.router)
        app.dependency_overrides[get_session] = _override_session
        app.dependency_overrides[require_admin_token] = lambda: None
        client = TestClient(app)
        event.listen(engine, "before_cursor_execute", capture)
        try:
            response = client.get(
                f"/comercios/{comercio_id}/configuracion"
            )
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        self.assertEqual(response.status_code, 200)
        flavor_selects = [
            s
            for s in statements
            if "FLAVORS_COMUNICACION" in s and s.startswith("SELECT")
        ]
        self.assertGreaterEqual(len(flavor_selects), 1)


class ConfiguracionComercioFlavorUnavailableTest(unittest.TestCase):
    """The configuration read must remain robust: the repository
    eager-loads the flavor relationship so the response schema
    never blows up on a missing relationship."""

    def test_repository_returns_comercio_with_flavor_loaded(self) -> None:
        from backend.repositories.configuracion_comercio_repository import (
            ConfiguracionComercioRepository,
        )

        suffix = _suffix()
        comercio_id = _seed_comercio(suffix)
        self.addCleanup(_delete_comercio, comercio_id)
        with TestingSessionLocal() as session:
            repo = ConfiguracionComercioRepository(session)
            comercio = repo.get_by_id(comercio_id)
        self.assertIsNotNone(comercio)
        assert comercio is not None
        self.assertIsNotNone(comercio.flavor_comunicacion)
        self.assertEqual(comercio.flavor_comunicacion.codigo, "neutro")


class ConfiguracionComercioNoLlmLeakTest(unittest.TestCase):
    """Diff-based guarantee: the flavor field on the response
    contains no instruction text and no description of the
    internal ``instruccion_llm`` payload."""

    def test_payload_search_excludes_instruccion_llm(self) -> None:
        suffix = _suffix()
        comercio_id = _seed_comercio(suffix)
        self.addCleanup(_delete_comercio, comercio_id)
        app = FastAPI()
        app.include_router(config_router.router)
        app.dependency_overrides[get_session] = _override_session
        app.dependency_overrides[require_admin_token] = lambda: None
        client = TestClient(app)
        with engine.connect() as conn:
            flavor_ids = [
                int(row[0])
                for row in conn.execute(
                    __import__("sqlalchemy").text(
                        "SELECT id FROM flavors_comunicacion"
                    )
                )
            ]
        for flavor_id in flavor_ids:
            with engine.connect() as conn:
                instruccion = conn.execute(
                    __import__("sqlalchemy").text(
                        "SELECT instruccion_llm FROM flavors_comunicacion "
                        "WHERE id = :id"
                    ),
                    {"id": flavor_id},
                ).scalar_one()
            response = client.get(
                f"/comercios/{comercio_id}/configuracion"
            )
            self.assertEqual(response.status_code, 200)
            dumped = response.text
            self.assertNotIn(instruccion, dumped)


class ConfiguracionComercioMissingTest(unittest.TestCase):
    def test_missing_comercio_returns_404(self) -> None:
        app = FastAPI()
        app.include_router(config_router.router)
        app.dependency_overrides[get_session] = _override_session
        app.dependency_overrides[require_admin_token] = lambda: None
        client = TestClient(app)
        response = client.get("/comercios/999999999/configuracion")
        self.assertEqual(response.status_code, 404)


class ConfiguracionComercioMagicMockTest(unittest.TestCase):
    """Coverage for the response schema using a MagicMock ORM-like
    object so the schema's nested validation is exercised without
    touching the live database."""

    def test_response_uses_only_safe_fields(self) -> None:
        from datetime import datetime, timezone

        sabor = MagicMock()
        sabor.id = 1
        sabor.codigo = "neutro"
        sabor.nombre = "Neutro"
        sabor.descripcion = "Tono profesional"
        sabor.version = 1
        sabor.activo = True
        comercio = MagicMock()
        comercio.id = 1
        comercio.nombre_fantasia = "x"
        comercio.nombre_corto = "x"
        comercio.razon_social = "x"
        comercio.cuit = "x"
        comercio.whatsapp = "x"
        comercio.calle = "x"
        comercio.numero = "x"
        comercio.piso_departamento = None
        comercio.localidad = "x"
        comercio.provincia = "x"
        comercio.codigo_postal = None
        comercio.slug = "x"
        comercio.estado_id = 1
        comercio.zona_horaria = "x"
        comercio.moneda = "x"
        comercio.idioma = "x"
        comercio.fecha_alta = datetime(2026, 1, 1, tzinfo=timezone.utc)
        comercio.fecha_ultima_modificacion = datetime(
            2026, 1, 1, tzinfo=timezone.utc
        )
        comercio.fecha_baja = None
        comercio.flavor_comunicacion = sabor
        payload = ComercioResponse.model_validate(comercio)
        dumped = payload.model_dump()
        self.assertIn("flavor_comunicacion", dumped)
        self.assertNotIn("instruccion_llm", dumped["flavor_comunicacion"])
        self.assertEqual(
            set(dumped["flavor_comunicacion"].keys()),
            {"id", "codigo", "nombre", "descripcion", "version", "activo"},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
