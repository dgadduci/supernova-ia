"""Automatic provider-processing worker focused tests.

Coverage:

1. The disabled flag never launches a worker process; the manual
   inbound / outbound CLIs remain usable.
2. The worker always invokes inbound before outbound in every
   cycle, in the strict order documented in ``design.md``.
3. The worker forwards the configured inbound and outbound
   bounds to the existing CLI seams without rounding,
   truncation or multiplication.
4. ``no_due_row``, retryable and terminal results from the
   inbound or outbound CLI are normal cycle outcomes: the
   worker continues to the next cycle without altering lease
   / retry / ordering semantics.
5. Invalid enabled configuration fails the startup validation
   step before ``uvicorn`` accepts traffic. A silent fallback
   to the manual CLI operation is forbidden.
6. An unexpected worker exception reaches the supervisor path:
   the loop body re-raises the exception so the entrypoint can
   exit non-zero and Railway can restart the service.
7. Worker logs contain only safe metadata: counts, outcomes,
   duration, configured bounds. They MUST NOT contain
   inbound / outbound bodies, customer E.164 numbers, LLM
   content, provider signatures, account SIDs, auth tokens or
   environment dumps.
8. The existing inbound and outbound CLI tests remain green
   (regression coverage stays in
   ``test_run_inbound_processing_cli`` and
   ``test_run_outbound_dispatch_cli``).

The loop is driven entirely through injectable seams so the
focused tests never sleep, never spawn subprocesses, never open
a database session and never import ``twilio``.
"""
from __future__ import annotations

import contextlib
import io
import logging
import os
import subprocess
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from backend.cli import run_provider_processing_worker as worker_cli
from backend.cli.run_provider_processing_worker import (
    _build_cycle_summary,
    _validate_worker_settings,
    main,
    run_cycle,
    run_forever,
    validate_worker_startup_or_exit,
)
from backend.config.settings import (
    DEFAULT_PROVIDER_PROCESSING_WORKER_ENABLED,
    DEFAULT_PROVIDER_PROCESSING_WORKER_INBOUND_MAX_ITEMS_PER_PASS,
    DEFAULT_PROVIDER_PROCESSING_WORKER_OUTBOUND_MAX_ATTEMPTS_PER_PASS,
    DEFAULT_PROVIDER_PROCESSING_WORKER_POLL_INTERVAL_SECONDS,
    Settings,
    load_settings,
)
from backend.services.exceptions import (
    InvalidProviderProcessingWorkerConfig,
    InvalidTwilioOutboundDispatchConfig,
)

_ROOT = Path(__file__).resolve().parents[2]


def _settings(
    *,
    enabled: bool = True,
    poll_interval_seconds: int = 5,
    inbound_bound: int = 1,
    outbound_bound: int = 16,
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
        provider_processing_worker_enabled=enabled,
        provider_processing_worker_poll_interval_seconds=poll_interval_seconds,
        provider_processing_worker_inbound_max_items_per_pass=inbound_bound,
        provider_processing_worker_outbound_max_attempts_per_pass=outbound_bound,
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


class DisabledWorkerRetainsManualCliTest(unittest.TestCase):
    """The disabled flag must keep the manual inbound / outbound
    CLIs unchanged and never launch an automatic worker."""

    def test_main_returns_zero_when_disabled(self) -> None:
        exit_code = main(
            settings_loader=lambda: _settings(enabled=False),
        )
        self.assertEqual(exit_code, 0)

    def test_validate_worker_settings_accepts_disabled_with_any_bounds(
        self,
    ) -> None:
        _validate_worker_settings(_settings(enabled=False))

    def test_validate_worker_startup_or_exit_accepts_disabled_settings(
        self,
    ) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            validate_worker_startup_or_exit()

    def test_entrypoint_does_not_modify_behavior_when_disabled(
        self,
    ) -> None:
        script = _ROOT / "docker-entrypoint.sh"
        subprocess.run(["sh", "-n", str(script)], check=True)
        source = script.read_text()
        self.assertIn("PROVIDER_PROCESSING_WORKER_ENABLED", source)
        self.assertIn("validate_worker_startup_or_exit", source)
        self.assertIn("python -m backend.cli.run_provider_processing_worker", source)


class WorkerOrderingAndForwardingTest(unittest.TestCase):
    """The worker must invoke inbound before outbound in every
    cycle and forward the configured bounds exactly."""

    def test_inbound_runs_before_outbound_in_a_single_cycle(self) -> None:
        call_order: list[str] = []

        def _inbound(bound: int) -> int:
            call_order.append(f"inbound:{bound}")
            return 0

        def _outbound(bound: int) -> int:
            call_order.append(f"outbound:{bound}")
            return 0

        summaries: list[dict[str, Any]] = []

        def _writer(summary: dict[str, Any]) -> None:
            summaries.append(summary)

        summary = run_cycle(
            settings=_settings(inbound_bound=1, outbound_bound=16),
            cycle_index=1,
            inbound_runner=_inbound,
            outbound_runner=_outbound,
            sleep_decision=lambda _settings, _cycle: False,
            cycle_summary_writer=_writer,
        )

        self.assertEqual(call_order, ["inbound:1", "outbound:16"])
        self.assertEqual(summary["inbound_bound"], 1)
        self.assertEqual(summary["outbound_bound"], 16)
        self.assertEqual(summaries, [summary])

    def test_forwards_configured_bounds_to_each_runner(self) -> None:
        inbound_bounds: list[int] = []
        outbound_bounds: list[int] = []

        def _inbound(bound: int) -> int:
            inbound_bounds.append(bound)
            return 0

        def _outbound(bound: int) -> int:
            outbound_bounds.append(bound)
            return 0

        settings = _settings(inbound_bound=3, outbound_bound=42)

        def _stop_after_one() -> bool:
            return bool(inbound_bounds)

        cycle_count = run_forever(
            settings=settings,
            inbound_runner=_inbound,
            outbound_runner=_outbound,
            sleeper=lambda _seconds: None,
            sleep_decision=lambda _settings, _cycle: False,
            cycle_summary_writer=lambda _summary: None,
            stop_predicate=_stop_after_one,
        )

        self.assertEqual(cycle_count, 1)
        self.assertEqual(inbound_bounds, [3])
        self.assertEqual(outbound_bounds, [42])

    def test_loop_keeps_inbound_before_outbound_across_cycles(self) -> None:
        call_order: list[str] = []
        counter = {"cycles": 0}

        def _inbound(bound: int) -> int:
            call_order.append(f"inbound:{bound}")
            return 0

        def _outbound(bound: int) -> int:
            call_order.append(f"outbound:{bound}")
            counter["cycles"] += 1
            return 0

        run_forever(
            settings=_settings(inbound_bound=1, outbound_bound=16),
            inbound_runner=_inbound,
            outbound_runner=_outbound,
            sleeper=lambda _seconds: None,
            sleep_decision=lambda _settings, _cycle: False,
            cycle_summary_writer=lambda _summary: None,
            stop_predicate=lambda: counter["cycles"] >= 4,
        )

        self.assertEqual(
            call_order,
            [
                "inbound:1",
                "outbound:16",
                "inbound:1",
                "outbound:16",
                "inbound:1",
                "outbound:16",
                "inbound:1",
                "outbound:16",
            ],
        )


class WorkerContinuesOnBusinessOutcomesTest(unittest.TestCase):
    """``no_due_row``, retryable and terminal results must be
    normal cycle outcomes: the loop never stops, the worker
    never alters retry / lease state."""

    def test_no_due_row_outcomes_continue_to_next_cycle(self) -> None:
        inbound_calls = {"n": 0}
        outbound_calls = {"n": 0}

        def _inbound(_bound: int) -> int:
            inbound_calls["n"] += 1
            return 0

        def _outbound(_bound: int) -> int:
            outbound_calls["n"] += 1
            return 0

        cycle_count = run_forever(
            settings=_settings(),
            inbound_runner=_inbound,
            outbound_runner=_outbound,
            sleeper=lambda _seconds: None,
            sleep_decision=lambda _settings, _cycle: False,
            cycle_summary_writer=lambda _summary: None,
            stop_predicate=lambda: inbound_calls["n"] >= 5,
        )

        self.assertEqual(cycle_count, 5)
        self.assertEqual(inbound_calls["n"], 5)
        self.assertEqual(outbound_calls["n"], 5)

    def test_retryable_and_terminal_exit_codes_continue_loop(self) -> None:
        exit_codes = iter([0, 1, 1, 0, 1, 0])
        calls = {"n": 0}

        def _inbound(_bound: int) -> int:
            calls["n"] += 1
            return next(exit_codes)

        def _outbound(_bound: int) -> int:
            calls["n"] += 1
            return 0

        cycle_count = run_forever(
            settings=_settings(),
            inbound_runner=_inbound,
            outbound_runner=_outbound,
            sleeper=lambda _seconds: None,
            sleep_decision=lambda _settings, _cycle: False,
            cycle_summary_writer=lambda _summary: None,
            stop_predicate=lambda: calls["n"] >= 12,
        )

        self.assertGreater(cycle_count, 0)

    def test_summary_writer_records_exit_codes(self) -> None:
        inbound_codes = iter([0, 1, 0, 0, 0])
        outbound_codes = iter([1, 0, 0, 0, 0])
        captured: list[dict[str, Any]] = []

        def _inbound(_bound: int) -> int:
            return next(inbound_codes)

        def _outbound(_bound: int) -> int:
            return next(outbound_codes)

        def _writer(summary: dict[str, Any]) -> None:
            captured.append(summary)

        cycle_count = run_forever(
            settings=_settings(),
            inbound_runner=_inbound,
            outbound_runner=_outbound,
            sleeper=lambda _seconds: None,
            sleep_decision=lambda _settings, _cycle: False,
            cycle_summary_writer=_writer,
            stop_predicate=lambda: len(captured) >= 3,
        )

        self.assertEqual(cycle_count, 3)
        self.assertEqual(
            [s["inbound_exit_code"] for s in captured], [0, 1, 0]
        )
        self.assertEqual(
            [s["outbound_exit_code"] for s in captured], [1, 0, 0]
        )

    def test_sleeper_invoked_with_configured_poll_interval(self) -> None:
        sleeps: list[float] = []

        cycle_count = run_forever(
            settings=_settings(poll_interval_seconds=7),
            inbound_runner=lambda _bound: 0,
            outbound_runner=lambda _bound: 0,
            sleeper=lambda seconds: sleeps.append(float(seconds)),
            sleep_decision=lambda _settings, _cycle: True,
            cycle_summary_writer=lambda _summary: None,
            stop_predicate=lambda: len(sleeps) >= 3,
        )

        self.assertEqual(cycle_count, 3)
        self.assertEqual(sleeps, [7.0, 7.0, 7.0])

    def test_sleep_decision_false_skips_sleep(self) -> None:
        sleeps: list[float] = []
        calls = {"n": 0}

        def _stop_after_one() -> bool:
            return calls["n"] >= 2

        def _inbound(_bound: int) -> int:
            calls["n"] += 1
            return 0

        def _outbound(_bound: int) -> int:
            calls["n"] += 1
            return 0

        cycle_count = run_forever(
            settings=_settings(poll_interval_seconds=99),
            inbound_runner=_inbound,
            outbound_runner=_outbound,
            sleeper=lambda seconds: sleeps.append(float(seconds)),
            sleep_decision=lambda _settings, _cycle: False,
            cycle_summary_writer=lambda _summary: None,
            stop_predicate=_stop_after_one,
        )

        self.assertEqual(cycle_count, 1)
        self.assertEqual(sleeps, [])


class WorkerConfigValidationTest(unittest.TestCase):
    """Invalid enabled worker configuration must fail startup
    before ``uvicorn`` accepts traffic."""

    def test_non_positive_poll_interval_rejected_when_enabled(
        self,
    ) -> None:
        with self.assertRaises(InvalidProviderProcessingWorkerConfig):
            _validate_worker_settings(_settings(poll_interval_seconds=0))

    def test_non_positive_inbound_bound_rejected_when_enabled(self) -> None:
        with self.assertRaises(InvalidProviderProcessingWorkerConfig):
            _validate_worker_settings(_settings(inbound_bound=0))

    def test_non_positive_outbound_bound_rejected_when_enabled(self) -> None:
        with self.assertRaises(InvalidProviderProcessingWorkerConfig):
            _validate_worker_settings(_settings(outbound_bound=-1))

    def test_valid_enabled_settings_pass_validation(self) -> None:
        _validate_worker_settings(_settings())

    def test_startup_validation_fails_when_outbound_config_missing(
        self,
    ) -> None:
        with mock.patch.dict(
            os.environ,
            {"PROVIDER_PROCESSING_WORKER_ENABLED": "true"},
            clear=True,
        ):
            with self.assertRaises(
                InvalidTwilioOutboundDispatchConfig
            ):
                validate_worker_startup_or_exit()

    def test_startup_validation_passes_when_enabled_with_valid_outbound(
        self,
    ) -> None:
        env = {
            "PROVIDER_PROCESSING_WORKER_ENABLED": "true",
            "TWILIO_AUTH_TOKEN": "secret-auth-token-value",
            "TWILIO_ACCOUNT_SID": "AC" + "0" * 32,
            "TWILIO_OUTBOUND_SENDER_E164": "+5491100000000",
            "TWILIO_CALLBACK_STATUS_URL": "https://example.test/cb",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            validate_worker_startup_or_exit()

    def test_main_enabled_with_invalid_outbound_fails_before_loop(
        self,
    ) -> None:
        """When the worker is enabled, ``main()`` must run the
        existing outbound validation BEFORE invoking the inbound
        or outbound runner. The CLI cannot rely exclusively on the
        entrypoint supervisor."""
        inbound_calls = {"n": 0}
        outbound_calls = {"n": 0}

        def _inbound(_bound: int) -> int:
            inbound_calls["n"] += 1
            return 0

        def _outbound(_bound: int) -> int:
            outbound_calls["n"] += 1
            return 0

        def _loader() -> Settings:
            return _settings(enabled=True, auth_token=None)

        with self.assertRaises(InvalidTwilioOutboundDispatchConfig):
            main(
                settings_loader=_loader,
                inbound_runner=_inbound,
                outbound_runner=_outbound,
            )

        self.assertEqual(inbound_calls["n"], 0)
        self.assertEqual(outbound_calls["n"], 0)

    def test_main_enabled_with_valid_outbound_runs_loop(self) -> None:
        """When the worker is enabled and outbound settings are
        valid, ``main()`` proceeds to the loop and respects the
        injectable ``stop_predicate`` so it returns without
        spawning real sleeps or processes."""
        inbound_calls = {"n": 0}
        outbound_calls = {"n": 0}

        def _inbound(_bound: int) -> int:
            inbound_calls["n"] += 1
            return 0

        def _outbound(_bound: int) -> int:
            outbound_calls["n"] += 1
            return 0

        def _loader() -> Settings:
            return _settings(enabled=True)

        cycles = main(
            settings_loader=_loader,
            inbound_runner=_inbound,
            outbound_runner=_outbound,
            sleeper=lambda _seconds: None,
            sleep_decision=lambda _settings, _cycle: False,
            stop_predicate=lambda: (
                inbound_calls["n"] >= 1 and outbound_calls["n"] >= 1
            ),
        )

        self.assertEqual(cycles, 1)
        self.assertEqual(inbound_calls["n"], 1)
        self.assertEqual(outbound_calls["n"], 1)


class WorkerUnexpectedExceptionTest(unittest.TestCase):
    """An unexpected exception inside the loop body MUST reach
    the supervisor path: it is logged safely with the exception
    class name only and re-raised so the entrypoint can exit
    non-zero."""

    def test_unexpected_inbound_exception_reaches_supervisor(self) -> None:
        logged: list[dict[str, Any]] = []

        def _log(*args: Any, **kwargs: Any) -> None:
            logged.append({"args": args, "kwargs": kwargs})

        def _inbound(_bound: int) -> int:
            raise RuntimeError("forced inbound failure")

        def _outbound(_bound: int) -> int:
            return 0

        with self.assertRaises(RuntimeError):
            run_forever(
                settings=_settings(),
                inbound_runner=_inbound,
                outbound_runner=_outbound,
                sleeper=lambda _seconds: None,
                sleep_decision=lambda _settings, _cycle: False,
                cycle_summary_writer=lambda _summary: None,
                stop_predicate=lambda: False,
                unexpected_exception_log=_log,
            )

        self.assertEqual(len(logged), 1)
        kwargs = logged[0]["kwargs"]
        self.assertEqual(kwargs["cycle_index"], 1)
        self.assertEqual(kwargs["reason"], "RuntimeError")

    def test_unexpected_outbound_exception_reaches_supervisor(self) -> None:
        def _inbound(_bound: int) -> int:
            return 0

        def _outbound(_bound: int) -> int:
            raise ValueError("forced outbound failure")

        with self.assertRaises(ValueError):
            run_cycle(
                settings=_settings(),
                cycle_index=2,
                inbound_runner=_inbound,
                outbound_runner=_outbound,
                sleep_decision=lambda _settings, _cycle: False,
                cycle_summary_writer=lambda _summary: None,
            )

    def test_unexpected_writer_exception_reaches_supervisor(self) -> None:
        def _writer(_summary: dict[str, Any]) -> None:
            raise OSError("forced writer failure")

        with self.assertRaises(OSError):
            run_cycle(
                settings=_settings(),
                cycle_index=1,
                inbound_runner=lambda _bound: 0,
                outbound_runner=lambda _bound: 0,
                sleep_decision=lambda _settings, _cycle: False,
                cycle_summary_writer=_writer,
            )


class WorkerObservabilityIsSafeTest(unittest.TestCase):
    """Worker logs MUST contain only derived counts, outcomes,
    configured bounds and exit codes. They MUST NOT contain
    inbound / outbound bodies, customer E.164 numbers, LLM
    content, provider signatures, account SIDs, tokens or
    environment dumps."""

    _FORBIDDEN_SUBSTRINGS = (
        "secret-auth-token-value",
        "AC000000000000000000000000000000",
        "+5491100000000",
        "+5491155556666",
        "openid",
        "X-Twilio-Signature",
        "Bearer ",
        "inbound body",
        "outbound body",
        "prompt",
        "PROVIDER_PROCESSING_WORKER_ENABLED=true",
        "PROVIDER_PROCESSING_WORKER_POLL_INTERVAL_SECONDS",
    )

    def test_cycle_summary_writer_default_output_is_safe(self) -> None:
        settings = _settings(inbound_bound=1, outbound_bound=16)
        summary = _build_cycle_summary(
            cycle_index=1,
            inbound_exit_code=0,
            outbound_exit_code=1,
            settings=settings,
            sleep_after=True,
        )

        with _capture_stdout() as stdout:
            worker_cli._default_cycle_summary_writer(summary)

        rendered = stdout.getvalue()
        self.assertIn("provider_worker_cycle", rendered)
        self.assertIn("cycle_index=1", rendered)
        self.assertIn("inbound_exit_code=0", rendered)
        self.assertIn("outbound_exit_code=1", rendered)
        self.assertIn("inbound_bound=1", rendered)
        self.assertIn("outbound_bound=16", rendered)
        self.assertIn("poll_interval_seconds=5", rendered)

        for token in self._FORBIDDEN_SUBSTRINGS:
            self.assertNotIn(token, rendered)

    def test_loop_output_excludes_secrets_and_payloads(self) -> None:
        calls = {"n": 0}

        def _inbound(_bound: int) -> int:
            calls["n"] += 1
            return 0

        def _outbound(_bound: int) -> int:
            calls["n"] += 1
            return 0

        with _capture_stdout() as stdout:
            run_forever(
                settings=_settings(inbound_bound=1, outbound_bound=16),
                inbound_runner=_inbound,
                outbound_runner=_outbound,
                sleeper=lambda _seconds: None,
                sleep_decision=lambda _settings, _cycle: False,
                stop_predicate=lambda: calls["n"] >= 2,
            )

        rendered = stdout.getvalue()
        for token in self._FORBIDDEN_SUBSTRINGS:
            self.assertNotIn(token, rendered)

    def test_unexpected_exception_log_omits_message_and_secrets(
        self,
    ) -> None:
        sentinels = (
            "secret-auth-token-value",
            "AC000000000000000000000000000000",
            "+5491100000000",
            "+5491155556666",
            "https://provider.example",
            "X-Twilio-Signature",
            "Bearer ",
            "leak:",
            "inbound body",
            "outbound body",
            "prompt",
        )
        secret_message = (
            "leak: secret-auth-token-value / "
            "AC000000000000000000000000000000 / +5491100000000 / "
            "https://provider.example/cb?token=Bearer xyz / "
            "X-Twilio-Signature=abc / inbound body / outbound body / prompt"
        )
        secret_exc = RuntimeError(secret_message)

        with self.assertLogs(
            worker_cli.logger, level=logging.ERROR
        ) as log_ctx:
            worker_cli._default_unexpected_exception_log(
                cycle_index=4,
                reason="RuntimeError",
                exc=secret_exc,
            )

        self.assertEqual(len(log_ctx.records), 1)
        record = log_ctx.records[0]

        self.assertEqual(
            record.name, worker_cli.logger.name
        )
        self.assertEqual(record.levelno, logging.ERROR)
        self.assertEqual(
            record.getMessage(),
            "provider_processing_worker_unexpected_failure",
        )
        self.assertFalse(
            record.exc_info,
            "unexpected-exception log must not attach a traceback",
        )
        self.assertIsNone(getattr(record, "exc_text", None))
        self.assertEqual(
            getattr(record, "cycle_index", None), 4
        )
        self.assertEqual(getattr(record, "reason", None), "RuntimeError")

        for token in sentinels:
            self.assertNotIn(
                token,
                record.getMessage(),
                f"sentinel {token!r} leaked in record message",
            )
        for attr, value in record.__dict__.items():
            if isinstance(value, str):
                for token in sentinels:
                    self.assertNotIn(
                        token,
                        value,
                        (
                            f"sentinel {token!r} leaked in record "
                            f"attribute {attr!r}"
                        ),
                    )

    def test_unexpected_exception_log_uses_logger_error_no_exc_info(
        self,
    ) -> None:
        """The implementation must call ``logger.error`` (NOT
        ``logger.exception``) so the traceback of the unexpected
        failure never reaches the logging record."""
        with mock.patch.object(
            worker_cli.logger, "error"
        ) as error_mock, mock.patch.object(
            worker_cli.logger, "exception"
        ) as exception_mock:
            worker_cli._default_unexpected_exception_log(
                cycle_index=2,
                reason="ValueError",
                exc=ValueError("sentinel secret-auth-token-value"),
            )

        exception_mock.assert_not_called()
        self.assertEqual(error_mock.call_count, 1)
        call = error_mock.call_args
        self.assertEqual(
            call.args[0],
            "provider_processing_worker_unexpected_failure",
        )
        self.assertNotIn("exc_info", call.kwargs)
        extra = call.kwargs["extra"]
        self.assertEqual(extra["cycle_index"], 2)
        self.assertEqual(extra["reason"], "ValueError")


class WorkerDisabledDefaultLoadTest(unittest.TestCase):
    """Loading ``Settings`` with no overrides must keep the
    worker disabled and the manual CLIs unchanged."""

    def test_default_settings_disable_worker(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = load_settings()
        self.assertEqual(
            settings.provider_processing_worker_enabled,
            DEFAULT_PROVIDER_PROCESSING_WORKER_ENABLED,
        )
        self.assertFalse(settings.provider_processing_worker_enabled)
        self.assertEqual(
            settings.provider_processing_worker_poll_interval_seconds,
            DEFAULT_PROVIDER_PROCESSING_WORKER_POLL_INTERVAL_SECONDS,
        )
        self.assertEqual(
            settings.provider_processing_worker_inbound_max_items_per_pass,
            DEFAULT_PROVIDER_PROCESSING_WORKER_INBOUND_MAX_ITEMS_PER_PASS,
        )
        self.assertEqual(
            settings.provider_processing_worker_outbound_max_attempts_per_pass,
            DEFAULT_PROVIDER_PROCESSING_WORKER_OUTBOUND_MAX_ATTEMPTS_PER_PASS,
        )

    def test_non_positive_env_value_rejected_at_load(self) -> None:
        env = {
            "PROVIDER_PROCESSING_WORKER_ENABLED": "true",
            "PROVIDER_PROCESSING_WORKER_POLL_INTERVAL_SECONDS": "-1",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(InvalidProviderProcessingWorkerConfig):
                load_settings()

    def test_positive_env_values_are_accepted(self) -> None:
        env = {
            "PROVIDER_PROCESSING_WORKER_ENABLED": "true",
            "PROVIDER_PROCESSING_WORKER_POLL_INTERVAL_SECONDS": "10",
            "PROVIDER_PROCESSING_WORKER_INBOUND_MAX_ITEMS_PER_PASS": "2",
            "PROVIDER_PROCESSING_WORKER_OUTBOUND_MAX_ATTEMPTS_PER_PASS": "32",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertTrue(settings.provider_processing_worker_enabled)
        self.assertEqual(
            settings.provider_processing_worker_poll_interval_seconds, 10
        )
        self.assertEqual(
            settings.provider_processing_worker_inbound_max_items_per_pass, 2
        )
        self.assertEqual(
            settings.provider_processing_worker_outbound_max_attempts_per_pass,
            32,
        )


class WorkerEntrypointShellContractTest(unittest.TestCase):
    """The Railway entrypoint shell must remain syntactically
    valid and MUST NOT change disabled behavior."""

    def test_entrypoint_is_valid_shell(self) -> None:
        script = _ROOT / "docker-entrypoint.sh"
        subprocess.run(["sh", "-n", str(script)], check=True)

    def test_entrypoint_disabled_block_is_guarded_by_flag(self) -> None:
        source = (_ROOT / "docker-entrypoint.sh").read_text()
        self.assertIn(
            "PROVIDER_PROCESSING_WORKER_ENABLED",
            source,
        )
        self.assertIn(
            "validate_worker_startup_or_exit",
            source,
        )
        self.assertIn(
            "python -m backend.cli.run_provider_processing_worker",
            source,
        )
        self.assertIn(
            "startup_error provider_worker_configuration_invalid",
            source,
        )
        self.assertIn(
            "startup_error provider_worker_exited",
            source,
        )

    def test_entrypoint_preserves_existing_required_assertions(
        self,
    ) -> None:
        source = (_ROOT / "docker-entrypoint.sh").read_text()
        for token in (
            "--tun=userspace-networking",
            "--state=mem:",
            "--socks5-server=127.0.0.1:1055",
            "json.load(sys.stdin).get",
            "required_var OLLAMA_PROXY_URL",
        ):
            self.assertIn(token, source)
        for token in (
            "socket.create_connection",
            "HTTP_PROXY=",
            "HTTPS_PROXY=",
            "ALL_PROXY=",
        ):
            self.assertNotIn(token, source)


class WorkerDefaultsConstantsTest(unittest.TestCase):
    def test_worker_defaults_are_positive_and_disabled(self) -> None:
        self.assertFalse(DEFAULT_PROVIDER_PROCESSING_WORKER_ENABLED)
        self.assertGreater(
            DEFAULT_PROVIDER_PROCESSING_WORKER_POLL_INTERVAL_SECONDS, 0
        )
        self.assertGreater(
            DEFAULT_PROVIDER_PROCESSING_WORKER_INBOUND_MAX_ITEMS_PER_PASS, 0
        )
        self.assertGreater(
            DEFAULT_PROVIDER_PROCESSING_WORKER_OUTBOUND_MAX_ATTEMPTS_PER_PASS,
            0,
        )


class WorkerEntrypointFlagParsingTest(unittest.TestCase):
    """The Railway entrypoint must accept only the documented
    truthy and falsy values for ``PROVIDER_PROCESSING_WORKER_ENABLED``.
    Any other value must abort startup before tailscaled or
    uvicorn is launched and MUST NOT echo the offending value."""

    _TRUE_VALUES = ("1", "true", "TRUE", "yes", "YES", "on", "ON")
    _FALSE_VALUES = ("0", "false", "FALSE", "no", "NO", "off", "OFF")
    _INVALID_VALUES = (
        "tru",
        "maybe",
        "1true",
        "yesno",
        "enabled",
        "YES ",
        " yes",
    )

    def _case_source(self) -> str:
        """Return the verbatim case block from the entrypoint."""
        text = (_ROOT / "docker-entrypoint.sh").read_text()
        start = text.find("provider_worker_enabled=0")
        if start == -1:
            self.fail("Could not locate worker flag case block start")
        end = text.find("\nesac\n", start)
        if end == -1:
            self.fail("Could not locate end of worker flag case block")
        return text[start : end + len("\nesac")]

    def _run_case(
        self, env_value: str | None
    ) -> tuple[int, str, str]:
        case_block = self._case_source()
        if env_value is None:
            assignment = "unset PROVIDER_PROCESSING_WORKER_ENABLED"
        else:
            escaped = env_value.replace("'", "'\\''")
            assignment = f"PROVIDER_PROCESSING_WORKER_ENABLED='{escaped}'"
        script = (
            f"{assignment}\n{case_block}\n"
            "printf 'RESULT=%s\\n' \"$provider_worker_enabled\""
        )
        proc = subprocess.run(
            ["sh", "-c", script],
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_entrypoint_is_valid_shell(self) -> None:
        subprocess.run(
            ["sh", "-n", str(_ROOT / "docker-entrypoint.sh")], check=True
        )

    def test_each_true_value_enables_worker(self) -> None:
        for value in self._TRUE_VALUES:
            with self.subTest(value=value):
                rc, stdout, stderr = self._run_case(value)
                self.assertEqual(rc, 0, msg=stderr)
                self.assertEqual(stdout.strip(), "RESULT=1")

    def test_each_false_value_disables_worker(self) -> None:
        for value in self._FALSE_VALUES:
            with self.subTest(value=value):
                rc, stdout, stderr = self._run_case(value)
                self.assertEqual(rc, 0, msg=stderr)
                self.assertEqual(stdout.strip(), "RESULT=0")

    def test_unset_variable_disables_worker(self) -> None:
        rc, stdout, stderr = self._run_case(None)
        self.assertEqual(rc, 0, msg=stderr)
        self.assertEqual(stdout.strip(), "RESULT=0")

    def test_invalid_value_fails_before_any_startup(self) -> None:
        """An invalid flag value must abort the entrypoint with
        exit code 1 BEFORE tailscaled or uvicorn is launched, and
        MUST NOT echo the offending value."""
        required_env = {
            "PATH": os.environ.get("PATH", ""),
            "SUPERNOVA_DATABASE_URL": "postgresql://x/y",
            "TS_AUTHKEY": "test",
            "TS_HOSTNAME": "test",
            "OLLAMA_PROXY_URL": "http://x",
            "PORT": "8000",
        }
        for value in self._INVALID_VALUES:
            with self.subTest(value=value):
                local_env = dict(required_env)
                local_env["PROVIDER_PROCESSING_WORKER_ENABLED"] = value
                proc = subprocess.run(
                    ["sh", str(_ROOT / "docker-entrypoint.sh")],
                    capture_output=True,
                    text=True,
                    env=local_env,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(
                    proc.returncode,
                    1,
                    msg=(
                        f"expected exit 1 for {value!r}, got "
                        f"{proc.returncode}: stdout={proc.stdout!r} "
                        f"stderr={proc.stderr!r}"
                    ),
                )
                self.assertIn(
                    "startup_error provider_worker_invalid_flag",
                    proc.stderr,
                )
                trimmed = (proc.stdout + proc.stderr).strip()
                self.assertNotIn(
                    value, trimmed,
                    msg=(
                        f"offending value {value!r} leaked into "
                        f"entrypoint output"
                    ),
                )
                self.assertNotIn("tailscale_ready", proc.stdout)
                self.assertNotIn(
                    "provider_worker=enabled", proc.stdout
                )
                self.assertNotIn("uvicorn", proc.stdout)

    def test_invalid_empty_string_fails(self) -> None:
        """An explicitly set empty string is NOT equivalent to
        "unset": the operator made a mistake and the entrypoint
        must reject it rather than silently disable the worker."""
        rc, stdout, stderr = self._run_case("")
        self.assertEqual(rc, 1)
        self.assertIn(
            "startup_error provider_worker_invalid_flag", stderr
        )
        # The *) branch exits before the trailing printf runs, so
        # stdout is empty: the worker was NOT silently enabled.
        self.assertEqual(stdout.strip(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)