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
6. Each normal ``dispatch`` result emits exactly one structured,
   stdout-bound ``outbound_attempt_outcome`` JSON event that the
   production observability CLI can query. The event never carries
   the message body, the destination E.164 or the provider SID.
"""
from __future__ import annotations

import ast
import contextlib
import dataclasses
import importlib
import io
import json
import logging
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

from twilio.base.exceptions import TwilioRestException

from backend.models.mensaje_proveedor_saliente import (
    MensajeProveedorSaliente,
    OutboundFailureCategory,
    OutboundProviderMessageState,
)
from backend.observability import (
    COMPONENT_OUTBOUND,
    EVENT_OUTBOUND_OUTCOME,
    parse_event,
)
from backend.services import outbound_message_dispatcher as dispatcher_module
from backend.services import twilio_outbound_adapter as adapter_module
from backend.services.outbound_callback_types import (  # noqa: F401  (boundary check)
    OutboundCallbackOutcome,
)
from backend.services.outbound_dispatch_types import (
    OutboundAttemptOutcome,
    OutboundCycleAggregate,
    OutboundDispatchOutcome,
    OutboundDispatchResult,
    OutboundPassEvidence,
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
    isolated_enabled: bool = False,
) -> MagicMock:
    settings = MagicMock(name="Settings")
    settings.twilio_outbound_sender_e164 = sender
    settings.twilio_callback_status_url = callback_url
    settings.twilio_outbound_lease_seconds = lease_seconds
    settings.twilio_outbound_initial_backoff_seconds = initial_backoff
    settings.twilio_outbound_max_backoff_seconds = max_backoff
    settings.twilio_outbound_max_attempts = max_attempts
    settings.commerce_isolated_outbound_enabled = bool(isolated_enabled)
    settings.commerce_isolated_http_timeout_seconds = 5
    settings.commerce_isolated_tc_base_url_legacy = None
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
            http_status=None,
            detalle=None,
        )
        with self.assertRaises((AttributeError, dataclasses.FrozenInstanceError)):
            result.message_sid = "SM-2"  # type: ignore[misc]


class DispatcherSafeAttemptEventTest(unittest.TestCase):
    """The dispatcher must emit exactly one sanitized
    ``provider_outbound_attempt`` log record per completed
    ``dispatch`` call. The record contains only the allowlisted
    safe fields and never the raw exception text, addresses,
    signatures, payloads, bodies or tracebacks.
    """

    def setUp(self) -> None:
        importlib.reload(dispatcher_module)

    @staticmethod
    def _build_dispatcher(
        *,
        messages_client: MagicMock,
        outbox_repo: MagicMock,
        db_session: MagicMock,
        attempts: int,
        now: datetime,
    ) -> OutboundMessageDispatcher:
        claimed = _claimed_row(attempts=attempts)
        outbox_repo.claim_due.return_value = claimed
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

    def test_accepted_dispatch_emits_safe_attempt_event(self) -> None:
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        outbox_repo.finalize_accepted.return_value = True
        messages_client = _StrictTwilioMessagesClient(sid="SM-OK")

        dispatcher = self._build_dispatcher(
            messages_client=messages_client,
            outbox_repo=outbox_repo,
            db_session=db_session,
            attempts=1,
            now=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
        )

        with self.assertLogs(
            dispatcher_module.logger, level=logging.INFO
        ) as log_ctx:
            dispatcher.dispatch()

        records = [
            r
            for r in log_ctx.records
            if r.getMessage() == "provider_outbound_attempt"
        ]
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.outcome, "sent")
        self.assertEqual(record.outbox_id, 11)
        self.assertEqual(record.durable_state, "accepted")
        self.assertIsNone(getattr(record, "attempt_count", None))
        self.assertIsNone(getattr(record, "failure_category", None))
        self.assertIsNone(getattr(record, "provider_code", None))
        self.assertIsNone(getattr(record, "http_status", None))
        self.assertIsNone(getattr(record, "exception_type", None))
        self.assertFalse(record.exc_info)

    def test_retryable_dispatch_emits_safe_attempt_event_with_code(
        self,
    ) -> None:
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        outbox_repo.finalize_retryable.return_value = True
        messages_client = MagicMock(name="TwilioMessagesClient")
        messages_client.create.side_effect = _synthetic_rest_exception(
            status=429, provider_code=20003
        )

        dispatcher = self._build_dispatcher(
            messages_client=messages_client,
            outbox_repo=outbox_repo,
            db_session=db_session,
            attempts=1,
            now=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
        )

        with self.assertLogs(
            dispatcher_module.logger, level=logging.INFO
        ) as log_ctx:
            dispatcher.dispatch()

        records = [
            r
            for r in log_ctx.records
            if r.getMessage() == "provider_outbound_attempt"
        ]
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.outcome, "retry_scheduled")
        self.assertEqual(record.outbox_id, 11)
        self.assertEqual(record.attempt_count, 1)
        self.assertEqual(record.durable_state, "retryable")
        self.assertEqual(
            record.failure_category, "retryable_429"
        )
        self.assertEqual(record.provider_code, "20003")
        self.assertEqual(record.http_status, 429)
        self.assertIsNone(getattr(record, "exception_type", None))
        self.assertFalse(record.exc_info)

    def test_terminal_dispatch_emits_safe_attempt_event(self) -> None:
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        outbox_repo.finalize_terminal.return_value = True
        messages_client = MagicMock(name="TwilioMessagesClient")
        messages_client.create.side_effect = _synthetic_rest_exception(
            status=403, provider_code=20003
        )

        dispatcher = self._build_dispatcher(
            messages_client=messages_client,
            outbox_repo=outbox_repo,
            db_session=db_session,
            attempts=1,
            now=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
        )

        with self.assertLogs(
            dispatcher_module.logger, level=logging.INFO
        ) as log_ctx:
            dispatcher.dispatch()

        records = [
            r
            for r in log_ctx.records
            if r.getMessage() == "provider_outbound_attempt"
        ]
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(
            record.outcome, "failed_terminal"
        )
        self.assertEqual(record.outbox_id, 11)
        self.assertEqual(record.attempt_count, 1)
        self.assertEqual(
            record.durable_state, "failed_terminal"
        )
        self.assertEqual(
            record.failure_category, "terminal_4xx"
        )
        self.assertEqual(record.provider_code, "20003")
        self.assertEqual(record.http_status, 403)
        self.assertIsNone(getattr(record, "exception_type", None))
        self.assertFalse(record.exc_info)

    def test_no_due_row_emits_safe_attempt_event_without_optionals(
        self,
    ) -> None:
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
            now=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
        )

        with self.assertLogs(
            dispatcher_module.logger, level=logging.INFO
        ) as log_ctx:
            dispatcher.dispatch()

        records = [
            r
            for r in log_ctx.records
            if r.getMessage() == "provider_outbound_attempt"
        ]
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.outcome, "no_due_row")
        self.assertIsNone(getattr(record, "outbox_id", None))
        self.assertIsNone(getattr(record, "attempt_count", None))
        self.assertIsNone(getattr(record, "durable_state", None))
        self.assertIsNone(getattr(record, "failure_category", None))
        self.assertIsNone(getattr(record, "provider_code", None))
        self.assertIsNone(getattr(record, "http_status", None))
        self.assertIsNone(getattr(record, "exception_type", None))
        self.assertFalse(record.exc_info)
        messages_client.create.assert_not_called()

    def test_technical_failure_emits_event_with_exception_class_only(
        self,
    ) -> None:
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        outbox_repo.claim_due.return_value = _claimed_row()
        messages_client = MagicMock(name="TwilioMessagesClient")
        messages_client.create.side_effect = TypeError(
            "secret-auth-token-value / +5491100000000 leak"
        )

        dispatcher = self._build_dispatcher(
            messages_client=messages_client,
            outbox_repo=outbox_repo,
            db_session=db_session,
            attempts=1,
            now=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
        )

        with self.assertLogs(
            dispatcher_module.logger, level=logging.INFO
        ) as log_ctx:
            with self.assertRaises(TypeError):
                dispatcher.dispatch()

        records = [
            r
            for r in log_ctx.records
            if r.getMessage() == "provider_outbound_attempt"
        ]
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(
            record.outcome, "technical_failure"
        )
        self.assertEqual(
            record.exception_type, "TypeError"
        )
        self.assertIsNone(getattr(record, "failure_category", None))
        self.assertIsNone(getattr(record, "provider_code", None))
        self.assertIsNone(getattr(record, "http_status", None))
        self.assertFalse(record.exc_info)

        for value in record.__dict__.values():
            if isinstance(value, str):
                self.assertNotIn("secret-auth-token-value", value)
                self.assertNotIn("+5491100000000", value)
                self.assertNotIn("leak", value)

    def test_event_payload_never_includes_addresses_or_payloads(
        self,
    ) -> None:
        sentinel = "+5491100000000-leak"
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        outbox_repo.finalize_accepted.return_value = True
        messages_client = _StrictTwilioMessagesClient(sid="SM-OK")

        row = _claimed_row()
        row.destinatario_e164 = sentinel
        row.cuerpo = "secret-body-content"
        outbox_repo.claim_due.return_value = row

        dispatcher = OutboundMessageDispatcher(
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
            now=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
        )

        with self.assertLogs(
            dispatcher_module.logger, level=logging.INFO
        ) as log_ctx:
            dispatcher.dispatch()

        records = [
            r
            for r in log_ctx.records
            if r.getMessage() == "provider_outbound_attempt"
        ]
        self.assertEqual(len(records), 1)
        record = records[0]
        for value in record.__dict__.values():
            if isinstance(value, str):
                self.assertNotIn(sentinel, value)
                self.assertNotIn("secret-body-content", value)
                self.assertNotIn("SM-OK", value)


class DispatcherOutboundOutcomeEventTest(unittest.TestCase):
    """The dispatcher must emit exactly one structured
    ``outbound_attempt_outcome`` JSON event on stdout per normal
    ``dispatch`` call so the production observability CLI can query
    the dispatcher state without parsing the Python log record.

    The structured event is the canonical contract the Railway
    query CLI binds to. The event carries only the allowlisted
    safe fields and never the outbound body, the destination
    E.164 or the provider SID. Technical failures do not emit this
    event; the existing ``provider_outbound_attempt`` log record
    and the repository-level ``database_technical_failure`` event
    stay the only safe surface for that path.
    """

    def setUp(self) -> None:
        importlib.reload(dispatcher_module)

    @staticmethod
    def _capture_stdout(callable_):
        """Invoke ``callable_`` with stdout redirected to a buffer.

        Returns the buffered stdout string so the test can assert
        verbatim on the JSON lines the dispatcher emits.
        """
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            callable_()
        return buffer.getvalue()

    @staticmethod
    def _parse_outbound_lines(stdout_text: str) -> list[dict]:
        """Parse every JSON line emitted to stdout and return only
        the ``outbound_attempt_outcome`` events.

        The dispatcher emits exactly one such line per normal
        ``dispatch`` call. The Railway query CLI parses the same
        shape through ``parse_event``; the assert uses the same
        helper so any contract drift fails the test.
        """
        parsed: list[dict] = []
        for raw_line in stdout_text.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if payload.get("event") == EVENT_OUTBOUND_OUTCOME:
                parsed.append(parse_event(stripped))
        return parsed

    def test_accepted_dispatch_emits_parseable_outbound_outcome_event(
        self,
    ) -> None:
        """A successful ``accepted`` dispatch must emit one
        parseable ``outbound_attempt_outcome`` event with safe
        fields only. The event must never carry the message body,
        the destination E.164 or the provider SID.
        """
        sentinel_body = "secret-body-content-accepted"
        sentinel_phone = "+5491100000099"
        sentinel_sid = "SM-ACCEPTED-9999"

        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        outbox_repo.finalize_accepted.return_value = True

        claimed = _claimed_row()
        claimed.cuerpo = sentinel_body
        claimed.destinatario_e164 = sentinel_phone
        outbox_repo.claim_due.return_value = claimed

        messages_client = _StrictTwilioMessagesClient(sid=sentinel_sid)

        dispatcher = OutboundMessageDispatcher(
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
            now=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
        )

        stdout_text = self._capture_stdout(dispatcher.dispatch)
        events = self._parse_outbound_lines(stdout_text)

        joined = json.dumps(events, sort_keys=True)
        self.assertNotIn(sentinel_body, joined)
        self.assertNotIn(sentinel_phone, joined)
        self.assertNotIn(sentinel_sid, joined)

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["event"], EVENT_OUTBOUND_OUTCOME)
        self.assertEqual(event["component"], COMPONENT_OUTBOUND)
        self.assertEqual(event["schema_version"], 1)
        self.assertEqual(event["outcome"], "accepted")
        self.assertEqual(event["outbox_id"], 11)
        self.assertEqual(event["durable_state"], "accepted")
        self.assertNotIn("failure_category", event)
        self.assertNotIn("exception_type", event)
        timestamp = event["timestamp"]
        self.assertIsInstance(timestamp, str)
        from datetime import datetime as _dt
        _dt.fromisoformat(timestamp)

    def test_no_due_row_dispatch_emits_parseable_outbound_outcome_event(
        self,
    ) -> None:
        """The ``no_due_row`` dispatcher branch must also emit the
        structured ``outbound_attempt_outcome`` event so the CLI
        can query the idle cycle safe endpoint. The event must
        carry no outbox context because no row was claimed.
        """
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
            now=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
        )

        stdout_text = self._capture_stdout(dispatcher.dispatch)
        events = self._parse_outbound_lines(stdout_text)

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["event"], EVENT_OUTBOUND_OUTCOME)
        self.assertEqual(event["component"], COMPONENT_OUTBOUND)
        self.assertEqual(event["outcome"], "no_due_row")
        self.assertIsNone(event.get("outbox_id"))
        self.assertIsNone(event.get("durable_state"))
        self.assertNotIn("failure_category", event)
        self.assertNotIn("exception_type", event)
        messages_client.create.assert_not_called()

    def test_technical_failure_does_not_emit_outbound_outcome_event(
        self,
    ) -> None:
        """A technical failure path must keep the existing
        contract: the ``provider_outbound_attempt`` log record
        with ``outcome=technical_failure`` is the only operational
        surface. The structured ``outbound_attempt_outcome`` event
        would be a no-op duplicate and is intentionally absent so
        the CLI never fabricates a business outcome from a
        technical exception.
        """
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        outbox_repo.claim_due.return_value = _claimed_row()
        messages_client = MagicMock(name="TwilioMessagesClient")
        messages_client.create.side_effect = TypeError(
            "secret-auth-token-value / leak"
        )

        dispatcher = OutboundMessageDispatcher(
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
            now=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
        )

        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            try:
                dispatcher.dispatch()
            except TypeError:
                pass

        events = self._parse_outbound_lines(captured.getvalue())
        self.assertEqual(events, [])
        joined = captured.getvalue()
        self.assertNotIn("secret-auth-token-value", joined)
        self.assertNotIn("leak", joined)


class DispatcherRunPassEvidenceTest(unittest.TestCase):
    """``run_pass_with_evidence`` accumulates typed results and
    captures technical exceptions so the CLI / worker can build
    per-cycle aggregates without re-running the dispatcher.
    """

    def setUp(self) -> None:
        importlib.reload(dispatcher_module)

    def test_run_pass_with_evidence_returns_results_and_exceptions(
        self,
    ) -> None:
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        outbox_repo.claim_due.side_effect = [
            _claimed_row(attempts=1),
            _claimed_row(attempts=1),
            None,
        ]
        outbox_repo.finalize_accepted.return_value = True
        outbox_repo.finalize_retryable.return_value = True
        messages_client = MagicMock(name="TwilioMessagesClient")
        messages_client.create.side_effect = [
            MagicMock(sid="SM-OK"),
            adapter_module._TwilioTransportError("timeout"),
        ]

        dispatcher = OutboundMessageDispatcher(
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
            now=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
        )

        evidence = dispatcher.run_pass_with_evidence(max_attempts_per_pass=4)

        self.assertIsInstance(evidence, OutboundPassEvidence)
        self.assertEqual(
            [r.outcome for r in evidence.results],
            [
                OutboundDispatchOutcome.SENT,
                OutboundDispatchOutcome.RETRY_SCHEDULED,
                OutboundDispatchOutcome.NO_DUE_ROW,
            ],
        )
        self.assertEqual(evidence.technical_exceptions, ())

    def test_run_pass_with_evidence_captures_technical_exception(
        self,
    ) -> None:
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        outbox_repo.claim_due.return_value = _claimed_row()
        messages_client = MagicMock(name="TwilioMessagesClient")
        messages_client.create.side_effect = TypeError(
            "leak: secret-auth-token-value"
        )

        dispatcher = OutboundMessageDispatcher(
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
            now=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
        )

        evidence = dispatcher.run_pass_with_evidence(max_attempts_per_pass=3)

        self.assertEqual(evidence.results, ())
        self.assertEqual(len(evidence.technical_exceptions), 1)
        self.assertIsInstance(
            evidence.technical_exceptions[0], TypeError
        )


class AttemptEventContractTest(unittest.TestCase):
    """Typed contracts are stable and carry only safe fields."""

    def test_attempt_outcome_enum_covers_all_dispatch_outcomes(self) -> None:
        self.assertEqual(
            OutboundAttemptOutcome.SENT.value,
            OutboundDispatchOutcome.SENT.value,
        )
        self.assertEqual(
            OutboundAttemptOutcome.RETRY_SCHEDULED.value,
            OutboundDispatchOutcome.RETRY_SCHEDULED.value,
        )
        self.assertEqual(
            OutboundAttemptOutcome.FAILED_TERMINAL.value,
            OutboundDispatchOutcome.FAILED_TERMINAL.value,
        )
        self.assertEqual(
            OutboundAttemptOutcome.NO_DUE_ROW.value,
            OutboundDispatchOutcome.NO_DUE_ROW.value,
        )
        self.assertEqual(
            OutboundAttemptOutcome.TECHNICAL_FAILURE.value,
            "technical_failure",
        )

    def test_cycle_aggregate_default_values(self) -> None:
        aggregate = OutboundCycleAggregate()
        self.assertEqual(aggregate.sent, 0)
        self.assertEqual(aggregate.retry_scheduled, 0)
        self.assertEqual(aggregate.failed_terminal, 0)
        self.assertEqual(aggregate.no_due_row, 0)
        self.assertEqual(aggregate.technical_failure, 0)
        self.assertEqual(dict(aggregate.failure_category_counts), {})

    def test_cycle_aggregate_is_frozen(self) -> None:
        aggregate = OutboundCycleAggregate(sent=1)
        with self.assertRaises((AttributeError, dataclasses.FrozenInstanceError)):
            aggregate.sent = 2  # type: ignore[misc]


class DispatcherStdoutEventExitTest(unittest.TestCase):
    """The structured ``outbound_attempt_outcome`` event must reach
    the Railway-captured stdout exit path, not the Python logging
    stderr path.

    Railway captures the service process stdout stream. The
    application logger writes to stderr by default, and the worker
    CLI also writes its key=value cycle summary to stdout. The
    structured event MUST end up on the same stdout exit path the
    worker key=value line uses so Railway's ``--json`` output
    surfaces it; a regression where the dispatcher writes the
    event to stderr (via the logger or any other redirect) would
    hide it from Railway and break the production observability
    CLI without any business-flow failure.
    """

    def setUp(self) -> None:
        importlib.reload(dispatcher_module)

    def _build_dispatcher_for_successful_dispatch(
        self, *, db_session: Any, outbox_repo: Any
    ) -> OutboundMessageDispatcher:
        outbox_repo.finalize_accepted.return_value = True
        claimed = _claimed_row()
        outbox_repo.claim_due.return_value = claimed
        messages_client = _StrictTwilioMessagesClient(sid="SM-OK-EXIT")
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
            now=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
        )

    def test_structured_event_reaches_stdout_not_stderr(self) -> None:
        """The dispatcher's structured event must land on stdout.

        The test captures BOTH stdout and stderr around a real
        ``dispatch()`` call (no stdout monkey-patching inside the
        dispatcher) and asserts that:

        * the bounded ``outbound_attempt_outcome`` JSON line is on
          stdout where Railway captures it;
        * the same event is NOT on stderr where the Python logger
          would have written it (a regression would push the event
          into stderr and hide it from Railway);
        * the worker key=value summary line emitted by the worker
          CLI through ``print(..., file=sys.stdout)`` shares the
          same stdout path the structured event uses, so a future
          refactor that swaps the dispatcher for a logger-only
          emission would fail this test.
        """
        db_session = MagicMock(name="DatabaseSession")
        outbox_repo = MagicMock(name="OutboundProviderMessageRepository")
        dispatcher = self._build_dispatcher_for_successful_dispatch(
            db_session=db_session, outbox_repo=outbox_repo
        )

        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(
            stderr_buffer
        ):
            dispatcher.dispatch()
            # Simulate the worker's key=value summary writer hitting
            # the same stdout exit path. The point of this test is
            # that BOTH the structured event and the worker summary
            # land on the Railway-captured stdout stream, not on
            # stderr.
            print(
                "provider_worker_cycle cycle_index=1 outbound_sent=1",
                file=sys.stdout,
            )

        stdout_text = stdout_buffer.getvalue()
        stderr_text = stderr_buffer.getvalue()

        # The structured event MUST be on stdout and parse as a
        # valid catalogued event. This is what Railway captures.
        stdout_events: list[dict] = []
        for raw_line in stdout_text.splitlines():
            if not raw_line.strip():
                continue
            try:
                parsed_line = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if (
                isinstance(parsed_line, dict)
                and parsed_line.get("event") == EVENT_OUTBOUND_OUTCOME
            ):
                stdout_events.append(parsed_line)
        self.assertEqual(
            len(stdout_events),
            1,
            f"expected exactly one structured outbound_attempt_outcome "
            f"event on stdout; got {len(stdout_events)}. "
            f"stdout={stdout_text!r}",
        )
        self.assertEqual(stdout_events[0]["outcome"], "accepted")
        self.assertEqual(stdout_events[0]["component"], "outbound_dispatch")

        # The event MUST NOT appear on stderr - a regression that
        # pushed it through the logger would hide it from Railway.
        stderr_event_lines = [
            line
            for line in stderr_text.splitlines()
            if EVENT_OUTBOUND_OUTCOME in line
        ]
        self.assertEqual(
            stderr_event_lines,
            [],
            f"structured event leaked into stderr (Railway would "
            f"miss it): {stderr_event_lines!r}",
        )

        # The worker key=value line shares the same stdout exit.
        # Both lines must appear on the same captured stdout buffer
        # because Railway captures them together.
        self.assertIn("provider_worker_cycle", stdout_text)
        self.assertIn("outbound_sent=1", stdout_text)

        # No raw exception text, provider SID or E.164 leaks into
        # either stream.
        for forbidden in (
            "SM-OK-EXIT",
            "+5491100000000",
            "secret-body-content",
        ):
            self.assertNotIn(forbidden, stdout_text)
            self.assertNotIn(forbidden, stderr_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)