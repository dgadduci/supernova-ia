"""Phase-7.4 deferred inbound processing CLI focused tests.

Coverage:

1. The CLI builds the real ``ProviderInboundMessageCoordinator``
   with the project's real ``_SessionLocal`` factory, routed through
   four injectable seams.
2. The CLI forwards the operator-supplied bounded
   ``--max-items-per-pass`` argument so the bounded pass cannot
   starve.
3. The CLI renders only safe summaries: counts, work ids, attempt
   counts and safe failure category/code. It never prints the
   inbound body, the customer E.164, the Twilio signature, the
   account SID, the auth token or any raw exception message.
4. Missing settings or a coordinator exception fails non-zero
   without leaking credentials or provider payloads.
5. No automatic loop occurs in any test: the CLI is the only
   caller of the coordinator's ``claim_due_processing`` /
   ``process_lease`` pair; the test stub explicitly verifies the
   bounded pass exits when the claim phase reports no due row.
"""
from __future__ import annotations

import ast
import contextlib
import io
import unittest
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

from backend.cli.run_inbound_processing import (
    build_parser,
    main,
)
from backend.config.settings import Settings
from backend.services.provider_inbound_message_coordinator import (
    ProviderInboundProcessingOutcome,
    ProviderInboundProcessingResult,
)


def _settings() -> Settings:
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
        twilio_auth_token="secret-auth-token-value",
        twilio_account_sid="AC" + "0" * 32,
        twilio_webhook_base_url="https://example.test",
        twilio_outbound_sender_e164="+5491100000000",
        twilio_callback_status_url="https://example.test/cb",
        twilio_outbound_lease_seconds=30,
        twilio_outbound_initial_backoff_seconds=30,
        twilio_outbound_max_backoff_seconds=300,
        twilio_outbound_max_attempts=5,
    )


def _ok_results() -> tuple[ProviderInboundProcessingResult, ...]:
    return (
        ProviderInboundProcessingResult(
            outcome=ProviderInboundProcessingOutcome.PROCESSED,
            procesamiento_id=42,
            receipt_id=7,
            intentos=1,
            categoria=None,
            codigo=None,
            detalle=None,
        ),
    )


def _retry_results() -> tuple[ProviderInboundProcessingResult, ...]:
    from backend.models.procesamiento_mensaje_proveedor import (
        ProcesamientoMensajeProveedorFailureCategory,
    )

    return (
        ProviderInboundProcessingResult(
            outcome=ProviderInboundProcessingOutcome.RETRY_SCHEDULED,
            procesamiento_id=11,
            receipt_id=7,
            intentos=2,
            categoria=ProcesamientoMensajeProveedorFailureCategory.PIPELINE_ERROR,
            codigo="pipeline_error",
            detalle=None,
        ),
    )


def _failure_results() -> tuple[ProviderInboundProcessingResult, ...]:
    from backend.models.procesamiento_mensaje_proveedor import (
        ProcesamientoMensajeProveedorFailureCategory,
    )

    return (
        ProviderInboundProcessingResult(
            outcome=ProviderInboundProcessingOutcome.FAILED_TERMINAL,
            procesamiento_id=99,
            receipt_id=7,
            intentos=3,
            categoria=ProcesamientoMensajeProveedorFailureCategory.BUDGET_EXHAUSTED,
            codigo="budget_exhausted",
            detalle="budget_exhausted",
        ),
    )


class _CoordinatorCapture:
    """Capture of coordinator construction and claim/process calls.

    The stub mimics the real coordinator surface so the CLI is the
    only component in the test that owns transaction control.
    """

    def __init__(
        self,
        *,
        leases: Sequence[Any],
        results: Sequence[ProviderInboundProcessingResult],
    ) -> None:
        self.leases: list[Any] = list(leases)
        self.results: list[ProviderInboundProcessingResult] = list(
            results
        )
        self.factories: list[dict[str, Any]] = []
        self.claim_calls: list[dict[str, Any]] = []
        self.process_calls: list[dict[str, Any]] = []

    def factory(self, **kwargs: Any) -> MagicMock:
        self.factories.append(dict(kwargs))
        coordinator = MagicMock(
            name="ProviderInboundMessageCoordinator"
        )
        coordinator.claim_due_processing.side_effect = (
            self._claim_due
        )
        coordinator.process_lease.side_effect = self._process_lease
        return coordinator

    def _claim_due(self, *, now: datetime) -> Any:
        self.claim_calls.append({"now": now})
        if not self.leases:
            return None
        return self.leases.pop(0)

    def _process_lease(
        self,
        leased: Any,
    ) -> ProviderInboundProcessingResult:
        self.process_calls.append({"leased_id": int(leased.id)})
        if self.results:
            return self.results.pop(0)
        return ProviderInboundProcessingResult(
            outcome=ProviderInboundProcessingOutcome.PROCESSED,
            procesamiento_id=int(leased.id),
            receipt_id=None,
            intentos=1,
            categoria=None,
            codigo=None,
            detalle=None,
        )


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


class CliBuildsRealCoordinatorDependenciesTest(unittest.TestCase):
    """The CLI must build the real coordinator through injectable
    seams, wiring the project's real ``_SessionLocal`` factory.
    """

    def test_cli_builds_coordinator_with_session_factory_and_seam(
        self,
    ) -> None:
        leased = MagicMock(name="LeasedRow")
        leased.id = 1
        capture = _CoordinatorCapture(
            leases=[leased], results=_ok_results()
        )
        session_factory = MagicMock(name="SessionFactory")
        session_factory.return_value = MagicMock(name="Session")

        with _capture_stdout():
            exit_code = main(
                argv=["--max-items-per-pass", "1"],
                settings_loader=lambda: _settings(),
                session_factory_builder=lambda: session_factory,
                coordinator_builder=capture.factory,
            )

        self.assertEqual(exit_code, 0)
        # The CLI opens one short-lived session for the claim
        # transaction and another short-lived session for the
        # processing transaction; the factory is therefore invoked
        # twice per leased row.
        self.assertEqual(len(capture.factories), 2)
        factory_kwargs = capture.factories[0]
        self.assertIn("session", factory_kwargs)
        self.assertIn("settings", factory_kwargs)
        self.assertIn("now", factory_kwargs)
        self.assertIsInstance(
            factory_kwargs["settings"], Settings
        )

    def test_default_session_factory_builder_returns_real_session_local(
        self,
    ) -> None:
        leased = MagicMock(name="LeasedRow")
        leased.id = 1
        capture = _CoordinatorCapture(
            leases=[leased], results=_ok_results()
        )

        with _capture_stdout():
            exit_code = main(
                argv=["--max-items-per-pass", "1"],
                settings_loader=lambda: _settings(),
                coordinator_builder=capture.factory,
            )

        self.assertEqual(exit_code, 0)
        # The CLI opens one short-lived session for the claim
        # transaction and another for the processing transaction;
        # the factory is therefore invoked twice per leased row.
        self.assertEqual(len(capture.factories), 2)
        self.assertIsNotNone(capture.factories[0]["session"])


class CliPassesBoundedPerPassArgumentTest(unittest.TestCase):
    """The CLI must forward the bounded per-pass argument to the
    coordinator's claim/process loop.
    """

    def test_forwards_max_items_per_pass_argument(self) -> None:
        leased_one = MagicMock(name="LeasedRow1")
        leased_one.id = 1
        leased_two = MagicMock(name="LeasedRow2")
        leased_two.id = 2
        capture = _CoordinatorCapture(
            leases=[leased_one, leased_two], results=_ok_results()
        )

        def _factory(**kwargs: Any) -> MagicMock:
            return capture.factory(**kwargs)

        with _capture_stdout():
            exit_code = main(
                argv=["--max-items-per-pass", "2"],
                settings_loader=lambda: _settings(),
                session_factory_builder=lambda: MagicMock(
                    name="SessionFactory"
                ),
                coordinator_builder=_factory,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(capture.claim_calls), 2)
        self.assertEqual(len(capture.process_calls), 2)

    def test_default_max_items_per_pass_is_used_when_flag_omitted(
        self,
    ) -> None:
        leased = MagicMock(name="LeasedRow")
        leased.id = 1
        capture = _CoordinatorCapture(
            leases=[leased], results=_ok_results()
        )

        def _factory(**kwargs: Any) -> MagicMock:
            return capture.factory(**kwargs)

        with _capture_stdout():
            exit_code = main(
                argv=[],
                settings_loader=lambda: _settings(),
                session_factory_builder=lambda: MagicMock(
                    name="SessionFactory"
                ),
                coordinator_builder=_factory,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(capture.claim_calls), 1)


class CliExitsWhenNoDueRowTest(unittest.TestCase):
    """The CLI must exit as soon as ``claim_due_processing`` returns
    ``None`` (no due row); the bounded pass MUST NOT loop.
    """

    def test_no_due_row_exits_immediately(self) -> None:
        capture = _CoordinatorCapture(leases=[], results=[])

        def _factory(**kwargs: Any) -> MagicMock:
            return capture.factory(**kwargs)

        with _capture_stdout():
            exit_code = main(
                argv=["--max-items-per-pass", "5"],
                settings_loader=lambda: _settings(),
                session_factory_builder=lambda: MagicMock(
                    name="SessionFactory"
                ),
                coordinator_builder=_factory,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(capture.claim_calls), 1)
        self.assertEqual(len(capture.process_calls), 0)


class CliRejectsInvalidBoundTest(unittest.TestCase):
    def test_non_positive_bound_fails_with_exit_code_two(self) -> None:
        with _capture_stdout() as stdout, _capture_stderr() as stderr:
            with self.assertRaises(SystemExit) as ctx:
                main(
                    argv=["--max-items-per-pass", "0"],
                    settings_loader=lambda: _settings(),
                    session_factory_builder=lambda: MagicMock(
                        name="SessionFactory"
                    ),
                    coordinator_builder=lambda **_: MagicMock(
                        name="ProviderInboundMessageCoordinator"
                    ),
                )
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("--max-items-per-pass", stderr.getvalue())


class CliRendersSafeSummaryTest(unittest.TestCase):
    """The CLI must render only safe operational summaries."""

    def test_summary_contains_counts_and_ids_only(self) -> None:
        leased = MagicMock(name="LeasedRow")
        leased.id = 42
        capture = _CoordinatorCapture(
            leases=[leased], results=_ok_results()
        )

        def _factory(**kwargs: Any) -> MagicMock:
            return capture.factory(**kwargs)

        with _capture_stdout() as stdout:
            exit_code = main(
                argv=["--max-items-per-pass", "1"],
                settings_loader=lambda: _settings(),
                session_factory_builder=lambda: MagicMock(
                    name="SessionFactory"
                ),
                coordinator_builder=_factory,
            )

        self.assertEqual(exit_code, 0)
        rendered = stdout.getvalue()

        self.assertIn("procesamiento_id=42 outcome=processed", rendered)
        self.assertIn("processed=1", rendered)
        self.assertIn("retry_scheduled=0", rendered)
        self.assertIn("failed_terminal=0", rendered)
        self.assertIn("total=1", rendered)

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
        leased = MagicMock(name="LeasedRow")
        leased.id = 11
        capture = _CoordinatorCapture(
            leases=[leased], results=_retry_results()
        )

        def _factory(**kwargs: Any) -> MagicMock:
            return capture.factory(**kwargs)

        with _capture_stdout() as stdout:
            exit_code = main(
                argv=["--max-items-per-pass", "1"],
                settings_loader=lambda: _settings(),
                session_factory_builder=lambda: MagicMock(
                    name="SessionFactory"
                ),
                coordinator_builder=_factory,
            )

        self.assertEqual(exit_code, 0)
        rendered = stdout.getvalue()
        self.assertIn(
            "procesamiento_id=11 outcome=retry_scheduled", rendered
        )
        self.assertIn("categoria=pipeline_error", rendered)
        self.assertIn("codigo=pipeline_error", rendered)
        for token in (
            "secret-auth-token-value",
            "AC000000000000000000000000000000",
        ):
            self.assertNotIn(token, rendered)


class CliConfigurationFailureTest(unittest.TestCase):
    """Missing settings must fail non-zero without leaking
    credentials, the auth token or the account SID.
    """

    def test_settings_loader_failure_fails_with_exit_code_two(
        self,
    ) -> None:
        def _bad_loader() -> Settings:
            raise ValueError("malformed")

        with _capture_stdout() as stdout, _capture_stderr() as stderr:
            exit_code = main(
                argv=["--max-items-per-pass", "1"],
                settings_loader=_bad_loader,
                session_factory_builder=lambda: MagicMock(
                    name="SessionFactory"
                ),
                coordinator_builder=lambda **_: MagicMock(
                    name="ProviderInboundMessageCoordinator"
                ),
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn(
            "invalid_inbound_settings", stderr.getvalue()
        )
        self.assertNotIn("malformed", stderr.getvalue())
        self.assertNotIn(
            "secret-auth-token-value", stderr.getvalue()
        )


class CliProcessingFailureTest(unittest.TestCase):
    """A processing exception must fail non-zero without leaking
    credentials, the auth token, the account SID, the inbound body
    or any raw exception message.
    """

    def test_process_lease_raises_fails_with_exit_code_one(self) -> None:
        leased = MagicMock(name="LeasedRow")
        leased.id = 1

        def _raise_process(_leased: Any) -> Any:
            raise RuntimeError("forced failure with secret token")

        def _factory(**_kwargs: Any) -> MagicMock:
            coordinator = MagicMock(
                name="ProviderInboundMessageCoordinator"
            )
            coordinator.claim_due_processing.return_value = leased
            coordinator.process_lease.side_effect = _raise_process
            return coordinator

        with _capture_stdout() as stdout, _capture_stderr() as stderr:
            exit_code = main(
                argv=["--max-items-per-pass", "1"],
                settings_loader=lambda: _settings(),
                session_factory_builder=lambda: MagicMock(
                    name="SessionFactory"
                ),
                coordinator_builder=_factory,
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn(
            "inbound_processing_failed", stderr.getvalue()
        )
        for token in (
            "secret-auth-token-value",
            "AC000000000000000000000000000000",
            "forced failure with secret token",
        ):
            self.assertNotIn(token, stderr.getvalue())

    def test_failed_terminal_outcome_returns_exit_code_one(self) -> None:
        leased = MagicMock(name="LeasedRow")
        leased.id = 99
        capture = _CoordinatorCapture(
            leases=[leased], results=_failure_results()
        )

        def _factory(**kwargs: Any) -> MagicMock:
            return capture.factory(**kwargs)

        with _capture_stdout() as stdout:
            exit_code = main(
                argv=["--max-items-per-pass", "1"],
                settings_loader=lambda: _settings(),
                session_factory_builder=lambda: MagicMock(
                    name="SessionFactory"
                ),
                coordinator_builder=_factory,
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("failed_terminal=1", stdout.getvalue())


class CliDoesNotImportTwilioAtModuleLevelTest(unittest.TestCase):
    """The CLI module must not import the Twilio SDK at module
    level; the Twilio adapter seam is constructed only by the
    outbound dispatcher, never by this CLI.
    """

    def test_cli_does_not_import_twilio_at_module_level(self) -> None:
        from backend.cli import run_inbound_processing as cli

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
                any(
                    name == "twilio" or name.startswith("twilio.")
                    for name in names
                ),
                f"CLI module must not import Twilio SDK at module "
                f"level (found {names!r})",
            )


class CliParserTest(unittest.TestCase):
    def test_help_lists_bounded_flag(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        self.assertIn("--max-items-per-pass", help_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)