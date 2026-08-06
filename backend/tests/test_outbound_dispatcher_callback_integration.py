"""Phase-5.6 real PostgreSQL integration tests.

These tests exercise the Phase-5.6 dispatcher and callback service
against the live ``supernova_test`` PostgreSQL database. Mocks cannot
substitute for the proofs the review relied on:

* the ``UPDATE ... WHERE id = (SELECT id ... LIMIT 1 FOR UPDATE
  SKIP LOCKED) RETURNING *`` claim contract that claims exactly one
  row per execution and leaves every other due row eligible;
* the durability of the lease across a session close so the network
  call runs against a committed lease;
* the isolation of the narrow claim / finalize transactions so the
  Twilio network call happens outside any open SQLAlchemy session;
* the expired-lease recovery path that re-claims a ``leased`` row
  whose ``lease_expira_en`` is in the past;
* the durability of a callback ``accepted -> delivered`` transition
  when the service commits in its own narrow transaction;
* the safe no-op behaviour for a validly signed callback that
  carries a ``MessageStatus`` the callback service does not
  recognise.

The tests seed exactly one parent ``recepciones_mensajes_proveedor``
row plus the outbox rows they need and remove every row they create
so unrelated rows are never modified.
"""
from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as SqlSession
from sqlalchemy.orm import sessionmaker
from twilio.request_validator import RequestValidator

from backend.dependencies import get_session
from backend.models.mensaje_proveedor_saliente import (
    MensajeProveedorSaliente,
    OutboundProviderMessageState,
)
from backend.models.recepcion_mensaje_proveedor import (
    RecepcionMensajeProveedor,
)
from backend.repositories.mensaje_proveedor_saliente_repository import (
    MensajeProveedorSalienteRepository,
)
from backend.services.outbound_dispatch_types import (
    OutboundDispatchOutcome,
)
from backend.services.outbound_message_dispatcher import (
    OutboundDispatchConfig,
    OutboundMessageDispatcher,
)
from backend.services.twilio_delivery_callback_service import (
    TwilioDeliveryCallbackService,
)
from backend.services.twilio_outbound_adapter import (
    TwilioMessagesClient,
)

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _delete_outbox_by_recepcion(recepcion_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(MensajeProveedorSaliente).where(
                MensajeProveedorSaliente.recepcion_mensaje_proveedor_id
                == recepcion_id
            )
        )


def _delete_recepcion(recepcion_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        _delete_outbox_by_recepcion(recepcion_id)
        session.execute(
            delete(RecepcionMensajeProveedor).where(
                RecepcionMensajeProveedor.id == recepcion_id
            )
        )


def _seed_recepcion(suffix: str) -> int:
    """Insert a minimal ``RecepcionMensajeProveedor`` row.

    The integration tests do not need the full inbound
    commerce/channel/client graph: they exercise the outbox table
    only, so a parent row with synthetic but unique FK ids is
    enough. ``canal_id``, ``cliente_id`` and ``comercio_id`` are
    resolved against the seeded catalogue so the FK constraints
    are satisfied.
    """
    from backend.models.canal_whatsapp import CanalWhatsapp
    from backend.models.cliente import Cliente
    from backend.models.comercio import Comercio

    with TestingSessionLocal() as session, session.begin():
        canal = session.execute(select(CanalWhatsapp).limit(1)).scalar_one()
        cliente = session.execute(select(Cliente).limit(1)).scalar_one()
        comercio = session.execute(select(Comercio).limit(1)).scalar_one()
        recepcion = RecepcionMensajeProveedor(
            proveedor="twilio",
            identificador_recepcion=f"itest-{suffix}",
            canal_id=int(canal.id),
            cliente_id=int(cliente.id),
            comercio_id=int(comercio.id),
        )
        session.add(recepcion)
        session.flush()
        return int(recepcion.id)


def _seed_outbox_row(
    *,
    recepcion_id: int,
    sequence: int,
    estado: str,
    destinatario_e164: str = "+5491155556666",
    cuerpo: str = "hola",
    intentos: int = 0,
    proximo_intento_en: datetime | None = None,
    token_lease: str | None = None,
    lease_expira_en: datetime | None = None,
    identificador_proveedor: str | None = None,
    estado_proveedor: str | None = None,
    estado_proveedor_en: datetime | None = None,
) -> int:
    """Insert one outbox row and return its primary key id."""
    with TestingSessionLocal() as session, session.begin():
        row = MensajeProveedorSaliente(
            proveedor="twilio",
            recepcion_mensaje_proveedor_id=recepcion_id,
            destinatario_e164=destinatario_e164,
            cuerpo=cuerpo,
            sequence=sequence,
            estado=estado,
            intentos=intentos,
            proximo_intento_en=proximo_intento_en,
            token_lease=token_lease,
            lease_expira_en=lease_expira_en,
            identificador_proveedor=identificador_proveedor,
            estado_proveedor=estado_proveedor,
            estado_proveedor_en=estado_proveedor_en,
        )
        session.add(row)
        session.flush()
        return int(row.id)


def _fetch_outbox_row(outbox_id: int) -> MensajeProveedorSaliente:
    with TestingSessionLocal() as session:
        row = session.get(MensajeProveedorSaliente, outbox_id)
        if row is None:
            raise AssertionError(f"row {outbox_id} not found")
        return row


def _require(row: MensajeProveedorSaliente | None) -> MensajeProveedorSaliente:
    if row is None:
        raise AssertionError("expected a persisted row")
    return row


def _count_outbox_estado(
    recepcion_id: int, estado: str
) -> int:
    with TestingSessionLocal() as session:
        return len(
            list(
                session.execute(
                    select(MensajeProveedorSaliente).where(
                        MensajeProveedorSaliente.recepcion_mensaje_proveedor_id
                        == recepcion_id,
                        MensajeProveedorSaliente.estado == estado,
                    )
                ).scalars()
            )
        )


def _count_due(recepcion_id: int, now: datetime) -> int:
    """Count rows that ``claim_due`` would consider eligible from a
    fresh session."""
    from sqlalchemy import and_, or_

    pending_path = and_(
        MensajeProveedorSaliente.recepcion_mensaje_proveedor_id
        == recepcion_id,
        MensajeProveedorSaliente.estado.in_(
            [
                OutboundProviderMessageState.PENDING.value,
                OutboundProviderMessageState.RETRYABLE.value,
            ]
        ),
        MensajeProveedorSaliente.token_lease.is_(None),
        or_(
            MensajeProveedorSaliente.proximo_intento_en.is_(None),
            MensajeProveedorSaliente.proximo_intento_en <= now,
        ),
    )
    expired_path = and_(
        MensajeProveedorSaliente.recepcion_mensaje_proveedor_id
        == recepcion_id,
        MensajeProveedorSaliente.estado
        == OutboundProviderMessageState.LEASED.value,
        MensajeProveedorSaliente.lease_expira_en.is_not(None),
        MensajeProveedorSaliente.lease_expira_en <= now,
    )
    with TestingSessionLocal() as session:
        return len(
            list(
                session.execute(
                    select(MensajeProveedorSaliente).where(
                        or_(pending_path, expired_path)
                    )
                ).scalars()
            )
        )


def _config() -> OutboundDispatchConfig:
    return OutboundDispatchConfig(
        sender_e164="+5491100000000",
        status_callback_url="https://example.test/cb",
        lease_seconds=30,
        initial_backoff_seconds=30,
        max_backoff_seconds=300,
        max_attempts=5,
    )


class DispatcherRealDbTest(unittest.TestCase):
    """Real-PostgreSQL proofs for the dispatcher transaction layout."""

    def setUp(self) -> None:
        self.suffix = _suffix()
        self.recepcion_id = _seed_recepcion(self.suffix)
        self.addCleanup(_delete_recepcion, self.recepcion_id)

    def test_claim_survives_session_close(self) -> None:
        """The lease written by the claim transaction is durable
        after the claim session is closed."""
        outbox_id = _seed_outbox_row(
            recepcion_id=self.recepcion_id,
            sequence=0,
            estado=OutboundProviderMessageState.PENDING.value,
        )

        session_factory = sessionmaker(
            bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
        )
        dispatcher = OutboundMessageDispatcher(
            session_factory=session_factory,
            messages_client=MagicMock(spec=TwilioMessagesClient),
            config=_config(),
            now=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
        )

        def _claim_only() -> MensajeProveedorSaliente | None:
            session = session_factory()
            try:
                repo = MensajeProveedorSalienteRepository(session)
                claimed = repo.claim_due(
                    now=dispatcher._now_or(),
                    lease_seconds=30,
                )
                session.commit()
                return claimed
            finally:
                session.close()

        claimed = _require(_claim_only())
        self.assertEqual(int(claimed.id), outbox_id)
        self.assertEqual(
            claimed.estado, OutboundProviderMessageState.LEASED.value
        )

        with TestingSessionLocal() as fresh_session:
            fresh_row = _require(
                fresh_session.get(MensajeProveedorSaliente, outbox_id)
            )
            self.assertEqual(
                fresh_row.estado,
                OutboundProviderMessageState.LEASED.value,
            )
            self.assertIsNotNone(fresh_row.token_lease)
            self.assertIsNotNone(fresh_row.lease_expira_en)
            self.assertEqual(int(fresh_row.intentos), 1)

    def test_finalize_survives_session_close(self) -> None:
        """The accepted SID written by the finalize transaction is
        durable after the finalize session is closed."""
        outbox_id = _seed_outbox_row(
            recepcion_id=self.recepcion_id,
            sequence=0,
            estado=OutboundProviderMessageState.LEASED.value,
            intentos=1,
            token_lease="lease-token-1",
            lease_expira_en=datetime(2026, 8, 6, 12, 5, 0, tzinfo=timezone.utc),
        )

        with TestingSessionLocal() as session, session.begin():
            repo = MensajeProveedorSalienteRepository(session)
            applied = repo.finalize_accepted(
                mensaje_id=outbox_id,
                lease_token="lease-token-1",
                identificador_proveedor="SM-DURABLE",
            )
            self.assertTrue(applied)

        with TestingSessionLocal() as fresh_session:
            fresh_row = _require(
                fresh_session.get(MensajeProveedorSaliente, outbox_id)
            )
            self.assertEqual(
                fresh_row.estado,
                OutboundProviderMessageState.ACCEPTED.value,
            )
            self.assertEqual(
                fresh_row.identificador_proveedor, "SM-DURABLE"
            )
            self.assertIsNone(fresh_row.token_lease)
            self.assertIsNone(fresh_row.lease_expira_en)

    def test_network_call_runs_outside_claim_transaction(self) -> None:
        """Between the claim commit and the finalize begin no
        SQLAlchemy session is open: the network call happens with
        every session closed. The dispatcher must own the claim
        transaction and the finalize transaction as separate
        short-lived sessions."""
        _seed_outbox_row(
            recepcion_id=self.recepcion_id,
            sequence=0,
            estado=OutboundProviderMessageState.PENDING.value,
        )
        _seed_outbox_row(
            recepcion_id=self.recepcion_id,
            sequence=1,
            estado=OutboundProviderMessageState.PENDING.value,
        )

        session_factory = sessionmaker(
            bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
        )

        open_sessions: list[SqlSession] = []
        closed_sessions: list[SqlSession] = []

        class _TrackingSessionFactory:
            def __call__(self) -> SqlSession:
                session = session_factory()
                open_sessions.append(session)
                original_close = session.close

                def _tracking_close() -> None:
                    if session not in closed_sessions:
                        closed_sessions.append(session)
                    original_close()

                session.close = _tracking_close  # type: ignore[method-assign]
                return session

        messages_client = MagicMock(spec=TwilioMessagesClient)
        messages_client.create.return_value = MagicMock(sid="SM-1")

        observed_open_during_send: list[int] = []

        def _track_send(*args: Any, **kwargs: Any) -> Any:
            observed_open_during_send.append(len(open_sessions) - len(closed_sessions))
            return messages_client.create.return_value

        messages_client.create.side_effect = _track_send

        dispatcher = OutboundMessageDispatcher(
            session_factory=_TrackingSessionFactory(),
            messages_client=messages_client,
            config=_config(),
            now=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
        )
        result = dispatcher.dispatch()
        self.assertEqual(result.outcome, OutboundDispatchOutcome.SENT)

        self.assertGreaterEqual(len(observed_open_during_send), 1)
        self.assertEqual(
            observed_open_during_send[-1],
            0,
            "Twilio network call must run with no SQLAlchemy "
            "session open",
        )
        self.assertGreaterEqual(len(open_sessions), 2)
        self.assertGreaterEqual(len(closed_sessions), 2)

    def test_claim_exactly_one_when_two_rows_due(self) -> None:
        """Two due rows: a single ``dispatch`` call leases exactly
        one and leaves the other eligible. The lease is held by the
        freshly minted token only; the second row keeps
        ``token_lease IS NULL`` so a subsequent dispatch can claim
        it."""
        id_a = _seed_outbox_row(
            recepcion_id=self.recepcion_id,
            sequence=0,
            estado=OutboundProviderMessageState.PENDING.value,
        )
        id_b = _seed_outbox_row(
            recepcion_id=self.recepcion_id,
            sequence=1,
            estado=OutboundProviderMessageState.PENDING.value,
        )

        session_factory = sessionmaker(
            bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
        )
        messages_client = MagicMock(spec=TwilioMessagesClient)
        messages_client.create.return_value = MagicMock(sid="SM-A")

        dispatcher = OutboundMessageDispatcher(
            session_factory=session_factory,
            messages_client=messages_client,
            config=_config(),
            now=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
        )

        result = dispatcher.dispatch()
        self.assertEqual(result.outcome, OutboundDispatchOutcome.SENT)
        self.assertEqual(result.mensaje_id, id_a)
        self.assertEqual(result.identificador_proveedor, "SM-A")

        with TestingSessionLocal() as session:
            row_a = _require(
                session.get(MensajeProveedorSaliente, id_a)
            )
            row_b = _require(
                session.get(MensajeProveedorSaliente, id_b)
            )

        self.assertEqual(
            row_a.estado, OutboundProviderMessageState.ACCEPTED.value
        )
        self.assertEqual(
            row_b.estado, OutboundProviderMessageState.PENDING.value
        )
        self.assertIsNone(row_b.token_lease)
        self.assertEqual(int(row_b.intentos), 0)

    def test_expired_lease_is_recovered_by_next_claim(self) -> None:
        """A row in ``leased`` state with an expired ``lease_expira_en``
        must be reclaimable so an abandoned dispatch cannot block
        the operator retry entry point forever."""
        outbox_id = _seed_outbox_row(
            recepcion_id=self.recepcion_id,
            sequence=0,
            estado=OutboundProviderMessageState.LEASED.value,
            intentos=1,
            token_lease="stale-lease",
            lease_expira_en=datetime(
                2026, 8, 6, 11, 59, 0, tzinfo=timezone.utc
            ),
        )

        session_factory = sessionmaker(
            bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
        )
        now = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)
        messages_client = MagicMock(spec=TwilioMessagesClient)
        messages_client.create.return_value = MagicMock(sid="SM-1")
        dispatcher = OutboundMessageDispatcher(
            session_factory=session_factory,
            messages_client=messages_client,
            config=_config(),
            now=now,
        )

        result = dispatcher.dispatch()

        self.assertEqual(result.outcome, OutboundDispatchOutcome.SENT)

        with TestingSessionLocal() as session:
            fresh_row = _require(
                session.get(MensajeProveedorSaliente, outbox_id)
            )
        self.assertEqual(
            fresh_row.estado, OutboundProviderMessageState.ACCEPTED.value
        )
        self.assertNotEqual(fresh_row.token_lease, "stale-lease")
        self.assertIsNone(fresh_row.token_lease)
        lease_expiry = fresh_row.lease_expira_en
        self.assertIsNone(lease_expiry)
        self.assertEqual(int(fresh_row.intentos), 2)
        self.assertEqual(fresh_row.identificador_proveedor, "SM-1")

    def test_duplicate_dispatch_attempt_two_due_rows(self) -> None:
        """Two pending rows: a first ``dispatch`` claims row A; the
        row B remains due. A second ``dispatch`` claims row B and
        only row B. After both calls every due row is leased or
        finalized and the lease count never exceeded one row at
        a time."""
        id_a = _seed_outbox_row(
            recepcion_id=self.recepcion_id,
            sequence=0,
            estado=OutboundProviderMessageState.PENDING.value,
        )
        id_b = _seed_outbox_row(
            recepcion_id=self.recepcion_id,
            sequence=1,
            estado=OutboundProviderMessageState.PENDING.value,
        )

        session_factory = sessionmaker(
            bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
        )
        messages_client = MagicMock(spec=TwilioMessagesClient)
        messages_client.create.side_effect = [
            MagicMock(sid="SM-A"),
            MagicMock(sid="SM-B"),
        ]
        dispatcher = OutboundMessageDispatcher(
            session_factory=session_factory,
            messages_client=messages_client,
            config=_config(),
            now=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
        )

        first = dispatcher.dispatch()
        self.assertEqual(first.mensaje_id, id_a)
        second = dispatcher.dispatch()
        self.assertEqual(second.mensaje_id, id_b)

        with TestingSessionLocal() as session:
            row_a = _require(
                session.get(MensajeProveedorSaliente, id_a)
            )
            row_b = _require(
                session.get(MensajeProveedorSaliente, id_b)
            )
        self.assertEqual(
            row_a.estado, OutboundProviderMessageState.ACCEPTED.value
        )
        self.assertEqual(
            row_b.estado, OutboundProviderMessageState.ACCEPTED.value
        )


class CallbackServiceRealDbTest(unittest.TestCase):
    """Real-PostgreSQL proofs for the callback service persistence."""

    def setUp(self) -> None:
        self.suffix = _suffix()
        self.recepcion_id = _seed_recepcion(self.suffix)
        self.addCleanup(_delete_recepcion, self.recepcion_id)

    def test_applied_transition_persists_across_session(self) -> None:
        """A callback applied inside the service's narrow
        transaction is visible from a fresh session."""
        outbox_id = _seed_outbox_row(
            recepcion_id=self.recepcion_id,
            sequence=0,
            estado=OutboundProviderMessageState.ACCEPTED.value,
            intentos=1,
            identificador_proveedor="SM-DELIVERED",
        )

        with TestingSessionLocal() as session:
            service = TwilioDeliveryCallbackService(
                session, now=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)
            )
            result = service.apply_callback(
                proveedor="twilio",
                identificador_proveedor="SM-DELIVERED",
                message_status="delivered",
            )
        self.assertEqual(result.outcome.value, "applied")

        with TestingSessionLocal() as fresh_session:
            fresh_row = _require(
                fresh_session.get(MensajeProveedorSaliente, outbox_id)
            )
        self.assertEqual(
            fresh_row.estado,
            OutboundProviderMessageState.DELIVERED.value,
        )
        self.assertEqual(fresh_row.estado_proveedor, "delivered")
        self.assertIsNotNone(fresh_row.estado_proveedor_en)

    def test_duplicate_callback_does_not_mutate_or_commit(self) -> None:
        """A duplicate callback for a row already in the target
        state must not mutate the row. The row remains exactly as
        it was before the call (state, provider timestamp and
        attempts are untouched)."""
        baseline_ts = datetime(2026, 8, 6, 11, 0, 0, tzinfo=timezone.utc)
        outbox_id = _seed_outbox_row(
            recepcion_id=self.recepcion_id,
            sequence=0,
            estado=OutboundProviderMessageState.DELIVERED.value,
            intentos=1,
            identificador_proveedor="SM-DUP",
            estado_proveedor="delivered",
            estado_proveedor_en=baseline_ts,
        )

        with TestingSessionLocal() as session:
            service = TwilioDeliveryCallbackService(session)
            result = service.apply_callback(
                proveedor="twilio",
                identificador_proveedor="SM-DUP",
                message_status="delivered",
            )
        self.assertEqual(result.outcome.value, "duplicate")

        with TestingSessionLocal() as fresh_session:
            fresh_row = _require(
                fresh_session.get(MensajeProveedorSaliente, outbox_id)
            )
        self.assertEqual(
            fresh_row.estado,
            OutboundProviderMessageState.DELIVERED.value,
        )
        self.assertEqual(fresh_row.estado_proveedor, "delivered")
        self.assertEqual(fresh_row.estado_proveedor_en, baseline_ts)
        self.assertEqual(int(fresh_row.intentos), 1)

    def test_regression_callback_does_not_mutate(self) -> None:
        outbox_id = _seed_outbox_row(
            recepcion_id=self.recepcion_id,
            sequence=0,
            estado=OutboundProviderMessageState.DELIVERED.value,
            intentos=1,
            identificador_proveedor="SM-REG",
            estado_proveedor="delivered",
            estado_proveedor_en=datetime(
                2026, 8, 6, 11, 0, 0, tzinfo=timezone.utc
            ),
        )
        with TestingSessionLocal() as session:
            service = TwilioDeliveryCallbackService(session)
            result = service.apply_callback(
                proveedor="twilio",
                identificador_proveedor="SM-REG",
                message_status="failed",
            )
        self.assertEqual(result.outcome.value, "regression")
        with TestingSessionLocal() as fresh_session:
            fresh_row = _require(
                fresh_session.get(MensajeProveedorSaliente, outbox_id)
            )
        self.assertEqual(
            fresh_row.estado,
            OutboundProviderMessageState.DELIVERED.value,
        )


TOKEN = "test-auth-token-itest"
BASE_URL = "https://example.test"
ROUTE = "/webhooks/twilio/whatsapp/status"


def _sign(form: dict[str, str]) -> str:
    validator = RequestValidator(TOKEN)
    return validator.compute_signature(f"{BASE_URL}{ROUTE}", form)


class CallbackRouteUnknownStatusTest(unittest.TestCase):
    """A signed callback with a ``MessageStatus`` outside the
    callback service's closed set must be a safe no-op: 204 reply,
    zero service calls, zero database access."""

    def setUp(self) -> None:
        import os

        os.environ["TWILIO_AUTH_TOKEN"] = TOKEN
        os.environ["TWILIO_WEBHOOK_BASE_URL"] = BASE_URL
        self.suffix = _suffix()
        self.recepcion_id = _seed_recepcion(self.suffix)
        self.addCleanup(_delete_recepcion, self.recepcion_id)
        self.outbox_id = _seed_outbox_row(
            recepcion_id=self.recepcion_id,
            sequence=0,
            estado=OutboundProviderMessageState.ACCEPTED.value,
            intentos=1,
            identificador_proveedor="SM-NOOP",
        )

    def _build_client(
        self,
    ) -> tuple[TestClient, MagicMock]:
        import backend.routers.twilio_delivery_callback as router_module

        app = FastAPI()
        app.include_router(router_module.router)
        db_session = MagicMock(name="DatabaseSession")
        app.dependency_overrides[get_session] = lambda: db_session
        return TestClient(app), db_session

    def test_signed_unsupported_status_returns_204_without_db_or_service(
        self,
    ) -> None:
        client, db_session = self._build_client()
        form = {"MessageSid": "SM-NOOP", "MessageStatus": "received"}
        signature = _sign(form)
        with patch(
            "backend.routers.twilio_delivery_callback.load_settings",
            return_value=MagicMock(
                twilio_auth_token=TOKEN, twilio_webhook_base_url=BASE_URL
            ),
        ), patch(
            "backend.routers.twilio_delivery_callback._validator_factory",
            return_value=RequestValidator(TOKEN),
        ), patch(
            "backend.routers.twilio_delivery_callback.TwilioDeliveryCallbackService"
        ) as service_cls:
            response = client.post(
                ROUTE, data=form, headers={"X-Twilio-Signature": signature}
            )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.text, "")
        service_cls.assert_not_called()
        for forbidden in (
            "execute",
            "scalar_one_or_none",
            "scalars",
            "query",
            "add",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertFalse(
                    any(
                        forbidden in str(call)
                        for call in db_session.method_calls
                    ),
                    f"route must not touch the database for an "
                    f"unsupported status; saw {forbidden!r}",
                )

        with TestingSessionLocal() as fresh_session:
            fresh_row = _require(
                fresh_session.get(MensajeProveedorSaliente, self.outbox_id)
            )
        self.assertEqual(
            fresh_row.estado,
            OutboundProviderMessageState.ACCEPTED.value,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
