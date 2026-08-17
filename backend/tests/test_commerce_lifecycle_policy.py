"""Focused tests for the centralized commerce availability policy.

The tests exercise every documented operating mode, the legacy
historical states (SUSPENDIDO / BAJA), exact deadline and quota
boundaries, the trial reset on entry and the no-reset behaviour for
in-trial edits.
"""
from __future__ import annotations

import unittest
import unittest.mock
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from backend.models import (
    Comercio,
    EstadoComercio,
    EstadoPedido,
    Pedido,
)
from backend.models.estado_comercio import EstadoComercioModoOperacion
from backend.models.session import EstadoSession
from backend.services.commerce_availability_service import (
    CommerceAvailabilityService,
    CommerceAvailabilityStatus,
    CommerceUnavailableReason,
)
from backend.services.comercio_service import ComercioService
from backend.services.exceptions import (
    EstadoComercioNotSelectable,
    InvalidTrialConfiguration,
)

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _ensure_legacy_seed() -> dict[str, int]:
    """Return the canonical lifecycle row ids, seeding the table
    once for the duration of the test session.

    The seeds mirror the lifecycle policy: ACTIVO/HABILITADO,
    INACTIVO/BLOQUEADO, PRUEBA/PRUEBA, SUSPENDIDO/BLOQUEADO,
    BAJA/BLOQUEADO. The historical rows are non-selectable.
    """
    cache: dict[str, int] = {}
    with engine.begin() as conn:
        rows: list[tuple[str, str, str, bool]] = [
            ("ACTIVO", "Activo", "habilitado", True),
            ("INACTIVO", "Inactivo", "bloqueado", True),
            ("PRUEBA", "Prueba", "prueba", True),
            ("SUSPENDIDO", "Suspendido", "bloqueado", False),
            ("BAJA", "Baja", "bloqueado", False),
        ]
        for codigo, descripcion, modo, seleccionable in rows:
            conn.exec_driver_sql(
                "INSERT INTO estado_comercio "
                "(codigo, descripcion, modo_operacion, seleccionable) "
                "VALUES (%s, %s, CAST(%s AS estado_comercio_modo_operacion), %s) "
                "ON CONFLICT (codigo) DO UPDATE SET "
                "descripcion = EXCLUDED.descripcion, "
                "modo_operacion = EXCLUDED.modo_operacion, "
                "seleccionable = EXCLUDED.seleccionable",
                (codigo, descripcion, modo, seleccionable),
            )
            row = conn.exec_driver_sql(
                "SELECT id FROM estado_comercio WHERE codigo = %s",
                (codigo,),
            ).first()
            assert row is not None
            cache[codigo] = int(row[0])
    return cache


def _seed_comercio(
    estado_id: int,
    *,
    prueba_hasta: datetime | None = None,
    prueba_max_pedidos: int | None = None,
    prueba_pedidos_consumidos: int = 0,
) -> int:
    suffix = _suffix()
    with TestingSessionLocal() as session, session.begin():
        comercio = Comercio(
            nombre_fantasia=f"Comercio {suffix}",
            nombre_corto=f"C {suffix}",
            razon_social=f"Razon {suffix} SRL",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+5492{suffix[:8]}",
            calle="Av. Test",
            numero="100",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"comercio-{suffix}",
            estado_id=estado_id,
            prueba_hasta=prueba_hasta,
            prueba_max_pedidos=prueba_max_pedidos,
            prueba_pedidos_consumidos=prueba_pedidos_consumidos,
        )
        session.add(comercio)
        session.flush()
        return int(comercio.id)


def _delete_comercio(comercio_id: int) -> None:
    from backend.models.session import Session as ConversationSession

    with TestingSessionLocal() as session, session.begin():
        subq = (
            select(ConversationSession.id)
            .where(ConversationSession.id_comercio == comercio_id)
            .scalar_subquery()
        )
        session.execute(delete(Pedido).where(Pedido.id_session.in_(subq)))
        session.execute(delete(Comercio).where(Comercio.id == comercio_id))


class CommerceAvailabilityServiceEnabledTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._seed = _ensure_legacy_seed()

    def test_enabled_commerce_is_available(self) -> None:
        comercio_id = _seed_comercio(self._seed["ACTIVO"])
        try:
            with TestingSessionLocal() as session:
                outcome = CommerceAvailabilityService(session).evaluate(comercio_id)
            self.assertEqual(
                outcome.status, CommerceAvailabilityStatus.AVAILABLE
            )
            self.assertIsNone(outcome.reason)
            self.assertEqual(
                outcome.modo_operacion,
                EstadoComercioModoOperacion.HABILITADO,
            )
        finally:
            _delete_comercio(comercio_id)

    def test_blocked_commerce_is_unavailable(self) -> None:
        comercio_id = _seed_comercio(self._seed["INACTIVO"])
        try:
            with TestingSessionLocal() as session:
                outcome = CommerceAvailabilityService(session).evaluate(comercio_id)
            self.assertEqual(
                outcome.status, CommerceAvailabilityStatus.UNAVAILABLE
            )
            self.assertEqual(
                outcome.reason, CommerceUnavailableReason.BLOCKED_STATE
            )
            self.assertEqual(
                outcome.modo_operacion,
                EstadoComercioModoOperacion.BLOQUEADO,
            )
        finally:
            _delete_comercio(comercio_id)

    def test_legacy_suspendido_is_blocked(self) -> None:
        comercio_id = _seed_comercio(self._seed["SUSPENDIDO"])
        try:
            with TestingSessionLocal() as session:
                outcome = CommerceAvailabilityService(session).evaluate(comercio_id)
            self.assertEqual(
                outcome.status, CommerceAvailabilityStatus.UNAVAILABLE
            )
            self.assertEqual(
                outcome.reason, CommerceUnavailableReason.BLOCKED_STATE
            )
        finally:
            _delete_comercio(comercio_id)

    def test_legacy_baja_is_blocked(self) -> None:
        comercio_id = _seed_comercio(self._seed["BAJA"])
        try:
            with TestingSessionLocal() as session:
                outcome = CommerceAvailabilityService(session).evaluate(comercio_id)
            self.assertEqual(
                outcome.status, CommerceAvailabilityStatus.UNAVAILABLE
            )
            self.assertEqual(
                outcome.reason, CommerceUnavailableReason.BLOCKED_STATE
            )
        finally:
            _delete_comercio(comercio_id)

    def test_missing_commerce_is_blocked(self) -> None:
        with TestingSessionLocal() as session:
            outcome = CommerceAvailabilityService(session).evaluate(99_999_999)
        self.assertEqual(
            outcome.status, CommerceAvailabilityStatus.UNAVAILABLE
        )
        self.assertEqual(
            outcome.reason, CommerceUnavailableReason.BLOCKED_STATE
        )


class CommerceAvailabilityServiceTrialTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._seed = _ensure_legacy_seed()

    def _future(self) -> datetime:
        return datetime.now(tz=timezone.utc) + timedelta(days=2)

    def _past(self) -> datetime:
        return datetime.now(tz=timezone.utc) - timedelta(days=2)

    def test_trial_below_quota_and_before_deadline(self) -> None:
        comercio_id = _seed_comercio(
            self._seed["PRUEBA"],
            prueba_hasta=self._future(),
            prueba_max_pedidos=3,
            prueba_pedidos_consumidos=1,
        )
        try:
            with TestingSessionLocal() as session:
                outcome = CommerceAvailabilityService(session).evaluate(comercio_id)
            self.assertEqual(
                outcome.status, CommerceAvailabilityStatus.AVAILABLE
            )
            self.assertEqual(
                outcome.modo_operacion,
                EstadoComercioModoOperacion.PRUEBA,
            )
        finally:
            _delete_comercio(comercio_id)

    def test_trial_at_exact_deadline_is_expired(self) -> None:
        comercio_id = _seed_comercio(
            self._seed["PRUEBA"],
            prueba_hasta=self._past(),
            prueba_max_pedidos=3,
            prueba_pedidos_consumidos=0,
        )
        try:
            with TestingSessionLocal() as session:
                outcome = CommerceAvailabilityService(session).evaluate(comercio_id)
            self.assertEqual(
                outcome.status, CommerceAvailabilityStatus.UNAVAILABLE
            )
            self.assertEqual(
                outcome.reason, CommerceUnavailableReason.TRIAL_EXPIRED
            )
        finally:
            _delete_comercio(comercio_id)

    def test_trial_at_exact_quota_is_exhausted(self) -> None:
        comercio_id = _seed_comercio(
            self._seed["PRUEBA"],
            prueba_hasta=self._future(),
            prueba_max_pedidos=2,
            prueba_pedidos_consumidos=2,
        )
        try:
            with TestingSessionLocal() as session:
                outcome = CommerceAvailabilityService(session).evaluate(comercio_id)
            self.assertEqual(
                outcome.status, CommerceAvailabilityStatus.UNAVAILABLE
            )
            self.assertEqual(
                outcome.reason,
                CommerceUnavailableReason.TRIAL_QUOTA_EXHAUSTED,
            )
        finally:
            _delete_comercio(comercio_id)

    def test_reserve_increments_counter(self) -> None:
        comercio_id = _seed_comercio(
            self._seed["PRUEBA"],
            prueba_hasta=self._future(),
            prueba_max_pedidos=3,
            prueba_pedidos_consumidos=0,
        )
        try:
            with TestingSessionLocal() as session, session.begin():
                outcome = CommerceAvailabilityService(
                    session
                ).reserve_confirmed_order(comercio_id)
            self.assertEqual(
                outcome.status, CommerceAvailabilityStatus.AVAILABLE
            )
            self.assertEqual(outcome.prueba_pedidos_consumidos, 1)
            with TestingSessionLocal() as session:
                refreshed = CommerceAvailabilityService(session).evaluate(
                    comercio_id
                )
            self.assertEqual(refreshed.prueba_pedidos_consumidos, 1)
        finally:
            _delete_comercio(comercio_id)

    def test_reserve_at_quota_returns_exhausted(self) -> None:
        comercio_id = _seed_comercio(
            self._seed["PRUEBA"],
            prueba_hasta=self._future(),
            prueba_max_pedidos=1,
            prueba_pedidos_consumidos=1,
        )
        try:
            with TestingSessionLocal() as session:
                outcome = CommerceAvailabilityService(
                    session
                ).reserve_confirmed_order(comercio_id)
            self.assertEqual(
                outcome.status, CommerceAvailabilityStatus.UNAVAILABLE
            )
            self.assertEqual(
                outcome.reason,
                CommerceUnavailableReason.TRIAL_QUOTA_EXHAUSTED,
            )
            with TestingSessionLocal() as session:
                refreshed = CommerceAvailabilityService(session).evaluate(
                    comercio_id
                )
            self.assertEqual(refreshed.prueba_pedidos_consumidos, 1)
        finally:
            _delete_comercio(comercio_id)


class CommerceServiceTrialLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._seed = _ensure_legacy_seed()

    def _make_comercio(
        self,
        *,
        estado_id: int,
        prueba_hasta: datetime | None = None,
        prueba_max_pedidos: int | None = None,
    ) -> int:
        suffix = _suffix()
        with TestingSessionLocal() as session, session.begin():
            comercio = Comercio(
                nombre_fantasia=f"C {suffix}",
                nombre_corto=f"X {suffix}",
                razon_social=f"Razon {suffix} SRL",
                cuit=f"30-{suffix[:8]}-{suffix[8]}",
                whatsapp=f"+5493{suffix[:8]}",
                calle="Calle",
                numero="1",
                piso_departamento=None,
                localidad="CABA",
                provincia="Buenos Aires",
                codigo_postal="C1000",
                slug=f"comercio-trial-{suffix}",
                estado_id=estado_id,
            )
            session.add(comercio)
            session.flush()
            comercio_id = int(comercio.id)
        if prueba_hasta is not None or prueba_max_pedidos is not None:
            with TestingSessionLocal() as session, session.begin():
                comercio = session.get(Comercio, comercio_id)
                assert comercio is not None
                comercio.prueba_hasta = prueba_hasta
                comercio.prueba_max_pedidos = prueba_max_pedidos
        return comercio_id

    def _delete(self, comercio_id: int) -> None:
        with TestingSessionLocal() as session, session.begin():
            session.execute(delete(Comercio).where(Comercio.id == comercio_id))

    def test_create_in_prueba_without_deadline_is_rejected(self) -> None:
        with TestingSessionLocal() as session:
            service = ComercioService(session)
            with self.assertRaises(InvalidTrialConfiguration):
                service.create(
                    {
                        "nombre_fantasia": "X",
                        "nombre_corto": "X",
                        "razon_social": "X SRL",
                        "cuit": "30-99999999-9",
                        "whatsapp": "+5493999999999",
                        "calle": "X",
                        "numero": "1",
                        "localidad": "CABA",
                        "provincia": "Buenos Aires",
                        "slug": "comercio-prueba-invalid",
                        "estado_id": self._seed["PRUEBA"],
                        "prueba_hasta": None,
                        "prueba_max_pedidos": 5,
                    }
                )

    def test_update_to_prueba_resets_counter(self) -> None:
        comercio_id = self._make_comercio(estado_id=self._seed["ACTIVO"])
        try:
            future = datetime.now(tz=timezone.utc) + timedelta(days=3)
            with TestingSessionLocal() as session, session.begin():
                comercio = session.get(Comercio, comercio_id)
                assert comercio is not None
                comercio.prueba_pedidos_consumidos = 7
            with TestingSessionLocal() as session:
                service = ComercioService(session)
                service.update(
                    comercio_id,
                    {
                        "nombre_fantasia": "X",
                        "nombre_corto": "X",
                        "razon_social": "X SRL",
                        "cuit": "30-99999999-0",
                        "calle": "X",
                        "numero": "1",
                        "localidad": "CABA",
                        "provincia": "Buenos Aires",
                        "estado_id": self._seed["PRUEBA"],
                        "prueba_hasta": future,
                        "prueba_max_pedidos": 10,
                        "zona_horaria": "America/Argentina/Buenos_Aires",
                        "moneda": "ARS",
                        "idioma": "es-AR",
                    },
                )
            with TestingSessionLocal() as session:
                comercio = session.get(Comercio, comercio_id)
                assert comercio is not None
                self.assertEqual(comercio.prueba_pedidos_consumidos, 0)
        finally:
            _delete_comercio(comercio_id)

    def test_update_in_prueba_preserves_counter(self) -> None:
        future = datetime.now(tz=timezone.utc) + timedelta(days=3)
        comercio_id = self._make_comercio(
            estado_id=self._seed["PRUEBA"],
            prueba_hasta=future,
            prueba_max_pedidos=10,
        )
        try:
            with TestingSessionLocal() as session, session.begin():
                comercio = session.get(Comercio, comercio_id)
                assert comercio is not None
                comercio.prueba_pedidos_consumidos = 4
            with TestingSessionLocal() as session:
                service = ComercioService(session)
                service.update(
                    comercio_id,
                    {
                        "nombre_fantasia": "X",
                        "nombre_corto": "X",
                        "razon_social": "X SRL",
                        "cuit": "30-99999999-0",
                        "calle": "X",
                        "numero": "1",
                        "localidad": "CABA",
                        "provincia": "Buenos Aires",
                        "estado_id": self._seed["PRUEBA"],
                        "prueba_hasta": future + timedelta(days=1),
                        "prueba_max_pedidos": 20,
                        "zona_horaria": "America/Argentina/Buenos_Aires",
                        "moneda": "ARS",
                        "idioma": "es-AR",
                    },
                )
            with TestingSessionLocal() as session:
                comercio = session.get(Comercio, comercio_id)
                assert comercio is not None
                self.assertEqual(comercio.prueba_pedidos_consumidos, 4)
        finally:
            _delete_comercio(comercio_id)


class EstadosComercioSeedIdempotencyTest(unittest.TestCase):
    """The CLI seed script must remain idempotent and reflect the
    canonical lifecycle configuration.

    Running ``main()`` twice never duplicates rows and every row
    keeps its original ``id``; the second invocation only aligns the
    mode / description / seleccionable columns with the JSON source
    of truth.
    """

    def test_seed_is_idempotent_and_keeps_original_ids(self) -> None:
        import importlib
        import os
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[2]
        original_argv = sys.argv
        original_url = os.environ.get("SUPERNOVA_DATABASE_URL")
        os.environ["SUPERNOVA_DATABASE_URL"] = TEST_URL
        sys.path.insert(0, str(repo_root))
        try:
            seed_module = importlib.import_module(
                "backend.db.seeds.seeds.estados_comercio"
            )
            importlib.reload(seed_module)
            seed_module.main()
            with engine.connect() as conn:
                rows_after_first = conn.execute(
                    select(
                        EstadoComercio.id,
                        EstadoComercio.codigo,
                        EstadoComercio.modo_operacion,
                        EstadoComercio.seleccionable,
                    ).order_by(EstadoComercio.id)
                ).all()
            self.assertGreaterEqual(len(rows_after_first), 5)
            ids_by_codigo = {
                row[1]: int(row[0]) for row in rows_after_first
            }
            for required in (
                "ACTIVO",
                "INACTIVO",
                "PRUEBA",
                "SUSPENDIDO",
                "BAJA",
            ):
                self.assertIn(required, ids_by_codigo)

            seed_module.main()
            with engine.connect() as conn:
                rows_after_second = conn.execute(
                    select(
                        EstadoComercio.id,
                        EstadoComercio.codigo,
                    )
                    .where(
                        EstadoComercio.codigo.in_(
                            [
                                "ACTIVO",
                                "INACTIVO",
                                "PRUEBA",
                                "SUSPENDIDO",
                                "BAJA",
                            ]
                        )
                    )
                    .order_by(EstadoComercio.id)
                ).all()
            second_ids = {
                codigo: int(row_id)
                for row_id, codigo in rows_after_second
            }
            self.assertEqual(second_ids, ids_by_codigo)
        finally:
            sys.path.remove(str(repo_root))
            if original_url is None:
                os.environ.pop("SUPERNOVA_DATABASE_URL", None)
            else:
                os.environ["SUPERNOVA_DATABASE_URL"] = original_url
            sys.argv = original_argv

    def test_seed_attributes_match_canonical_lifecycle(self) -> None:
        with engine.connect() as conn:
            for codigo, modo, seleccionable in (
                (
                    "ACTIVO",
                    EstadoComercioModoOperacion.HABILITADO,
                    True,
                ),
                (
                    "INACTIVO",
                    EstadoComercioModoOperacion.BLOQUEADO,
                    True,
                ),
                (EstadoComercioModoOperacion.PRUEBA.name, "prueba", True)
                if False
                else (
                    "PRUEBA",
                    EstadoComercioModoOperacion.PRUEBA,
                    True,
                ),
                (
                    "SUSPENDIDO",
                    EstadoComercioModoOperacion.BLOQUEADO,
                    False,
                ),
                (
                    "BAJA",
                    EstadoComercioModoOperacion.BLOQUEADO,
                    False,
                ),
            ):
                row = conn.execute(
                    select(
                        EstadoComercio.codigo,
                        EstadoComercio.modo_operacion,
                        EstadoComercio.seleccionable,
                    ).where(EstadoComercio.codigo == codigo)
                ).first()
                self.assertIsNotNone(row, f"{codigo} row missing")
                assert row is not None
                self.assertEqual(row[1], modo)
                self.assertEqual(bool(row[2]), seleccionable)


class EstadosComercioRouterAuthTest(unittest.TestCase):
    """The ``/estados-comercio`` JSON router is admin-only.

    The legacy ``POST`` endpoint was retired but the remaining list
    and detail surfaces must keep the documented admin token gate
    so a forged unauthenticated request cannot enumerate the
    canonical lifecycle configuration.
    """

    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import backend.dependencies as dependencies_module
        from backend.config import settings as settings_module
        from backend.config.settings import Settings
        from backend.routers.estados_comercios import router as estados_router

        self._settings_patcher = unittest.mock.patch.object(
            dependencies_module,
            "load_settings",
            return_value=Settings(
                **{**settings_module.load_settings().__dict__,
                    "order_management_admin_token": "lifecycle-test-token"}
            ),
        )
        self._settings_patcher.start()
        self.addCleanup(self._settings_patcher.stop)

        self.app = FastAPI()
        self.app.include_router(estados_router)
        self.client = TestClient(
            self.app, raise_server_exceptions=False
        )

    def _auth_headers(self) -> dict[str, str]:
        return {"X-Admin-Token": "lifecycle-test-token"}

    def test_list_without_token_returns_auth_rejection(self) -> None:
        response = self.client.get("/estados-comercio")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {"detail": "Administrative credential required"},
        )

    def test_list_with_token_returns_canonical_rows(self) -> None:
        response = self.client.get(
            "/estados-comercio", headers=self._auth_headers()
        )
        self.assertEqual(response.status_code, 200)
        rows = response.json()
        codigos = {row["codigo"] for row in rows}
        self.assertIn("ACTIVO", codigos)
        self.assertIn("INACTIVO", codigos)
        self.assertIn("PRUEBA", codigos)
        self.assertIn("SUSPENDIDO", codigos)
        self.assertIn("BAJA", codigos)

    def test_detail_without_token_returns_auth_rejection(self) -> None:
        with TestingSessionLocal() as session:
            estado = session.execute(
                select(EstadoComercio).where(
                    EstadoComercio.codigo == "ACTIVO"
                )
            ).scalar_one()
            estado_id = int(estado.id)
        response = self.client.get(f"/estados-comercio/{estado_id}")
        self.assertEqual(response.status_code, 401)

    def test_detail_with_token_returns_row(self) -> None:
        with TestingSessionLocal() as session:
            estado = session.execute(
                select(EstadoComercio).where(
                    EstadoComercio.codigo == "ACTIVO"
                )
            ).scalar_one()
            estado_id = int(estado.id)
        response = self.client.get(
            f"/estados-comercio/{estado_id}",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["codigo"], "ACTIVO")


class ComercioServiceSeleccionableGuardTest(unittest.TestCase):
    """``ComercioService`` must reject any non-selectable ``estado_id``.

    The legacy SUSPENDIDO / BAJA rows are kept as historical,
    non-selectable configuration. Even when the rendered form
    exposes only the selectable rows, the service must reject a
    forged or stale submission before staging any change.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._seed = _ensure_legacy_seed()

    def test_create_with_suspendido_is_rejected_without_mutation(self) -> None:
        suffix = _suffix()
        with TestingSessionLocal() as session:
            service = ComercioService(session)
            with self.assertRaises(EstadoComercioNotSelectable):
                service.create(
                    {
                        "nombre_fantasia": "S",
                        "nombre_corto": "S",
                        "razon_social": "S SRL",
                        "cuit": f"30-{suffix[:8]}-{suffix[8]}",
                        "whatsapp": f"+54923{suffix[:8]}",
                        "calle": "Av",
                        "numero": "1",
                        "localidad": "CABA",
                        "provincia": "Buenos Aires",
                        "slug": f"comercio-suspendido-{suffix}",
                        "estado_id": self._seed["SUSPENDIDO"],
                    }
                )
            comercio_count = session.execute(
                select(Comercio).where(
                    Comercio.slug == f"comercio-suspendido-{suffix}"
                )
            ).first()
            self.assertIsNone(comercio_count)

    def test_create_with_baja_is_rejected_without_mutation(self) -> None:
        suffix = _suffix()
        with TestingSessionLocal() as session:
            service = ComercioService(session)
            with self.assertRaises(EstadoComercioNotSelectable):
                service.create(
                    {
                        "nombre_fantasia": "B",
                        "nombre_corto": "B",
                        "razon_social": "B SRL",
                        "cuit": f"30-{suffix[:8]}-{suffix[8]}",
                        "whatsapp": f"+54924{suffix[:8]}",
                        "calle": "Av",
                        "numero": "1",
                        "localidad": "CABA",
                        "provincia": "Buenos Aires",
                        "slug": f"comercio-baja-{suffix}",
                        "estado_id": self._seed["BAJA"],
                    }
                )

    def test_update_to_suspendido_is_rejected_without_mutation(self) -> None:
        comercio_id = _seed_comercio(self._seed["ACTIVO"])
        try:
            with TestingSessionLocal() as session:
                service = ComercioService(session)
                with self.assertRaises(EstadoComercioNotSelectable):
                    service.update(
                        comercio_id,
                        {
                            "nombre_fantasia": "X",
                            "nombre_corto": "X",
                            "razon_social": "X SRL",
                            "cuit": "30-99999999-0",
                            "calle": "X",
                            "numero": "1",
                            "localidad": "CABA",
                            "provincia": "Buenos Aires",
                            "estado_id": self._seed["SUSPENDIDO"],
                            "zona_horaria": "America/Argentina/Buenos_Aires",
                            "moneda": "ARS",
                            "idioma": "es-AR",
                        },
                    )
            with TestingSessionLocal() as session:
                comercio = session.get(Comercio, comercio_id)
                self.assertIsNotNone(comercio)
                assert comercio is not None
                self.assertEqual(int(comercio.estado_id), self._seed["ACTIVO"])
        finally:
            _delete_comercio(comercio_id)

    def test_update_to_baja_is_rejected_without_mutation(self) -> None:
        comercio_id = _seed_comercio(self._seed["ACTIVO"])
        try:
            with TestingSessionLocal() as session:
                service = ComercioService(session)
                with self.assertRaises(EstadoComercioNotSelectable):
                    service.update(
                        comercio_id,
                        {
                            "nombre_fantasia": "X",
                            "nombre_corto": "X",
                            "razon_social": "X SRL",
                            "cuit": "30-99999999-0",
                            "calle": "X",
                            "numero": "1",
                            "localidad": "CABA",
                            "provincia": "Buenos Aires",
                            "estado_id": self._seed["BAJA"],
                            "zona_horaria": "America/Argentina/Buenos_Aires",
                            "moneda": "ARS",
                            "idioma": "es-AR",
                        },
                    )
        finally:
            _delete_comercio(comercio_id)


class ComercioServiceTrialTransitionTest(unittest.TestCase):
    """The ``ComercioService.update`` lifecycle logic preserves the
    historical PRUEBA configuration when leaving PRUEBA and never
    lets a forged payload reset the consumed counter during an
    in-trial edit.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._seed = _ensure_legacy_seed()

    def _make_comercio(
        self,
        *,
        estado_id: int,
        prueba_hasta: datetime | None = None,
        prueba_max_pedidos: int | None = None,
        prueba_pedidos_consumidos: int = 0,
    ) -> int:
        suffix = _suffix()
        with TestingSessionLocal() as session, session.begin():
            comercio = Comercio(
                nombre_fantasia=f"T {suffix}",
                nombre_corto=f"T {suffix}",
                razon_social=f"Trans {suffix} SRL",
                cuit=f"30-{suffix[:8]}-{suffix[8]}",
                whatsapp=f"+54925{suffix[:8]}",
                calle="Calle",
                numero="1",
                piso_departamento=None,
                localidad="CABA",
                provincia="Buenos Aires",
                codigo_postal="C1000",
                slug=f"comercio-trans-{suffix}",
                estado_id=estado_id,
                prueba_hasta=prueba_hasta,
                prueba_max_pedidos=prueba_max_pedidos,
                prueba_pedidos_consumidos=prueba_pedidos_consumidos,
            )
            session.add(comercio)
            session.flush()
            return int(comercio.id)

    def test_leaving_prueba_preserves_historical_configuration(self) -> None:
        future = datetime.now(tz=timezone.utc) + timedelta(days=3)
        comercio_id = self._make_comercio(
            estado_id=self._seed["PRUEBA"],
            prueba_hasta=future,
            prueba_max_pedidos=10,
            prueba_pedidos_consumidos=4,
        )
        try:
            with TestingSessionLocal() as session:
                service = ComercioService(session)
                service.update(
                    comercio_id,
                    {
                        "nombre_fantasia": "X",
                        "nombre_corto": "X",
                        "razon_social": "X SRL",
                        "cuit": "30-99999999-0",
                        "calle": "X",
                        "numero": "1",
                        "localidad": "CABA",
                        "provincia": "Buenos Aires",
                        "estado_id": self._seed["ACTIVO"],
                        "zona_horaria": "America/Argentina/Buenos_Aires",
                        "moneda": "ARS",
                        "idioma": "es-AR",
                    },
                )
            with TestingSessionLocal() as session:
                comercio = session.get(Comercio, comercio_id)
                assert comercio is not None
                self.assertEqual(int(comercio.estado_id), self._seed["ACTIVO"])
                self.assertEqual(comercio.prueba_hasta, future)
                self.assertEqual(comercio.prueba_max_pedidos, 10)
                self.assertEqual(comercio.prueba_pedidos_consumidos, 4)
        finally:
            _delete_comercio(comercio_id)

    def test_leaving_prueba_to_bloqueado_preserves_historical_configuration(
        self,
    ) -> None:
        future = datetime.now(tz=timezone.utc) + timedelta(days=4)
        comercio_id = self._make_comercio(
            estado_id=self._seed["PRUEBA"],
            prueba_hasta=future,
            prueba_max_pedidos=5,
            prueba_pedidos_consumidos=2,
        )
        try:
            with TestingSessionLocal() as session:
                service = ComercioService(session)
                service.update(
                    comercio_id,
                    {
                        "nombre_fantasia": "X",
                        "nombre_corto": "X",
                        "razon_social": "X SRL",
                        "cuit": "30-99999999-0",
                        "calle": "X",
                        "numero": "1",
                        "localidad": "CABA",
                        "provincia": "Buenos Aires",
                        "estado_id": self._seed["INACTIVO"],
                        "zona_horaria": "America/Argentina/Buenos_Aires",
                        "moneda": "ARS",
                        "idioma": "es-AR",
                    },
                )
            with TestingSessionLocal() as session:
                comercio = session.get(Comercio, comercio_id)
                assert comercio is not None
                self.assertEqual(int(comercio.estado_id), self._seed["INACTIVO"])
                self.assertEqual(comercio.prueba_hasta, future)
                self.assertEqual(comercio.prueba_max_pedidos, 5)
                self.assertEqual(comercio.prueba_pedidos_consumidos, 2)
        finally:
            _delete_comercio(comercio_id)

    def test_in_prueba_edit_ignores_forged_counter_reset(self) -> None:
        future = datetime.now(tz=timezone.utc) + timedelta(days=3)
        new_future = future + timedelta(days=2)
        comercio_id = self._make_comercio(
            estado_id=self._seed["PRUEBA"],
            prueba_hasta=future,
            prueba_max_pedidos=10,
            prueba_pedidos_consumidos=4,
        )
        try:
            with TestingSessionLocal() as session:
                service = ComercioService(session)
                with self.assertRaises(ValueError):
                    service.update(
                        comercio_id,
                        {
                            "nombre_fantasia": "X",
                            "nombre_corto": "X",
                            "razon_social": "X SRL",
                            "cuit": "30-99999999-0",
                            "calle": "X",
                            "numero": "1",
                            "localidad": "CABA",
                            "provincia": "Buenos Aires",
                            "estado_id": self._seed["PRUEBA"],
                            "prueba_hasta": new_future,
                            "prueba_max_pedidos": 20,
                            "prueba_pedidos_consumidos_reset": True,
                            "zona_horaria": "America/Argentina/Buenos_Aires",
                            "moneda": "ARS",
                            "idioma": "es-AR",
                        },
                    )
            with TestingSessionLocal() as session:
                comercio = session.get(Comercio, comercio_id)
                assert comercio is not None
                self.assertEqual(comercio.prueba_hasta, future)
                self.assertEqual(comercio.prueba_max_pedidos, 10)
                self.assertEqual(comercio.prueba_pedidos_consumidos, 4)
        finally:
            _delete_comercio(comercio_id)

    def test_in_prueba_edit_without_reset_flag_preserves_counter(self) -> None:
        future = datetime.now(tz=timezone.utc) + timedelta(days=3)
        new_future = future + timedelta(days=2)
        comercio_id = self._make_comercio(
            estado_id=self._seed["PRUEBA"],
            prueba_hasta=future,
            prueba_max_pedidos=10,
            prueba_pedidos_consumidos=6,
        )
        try:
            with TestingSessionLocal() as session:
                service = ComercioService(session)
                service.update(
                    comercio_id,
                    {
                        "nombre_fantasia": "X",
                        "nombre_corto": "X",
                        "razon_social": "X SRL",
                        "cuit": "30-99999999-0",
                        "calle": "X",
                        "numero": "1",
                        "localidad": "CABA",
                        "provincia": "Buenos Aires",
                        "estado_id": self._seed["PRUEBA"],
                        "prueba_hasta": new_future,
                        "prueba_max_pedidos": 20,
                        "zona_horaria": "America/Argentina/Buenos_Aires",
                        "moneda": "ARS",
                        "idioma": "es-AR",
                    },
                )
            with TestingSessionLocal() as session:
                comercio = session.get(Comercio, comercio_id)
                assert comercio is not None
                self.assertEqual(comercio.prueba_hasta, new_future)
                self.assertEqual(comercio.prueba_max_pedidos, 20)
                self.assertEqual(comercio.prueba_pedidos_consumidos, 6)
        finally:
            _delete_comercio(comercio_id)

    def test_entering_prueba_resets_counter(self) -> None:
        comercio_id = self._make_comercio(
            estado_id=self._seed["ACTIVO"],
            prueba_pedidos_consumidos=9,
        )
        future = datetime.now(tz=timezone.utc) + timedelta(days=3)
        try:
            with TestingSessionLocal() as session:
                service = ComercioService(session)
                service.update(
                    comercio_id,
                    {
                        "nombre_fantasia": "X",
                        "nombre_corto": "X",
                        "razon_social": "X SRL",
                        "cuit": "30-99999999-0",
                        "calle": "X",
                        "numero": "1",
                        "localidad": "CABA",
                        "provincia": "Buenos Aires",
                        "estado_id": self._seed["PRUEBA"],
                        "prueba_hasta": future,
                        "prueba_max_pedidos": 10,
                        "zona_horaria": "America/Argentina/Buenos_Aires",
                        "moneda": "ARS",
                        "idioma": "es-AR",
                    },
                )
            with TestingSessionLocal() as session:
                comercio = session.get(Comercio, comercio_id)
                assert comercio is not None
                self.assertEqual(int(comercio.estado_id), self._seed["PRUEBA"])
                self.assertEqual(comercio.prueba_pedidos_consumidos, 0)
        finally:
            _delete_comercio(comercio_id)


class ComerciosSeedByCodigoTest(unittest.TestCase):
    """The ``backend.db.seeds.seeds.comercios`` seed must resolve the
    ``estado_codigo`` reference against the live
    ``estado_comercio.codigo`` column (post-migration contract).

    The test exercises the real ``main()`` path against the project
    test database by swapping the JSON data file for a temporary
    fixture that uses a unique ``cuit`` per run so the test never
    collides with persisted fixtures or other tests.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._seed = _ensure_legacy_seed()

    def _write_json(self, tmp_path, rows):
        import json as _json

        data_file = tmp_path / "comercio_seed_test.json"
        data_file.write_text(_json.dumps(rows), encoding="utf-8")
        return data_file

    def _cleanup_comercio(self, slug: str, cuit: str) -> None:
        with TestingSessionLocal() as session, session.begin():
            session.execute(
                delete(Comercio).where(
                    (Comercio.slug == slug) | (Comercio.cuit == cuit)
                )
            )

    def test_seed_resolves_activo_by_codigo_and_inserts_with_correct_estado_id(
        self,
    ) -> None:
        import importlib
        import json as _json
        import os
        import sys
        from pathlib import Path

        suffix = _suffix()
        slug = f"seed-activo-{suffix}"
        cuit = f"30-{suffix[:8]}-{suffix[8]}"
        whatsapp = f"+54926{suffix[:8]}"
        data_file = self._write_json(
            Path("/tmp"),
            [
                {
                    "nombre_fantasia": "Seed Activo",
                    "nombre_corto": "SA",
                    "razon_social": "Seed Activo SRL",
                    "cuit": cuit,
                    "whatsapp": whatsapp,
                    "calle": "Av. Seed",
                    "numero": "100",
                    "piso_departamento": None,
                    "localidad": "CABA",
                    "provincia": "Buenos Aires",
                    "codigo_postal": "C1000",
                    "slug": slug,
                    "estado_codigo": "ACTIVO",
                }
            ],
        )

        repo_root = Path(__file__).resolve().parents[2]
        original_argv = sys.argv
        original_url = os.environ.get("SUPERNOVA_DATABASE_URL")
        os.environ["SUPERNOVA_DATABASE_URL"] = TEST_URL
        sys.path.insert(0, str(repo_root))
        try:
            seed_module = importlib.import_module(
                "backend.db.seeds.seeds.comercios"
            )
            importlib.reload(seed_module)
            with unittest.mock.patch.object(
                seed_module, "DATA_FILE", data_file
            ):
                seed_module.main()
        finally:
            sys.path.remove(str(repo_root))
            if original_url is None:
                os.environ.pop("SUPERNOVA_DATABASE_URL", None)
            else:
                os.environ["SUPERNOVA_DATABASE_URL"] = original_url
            sys.argv = original_argv

        with TestingSessionLocal() as session:
            comercio = session.execute(
                select(Comercio).where(Comercio.slug == slug)
            ).scalar_one_or_none()
            self.assertIsNotNone(comercio)
            assert comercio is not None
            self.assertEqual(int(comercio.estado_id), self._seed["ACTIVO"])
            self.assertEqual(comercio.cuit, cuit)

        self._cleanup_comercio(slug, cuit)

    def test_seed_rejects_unknown_estado_codigo_without_inserting(self) -> None:
        import importlib
        import os
        import sys
        from pathlib import Path

        suffix = _suffix()
        slug = f"seed-unknown-{suffix}"
        cuit = f"30-{suffix[:8]}-{suffix[8]}"
        whatsapp = f"+54927{suffix[:8]}"
        data_file = self._write_json(
            Path("/tmp"),
            [
                {
                    "nombre_fantasia": "Seed Unknown",
                    "nombre_corto": "SU",
                    "razon_social": "Seed Unknown SRL",
                    "cuit": cuit,
                    "whatsapp": whatsapp,
                    "calle": "Av. Seed",
                    "numero": "200",
                    "piso_departamento": None,
                    "localidad": "CABA",
                    "provincia": "Buenos Aires",
                    "codigo_postal": "C1000",
                    "slug": slug,
                    "estado_codigo": "BOGUS_STATE",
                }
            ],
        )

        repo_root = Path(__file__).resolve().parents[2]
        original_argv = sys.argv
        original_url = os.environ.get("SUPERNOVA_DATABASE_URL")
        os.environ["SUPERNOVA_DATABASE_URL"] = TEST_URL
        sys.path.insert(0, str(repo_root))
        try:
            seed_module = importlib.import_module(
                "backend.db.seeds.seeds.comercios"
            )
            importlib.reload(seed_module)
            with unittest.mock.patch.object(
                seed_module, "DATA_FILE", data_file
            ):
                with self.assertRaises(ValueError) as ctx:
                    seed_module.main()
                self.assertIn(
                    "estado_codigo 'BOGUS_STATE'",
                    str(ctx.exception),
                )
        finally:
            sys.path.remove(str(repo_root))
            if original_url is None:
                os.environ.pop("SUPERNOVA_DATABASE_URL", None)
            else:
                os.environ["SUPERNOVA_DATABASE_URL"] = original_url
            sys.argv = original_argv

        with TestingSessionLocal() as session:
            comercio = session.execute(
                select(Comercio).where(Comercio.slug == slug)
            ).scalar_one_or_none()
            self.assertIsNone(comercio)

        self._cleanup_comercio(slug, cuit)


if __name__ == "__main__":
    unittest.main()