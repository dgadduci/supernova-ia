"""Focused tests for the bounded ``OutboundCommandDispatcher`` helper.

The tests cover the documented behaviour:

* the helper is gated by the documented feature flag — when the flag is
  off the helper raises :class:`OutboundCommandSkipped` so the central
  dispatcher falls back to the documented central Twilio path;
* the helper uses the per-installation ``tc_service_url`` stored on the
  installation row, never a global base URL — two installations for two
  commerces route to two different URLs;
* the helper claims the durable
  ``instalaciones_twilio_comercio_idempotencia`` slot for every accepted
  command in its own short transaction; concurrent dispatchers
  serialise through the unique database index; the second caller
  recovers the durable state without firing a second ``messages.create``;
* the same ``(instalacion_id, idempotency_key)`` returns the durable
  result without firing a second ``messages.create`` even when the
  helper is restarted between calls;
* the durable claim survives the closure of the session used for the
  helper call — the central dispatcher closes its short-lived session
  after the helper returns and the claim is still observable from a
  fresh session;
* the durable claim row is left ``in_progress`` after a network
  timeout / malformed body so a subsequent retry returns the durable
  state instead of firing a second send;
* the helper classifies HTTP responses per the documented contract:
  ``200`` with typed body finalizes the claim, ``401`` / ``403`` /
  ``400`` finalize as ``terminal``, ``429`` / ``5xx`` finalize as
  ``retryable``, timeouts and connection errors leave the claim
  ``in_progress`` and raise :class:`OutboundCommandAmbiguous`;
* the bounded state machine for the durable claim row:
  ``sent`` / ``terminal`` / ``in_progress`` never fire a second
  ``messages.create``; ``retryable`` atomically transitions to
  ``in_progress`` on the next dispatch and performs a new HTTP
  call — two concurrent callers on the same ``retryable`` row
  serialise through the conditional ``UPDATE`` so only one
  performs the new send while the other returns the durable
  state without calling T-C;
* the central ``OutboundMessageDispatcher.dispatch()`` flow invokes the
  helper when the flag is on and an active installation exists, and
  falls back to the documented central Twilio path when no active
  installation exists. The retryable → sent retry sequence is driven
  through the real central dispatcher so the bounded CLI / outbox
  lease / finalize path is exercised end-to-end.

The tests intentionally avoid mocking the Twilio SDK; they inject a
fake HTTP poster through the documented ``http_post`` seam so no real
network call is performed. The concurrent claim test uses two
independent sessions and two independent transactions driven by a
``threading.Barrier`` so the second caller really races the first one
on the unique database constraint.
"""
from __future__ import annotations

import json
import os
import threading
import unittest
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

from cryptography.fernet import Fernet
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from backend.config.settings import Settings
from backend.models import (
    CanalWhatsapp,
    CanalWhatsappMode,
    Comercio,
    EstadoComercio,
    InstalacionTwilioComercio,
    InstalacionTwilioComercioIdempotencia,
    MensajeProveedorSaliente,
    OutboundProviderMessageState,
    RecepcionMensajeProveedor,
)
from backend.services.instalacion_secret_envelope import (
    encrypt_secret,
    resolve_master_keys,
)
from backend.services.outbound_command_dispatcher import (
    OutboundCommandAmbiguous,
    OutboundCommandDispatcher,
    OutboundCommandResult,
    OutboundCommandSkipped,
)

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)

MASTER_KEY: str = Fernet.generate_key().decode("ascii")
os.environ["COMMERCE_INSTALLATION_MASTER_KEY"] = MASTER_KEY


def _settings(
    *,
    isolated_enabled: bool = True,
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
        twilio_outbound_sender_e164="+5491100000000",
        twilio_callback_status_url=None,
        twilio_outbound_lease_seconds=30,
        twilio_outbound_initial_backoff_seconds=30,
        twilio_outbound_max_backoff_seconds=300,
        twilio_outbound_max_attempts=5,
        commerce_isolated_outbound_enabled=bool(isolated_enabled),
        commerce_isolated_http_timeout_seconds=5,
        commerce_isolated_tc_base_url_legacy=None,
    )


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _estado_id_activo() -> int:
    with engine.connect() as c:
        row = c.execute(
            select(EstadoComercio.id).where(EstadoComercio.codigo == "ACTIVO")
        ).first()
        if row is None:
            raise RuntimeError("estado ACTIVO not seeded")
        return int(row[0])


def _seed_comercio(suffix: str) -> int:
    with TestingSessionLocal() as session, session.begin():
        comercio = Comercio(
            nombre_fantasia=f"Isolated {suffix}",
            nombre_corto=f"II {suffix}",
            razon_social=f"Isolated SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+54915{suffix[:8]}",
            calle="Av. Iso",
            numero="100",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"iso-{suffix}",
            estado_id=_estado_id_activo(),
        )
        session.add(comercio)
        session.flush()
        return int(comercio.id)


def _seed_recepcion(comercio_id: int) -> tuple[int, int, int]:
    canal_id = _seed_canal(comercio_id)
    cliente_id = _seed_cliente()
    with TestingSessionLocal() as session, session.begin():
        recepcion = RecepcionMensajeProveedor(
            comercio_id=comercio_id,
            proveedor="twilio",
            identificador_recepcion=f"SM-{uuid.uuid4().hex[:10]}",
            canal_id=canal_id,
            cliente_id=cliente_id,
            fecha_recepcion=datetime.now(tz=timezone.utc),
        )
        session.add(recepcion)
        session.flush()
        return int(recepcion.id), int(canal_id), int(cliente_id)


def _seed_canal(comercio_id: int) -> int:
    with TestingSessionLocal() as session, session.begin():
        canal = CanalWhatsapp(
            provider="twilio",
            destination_e164=f"+54916{uuid.uuid4().hex[:7]}",
            mode=CanalWhatsappMode.DEDICATED,
            id_comercio_exclusivo=comercio_id,
            activo=True,
        )
        session.add(canal)
        session.flush()
        return int(canal.id)


def _seed_cliente() -> int:
    from backend.models import Cliente

    with TestingSessionLocal() as session, session.begin():
        cliente = Cliente(
            whatsapp=f"+54917{uuid.uuid4().hex[:7]}",
            nombre="Iso",
            domicilio=None,
            activo=True,
        )
        session.add(cliente)
        session.flush()
        return int(cliente.id)


def _seed_outbox(recepcion_id: int) -> int:
    from datetime import datetime, timezone

    with TestingSessionLocal() as session, session.begin():
        row = MensajeProveedorSaliente(
            proveedor="twilio",
            recepcion_mensaje_proveedor_id=recepcion_id,
            destinatario_e164="+5491155556666",
            cuerpo="hola",
            sequence=0,
            estado=OutboundProviderMessageState.PENDING.value,
            identificador_proveedor=None,
            intentos=1,
            proximo_intento_en=None,
            token_lease=None,
            lease_expira_en=None,
            categoria_ultimo_fallo=None,
            codigo_ultimo_fallo=None,
            estado_proveedor=None,
            estado_proveedor_en=None,
            fecha_creacion=datetime.now(tz=timezone.utc),
        )
        session.add(row)
        session.flush()
        return int(row.id)


def _seed_instalacion(
    *,
    comercio_id: int,
    instalacion_id: str,
    plain_secret: str,
    tc_service_url: str,
) -> None:
    bundle = resolve_master_keys(current_env=MASTER_KEY, previous_env=None)
    envelope, key_id = encrypt_secret(
        plain_secret=plain_secret, bundle=bundle
    )
    with TestingSessionLocal() as session, session.begin():
        row = InstalacionTwilioComercio(
            id_comercio=comercio_id,
            tc_service_url=tc_service_url,
            instalacion_id=instalacion_id,
            activo=True,
            secreto_envelope=envelope,
            secreto_envelope_kid=key_id,
        )
        session.add(row)


def _cleanup(comercio_id: int, instalacion_id: str | None = None) -> None:
    from backend.models import (
        Cliente,
        MensajeProveedorSaliente,
        RecepcionMensajeProveedor,
    )

    with TestingSessionLocal() as session, session.begin():
        if instalacion_id is not None:
            session.execute(
                delete(InstalacionTwilioComercioIdempotencia).where(
                    InstalacionTwilioComercioIdempotencia.instalacion_id
                    == instalacion_id
                )
            )
        session.execute(
            delete(MensajeProveedorSaliente).where(
                MensajeProveedorSaliente.recepcion_mensaje_proveedor_id.in_(
                    select(RecepcionMensajeProveedor.id).where(
                        RecepcionMensajeProveedor.comercio_id == comercio_id
                    )
                )
            )
        )
        session.execute(
            delete(RecepcionMensajeProveedor).where(
                RecepcionMensajeProveedor.comercio_id == comercio_id
            )
        )
        session.execute(
            delete(Cliente).where(
                Cliente.id.in_(
                    select(RecepcionMensajeProveedor.cliente_id).where(
                        RecepcionMensajeProveedor.comercio_id == comercio_id
                    )
                )
            )
        )
        session.execute(
            delete(InstalacionTwilioComercio).where(
                InstalacionTwilioComercio.id_comercio == comercio_id
            )
        )
        session.execute(
            delete(CanalWhatsapp).where(
                CanalWhatsapp.id_comercio_exclusivo == comercio_id
            )
        )
        session.execute(delete(Comercio).where(Comercio.id == comercio_id))


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        body: dict[str, Any] | None = None,
        text: str | None = None,
    ) -> None:
        self.status_code = int(status_code)
        if text is not None:
            self.text = str(text)
        else:
            self.text = json.dumps(body) if body is not None else ""


class HelperTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.suffix = _suffix()
        self.comercio_id = _seed_comercio(self.suffix)
        self.recepcion_id, _canal, _cliente = _seed_recepcion(self.comercio_id)
        self.outbox_id = _seed_outbox(self.recepcion_id)
        self.instalacion_id = (
            "i" + self.suffix + ("a" * (23 - len(self.suffix)))
        )[:24]
        self.plain_secret = "shared-secret-1234567890"
        self.tc_service_url = "https://tc.example.test"
        _seed_instalacion(
            comercio_id=self.comercio_id,
            instalacion_id=self.instalacion_id,
            plain_secret=self.plain_secret,
            tc_service_url=self.tc_service_url,
        )

    def tearDown(self) -> None:
        _cleanup(self.comercio_id, self.instalacion_id)


def _load_outbox(outbox_id: int) -> MensajeProveedorSaliente:
    session = TestingSessionLocal()
    try:
        return session.get(MensajeProveedorSaliente, outbox_id)
    finally:
        session.close()


class OutboundCommandDispatcherFlagOffTest(HelperTestCase):
    def test_flag_off_raises_skipped(self) -> None:
        helper = OutboundCommandDispatcher(
            session_factory=TestingSessionLocal,
            settings=_settings(isolated_enabled=False),
            master_keys=resolve_master_keys(
                current_env=MASTER_KEY, previous_env=None
            ),
        )
        with self.assertRaises(OutboundCommandSkipped):
            helper.dispatch(outbox_row=_load_outbox(self.outbox_id))


class OutboundCommandDispatcherHappyPathTest(HelperTestCase):
    def test_uses_per_installation_url_and_only_one_call(self) -> None:
        calls: list[dict[str, Any]] = []

        def _http_post(*, url: str, payload: bytes, headers: dict[str, str]):
            calls.append(
                {"url": url, "payload": payload, "headers": headers}
            )
            return _FakeResponse(
                status_code=200,
                body={"status": "sent", "message_sid": "SM-XYZ"},
            )

        helper = OutboundCommandDispatcher(
            session_factory=TestingSessionLocal,
            settings=_settings(isolated_enabled=True),
            master_keys=resolve_master_keys(
                current_env=MASTER_KEY, previous_env=None
            ),
            http_post=_http_post,
        )
        result = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        self.assertEqual(result.status, "sent")
        self.assertEqual(result.message_sid, "SM-XYZ")
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(
            call["url"],
            "https://tc.example.test/internal/commands/send-message",
        )
        body = json.loads(call["payload"].decode("utf-8"))
        self.assertEqual(body["instalacion_id"], self.instalacion_id)
        self.assertEqual(body["comercio_id"], self.comercio_id)
        self.assertEqual(body["idempotency_key"], f"outbox-{self.outbox_id}")
        self.assertEqual(body["status_callback_url"], None)
        self.assertEqual(
            call["headers"]["X-Installation-Id"], self.instalacion_id
        )
        self.assertEqual(len(call["headers"]["X-Installation-Signature"]), 64)

        with TestingSessionLocal() as verify_session:
            claim = verify_session.execute(
                select(InstalacionTwilioComercioIdempotencia).where(
                    InstalacionTwilioComercioIdempotencia.instalacion_id
                    == self.instalacion_id,
                    InstalacionTwilioComercioIdempotencia.idempotency_key
                    == f"outbox-{self.outbox_id}",
                )
            ).scalar_one()
            self.assertEqual(claim.estado, "sent")
            self.assertEqual(claim.message_sid, "SM-XYZ")


class OutboundCommandDispatcherClaimPersistsAcrossSessionsTest(
    HelperTestCase
):
    """The claim survives the closure of the helper's short session.

    The helper opens short-lived sessions for the claim and the
    finalize. A fresh database session opened after the helper returns
    must observe the durable claim row in the documented state so the
    bounded CLI / central dispatcher can resume the row in its own
    caller-owned transaction.
    """

    def test_claim_persisted_through_real_dispatcher_flow(self) -> None:
        from backend.services.outbound_dispatch_types import (
            OutboundDispatchOutcome,
        )
        from backend.services.outbound_message_dispatcher import (
            OutboundDispatchConfig,
            OutboundMessageDispatcher,
        )

        calls: list[dict[str, Any]] = []

        def _http_post(*, url: str, payload: bytes, headers: dict[str, str]):
            calls.append(
                {"url": url, "payload": payload, "headers": headers}
            )
            return _FakeResponse(
                status_code=200,
                body={"status": "sent", "message_sid": "SM-XYZ"},
            )

        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        claimed_row = MensajeProveedorSaliente(
            id=self.outbox_id,
            proveedor="twilio",
            recepcion_mensaje_proveedor_id=self.recepcion_id,
            destinatario_e164="+5491155556666",
            cuerpo="hola",
            sequence=0,
            estado=OutboundProviderMessageState.LEASED.value,
            identificador_proveedor=None,
            intentos=1,
            proximo_intento_en=None,
            token_lease="lease-token-1",
            lease_expira_en=None,
            categoria_ultimo_fallo=None,
            codigo_ultimo_fallo=None,
            estado_proveedor=None,
            estado_proveedor_en=None,
            fecha_creacion=datetime.now(tz=timezone.utc),
        )
        outbox_repo.claim_due.return_value = claimed_row
        outbox_repo.finalize_accepted.return_value = True

        dispatcher = OutboundMessageDispatcher(
            session_factory=TestingSessionLocal,
            config=OutboundDispatchConfig(
                sender_e164="+5491100000000",
                status_callback_url=None,
                lease_seconds=30,
                initial_backoff_seconds=30,
                max_backoff_seconds=300,
                max_attempts=5,
            ),
            outbox_repo_factory=lambda _session: outbox_repo,
            settings=_settings(isolated_enabled=True),
            isolated_dispatcher_factory=lambda factory: OutboundCommandDispatcher(
                session_factory=factory,
                settings=_settings(isolated_enabled=True),
                master_keys=resolve_master_keys(
                    current_env=MASTER_KEY, previous_env=None
                ),
                http_post=_http_post,
            ),
        )

        result = dispatcher.dispatch()
        self.assertEqual(result.outcome, OutboundDispatchOutcome.SENT)
        self.assertEqual(len(calls), 1)

        with TestingSessionLocal() as verify_session:
            claim = verify_session.execute(
                select(InstalacionTwilioComercioIdempotencia).where(
                    InstalacionTwilioComercioIdempotencia.instalacion_id
                    == self.instalacion_id,
                    InstalacionTwilioComercioIdempotencia.idempotency_key
                    == f"outbox-{self.outbox_id}",
                )
            ).scalar_one()
            self.assertEqual(claim.estado, "sent")
            self.assertEqual(claim.message_sid, "SM-XYZ")


class OutboundCommandDispatcherSameKeyReturnsDurableTest(HelperTestCase):
    def test_same_key_returns_durable_without_second_call(self) -> None:
        calls: list[dict[str, Any]] = []

        def _http_post(*, url: str, payload: bytes, headers: dict[str, str]):
            calls.append(
                {"url": url, "payload": payload, "headers": headers}
            )
            return _FakeResponse(
                status_code=200,
                body={"status": "sent", "message_sid": "SM-XYZ"},
            )

        helper = OutboundCommandDispatcher(
            session_factory=TestingSessionLocal,
            settings=_settings(isolated_enabled=True),
            master_keys=resolve_master_keys(
                current_env=MASTER_KEY, previous_env=None
            ),
            http_post=_http_post,
        )
        first = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        second = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))

        self.assertEqual(first.status, "sent")
        self.assertEqual(second.status, "sent")
        self.assertEqual(second.message_sid, "SM-XYZ")
        self.assertEqual(len(calls), 1)


class OutboundCommandDispatcherAmbiguousResultTest(HelperTestCase):
    def test_ambiguous_result_leaves_claim_in_progress(self) -> None:
        def _http_post(*, url: str, payload: bytes, headers: dict[str, str]):
            raise ConnectionError("simulated connection drop")

        helper = OutboundCommandDispatcher(
            session_factory=TestingSessionLocal,
            settings=_settings(isolated_enabled=True),
            master_keys=resolve_master_keys(
                current_env=MASTER_KEY, previous_env=None
            ),
            http_post=_http_post,
        )
        with self.assertRaises(OutboundCommandAmbiguous):
            helper.dispatch(outbox_row=_load_outbox(self.outbox_id))

        with TestingSessionLocal() as verify_session:
            claim = verify_session.execute(
                select(InstalacionTwilioComercioIdempotencia).where(
                    InstalacionTwilioComercioIdempotencia.instalacion_id
                    == self.instalacion_id,
                    InstalacionTwilioComercioIdempotencia.idempotency_key
                    == f"outbox-{self.outbox_id}",
                )
            ).scalar_one()
            self.assertEqual(claim.estado, "in_progress")
            self.assertIsNone(claim.http_status)

        def _second_post(*, url: str, payload: bytes, headers: dict[str, str]):
            return _FakeResponse(
                status_code=200,
                body={"status": "sent", "message_sid": "SM-LATE"},
            )

        helper_late = OutboundCommandDispatcher(
            session_factory=TestingSessionLocal,
            settings=_settings(isolated_enabled=True),
            master_keys=resolve_master_keys(
                current_env=MASTER_KEY, previous_env=None
            ),
            http_post=_second_post,
        )
        result = helper_late.dispatch(outbox_row=_load_outbox(self.outbox_id))
        self.assertEqual(result.status, "in_progress")
        self.assertEqual(result.http_status, 0)
        self.assertIsNone(result.message_sid)

    def test_network_failure_leaves_in_progress(self) -> None:
        """Network failure raises Ambiguous and leaves the claim
        ``in_progress``. A subsequent retry returns the durable
        ``in_progress`` state and never fires a second
        ``messages.create``."""

        def _http_post_fail(*, url: str, payload: bytes, headers: dict[str, str]):
            raise ConnectionError("simulated connection drop")

        helper = OutboundCommandDispatcher(
            session_factory=TestingSessionLocal,
            settings=_settings(isolated_enabled=True),
            master_keys=resolve_master_keys(
                current_env=MASTER_KEY, previous_env=None
            ),
            http_post=_http_post_fail,
        )
        with self.assertRaises(OutboundCommandAmbiguous):
            helper.dispatch(outbox_row=_load_outbox(self.outbox_id))

        with TestingSessionLocal() as verify_session:
            claim = verify_session.execute(
                select(InstalacionTwilioComercioIdempotencia).where(
                    InstalacionTwilioComercioIdempotencia.instalacion_id
                    == self.instalacion_id,
                    InstalacionTwilioComercioIdempotencia.idempotency_key
                    == f"outbox-{self.outbox_id}",
                )
            ).scalar_one()
            self.assertEqual(claim.estado, "in_progress")
            self.assertIsNone(claim.http_status)

        second_calls: list[dict[str, Any]] = []

        def _http_post_recovered(
            *, url: str, payload: bytes, headers: dict[str, str]
        ):
            second_calls.append(
                {"url": url, "payload": payload, "headers": headers}
            )
            return _FakeResponse(
                status_code=200,
                body={"status": "sent", "message_sid": "SM-RECOVERED"},
            )

        helper_late = OutboundCommandDispatcher(
            session_factory=TestingSessionLocal,
            settings=_settings(isolated_enabled=True),
            master_keys=resolve_master_keys(
                current_env=MASTER_KEY, previous_env=None
            ),
            http_post=_http_post_recovered,
        )
        result = helper_late.dispatch(outbox_row=_load_outbox(self.outbox_id))
        self.assertEqual(result.status, "in_progress")
        self.assertEqual(second_calls, [])


class OutboundCommandDispatcherHttpClassificationTest(HelperTestCase):
    """HTTP responses must map to the documented closed claim lifecycle.

    The classification is closed:

    * ``200`` + typed body — finalize the claim with that state;
    * ``400`` / ``401`` / ``403`` / ``404`` / ``409`` / ``422`` —
      finalize as ``terminal`` so the claim is never left
      ``in_progress`` because of a configuration drift;
    * ``429`` / ``5xx`` — finalize as ``retryable`` so the bounded
      CLI drives the bounded retry path without firing a second
      ``messages.create``;
    * network failure / malformed body on ``200`` — leave the claim
      ``in_progress`` and raise :class:`OutboundCommandAmbiguous`;
    * unknown ``4xx`` — leave the claim ``in_progress`` and raise
      :class:`OutboundCommandAmbiguous` so the bounded CLI finalizes
      the central outbox row as ``retryable``. Unknown ``4xx`` codes
      are never defaulted to ``retryable``.
    """

    def _build_helper(self, http_post):
        return OutboundCommandDispatcher(
            session_factory=TestingSessionLocal,
            settings=_settings(isolated_enabled=True),
            master_keys=resolve_master_keys(
                current_env=MASTER_KEY, previous_env=None
            ),
            http_post=http_post,
        )

    def _read_claim(self) -> InstalacionTwilioComercioIdempotencia:
        with TestingSessionLocal() as verify_session:
            return verify_session.execute(
                select(InstalacionTwilioComercioIdempotencia).where(
                    InstalacionTwilioComercioIdempotencia.instalacion_id
                    == self.instalacion_id,
                    InstalacionTwilioComercioIdempotencia.idempotency_key
                    == f"outbox-{self.outbox_id}",
                )
            ).scalar_one()

    def test_http_401_finalizes_as_terminal(self) -> None:
        def _post(*, url: str, payload: bytes, headers: dict[str, str]):
            return _FakeResponse(status_code=401, body=None)

        helper = self._build_helper(_post)
        result = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        self.assertEqual(result.status, "terminal")
        self.assertEqual(result.http_status, 401)
        self.assertEqual(result.code, "http_401")
        claim = self._read_claim()
        self.assertEqual(claim.estado, "terminal")
        self.assertEqual(claim.http_status, 401)

    def test_http_403_finalizes_as_terminal(self) -> None:
        def _post(*, url: str, payload: bytes, headers: dict[str, str]):
            return _FakeResponse(status_code=403, body=None)

        helper = self._build_helper(_post)
        result = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        self.assertEqual(result.status, "terminal")
        self.assertEqual(result.http_status, 403)
        self.assertEqual(result.code, "http_403")
        claim = self._read_claim()
        self.assertEqual(claim.estado, "terminal")

    def test_http_400_finalizes_as_terminal(self) -> None:
        def _post(*, url: str, payload: bytes, headers: dict[str, str]):
            return _FakeResponse(status_code=400, body=None)

        helper = self._build_helper(_post)
        result = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        self.assertEqual(result.status, "terminal")
        self.assertEqual(result.http_status, 400)
        self.assertEqual(result.code, "http_400_contract")
        claim = self._read_claim()
        self.assertEqual(claim.estado, "terminal")

    def test_http_429_finalizes_as_retryable(self) -> None:
        def _post(*, url: str, payload: bytes, headers: dict[str, str]):
            return _FakeResponse(status_code=429, body=None)

        helper = self._build_helper(_post)
        result = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        self.assertEqual(result.status, "retryable")
        self.assertEqual(result.http_status, 429)
        self.assertEqual(result.code, "http_429_rate_limited")
        claim = self._read_claim()
        self.assertEqual(claim.estado, "retryable")
        self.assertEqual(claim.http_status, 429)

    def test_http_500_finalizes_as_retryable(self) -> None:
        def _post(*, url: str, payload: bytes, headers: dict[str, str]):
            return _FakeResponse(status_code=500, body=None)

        helper = self._build_helper(_post)
        result = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        self.assertEqual(result.status, "retryable")
        self.assertEqual(result.http_status, 500)
        self.assertEqual(result.code, "http_500_provider")
        claim = self._read_claim()
        self.assertEqual(claim.estado, "retryable")

    def test_http_404_finalizes_as_terminal(self) -> None:
        """``404`` is in the closed terminal set."""

        def _post(*, url: str, payload: bytes, headers: dict[str, str]):
            return _FakeResponse(status_code=404, body=None)

        helper = self._build_helper(_post)
        result = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        self.assertEqual(result.status, "terminal")
        self.assertEqual(result.http_status, 404)
        self.assertEqual(result.code, "http_404")
        claim = self._read_claim()
        self.assertEqual(claim.estado, "terminal")
        self.assertEqual(claim.http_status, 404)

    def test_http_409_finalizes_as_terminal(self) -> None:
        """``409`` is in the closed terminal set."""

        def _post(*, url: str, payload: bytes, headers: dict[str, str]):
            return _FakeResponse(status_code=409, body=None)

        helper = self._build_helper(_post)
        result = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        self.assertEqual(result.status, "terminal")
        self.assertEqual(result.http_status, 409)
        self.assertEqual(result.code, "http_409")
        claim = self._read_claim()
        self.assertEqual(claim.estado, "terminal")

    def test_http_422_finalizes_as_terminal(self) -> None:
        """``422`` is in the closed terminal set."""

        def _post(*, url: str, payload: bytes, headers: dict[str, str]):
            return _FakeResponse(status_code=422, body=None)

        helper = self._build_helper(_post)
        result = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        self.assertEqual(result.status, "terminal")
        self.assertEqual(result.http_status, 422)
        self.assertEqual(result.code, "http_422")
        claim = self._read_claim()
        self.assertEqual(claim.estado, "terminal")

    def test_http_unknown_4xx_raises_ambiguous(self) -> None:
        """Unknown ``4xx`` codes raise Ambiguous and leave the claim
        ``in_progress``.

        The helper must NEVER default an unknown ``4xx`` code to
        ``retryable``: a silent misconfiguration cannot pollute the
        durable claim state.
        """

        def _post(*, url: str, payload: bytes, headers: dict[str, str]):
            return _FakeResponse(status_code=418, body=None)

        helper = self._build_helper(_post)
        with self.assertRaises(OutboundCommandAmbiguous):
            helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        claim = self._read_claim()
        self.assertEqual(claim.estado, "in_progress")
        self.assertIsNone(claim.http_status)

    def test_http_unknown_4xx_412_raises_ambiguous(self) -> None:
        """Another documented unknown ``4xx`` boundary (``412``)."""

        def _post(*, url: str, payload: bytes, headers: dict[str, str]):
            return _FakeResponse(status_code=412, body=None)

        helper = self._build_helper(_post)
        with self.assertRaises(OutboundCommandAmbiguous):
            helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        claim = self._read_claim()
        self.assertEqual(claim.estado, "in_progress")

    def test_http_timeout_leaves_in_progress(self) -> None:
        def _post(*, url: str, payload: bytes, headers: dict[str, str]):
            raise TimeoutError("simulated network timeout")

        helper = self._build_helper(_post)
        with self.assertRaises(OutboundCommandAmbiguous):
            helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        claim = self._read_claim()
        self.assertEqual(claim.estado, "in_progress")
        self.assertIsNone(claim.http_status)

    def test_http_invalid_body_leaves_in_progress(self) -> None:
        def _post(*, url: str, payload: bytes, headers: dict[str, str]):
            return _FakeResponse(
                status_code=200, text="not-a-json-body"
            )

        helper = self._build_helper(_post)
        with self.assertRaises(OutboundCommandAmbiguous):
            helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        claim = self._read_claim()
        self.assertEqual(claim.estado, "in_progress")
        self.assertIsNone(claim.http_status)

    def test_retry_after_timeout_uses_durable_claim_without_second_send(
        self,
    ) -> None:
        """After a timeout the claim is ``in_progress``.

        A subsequent retry with the same key must short-circuit to
        the durable state without firing a second ``messages.create``,
        so the bounded CLI can drive the bounded retry path.
        """

        def _post_timeout(*, url: str, payload: bytes, headers: dict[str, str]):
            raise TimeoutError("simulated network timeout")

        helper_timeout = self._build_helper(_post_timeout)
        with self.assertRaises(OutboundCommandAmbiguous):
            helper_timeout.dispatch(outbox_row=_load_outbox(self.outbox_id))

        calls: list[dict[str, Any]] = []

        def _post_recovered(*, url: str, payload: bytes, headers: dict[str, str]):
            calls.append(
                {"url": url, "payload": payload, "headers": headers}
            )
            return _FakeResponse(
                status_code=200,
                body={"status": "sent", "message_sid": "SM-RECOVERED"},
            )

        helper_recovered = self._build_helper(_post_recovered)
        result = helper_recovered.dispatch(
            outbox_row=_load_outbox(self.outbox_id)
        )
        self.assertEqual(result.status, "in_progress")
        self.assertEqual(len(calls), 0)


class OutboundCommandDispatcherConcurrentClaimTest(HelperTestCase):
    """Truly concurrent claim test.

    Two threads, two sessions, two transactions and a
    :class:`threading.Barrier` to force the race. The race winner
    commits the ``INSERT`` and runs the network call. The losing
    thread sees the constraint violation, recovers the durable state
    via a fresh session and returns the winner's typed result without
    firing a second ``messages.create``. The race is enforced by the
    ``threading.Barrier`` so neither thread can finish its claim
    before the other enters the critical section.

    The thread that wins the race returns the ``SM-WINNER`` SID it
    produced. The thread that loses the race returns the same SID it
    recovered from the durable row — never its own placeholder
    ``SM-LOSER``. Exactly one ``messages.create`` call fires.
    """

    def test_concurrent_claim_serialises_through_unique_index(self) -> None:
        canonical_sid = "SM-ONCE"
        first_calls = {"value": 0}
        first_calls_lock = threading.Lock()
        first_can_return = threading.Event()
        first_entered = threading.Event()

        def _http_post_first(
            *, url: str, payload: bytes, headers: dict[str, str]
        ):
            with first_calls_lock:
                first_calls["value"] += 1
            first_entered.set()
            first_can_return.wait(timeout=5.0)
            return _FakeResponse(
                status_code=200,
                body={"status": "sent", "message_sid": canonical_sid},
            )

        second_calls = {"value": 0}
        second_calls_lock = threading.Lock()

        def _http_post_second(
            *, url: str, payload: bytes, headers: dict[str, str]
        ):
            with second_calls_lock:
                second_calls["value"] += 1
            return _FakeResponse(
                status_code=200,
                body={"status": "sent", "message_sid": canonical_sid},
            )

        barrier = threading.Barrier(2)
        results: dict[str, OutboundCommandResult | None] = {}
        exceptions: dict[str, BaseException | None] = {}

        def _run(label: str, http_post) -> None:
            try:
                helper = OutboundCommandDispatcher(
                    session_factory=TestingSessionLocal,
                    settings=_settings(isolated_enabled=True),
                    master_keys=resolve_master_keys(
                        current_env=MASTER_KEY, previous_env=None
                    ),
                    http_post=http_post,
                )
                barrier.wait(timeout=5.0)
                results[label] = helper.dispatch(
                    outbox_row=_load_outbox(self.outbox_id)
                )
            except BaseException as exc:  # noqa: BLE001 - capture per-thread failure for the assertion
                exceptions[label] = exc

        first = threading.Thread(
            target=_run, args=("first", _http_post_first)
        )
        second = threading.Thread(
            target=_run, args=("second", _http_post_second)
        )
        first.start()
        second.start()
        first_entered.wait(timeout=5.0)
        first_can_return.set()
        first.join(timeout=10.0)
        second.join(timeout=10.0)

        self.assertNotIn("first", exceptions)
        self.assertNotIn("second", exceptions)
        self.assertEqual(first_calls["value"] + second_calls["value"], 1)
        first_result = results["first"]
        second_result = results["second"]
        assert first_result is not None
        assert second_result is not None

        all_sids = {first_result.message_sid, second_result.message_sid}
        all_statuses = {first_result.status, second_result.status}
        self.assertEqual(all_sids, {canonical_sid})
        self.assertEqual(all_statuses, {"sent"})


class CentralDispatcherFallsBackWhenNoInstallationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.suffix = _suffix()
        self.comercio_id = _seed_comercio(self.suffix)
        self.recepcion_id, _canal, _cliente = _seed_recepcion(self.comercio_id)
        self.outbox_id = _seed_outbox(self.recepcion_id)

    def tearDown(self) -> None:
        _cleanup(self.comercio_id)

    def test_flag_on_without_installation_falls_back_to_central(self) -> None:
        from backend.services.outbound_dispatch_types import (
            OutboundDispatchOutcome,
        )
        from backend.services.outbound_message_dispatcher import (
            OutboundDispatchConfig,
            OutboundMessageDispatcher,
        )

        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        claimed_row = MensajeProveedorSaliente(
            id=self.outbox_id,
            proveedor="twilio",
            recepcion_mensaje_proveedor_id=self.recepcion_id,
            destinatario_e164="+5491155556666",
            cuerpo="hola",
            sequence=0,
            estado=OutboundProviderMessageState.LEASED.value,
            identificador_proveedor=None,
            intentos=1,
            proximo_intento_en=None,
            token_lease="lease-token-1",
            lease_expira_en=None,
            categoria_ultimo_fallo=None,
            codigo_ultimo_fallo=None,
            estado_proveedor=None,
            estado_proveedor_en=None,
            fecha_creacion=datetime.now(tz=timezone.utc),
        )
        outbox_repo.claim_due.return_value = claimed_row
        outbox_repo.finalize_accepted.return_value = True

        messages_client = MagicMock(name="TwilioMessagesClient")
        messages_client.create.return_value = type(
            "Message", (), {"sid": "SM-ABC"}
        )()

        dispatcher = OutboundMessageDispatcher(
            session_factory=TestingSessionLocal,
            messages_client=messages_client,
            config=OutboundDispatchConfig(
                sender_e164="+5491100000000",
                status_callback_url=None,
                lease_seconds=30,
                initial_backoff_seconds=30,
                max_backoff_seconds=300,
                max_attempts=5,
            ),
            outbox_repo_factory=lambda _session: outbox_repo,
            settings=_settings(isolated_enabled=True),
        )

        result = dispatcher.dispatch()
        self.assertEqual(result.outcome, OutboundDispatchOutcome.SENT)
        self.assertEqual(messages_client.create.call_count, 1)


class CentralDispatcherRoutesThroughHelperTest(HelperTestCase):
    def test_flag_on_with_installation_routes_through_helper(self) -> None:
        from backend.services.outbound_dispatch_types import (
            OutboundDispatchOutcome,
        )
        from backend.services.outbound_message_dispatcher import (
            OutboundDispatchConfig,
            OutboundMessageDispatcher,
        )

        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        claimed_row = MensajeProveedorSaliente(
            id=self.outbox_id,
            proveedor="twilio",
            recepcion_mensaje_proveedor_id=self.recepcion_id,
            destinatario_e164="+5491155556666",
            cuerpo="hola",
            sequence=0,
            estado=OutboundProviderMessageState.LEASED.value,
            identificador_proveedor=None,
            intentos=1,
            proximo_intento_en=None,
            token_lease="lease-token-1",
            lease_expira_en=None,
            categoria_ultimo_fallo=None,
            codigo_ultimo_fallo=None,
            estado_proveedor=None,
            estado_proveedor_en=None,
            fecha_creacion=datetime.now(tz=timezone.utc),
        )
        outbox_repo.claim_due.return_value = claimed_row
        outbox_repo.finalize_accepted.return_value = True

        messages_client = MagicMock(name="TwilioMessagesClient")

        calls: list[dict[str, Any]] = []

        def _http_post(*, url: str, payload: bytes, headers: dict[str, str]):
            calls.append(
                {"url": url, "payload": payload, "headers": headers}
            )
            return _FakeResponse(
                status_code=200,
                body={"status": "sent", "message_sid": "SM-XYZ"},
            )

        def _helper_factory(session_factory):
            return OutboundCommandDispatcher(
                session_factory=session_factory,
                settings=_settings(isolated_enabled=True),
                master_keys=resolve_master_keys(
                    current_env=MASTER_KEY, previous_env=None
                ),
                http_post=_http_post,
            )

        dispatcher = OutboundMessageDispatcher(
            session_factory=TestingSessionLocal,
            messages_client=messages_client,
            config=OutboundDispatchConfig(
                sender_e164="+5491100000000",
                status_callback_url=None,
                lease_seconds=30,
                initial_backoff_seconds=30,
                max_backoff_seconds=300,
                max_attempts=5,
            ),
            outbox_repo_factory=lambda _session: outbox_repo,
            settings=_settings(isolated_enabled=True),
            isolated_dispatcher_factory=_helper_factory,
        )

        result = dispatcher.dispatch()
        self.assertEqual(result.outcome, OutboundDispatchOutcome.SENT)
        self.assertEqual(len(calls), 1)
        self.assertEqual(messages_client.create.call_count, 0)
        self.assertEqual(
            calls[0]["url"],
            "https://tc.example.test/internal/commands/send-message",
        )


class CentralDispatcherFlagOffTest(HelperTestCase):
    """When the flag is off the central dispatcher must not invoke the
    bounded helper and must fall back to the documented central Twilio
    path. The test exercises the real dispatcher flow without any
    helper factory so the central branch is the only path taken.
    """

    def test_flag_off_skips_helper_and_uses_central(self) -> None:
        from backend.services.outbound_dispatch_types import (
            OutboundDispatchOutcome,
        )
        from backend.services.outbound_message_dispatcher import (
            OutboundDispatchConfig,
            OutboundMessageDispatcher,
        )

        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        claimed_row = MensajeProveedorSaliente(
            id=self.outbox_id,
            proveedor="twilio",
            recepcion_mensaje_proveedor_id=self.recepcion_id,
            destinatario_e164="+5491155556666",
            cuerpo="hola",
            sequence=0,
            estado=OutboundProviderMessageState.LEASED.value,
            identificador_proveedor=None,
            intentos=1,
            proximo_intento_en=None,
            token_lease="lease-token-1",
            lease_expira_en=None,
            categoria_ultimo_fallo=None,
            codigo_ultimo_fallo=None,
            estado_proveedor=None,
            estado_proveedor_en=None,
            fecha_creacion=datetime.now(tz=timezone.utc),
        )
        outbox_repo.claim_due.return_value = claimed_row
        outbox_repo.finalize_accepted.return_value = True

        messages_client = MagicMock(name="TwilioMessagesClient")
        messages_client.create.return_value = type(
            "Message", (), {"sid": "SM-CENTRAL"}
        )()

        helper_calls: list[dict[str, Any]] = []

        def _http_post(*, url: str, payload: bytes, headers: dict[str, str]):
            helper_calls.append(
                {"url": url, "payload": payload, "headers": headers}
            )
            return _FakeResponse(
                status_code=200,
                body={"status": "sent", "message_sid": "SM-HELPER"},
            )

        dispatcher = OutboundMessageDispatcher(
            session_factory=TestingSessionLocal,
            messages_client=messages_client,
            config=OutboundDispatchConfig(
                sender_e164="+5491100000000",
                status_callback_url=None,
                lease_seconds=30,
                initial_backoff_seconds=30,
                max_backoff_seconds=300,
                max_attempts=5,
            ),
            outbox_repo_factory=lambda _session: outbox_repo,
            settings=_settings(isolated_enabled=False),
            isolated_dispatcher_factory=lambda factory: OutboundCommandDispatcher(
                session_factory=factory,
                settings=_settings(isolated_enabled=False),
                master_keys=resolve_master_keys(
                    current_env=MASTER_KEY, previous_env=None
                ),
                http_post=_http_post,
            ),
        )

        result = dispatcher.dispatch()
        self.assertEqual(result.outcome, OutboundDispatchOutcome.SENT)
        self.assertEqual(helper_calls, [])
        self.assertEqual(messages_client.create.call_count, 1)


class CentralDispatcherPerInstallationUrlTest(HelperTestCase):
    """Two installations must route through two different URLs.

    The dispatcher must use the per-installation
    ``tc_service_url`` stored on the row and never a global base URL.
    """

    def setUp(self) -> None:
        super().setUp()
        self.other_suffix = _suffix()
        self.other_comercio_id = _seed_comercio(self.other_suffix)
        (
            self.other_recepcion_id,
            _other_canal,
            _other_cliente,
        ) = _seed_recepcion(self.other_comercio_id)
        self.other_outbox_id = _seed_outbox(self.other_recepcion_id)
        self.other_instalacion_id = (
            "o" + self.other_suffix + ("a" * (23 - len(self.other_suffix)))
        )[:24]
        self.other_tc_service_url = "https://other.example.test"
        _seed_instalacion(
            comercio_id=self.other_comercio_id,
            instalacion_id=self.other_instalacion_id,
            plain_secret="other-secret-9876543210",
            tc_service_url=self.other_tc_service_url,
        )

    def tearDown(self) -> None:
        super().tearDown()
        _cleanup(self.other_comercio_id, self.other_instalacion_id)

    def test_dispatcher_routes_through_per_installation_url(self) -> None:
        from backend.services.outbound_dispatch_types import (
            OutboundDispatchOutcome,
        )
        from backend.services.outbound_message_dispatcher import (
            OutboundDispatchConfig,
            OutboundMessageDispatcher,
        )

        helper_calls: list[dict[str, Any]] = []

        def _http_post(*, url: str, payload: bytes, headers: dict[str, str]):
            helper_calls.append(
                {"url": url, "payload": payload, "headers": headers}
            )
            body = json.loads(payload.decode("utf-8"))
            instalacion_id = body["instalacion_id"]
            return _FakeResponse(
                status_code=200,
                body={
                    "status": "sent",
                    "message_sid": f"SM-{instalacion_id[-6:].upper()}",
                },
            )

        def _helper_factory(session_factory):
            return OutboundCommandDispatcher(
                session_factory=session_factory,
                settings=_settings(isolated_enabled=True),
                master_keys=resolve_master_keys(
                    current_env=MASTER_KEY, previous_env=None
                ),
                http_post=_http_post,
            )

        def _outbox_repo_factory(session):
            from backend.repositories.mensaje_proveedor_saliente_repository import (
                MensajeProveedorSalienteRepository,
            )

            return MensajeProveedorSalienteRepository(session)

        dispatcher = OutboundMessageDispatcher(
            session_factory=TestingSessionLocal,
            config=OutboundDispatchConfig(
                sender_e164="+5491100000000",
                status_callback_url=None,
                lease_seconds=30,
                initial_backoff_seconds=30,
                max_backoff_seconds=300,
                max_attempts=5,
            ),
            outbox_repo_factory=_outbox_repo_factory,
            settings=_settings(isolated_enabled=True),
            isolated_dispatcher_factory=_helper_factory,
        )

        first = dispatcher.dispatch()
        second = dispatcher.dispatch()
        self.assertEqual(first.outcome, OutboundDispatchOutcome.SENT)
        self.assertEqual(second.outcome, OutboundDispatchOutcome.SENT)
        self.assertEqual(len(helper_calls), 2)
        urls = {call["url"] for call in helper_calls}
        self.assertEqual(
            urls,
            {
                "https://tc.example.test/internal/commands/send-message",
                "https://other.example.test/internal/commands/send-message",
            },
        )


class OutboundCommandDispatcherRetryableFirstAttemptTest(HelperTestCase):
    """Mandatory scenario: first attempt is 429, second attempt is sent.

    The first dispatch must finalize the claim as ``retryable`` so
    the bounded CLI drives the documented bounded retry path. The
    second dispatch must atomically transition the row back to
    ``in_progress`` and perform a new HTTP call. The two real
    ``messages.create`` calls must fire — exactly one per attempt —
    and the claim must end in ``sent``.
    """

    def test_first_attempt_429_then_succeeded(self) -> None:
        from backend.services.outbound_command_dispatcher import (
            OutboundCommandDispatcher as _Dispatcher,
        )

        call_counter = {"value": 0}
        responses = [
            _FakeResponse(
                status_code=429,
                body={"status": "retryable", "code": "http_429_rate_limited"},
            ),
            _FakeResponse(
                status_code=200,
                body={"status": "sent", "message_sid": "SM-RECOVERED"},
            ),
        ]

        def _http_post(*, url: str, payload: bytes, headers: dict[str, str]):
            call_counter["value"] += 1
            return responses[call_counter["value"] - 1]

        helper = _Dispatcher(
            session_factory=TestingSessionLocal,
            settings=_settings(isolated_enabled=True),
            master_keys=resolve_master_keys(
                current_env=MASTER_KEY, previous_env=None
            ),
            http_post=_http_post,
        )

        first = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        self.assertEqual(first.status, "retryable")
        self.assertEqual(first.http_status, 429)
        self.assertEqual(first.code, "http_429_rate_limited")

        with TestingSessionLocal() as verify_session:
            claim = verify_session.execute(
                select(InstalacionTwilioComercioIdempotencia).where(
                    InstalacionTwilioComercioIdempotencia.instalacion_id
                    == self.instalacion_id,
                    InstalacionTwilioComercioIdempotencia.idempotency_key
                    == f"outbox-{self.outbox_id}",
                )
            ).scalar_one()
            self.assertEqual(claim.estado, "retryable")
            self.assertEqual(claim.http_status, 429)

        second = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        self.assertEqual(second.status, "sent")
        self.assertEqual(second.message_sid, "SM-RECOVERED")
        self.assertEqual(call_counter["value"], 2)

        with TestingSessionLocal() as verify_session:
            claim = verify_session.execute(
                select(InstalacionTwilioComercioIdempotencia).where(
                    InstalacionTwilioComercioIdempotencia.instalacion_id
                    == self.instalacion_id,
                    InstalacionTwilioComercioIdempotencia.idempotency_key
                    == f"outbox-{self.outbox_id}",
                )
            ).scalar_one()
            self.assertEqual(claim.estado, "sent")
            self.assertEqual(claim.message_sid, "SM-RECOVERED")
            self.assertEqual(claim.http_status, 200)
            self.assertIsNone(claim.codigo)

    def test_first_attempt_500_then_succeeded(self) -> None:
        from backend.services.outbound_command_dispatcher import (
            OutboundCommandDispatcher as _Dispatcher,
        )

        call_counter = {"value": 0}
        responses = [
            _FakeResponse(
                status_code=500,
                body={"status": "retryable", "code": "http_500_provider"},
            ),
            _FakeResponse(
                status_code=200,
                body={"status": "sent", "message_sid": "SM-OK-500"},
            ),
        ]

        def _http_post(*, url: str, payload: bytes, headers: dict[str, str]):
            call_counter["value"] += 1
            return responses[call_counter["value"] - 1]

        helper = _Dispatcher(
            session_factory=TestingSessionLocal,
            settings=_settings(isolated_enabled=True),
            master_keys=resolve_master_keys(
                current_env=MASTER_KEY, previous_env=None
            ),
            http_post=_http_post,
        )

        first = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        self.assertEqual(first.status, "retryable")
        self.assertEqual(first.http_status, 500)
        self.assertEqual(first.code, "http_500_provider")

        second = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        self.assertEqual(second.status, "sent")
        self.assertEqual(second.message_sid, "SM-OK-500")
        self.assertEqual(call_counter["value"], 2)

        with TestingSessionLocal() as verify_session:
            claim = verify_session.execute(
                select(InstalacionTwilioComercioIdempotencia).where(
                    InstalacionTwilioComercioIdempotencia.instalacion_id
                    == self.instalacion_id,
                    InstalacionTwilioComercioIdempotencia.idempotency_key
                    == f"outbox-{self.outbox_id}",
                )
            ).scalar_one()
            self.assertEqual(claim.estado, "sent")
            self.assertEqual(claim.message_sid, "SM-OK-500")

    def test_multiple_retryable_then_succeeded(self) -> None:
        """Multiple retryable attempts before the final success.

        The bounded CLI must drive the documented bounded retry path
        without ever firing a second ``messages.create`` per attempt.
        The claim must remain in ``retryable`` between attempts and
        transition to ``sent`` only on the final attempt.
        """
        from backend.services.outbound_command_dispatcher import (
            OutboundCommandDispatcher as _Dispatcher,
        )

        call_counter = {"value": 0}
        responses = [
            _FakeResponse(
                status_code=429,
                body={"status": "retryable", "code": "http_429_rate_limited"},
            ),
            _FakeResponse(
                status_code=503,
                body={"status": "retryable", "code": "http_503_provider"},
            ),
            _FakeResponse(
                status_code=500,
                body={"status": "retryable", "code": "http_500_provider"},
            ),
            _FakeResponse(
                status_code=200,
                body={"status": "sent", "message_sid": "SM-FINALLY"},
            ),
        ]

        def _http_post(*, url: str, payload: bytes, headers: dict[str, str]):
            call_counter["value"] += 1
            return responses[call_counter["value"] - 1]

        helper = _Dispatcher(
            session_factory=TestingSessionLocal,
            settings=_settings(isolated_enabled=True),
            master_keys=resolve_master_keys(
                current_env=MASTER_KEY, previous_env=None
            ),
            http_post=_http_post,
        )

        for _ in range(3):
            retry = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
            self.assertEqual(retry.status, "retryable")
            with TestingSessionLocal() as verify_session:
                claim = verify_session.execute(
                    select(InstalacionTwilioComercioIdempotencia).where(
                        InstalacionTwilioComercioIdempotencia.instalacion_id
                        == self.instalacion_id,
                        InstalacionTwilioComercioIdempotencia.idempotency_key
                        == f"outbox-{self.outbox_id}",
                    )
                ).scalar_one()
                self.assertEqual(claim.estado, "retryable")

        final = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        self.assertEqual(final.status, "sent")
        self.assertEqual(final.message_sid, "SM-FINALLY")
        self.assertEqual(call_counter["value"], 4)

        with TestingSessionLocal() as verify_session:
            claim = verify_session.execute(
                select(InstalacionTwilioComercioIdempotencia).where(
                    InstalacionTwilioComercioIdempotencia.instalacion_id
                    == self.instalacion_id,
                    InstalacionTwilioComercioIdempotencia.idempotency_key
                    == f"outbox-{self.outbox_id}",
                )
            ).scalar_one()
            self.assertEqual(claim.estado, "sent")
            self.assertEqual(claim.message_sid, "SM-FINALLY")


class OutboundCommandDispatcherSentDoesNotRefireTest(HelperTestCase):
    """Mandatory scenario: a ``sent`` claim never fires a second call.

    The first dispatch finalizes the claim as ``sent``. Every
    subsequent dispatch must short-circuit to the durable state
    without firing a second ``messages.create``.
    """

    def test_sent_claim_does_not_refire(self) -> None:
        from backend.services.outbound_command_dispatcher import (
            OutboundCommandDispatcher as _Dispatcher,
        )

        calls: list[dict[str, Any]] = []

        def _http_post(*, url: str, payload: bytes, headers: dict[str, str]):
            calls.append(
                {"url": url, "payload": payload, "headers": headers}
            )
            return _FakeResponse(
                status_code=200,
                body={"status": "sent", "message_sid": "SM-ONCE"},
            )

        helper = _Dispatcher(
            session_factory=TestingSessionLocal,
            settings=_settings(isolated_enabled=True),
            master_keys=resolve_master_keys(
                current_env=MASTER_KEY, previous_env=None
            ),
            http_post=_http_post,
        )

        first = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        self.assertEqual(first.status, "sent")
        self.assertEqual(first.message_sid, "SM-ONCE")

        for _ in range(3):
            result = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
            self.assertEqual(result.status, "sent")
            self.assertEqual(result.message_sid, "SM-ONCE")

        self.assertEqual(len(calls), 1)


class OutboundCommandDispatcherTerminalDoesNotRefireTest(HelperTestCase):
    """Mandatory scenario: a ``terminal`` claim never fires a second call.

    The first dispatch finalizes the claim as ``terminal``. Every
    subsequent dispatch must short-circuit to the durable state
    without firing a second ``messages.create``.
    """

    def test_terminal_claim_does_not_refire(self) -> None:
        from backend.services.outbound_command_dispatcher import (
            OutboundCommandDispatcher as _Dispatcher,
        )

        calls: list[dict[str, Any]] = []

        def _http_post(*, url: str, payload: bytes, headers: dict[str, str]):
            calls.append(
                {"url": url, "payload": payload, "headers": headers}
            )
            return _FakeResponse(status_code=401, body=None)

        helper = _Dispatcher(
            session_factory=TestingSessionLocal,
            settings=_settings(isolated_enabled=True),
            master_keys=resolve_master_keys(
                current_env=MASTER_KEY, previous_env=None
            ),
            http_post=_http_post,
        )

        first = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        self.assertEqual(first.status, "terminal")
        self.assertEqual(first.http_status, 401)

        with TestingSessionLocal() as verify_session:
            claim = verify_session.execute(
                select(InstalacionTwilioComercioIdempotencia).where(
                    InstalacionTwilioComercioIdempotencia.instalacion_id
                    == self.instalacion_id,
                    InstalacionTwilioComercioIdempotencia.idempotency_key
                    == f"outbox-{self.outbox_id}",
                )
            ).scalar_one()
            self.assertEqual(claim.estado, "terminal")

        for _ in range(3):
            result = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
            self.assertEqual(result.status, "terminal")
            self.assertEqual(result.http_status, 401)

        self.assertEqual(len(calls), 1)


class OutboundCommandDispatcherInProgressDoesNotRefireTest(HelperTestCase):
    """Mandatory scenario: an ``in_progress`` claim never fires a second call.

    The first dispatch leaves the claim in ``in_progress`` after a
    network timeout. Every subsequent dispatch must short-circuit to
    the durable state without firing a second ``messages.create``.
    """

    def test_in_progress_claim_does_not_refire(self) -> None:
        from backend.services.outbound_command_dispatcher import (
            OutboundCommandDispatcher as _Dispatcher,
        )

        call_counter = {"value": 0}
        recovered_calls: list[dict[str, Any]] = []

        def _http_post_timeout(
            *, url: str, payload: bytes, headers: dict[str, str]
        ):
            call_counter["value"] += 1
            raise TimeoutError("simulated network timeout")

        helper = _Dispatcher(
            session_factory=TestingSessionLocal,
            settings=_settings(isolated_enabled=True),
            master_keys=resolve_master_keys(
                current_env=MASTER_KEY, previous_env=None
            ),
            http_post=_http_post_timeout,
        )
        with self.assertRaises(OutboundCommandAmbiguous):
            helper.dispatch(outbox_row=_load_outbox(self.outbox_id))

        with TestingSessionLocal() as verify_session:
            claim = verify_session.execute(
                select(InstalacionTwilioComercioIdempotencia).where(
                    InstalacionTwilioComercioIdempotencia.instalacion_id
                    == self.instalacion_id,
                    InstalacionTwilioComercioIdempotencia.idempotency_key
                    == f"outbox-{self.outbox_id}",
                )
            ).scalar_one()
            self.assertEqual(claim.estado, "in_progress")

        def _http_post_recovered(
            *, url: str, payload: bytes, headers: dict[str, str]
        ):
            recovered_calls.append(
                {"url": url, "payload": payload, "headers": headers}
            )
            return _FakeResponse(
                status_code=200,
                body={"status": "sent", "message_sid": "SM-RECOVERED"},
            )

        helper_recovered = _Dispatcher(
            session_factory=TestingSessionLocal,
            settings=_settings(isolated_enabled=True),
            master_keys=resolve_master_keys(
                current_env=MASTER_KEY, previous_env=None
            ),
            http_post=_http_post_recovered,
        )

        for _ in range(3):
            result = helper_recovered.dispatch(
                outbox_row=_load_outbox(self.outbox_id)
            )
            self.assertEqual(result.status, "in_progress")
            self.assertIsNone(result.message_sid)

        self.assertEqual(call_counter["value"], 1)
        self.assertEqual(recovered_calls, [])


class OutboundCommandDispatcherConcurrentRetryableClaimTest(HelperTestCase):
    """Mandatory scenario: two concurrent callers on a ``retryable`` claim.

    Two threads, two sessions, two transactions and a
    :class:`threading.Barrier` to force the race. Both threads see the
    same ``retryable`` claim. The atomic
    ``UPDATE ... WHERE estado = 'retryable'`` predicate serialises
    them: only one wins and runs the new HTTP call; the other returns
    the durable state without calling T-C. Exactly one
    ``messages.create`` call fires for the second attempt.
    """

    def test_concurrent_retryable_claim_serialises_through_predicate(
        self,
    ) -> None:
        from backend.services.outbound_command_dispatcher import (
            OutboundCommandDispatcher as _Dispatcher,
        )

        # Seed a retryable claim directly so both threads start from
        # the same documented state.
        with TestingSessionLocal() as session, session.begin():
            seeded = InstalacionTwilioComercioIdempotencia(
                instalacion_id=self.instalacion_id,
                idempotency_key=f"outbox-{self.outbox_id}",
                estado="retryable",
                message_sid=None,
                codigo="http_429_rate_limited",
                http_status=429,
            )
            session.add(seeded)

        canonical_sid = "SM-ONCE-RETRYABLE"
        first_calls = {"value": 0}
        first_calls_lock = threading.Lock()
        first_entered = threading.Event()
        first_can_return = threading.Event()

        def _http_post_first(
            *, url: str, payload: bytes, headers: dict[str, str]
        ):
            with first_calls_lock:
                first_calls["value"] += 1
            first_entered.set()
            first_can_return.wait(timeout=5.0)
            return _FakeResponse(
                status_code=200,
                body={"status": "sent", "message_sid": canonical_sid},
            )

        second_calls = {"value": 0}
        second_calls_lock = threading.Lock()

        def _http_post_second(
            *, url: str, payload: bytes, headers: dict[str, str]
        ):
            with second_calls_lock:
                second_calls["value"] += 1
            return _FakeResponse(
                status_code=200,
                body={"status": "sent", "message_sid": canonical_sid},
            )

        barrier = threading.Barrier(2)
        results: dict[str, OutboundCommandResult | None] = {}
        exceptions: dict[str, BaseException | None] = {}

        def _run(label: str, http_post) -> None:
            try:
                helper = _Dispatcher(
                    session_factory=TestingSessionLocal,
                    settings=_settings(isolated_enabled=True),
                    master_keys=resolve_master_keys(
                        current_env=MASTER_KEY, previous_env=None
                    ),
                    http_post=http_post,
                )
                barrier.wait(timeout=5.0)
                results[label] = helper.dispatch(
                    outbox_row=_load_outbox(self.outbox_id)
                )
            except BaseException as exc:  # noqa: BLE001
                exceptions[label] = exc

        first = threading.Thread(
            target=_run, args=("first", _http_post_first)
        )
        second = threading.Thread(
            target=_run, args=("second", _http_post_second)
        )
        first.start()
        second.start()
        first_entered.wait(timeout=5.0)
        first_can_return.set()
        first.join(timeout=10.0)
        second.join(timeout=10.0)

        self.assertNotIn("first", exceptions)
        self.assertNotIn("second", exceptions)
        # Exactly one real HTTP call — the loser must short-circuit
        # without firing a second ``messages.create``.
        self.assertEqual(first_calls["value"] + second_calls["value"], 1)

        first_result = results["first"]
        second_result = results["second"]
        assert first_result is not None
        assert second_result is not None

        # The winner finalizes the row to ``sent`` and reports the
        # canonical SID; the loser reports the durable state.
        seen_sids = {
            first_result.message_sid,
            second_result.message_sid,
        }
        seen_statuses = {first_result.status, second_result.status}
        self.assertIn(canonical_sid, seen_sids)
        self.assertTrue(seen_statuses.issubset({"sent", "in_progress"}))
        self.assertIn("sent", seen_statuses)

        # The durable claim row is ``sent`` once the winner
        # finalizes.
        with TestingSessionLocal() as verify_session:
            claim = verify_session.execute(
                select(InstalacionTwilioComercioIdempotencia).where(
                    InstalacionTwilioComercioIdempotencia.instalacion_id
                    == self.instalacion_id,
                    InstalacionTwilioComercioIdempotencia.idempotency_key
                    == f"outbox-{self.outbox_id}",
                )
            ).scalar_one()
            self.assertEqual(claim.estado, "sent")
            self.assertEqual(claim.message_sid, canonical_sid)


class OutboundCommandDispatcherCentralDispatcherRetryableFlowTest(
    HelperTestCase
):
    """Mandatory scenario: the retryable → sent flow drives through the
    real ``OutboundMessageDispatcher``.

    The flow must be exercised through the real central dispatcher
    so the bounded CLI / outbox lease / finalize path is covered
    end-to-end. Two real ``dispatch`` calls must fire two real
    HTTP calls; the outbox row must transition from ``leased`` /
    ``retryable`` to ``accepted``; the durable claim row must
    transition from ``retryable`` to ``sent``.
    """

    def test_retryable_then_sent_via_real_central_dispatcher(
        self,
    ) -> None:
        from backend.services.outbound_dispatch_types import (
            OutboundAttemptOutcome,
            OutboundDispatchOutcome,
        )
        from backend.services.outbound_message_dispatcher import (
            OutboundDispatchConfig,
            OutboundMessageDispatcher,
        )

        # Seed an outbox row in ``PENDING`` state so the real
        # ``MensajeProveedorSalienteRepository.claim_due`` picks it
        # up on the first dispatch.
        with TestingSessionLocal() as session, session.begin():
            session.execute(
                delete(MensajeProveedorSaliente).where(
                    MensajeProveedorSaliente.id == self.outbox_id
                )
            )
            seeded = MensajeProveedorSaliente(
                id=self.outbox_id,
                proveedor="twilio",
                recepcion_mensaje_proveedor_id=self.recepcion_id,
                destinatario_e164="+5491155556666",
                cuerpo="hola",
                sequence=0,
                estado=OutboundProviderMessageState.PENDING.value,
                identificador_proveedor=None,
                intentos=1,
                proximo_intento_en=None,
                token_lease=None,
                lease_expira_en=None,
                categoria_ultimo_fallo=None,
                codigo_ultimo_fallo=None,
                estado_proveedor=None,
                estado_proveedor_en=None,
                fecha_creacion=datetime.now(tz=timezone.utc),
            )
            session.add(seeded)

        call_counter = {"value": 0}
        responses = [
            _FakeResponse(
                status_code=429,
                body={"status": "retryable", "code": "http_429_rate_limited"},
            ),
            _FakeResponse(
                status_code=200,
                body={"status": "sent", "message_sid": "SM-CENTRAL-RECOVERED"},
            ),
        ]

        def _http_post(*, url: str, payload: bytes, headers: dict[str, str]):
            call_counter["value"] += 1
            return responses[call_counter["value"] - 1]

        def _helper_factory(session_factory):
            return OutboundCommandDispatcher(
                session_factory=session_factory,
                settings=_settings(isolated_enabled=True),
                master_keys=resolve_master_keys(
                    current_env=MASTER_KEY, previous_env=None
                ),
                http_post=_http_post,
            )

        dispatcher = OutboundMessageDispatcher(
            session_factory=TestingSessionLocal,
            messages_client=MagicMock(name="TwilioMessagesClient"),
            config=OutboundDispatchConfig(
                sender_e164="+5491100000000",
                status_callback_url=None,
                lease_seconds=30,
                initial_backoff_seconds=30,
                max_backoff_seconds=300,
                max_attempts=5,
            ),
            settings=_settings(isolated_enabled=True),
            isolated_dispatcher_factory=_helper_factory,
        )

        first = dispatcher.dispatch()
        self.assertEqual(first.outcome, OutboundDispatchOutcome.RETRY_SCHEDULED)
        self.assertEqual(call_counter["value"], 1)

        with TestingSessionLocal() as verify_session:
            claim = verify_session.execute(
                select(InstalacionTwilioComercioIdempotencia).where(
                    InstalacionTwilioComercioIdempotencia.instalacion_id
                    == self.instalacion_id,
                    InstalacionTwilioComercioIdempotencia.idempotency_key
                    == f"outbox-{self.outbox_id}",
                )
            ).scalar_one()
            self.assertEqual(claim.estado, "retryable")
            self.assertEqual(claim.http_status, 429)

        # Force the outbox row to be ``due`` again so the second
        # dispatch claims it through the real repository.
        with TestingSessionLocal() as session, session.begin():
            row = session.get(MensajeProveedorSaliente, self.outbox_id)
            assert row is not None
            row.proximo_intento_en = None
            row.token_lease = None
            row.lease_expira_en = None

        second = dispatcher.dispatch()
        self.assertEqual(second.outcome, OutboundDispatchOutcome.SENT)
        self.assertEqual(second.identificador_proveedor, "SM-CENTRAL-RECOVERED")
        self.assertEqual(call_counter["value"], 2)

        with TestingSessionLocal() as verify_session:
            claim = verify_session.execute(
                select(InstalacionTwilioComercioIdempotencia).where(
                    InstalacionTwilioComercioIdempotencia.instalacion_id
                    == self.instalacion_id,
                    InstalacionTwilioComercioIdempotencia.idempotency_key
                    == f"outbox-{self.outbox_id}",
                )
            ).scalar_one()
            self.assertEqual(claim.estado, "sent")
            self.assertEqual(claim.message_sid, "SM-CENTRAL-RECOVERED")

            outbox_row = verify_session.get(
                MensajeProveedorSaliente, self.outbox_id
            )
            assert outbox_row is not None
            self.assertEqual(
                outbox_row.identificador_proveedor, "SM-CENTRAL-RECOVERED"
            )
            self.assertEqual(
                outbox_row.estado, OutboundProviderMessageState.ACCEPTED.value
            )


class CentralDispatcherCapturesOutboundCommandAmbiguousTest(HelperTestCase):
    """Bloqueante 1: the central ``OutboundMessageDispatcher`` must
    capture :class:`OutboundCommandAmbiguous` and finalize the central
    outbox row as ``retryable`` while the durable claim row stays
    ``in_progress``. The dispatcher must NEVER fall back to the
    documented central Twilio ``messages.create`` path on an
    ambiguous result: the bounded CLI / outbox lease stays the
    single owner of the row and the next dispatch drives the
    documented bounded retry path.

    The test exercises the real central dispatcher flow end-to-end
    with an injected helper that raises ``OutboundCommandAmbiguous``
    on the first attempt and recovers with a typed ``sent``
    response on the second attempt. The integration asserts:

    * the timeout/ambiguous helper result finalizes the central
      outbox row as ``retryable``;
    * the durable ``instalaciones_twilio_comercio_idempotencia``
      claim row stays in ``in_progress`` after the ambiguous
      attempt;
    * zero ``messages.create`` calls fire against the documented
      central Twilio path during the ambiguous attempt;
    * the next attempt short-circuits to the durable
      ``in_progress`` state without firing any new HTTP call
      against either the T-C adapter or the central Twilio path;
    * the duplicate-send protection is preserved across the
      ambiguous result.
    """

    def test_central_dispatcher_captures_ambiguous_and_finalizes_retryable(
        self,
    ) -> None:
        from backend.services.outbound_command_dispatcher import (
            OutboundCommandDispatcher as _Helper,
        )
        from backend.services.outbound_dispatch_types import (
            OutboundDispatchOutcome,
        )
        from backend.services.outbound_message_dispatcher import (
            OutboundDispatchConfig,
            OutboundMessageDispatcher,
        )

        ambiguous_calls: list[dict[str, Any]] = []

        def _http_post_ambiguous(
            *, url: str, payload: bytes, headers: dict[str, str]
        ):
            ambiguous_calls.append(
                {"url": url, "payload": payload, "headers": headers}
            )
            raise TimeoutError("simulated T-C adapter timeout")

        def _helper_factory(session_factory):
            return _Helper(
                session_factory=session_factory,
                settings=_settings(isolated_enabled=True),
                master_keys=resolve_master_keys(
                    current_env=MASTER_KEY, previous_env=None
                ),
                http_post=_http_post_ambiguous,
            )

        messages_client = MagicMock(name="TwilioMessagesClient")

        dispatcher = OutboundMessageDispatcher(
            session_factory=TestingSessionLocal,
            messages_client=messages_client,
            config=OutboundDispatchConfig(
                sender_e164="+5491100000000",
                status_callback_url=None,
                lease_seconds=30,
                initial_backoff_seconds=30,
                max_backoff_seconds=300,
                max_attempts=5,
            ),
            settings=_settings(isolated_enabled=True),
            isolated_dispatcher_factory=_helper_factory,
        )

        result = dispatcher.dispatch()
        self.assertEqual(result.outcome, OutboundDispatchOutcome.RETRY_SCHEDULED)
        self.assertEqual(result.codigo, "ambiguous_tc_response")
        self.assertEqual(len(ambiguous_calls), 1)
        self.assertEqual(messages_client.create.call_count, 0)

        with TestingSessionLocal() as verify_session:
            claim = verify_session.execute(
                select(InstalacionTwilioComercioIdempotencia).where(
                    InstalacionTwilioComercioIdempotencia.instalacion_id
                    == self.instalacion_id,
                    InstalacionTwilioComercioIdempotencia.idempotency_key
                    == f"outbox-{self.outbox_id}",
                )
            ).scalar_one()
            self.assertEqual(claim.estado, "in_progress")
            self.assertIsNone(claim.http_status)

            outbox_row = verify_session.get(
                MensajeProveedorSaliente, self.outbox_id
            )
            assert outbox_row is not None
            self.assertEqual(
                outbox_row.estado, OutboundProviderMessageState.RETRYABLE.value
            )
            self.assertEqual(outbox_row.codigo_ultimo_fallo, "ambiguous_tc_response")
            self.assertIsNone(outbox_row.identificador_proveedor)

        with TestingSessionLocal() as session, session.begin():
            row = session.get(MensajeProveedorSaliente, self.outbox_id)
            assert row is not None
            row.proximo_intento_en = None
            row.token_lease = None
            row.lease_expira_en = None

        second_calls: list[dict[str, Any]] = []

        def _http_post_recovered(
            *, url: str, payload: bytes, headers: dict[str, str]
        ):
            second_calls.append(
                {"url": url, "payload": payload, "headers": headers}
            )
            return _FakeResponse(
                status_code=200,
                body={"status": "sent", "message_sid": "SM-LATE"},
            )

        def _helper_factory_recovered(session_factory):
            return _Helper(
                session_factory=session_factory,
                settings=_settings(isolated_enabled=True),
                master_keys=resolve_master_keys(
                    current_env=MASTER_KEY, previous_env=None
                ),
                http_post=_http_post_recovered,
            )

        dispatcher_recovered = OutboundMessageDispatcher(
            session_factory=TestingSessionLocal,
            messages_client=messages_client,
            config=OutboundDispatchConfig(
                sender_e164="+5491100000000",
                status_callback_url=None,
                lease_seconds=30,
                initial_backoff_seconds=30,
                max_backoff_seconds=300,
                max_attempts=5,
            ),
            settings=_settings(isolated_enabled=True),
            isolated_dispatcher_factory=_helper_factory_recovered,
        )

        second = dispatcher_recovered.dispatch()
        self.assertEqual(second.outcome, OutboundDispatchOutcome.RETRY_SCHEDULED)
        self.assertEqual(second_calls, [])
        self.assertEqual(messages_client.create.call_count, 0)

        with TestingSessionLocal() as verify_session:
            claim = verify_session.execute(
                select(InstalacionTwilioComercioIdempotencia).where(
                    InstalacionTwilioComercioIdempotencia.instalacion_id
                    == self.instalacion_id,
                    InstalacionTwilioComercioIdempotencia.idempotency_key
                    == f"outbox-{self.outbox_id}",
                )
            ).scalar_one()
            self.assertEqual(claim.estado, "in_progress")
            self.assertIsNone(claim.message_sid)
            self.assertIsNone(claim.http_status)

            outbox_row = verify_session.get(
                MensajeProveedorSaliente, self.outbox_id
            )
            assert outbox_row is not None
            self.assertEqual(
                outbox_row.estado, OutboundProviderMessageState.RETRYABLE.value
            )
            self.assertIsNone(outbox_row.identificador_proveedor)


class OutboundCommandDispatcherResponseContractTest(HelperTestCase):
    """Bloqueante 3: ``CanonicalOutboundResponse`` is a closed
    contract.

    The bounded helper validates the typed response against the
    closed contract:

    * ``status`` MUST be one of ``{"sent", "retryable", "terminal"}``;
    * ``status == "sent"`` MUST carry a non-empty ``message_sid``;
    * any extra field is rejected by the ``extra="forbid"`` policy.

    An invalid response is treated as an ambiguous result: the
    helper raises :class:`OutboundCommandAmbiguous` so the bounded
    CLI finalizes the central outbox row as ``retryable`` while the
    durable claim row stays ``in_progress`` for recovery. The helper
    NEVER fires a second ``messages.create`` call after an invalid
    response.
    """

    def _build_helper(self, http_post):
        return OutboundCommandDispatcher(
            session_factory=TestingSessionLocal,
            settings=_settings(isolated_enabled=True),
            master_keys=resolve_master_keys(
                current_env=MASTER_KEY, previous_env=None
            ),
            http_post=http_post,
        )

    def _read_claim(self) -> InstalacionTwilioComercioIdempotencia:
        with TestingSessionLocal() as verify_session:
            return verify_session.execute(
                select(InstalacionTwilioComercioIdempotencia).where(
                    InstalacionTwilioComercioIdempotencia.instalacion_id
                    == self.instalacion_id,
                    InstalacionTwilioComercioIdempotencia.idempotency_key
                    == f"outbox-{self.outbox_id}",
                )
            ).scalar_one()

    def test_response_unknown_status_raises_ambiguous(self) -> None:
        """An unknown ``status`` value raises Ambiguous and keeps the
        claim ``in_progress``."""

        def _post(*, url: str, payload: bytes, headers: dict[str, str]):
            return _FakeResponse(
                status_code=200,
                body={"status": "ok-but-not-typed", "message_sid": "SM-XYZ"},
            )

        helper = self._build_helper(_post)
        with self.assertRaises(OutboundCommandAmbiguous):
            helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        claim = self._read_claim()
        self.assertEqual(claim.estado, "in_progress")
        self.assertIsNone(claim.message_sid)

    def test_response_sent_without_message_sid_raises_ambiguous(self) -> None:
        """A ``sent`` response without a non-empty ``message_sid``
        raises Ambiguous and keeps the claim ``in_progress``."""

        def _post(*, url: str, payload: bytes, headers: dict[str, str]):
            return _FakeResponse(
                status_code=200,
                body={"status": "sent", "message_sid": ""},
            )

        helper = self._build_helper(_post)
        with self.assertRaises(OutboundCommandAmbiguous):
            helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        claim = self._read_claim()
        self.assertEqual(claim.estado, "in_progress")

    def test_response_sent_without_message_sid_field_raises_ambiguous(
        self,
    ) -> None:
        """A ``sent`` response missing the ``message_sid`` field
        altogether also raises Ambiguous."""

        def _post(*, url: str, payload: bytes, headers: dict[str, str]):
            return _FakeResponse(
                status_code=200,
                body={"status": "sent"},
            )

        helper = self._build_helper(_post)
        with self.assertRaises(OutboundCommandAmbiguous):
            helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        claim = self._read_claim()
        self.assertEqual(claim.estado, "in_progress")

    def test_response_extra_field_raises_ambiguous(self) -> None:
        """An extra field is rejected by the closed contract and
        treated as ambiguous."""

        def _post(*, url: str, payload: bytes, headers: dict[str, str]):
            return _FakeResponse(
                status_code=200,
                body={
                    "status": "sent",
                    "message_sid": "SM-XYZ",
                    "sensitive": "leak",
                },
            )

        helper = self._build_helper(_post)
        with self.assertRaises(OutboundCommandAmbiguous):
            helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        claim = self._read_claim()
        self.assertEqual(claim.estado, "in_progress")

    def test_response_valid_sent_finalizes_as_sent(self) -> None:
        """A valid ``sent`` response with a non-empty ``message_sid``
        finalizes the claim as ``sent``."""

        def _post(*, url: str, payload: bytes, headers: dict[str, str]):
            return _FakeResponse(
                status_code=200,
                body={"status": "sent", "message_sid": "SM-VALID"},
            )

        helper = self._build_helper(_post)
        result = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        self.assertEqual(result.status, "sent")
        self.assertEqual(result.message_sid, "SM-VALID")
        claim = self._read_claim()
        self.assertEqual(claim.estado, "sent")
        self.assertEqual(claim.message_sid, "SM-VALID")

    def test_response_valid_retryable_finalizes_as_retryable(self) -> None:
        """A valid ``retryable`` response finalizes the claim as
        ``retryable``."""

        def _post(*, url: str, payload: bytes, headers: dict[str, str]):
            return _FakeResponse(
                status_code=200,
                body={"status": "retryable", "code": "queue_full"},
            )

        helper = self._build_helper(_post)
        result = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        self.assertEqual(result.status, "retryable")
        self.assertEqual(result.code, "queue_full")
        self.assertIsNone(result.message_sid)
        claim = self._read_claim()
        self.assertEqual(claim.estado, "retryable")
        self.assertIsNone(claim.message_sid)

    def test_response_valid_terminal_finalizes_as_terminal(self) -> None:
        """A valid ``terminal`` response finalizes the claim as
        ``terminal``."""

        def _post(*, url: str, payload: bytes, headers: dict[str, str]):
            return _FakeResponse(
                status_code=200,
                body={"status": "terminal", "code": "blocked_recipient"},
            )

        helper = self._build_helper(_post)
        result = helper.dispatch(outbox_row=_load_outbox(self.outbox_id))
        self.assertEqual(result.status, "terminal")
        self.assertEqual(result.code, "blocked_recipient")
        self.assertIsNone(result.message_sid)
        claim = self._read_claim()
        self.assertEqual(claim.estado, "terminal")
        self.assertIsNone(claim.message_sid)


if __name__ == "__main__":
    unittest.main(verbosity=2)