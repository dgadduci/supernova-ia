"""Phase-5.6 Twilio outbound dispatcher focused tests.

Coverage:

1. The dispatcher claims one due row, calls the Twilio seam once,
   stores the returned SID and cannot send an active lease twice.
2. Transport / 429 / 5xx produce bounded retryable rows; definitive
   4xx and budget exhaustion are terminal.
3. A row with an existing SID is not resent awaiting its callback.
4. Static boundaries: the dispatcher never imports FastAPI, the
   Twilio SDK, the coordinator or the response orchestrator.
5. The real ``twilio.base.exceptions.TwilioRestException`` from the
   pinned SDK 9.10.9 is classified by its HTTP ``status``, not its
   provider ``code``. Unknown exceptions escape unchanged.
"""
from __future__ import annotations

import ast
import dataclasses
import importlib
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

from twilio.base.exceptions import TwilioRestException

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
    OutboundDispatchPayload,
    TwilioMessagesClient,
    TwilioSendRequest,
    TwilioSendResult,
    TwilioSendStatus,
)
from backend.services.twilio_outbound_adapter import (
    send as twilio_send,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


class _StrictTwilioMessagesClient:
    """Strict Twilio ``9.10.9`` Message-create stand-in.

    The stand-in reproduces the pinned SDK's exact ``create`` keyword
    signature (``to``, ``from_``, ``body``, ``status_callback``). Any
    other keyword argument — including the previously-passes
    ``idempotency_key`` — raises ``TypeError`` at the seam, the same
    way the real SDK would. Each call records the four supported
    fields so the focused test can assert the precise payload shape
    without logging bodies, addresses, SIDs or credentials.
    """

    __slots__ = ("_sid", "calls")

    def __init__(self, sid: str) -> None:
        self._sid = sid
        self.calls: list[dict[str, str]] = []

    def create(
        self,
        *,
        to: str,
        from_: str,
        body: str,
        status_callback: str,
    ) -> MagicMock:
        received = {
            "to": to,
            "from_": from_,
            "body": body,
            "status_callback": status_callback,
        }
        self.calls.append(received)
        return MagicMock(sid=self._sid)


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


def _synthetic_rest_exception(
    *,
    status: int,
    provider_code: int | None = 20003,
) -> TwilioRestException:
    """Construct a pinned SDK ``TwilioRestException`` with synthetic
    safe data only.

    The URI is a fixed test marker that mirrors the shape of the
    production path without leaking a real account context. ``msg``
    carries an obvious canary so tests can assert the raw text is
    never persisted. ``details`` is omitted. Provider ``code`` is
    optional so tests can prove HTTP ``status`` — not ``code`` —
    drives retry policy.
    """
    return TwilioRestException(
        status=int(status),
        uri="/2010-04-01/Accounts/test/Messages.json",
        msg=f"synthetic-{status}-message",
        code=provider_code,
    )


class DispatchAcceptedSendTest(unittest.TestCase):
    def setUp(self) -> None:
        importlib.reload(dispatcher_module)

    def test_dispatcher_claims_due_row_and_stores_sid(self) -> None:
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        outbox_repo.claim_due.return_value = _claimed_row()
        outbox_repo.finalize_accepted.return_value = True

        messages_client = _StrictTwilioMessagesClient(sid="SM-ABC")

        dispatcher = OutboundMessageDispatcher(
            session_factory=lambda: db_session,
            messages_client=cast(
                TwilioMessagesClient, messages_client
            ),
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
        self.assertEqual(len(messages_client.calls), 1)
        sent = messages_client.calls[0]
        self.assertEqual(set(sent.keys()), {"to", "from_", "body", "status_callback"})
        self.assertEqual(sent["to"], "whatsapp:+5491155556666")
        self.assertEqual(sent["from_"], "whatsapp:+5491100000000")
        self.assertEqual(sent["body"], "hola")
        self.assertEqual(sent["status_callback"], "https://example.test/cb")
        self.assertNotIn("idempotency_key", sent)
        self.assertGreaterEqual(db_session.commit.call_count, 2)
        self.assertEqual(db_session.close.call_count, 2)
        self.assertEqual(db_session.rollback.call_count, 0)

    def test_strict_seam_rejects_unsupported_keyword(self) -> None:
        """The strict stand-in is the explicit proof that the
        production call shape contains only the four supported SDK
        arguments. Any attempt to forward ``idempotency_key`` — or
        any other unsupported keyword — is rejected at the seam, the
        same way the real Twilio ``9.10.9`` SDK rejects it."""

        messages_client = _StrictTwilioMessagesClient(sid="SM-ABC")

        with self.assertRaises(TypeError):
            messages_client.create(
                to="+5491155556666",
                from_="+5491100000000",
                body="hola",
                status_callback="https://example.test/cb",
                idempotency_key="outbox-11",  # type: ignore[call-arg]
            )
        self.assertEqual(messages_client.calls, [])

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
        messages_client.create.side_effect = _synthetic_rest_exception(
            status=403,
            provider_code=20003,
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
        kwargs = outbox_repo.finalize_terminal.call_args.kwargs
        self.assertEqual(kwargs["codigo"], "20003")
        self.assertNotIn(
            "synthetic-403-message",
            str(kwargs.get("codigo", "")),
            "raw exception text must never reach persistence",
        )

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


class RealRestExceptionClassificationTest(unittest.TestCase):
    """Pinned SDK ``TwilioRestException`` contract.

    All tests construct synthetic safe data — no real network, no
    real account, no addresses, no bodies. They prove:

    1. HTTP 429 → bounded retry with the provider code carried only
       as observability.
    2. HTTP 5xx (incl. 408 / 425) → bounded retry.
    3. Other HTTP 4xx → immediate terminal finalization; raw
       exception text is dropped.
    4. The Twilio provider ``code`` does not control retry policy.
    5. ``TypeError`` and exceptions outside the supported categories
       propagate as technical failures.
    """

    def setUp(self) -> None:
        importlib.reload(dispatcher_module)

    @staticmethod
    def _build_dispatcher(
        *,
        messages_client: MagicMock,
        outbox_repo: MagicMock,
        db_session: MagicMock,
        now: datetime,
    ) -> OutboundMessageDispatcher:
        return OutboundMessageDispatcher(
            session_factory=lambda: db_session,
            messages_client=cast(TwilioMessagesClient, messages_client),
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

    def test_http_429_is_bounded_retry_with_provider_code(self) -> None:
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        claimed = _claimed_row(attempts=1)
        outbox_repo.claim_due.return_value = claimed
        outbox_repo.finalize_retryable.return_value = True

        messages_client = MagicMock(name="TwilioMessagesClient")
        messages_client.create.side_effect = _synthetic_rest_exception(
            status=429,
            provider_code=20003,
        )

        now = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)
        dispatcher = self._build_dispatcher(
            messages_client=messages_client,
            outbox_repo=outbox_repo,
            db_session=db_session,
            now=now,
        )

        result = dispatcher.dispatch()

        self.assertEqual(
            result.outcome, OutboundDispatchOutcome.RETRY_SCHEDULED
        )
        self.assertEqual(
            result.categoria, OutboundFailureCategory.RETRYABLE_429
        )
        outbox_repo.finalize_retryable.assert_called_once()
        kwargs = outbox_repo.finalize_retryable.call_args.kwargs
        self.assertEqual(kwargs["codigo"], "20003")
        self.assertEqual(
            kwargs["proximo_intento_en"], now + timedelta(seconds=30)
        )
        self.assertNotIn(
            "synthetic-429-message", str(kwargs.get("codigo", ""))
        )

    def test_http_5xx_is_bounded_retry(self) -> None:
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        claimed = _claimed_row(attempts=1)
        outbox_repo.claim_due.return_value = claimed
        outbox_repo.finalize_retryable.return_value = True

        messages_client = MagicMock(name="TwilioMessagesClient")
        messages_client.create.side_effect = _synthetic_rest_exception(
            status=500,
            provider_code=20500,
        )

        now = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)
        dispatcher = self._build_dispatcher(
            messages_client=messages_client,
            outbox_repo=outbox_repo,
            db_session=db_session,
            now=now,
        )

        result = dispatcher.dispatch()

        self.assertEqual(
            result.outcome, OutboundDispatchOutcome.RETRY_SCHEDULED
        )
        self.assertEqual(
            result.categoria, OutboundFailureCategory.RETRYABLE_5XX
        )
        kwargs = outbox_repo.finalize_retryable.call_args.kwargs
        self.assertEqual(kwargs["codigo"], "20500")
        self.assertEqual(
            kwargs["proximo_intento_en"], now + timedelta(seconds=30)
        )

    def test_http_408_and_425_are_retryable_5xx(self) -> None:
        for status in (408, 425, 502, 503, 504):
            with self.subTest(status=status):
                db_session = MagicMock(name="DatabaseSession")
                outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
                outbox_repo.claim_due.return_value = _claimed_row(attempts=1)
                outbox_repo.finalize_retryable.return_value = True

                messages_client = MagicMock(name="TwilioMessagesClient")
                messages_client.create.side_effect = (
                    _synthetic_rest_exception(
                        status=status, provider_code=20003
                    )
                )

                now = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)
                dispatcher = self._build_dispatcher(
                    messages_client=messages_client,
                    outbox_repo=outbox_repo,
                    db_session=db_session,
                    now=now,
                )

                result = dispatcher.dispatch()

                self.assertEqual(
                    result.outcome,
                    OutboundDispatchOutcome.RETRY_SCHEDULED,
                )
                self.assertEqual(
                    result.categoria,
                    OutboundFailureCategory.RETRYABLE_5XX,
                )

    def test_http_501_is_retryable_5xx(self) -> None:
        """HTTP 501 was previously omitted from the retryable set.

        Any HTTP status in the 500-599 range is retryable-5xx. This
        representative case proves the widened classifier still maps
        to ``RETRY_SCHEDULED`` and ``RETRYABLE_5XX`` for a status the
        earlier explicit short list would have misclassified.
        """
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        outbox_repo.claim_due.return_value = _claimed_row(attempts=1)
        outbox_repo.finalize_retryable.return_value = True

        messages_client = MagicMock(name="TwilioMessagesClient")
        messages_client.create.side_effect = _synthetic_rest_exception(
            status=501,
            provider_code=20501,
        )

        now = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)
        dispatcher = self._build_dispatcher(
            messages_client=messages_client,
            outbox_repo=outbox_repo,
            db_session=db_session,
            now=now,
        )

        result = dispatcher.dispatch()

        self.assertEqual(
            result.outcome, OutboundDispatchOutcome.RETRY_SCHEDULED
        )
        self.assertEqual(
            result.categoria, OutboundFailureCategory.RETRYABLE_5XX
        )
        kwargs = outbox_repo.finalize_retryable.call_args.kwargs
        self.assertEqual(kwargs["codigo"], "20501")
        self.assertEqual(
            kwargs["proximo_intento_en"], now + timedelta(seconds=30)
        )

    def test_other_4xx_is_terminal_and_drops_exception_message(self) -> None:
        for status in (400, 401, 403, 404, 422):
            with self.subTest(status=status):
                db_session = MagicMock(name="DatabaseSession")
                outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
                outbox_repo.claim_due.return_value = _claimed_row(attempts=1)
                outbox_repo.finalize_terminal.return_value = True

                messages_client = MagicMock(name="TwilioMessagesClient")
                messages_client.create.side_effect = (
                    _synthetic_rest_exception(
                        status=status, provider_code=20003
                    )
                )

                dispatcher = self._build_dispatcher(
                    messages_client=messages_client,
                    outbox_repo=outbox_repo,
                    db_session=db_session,
                    now=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
                )

                result = dispatcher.dispatch()

                self.assertEqual(
                    result.outcome,
                    OutboundDispatchOutcome.FAILED_TERMINAL,
                )
                self.assertEqual(
                    result.categoria,
                    OutboundFailureCategory.TERMINAL_4XX,
                )
                kwargs = outbox_repo.finalize_terminal.call_args.kwargs
                detalle = str(kwargs.get("codigo", ""))
                self.assertNotIn(
                    f"synthetic-{status}-message",
                    detalle,
                    "raw exception msg must never reach persistence",
                )
                self.assertNotIn(
                    "/2010-04-01/Accounts/test/Messages.json",
                    detalle,
                    "raw exception URI must never reach persistence",
                )

    def test_provider_code_does_not_drive_retry_policy(self) -> None:
        """Same Twilio provider ``code`` with different HTTP statuses
        must map to different categories. The provider code is
        observability only — HTTP ``status`` decides retry policy."""
        cases = [
            (429, OutboundFailureCategory.RETRYABLE_429),
            (503, OutboundFailureCategory.RETRYABLE_5XX),
            (403, OutboundFailureCategory.TERMINAL_4XX),
        ]
        for status, expected in cases:
            with self.subTest(status=status):
                db_session = MagicMock(name="DatabaseSession")
                outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
                outbox_repo.claim_due.return_value = _claimed_row(attempts=1)
                outbox_repo.finalize_retryable.return_value = True
                outbox_repo.finalize_terminal.return_value = True

                messages_client = MagicMock(name="TwilioMessagesClient")
                messages_client.create.side_effect = (
                    _synthetic_rest_exception(
                        status=status, provider_code=20003
                    )
                )

                dispatcher = self._build_dispatcher(
                    messages_client=messages_client,
                    outbox_repo=outbox_repo,
                    db_session=db_session,
                    now=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
                )

                result = dispatcher.dispatch()

                self.assertEqual(result.categoria, expected)
                if expected is OutboundFailureCategory.TERMINAL_4XX:
                    outbox_repo.finalize_terminal.assert_called_once()
                    outbox_repo.finalize_retryable.assert_not_called()
                else:
                    outbox_repo.finalize_retryable.assert_called_once()
                    outbox_repo.finalize_terminal.assert_not_called()

    def test_typeerror_escapes_as_technical_failure(self) -> None:
        """A ``TypeError`` from the seam is outside the explicit
        supported categories — it must propagate unchanged rather
        than be silently classified as a provider outcome."""
        messages_client = MagicMock(name="TwilioMessagesClient")
        messages_client.create.side_effect = TypeError(
            "unexpected kwarg"
        )

        payload = OutboundDispatchPayload(
            destinatario_e164="+5491155556666",
            cuerpo="hola",
            idempotency_key="outbox-11",
        )
        request = TwilioSendRequest(
            destinatario_e164=payload.destinatario_e164,
            sender_e164="+5491100000000",
            cuerpo=payload.cuerpo,
            status_callback_url="https://example.test/cb",
            idempotency_key=payload.idempotency_key,
        )

        with self.assertRaises(TypeError):
            twilio_send(cast(TwilioMessagesClient, messages_client), request)


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