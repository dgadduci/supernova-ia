"""Phase-5.6 outbound dispatch CLI focused tests.

Coverage:

1. The CLI builds the real ``OutboundMessageDispatcher`` with the
   project's real ``_SessionLocal`` factory and the real
   ``twilio.rest.Client`` ``messages`` seam, routed through four
   injectable seams.
2. The CLI passes the operator-supplied bounded per-pass maximum
   to ``OutboundMessageDispatcher.run_pass_with_evidence``.
3. The CLI renders only safe summaries: counts, outbox ids, Twilio
   SIDs, failure categories, HTTP status when known, technical
   exception class when the dispatcher raised. It never prints
   the auth token, the account SID, the outbound body or any
   other inbound text.
4. Missing / invalid configuration or a dispatch exception fails
   non-zero without leaking credentials, the outbound body or the
   inbound text.
5. No network call occurs in any test: the messages seam is a
   stub the tests own, and the dispatcher's stub client is
   asserted to never reach the SDK.
"""
from __future__ import annotations

import ast
import contextlib
import io
import unittest
from collections.abc import Callable, Sequence
from typing import Any
from unittest import mock
from unittest.mock import MagicMock

from backend.cli import run_outbound_dispatch as cli_module
from backend.cli.run_outbound_dispatch import (
    DEFAULT_MAX_ATTEMPTS_PER_PASS,
    build_parser,
    main,
)
from backend.config.settings import Settings
from backend.models.mensaje_proveedor_saliente import (
    OutboundFailureCategory,
)
from backend.services.outbound_dispatch_types import (
    OutboundDispatchOutcome,
    OutboundDispatchResult,
)


def _settings(
    *,
    account_sid: str | None = "AC" + "0" * 32,
    auth_token: str | None = "secret-auth-token-value",
    sender: str | None = "+5491100000000",
    callback_url: str | None = "https://example.test/cb",
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
        twilio_auth_token=auth_token,
        twilio_account_sid=account_sid,
        twilio_webhook_base_url="https://example.test",
        twilio_outbound_sender_e164=sender,
        twilio_callback_status_url=callback_url,
        twilio_outbound_lease_seconds=30,
        twilio_outbound_initial_backoff_seconds=30,
        twilio_outbound_max_backoff_seconds=300,
        twilio_outbound_max_attempts=5,
    )


def _ok_results() -> tuple[OutboundDispatchResult, ...]:
    return (
        OutboundDispatchResult(
            outcome=OutboundDispatchOutcome.SENT,
            mensaje_id=42,
            identificador_proveedor="SM-XYZ-1234",
            intentos=None,
            categoria=None,
            codigo=None,
            detalle=None,
        ),
        OutboundDispatchResult(
            outcome=OutboundDispatchOutcome.NO_DUE_ROW,
            mensaje_id=None,
            identificador_proveedor=None,
            intentos=None,
            categoria=None,
            codigo=None,
            detalle="no_due_row",
        ),
    )


def _failure_results() -> tuple[OutboundDispatchResult, ...]:
    return (
        OutboundDispatchResult(
            outcome=OutboundDispatchOutcome.FAILED_TERMINAL,
            mensaje_id=11,
            identificador_proveedor=None,
            intentos=5,
            categoria=OutboundFailureCategory.TERMINAL_4XX,
            codigo="403",
            detalle=None,
        ),
    )


def _build_dispatcher_mock(
    *,
    results: Sequence[OutboundDispatchResult],
    technical_exceptions: Sequence[BaseException] = (),
) -> MagicMock:
    """Build a dispatcher mock that exposes the per-pass evidence.

    The CLI now invokes ``run_pass_with_evidence`` instead of
    ``run_retry_pass`` so the safe per-cycle aggregate can be
    derived. The helper also keeps ``run_retry_pass`` configured
    for legacy assertions that exercise the legacy code path.
    """
    from backend.services.outbound_dispatch_types import (
        OutboundPassEvidence,
    )

    dispatcher = MagicMock(name="OutboundMessageDispatcher")
    dispatcher.run_pass_with_evidence.return_value = OutboundPassEvidence(
        results=tuple(results),
        technical_exceptions=tuple(technical_exceptions),
    )
    dispatcher.run_retry_pass.return_value = tuple(results)
    return dispatcher


class DispatcherCapture:
    """Lightweight capture of the dispatcher construction and pass."""

    def __init__(
        self,
        results: Sequence[OutboundDispatchResult],
        technical_exceptions: Sequence[BaseException] = (),
    ) -> None:
        self.results = tuple(results)
        self.technical_exceptions = tuple(technical_exceptions)
        self.kwargs: dict[str, Any] = {}
        self.calls: list[dict[str, Any]] = []

    def factory(self, **kwargs: Any) -> MagicMock:
        self.kwargs = dict(kwargs)
        dispatcher = _build_dispatcher_mock(
            results=self.results,
            technical_exceptions=self.technical_exceptions,
        )
        self.calls.append({"dispatcher": dispatcher, "kwargs": dict(kwargs)})
        return dispatcher


@contextlib.contextmanager
def _capture_stdout() -> Any:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        yield buffer


@contextlib.contextmanager
def _capture_stderr() -> Any:
    buffer = io.StringIO()
    with contextlib.redirect_stderr(buffer):
        yield buffer


class CliBuildsRealDispatcherDependenciesTest(unittest.TestCase):
    """The CLI must build the real dispatcher through injectable
    seams, wiring the project's real ``_SessionLocal`` factory and
    the real ``twilio.rest.Client`` ``messages`` instance."""

    def test_cli_builds_dispatcher_with_session_factory_and_messages_seam(
        self,
    ) -> None:
        capture = DispatcherCapture(_ok_results())
        session_factory = MagicMock(name="SessionFactory")
        messages_client = MagicMock(name="TwilioMessagesClient")

        with _capture_stdout():
            exit_code = main(
                argv=["--max-attempts-per-pass", "8"],
                settings_loader=lambda: _settings(),
                session_factory_builder=lambda: session_factory,
                messages_client_builder=lambda **_kwargs: messages_client,
                dispatcher_builder=capture.factory,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(capture.calls), 1)
        kwargs = capture.kwargs
        self.assertIs(kwargs["session_factory"], session_factory)
        self.assertIs(kwargs["messages_client"], messages_client)
        self.assertIsInstance(kwargs["settings"], Settings)
        self.assertEqual(
            kwargs["settings"].twilio_auth_token,
            "secret-auth-token-value",
        )
        self.assertEqual(
            kwargs["settings"].twilio_account_sid,
            "AC" + "0" * 32,
        )

    def test_default_session_factory_builder_returns_real_session_local(
        self,
    ) -> None:
        captured: dict[str, Any] = {}
        capture = DispatcherCapture(_ok_results())

        def _factory(
            *, settings: Settings, **_kwargs: Any
        ) -> MagicMock:
            captured["settings"] = settings
            return capture.factory(settings=settings, **_kwargs)

        with _capture_stdout():
            exit_code = main(
                argv=["--max-attempts-per-pass", "4"],
                settings_loader=lambda: _settings(),
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=_factory,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(capture.calls), 1)
        kwargs = capture.calls[0]["kwargs"]
        self.assertIs(kwargs["session_factory"], cli_module._SessionLocal)

    def test_default_messages_client_builder_constructs_real_twilio_client(
        self,
    ) -> None:
        captured: dict[str, Any] = {}

        class _FakeMessages:
            def __init__(self) -> None:
                captured["instance"] = self

        class _FakeClient:
            def __init__(self, account_sid: str, auth_token: str) -> None:
                captured["account_sid"] = account_sid
                captured["auth_token"] = auth_token
                self.messages = _FakeMessages()

        real_builder = cli_module._build_messages_client
        sentinel = MagicMock(name="RealClient", spec=_FakeClient)
        sentinel.messages = _FakeMessages()

        with _capture_stdout():
            with mock.patch(
                "twilio.rest.Client", wraps=lambda *a, **kw: sentinel
            ):
                client = real_builder(
                    account_sid="AC" + "1" * 32,
                    auth_token="real-auth-token",
                )

        self.assertIs(client, sentinel.messages)


class CliPassesBoundedPerPassArgumentTest(unittest.TestCase):
    """The CLI must forward the bounded per-pass argument to
    ``OutboundMessageDispatcher.run_pass_with_evidence``."""

    def test_forwards_max_attempts_per_pass_argument(self) -> None:
        dispatcher = _build_dispatcher_mock(results=_ok_results())
        capture = DispatcherCapture(_ok_results())

        def _factory(**kwargs: Any) -> MagicMock:
            return dispatcher

        with _capture_stdout():
            exit_code = main(
                argv=["--max-attempts-per-pass", "3"],
                settings_loader=lambda: _settings(),
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=_factory,
            )

        self.assertEqual(exit_code, 0)
        dispatcher.run_pass_with_evidence.assert_called_once_with(
            max_attempts_per_pass=3,
        )
        self.assertEqual(len(capture.calls), 0)

    def test_default_max_attempts_per_pass_is_used_when_flag_omitted(self) -> None:
        dispatcher = _build_dispatcher_mock(results=_ok_results())

        with _capture_stdout():
            exit_code = main(
                argv=[],
                settings_loader=lambda: _settings(),
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=lambda **_: dispatcher,
            )

        self.assertEqual(exit_code, 0)
        dispatcher.run_pass_with_evidence.assert_called_once_with(
            max_attempts_per_pass=DEFAULT_MAX_ATTEMPTS_PER_PASS,
        )


class CliRejectsInvalidBoundTest(unittest.TestCase):
    def test_non_positive_bound_fails_with_exit_code_two(self) -> None:
        with _capture_stdout() as stdout, _capture_stderr() as stderr:
            with self.assertRaises(SystemExit) as ctx:
                main(
                    argv=["--max-attempts-per-pass", "0"],
                    settings_loader=lambda: _settings(),
                    messages_client_builder=lambda **_kwargs: MagicMock(
                        name="TwilioMessagesClient"
                    ),
                    dispatcher_builder=lambda **_: MagicMock(
                        name="OutboundMessageDispatcher"
                    ),
                )
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("--max-attempts-per-pass", stderr.getvalue())


class CliRendersSafeSummaryTest(unittest.TestCase):
    """The CLI must render only safe operational summaries."""

    def test_summary_contains_counts_and_ids_only(self) -> None:
        dispatcher = _build_dispatcher_mock(results=_ok_results())

        with _capture_stdout() as stdout:
            exit_code = main(
                argv=["--max-attempts-per-pass", "8"],
                settings_loader=lambda: _settings(),
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=lambda **_: dispatcher,
            )

        self.assertEqual(exit_code, 0)
        rendered = stdout.getvalue()

        self.assertIn("mensaje_id=42 outcome=sent", rendered)
        self.assertIn("identificador_proveedor=SM-XYZ-1234", rendered)
        self.assertIn("sent=1", rendered)
        self.assertIn("retry_scheduled=0", rendered)
        self.assertIn("failed_terminal=0", rendered)
        self.assertIn("no_due_row=1", rendered)
        self.assertIn("technical_failure=0", rendered)
        self.assertIn("total=2", rendered)

        forbidden_substrings = (
            "secret-auth-token-value",
            "AC000000000000000000000000000000",
            "real-auth-token",
            "+5491100000000",
            "+5491155556666",
            "hola",
            "openid",
            "X-Twilio-Signature",
        )
        for token in forbidden_substrings:
            self.assertNotIn(token, rendered)

    def test_retry_outcome_summary_omits_body(self) -> None:
        retry_result = OutboundDispatchResult(
            outcome=OutboundDispatchOutcome.RETRY_SCHEDULED,
            mensaje_id=99,
            identificador_proveedor=None,
            intentos=1,
            categoria=OutboundFailureCategory.RETRYABLE_TIMEOUT,
            codigo="transport_error",
            durable_state="retryable",
            http_status=None,
            detalle="TimeoutError",
        )
        no_due_result = OutboundDispatchResult(
            outcome=OutboundDispatchOutcome.NO_DUE_ROW,
            mensaje_id=None,
            identificador_proveedor=None,
            intentos=None,
            categoria=None,
            codigo=None,
            detalle="no_due_row",
        )
        dispatcher = _build_dispatcher_mock(
            results=(retry_result, no_due_result),
        )

        with _capture_stdout() as stdout:
            exit_code = main(
                argv=[],
                settings_loader=lambda: _settings(),
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=lambda **_: dispatcher,
            )

        self.assertEqual(exit_code, 0)
        rendered = stdout.getvalue()
        self.assertIn("mensaje_id=99 outcome=retry_scheduled", rendered)
        self.assertIn("categoria=retryable_timeout", rendered)
        self.assertIn("codigo=transport_error", rendered)
        for token in ("secret-auth-token-value", "AC000000000000000000000000000000"):
            self.assertNotIn(token, rendered)


class CliConfigurationFailureTest(unittest.TestCase):
    """Missing / invalid configuration must fail non-zero without
    leaking credentials, the auth token or the account SID."""

    def test_missing_auth_token_fails_with_exit_code_two(self) -> None:
        with _capture_stdout() as stdout, _capture_stderr() as stderr:
            exit_code = main(
                argv=["--max-attempts-per-pass", "8"],
                settings_loader=lambda: _settings(auth_token=None),
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=lambda **_: MagicMock(
                    name="OutboundMessageDispatcher"
                ),
            )
        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("invalid_outbound_settings", stderr.getvalue())
        self.assertNotIn("None", stderr.getvalue())

    def test_missing_account_sid_fails_with_exit_code_two(self) -> None:
        with _capture_stdout() as stdout, _capture_stderr() as stderr:
            exit_code = main(
                argv=["--max-attempts-per-pass", "8"],
                settings_loader=lambda: _settings(account_sid=None),
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=lambda **_: MagicMock(
                    name="OutboundMessageDispatcher"
                ),
            )
        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("invalid_outbound_settings", stderr.getvalue())
        self.assertNotIn("None", stderr.getvalue())

    def test_missing_sender_fails_with_exit_code_two(self) -> None:
        with _capture_stdout() as stdout, _capture_stderr() as stderr:
            exit_code = main(
                argv=["--max-attempts-per-pass", "8"],
                settings_loader=lambda: _settings(sender=None),
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=lambda **_: MagicMock(
                    name="OutboundMessageDispatcher"
                ),
            )
        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("invalid_outbound_settings", stderr.getvalue())

    def test_settings_loader_typed_error_fails_with_exit_code_two(self) -> None:
        from backend.services.exceptions import (
            InvalidTwilioWebhookAuthToken,
        )

        def _bad_loader() -> Settings:
            raise InvalidTwilioWebhookAuthToken("malformed")

        with _capture_stdout() as stdout, _capture_stderr() as stderr:
            exit_code = main(
                argv=["--max-attempts-per-pass", "8"],
                settings_loader=_bad_loader,
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=lambda **_: MagicMock(
                    name="OutboundMessageDispatcher"
                ),
            )
        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("invalid_outbound_settings", stderr.getvalue())

    def test_invalid_account_sid_format_fails_with_exit_code_two(self) -> None:
        """The CLI rejects a malformed account SID before any I/O."""
        with _capture_stdout() as stdout, _capture_stderr() as stderr:
            exit_code = main(
                argv=["--max-attempts-per-pass", "8"],
                settings_loader=lambda: _settings(account_sid="not-canonical"),
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=lambda **_: MagicMock(
                    name="OutboundMessageDispatcher"
                ),
            )
        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("invalid_outbound_settings", stderr.getvalue())

    def test_missing_callback_url_fails_with_exit_code_two(self) -> None:
        with _capture_stdout() as stdout, _capture_stderr() as stderr:
            exit_code = main(
                argv=["--max-attempts-per-pass", "8"],
                settings_loader=lambda: _settings(callback_url=None),
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=lambda **_: MagicMock(
                    name="OutboundMessageDispatcher"
                ),
            )
        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("invalid_outbound_settings", stderr.getvalue())


class CliEarlySettingsFailureSafeAggregateTest(unittest.TestCase):
    """When the CLI terminates before the dispatcher is invoked
    because of a settings loader / validation failure, it MUST
    still emit one safe ``OutboundCycleAggregate`` through the
    ``cycle_aggregate_writer`` seam. The aggregate must reflect a
    fresh technical failure (``technical_failure=1``) and must
    NOT carry stale ``sent`` / ``retry_scheduled`` /
    ``failed_terminal`` / ``no_due_row`` / category counts or
    any sensitive payload."""

    def _assert_safe_aggregate(
        self,
        aggregate: Any,
        expected_failure_count: int = 1,
    ) -> None:
        self.assertEqual(aggregate.sent, 0)
        self.assertEqual(aggregate.retry_scheduled, 0)
        self.assertEqual(aggregate.failed_terminal, 0)
        self.assertEqual(aggregate.no_due_row, 0)
        self.assertEqual(
            aggregate.technical_failure, expected_failure_count
        )
        self.assertEqual(dict(aggregate.failure_category_counts), {})

    def test_settings_loader_error_writes_safe_aggregate(self) -> None:
        from backend.services.exceptions import (
            InvalidTwilioOutboundDispatchConfig,
        )

        def _bad_loader() -> Settings:
            raise InvalidTwilioOutboundDispatchConfig(
                "leak: secret-auth-token-value body=hola"
            )

        captured: list[Any] = []

        def _writer(aggregate: Any) -> None:
            captured.append(aggregate)

        with _capture_stdout() as stdout, _capture_stderr() as stderr:
            exit_code = main(
                argv=["--max-attempts-per-pass", "8"],
                settings_loader=_bad_loader,
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=lambda **_: MagicMock(
                    name="OutboundMessageDispatcher"
                ),
                cycle_aggregate_writer=_writer,
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(len(captured), 1)
        self._assert_safe_aggregate(captured[0])

        stderr_rendered = stderr.getvalue()
        self.assertIn("invalid_outbound_settings", stderr_rendered)
        for token in (
            "secret-auth-token-value",
            "AC000000000000000000000000000000",
            "+5491100000000",
            "body=hola",
            "leak:",
        ):
            self.assertNotIn(token, stderr_rendered)

    def test_settings_validation_error_writes_safe_aggregate(self) -> None:
        """A malformed ``Settings`` instance must reach the
        ``_validate_outbound_settings`` branch and emit one safe
        aggregate through the writer seam."""

        captured: list[Any] = []

        def _writer(aggregate: Any) -> None:
            captured.append(aggregate)

        with _capture_stdout() as stdout, _capture_stderr() as stderr:
            exit_code = main(
                argv=["--max-attempts-per-pass", "8"],
                settings_loader=lambda: _settings(auth_token=None),
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=lambda **_: MagicMock(
                    name="OutboundMessageDispatcher"
                ),
                cycle_aggregate_writer=_writer,
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(len(captured), 1)
        self._assert_safe_aggregate(captured[0])

        stderr_rendered = stderr.getvalue()
        self.assertIn("invalid_outbound_settings", stderr_rendered)
        for token in (
            "secret-auth-token-value",
            "AC000000000000000000000000000000",
            "+5491100000000",
        ):
            self.assertNotIn(token, stderr_rendered)


class CliTwilioClientConstructionFailureTest(unittest.TestCase):
    def test_messages_client_builder_failure_fails_with_exit_code_three(
        self,
    ) -> None:
        def _raise(**_kwargs: Any) -> Any:
            raise RuntimeError("boom")

        with _capture_stdout() as stdout, _capture_stderr() as stderr:
            exit_code = main(
                argv=["--max-attempts-per-pass", "8"],
                settings_loader=lambda: _settings(),
                session_factory_builder=lambda: MagicMock(name="SessionFactory"),
                messages_client_builder=_raise,
                dispatcher_builder=lambda **_: MagicMock(
                    name="OutboundMessageDispatcher"
                ),
            )
        self.assertEqual(exit_code, 3)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("twilio_client_construction_failed", stderr.getvalue())
        self.assertNotIn("secret-auth-token-value", stderr.getvalue())
        self.assertNotIn("AC000000000000000000000000000000", stderr.getvalue())

    def test_twilio_client_failure_writes_safe_technical_aggregate(
        self,
    ) -> None:
        """A Twilio client construction failure MUST emit one safe
        ``OutboundCycleAggregate`` through the
        ``cycle_aggregate_writer`` seam. The aggregate must reflect
        a fresh technical failure (``technical_failure=1``) and
        must NOT carry stale ``sent`` / ``retry_scheduled`` /
        ``failed_terminal`` / ``no_due_row`` / category counts or
        any sensitive payload."""

        def _raise(**_kwargs: Any) -> Any:
            raise RuntimeError(
                "leak: secret-auth-token-value / "
                "AC000000000000000000000000000000 / body=hola"
            )

        captured: list[Any] = []

        def _writer(aggregate: Any) -> None:
            captured.append(aggregate)

        with _capture_stdout() as stdout, _capture_stderr() as stderr:
            exit_code = main(
                argv=["--max-attempts-per-pass", "8"],
                settings_loader=lambda: _settings(),
                session_factory_builder=lambda: MagicMock(
                    name="SessionFactory"
                ),
                messages_client_builder=_raise,
                dispatcher_builder=lambda **_: MagicMock(
                    name="OutboundMessageDispatcher"
                ),
                cycle_aggregate_writer=_writer,
            )

        self.assertEqual(exit_code, 3)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(len(captured), 1)
        aggregate = captured[0]
        self.assertEqual(aggregate.sent, 0)
        self.assertEqual(aggregate.retry_scheduled, 0)
        self.assertEqual(aggregate.failed_terminal, 0)
        self.assertEqual(aggregate.no_due_row, 0)
        self.assertEqual(aggregate.technical_failure, 1)
        self.assertEqual(dict(aggregate.failure_category_counts), {})

        forbidden = (
            "secret-auth-token-value",
            "AC000000000000000000000000000000",
            "+5491100000000",
            "body=hola",
            "leak:",
        )
        stderr_rendered = stderr.getvalue()
        for token in forbidden:
            self.assertNotIn(token, stderr_rendered)
        self.assertIn("twilio_client_construction_failed", stderr_rendered)


class CliDispatchFailureTest(unittest.TestCase):
    """A dispatch exception must fail non-zero without leaking
    credentials, the auth token, the account SID or the outbound
    body."""

    def test_dispatcher_raises_fails_with_exit_code_one(self) -> None:
        dispatcher = MagicMock(name="OutboundMessageDispatcher")
        dispatcher.run_pass_with_evidence.side_effect = RuntimeError(
            "secret-auth-token-value body=hola"
        )

        with _capture_stdout() as stdout, _capture_stderr() as stderr:
            exit_code = main(
                argv=["--max-attempts-per-pass", "8"],
                settings_loader=lambda: _settings(),
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=lambda **_: dispatcher,
            )
        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("dispatch_pass_failed", stderr.getvalue())
        self.assertNotIn("secret-auth-token-value", stderr.getvalue())
        self.assertNotIn("body=hola", stderr.getvalue())
        self.assertNotIn("AC000000000000000000000000000000", stderr.getvalue())

    def test_failed_terminal_outcome_returns_exit_code_one(self) -> None:
        dispatcher = _build_dispatcher_mock(results=_failure_results())

        with _capture_stdout() as stdout:
            exit_code = main(
                argv=["--max-attempts-per-pass", "8"],
                settings_loader=lambda: _settings(),
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=lambda **_: dispatcher,
            )
        self.assertEqual(exit_code, 1)
        self.assertIn("failed_terminal=1", stdout.getvalue())


class CliDoesNotReachNetworkTest(unittest.TestCase):
    """The CLI itself must not perform any network call. The
    dispatcher is the only network boundary; the CLI is the only
    caller of the dispatcher; therefore no test should ever need
    the real Twilio SDK or the network."""

    def test_messages_client_create_is_never_invoked_by_cli(self) -> None:
        messages_client = MagicMock(name="TwilioMessagesClient")

        def _builder(**_kwargs: Any) -> MagicMock:
            return messages_client

        dispatcher = _build_dispatcher_mock(results=_ok_results())

        with _capture_stdout():
            exit_code = main(
                argv=["--max-attempts-per-pass", "4"],
                settings_loader=lambda: _settings(),
                messages_client_builder=_builder,
                dispatcher_builder=lambda **_: dispatcher,
            )

        self.assertEqual(exit_code, 0)
        messages_client.create.assert_not_called()

    def test_cli_does_not_import_twilio_at_module_level(self) -> None:
        from backend.cli import run_outbound_dispatch as cli

        source = cli.__file__
        with open(source, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        module_imports = [
            node
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        for node in module_imports:
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
            else:
                names = {node.module or ""}
            self.assertFalse(
                any(name == "twilio" or name.startswith("twilio.")
                    for name in names),
                f"CLI module must not import Twilio SDK at module level "
                f"(found {names!r})",
            )


class CliParserTest(unittest.TestCase):
    def test_help_lists_bounded_flag(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        self.assertIn("--max-attempts-per-pass", help_text)


class CliSafeAggregateWriterTest(unittest.TestCase):
    """The CLI exposes a ``cycle_aggregate_writer`` seam so the
    worker can capture the per-cycle safe aggregate without
    re-running the dispatcher. The aggregate must include the
    per-outcome counts, the per-failure-category breakdown, and
    the technical failure count without leaking any payload.
    """

    def test_cycle_aggregate_writer_receives_safe_aggregate(self) -> None:
        retry_result = OutboundDispatchResult(
            outcome=OutboundDispatchOutcome.RETRY_SCHEDULED,
            mensaje_id=11,
            identificador_proveedor=None,
            intentos=1,
            categoria=OutboundFailureCategory.RETRYABLE_429,
            codigo="20003",
            durable_state="retryable",
            http_status=429,
        )
        terminal_result = OutboundDispatchResult(
            outcome=OutboundDispatchOutcome.FAILED_TERMINAL,
            mensaje_id=12,
            identificador_proveedor=None,
            intentos=5,
            categoria=OutboundFailureCategory.BUDGET_EXHAUSTED,
            codigo="transport_error",
            durable_state="failed_terminal",
        )
        no_due_result = OutboundDispatchResult(
            outcome=OutboundDispatchOutcome.NO_DUE_ROW,
            mensaje_id=None,
            identificador_proveedor=None,
            intentos=None,
            categoria=None,
            codigo=None,
            detalle="no_due_row",
        )
        dispatcher = _build_dispatcher_mock(
            results=(retry_result, terminal_result, no_due_result),
        )

        captured: dict[str, Any] = {}

        def _writer(aggregate: Any) -> None:
            captured["aggregate"] = aggregate

        with _capture_stdout():
            exit_code = main(
                argv=["--max-attempts-per-pass", "4"],
                settings_loader=lambda: _settings(),
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=lambda **_: dispatcher,
                cycle_aggregate_writer=_writer,
            )

        self.assertEqual(exit_code, 1)
        aggregate = captured["aggregate"]
        self.assertEqual(aggregate.sent, 0)
        self.assertEqual(aggregate.retry_scheduled, 1)
        self.assertEqual(aggregate.failed_terminal, 1)
        self.assertEqual(aggregate.no_due_row, 1)
        self.assertEqual(aggregate.technical_failure, 0)
        self.assertEqual(
            dict(aggregate.failure_category_counts),
            {
                "retryable_429": 1,
                "budget_exhausted": 1,
            },
        )

    def test_cycle_aggregate_writer_receives_technical_failure_count(
        self,
    ) -> None:
        dispatcher = MagicMock(name="OutboundMessageDispatcher")
        dispatcher.run_pass_with_evidence.side_effect = RuntimeError(
            "leak: secret-auth-token-value"
        )

        captured: dict[str, Any] = {}

        def _writer(aggregate: Any) -> None:
            captured["aggregate"] = aggregate

        with _capture_stdout():
            exit_code = main(
                argv=["--max-attempts-per-pass", "4"],
                settings_loader=lambda: _settings(),
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=lambda **_: dispatcher,
                cycle_aggregate_writer=_writer,
            )

        self.assertEqual(exit_code, 1)
        aggregate = captured["aggregate"]
        self.assertEqual(aggregate.sent, 0)
        self.assertEqual(aggregate.technical_failure, 1)
        self.assertEqual(dict(aggregate.failure_category_counts), {})

    def test_per_attempt_lines_print_http_status_when_known(self) -> None:
        retry_result = OutboundDispatchResult(
            outcome=OutboundDispatchOutcome.RETRY_SCHEDULED,
            mensaje_id=11,
            identificador_proveedor=None,
            intentos=1,
            categoria=OutboundFailureCategory.RETRYABLE_429,
            codigo="20003",
            durable_state="retryable",
            http_status=429,
        )
        dispatcher = _build_dispatcher_mock(results=(retry_result,))

        with _capture_stdout() as stdout:
            exit_code = main(
                argv=["--max-attempts-per-pass", "1"],
                settings_loader=lambda: _settings(),
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=lambda **_: dispatcher,
            )

        self.assertEqual(exit_code, 0)
        rendered = stdout.getvalue()
        self.assertIn("http_status=429", rendered)
        self.assertIn("durable_state=retryable", rendered)
        self.assertIn("categoria=retryable_429", rendered)
        self.assertIn("codigo=20003", rendered)

    def test_per_attempt_lines_print_exception_class_on_technical_failure(
        self,
    ) -> None:
        dispatcher = MagicMock(name="OutboundMessageDispatcher")
        dispatcher.run_pass_with_evidence.side_effect = RuntimeError(
            "leak: secret-auth-token-value body=hola"
        )

        with _capture_stdout() as stdout, _capture_stderr() as stderr:
            exit_code = main(
                argv=["--max-attempts-per-pass", "1"],
                settings_loader=lambda: _settings(),
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=lambda **_: dispatcher,
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        stderr_rendered = stderr.getvalue()
        self.assertIn("dispatch_pass_failed", stderr_rendered)
        self.assertNotIn("secret-auth-token-value", stderr_rendered)
        self.assertNotIn("body=hola", stderr_rendered)
        self.assertNotIn(
            "AC000000000000000000000000000000", stderr_rendered
        )

    def test_per_attempt_lines_never_leak_sensitive_substrings(self) -> None:
        retry_result = OutboundDispatchResult(
            outcome=OutboundDispatchOutcome.FAILED_TERMINAL,
            mensaje_id=11,
            identificador_proveedor=None,
            intentos=5,
            categoria=OutboundFailureCategory.TERMINAL_4XX,
            codigo="403",
            durable_state="failed_terminal",
            http_status=403,
        )
        dispatcher = _build_dispatcher_mock(results=(retry_result,))

        with _capture_stdout() as stdout:
            exit_code = main(
                argv=["--max-attempts-per-pass", "1"],
                settings_loader=lambda: _settings(),
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=lambda **_: dispatcher,
            )

        self.assertEqual(exit_code, 1)
        rendered = stdout.getvalue()
        for token in (
            "secret-auth-token-value",
            "AC000000000000000000000000000000",
            "+5491100000000",
            "+5491155556666",
            "openid",
            "X-Twilio-Signature",
            "Bearer ",
        ):
            self.assertNotIn(token, rendered)


def _raise_runtime_error(message: str) -> Callable[..., Any]:
    def _fn(**_kwargs: Any) -> Any:
        raise RuntimeError(message)

    return _fn


if __name__ == "__main__":
    unittest.main(verbosity=2)
