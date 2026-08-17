"""Focused tests for the controlled-WhatsApp pilot routing CLI.

Coverage:

1. ``--verify-only`` returns ``ready`` for the exact active client +
   active dedicated channel + resolver RESOLVED to the selected
   commerce; returns ``not_ready`` for missing client / channel;
   returns ``inactive_client_requires_acknowledgement`` for an
   inactive client; returns ``configuration_failure`` for an
   existing wrong / inactive / shared channel.
2. ``--apply`` stages the missing active client and dedicated
   channel, flushes once, runs the final
   ``CommerceChannelResolver`` check, commits exactly once on
   success and rolls back on configuration failure.
3. The CLI never prints, logs or includes in an exception the
   ``--cliente-e164`` argument, the configured
   ``TWILIO_OUTBOUND_SENDER_E164`` sender, the supplied
   ``--comercio-id`` commerce address (when relevant) or any
   message body.
4. Exit codes map cleanly: ``0`` for ``ready`` / ``provisioned``,
   ``2`` for input / configuration rejection, ``3`` for any
   ``not_ready`` / ``inactive_client_requires_acknowledgement`` /
   ``configuration_failure`` / ``commerce_unavailable`` /
   ``duplicate_conflict`` status and ``1`` for technical failure.
5. The CLI is the sole owner of one setup transaction; the
   staging service never calls ``commit``, ``rollback``,
   ``begin`` or ``flush``; the resolver is the final gate before
   commit.

The tests use the live ``supernova_test`` PostgreSQL database and
seed / remove a per-test comercio, canal and client so unrelated
rows are never modified. The CLI receives a stub ``Settings``
instance and a stub session factory so no test reaches the real
``load_settings`` or the real ``_SessionLocal``.
"""
from __future__ import annotations

import ast
import contextlib
import io
import unittest
import uuid
from typing import Any
from unittest import mock

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from backend.cli.provision_whatsapp_pilot_routing import (
    EXIT_INPUT_INVALID,
    EXIT_NOT_READY,
    EXIT_OK,
    EXIT_TECHNICAL_FAILURE,
    build_parser,
    main,
)
from backend.config.settings import Settings
from backend.models import (
    CanalWhatsapp,
    CanalWhatsappMode,
    Cliente,
    Comercio,
    ComercioCanalCompartido,
    EstadoComercio,
)
from backend.services.whatsapp_pilot_routing_provisioning_service import (
    ProvisioningMode,
    ProvisioningStatus,
    WhatsappPilotRoutingProvisioningService,
)

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False
)


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _estado_id(nombre: str) -> int:
    with engine.connect() as c:
        row = c.execute(
            select(EstadoComercio.id).where(EstadoComercio.codigo == nombre)
        ).first()
        if row is None:
            raise RuntimeError(
                f"estado {nombre!r} not seeded in supernova_test"
            )
        return row[0]


def _seed_comercio(suffix: str | None = None) -> dict[str, Any]:
    suffix = suffix or _suffix()
    with TestingSessionLocal() as session, session.begin():
        comercio = Comercio(
            nombre_fantasia=f"Pilot Test {suffix}",
            nombre_corto=f"PT {suffix}",
            razon_social=f"Pilot Test SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+54941{suffix[:8]}",
            calle="Av. Pilot",
            numero="100",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"pilot-test-{suffix}",
            estado_id=_estado_id("ACTIVO"),
        )
        session.add(comercio)
        session.flush()
        comercio_id = int(comercio.id)
    return {"comercio_id": comercio_id, "suffix": suffix}


def _seed_inactive_comercio(suffix: str | None = None) -> dict[str, Any]:
    suffix = suffix or _suffix()
    with TestingSessionLocal() as session, session.begin():
        comercio = Comercio(
            nombre_fantasia=f"Pilot Inactive {suffix}",
            nombre_corto=f"PI {suffix}",
            razon_social=f"Pilot Inactive SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+54942{suffix[:8]}",
            calle="Av. Pilot",
            numero="200",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"pilot-inactive-{suffix}",
            estado_id=_estado_id("INACTIVO"),
        )
        session.add(comercio)
        session.flush()
        comercio_id = int(comercio.id)
    return {"comercio_id": comercio_id, "suffix": suffix}


def _delete_pilot_fixture(
    *,
    comercio_id: int,
    sender_e164: str,
    cliente_e164: str,
) -> None:
    with TestingSessionLocal() as session, session.begin():
        canal_ids_subquery = select(CanalWhatsapp.id).where(
            CanalWhatsapp.destination_e164 == sender_e164
        )
        session.execute(
            delete(ComercioCanalCompartido).where(
                ComercioCanalCompartido.canal_id.in_(canal_ids_subquery)
            )
        )
        session.execute(
            delete(CanalWhatsapp).where(
                CanalWhatsapp.destination_e164 == sender_e164
            )
        )
        session.execute(
            delete(CanalWhatsapp).where(
                CanalWhatsapp.id_comercio_exclusivo == comercio_id
            )
        )
        session.execute(
            delete(Cliente).where(Cliente.whatsapp == cliente_e164)
        )
        session.execute(delete(Comercio).where(Comercio.id == comercio_id))


def _settings(
    *,
    sender: str | None = "+5491100000000",
) -> Settings:
    return Settings(
        llm_url="http://llm.test",
        llm_model="test-llm",
        llm_timeout=30,
        llm_keep_alive="1h",
        llm_num_ctx=2048,
        llm_num_predict=256,
        llm_log_content=False,
        llm_log_max_chars=50,
        embedding_url="http://embed.test",
        embedding_model="test-embed",
        embedding_timeout_seconds=15,
        embedding_batch_size=32,
        embedding_dimension=384,
        twilio_auth_token="test-auth-token",
        twilio_account_sid="AC" + "0" * 32,
        twilio_webhook_base_url="https://example.test",
        twilio_outbound_sender_e164=sender,
        twilio_callback_status_url="https://example.test/cb",
        twilio_outbound_lease_seconds=30,
        twilio_outbound_initial_backoff_seconds=30,
        twilio_outbound_max_backoff_seconds=300,
        twilio_outbound_max_attempts=5,
    )


@contextlib.contextmanager
def _capture_streams() -> Any:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
        stderr
    ):
        yield stdout, stderr


def _destination(suffix: str, idx: int) -> str:
    digits = (int(suffix, 16) * 1000 + idx) % 10_000_000
    return f"+54931{digits:07d}"


def _delete_cliente(cliente_e164: str) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(Cliente).where(Cliente.whatsapp == cliente_e164)
        )


def _delete_canal(sender_e164: str) -> None:
    with TestingSessionLocal() as session, session.begin():
        canal_ids_subquery = select(CanalWhatsapp.id).where(
            CanalWhatsapp.destination_e164 == sender_e164
        )
        session.execute(
            delete(ComercioCanalCompartido).where(
                ComercioCanalCompartido.canal_id.in_(canal_ids_subquery)
            )
        )
        session.execute(
            delete(CanalWhatsapp).where(
                CanalWhatsapp.destination_e164 == sender_e164
            )
        )


class _SessionFactorySpy:
    """Callable wrapper around the real ``TestingSessionLocal``.

    The spy counts how many sessions the CLI opens so tests can
    assert the single-transaction contract without monkey-patching
    the global ``_SessionLocal`` factory.
    """

    def __init__(self) -> None:
        self.open_calls = 0

    def __call__(self) -> Session:
        self.open_calls += 1
        return TestingSessionLocal()


class CliVerifyModeTest(unittest.TestCase):
    """Verify mode coverage for the documented readiness outcomes."""

    def setUp(self) -> None:
        self.fixtures = _seed_comercio()
        self.suffix = self.fixtures["suffix"]
        self.comercio_id = int(self.fixtures["comercio_id"])
        self.sender = _destination(self.suffix, 1)
        self.cliente = _destination(self.suffix, 2)
        self.addCleanup(
            _delete_pilot_fixture,
            comercio_id=self.comercio_id,
            sender_e164=self.sender,
            cliente_e164=self.cliente,
        )

    def _seed_active_dedicated_canal(self) -> int:
        with TestingSessionLocal() as session, session.begin():
            from backend.services.canal_whatsapp_service import (
                CanalWhatsappService,
            )

            canal = CanalWhatsappService(session).register_dedicated_channel(
                provider="twilio",
                destination=self.sender,
                id_comercio_exclusivo=self.comercio_id,
            )
            session.flush()
            return int(canal.id)

    def _seed_active_cliente(self) -> int:
        with TestingSessionLocal() as session, session.begin():
            cliente = Cliente(
                whatsapp=self.cliente, nombre=None, domicilio=None, activo=True
            )
            session.add(cliente)
            session.flush()
            return int(cliente.id)

    def test_verify_ready_when_state_already_matches(self) -> None:
        canal_id = self._seed_active_dedicated_canal()
        cliente_id = self._seed_active_cliente()

        with _capture_streams() as (stdout, stderr):
            exit_code = main(
                argv=[
                    "--cliente-e164",
                    self.cliente,
                    "--comercio-id",
                    str(self.comercio_id),
                ],
                settings_loader=lambda: _settings(sender=self.sender),
                session_factory=_SessionFactorySpy(),
            )

        self.assertEqual(exit_code, EXIT_OK)
        rendered = stdout.getvalue()
        self.assertIn(f"status={ProvisioningStatus.READY.value}", rendered)
        self.assertIn(f"comercio_id={self.comercio_id}", rendered)
        self.assertIn(f"canal_id={canal_id}", rendered)
        self.assertIn(f"cliente_id={cliente_id}", rendered)
        self.assertIn("resolver_status=resolved", rendered)
        self.assertNotIn(self.cliente, rendered)
        self.assertNotIn(self.sender, rendered)
        self.assertEqual(stderr.getvalue(), "")

    def test_verify_not_ready_when_client_and_channel_missing(self) -> None:
        with _capture_streams() as (stdout, _stderr):
            exit_code = main(
                argv=[
                    "--cliente-e164",
                    self.cliente,
                    "--comercio-id",
                    str(self.comercio_id),
                ],
                settings_loader=lambda: _settings(sender=self.sender),
                session_factory=_SessionFactorySpy(),
            )

        self.assertEqual(exit_code, EXIT_NOT_READY)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={ProvisioningStatus.NOT_READY.value}",
            rendered,
        )
        self.assertIn("detalle=client_and_channel_missing", rendered)
        self.assertNotIn(self.cliente, rendered)
        self.assertNotIn(self.sender, rendered)

    def test_verify_not_ready_when_only_channel_missing(self) -> None:
        self._seed_active_cliente()
        with _capture_streams() as (stdout, _stderr):
            exit_code = main(
                argv=[
                    "--cliente-e164",
                    self.cliente,
                    "--comercio-id",
                    str(self.comercio_id),
                ],
                settings_loader=lambda: _settings(sender=self.sender),
                session_factory=_SessionFactorySpy(),
            )

        self.assertEqual(exit_code, EXIT_NOT_READY)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={ProvisioningStatus.NOT_READY.value}",
            rendered,
        )
        self.assertIn("detalle=channel_missing", rendered)

    def test_verify_inactive_client_requires_acknowledgement(self) -> None:
        canal_id = self._seed_active_dedicated_canal()
        with TestingSessionLocal() as session, session.begin():
            session.add(
                Cliente(
                    whatsapp=self.cliente,
                    nombre=None,
                    domicilio=None,
                    activo=False,
                )
            )

        with _capture_streams() as (stdout, _stderr):
            exit_code = main(
                argv=[
                    "--cliente-e164",
                    self.cliente,
                    "--comercio-id",
                    str(self.comercio_id),
                ],
                settings_loader=lambda: _settings(sender=self.sender),
                session_factory=_SessionFactorySpy(),
            )

        self.assertEqual(exit_code, EXIT_NOT_READY)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status="
            f"{ProvisioningStatus.INACTIVE_CLIENT_REQUIRES_ACKNOWLEDGEMENT.value}",
            rendered,
        )
        self.assertIn(f"canal_id={canal_id}", rendered)
        self.assertNotIn(self.cliente, rendered)
        self.assertNotIn(self.sender, rendered)

    def test_verify_configuration_failure_when_canal_wrong_commerce(
        self,
    ) -> None:
        other = _seed_comercio()
        self.addCleanup(
            _delete_pilot_fixture,
            comercio_id=int(other["comercio_id"]),
            sender_e164=self.sender,
            cliente_e164=self.cliente,
        )
        with TestingSessionLocal() as session, session.begin():
            from backend.services.canal_whatsapp_service import (
                CanalWhatsappService,
            )

            CanalWhatsappService(session).register_dedicated_channel(
                provider="twilio",
                destination=self.sender,
                id_comercio_exclusivo=int(other["comercio_id"]),
            )
        self._seed_active_cliente()

        with _capture_streams() as (stdout, _stderr):
            exit_code = main(
                argv=[
                    "--cliente-e164",
                    self.cliente,
                    "--comercio-id",
                    str(self.comercio_id),
                ],
                settings_loader=lambda: _settings(sender=self.sender),
                session_factory=_SessionFactorySpy(),
            )

        self.assertEqual(exit_code, EXIT_NOT_READY)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={ProvisioningStatus.CONFIGURATION_FAILURE.value}",
            rendered,
        )
        self.assertIn("detalle=channel_commerce_mismatch", rendered)

    def test_verify_configuration_failure_when_canal_inactive(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            from backend.services.canal_whatsapp_service import (
                CanalWhatsappService,
            )

            service = CanalWhatsappService(session)
            canal = service.register_dedicated_channel(
                provider="twilio",
                destination=self.sender,
                id_comercio_exclusivo=self.comercio_id,
            )
            session.flush()
            service.deactivate_channel(int(canal.id))
        self._seed_active_cliente()

        with _capture_streams() as (stdout, _stderr):
            exit_code = main(
                argv=[
                    "--cliente-e164",
                    self.cliente,
                    "--comercio-id",
                    str(self.comercio_id),
                ],
                settings_loader=lambda: _settings(sender=self.sender),
                session_factory=_SessionFactorySpy(),
            )

        self.assertEqual(exit_code, EXIT_NOT_READY)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={ProvisioningStatus.CONFIGURATION_FAILURE.value}",
            rendered,
        )
        self.assertIn("detalle=channel_inactive", rendered)


class CliApplyModeTest(unittest.TestCase):
    """Apply mode coverage for the documented provisioning outcomes."""

    def setUp(self) -> None:
        self.fixtures = _seed_comercio()
        self.suffix = self.fixtures["suffix"]
        self.comercio_id = int(self.fixtures["comercio_id"])
        self.sender = _destination(self.suffix, 1)
        self.cliente = _destination(self.suffix, 2)
        self.addCleanup(
            _delete_pilot_fixture,
            comercio_id=self.comercio_id,
            sender_e164=self.sender,
            cliente_e164=self.cliente,
        )

    def test_apply_provisions_missing_client_and_channel(self) -> None:
        spy = _SessionFactorySpy()
        with _capture_streams() as (stdout, stderr):
            exit_code = main(
                argv=[
                    "--cliente-e164",
                    self.cliente,
                    "--comercio-id",
                    str(self.comercio_id),
                    "--apply",
                ],
                settings_loader=lambda: _settings(sender=self.sender),
                session_factory=spy,
            )

        self.assertEqual(exit_code, EXIT_OK)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={ProvisioningStatus.PROVISIONED.value}",
            rendered,
        )
        self.assertIn("actions=client_created,channel_created", rendered)
        self.assertNotIn(self.cliente, rendered)
        self.assertNotIn(self.sender, rendered)
        self.assertEqual(stderr.getvalue(), "")

        with TestingSessionLocal() as session:
            from backend.models.canal_whatsapp import (
                CanalWhatsapp as CanalModel,
            )

            canal = (
                session.execute(
                    select(CanalModel).where(
                        CanalModel.destination_e164 == self.sender
                    )
                )
                .scalars()
                .first()
            )
            self.assertIsNotNone(canal)
            canal_row: Any = canal
            self.assertTrue(bool(canal_row.activo))
            self.assertEqual(
                int(canal_row.id_comercio_exclusivo), self.comercio_id
            )
            self.assertIs(canal_row.mode, CanalWhatsappMode.DEDICATED)

            cliente = (
                session.execute(
                    select(Cliente).where(Cliente.whatsapp == self.cliente)
                )
                .scalars()
                .first()
            )
            self.assertIsNotNone(cliente)
            cliente_row: Any = cliente
            self.assertTrue(bool(cliente_row.activo))

        self.assertEqual(spy.open_calls, 1)

    def test_apply_reactivates_inactive_client_with_ack(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            session.add(
                Cliente(
                    whatsapp=self.cliente,
                    nombre=None,
                    domicilio=None,
                    activo=False,
                )
            )

        with _capture_streams() as (stdout, stderr):
            exit_code = main(
                argv=[
                    "--cliente-e164",
                    self.cliente,
                    "--comercio-id",
                    str(self.comercio_id),
                    "--apply",
                    "--reactivate-client",
                ],
                settings_loader=lambda: _settings(sender=self.sender),
                session_factory=_SessionFactorySpy(),
            )

        self.assertEqual(exit_code, EXIT_OK)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={ProvisioningStatus.PROVISIONED.value}",
            rendered,
        )
        self.assertIn("actions=client_reactivated,channel_created", rendered)
        self.assertEqual(stderr.getvalue(), "")

        with TestingSessionLocal() as session:
            cliente = (
                session.execute(
                    select(Cliente).where(Cliente.whatsapp == self.cliente)
                )
                .scalars()
                .first()
            )
            self.assertIsNotNone(cliente)
            cliente_row: Any = cliente
            self.assertTrue(bool(cliente_row.activo))

    def test_apply_without_ack_returns_inactive_client_status(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            session.add(
                Cliente(
                    whatsapp=self.cliente,
                    nombre=None,
                    domicilio=None,
                    activo=False,
                )
            )

        with _capture_streams() as (stdout, _stderr):
            exit_code = main(
                argv=[
                    "--cliente-e164",
                    self.cliente,
                    "--comercio-id",
                    str(self.comercio_id),
                    "--apply",
                ],
                settings_loader=lambda: _settings(sender=self.sender),
                session_factory=_SessionFactorySpy(),
            )

        self.assertEqual(exit_code, EXIT_NOT_READY)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status="
            f"{ProvisioningStatus.INACTIVE_CLIENT_REQUIRES_ACKNOWLEDGEMENT.value}",
            rendered,
        )

        with TestingSessionLocal() as session:
            from backend.models.canal_whatsapp import (
                CanalWhatsapp as CanalModel,
            )

            canal = (
                session.execute(
                    select(CanalModel).where(
                        CanalModel.destination_e164 == self.sender
                    )
                )
                .scalars()
                .first()
            )
            self.assertIsNone(canal)
            cliente = (
                session.execute(
                    select(Cliente).where(Cliente.whatsapp == self.cliente)
                )
                .scalars()
                .first()
            )
            self.assertIsNotNone(cliente)
            cliente_row: Any = cliente
            self.assertFalse(bool(cliente_row.activo))

    def test_apply_rolls_back_on_conflicting_canal(self) -> None:
        other = _seed_comercio()
        self.addCleanup(
            _delete_pilot_fixture,
            comercio_id=int(other["comercio_id"]),
            sender_e164=self.sender,
            cliente_e164=self.cliente,
        )
        with TestingSessionLocal() as session, session.begin():
            from backend.services.canal_whatsapp_service import (
                CanalWhatsappService,
            )

            CanalWhatsappService(session).register_dedicated_channel(
                provider="twilio",
                destination=self.sender,
                id_comercio_exclusivo=int(other["comercio_id"]),
            )

        with _capture_streams() as (stdout, _stderr):
            exit_code = main(
                argv=[
                    "--cliente-e164",
                    self.cliente,
                    "--comercio-id",
                    str(self.comercio_id),
                    "--apply",
                ],
                settings_loader=lambda: _settings(sender=self.sender),
                session_factory=_SessionFactorySpy(),
            )

        self.assertEqual(exit_code, EXIT_NOT_READY)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={ProvisioningStatus.CONFIGURATION_FAILURE.value}",
            rendered,
        )

        with TestingSessionLocal() as session:
            cliente = (
                session.execute(
                    select(Cliente).where(Cliente.whatsapp == self.cliente)
                )
                .scalars()
                .first()
            )
            self.assertIsNone(cliente)

    def test_apply_returns_ready_when_exact_canal_and_cliente_already_match(
        self,
    ) -> None:
        canal_id = self._seed_active_dedicated_canal()
        cliente_id = self._seed_active_cliente()

        with _capture_streams() as (stdout, stderr):
            exit_code = main(
                argv=[
                    "--cliente-e164",
                    self.cliente,
                    "--comercio-id",
                    str(self.comercio_id),
                    "--apply",
                ],
                settings_loader=lambda: _settings(sender=self.sender),
                session_factory=_SessionFactorySpy(),
            )

        self.assertEqual(exit_code, EXIT_OK)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={ProvisioningStatus.READY.value}",
            rendered,
        )
        self.assertIn(f"canal_id={canal_id}", rendered)
        self.assertIn(f"cliente_id={cliente_id}", rendered)
        self.assertIn("resolver_status=resolved", rendered)
        self.assertNotIn("actions=", rendered)
        self.assertNotIn(self.cliente, rendered)
        self.assertNotIn(self.sender, rendered)
        self.assertEqual(stderr.getvalue(), "")

        with TestingSessionLocal() as session:
            from backend.models.canal_whatsapp import (
                CanalWhatsapp as CanalModel,
            )

            canales = list(
                session.execute(
                    select(CanalModel).where(
                        CanalModel.destination_e164 == self.sender
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(len(canales), 1)
            canal_row: Any = canales[0]
            self.assertEqual(int(canal_row.id), canal_id)
            self.assertTrue(bool(canal_row.activo))
            self.assertEqual(
                int(canal_row.id_comercio_exclusivo), self.comercio_id
            )
            self.assertIs(canal_row.mode, CanalWhatsappMode.DEDICATED)

            cliente = (
                session.execute(
                    select(Cliente).where(Cliente.whatsapp == self.cliente)
                )
                .scalars()
                .first()
            )
            self.assertIsNotNone(cliente)
            cliente_row: Any = cliente
            self.assertEqual(int(cliente_row.id), cliente_id)
            self.assertTrue(bool(cliente_row.activo))

    def test_apply_provisions_only_cliente_when_exact_canal_already_exists(
        self,
    ) -> None:
        canal_id = self._seed_active_dedicated_canal()

        with _capture_streams() as (stdout, stderr):
            exit_code = main(
                argv=[
                    "--cliente-e164",
                    self.cliente,
                    "--comercio-id",
                    str(self.comercio_id),
                    "--apply",
                ],
                settings_loader=lambda: _settings(sender=self.sender),
                session_factory=_SessionFactorySpy(),
            )

        self.assertEqual(exit_code, EXIT_OK)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={ProvisioningStatus.PROVISIONED.value}",
            rendered,
        )
        self.assertIn("actions=client_created", rendered)
        self.assertNotIn("channel_created", rendered)
        self.assertNotIn(self.cliente, rendered)
        self.assertNotIn(self.sender, rendered)
        self.assertEqual(stderr.getvalue(), "")

        with TestingSessionLocal() as session:
            from backend.models.canal_whatsapp import (
                CanalWhatsapp as CanalModel,
            )

            canales = list(
                session.execute(
                    select(CanalModel).where(
                        CanalModel.destination_e164 == self.sender
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(len(canales), 1)
            canal_row: Any = canales[0]
            self.assertEqual(int(canal_row.id), canal_id)
            self.assertTrue(bool(canal_row.activo))
            self.assertEqual(
                int(canal_row.id_comercio_exclusivo), self.comercio_id
            )
            self.assertIs(canal_row.mode, CanalWhatsappMode.DEDICATED)

            cliente = (
                session.execute(
                    select(Cliente).where(Cliente.whatsapp == self.cliente)
                )
                .scalars()
                .first()
            )
            self.assertIsNotNone(cliente)
            cliente_row: Any = cliente
            self.assertTrue(bool(cliente_row.activo))

    def _seed_active_dedicated_canal(self) -> int:
        with TestingSessionLocal() as session, session.begin():
            from backend.services.canal_whatsapp_service import (
                CanalWhatsappService,
            )

            canal = CanalWhatsappService(session).register_dedicated_channel(
                provider="twilio",
                destination=self.sender,
                id_comercio_exclusivo=self.comercio_id,
            )
            session.flush()
            return int(canal.id)

    def _seed_active_cliente(self) -> int:
        with TestingSessionLocal() as session, session.begin():
            cliente = Cliente(
                whatsapp=self.cliente, nombre=None, domicilio=None, activo=True
            )
            session.add(cliente)
            session.flush()
            return int(cliente.id)


class CliConfigurationAndInputTest(unittest.TestCase):
    """Input / configuration rejection coverage."""

    def setUp(self) -> None:
        self.fixtures = _seed_comercio()
        self.suffix = self.fixtures["suffix"]
        self.comercio_id = int(self.fixtures["comercio_id"])
        self.sender = _destination(self.suffix, 1)
        self.cliente = _destination(self.suffix, 2)
        self.addCleanup(
            _delete_pilot_fixture,
            comercio_id=self.comercio_id,
            sender_e164=self.sender,
            cliente_e164=self.cliente,
        )

    def test_missing_sender_setting_fails_with_exit_code_two(self) -> None:
        with _capture_streams() as (stdout, stderr):
            exit_code = main(
                argv=[
                    "--cliente-e164",
                    self.cliente,
                    "--comercio-id",
                    str(self.comercio_id),
                ],
                settings_loader=lambda: _settings(sender=None),
                session_factory=_SessionFactorySpy(),
            )

        self.assertEqual(exit_code, EXIT_INPUT_INVALID)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("invalid_sender", stderr.getvalue())
        self.assertNotIn(self.cliente, stderr.getvalue())
        self.assertNotIn(self.sender, stderr.getvalue())

    def test_invalid_cliente_e164_fails_with_exit_code_two(self) -> None:
        with _capture_streams() as (stdout, stderr):
            exit_code = main(
                argv=[
                    "--cliente-e164",
                    "not-a-number",
                    "--comercio-id",
                    str(self.comercio_id),
                ],
                settings_loader=lambda: _settings(sender=self.sender),
                session_factory=_SessionFactorySpy(),
            )

        self.assertEqual(exit_code, EXIT_INPUT_INVALID)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("invalid_cliente_e164", stderr.getvalue())

    def test_invalid_comercio_id_fails_with_exit_code_two(self) -> None:
        with _capture_streams() as (_stdout, stderr):
            with self.assertRaises(SystemExit) as ctx:
                main(
                    argv=[
                        "--cliente-e164",
                        self.cliente,
                        "--comercio-id",
                        "0",
                    ],
                    settings_loader=lambda: _settings(sender=self.sender),
                    session_factory=_SessionFactorySpy(),
                )
        self.assertEqual(ctx.exception.code, EXIT_INPUT_INVALID)
        self.assertIn("--comercio-id", stderr.getvalue())

    def test_commerce_unavailable_returns_typed_status(self) -> None:
        inactive = _seed_inactive_comercio()
        self.addCleanup(
            _delete_pilot_fixture,
            comercio_id=int(inactive["comercio_id"]),
            sender_e164=self.sender,
            cliente_e164=self.cliente,
        )

        with _capture_streams() as (stdout, _stderr):
            exit_code = main(
                argv=[
                    "--cliente-e164",
                    self.cliente,
                    "--comercio-id",
                    str(inactive["comercio_id"]),
                ],
                settings_loader=lambda: _settings(sender=self.sender),
                session_factory=_SessionFactorySpy(),
            )

        self.assertEqual(exit_code, EXIT_NOT_READY)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={ProvisioningStatus.COMMERCE_UNAVAILABLE.value}",
            rendered,
        )


class CliSanitizedOutputTest(unittest.TestCase):
    """The CLI must never echo the address, sender, body, credential
    or DB URL."""

    def setUp(self) -> None:
        self.fixtures = _seed_comercio()
        self.suffix = self.fixtures["suffix"]
        self.comercio_id = int(self.fixtures["comercio_id"])
        self.sender = _destination(self.suffix, 1)
        self.cliente = _destination(self.suffix, 2)
        self.addCleanup(
            _delete_pilot_fixture,
            comercio_id=self.comercio_id,
            sender_e164=self.sender,
            cliente_e164=self.cliente,
        )

    def test_summary_excludes_address_sender_and_secrets(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            from backend.services.canal_whatsapp_service import (
                CanalWhatsappService,
            )

            CanalWhatsappService(session).register_dedicated_channel(
                provider="twilio",
                destination=self.sender,
                id_comercio_exclusivo=self.comercio_id,
            )
            session.add(
                Cliente(
                    whatsapp=self.cliente,
                    nombre=None,
                    domicilio=None,
                    activo=True,
                )
            )

        with _capture_streams() as (stdout, stderr):
            exit_code = main(
                argv=[
                    "--cliente-e164",
                    self.cliente,
                    "--comercio-id",
                    str(self.comercio_id),
                ],
                settings_loader=lambda: _settings(sender=self.sender),
                session_factory=_SessionFactorySpy(),
            )

        self.assertEqual(exit_code, EXIT_OK)
        rendered = stdout.getvalue() + stderr.getvalue()
        forbidden = (
            self.cliente,
            self.sender,
            "test-auth-token",
            "AC000000000000000000000000000000",
            "https://example.test/cb",
            "postgresql",
            "supernova_test",
        )
        for token in forbidden:
            self.assertNotIn(token, rendered)


class CliModuleBoundariesTest(unittest.TestCase):
    """The CLI must not import or invoke pipeline components."""

    def test_cli_does_not_import_pipeline_modules(self) -> None:
        from backend.cli import provision_whatsapp_pilot_routing as cli

        source = cli.__file__
        assert source is not None
        with open(source, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        forbidden = {
            "backend.routers.incoming_messages",
            "backend.routers.twilio_webhook",
            "backend.intents.orchestration.incoming_message_orchestrator",
            "backend.recognizers.product_recognizer",
            "backend.services.outbound_message_dispatcher",
            "backend.services.twilio_delivery_callback_adapter",
            "backend.scripts.cli_chat_client",
        }
        module_imports = [
            node
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        for node in module_imports:
            target = (
                {alias.name for alias in node.names}
                if isinstance(node, ast.Import)
                else {node.module or ""}
            )
            self.assertFalse(
                any(t in forbidden for t in target),
                f"CLI must not import pipeline modules (found {target!r})",
            )

    def test_staging_service_does_not_call_commit_or_rollback(self) -> None:
        fixtures = _seed_comercio()
        suffix = fixtures["suffix"]
        comercio_id = int(fixtures["comercio_id"])
        sender = _destination(suffix, 1)
        cliente = _destination(suffix, 2)
        self.addCleanup(
            _delete_pilot_fixture,
            comercio_id=comercio_id,
            sender_e164=sender,
            cliente_e164=cliente,
        )
        with TestingSessionLocal() as session:
            service = WhatsappPilotRoutingProvisioningService(session)
            with mock.patch.object(
                session, "commit"
            ) as commit, mock.patch.object(
                session, "rollback"
            ) as rollback, mock.patch.object(
                session, "begin"
            ) as begin, mock.patch.object(
                session, "flush"
            ) as flush:
                result = service.apply(
                    cliente_e164_canonical=cliente,
                    comercio_id=comercio_id,
                    sender_e164_canonical=sender,
                    reactivate_client_acknowledgement=False,
                )
        self.assertEqual(result.mode, ProvisioningMode.APPLY)
        commit.assert_not_called()
        rollback.assert_not_called()
        begin.assert_not_called()
        flush.assert_not_called()


class CliParserTest(unittest.TestCase):
    def test_help_lists_required_flags(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        self.assertIn("--cliente-e164", help_text)
        self.assertIn("--comercio-id", help_text)
        self.assertIn("--apply", help_text)
        self.assertIn("--reactivate-client", help_text)

    def test_parser_rejects_missing_required_arg(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])


class CliUnexpectedFailureTest(unittest.TestCase):
    """A technical failure (e.g. database unreachable) must surface as
    exit code ``1`` with a sanitized status."""

    def setUp(self) -> None:
        self.fixtures = _seed_comercio()
        self.suffix = self.fixtures["suffix"]
        self.comercio_id = int(self.fixtures["comercio_id"])
        self.sender = _destination(self.suffix, 1)
        self.cliente = _destination(self.suffix, 2)
        self.addCleanup(
            _delete_pilot_fixture,
            comercio_id=self.comercio_id,
            sender_e164=self.sender,
            cliente_e164=self.cliente,
        )

    def test_unexpected_session_failure_returns_exit_code_one(self) -> None:
        class _BrokenSessionFactory:
            def __call__(self) -> Session:
                raise RuntimeError("secret-cliente-e164 db=postgresql")

        with _capture_streams() as (stdout, stderr):
            exit_code = main(
                argv=[
                    "--cliente-e164",
                    self.cliente,
                    "--comercio-id",
                    str(self.comercio_id),
                ],
                settings_loader=lambda: _settings(sender=self.sender),
                session_factory=_BrokenSessionFactory(),
            )

        self.assertEqual(exit_code, EXIT_TECHNICAL_FAILURE)
        rendered = stdout.getvalue() + stderr.getvalue()
        self.assertIn(
            ProvisioningStatus.TECHNICAL_FAILURE.value,
            rendered,
        )
        self.assertNotIn("secret-cliente-e164", rendered)
        self.assertNotIn("postgresql", rendered)
        self.assertNotIn(self.cliente, rendered)
        self.assertNotIn(self.sender, rendered)


def _resolve_post_apply_for_test(
    service: WhatsappPilotRoutingProvisioningService,
    sender: str,
    comercio_id: int,
    cliente_id: int | None,
    canal_id: int | None,
) -> Any:
    """Wrapper so tests can target the internal helper indirectly.

    The wrapper mirrors the post-apply resolver check used by the
    CLI; tests that need to drive the path directly call this
    helper instead of importing the private symbol.
    """
    from backend.cli.provision_whatsapp_pilot_routing import (
        _resolve_post_apply,
    )
    from backend.services.whatsapp_pilot_routing_provisioning_service import (
        ProvisioningMode,
        ProvisioningResult,
        ProvisioningStatus,
    )

    staging = ProvisioningResult(
        mode=ProvisioningMode.APPLY,
        status=ProvisioningStatus.NOT_READY,
        comercio_id=comercio_id,
        cliente_id=cliente_id,
        canal_id=canal_id,
        resolver_status=None,
    )
    return _resolve_post_apply(
        service=service,
        cliente_e164_canonical="+5491100000000",
        sender_e164_canonical=sender,
        comercio_id=comercio_id,
        staging=staging,
    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
