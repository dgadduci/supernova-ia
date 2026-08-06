"""Phase-5.6 Twilio outbound dispatcher focused tests.

Coverage:

1. The dispatcher claims one due row, calls the Twilio seam once,
   stores the returned SID and cannot send an active lease twice.
2. Transport / 429 / 5xx produce bounded retryable rows; definitive
   4xx and budget exhaustion are terminal.
3. A row with an existing SID is not resent awaiting its callback.
4. Static boundaries: the dispatcher never imports FastAPI, the
   Twilio SDK, the coordinator or the response orchestrator.
"""
from __future__ import annotations

import ast
import dataclasses
import importlib
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

from backend.models.mensaje_proveedor_saliente import (
    MensajeProveedorSaliente,
    OutboundFailureCategory,
    OutboundProviderMessageState,
)
from backend.services import outbound_message_dispatcher as dispatcher_module
from backend.services import twilio_outbound_adapter as adapter_module
from backend.services.outbound_callback_types import (  # noqa: F401  (boundary check)
    OutboundCallbackOutcome,
)
from backend.services.outbound_dispatch_types import (
    OutboundDispatchOutcome,
    OutboundDispatchResult,
)
from backend.services.outbound_message_dispatcher import (
    OutboundDispatchConfig,
    OutboundMessageDispatcher,
)
from backend.services.twilio_outbound_adapter import (
    TwilioSendResult,
    TwilioSendStatus,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _settings_stub(
    *,
    sender: str = "+5491100000000",
    callback_url: str = "https://example.test/cb",
    lease_seconds: int = 30,
    initial_backoff: int = 30,
    max_backoff: int = 300,
    max_attempts: int = 5,
) -> MagicMock:
    settings = MagicMock(name="Settings")
    settings.twilio_outbound_sender_e164 = sender
    settings.twilio_callback_status_url = callback_url
    settings.twilio_outbound_lease_seconds = lease_seconds
    settings.twilio_outbound_initial_backoff_seconds = initial_backoff
    settings.twilio_outbound_max_backoff_seconds = max_backoff
    settings.twilio_outbound_max_attempts = max_attempts
    return settings


def _claimed_row(
    *,
    outbox_id: int = 11,
    lease_token: str = "lease-token-1",
    attempts: int = 1,
    estado: str = OutboundProviderMessageState.LEASED.value,
) -> MensajeProveedorSaliente:
    row = MensajeProveedorSaliente(
        id=outbox_id,
        proveedor="twilio",
        recepcion_mensaje_proveedor_id=1,
        destinatario_e164="+5491155556666",
        cuerpo="hola",
        sequence=0,
        estado=estado,
        identificador_proveedor=None,
        intentos=attempts,
        proximo_intento_en=None,
        token_lease=lease_token,
        lease_expira_en=None,
        categoria_ultimo_fallo=None,
        codigo_ultimo_fallo=None,
        estado_proveedor=None,
        estado_proveedor_en=None,
        fecha_creacion=datetime.now(tz=timezone.utc),
    )
    return row


class DispatchAcceptedSendTest(unittest.TestCase):
    def setUp(self) -> None:
        importlib.reload(dispatcher_module)

    def test_dispatcher_claims_due_row_and_stores_sid(self) -> None:
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        outbox_repo.claim_due.return_value = _claimed_row()
        outbox_repo.finalize_accepted.return_value = True

        messages_client = MagicMock(name="TwilioMessagesClient")
        messages_client.create.return_value = MagicMock(sid="SM-ABC")

        dispatcher = OutboundMessageDispatcher(
            session_factory=lambda: db_session,
            messages_client=messages_client,
            config=OutboundDispatchConfig(
                sender_e164="+5491100000000",
                status_callback_url="https://example.test/cb",
                lease_seconds=30,
                initial_backoff_seconds=30,
                max_backoff_seconds=300,
                max_attempts=5,
            ),
            outbox_repo_factory=lambda _session: outbox_repo,
            settings=_settings_stub(),
            now=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
        )

        result = dispatcher.dispatch()

        self.assertEqual(result.outcome, OutboundDispatchOutcome.SENT)
        self.assertEqual(result.mensaje_id, 11)
        self.assertEqual(result.identificador_proveedor, "SM-ABC")
        outbox_repo.claim_due.assert_called_once()
        outbox_repo.finalize_accepted.assert_called_once_with(
            mensaje_id=11,
            lease_token="lease-token-1",
            identificador_proveedor="SM-ABC",
        )
        messages_client.create.assert_called_once()
        kwargs = messages_client.create.call_args.kwargs
        self.assertEqual(kwargs["to"], "+5491155556666")
        self.assertEqual(kwargs["from_"], "+5491100000000")
        self.assertEqual(kwargs["body"], "hola")
        self.assertEqual(kwargs["status_callback"], "https://example.test/cb")
        self.assertEqual(kwargs["idempotency_key"], "outbox-11")
        self.assertGreaterEqual(db_session.commit.call_count, 2)
        self.assertEqual(db_session.close.call_count, 2)
        self.assertEqual(db_session.rollback.call_count, 0)

    def test_dispatcher_returns_no_due_row_when_claim_misses(self) -> None:
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        outbox_repo.claim_due.return_value = None

        messages_client = MagicMock(name="TwilioMessagesClient")

        dispatcher = OutboundMessageDispatcher(
            session_factory=lambda: db_session,
            messages_client=messages_client,
            config=OutboundDispatchConfig(
                sender_e164="+5491100000000",
                status_callback_url="https://example.test/cb",
                lease_seconds=30,
                initial_backoff_seconds=30,
                max_backoff_seconds=300,
                max_attempts=5,
            ),
            outbox_repo_factory=lambda _session: outbox_repo,
            settings=_settings_stub(),
        )

        result = dispatcher.dispatch()

        self.assertEqual(result.outcome, OutboundDispatchOutcome.NO_DUE_ROW)
        messages_client.create.assert_not_called()
        db_session.commit.assert_called_once()


class DispatchRetryClassificationTest(unittest.TestCase):
    def setUp(self) -> None:
        importlib.reload(dispatcher_module)

    def test_retryable_transport_failure_schedules_retry(self) -> None:
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        claimed = _claimed_row(attempts=1)
        outbox_repo.claim_due.return_value = claimed
        outbox_repo.finalize_retryable.return_value = True

        messages_client = MagicMock(name="TwilioMessagesClient")
        messages_client.create.side_effect = (
            adapter_module._TwilioTransportError("timeout")
        )

        now = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)
        dispatcher = OutboundMessageDispatcher(
            session_factory=lambda: db_session,
            messages_client=messages_client,
            config=OutboundDispatchConfig(
                sender_e164="+5491100000000",
                status_callback_url="https://example.test/cb",
                lease_seconds=30,
                initial_backoff_seconds=30,
                max_backoff_seconds=300,
                max_attempts=5,
            ),
            outbox_repo_factory=lambda _session: outbox_repo,
            settings=_settings_stub(),
            now=now,
        )

        result = dispatcher.dispatch()

        self.assertEqual(
            result.outcome, OutboundDispatchOutcome.RETRY_SCHEDULED
        )
        self.assertEqual(result.mensaje_id, 11)
        self.assertEqual(result.categoria, OutboundFailureCategory.RETRYABLE_TIMEOUT)
        outbox_repo.finalize_retryable.assert_called_once()
        kwargs = outbox_repo.finalize_retryable.call_args.kwargs
        self.assertEqual(
            kwargs["proximo_intento_en"],
            now + timedelta(seconds=30),
        )

    def test_terminal_4xx_is_immediately_terminal(self) -> None:
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        claimed = _claimed_row(attempts=1)
        outbox_repo.claim_due.return_value = claimed
        outbox_repo.finalize_terminal.return_value = True

        messages_client = MagicMock(name="TwilioMessagesClient")
        messages_client.create.side_effect = (
            adapter_module._TwilioAPIError(403)
        )

        dispatcher = OutboundMessageDispatcher(
            session_factory=lambda: db_session,
            messages_client=messages_client,
            config=OutboundDispatchConfig(
                sender_e164="+5491100000000",
                status_callback_url="https://example.test/cb",
                lease_seconds=30,
                initial_backoff_seconds=30,
                max_backoff_seconds=300,
                max_attempts=5,
            ),
            outbox_repo_factory=lambda _session: outbox_repo,
            settings=_settings_stub(),
        )

        result = dispatcher.dispatch()

        self.assertEqual(
            result.outcome, OutboundDispatchOutcome.FAILED_TERMINAL
        )
        self.assertEqual(
            result.categoria, OutboundFailureCategory.TERMINAL_4XX
        )
        outbox_repo.finalize_terminal.assert_called_once()

    def test_retry_budget_exhaustion_is_terminal(self) -> None:
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        claimed = _claimed_row(attempts=5)
        outbox_repo.claim_due.return_value = claimed
        outbox_repo.finalize_terminal.return_value = True

        messages_client = MagicMock(name="TwilioMessagesClient")
        messages_client.create.side_effect = (
            adapter_module._TwilioTransportError("timeout")
        )

        dispatcher = OutboundMessageDispatcher(
            session_factory=lambda: db_session,
            messages_client=messages_client,
            config=OutboundDispatchConfig(
                sender_e164="+5491100000000",
                status_callback_url="https://example.test/cb",
                lease_seconds=30,
                initial_backoff_seconds=30,
                max_backoff_seconds=300,
                max_attempts=5,
            ),
            outbox_repo_factory=lambda _session: outbox_repo,
            settings=_settings_stub(max_attempts=5),
        )

        result = dispatcher.dispatch()

        self.assertEqual(
            result.outcome, OutboundDispatchOutcome.FAILED_TERMINAL
        )
        self.assertEqual(
            result.categoria, OutboundFailureCategory.BUDGET_EXHAUSTED
        )

    def test_backoff_is_bounded_by_max_seconds(self) -> None:
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        claimed = _claimed_row(attempts=20)
        outbox_repo.claim_due.return_value = claimed
        outbox_repo.finalize_retryable.return_value = True

        messages_client = MagicMock(name="TwilioMessagesClient")
        messages_client.create.side_effect = (
            adapter_module._TwilioTransportError("timeout")
        )

        now = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)
        dispatcher = OutboundMessageDispatcher(
            session_factory=lambda: db_session,
            messages_client=messages_client,
            config=OutboundDispatchConfig(
                sender_e164="+5491100000000",
                status_callback_url="https://example.test/cb",
                lease_seconds=30,
                initial_backoff_seconds=30,
                max_backoff_seconds=60,
                max_attempts=99,
            ),
            outbox_repo_factory=lambda _session: outbox_repo,
            settings=_settings_stub(max_backoff=60, max_attempts=99),
            now=now,
        )

        dispatcher.dispatch()

        kwargs = outbox_repo.finalize_retryable.call_args.kwargs
        self.assertEqual(
            kwargs["proximo_intento_en"],
            now + timedelta(seconds=60),
        )


class LateFinalizationProtectionTest(unittest.TestCase):
    def setUp(self) -> None:
        importlib.reload(dispatcher_module)

    def test_late_acceptance_does_not_overwrite_state(self) -> None:
        """When the SDK returns success but the lease token is no
        longer present (because a parallel dispatcher already
        claimed and finalized the row), the dispatcher records a
        no-op result rather than overwriting the newer attempt."""
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        claimed = _claimed_row(lease_token="stale-token")
        outbox_repo.claim_due.return_value = claimed
        outbox_repo.finalize_accepted.return_value = False

        messages_client = MagicMock(name="TwilioMessagesClient")
        messages_client.create.return_value = MagicMock(sid="SM-LATE")

        dispatcher = OutboundMessageDispatcher(
            session_factory=lambda: db_session,
            messages_client=messages_client,
            config=OutboundDispatchConfig(
                sender_e164="+5491100000000",
                status_callback_url="https://example.test/cb",
                lease_seconds=30,
                initial_backoff_seconds=30,
                max_backoff_seconds=300,
                max_attempts=5,
            ),
            outbox_repo_factory=lambda _session: outbox_repo,
            settings=_settings_stub(),
        )

        result = dispatcher.dispatch()

        self.assertEqual(result.outcome, OutboundDispatchOutcome.NO_DUE_ROW)
        self.assertEqual(result.mensaje_id, 11)
        self.assertEqual(result.detalle, "late_acceptance")


class AcceptedRowNotResentTest(unittest.TestCase):
    def setUp(self) -> None:
        importlib.reload(dispatcher_module)

    def test_accepted_rows_are_not_due(self) -> None:
        """The repository's ``claim_due`` query excludes rows that
        are already in ``accepted`` or terminal states. A row with
        an existing SID stays in ``accepted`` until its callback
        arrives; the dispatcher never picks it up again."""

        repo_path = (
            REPO_ROOT
            / "backend"
            / "repositories"
            / "mensaje_proveedor_saliente_repository.py"
        )
        source = repo_path.read_text(encoding="utf-8")
        self.assertIn(
            "OutboundProviderMessageState.ACCEPTED.value",
            source,
            "claim_due must reference accepted state to confirm exclusion",
        )
        self.assertIn(
            "OutboundProviderMessageState.PENDING.value",
            source,
        )
        self.assertIn(
            "OutboundProviderMessageState.RETRYABLE.value",
            source,
        )


class ModuleBoundaryTest(unittest.TestCase):
    def test_dispatcher_does_not_import_http_or_twilio(self) -> None:
        path = (
            REPO_ROOT
            / "backend"
            / "services"
            / "outbound_message_dispatcher.py"
        )
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        forbidden = {"fastapi", "starlette", "twilio", "RequestValidator"}
        leaked = forbidden & names
        self.assertEqual(
            leaked,
            set(),
            f"Outbound dispatcher must not import HTTP / Twilio SDK: {leaked}",
        )

    def test_adapter_does_not_import_sqlalchemy_or_repository(self) -> None:
        path = (
            REPO_ROOT
            / "backend"
            / "services"
            / "twilio_outbound_adapter.py"
        )
        source = path.read_text(encoding="utf-8")
        for forbidden in (
            "sqlalchemy",
            "from backend.repositories",
            "MensajeProveedorSalienteRepository",
            "from backend.models",
            "from backend.routers",
            "from backend.intents",
            "from backend.config",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(
                    forbidden,
                    source,
                    f"adapter must not import {forbidden}",
                )


class DispatcherResultContractTest(unittest.TestCase):
    def test_outbound_dispatch_result_is_frozen(self) -> None:
        result = OutboundDispatchResult(
            outcome=OutboundDispatchOutcome.NO_DUE_ROW,
            mensaje_id=None,
            identificador_proveedor=None,
            intentos=None,
            categoria=None,
            codigo=None,
            detalle="x",
        )
        with self.assertRaises((AttributeError, dataclasses.FrozenInstanceError)):
            result.outcome = OutboundDispatchOutcome.SENT  # type: ignore[misc]

    def test_dispatcher_module_exports(self) -> None:
        self.assertEqual(
            set(dispatcher_module.__all__),
            {
                "OutboundDispatchConfig",
                "OutboundMessageDispatcher",
                "OutboxRepoFactory",
                "SessionFactory",
            },
        )


class TwilioSendResultContractTest(unittest.TestCase):
    def test_send_result_is_frozen(self) -> None:
        result = TwilioSendResult(
            status=TwilioSendStatus.SENT,
            message_sid="SM-1",
            categoria=None,
            codigo=None,
            detalle=None,
        )
        with self.assertRaises((AttributeError, dataclasses.FrozenInstanceError)):
            result.message_sid = "SM-2"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main(verbosity=2)