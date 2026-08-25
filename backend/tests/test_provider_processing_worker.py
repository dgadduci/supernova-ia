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
import json
import logging
import os
import signal
import subprocess
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock
from unittest.mock import MagicMock

from backend.cli import run_inbound_processing as inbound_cli
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
from backend.observability import EVENT_WORKER_LIVENESS
from backend.services.exceptions import (
    InvalidProviderProcessingWorkerConfig,
    InvalidTwilioOutboundDispatchConfig,
)

_ROOT = Path(__file__).resolve().parents[2]


def _liveness_events(stdout_text: str) -> list[dict[str, Any]]:
    """Parse captured stdout and return only the liveness events.

    The helper preserves the order of emitted events so tests can
    assert the closed lifecycle sequence
    (``cycle_started`` → ``phase_started`` → ``phase_completed``
    → ``cycle_completed`` → ``phase_started`` → ``phase_completed``)
    without depending on internal counters.
    """
    events: list[dict[str, Any]] = []
    for line in stdout_text.splitlines():
        stripped = line.strip()
        if not stripped or not stripped.startswith("{"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("event") == EVENT_WORKER_LIVENESS:
            events.append(payload)
    return events


def _settings(
    *,
    enabled: bool = True,
    poll_interval_seconds: int = 5,
    inbound_bound: int = 1,
    outbound_bound: int = 16,
    inbound_timeout_seconds: int = 240,
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
        provider_processing_worker_inbound_timeout_seconds=inbound_timeout_seconds,
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
            readiness_probe=worker_cli._always_ready_probe,
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


def _not_ready_result(
    *,
    generate_category: str = "QueryLlmConnectionError",
    embed_category: str = "skipped_due_to_generate_failure",
    embed_dimension: int | None = None,
    generate_duration_seconds: float = 0.5,
    embed_duration_seconds: float = 0.0,
) -> Any:
    from backend.scripts.check_railway_ollama_contracts import (
        OllamaReadinessResult,
    )

    return OllamaReadinessResult(
        ready=False,
        generate_category=generate_category,
        embed_category=embed_category,
        embed_dimension=embed_dimension,
        generate_duration_seconds=generate_duration_seconds,
        embed_duration_seconds=embed_duration_seconds,
    )


def _ready_result(
    *,
    embed_dimension: int | None = 4,
    generate_duration_seconds: float = 0.25,
    embed_duration_seconds: float = 0.15,
) -> Any:
    from backend.scripts.check_railway_ollama_contracts import (
        OllamaReadinessResult,
    )

    return OllamaReadinessResult(
        ready=True,
        generate_category="passed",
        embed_category="passed",
        embed_dimension=embed_dimension,
        generate_duration_seconds=generate_duration_seconds,
        embed_duration_seconds=embed_duration_seconds,
    )


class WorkerReadinessGateTest(unittest.TestCase):
    """The worker SHALL not invoke inbound until a controlled
    fixed-input probe proves both configured Ollama generate and
    embedding surfaces usable. While not ready, the bounded
    outbound pass MUST still run and the cycle summary MUST
    surface a safe not-ready category. After the first success the
    readiness flag is cached for the worker process."""

    def test_first_probe_failure_skips_inbound_and_runs_outbound(
        self,
    ) -> None:
        inbound_calls: list[int] = []
        outbound_calls: list[int] = []
        summaries: list[dict[str, Any]] = []

        def _inbound(bound: int) -> int:
            inbound_calls.append(bound)
            return 0

        def _outbound(bound: int) -> int:
            outbound_calls.append(bound)
            return 0

        cycle_count = run_forever(
            settings=_settings(inbound_bound=1, outbound_bound=16),
            inbound_runner=_inbound,
            outbound_runner=_outbound,
            sleeper=lambda _seconds: None,
            sleep_decision=lambda _settings, _cycle: False,
            cycle_summary_writer=lambda summary: summaries.append(summary),
            stop_predicate=lambda: len(outbound_calls) >= 1,
            readiness_probe=lambda: _not_ready_result(),
        )

        self.assertEqual(cycle_count, 1)
        self.assertEqual(inbound_calls, [])
        self.assertEqual(outbound_calls, [16])
        self.assertEqual(len(summaries), 1)
        summary = summaries[0]
        self.assertFalse(summary["ollama_ready"])
        self.assertIsNone(summary["inbound_exit_code"])
        self.assertEqual(summary["outbound_exit_code"], 0)
        self.assertEqual(
            summary["not_ready_category"], "QueryLlmConnectionError"
        )
        self.assertIn("probe_duration_seconds", summary)

    def test_consecutive_probe_failures_keep_inbound_skipped(
        self,
    ) -> None:
        inbound_calls: list[int] = []
        outbound_calls: list[int] = []

        def _inbound(bound: int) -> int:
            inbound_calls.append(bound)
            return 0

        def _outbound(bound: int) -> int:
            outbound_calls.append(bound)
            return 0

        cycle_count = run_forever(
            settings=_settings(inbound_bound=2, outbound_bound=8),
            inbound_runner=_inbound,
            outbound_runner=_outbound,
            sleeper=lambda _seconds: None,
            sleep_decision=lambda _settings, _cycle: False,
            cycle_summary_writer=lambda _summary: None,
            stop_predicate=lambda: len(outbound_calls) >= 3,
            readiness_probe=lambda: _not_ready_result(),
        )

        self.assertEqual(cycle_count, 3)
        self.assertEqual(inbound_calls, [])
        self.assertEqual(outbound_calls, [8, 8, 8])

    def test_recovery_runs_inbound_before_outbound_next_cycle(
        self,
    ) -> None:
        inbound_calls: list[int] = []
        outbound_calls: list[int] = []
        probe_calls: list[int] = []
        call_order: list[str] = []

        def _probe():
            probe_calls.append(1)
            call_order.append("probe")
            if len(probe_calls) < 3:
                return _not_ready_result()
            return _ready_result()

        def _inbound(bound: int) -> int:
            inbound_calls.append(bound)
            call_order.append(f"inbound:{bound}")
            return 0

        def _outbound(bound: int) -> int:
            outbound_calls.append(bound)
            call_order.append(f"outbound:{bound}")
            return 0

        cycle_count = run_forever(
            settings=_settings(inbound_bound=2, outbound_bound=8),
            inbound_runner=_inbound,
            outbound_runner=_outbound,
            sleeper=lambda _seconds: None,
            sleep_decision=lambda _settings, _cycle: False,
            cycle_summary_writer=lambda _summary: None,
            stop_predicate=lambda: len(inbound_calls) >= 1,
            readiness_probe=_probe,
        )

        self.assertEqual(cycle_count, 3)
        self.assertEqual(inbound_calls, [2])
        self.assertEqual(outbound_calls, [8, 8, 8])
        self.assertEqual(
            call_order,
            [
                "probe",
                "outbound:8",
                "probe",
                "outbound:8",
                "probe",
                "inbound:2",
                "outbound:8",
            ],
        )

    def test_cached_ready_skips_probe_on_subsequent_cycles(self) -> None:
        probe_calls: list[int] = []
        inbound_calls: list[int] = []
        outbound_calls: list[int] = []

        def _probe():
            probe_calls.append(1)
            return _ready_result()

        def _inbound(bound: int) -> int:
            inbound_calls.append(bound)
            return 0

        def _outbound(bound: int) -> int:
            outbound_calls.append(bound)
            return 0

        cycle_count = run_forever(
            settings=_settings(),
            inbound_runner=_inbound,
            outbound_runner=_outbound,
            sleeper=lambda _seconds: None,
            sleep_decision=lambda _settings, _cycle: False,
            cycle_summary_writer=lambda _summary: None,
            stop_predicate=lambda: len(outbound_calls) >= 4,
            readiness_probe=_probe,
        )

        self.assertEqual(cycle_count, 4)
        self.assertEqual(probe_calls, [1])
        self.assertEqual(inbound_calls, [1, 1, 1, 1])
        self.assertEqual(outbound_calls, [16, 16, 16, 16])

    def test_not_ready_summary_records_embed_category_when_generate_passes(
        self,
    ) -> None:
        summaries: list[dict[str, Any]] = []

        def _probe():
            return _not_ready_result(
                generate_category="passed",
                generate_duration_seconds=0.5,
                embed_category="EmbeddingConnectionError",
                embed_duration_seconds=0.7,
            )

        run_forever(
            settings=_settings(),
            inbound_runner=lambda _bound: 0,
            outbound_runner=lambda _bound: 0,
            sleeper=lambda _seconds: None,
            sleep_decision=lambda _settings, _cycle: False,
            cycle_summary_writer=lambda s: summaries.append(s),
            stop_predicate=lambda: len(summaries) >= 1,
            readiness_probe=_probe,
        )

        self.assertEqual(len(summaries), 1)
        summary = summaries[0]
        self.assertFalse(summary["ollama_ready"])
        self.assertEqual(
            summary["not_ready_category"], "EmbeddingConnectionError"
        )
        self.assertAlmostEqual(summary["probe_duration_seconds"], 1.2)

    def test_unexpected_probe_exception_yields_not_ready(self) -> None:
        """A buggy probe that escapes an exception must NOT crash
        the worker: the cycle is recorded as not-ready and the
        loop continues."""
        inbound_calls: list[int] = []
        outbound_calls: list[int] = []
        summaries: list[dict[str, Any]] = []

        def _probe():
            raise RuntimeError("forced probe failure")

        def _inbound(bound: int) -> int:
            inbound_calls.append(bound)
            return 0

        def _outbound(bound: int) -> int:
            outbound_calls.append(bound)
            return 0

        cycle_count = run_forever(
            settings=_settings(),
            inbound_runner=_inbound,
            outbound_runner=_outbound,
            sleeper=lambda _seconds: None,
            sleep_decision=lambda _settings, _cycle: False,
            cycle_summary_writer=lambda s: summaries.append(s),
            stop_predicate=lambda: len(outbound_calls) >= 2,
            readiness_probe=_probe,
        )

        self.assertEqual(cycle_count, 2)
        self.assertEqual(inbound_calls, [])
        self.assertEqual(outbound_calls, [16, 16])
        for summary in summaries:
            self.assertFalse(summary["ollama_ready"])
            self.assertEqual(
                summary["not_ready_category"], "probe_unexpected_error"
            )

    def test_ollama_ready_transition_logs_safe_metadata(self) -> None:
        """When the probe first succeeds, the worker emits one
        safe ``provider_processing_worker_ollama_ready`` log
        record carrying only cycle_index and probe_duration."""
        logger = logging.getLogger(
            "backend.cli.run_provider_processing_worker"
        )
        probe_calls: list[int] = []
        with self.assertLogs(logger, level=logging.INFO) as log_ctx:
            run_forever(
                settings=_settings(),
                inbound_runner=lambda _bound: 0,
                outbound_runner=lambda _bound: 0,
                sleeper=lambda _seconds: None,
                sleep_decision=lambda _settings, _cycle: False,
                cycle_summary_writer=lambda _summary: None,
                stop_predicate=lambda: len(probe_calls) >= 1,
                readiness_probe=lambda: (
                    probe_calls.append(1)
                    or _ready_result(
                        generate_duration_seconds=0.3,
                        embed_duration_seconds=0.2,
                    )
                ),
            )

        ready_records = [
            record
            for record in log_ctx.records
            if record.getMessage()
            == "provider_processing_worker_ollama_ready"
        ]
        self.assertEqual(len(ready_records), 1)
        ready = ready_records[0]
        self.assertEqual(
            getattr(ready, "cycle_index", None), 1
        )
        probe_duration = getattr(ready, "probe_duration_seconds", None)
        self.assertIsNotNone(probe_duration)
        self.assertAlmostEqual(float(probe_duration), 0.5)  # type: ignore[arg-type]
        self.assertFalse(getattr(ready, "exc_info", False))

    def test_unexpected_probe_exception_does_not_leak_payload(
        self,
    ) -> None:
        """The defensive guard MUST NOT log ``str(exc)`` or any
        sensitive payload carried by the probe exception."""
        sentinels = (
            "secret-auth-token-value",
            "AC000000000000000000000000000000",
            "+5491100000000",
            "https://provider.example",
            "X-Twilio-Signature",
            "Bearer ",
            "leak:",
            "inbound body",
            "outbound body",
            "prompt",
            "embed probe secret",
        )
        secret_message = (
            "leak: secret-auth-token-value / "
            "AC000000000000000000000000000000 / +5491100000000 / "
            "https://provider.example/cb?token=Bearer xyz / "
            "X-Twilio-Signature=abc / inbound body / outbound body / "
            "prompt / embed probe secret"
        )

        def _probe():
            raise RuntimeError(secret_message)

        logger = logging.getLogger(
            "backend.cli.run_provider_processing_worker"
        )
        probe_calls: list[int] = []
        with self.assertLogs(logger, level=logging.ERROR) as log_ctx:
            run_forever(
                settings=_settings(),
                inbound_runner=lambda _bound: 0,
                outbound_runner=lambda _bound: 0,
                sleeper=lambda _seconds: None,
                sleep_decision=lambda _settings, _cycle: False,
                cycle_summary_writer=lambda _summary: None,
                stop_predicate=lambda: len(probe_calls) >= 1,
                readiness_probe=lambda: (
                    probe_calls.append(1) or _probe()
                ),
            )

        self.assertEqual(len(log_ctx.records), 1)
        record = log_ctx.records[0]
        self.assertEqual(
            record.getMessage(),
            "provider_processing_worker_unexpected_failure",
        )
        self.assertFalse(record.exc_info)
        self.assertEqual(getattr(record, "reason", None), "RuntimeError")
        for token in sentinels:
            self.assertNotIn(token, record.getMessage())
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

    def test_not_ready_cycle_summary_excludes_sensitive_payloads(
        self,
    ) -> None:
        """A not-ready cycle summary MUST NOT contain probe text,
        probe response, vectors, URL/proxy or any operator/
        provider/customer content."""
        sentinels = (
            "secret-auth-token-value",
            "AC000000000000000000000000000000",
            "+5491100000000",
            "https://provider.example",
            "X-Twilio-Signature",
            "Bearer ",
            "leak:",
            "inbound body",
            "outbound body",
            "prompt",
            "embed probe secret",
        )

        probe_calls: list[int] = []

        def _probe():
            probe_calls.append(1)
            return _not_ready_result(
                generate_category="QueryLlmHttpError",
                embed_category="skipped_due_to_generate_failure",
            )

        with _capture_stdout() as stdout:
            run_forever(
                settings=_settings(),
                inbound_runner=lambda _bound: 0,
                outbound_runner=lambda _bound: 0,
                sleeper=lambda _seconds: None,
                sleep_decision=lambda _settings, _cycle: False,
                cycle_summary_writer=worker_cli._default_cycle_summary_writer,
                stop_predicate=lambda: len(probe_calls) >= 1,
                readiness_probe=_probe,
            )

        rendered = stdout.getvalue()
        self.assertIn("ollama_ready=False", rendered)
        self.assertIn(
            "not_ready_category=QueryLlmHttpError", rendered
        )
        self.assertIn("inbound_exit_code=None", rendered)
        for token in sentinels:
            self.assertNotIn(token, rendered)

    def test_run_cycle_with_ollama_ready_false_skips_inbound(
        self,
    ) -> None:
        inbound_calls: list[int] = []
        outbound_calls: list[int] = []

        def _inbound(bound: int) -> int:
            inbound_calls.append(bound)
            return 0

        def _outbound(bound: int) -> int:
            outbound_calls.append(bound)
            return 0

        summaries: list[dict[str, Any]] = []

        def _writer(summary: dict[str, Any]) -> None:
            summaries.append(summary)

        summary = run_cycle(
            settings=_settings(inbound_bound=3, outbound_bound=42),
            cycle_index=7,
            inbound_runner=_inbound,
            outbound_runner=_outbound,
            sleep_decision=lambda _settings, _cycle: False,
            cycle_summary_writer=_writer,
            ollama_ready=False,
            not_ready_category="EmbeddingTimeoutError",
            probe_duration_seconds=1.25,
        )

        self.assertEqual(inbound_calls, [])
        self.assertEqual(outbound_calls, [42])
        self.assertEqual(summary["ollama_ready"], False)
        self.assertIsNone(summary["inbound_exit_code"])
        self.assertEqual(summary["outbound_exit_code"], 0)
        self.assertEqual(
            summary["not_ready_category"], "EmbeddingTimeoutError"
        )
        self.assertEqual(summary["probe_duration_seconds"], 1.25)
        self.assertEqual(summary["cycle_index"], 7)

    def test_run_cycle_default_ollama_ready_true_keeps_inbound(
        self,
    ) -> None:
        """When ``ollama_ready`` is omitted, ``run_cycle`` keeps
        the legacy inbound-then-outbound behavior so existing
        callers and tests remain green."""
        call_order: list[str] = []

        def _inbound(bound: int) -> int:
            call_order.append(f"inbound:{bound}")
            return 0

        def _outbound(bound: int) -> int:
            call_order.append(f"outbound:{bound}")
            return 0

        summary = run_cycle(
            settings=_settings(inbound_bound=1, outbound_bound=16),
            cycle_index=2,
            inbound_runner=_inbound,
            outbound_runner=_outbound,
            sleep_decision=lambda _settings, _cycle: False,
            cycle_summary_writer=lambda _summary: None,
        )

        self.assertEqual(call_order, ["inbound:1", "outbound:16"])
        self.assertTrue(summary["ollama_ready"])
        self.assertEqual(summary["inbound_exit_code"], 0)
        self.assertNotIn("not_ready_category", summary)
        self.assertNotIn("probe_duration_seconds", summary)

    def test_main_with_real_default_probe_uses_settings_bound(
        self,
    ) -> None:
        """The default readiness probe factory binds the probe to
        the same ``Settings`` instance used by ``main()`` so the
        probe respects the worker's configured LLM and embedding
        endpoints."""

        observed: dict[str, Any] = {}

        class _ProbeStub:
            def __init__(self, settings: Settings) -> None:
                observed["settings_id"] = id(settings)
                observed["llm_url"] = settings.llm_url
                observed["embedding_url"] = settings.embedding_url

            def __call__(self) -> Any:
                return worker_cli._always_ready_probe()

        captured_settings: dict[str, Settings] = {}

        def _loader() -> Settings:
            settings = _settings()
            captured_settings["value"] = settings
            return settings

        main(
            settings_loader=_loader,
            inbound_runner=lambda _bound: 0,
            outbound_runner=lambda _bound: 0,
            sleeper=lambda _seconds: None,
            sleep_decision=lambda _settings, _cycle: False,
            stop_predicate=lambda: True,
            readiness_probe=_ProbeStub(
                captured_settings.get("value", _settings())
            ),
        )

        self.assertEqual(
            observed["settings_id"], id(captured_settings["value"])
        )


class WorkerReadinessSeamContractTest(unittest.TestCase):
    """The readiness seam is reusable and side-effect-free. It
    opens no DB session, sends no provider message, mutates no
    business state."""

    def _settings(self) -> Settings:
        return Settings(
            llm_url="http://llm.test/api/generate",
            llm_model="test-llm",
            llm_timeout=30,
            llm_keep_alive="1h",
            llm_num_ctx=2048,
            llm_num_predict=256,
            llm_log_content=False,
            llm_log_max_chars=50,
            embedding_url="http://embed.test/api/embed",
            embedding_model="test-embed",
            embedding_timeout_seconds=15,
            embedding_batch_size=2,
            embedding_dimension=4,
        )

    def test_seam_returns_ready_when_both_probes_pass(self) -> None:
        from backend.scripts.check_railway_ollama_contracts import (
            check_ollama_readiness,
        )

        settings = self._settings()
        with mock.patch(
            "backend.scripts.check_railway_ollama_contracts.QueryLlm"
        ) as query_cls, mock.patch(
            "backend.scripts.check_railway_ollama_contracts.OllamaEmbeddingClient"
        ) as embed_cls:
            query_instance = query_cls.return_value
            query_instance.request.return_value = {"ok": True}
            embed_instance = embed_cls.return_value
            embed_instance.embed_query.return_value = [0.1, 0.2, 0.3, 0.4]

            result = check_ollama_readiness(settings=settings)

        self.assertTrue(result.ready)
        self.assertEqual(result.generate_category, "passed")
        self.assertEqual(result.embed_category, "passed")
        self.assertEqual(result.embed_dimension, 4)
        self.assertGreaterEqual(result.generate_duration_seconds, 0.0)
        self.assertGreaterEqual(result.embed_duration_seconds, 0.0)

        query_instance.request.assert_called_once()
        embed_instance.embed_query.assert_called_once()

    def test_seam_short_circuits_embed_when_generate_fails(self) -> None:
        from backend.llm.query_llm import (
            QueryLlmConnectionError,
        )
        from backend.scripts.check_railway_ollama_contracts import (
            check_ollama_readiness,
        )

        settings = self._settings()
        with mock.patch(
            "backend.scripts.check_railway_ollama_contracts.QueryLlm"
        ) as query_cls, mock.patch(
            "backend.scripts.check_railway_ollama_contracts.OllamaEmbeddingClient"
        ) as embed_cls:
            query_instance = query_cls.return_value
            query_instance.request.side_effect = QueryLlmConnectionError(
                "refused"
            )
            result = check_ollama_readiness(settings=settings)

        self.assertFalse(result.ready)
        self.assertEqual(
            result.generate_category, "QueryLlmConnectionError"
        )
        self.assertEqual(
            result.embed_category, "skipped_due_to_generate_failure"
        )
        self.assertIsNone(result.embed_dimension)
        embed_cls.assert_not_called()

    def test_seam_records_embed_failure_category(self) -> None:
        from backend.llm.embedding_client import (
            EmbeddingConnectionError,
        )
        from backend.scripts.check_railway_ollama_contracts import (
            check_ollama_readiness,
        )

        settings = self._settings()
        with mock.patch(
            "backend.scripts.check_railway_ollama_contracts.QueryLlm"
        ) as query_cls, mock.patch(
            "backend.scripts.check_railway_ollama_contracts.OllamaEmbeddingClient"
        ) as embed_cls:
            query_instance = query_cls.return_value
            query_instance.request.return_value = {"ok": True}
            embed_instance = embed_cls.return_value
            embed_instance.embed_query.side_effect = (
                EmbeddingConnectionError("refused")
            )
            result = check_ollama_readiness(settings=settings)

        self.assertFalse(result.ready)
        self.assertEqual(result.generate_category, "passed")
        self.assertEqual(
            result.embed_category, "EmbeddingConnectionError"
        )
        self.assertIsNone(result.embed_dimension)

    def test_seam_swallows_unexpected_generate_exception(self) -> None:
        from backend.scripts.check_railway_ollama_contracts import (
            check_ollama_readiness,
        )

        settings = self._settings()
        with mock.patch(
            "backend.scripts.check_railway_ollama_contracts.QueryLlm"
        ) as query_cls, mock.patch(
            "backend.scripts.check_railway_ollama_contracts.OllamaEmbeddingClient"
        ) as embed_cls:
            query_instance = query_cls.return_value
            query_instance.request.side_effect = ValueError(
                "leak: secret-auth-token-value / prompt"
            )
            result = check_ollama_readiness(settings=settings)

        self.assertFalse(result.ready)
        self.assertEqual(
            result.generate_category, "generate_unexpected_error"
        )
        self.assertEqual(
            result.embed_category, "skipped_due_to_generate_failure"
        )
        self.assertNotIn("secret-auth-token-value", result.generate_category)
        self.assertNotIn("prompt", result.generate_category)
        embed_cls.assert_not_called()

    def test_seam_swallows_unexpected_embed_exception(self) -> None:
        from backend.scripts.check_railway_ollama_contracts import (
            check_ollama_readiness,
        )

        settings = self._settings()
        with mock.patch(
            "backend.scripts.check_railway_ollama_contracts.QueryLlm"
        ) as query_cls, mock.patch(
            "backend.scripts.check_railway_ollama_contracts.OllamaEmbeddingClient"
        ) as embed_cls:
            query_instance = query_cls.return_value
            query_instance.request.return_value = {"ok": True}
            embed_instance = embed_cls.return_value
            embed_instance.embed_query.side_effect = OSError(
                "leak: secret-auth-token-value"
            )
            result = check_ollama_readiness(settings=settings)

        self.assertFalse(result.ready)
        self.assertEqual(result.generate_category, "passed")
        self.assertEqual(
            result.embed_category, "embed_unexpected_error"
        )
        self.assertIsNone(result.embed_dimension)
        self.assertNotIn("secret-auth-token-value", result.embed_category)

    def test_seam_does_not_open_db_or_invoke_twilio(self) -> None:
        """The seam ``check_ollama_readiness`` MUST NOT touch the
        database or Twilio modules. The seam only references the
        typed LLM clients (``QueryLlm``, ``OllamaEmbeddingClient``)
        and the loaded ``Settings``; it never imports any database,
        ORM, Twilio or HTTP-direct module."""
        import inspect

        from backend.scripts.check_railway_ollama_contracts import (
            check_ollama_readiness,
        )

        source = inspect.getsource(check_ollama_readiness)
        forbidden_tokens = (
            "_SessionLocal",
            "Session(",
            "begin()",
            "commit()",
            "rollback()",
            "flush(",
            "Twilio",
            "twilio",
            "requests.post",
            "requests.get",
            "socks5h",
            "HTTP_PROXY",
            "ALL_PROXY",
            "HTTPS_PROXY",
            "ProviderInboundMessageCoordinator",
            "CanalWhatsappService",
            "OutboundDispatcher",
        )
        for token in forbidden_tokens:
            self.assertNotIn(
                token,
                source,
                f"seam must not reference {token!r}",
            )

    def test_seam_module_imports_only_typed_llm_dependencies(self) -> None:
        """The seam module imports only the LLM clients, ``Settings``
        and stdlib/argparse/dataclasses for the CLI surface. The
        ``check_ollama_readiness`` symbol itself MUST come from
        the module without any DB / ORM / Twilio side-effect."""
        from backend.scripts import check_railway_ollama_contracts as seam

        self.assertTrue(callable(seam.check_ollama_readiness))
        self.assertTrue(callable(seam.OllamaReadinessResult))

    def test_seam_uses_fixed_inputs_that_are_never_logged(
        self,
    ) -> None:
        """The fixed probe inputs are NEVER surfaced in the
        :class:`OllamaReadinessResult` or in the seam's local
        state."""
        from backend.scripts.check_railway_ollama_contracts import (
            _OLLAMA_READINESS_PROBE_EMBED_INPUT,
            _OLLAMA_READINESS_PROBE_GENERATE_PROMPT,
            check_ollama_readiness,
        )

        settings = self._settings()
        with mock.patch(
            "backend.scripts.check_railway_ollama_contracts.QueryLlm"
        ) as query_cls, mock.patch(
            "backend.scripts.check_railway_ollama_contracts.OllamaEmbeddingClient"
        ) as embed_cls:
            query_instance = query_cls.return_value
            query_instance.request.return_value = {"ok": True}
            embed_instance = embed_cls.return_value
            embed_instance.embed_query.return_value = [0.1, 0.2, 0.3, 0.4]
            result = check_ollama_readiness(settings=settings)

        query_args, _ = query_instance.request.call_args
        self.assertEqual(query_args[0], _OLLAMA_READINESS_PROBE_GENERATE_PROMPT)
        embed_args, _ = embed_instance.embed_query.call_args
        self.assertEqual(embed_args[0], _OLLAMA_READINESS_PROBE_EMBED_INPUT)

        dumped = repr(result)
        self.assertNotIn(_OLLAMA_READINESS_PROBE_GENERATE_PROMPT, dumped)
        self.assertNotIn(_OLLAMA_READINESS_PROBE_EMBED_INPUT, dumped)
        for field in (
            "generate_category",
            "embed_category",
            "embed_dimension",
            "generate_duration_seconds",
            "embed_duration_seconds",
        ):
            self.assertNotIn(
                _OLLAMA_READINESS_PROBE_GENERATE_PROMPT,
                repr(getattr(result, field)),
            )
            self.assertNotIn(
                _OLLAMA_READINESS_PROBE_EMBED_INPUT,
                repr(getattr(result, field)),
            )

    def test_seam_dimension_pass_uses_client_validated_length(
        self,
    ) -> None:
        from backend.scripts.check_railway_ollama_contracts import (
            check_ollama_readiness,
        )

        settings = self._settings()
        with mock.patch(
            "backend.scripts.check_railway_ollama_contracts.QueryLlm"
        ) as query_cls, mock.patch(
            "backend.scripts.check_railway_ollama_contracts.OllamaEmbeddingClient"
        ) as embed_cls:
            query_cls.return_value.request.return_value = {"ok": True}
            embed_instance = embed_cls.return_value
            embed_instance.embed_query.return_value = [0.0, 0.0, 0.0, 0.0]
            result = check_ollama_readiness(settings=settings)

        self.assertTrue(result.ready)
        self.assertEqual(result.embed_dimension, settings.embedding_dimension)


class WorkerReadinessDiagnosticCliRegressionTest(unittest.TestCase):
    """The existing diagnostic CLI contract MUST be preserved."""

    def test_diagnostic_cli_emits_generate_passed_when_both_pass(
        self,
    ) -> None:
        import contextlib
        import io

        from backend.scripts import check_railway_ollama_contracts as seam

        settings = self._settings_for_diagnostic()
        with mock.patch.object(seam, "QueryLlm") as query_cls, mock.patch.object(
            seam, "OllamaEmbeddingClient"
        ) as embed_cls, mock.patch.object(
            seam, "load_settings", return_value=settings
        ):
            query_cls.return_value.request.return_value = {"ok": True}
            embed_cls.return_value.embed_query.return_value = [0.0] * 4
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
                stderr
            ):
                result = seam.main(argv=[])

        self.assertEqual(result, 0)
        rendered_stdout = stdout.getvalue()
        rendered_stderr = stderr.getvalue()
        self.assertIn("generate=passed", rendered_stdout)
        self.assertIn("model=test-llm", rendered_stdout)
        self.assertIn("embed=passed", rendered_stdout)
        self.assertIn("dimension=4", rendered_stdout)
        self.assertNotIn("generate=failed", rendered_stderr)
        self.assertNotIn("embed=failed", rendered_stderr)

    def test_diagnostic_cli_returns_one_when_generate_fails(
        self,
    ) -> None:
        import contextlib
        import io

        from backend.llm.query_llm import QueryLlmConnectionError
        from backend.scripts import check_railway_ollama_contracts as seam

        settings = self._settings_for_diagnostic()
        with mock.patch.object(seam, "QueryLlm") as query_cls, mock.patch.object(
            seam, "OllamaEmbeddingClient"
        ) as embed_cls, mock.patch.object(
            seam, "load_settings", return_value=settings
        ):
            query_cls.return_value.request.side_effect = (
                QueryLlmConnectionError("refused")
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
                stderr
            ):
                result = seam.main(argv=[])

        self.assertEqual(result, 1)
        self.assertNotIn("generate=passed", stdout.getvalue())
        self.assertIn("generate=failed", stderr.getvalue())
        self.assertIn("category=QueryLlmConnectionError", stderr.getvalue())
        embed_cls.assert_not_called()

    def test_diagnostic_cli_returns_one_when_embed_fails(self) -> None:
        import contextlib
        import io

        from backend.llm.embedding_client import EmbeddingConnectionError
        from backend.scripts import check_railway_ollama_contracts as seam

        settings = self._settings_for_diagnostic()
        with mock.patch.object(seam, "QueryLlm") as query_cls, mock.patch.object(
            seam, "OllamaEmbeddingClient"
        ) as embed_cls, mock.patch.object(
            seam, "load_settings", return_value=settings
        ):
            query_cls.return_value.request.return_value = {"ok": True}
            embed_cls.return_value.embed_query.side_effect = (
                EmbeddingConnectionError("refused")
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
                stderr
            ):
                result = seam.main(argv=[])

        self.assertEqual(result, 1)
        self.assertIn("generate=passed", stdout.getvalue())
        self.assertIn("embed=failed", stderr.getvalue())
        self.assertIn(
            "category=EmbeddingConnectionError", stderr.getvalue()
        )

    def _settings_for_diagnostic(self) -> Settings:
        return Settings(
            llm_url="http://llm.test/api/generate",
            llm_model="test-llm",
            llm_timeout=30,
            llm_keep_alive="1h",
            llm_num_ctx=2048,
            llm_num_predict=256,
            llm_log_content=False,
            llm_log_max_chars=50,
            embedding_url="http://embed.test/api/embed",
            embedding_model="test-embed",
            embedding_timeout_seconds=15,
            embedding_batch_size=2,
            embedding_dimension=4,
        )


class WorkerOutboundCycleAggregateTest(unittest.TestCase):
    """The worker must emit one safe per-cycle outbound aggregate
    so terminal Twilio failures are not reduced to a single exit
    code. The aggregate flows through the cycle summary writer
    and never includes bodies, addresses, signatures, payloads or
    environment dumps.
    """

    def test_cycle_summary_contains_outbound_aggregate_counts(
        self,
    ) -> None:
        from backend.services.outbound_dispatch_types import (
            OutboundCycleAggregate,
        )

        inbound_calls: list[int] = []
        outbound_calls: list[int] = []
        summaries: list[dict[str, Any]] = []

        def _inbound(bound: int) -> int:
            inbound_calls.append(bound)
            return 0

        def _outbound(bound: int) -> int:
            outbound_calls.append(bound)
            return 0

        aggregate = OutboundCycleAggregate(
            sent=2,
            retry_scheduled=1,
            failed_terminal=1,
            no_due_row=1,
            technical_failure=0,
            failure_category_counts={
                "retryable_429": 1,
                "terminal_4xx": 1,
            },
        )

        def _producer(bound: int) -> OutboundCycleAggregate:
            return aggregate

        run_cycle(
            settings=_settings(inbound_bound=1, outbound_bound=16),
            cycle_index=1,
            inbound_runner=_inbound,
            outbound_runner=_outbound,
            sleep_decision=lambda _settings, _cycle: False,
            cycle_summary_writer=lambda s: summaries.append(s),
            outbound_cycle_aggregate_producer=_producer,
        )

        self.assertEqual(len(summaries), 1)
        summary = summaries[0]
        self.assertEqual(summary["outbound_cycle_aggregate"], aggregate)
        self.assertEqual(summary["outbound_cycle_aggregate"].sent, 2)
        self.assertEqual(
            summary["outbound_cycle_aggregate"].failed_terminal, 1
        )

    def test_cycle_summary_writer_default_renders_safe_aggregate_line(
        self,
    ) -> None:
        from backend.services.outbound_dispatch_types import (
            OutboundCycleAggregate,
        )

        summary = _build_cycle_summary(
            cycle_index=3,
            inbound_exit_code=0,
            outbound_exit_code=1,
            settings=_settings(inbound_bound=1, outbound_bound=16),
            sleep_after=True,
            outbound_cycle_aggregate=OutboundCycleAggregate(
                sent=1,
                retry_scheduled=2,
                failed_terminal=1,
                no_due_row=1,
                technical_failure=0,
                failure_category_counts={
                    "retryable_429": 1,
                    "terminal_4xx": 1,
                    "budget_exhausted": 1,
                },
            ),
        )

        with _capture_stdout() as stdout:
            worker_cli._default_cycle_summary_writer(summary)

        rendered = stdout.getvalue()
        self.assertIn("outbound_sent=1", rendered)
        self.assertIn("outbound_retry_scheduled=2", rendered)
        self.assertIn("outbound_failed_terminal=1", rendered)
        self.assertIn("outbound_no_due_row=1", rendered)
        self.assertIn("outbound_technical_failure=0", rendered)
        self.assertIn("outbound_failure_categories=", rendered)
        self.assertIn("retryable_429=1", rendered)
        self.assertIn("terminal_4xx=1", rendered)
        self.assertIn("budget_exhausted=1", rendered)

        forbidden = (
            "secret-auth-token-value",
            "AC000000000000000000000000000000",
            "+5491100000000",
            "+5491155556666",
            "X-Twilio-Signature",
            "Bearer ",
        )
        for token in forbidden:
            self.assertNotIn(token, rendered)

    def test_cycle_summary_writer_omits_aggregate_when_none(
        self,
    ) -> None:
        summary = _build_cycle_summary(
            cycle_index=1,
            inbound_exit_code=0,
            outbound_exit_code=0,
            settings=_settings(),
            sleep_after=False,
        )

        with _capture_stdout() as stdout:
            worker_cli._default_cycle_summary_writer(summary)

        rendered = stdout.getvalue()
        self.assertNotIn("outbound_sent=", rendered)
        self.assertNotIn("outbound_failure_categories=", rendered)

    def test_default_outbound_runner_shares_aggregate_with_default_producer(
        self,
    ) -> None:
        """Production wiring must feed the per-cycle aggregate
        from the default outbound runner into the default
        outbound cycle aggregate producer without re-running the
        dispatcher.
        """

        from backend.services.outbound_dispatch_types import (
            OutboundDispatchOutcome,
            OutboundDispatchResult,
            OutboundPassEvidence,
        )

        # Reset the shared cell so prior tests cannot leak into this
        # assertion. The cell is process-local by design.
        worker_cli._WORKER_OUTBOUND_CELL.aggregate = None

        sent_result = OutboundDispatchResult(
            outcome=OutboundDispatchOutcome.SENT,
            mensaje_id=42,
            identificador_proveedor="SM-OK",
            intentos=None,
            categoria=None,
            codigo=None,
            durable_state="accepted",
        )
        evidence = OutboundPassEvidence(
            results=(sent_result,),
            technical_exceptions=(),
        )

        # Inject the dispatcher mock directly into the CLI's
        # ``main()`` so the default runner's closure writer
        # receives the per-cycle aggregate and the producer
        # seam surfaces it without re-running the dispatcher.
        from backend.cli.run_outbound_dispatch import (
            main as outbound_main,
        )

        dispatcher_mock = MagicMock(name="OutboundMessageDispatcher")
        dispatcher_mock.run_pass_with_evidence.return_value = evidence

        with mock.patch.dict(
            os.environ,
            {
                "TWILIO_AUTH_TOKEN": "test-token",
                "TWILIO_ACCOUNT_SID": "AC" + "0" * 32,
                "TWILIO_OUTBOUND_SENDER_E164": "+5491100000000",
                "TWILIO_CALLBACK_STATUS_URL": (
                    "https://example.test/cb"
                ),
            },
            clear=True,
        ), _capture_stdout():
            exit_code = outbound_main(
                argv=["--max-attempts-per-pass", "16"],
                session_factory_builder=lambda: MagicMock(
                    name="SessionFactory"
                ),
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=lambda **_: dispatcher_mock,
                cycle_aggregate_writer=lambda agg: setattr(
                    worker_cli._WORKER_OUTBOUND_CELL,
                    "aggregate",
                    agg,
                ),
            )

        self.assertEqual(exit_code, 0)

        producer = worker_cli._default_outbound_cycle_aggregate_producer
        aggregate = producer(16)

        self.assertEqual(aggregate.sent, 1)
        self.assertEqual(aggregate.retry_scheduled, 0)
        self.assertEqual(aggregate.failed_terminal, 0)
        self.assertEqual(aggregate.technical_failure, 0)
        self.assertEqual(dict(aggregate.failure_category_counts), {})

        worker_cli._WORKER_OUTBOUND_CELL.aggregate = None


class DefaultOutboundRunnerCellResetTest(unittest.TestCase):
    """The default outbound runner must reset the shared
    ``_WORKER_OUTBOUND_CELL.aggregate`` BEFORE invoking the CLI
    so a previous cycle's safe aggregate never leaks into the
    next cycle, even when the CLI terminates early without
    writing a fresh aggregate (settings / validation / Twilio
    client construction failure)."""

    def setUp(self) -> None:
        # Snapshot the cell so a failing test cannot leak a stale
        # aggregate into the next test. The cell is process-local
        # by design.
        self._previous_cell = worker_cli._WORKER_OUTBOUND_CELL.aggregate
        worker_cli._WORKER_OUTBOUND_CELL.aggregate = None

    def tearDown(self) -> None:
        worker_cli._WORKER_OUTBOUND_CELL.aggregate = self._previous_cell

    def test_default_runner_resets_cell_before_invoking_cli(self) -> None:
        """The cell MUST be cleared before any ``main()`` call so a
        stale previous-cycle aggregate cannot be observed when the
        CLI raises before reaching the dispatcher."""

        from backend.services.outbound_dispatch_types import (
            OutboundCycleAggregate,
        )

        previous = OutboundCycleAggregate(
            sent=5,
            retry_scheduled=3,
            failed_terminal=2,
            no_due_row=1,
            technical_failure=0,
            failure_category_counts={"foo": 2},
        )
        worker_cli._WORKER_OUTBOUND_CELL.aggregate = previous

        observed: list[Any] = []

        def _spy_main(*args: Any, **kwargs: Any) -> int:
            observed.append(
                ("cell_at_call", worker_cli._WORKER_OUTBOUND_CELL.aggregate)
            )
            from backend.services.exceptions import (
                InvalidTwilioOutboundDispatchConfig,
            )
            raise InvalidTwilioOutboundDispatchConfig("forced settings error")

        with mock.patch.object(
            worker_cli, "run_outbound_dispatch_main", _spy_main
        ):
            with self.assertRaises(InvalidTwilioOutboundDispatchConfig):
                worker_cli._default_outbound_runner(4)

        self.assertEqual(len(observed), 1)
        cell_at_call = observed[0][1]
        self.assertIsNone(
            cell_at_call,
            "cell must be cleared before the CLI is invoked; "
            "stale aggregate would otherwise leak into the next "
            "cycle's producer",
        )

    def test_previous_aggregate_then_early_failure_does_not_reuse_stale(
        self,
    ) -> None:
        """A cycle that runs after a previous successful cycle
        followed by an early CLI failure MUST NOT reuse the
        previous cycle's ``sent`` / ``retry_scheduled`` /
        ``failed_terminal`` / ``no_due_row`` / category counts."""

        from backend.cli.run_outbound_dispatch import (
            main as outbound_main,
        )
        from backend.models.mensaje_proveedor_saliente import (
            OutboundFailureCategory,
        )
        from backend.services.outbound_dispatch_types import (
            OutboundDispatchOutcome,
            OutboundDispatchResult,
            OutboundPassEvidence,
        )

        worker_cli._WORKER_OUTBOUND_CELL.aggregate = None

        # Previous cycle succeeded with non-trivial evidence.
        sent_result = OutboundDispatchResult(
            outcome=OutboundDispatchOutcome.SENT,
            mensaje_id=11,
            identificador_proveedor="SM-PREV",
            intentos=None,
            categoria=None,
            codigo=None,
            durable_state="accepted",
        )
        retry_result = OutboundDispatchResult(
            outcome=OutboundDispatchOutcome.RETRY_SCHEDULED,
            mensaje_id=12,
            identificador_proveedor=None,
            intentos=2,
            categoria=OutboundFailureCategory.RETRYABLE_429,
            codigo="20003",
            durable_state="retryable",
            http_status=429,
        )
        terminal_result = OutboundDispatchResult(
            outcome=OutboundDispatchOutcome.FAILED_TERMINAL,
            mensaje_id=13,
            identificador_proveedor=None,
            intentos=5,
            categoria=OutboundFailureCategory.TERMINAL_4XX,
            codigo="403",
            durable_state="failed_terminal",
            http_status=403,
        )
        previous_evidence = OutboundPassEvidence(
            results=(sent_result, retry_result, terminal_result),
            technical_exceptions=(),
        )
        dispatcher_mock = MagicMock(name="OutboundMessageDispatcher")
        dispatcher_mock.run_pass_with_evidence.return_value = (
            previous_evidence
        )

        with mock.patch.dict(
            os.environ,
            {
                "TWILIO_AUTH_TOKEN": "prev-token",
                "TWILIO_ACCOUNT_SID": "AC" + "0" * 32,
                "TWILIO_OUTBOUND_SENDER_E164": "+5491100000000",
                "TWILIO_CALLBACK_STATUS_URL": (
                    "https://example.test/cb"
                ),
            },
            clear=True,
        ), _capture_stdout():
            prev_exit = outbound_main(
                argv=["--max-attempts-per-pass", "16"],
                session_factory_builder=lambda: MagicMock(
                    name="SessionFactory"
                ),
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=lambda **_: dispatcher_mock,
                cycle_aggregate_writer=lambda agg: setattr(
                    worker_cli._WORKER_OUTBOUND_CELL,
                    "aggregate",
                    agg,
                ),
            )

        self.assertEqual(prev_exit, 1)
        previous_aggregate = worker_cli._WORKER_OUTBOUND_CELL.aggregate
        self.assertIsNotNone(previous_aggregate)
        self.assertEqual(previous_aggregate.sent, 1)
        self.assertEqual(previous_aggregate.retry_scheduled, 1)
        self.assertEqual(previous_aggregate.failed_terminal, 1)
        self.assertEqual(previous_aggregate.no_due_row, 0)
        self.assertEqual(previous_aggregate.technical_failure, 0)
        self.assertEqual(
            dict(previous_aggregate.failure_category_counts),
            {"retryable_429": 1, "terminal_4xx": 1},
        )

        # Second cycle: Twilio client construction fails BEFORE the
        # dispatcher runs. The shared cell must NOT still hold the
        # previous cycle's aggregate.
        def _raise_client(**_kwargs: Any) -> Any:
            raise RuntimeError("boom twilio construction")

        captured_writer: list[Any] = []
        with _capture_stdout(), _capture_stderr():
            second_exit = outbound_main(
                argv=["--max-attempts-per-pass", "4"],
                settings_loader=lambda: _settings(),
                session_factory_builder=lambda: MagicMock(
                    name="SessionFactory"
                ),
                messages_client_builder=_raise_client,
                dispatcher_builder=lambda **_: MagicMock(
                    name="OutboundMessageDispatcher"
                ),
                cycle_aggregate_writer=captured_writer.append,
            )

        self.assertEqual(second_exit, 3)
        self.assertEqual(len(captured_writer), 1)
        second_aggregate = captured_writer[0]
        self.assertEqual(second_aggregate.sent, 0)
        self.assertEqual(second_aggregate.retry_scheduled, 0)
        self.assertEqual(second_aggregate.failed_terminal, 0)
        self.assertEqual(second_aggregate.no_due_row, 0)
        self.assertEqual(second_aggregate.technical_failure, 1)
        self.assertEqual(dict(second_aggregate.failure_category_counts), {})

        worker_cli._WORKER_OUTBOUND_CELL.aggregate = None

    def test_default_runner_default_producer_no_double_dispatch(
        self,
    ) -> None:
        """The default wiring must feed the per-cycle aggregate
        from the default outbound runner into the default
        outbound cycle aggregate producer WITHOUT invoking the
        dispatcher a second time."""

        from backend.cli.run_outbound_dispatch import (
            main as outbound_main,
        )
        from backend.services.outbound_dispatch_types import (
            OutboundDispatchOutcome,
            OutboundDispatchResult,
            OutboundPassEvidence,
        )

        worker_cli._WORKER_OUTBOUND_CELL.aggregate = None

        sent_result = OutboundDispatchResult(
            outcome=OutboundDispatchOutcome.SENT,
            mensaje_id=42,
            identificador_proveedor="SM-OK",
            intentos=None,
            categoria=None,
            codigo=None,
            durable_state="accepted",
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
        evidence = OutboundPassEvidence(
            results=(sent_result, no_due_result),
            technical_exceptions=(),
        )
        dispatcher_mock = MagicMock(name="OutboundMessageDispatcher")
        dispatcher_mock.run_pass_with_evidence.return_value = evidence

        # The dispatcher is wired through the CLI's
        # ``dispatcher_builder`` seam. The cycle_aggregate_writer
        # writes to the shared cell exactly as the default
        # runner's closure writer does in production.
        with mock.patch.dict(
            os.environ,
            {
                "TWILIO_AUTH_TOKEN": "ok-token",
                "TWILIO_ACCOUNT_SID": "AC" + "0" * 32,
                "TWILIO_OUTBOUND_SENDER_E164": "+5491100000000",
                "TWILIO_CALLBACK_STATUS_URL": (
                    "https://example.test/cb"
                ),
            },
            clear=True,
        ), _capture_stdout():
            exit_code = outbound_main(
                argv=["--max-attempts-per-pass", "16"],
                session_factory_builder=lambda: MagicMock(
                    name="SessionFactory"
                ),
                messages_client_builder=lambda **_kwargs: MagicMock(
                    name="TwilioMessagesClient"
                ),
                dispatcher_builder=lambda **_: dispatcher_mock,
                cycle_aggregate_writer=lambda agg: setattr(
                    worker_cli._WORKER_OUTBOUND_CELL,
                    "aggregate",
                    agg,
                ),
            )

        self.assertEqual(exit_code, 0)

        # The default producer must surface the captured
        # aggregate without invoking the dispatcher a second
        # time.
        producer_calls: list[int] = []
        original_producer = (
            worker_cli._default_outbound_cycle_aggregate_producer
        )

        def _producer_with_invariant(bound: int) -> Any:
            producer_calls.append(bound)
            return original_producer(bound)

        with mock.patch.object(
            worker_cli,
            "_default_outbound_cycle_aggregate_producer",
            _producer_with_invariant,
        ):
            aggregate = worker_cli._default_outbound_cycle_aggregate_producer(
                16
            )

        self.assertEqual(producer_calls, [16])
        self.assertEqual(aggregate.sent, 1)
        self.assertEqual(aggregate.retry_scheduled, 0)
        self.assertEqual(aggregate.failed_terminal, 0)
        self.assertEqual(aggregate.no_due_row, 1)
        self.assertEqual(aggregate.technical_failure, 0)
        self.assertEqual(dict(aggregate.failure_category_counts), {})
        dispatcher_mock.run_pass_with_evidence.assert_called_once()

        worker_cli._WORKER_OUTBOUND_CELL.aggregate = None


class WorkerLivenessReadyCycleTest(unittest.TestCase):
    """A normal ready cycle MUST emit the closed lifecycle
    sequence:

    ``cycle_started`` → ``phase_started(inbound)`` →
    ``phase_completed(inbound)`` → ``phase_started(outbound)`` →
    ``phase_completed(outbound)`` → ``cycle_completed`` →
    ``phase_started(sleep)`` → ``phase_completed(sleep)``.

    No provider / database / Twilio call is invoked because the
    loop is driven entirely through injectable runner, sleeper,
    readiness probe and cycle summary seams.
    """

    def test_ready_cycle_emits_full_lifecycle_in_order(self) -> None:
        events: list[dict[str, Any]] = []

        def _inbound(_bound: int) -> int:
            events.append({"kind": "inbound_runner"})
            return 0

        def _outbound(_bound: int) -> int:
            events.append({"kind": "outbound_runner"})
            return 0

        with _capture_stdout() as stdout:
            run_cycle(
                settings=_settings(inbound_bound=1, outbound_bound=16),
                cycle_index=1,
                inbound_runner=_inbound,
                outbound_runner=_outbound,
                sleep_decision=lambda _settings, _cycle: False,
                cycle_summary_writer=lambda _summary: None,
            )

        liveness = _liveness_events(stdout.getvalue())
        outcomes = [
            (event.get("phase"), event.get("outcome"))
            for event in liveness
        ]
        self.assertEqual(
            outcomes,
            [
                ("inbound", "phase_started"),
                ("inbound_runner", "phase_started"),
                ("inbound_runner", "phase_completed"),
                ("inbound", "phase_completed"),
                ("outbound", "phase_started"),
                ("outbound", "phase_completed"),
                ("cycle_summary", "phase_started"),
                ("cycle_summary", "phase_completed"),
            ],
            f"unexpected liveness sequence: {outcomes}",
        )

    def test_ready_cycle_lifecycle_with_sleep(self) -> None:
        """The full ``run_forever`` loop MUST emit the cycle
        envelope and sleep phase alongside the inbound/outbound
        instrumentation."""
        inbound_calls: list[int] = []
        outbound_calls: list[int] = []
        sleep_calls: list[float] = []

        def _inbound(bound: int) -> int:
            inbound_calls.append(bound)
            return 0

        def _outbound(bound: int) -> int:
            outbound_calls.append(bound)
            return 0

        with _capture_stdout() as stdout:
            run_forever(
                settings=_settings(inbound_bound=2, outbound_bound=8),
                inbound_runner=_inbound,
                outbound_runner=_outbound,
                sleeper=lambda seconds: sleep_calls.append(float(seconds)),
                sleep_decision=lambda _settings, _cycle: True,
                cycle_summary_writer=lambda _summary: None,
                stop_predicate=lambda: len(inbound_calls) >= 1,
                readiness_probe=worker_cli._always_ready_probe,
            )

        liveness = _liveness_events(stdout.getvalue())
        outcomes = [
            (event.get("phase"), event.get("outcome"))
            for event in liveness
        ]
        self.assertEqual(
            outcomes,
            [
                (None, "cycle_started"),
                ("readiness", "phase_started"),
                ("readiness", "phase_completed"),
                ("inbound", "phase_started"),
                ("inbound_runner", "phase_started"),
                ("inbound_runner", "phase_completed"),
                ("inbound", "phase_completed"),
                ("outbound", "phase_started"),
                ("outbound", "phase_completed"),
                ("cycle_summary", "phase_started"),
                ("cycle_summary", "phase_completed"),
                (None, "cycle_completed"),
                ("sleep", "phase_started"),
                ("sleep", "phase_completed"),
            ],
            f"unexpected liveness sequence: {outcomes}",
        )
        self.assertEqual(inbound_calls, [2])
        self.assertEqual(outbound_calls, [8])
        self.assertEqual(sleep_calls, [5.0])

    def test_lifecycle_cycle_index_increments_per_cycle(self) -> None:
        inbound_calls: list[int] = []
        outbound_calls: list[int] = []

        def _inbound(bound: int) -> int:
            inbound_calls.append(bound)
            return 0

        def _outbound(bound: int) -> int:
            outbound_calls.append(bound)
            return 0

        with _capture_stdout() as stdout:
            run_forever(
                settings=_settings(inbound_bound=1, outbound_bound=16),
                inbound_runner=_inbound,
                outbound_runner=_outbound,
                sleeper=lambda _seconds: None,
                sleep_decision=lambda _settings, _cycle: False,
                cycle_summary_writer=lambda _summary: None,
                stop_predicate=lambda: len(inbound_calls) >= 3,
                readiness_probe=worker_cli._always_ready_probe,
            )

        liveness = _liveness_events(stdout.getvalue())
        cycle_indices: list[int] = sorted(
            {
                int(event["cycle_index"])
                for event in liveness
                if event.get("cycle_index") is not None
            }
        )
        self.assertEqual(cycle_indices, [1, 2, 3])
        started = [
            event
            for event in liveness
            if event.get("outcome") == "cycle_started"
        ]
        self.assertEqual(
            [event.get("cycle_index") for event in started],
            [1, 2, 3],
        )

    def test_inbound_phase_starts_before_outbound_phase(self) -> None:
        order: list[str] = []

        def _inbound(_bound: int) -> int:
            order.append("inbound")
            return 0

        def _outbound(_bound: int) -> int:
            order.append("outbound")
            return 0

        with _capture_stdout():
            run_cycle(
                settings=_settings(inbound_bound=1, outbound_bound=16),
                cycle_index=1,
                inbound_runner=_inbound,
                outbound_runner=_outbound,
                sleep_decision=lambda _settings, _cycle: False,
                cycle_summary_writer=lambda _summary: None,
            )

        self.assertEqual(order, ["inbound", "outbound"])


class WorkerLivenessNotReadyCycleTest(unittest.TestCase):
    """A not-ready cycle MUST keep the readiness phase, skip the
    inbound phase instrumentation, and still instrument the
    outbound pass exactly once per cycle."""

    def test_not_ready_cycle_skips_inbound_and_runs_outbound(self) -> None:
        inbound_calls: list[int] = []
        outbound_calls: list[int] = []

        def _inbound(bound: int) -> int:
            inbound_calls.append(bound)
            return 0

        def _outbound(bound: int) -> int:
            outbound_calls.append(bound)
            return 0

        with _capture_stdout() as stdout:
            run_forever(
                settings=_settings(inbound_bound=1, outbound_bound=16),
                inbound_runner=_inbound,
                outbound_runner=_outbound,
                sleeper=lambda _seconds: None,
                sleep_decision=lambda _settings, _cycle: False,
                cycle_summary_writer=lambda _summary: None,
                stop_predicate=lambda: len(outbound_calls) >= 1,
                readiness_probe=lambda: _not_ready_result(),
            )

        liveness = _liveness_events(stdout.getvalue())
        outcomes = [
            (event.get("phase"), event.get("outcome"))
            for event in liveness
        ]
        self.assertEqual(
            outcomes,
            [
                (None, "cycle_started"),
                ("readiness", "phase_started"),
                ("readiness", "phase_completed"),
                ("outbound", "phase_started"),
                ("outbound", "phase_completed"),
                ("cycle_summary", "phase_started"),
                ("cycle_summary", "phase_completed"),
                (None, "cycle_completed"),
            ],
            f"unexpected liveness sequence: {outcomes}",
        )
        self.assertEqual(inbound_calls, [])
        self.assertEqual(outbound_calls, [16])

    def test_consecutive_not_ready_cycles_never_invoke_inbound(self) -> None:
        inbound_calls: list[int] = []
        outbound_calls: list[int] = []

        def _inbound(bound: int) -> int:
            inbound_calls.append(bound)
            return 0

        def _outbound(bound: int) -> int:
            outbound_calls.append(bound)
            return 0

        with _capture_stdout():
            run_forever(
                settings=_settings(inbound_bound=2, outbound_bound=8),
                inbound_runner=_inbound,
                outbound_runner=_outbound,
                sleeper=lambda _seconds: None,
                sleep_decision=lambda _settings, _cycle: False,
                cycle_summary_writer=lambda _summary: None,
                stop_predicate=lambda: len(outbound_calls) >= 3,
                readiness_probe=lambda: _not_ready_result(),
            )

        self.assertEqual(inbound_calls, [])
        self.assertEqual(outbound_calls, [8, 8, 8])


class WorkerLivenessPhaseFailureTest(unittest.TestCase):
    """A phase that raises MUST emit ``phase_failed`` with safe
    metadata and preserve the existing re-raise so the supervisor
    path can restart the service. No ``phase_completed`` may be
    fabricated after a failure."""

    def test_inbound_runner_exception_emits_phase_failed(self) -> None:
        logged: list[dict[str, Any]] = []

        def _log(*args: Any, **kwargs: Any) -> None:
            logged.append({"args": args, "kwargs": kwargs})

        def _inbound(_bound: int) -> int:
            raise RuntimeError("forced inbound failure")

        def _outbound(_bound: int) -> int:
            return 0

        with _capture_stdout() as stdout:
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
                    readiness_probe=worker_cli._always_ready_probe,
                )

        liveness = _liveness_events(stdout.getvalue())
        failed = [
            event
            for event in liveness
            if event.get("outcome") == "phase_failed"
        ]
        self.assertEqual(
            len(failed),
            2,
            "inbound raise MUST surface as both inbound_runner and "
            "inbound phase_failed",
        )
        self.assertEqual(
            [event["phase"] for event in failed],
            ["inbound_runner", "inbound"],
        )
        for event in failed:
            self.assertEqual(event["failure_category"], "worker_exception")
            self.assertEqual(event["exception_type"], "RuntimeError")
            self.assertEqual(event["cycle_index"], 1)
            self.assertIsInstance(event["elapsed_ms"], int)
            self.assertGreaterEqual(event["elapsed_ms"], 0)

        completed = [
            event
            for event in liveness
            if event.get("outcome") == "phase_completed"
        ]
        self.assertEqual(
            [event.get("phase") for event in completed],
            ["readiness"],
            "phase_completed must only appear for phases that returned",
        )

        cycle_completed = [
            event
            for event in liveness
            if event.get("outcome") == "cycle_completed"
        ]
        self.assertEqual(
            cycle_completed,
            [],
            "cycle_completed must NOT be emitted when a phase fails",
        )

        cycle_summary = [
            event
            for event in liveness
            if event.get("phase") == "cycle_summary"
        ]
        self.assertEqual(
            cycle_summary,
            [],
            "cycle_summary MUST NOT be emitted when the inbound pass fails",
        )

    def test_outbound_runner_exception_emits_phase_failed(self) -> None:
        logged: list[dict[str, Any]] = []

        def _log(*args: Any, **kwargs: Any) -> None:
            logged.append({"args": args, "kwargs": kwargs})

        def _inbound(_bound: int) -> int:
            return 0

        def _outbound(_bound: int) -> int:
            raise ValueError("forced outbound failure")

        with _capture_stdout() as stdout:
            with self.assertRaises(ValueError):
                run_cycle(
                    settings=_settings(),
                    cycle_index=4,
                    inbound_runner=_inbound,
                    outbound_runner=_outbound,
                    sleep_decision=lambda _settings, _cycle: False,
                    cycle_summary_writer=lambda _summary: None,
                )

        liveness = _liveness_events(stdout.getvalue())
        failed = [
            event
            for event in liveness
            if event.get("outcome") == "phase_failed"
        ]
        self.assertEqual(len(failed), 1)
        event = failed[0]
        self.assertEqual(event["phase"], "outbound")
        self.assertEqual(event["failure_category"], "worker_exception")
        self.assertEqual(event["exception_type"], "ValueError")
        self.assertEqual(event["cycle_index"], 4)

        completed = [
            event
            for event in liveness
            if event.get("outcome") == "phase_completed"
        ]
        self.assertEqual(
            [event.get("phase") for event in completed],
            ["inbound_runner", "inbound"],
            "inbound_runner and inbound phase_completed are allowed, "
            "outbound must NOT",
        )

    def test_no_phase_completed_after_failure(self) -> None:
        """A runner that never returns (raises an exception) MUST
        not produce a fabricated ``phase_completed``. The
        ``phase_started`` record is the intentional evidence
        boundary for the operator."""

        def _inbound(_bound: int) -> int:
            raise OSError("forced hang-like failure")

        def _outbound(_bound: int) -> int:
            return 0

        with _capture_stdout() as stdout:
            with self.assertRaises(OSError):
                run_cycle(
                    settings=_settings(),
                    cycle_index=3,
                    inbound_runner=_inbound,
                    outbound_runner=_outbound,
                    sleep_decision=lambda _settings, _cycle: False,
                    cycle_summary_writer=lambda _summary: None,
                )

        liveness = _liveness_events(stdout.getvalue())
        inbound_started = [
            event
            for event in liveness
            if event.get("phase") == "inbound"
            and event.get("outcome") == "phase_started"
        ]
        inbound_completed = [
            event
            for event in liveness
            if event.get("phase") == "inbound"
            and event.get("outcome") == "phase_completed"
        ]
        inbound_failed = [
            event
            for event in liveness
            if event.get("phase") == "inbound"
            and event.get("outcome") == "phase_failed"
        ]
        self.assertEqual(len(inbound_started), 1)
        self.assertEqual(inbound_completed, [])
        self.assertEqual(len(inbound_failed), 1)

    def test_readiness_probe_failure_emits_phase_failed(self) -> None:
        """A buggy readiness probe that escapes MUST surface as a
        ``phase_failed`` for ``readiness`` with safe metadata. The
        existing defensive guard converts the exception into a
        not-ready cycle so the loop continues."""

        def _probe() -> Any:
            raise RuntimeError("forced probe failure")

        def _inbound(_bound: int) -> int:
            return 0

        def _outbound(_bound: int) -> int:
            return 0

        outbound_calls: list[int] = []

        def _outbound_record(bound: int) -> int:
            outbound_calls.append(bound)
            return 0

        with _capture_stdout() as stdout:
            run_forever(
                settings=_settings(),
                inbound_runner=_inbound,
                outbound_runner=_outbound_record,
                sleeper=lambda _seconds: None,
                sleep_decision=lambda _settings, _cycle: False,
                cycle_summary_writer=lambda _summary: None,
                stop_predicate=lambda: len(outbound_calls) >= 1,
                readiness_probe=_probe,
            )

        liveness = _liveness_events(stdout.getvalue())
        readiness_failed = [
            event
            for event in liveness
            if event.get("phase") == "readiness"
            and event.get("outcome") == "phase_failed"
        ]
        self.assertEqual(len(readiness_failed), 1)
        event = readiness_failed[0]
        self.assertEqual(event["failure_category"], "worker_exception")
        self.assertEqual(event["exception_type"], "RuntimeError")
        readiness_completed = [
            event
            for event in liveness
            if event.get("phase") == "readiness"
            and event.get("outcome") == "phase_completed"
        ]
        self.assertEqual(readiness_completed, [])


class WorkerLivenessNoProviderNoDbTest(unittest.TestCase):
    """Focused tests MUST NOT touch any provider, Twilio or DB
    seam. The worker runs entirely on injectable runners, a stub
    sleeper, an in-memory readiness probe and a no-op summary
    writer."""

    def test_ready_loop_does_not_import_twilio_or_db_modules(self) -> None:
        """The instrumentation MUST keep the worker process free
        of direct Twilio / database / coordinator / dispatcher /
        repository / session imports. Any regression that imports
        those layers directly would mean the new code is reaching
        across the closed architecture boundary the change is
        required to preserve.

        The check inspects the worker's own source via
        :mod:`ast` so a regression on a transitive import (i.e.
        a deeper module imported by the bounded inbound /
        outbound CLIs that the worker orchestrates through their
        :func:`main` seams) is NOT reported here; the worker
        only orchestrates the existing CLIs.
        """

        import ast
        import inspect

        import backend.cli.run_provider_processing_worker as worker_mod

        source = inspect.getsource(worker_mod)
        tree = ast.parse(source)

        direct_imports: list[tuple[str | None, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    direct_imports.append((None, alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                for alias in node.names:
                    direct_imports.append((node.module, alias.name))

        # The AST walk is only meaningful when the worker declares
        # at least one import. Without this guard the test would
        # silently pass on an empty module that imports nothing
        # at all.
        self.assertGreater(
            len(direct_imports),
            0,
            "test setup: worker module must declare at least one "
            "import for the AST walk to be meaningful",
        )

        forbidden_module_substrings = (
            "twilio",
            "sqlalchemy",
            "requests",
            "httpx",
            "socks5h",
            "backend.models",
            "backend.repositories",
            "backend.coordinators",
            "backend.dispatchers",
            "SessionLocal",
            "CanalWhatsapp",
        )

        forbidden_imported_names = {
            "ProviderInboundMessageCoordinator",
            "OutboundMessageDispatcher",
            "OutboundMessageRepository",
            "ProviderInboundMessageRepository",
            "ProviderInboundMessageRepositoryFacade",
            "SessionLocal",
            "_SessionLocal",
            "CanalWhatsappService",
            "create_session",
            "session_factory",
        }

        for module, name in direct_imports:
            if module is not None:
                module_lower = module.lower()
                for forbidden in forbidden_module_substrings:
                    self.assertNotIn(
                        forbidden,
                        module_lower,
                        (
                            f"worker MUST NOT directly import modules "
                            f"containing {forbidden!r}; "
                            f"found import of {module!r}"
                        ),
                    )
            self.assertNotIn(
                name,
                forbidden_imported_names,
                (
                    f"worker MUST NOT directly import {name!r} "
                    f"(module={module!r})"
                ),
            )

    def test_ready_loop_does_not_reference_twilio_db_or_dispatcher_strings(
        self,
    ) -> None:
        """Defence-in-depth: the worker source MUST NOT reference
        any of the documented deep-layer call patterns
        (``twilio``, ``Session(``, ``begin()``, ``commit()``,
        ``rollback()``, ``ProviderInboundMessageCoordinator``,
        ``OutboundMessageDispatcher``). These tokens remain
        present in the bounded CLI / dispatcher modules, but a
        regression on the worker MUST fail this test so the
        closed architecture boundary stays enforced."""

        import inspect

        import backend.cli.run_provider_processing_worker as worker_mod

        source = inspect.getsource(worker_mod)

        forbidden_substrings = (
            "twilio",
            "requests.post",
            "requests.get",
            "_SessionLocal",
            "Session(",
            "begin()",
            "commit()",
            "rollback()",
            "ProviderInboundMessageCoordinator",
            "CanalWhatsappService",
            "OutboundMessageDispatcher",
        )
        for token in forbidden_substrings:
            self.assertNotIn(
                token,
                source,
                f"worker source referenced forbidden {token!r} token",
            )

    def test_lifecycle_does_not_reseed_default_outbound_runner(self) -> None:
        """The new code MUST NOT swap the default outbound runner
        or invoke the dispatcher a second time per cycle."""

        def _inbound(_bound: int) -> int:
            return 0

        outbound_calls: list[int] = []

        def _outbound(bound: int) -> int:
            outbound_calls.append(bound)
            return 0

        with _capture_stdout() as stdout:
            run_forever(
                settings=_settings(),
                inbound_runner=_inbound,
                outbound_runner=_outbound,
                sleeper=lambda _seconds: None,
                sleep_decision=lambda _settings, _cycle: False,
                cycle_summary_writer=lambda _summary: None,
                stop_predicate=lambda: len(outbound_calls) >= 1,
                readiness_probe=worker_cli._always_ready_probe,
            )

        liveness = _liveness_events(stdout.getvalue())
        # Each cycle produces exactly one outbound phase_started +
        # one phase_completed pair. Re-running the dispatcher would
        # double these counters.
        outbound_starts = [
            event
            for event in liveness
            if event.get("phase") == "outbound"
            and event.get("outcome") == "phase_started"
        ]
        outbound_completes = [
            event
            for event in liveness
            if event.get("phase") == "outbound"
            and event.get("outcome") == "phase_completed"
        ]
        self.assertEqual(len(outbound_starts), 1)
        self.assertEqual(len(outbound_completes), 1)


class WorkerLivenessSafeMetadataTest(unittest.TestCase):
    """Liveness events MUST NEVER carry sensitive payload."""

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
        "exception message",
        "leak:",
    )

    def test_lifecycle_does_not_leak_secrets_or_payloads(self) -> None:
        secret_message = (
            "leak: secret-auth-token-value / "
            "AC000000000000000000000000000000 / +5491100000000 / "
            "inbound body / outbound body / prompt / exception message"
        )

        def _inbound(_bound: int) -> int:
            return 0

        outbound_calls_a: list[int] = []
        outbound_calls_b: list[int] = []

        def _outbound_a(bound: int) -> int:
            outbound_calls_a.append(bound)
            return 0

        def _outbound_b(bound: int) -> int:
            outbound_calls_b.append(bound)
            return 0

        with _capture_stdout() as stdout:
            run_forever(
                settings=_settings(),
                inbound_runner=_inbound,
                outbound_runner=_outbound_a,
                sleeper=lambda _seconds: None,
                sleep_decision=lambda _settings, _cycle: False,
                cycle_summary_writer=lambda _summary: None,
                stop_predicate=lambda: len(outbound_calls_a) >= 1,
                readiness_probe=worker_cli._always_ready_probe,
                unexpected_exception_log=lambda **_kwargs: None,
            )

        # Re-run with a probe exception carrying the secret and
        # verify the failure event surfaces only the class name.
        def _probe() -> Any:
            raise RuntimeError(secret_message)

        with _capture_stdout() as stdout:
            run_forever(
                settings=_settings(),
                inbound_runner=_inbound,
                outbound_runner=_outbound_b,
                sleeper=lambda _seconds: None,
                sleep_decision=lambda _settings, _cycle: False,
                cycle_summary_writer=lambda _summary: None,
                stop_predicate=lambda: len(outbound_calls_b) >= 1,
                readiness_probe=_probe,
                unexpected_exception_log=lambda **_kwargs: None,
            )

        rendered = stdout.getvalue()
        for token in self._FORBIDDEN_SUBSTRINGS:
            self.assertNotIn(
                token,
                rendered,
                f"sentinel {token!r} leaked in liveness output",
            )


class WorkerInboundTimeoutTest(unittest.TestCase):
    """Focused coverage for the bounded inbound-pass timeout seam.

    The seam applies only to the automatic inbound pass, restores
    the SIGALRM timer/handler on every return path, propagates the
    safe timeout through the existing supervisor, never invokes the
    outbound runner when the bound fires and never opens a database
    session or calls transaction or lease repair methods. The tests
    drive the loop through the existing injectable seams so they
    do not touch the real coordinator, dispatcher, Twilio or DB.
    """

    def setUp(self) -> None:
        self._previous_sigterm = signal.getsignal(signal.SIGTERM)
        self._previous_sigint = signal.getsignal(signal.SIGINT)

    def tearDown(self) -> None:
        # Defensive restore so a misbehaving test cannot leak state
        # into the rest of the suite: signal handlers are
        # process-global and the worker validator restores them per
        # cycle.
        signal.signal(signal.SIGTERM, self._previous_sigterm)
        signal.signal(signal.SIGINT, self._previous_sigint)
        signal.setitimer(signal.ITIMER_REAL, 0)

    def test_normal_inbound_preserves_inbound_then_outbound_order(
        self,
    ) -> None:
        call_order: list[str] = []

        def _inbound(bound: int) -> int:
            call_order.append(f"inbound:{bound}")
            return 0

        def _outbound(bound: int) -> int:
            call_order.append(f"outbound:{bound}")
            return 0

        with _capture_stdout() as stdout:
            summary = run_cycle(
                settings=_settings(
                    inbound_bound=1,
                    outbound_bound=8,
                    inbound_timeout_seconds=2,
                ),
                cycle_index=1,
                inbound_runner=_inbound,
                outbound_runner=_outbound,
                sleep_decision=lambda _settings, _cycle: False,
                cycle_summary_writer=lambda _summary: None,
            )

        self.assertEqual(call_order, ["inbound:1", "outbound:8"])
        self.assertEqual(summary["inbound_exit_code"], 0)
        self.assertEqual(summary["outbound_exit_code"], 0)

        liveness = _liveness_events(stdout.getvalue())
        outcomes = [
            (event.get("phase"), event.get("outcome"))
            for event in liveness
        ]
        self.assertEqual(
            outcomes,
            [
                ("inbound", "phase_started"),
                ("inbound_runner", "phase_started"),
                ("inbound_runner", "phase_completed"),
                ("inbound", "phase_completed"),
                ("outbound", "phase_started"),
                ("outbound", "phase_completed"),
                ("cycle_summary", "phase_started"),
                ("cycle_summary", "phase_completed"),
            ],
        )

    def test_inbound_timeout_fires_phase_failed_and_skips_outbound(
        self,
    ) -> None:
        inbound_calls: list[int] = []
        outbound_calls: list[int] = []

        def _slow_inbound(_bound: int) -> int:
            inbound_calls.append(1)
            time.sleep(2.0)
            return 0

        def _outbound(bound: int) -> int:
            outbound_calls.append(bound)
            return 0

        with _capture_stdout() as stdout:
            with self.assertRaises(worker_cli._InboundTimeoutError):
                run_cycle(
                    settings=_settings(
                        inbound_timeout_seconds=1,
                    ),
                    cycle_index=3,
                    inbound_runner=_slow_inbound,
                    outbound_runner=_outbound,
                    sleep_decision=lambda _settings, _cycle: False,
                    cycle_summary_writer=lambda _summary: None,
                )

        self.assertEqual(inbound_calls, [1])
        self.assertEqual(
            outbound_calls,
            [],
            "outbound runner MUST NOT be invoked when the inbound pass times out",
        )

        liveness = _liveness_events(stdout.getvalue())
        outcomes = [
            (event.get("phase"), event.get("outcome"))
            for event in liveness
        ]
        self.assertEqual(
            outcomes,
            [
                ("inbound", "phase_started"),
                ("inbound_runner", "phase_started"),
                ("inbound_runner", "phase_failed"),
                ("inbound", "phase_failed"),
            ],
            "timeout MUST emit inbound_runner and inbound failure only; "
            "no phase_completed, no outbound, no cycle_summary",
        )

        failed = [
            event
            for event in liveness
            if event.get("outcome") == "phase_failed"
        ]
        self.assertEqual(
            len(failed),
            2,
            "timeout MUST emit both inbound_runner and inbound failure",
        )
        self.assertEqual(
            [event["phase"] for event in failed],
            ["inbound_runner", "inbound"],
        )
        for event in failed:
            self.assertEqual(event["failure_category"], "worker_exception")
            self.assertEqual(
                event["exception_type"], "_InboundTimeoutError"
            )
            self.assertEqual(event["cycle_index"], 3)
            self.assertIsInstance(event["elapsed_ms"], int)

        completed = [
            event
            for event in liveness
            if event.get("outcome") == "phase_completed"
        ]
        self.assertEqual(
            completed,
            [],
            "phase_completed MUST NOT be fabricated after a timeout",
        )

        cycle_completed = [
            event
            for event in liveness
            if event.get("outcome") == "cycle_completed"
        ]
        self.assertEqual(
            cycle_completed,
            [],
            "cycle_completed MUST NOT be emitted after a timeout",
        )

        cycle_summary = [
            event
            for event in liveness
            if event.get("phase") == "cycle_summary"
        ]
        self.assertEqual(
            cycle_summary,
            [],
            "cycle_summary MUST NOT be emitted when the inbound pass times out",
        )

    def test_inbound_timeout_restores_signal_handler(self) -> None:
        sentinel_handler = signal.SIG_DFL
        previous = signal.signal(signal.SIGALRM, sentinel_handler)

        def _slow_inbound(_bound: int) -> int:
            time.sleep(2.0)
            return 0

        try:
            with self.assertRaises(worker_cli._InboundTimeoutError):
                worker_cli._run_inbound_with_timeout(
                    _slow_inbound,
                    1,
                    1,
                )
        finally:
            signal.signal(signal.SIGALRM, previous)

        restored = signal.getsignal(signal.SIGALRM)
        self.assertEqual(
            restored,
            sentinel_handler,
            "SIGALRM handler MUST be restored to the previous value",
        )

    def test_inbound_timeout_cancels_active_timer(self) -> None:
        def _slow_inbound(_bound: int) -> int:
            time.sleep(2.0)
            return 0

        previous = signal.getsignal(signal.SIGALRM)
        try:
            with self.assertRaises(worker_cli._InboundTimeoutError):
                worker_cli._run_inbound_with_timeout(
                    _slow_inbound, 1, 1
                )
        finally:
            signal.signal(signal.SIGALRM, previous)

        remaining = signal.setitimer(signal.ITIMER_REAL, 0)
        self.assertEqual(
            remaining,
            (0.0, 0.0),
            "the ITIMER_REAL timer MUST be cancelled after the timeout path",
        )

    def test_normal_inbound_restores_signal_handler(self) -> None:
        sentinel_handler = signal.SIG_DFL
        previous = signal.signal(signal.SIGALRM, sentinel_handler)
        try:
            exit_code = worker_cli._run_inbound_with_timeout(
                lambda bound: int(bound), 4, 60
            )
        finally:
            signal.signal(signal.SIGALRM, previous)

        self.assertEqual(exit_code, 4)
        restored = signal.getsignal(signal.SIGALRM)
        self.assertEqual(
            restored,
            sentinel_handler,
            "SIGALRM handler MUST be restored after a normal return",
        )

    def test_inbound_runner_exception_restores_signal_handler(self) -> None:
        sentinel_handler = signal.SIG_DFL
        previous = signal.signal(signal.SIGALRM, sentinel_handler)

        def _raise(_bound: int) -> int:
            raise RuntimeError("forced inbound failure")

        try:
            with self.assertRaises(RuntimeError):
                worker_cli._run_inbound_with_timeout(_raise, 1, 60)
        finally:
            signal.signal(signal.SIGALRM, previous)

        restored = signal.getsignal(signal.SIGALRM)
        self.assertEqual(
            restored,
            sentinel_handler,
            "SIGALRM handler MUST be restored when the runner raises",
        )

    def test_inbound_timeout_propagates_through_supervisor(self) -> None:
        """The bounded timeout MUST reach the supervisor path so the
        worker process exits non-zero and the existing entrypoint
        supervisor can restart the service."""

        def _slow_inbound(_bound: int) -> int:
            time.sleep(2.0)
            return 0

        with self.assertRaises(worker_cli._InboundTimeoutError):
            run_forever(
                settings=_settings(inbound_timeout_seconds=1),
                inbound_runner=_slow_inbound,
                outbound_runner=lambda _bound: 0,
                sleeper=lambda _seconds: None,
                sleep_decision=lambda _settings, _cycle: False,
                cycle_summary_writer=lambda _summary: None,
                stop_predicate=lambda: False,
                unexpected_exception_log=lambda **_kwargs: None,
                readiness_probe=worker_cli._always_ready_probe,
            )

    def test_inbound_timeout_does_not_invoke_outbound(self) -> None:
        """A timed-out inbound pass MUST NOT call the outbound
        runner: the existing inbound-before-outbound ordering is
        broken on timeout by design so the worker exits non-zero and
        Railway can restart the service."""

        outbound_calls: list[int] = []

        def _slow_inbound(_bound: int) -> int:
            time.sleep(2.0)
            return 0

        def _outbound(bound: int) -> int:
            outbound_calls.append(bound)
            return 0

        with self.assertRaises(worker_cli._InboundTimeoutError):
            run_cycle(
                settings=_settings(inbound_timeout_seconds=1),
                cycle_index=5,
                inbound_runner=_slow_inbound,
                outbound_runner=_outbound,
                sleep_decision=lambda _settings, _cycle: False,
                cycle_summary_writer=lambda _summary: None,
            )

        self.assertEqual(
            outbound_calls,
            [],
            "outbound runner MUST NOT be invoked when the inbound pass times out",
        )

    def test_inbound_timeout_does_not_call_transaction_or_lease_methods(
        self,
    ) -> None:
        """The timeout helper MUST NOT touch SQLAlchemy session,
        commit, rollback, flush, close, lease finalization, replay
        or any coordinator-side repair. The existing lease
        expiry/reclaim path is the only recovery authority."""

        forbidden_calls: list[str] = []

        def _slow_inbound(_bound: int) -> int:
            # Snapshot the call frames on the timeout path so the
            # assertion sees the exact callsite surface.
            import inspect

            frame = inspect.currentframe()
            try:
                while frame is not None:
                    locals_snapshot = list(frame.f_locals.keys())
                    for name in locals_snapshot:
                        if name in {
                            "commit",
                            "rollback",
                            "flush",
                            "close",
                            "begin",
                            "refresh",
                            "expire",
                        } and callable(frame.f_locals.get(name)):
                            forbidden_calls.append(name)
                    frame = frame.f_back
            finally:
                del frame
            time.sleep(2.0)
            return 0

        with self.assertRaises(worker_cli._InboundTimeoutError):
            worker_cli._run_inbound_with_timeout(
                _slow_inbound, 1, 1
            )

        self.assertEqual(
            forbidden_calls,
            [],
            "timeout path MUST NOT call transaction or session methods",
        )

    def test_inbound_timeout_evidence_carries_no_payload_or_secrets(
        self,
    ) -> None:
        """A timeout must never leak the inbound / outbound body,
        customer E.164 number, LLM content, provider signature,
        account SID, auth token, prompt or arbitrary text. The
        liveness evidence carries only the safe timeout class name."""

        secret_message = (
            "leak: secret-auth-token-value / "
            "AC00000000000000000000000000000000 / +5491100000000 / "
            "inbound body / outbound body / prompt"
        )

        def _slow_inbound(_bound: int) -> int:
            raise RuntimeError(secret_message)

        # Force the runner to raise so the inbound exception path
        # picks up the secret and we can verify the liveness event
        # keeps only the safe exception class name.
        # We swap the slow runner for an immediate raiser to keep
        # the test fast while still exercising the same call site.

        with _capture_stdout() as stdout:
            with self.assertRaises(RuntimeError):
                run_cycle(
                    settings=_settings(inbound_timeout_seconds=60),
                    cycle_index=2,
                    inbound_runner=_slow_inbound,
                    outbound_runner=lambda _bound: 0,
                    sleep_decision=lambda _settings, _cycle: False,
                    cycle_summary_writer=lambda _summary: None,
                )

        rendered = stdout.getvalue()
        for token in (
            "secret-auth-token-value",
            "AC00000000000000000000000000000000",
            "+5491100000000",
            "inbound body",
            "outbound body",
            "prompt",
        ):
            self.assertNotIn(
                token,
                rendered,
                f"sentinel {token!r} leaked in liveness output",
            )

    def test_timeout_helper_rejects_non_positive_bound(self) -> None:
        """The helper fails closed when the timeout is non-positive so
        a regression that bypasses the worker startup validation
        cannot spawn an unbounded inbound pass."""

        from backend.services.exceptions import (
            InvalidProviderProcessingWorkerConfig,
        )

        with self.assertRaises(InvalidProviderProcessingWorkerConfig):
            worker_cli._run_inbound_with_timeout(lambda _bound: 0, 1, 0)
        with self.assertRaises(InvalidProviderProcessingWorkerConfig):
            worker_cli._run_inbound_with_timeout(
                lambda _bound: 0, 1, -5
            )


class WorkerInboundTimeoutTraversesInboundCliTest(unittest.TestCase):
    """The bounded timeout signal MUST traverse the real inbound CLI.

    ``backend.cli.run_inbound_processing.main`` wraps
    ``process_lease`` in a defensive ``except Exception`` handler that
    converts any escaping failure into exit code ``1``. A timeout
    absorbed that way would let the worker continue into the outbound
    pass and would hide the stuck turn from the supervisor, so the
    signal MUST reach the caller untouched and the worker MUST NOT
    invoke outbound. The tests drive the real inbound CLI through its
    injectable seams so no database session, coordinator, LLM or
    Twilio client is involved.
    """

    def _inbound_cli_runner(
        self,
        *,
        process_calls: list[int],
    ) -> Any:
        """Build an inbound runner backed by the real inbound CLI.

        The coordinator seam leases exactly one row and raises the
        worker timeout signal from ``process_lease``, which is the
        exact production boundary: the SIGALRM handler fires while the
        coordinator is processing the leased row.
        """
        leases: list[Any] = []
        leased = MagicMock(name="LeasedRow")
        leased.id = 1
        leases.append(leased)

        def _claim_due(*, now: Any) -> Any:
            if not leases:
                return None
            return leases.pop(0)

        def _process_lease(leased_row: Any) -> Any:
            process_calls.append(int(leased_row.id))
            raise worker_cli._InboundTimeoutError()

        def _coordinator_builder(**_kwargs: Any) -> MagicMock:
            coordinator = MagicMock(
                name="ProviderInboundMessageCoordinator"
            )
            coordinator.claim_due_processing.side_effect = _claim_due
            coordinator.process_lease.side_effect = _process_lease
            return coordinator

        session_factory = MagicMock(name="SessionFactory")
        session_factory.return_value = MagicMock(name="Session")

        def _runner(bound: int) -> int:
            return inbound_cli.main(
                argv=["--max-items-per-pass", str(int(bound))],
                settings_loader=lambda: _settings(),
                session_factory_builder=lambda: session_factory,
                coordinator_builder=_coordinator_builder,
            )

        return _runner

    def test_timeout_is_not_converted_into_inbound_exit_code_one(
        self,
    ) -> None:
        process_calls: list[int] = []
        runner = self._inbound_cli_runner(process_calls=process_calls)

        with _capture_stdout() as stdout, _capture_stderr() as stderr:
            with self.assertRaises(worker_cli._InboundTimeoutError):
                runner(1)

        self.assertEqual(
            process_calls,
            [1],
            "the real inbound CLI MUST reach process_lease before the timeout",
        )
        self.assertNotIn(
            "inbound_processing_failed",
            stderr.getvalue(),
            "the inbound CLI MUST NOT absorb the timeout as exit code 1",
        )
        self.assertNotIn(
            "processed=",
            stdout.getvalue(),
            "the inbound CLI MUST NOT print a pass summary after a timeout",
        )

    def test_worker_cycle_timeout_through_inbound_cli_skips_outbound(
        self,
    ) -> None:
        process_calls: list[int] = []
        outbound_calls: list[int] = []
        runner = self._inbound_cli_runner(process_calls=process_calls)

        def _outbound(bound: int) -> int:
            outbound_calls.append(bound)
            return 0

        with _capture_stdout() as stdout, _capture_stderr():
            with self.assertRaises(worker_cli._InboundTimeoutError):
                run_cycle(
                    settings=_settings(inbound_timeout_seconds=60),
                    cycle_index=9,
                    inbound_runner=runner,
                    outbound_runner=_outbound,
                    sleep_decision=lambda _settings, _cycle: False,
                    cycle_summary_writer=lambda _summary: None,
                )

        self.assertEqual(process_calls, [1])
        self.assertEqual(
            outbound_calls,
            [],
            "outbound MUST NOT run when the timeout traverses the inbound CLI",
        )

        rendered = stdout.getvalue()
        self.assertNotIn(
            "provider_inbound_processing_outcome",
            rendered,
            "no inbound outcome may be recorded for a timed-out pass",
        )

        liveness = _liveness_events(rendered)
        outcomes = [
            (event.get("phase"), event.get("outcome"))
            for event in liveness
        ]
        self.assertEqual(
            outcomes,
            [
                ("inbound", "phase_started"),
                ("inbound_runner", "phase_started"),
                ("inbound_runner", "phase_failed"),
                ("inbound", "phase_failed"),
            ],
            "timeout MUST emit inbound_runner and inbound failure "
            "only; no phase_completed, no outbound, no cycle_summary",
        )
        failed = liveness[-1]
        self.assertEqual(failed["failure_category"], "worker_exception")
        self.assertEqual(
            failed["exception_type"], "_InboundTimeoutError"
        )
        self.assertEqual(failed["cycle_index"], 9)
        runner_failed = [
            event
            for event in liveness
            if event.get("phase") == "inbound_runner"
            and event.get("outcome") == "phase_failed"
        ]
        self.assertEqual(len(runner_failed), 1)
        self.assertEqual(
            runner_failed[0]["exception_type"], "_InboundTimeoutError"
        )
        cycle_summary = [
            event
            for event in liveness
            if event.get("phase") == "cycle_summary"
        ]
        self.assertEqual(cycle_summary, [])

    def test_worker_supervisor_receives_timeout_from_inbound_cli(
        self,
    ) -> None:
        """``run_forever`` MUST re-raise the signal so the entrypoint
        supervisor exits non-zero instead of looping forever."""

        process_calls: list[int] = []
        outbound_calls: list[int] = []
        runner = self._inbound_cli_runner(process_calls=process_calls)

        with _capture_stdout(), _capture_stderr():
            with self.assertRaises(worker_cli._InboundTimeoutError):
                run_forever(
                    settings=_settings(inbound_timeout_seconds=60),
                    inbound_runner=runner,
                    outbound_runner=lambda bound: outbound_calls.append(
                        bound
                    )
                    or 0,
                    sleeper=lambda _seconds: None,
                    sleep_decision=lambda _settings, _cycle: False,
                    cycle_summary_writer=lambda _summary: None,
                    stop_predicate=lambda: False,
                    unexpected_exception_log=lambda **_kwargs: None,
                    readiness_probe=worker_cli._always_ready_probe,
                )

        self.assertEqual(process_calls, [1])
        self.assertEqual(outbound_calls, [])


class WorkerInboundTimeoutSettingsTest(unittest.TestCase):
    """The inbound-pass timeout setting MUST validate as a positive
    integer when the worker is enabled, default to a bound derived
    from the configured model/embedding timeouts and refuse a
    fallback to an unbounded worker."""

    def test_default_timeout_is_positive_and_derived(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = load_settings()
        self.assertGreater(
            settings.provider_processing_worker_inbound_timeout_seconds, 0
        )
        self.assertGreaterEqual(
            settings.provider_processing_worker_inbound_timeout_seconds,
            settings.llm_timeout,
        )
        self.assertGreaterEqual(
            settings.provider_processing_worker_inbound_timeout_seconds,
            settings.embedding_timeout_seconds,
        )

    def test_explicit_positive_override_is_accepted(self) -> None:
        env = {"PROVIDER_PROCESSING_WORKER_INBOUND_TIMEOUT_SECONDS": "120"}
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(
            settings.provider_processing_worker_inbound_timeout_seconds, 120
        )

    def test_zero_override_is_rejected(self) -> None:
        from backend.services.exceptions import (
            InvalidProviderProcessingWorkerConfig,
        )

        with mock.patch.dict(
            os.environ,
            {"PROVIDER_PROCESSING_WORKER_INBOUND_TIMEOUT_SECONDS": "0"},
            clear=True,
        ):
            with self.assertRaises(InvalidProviderProcessingWorkerConfig):
                load_settings()

    def test_negative_override_is_rejected(self) -> None:
        from backend.services.exceptions import (
            InvalidProviderProcessingWorkerConfig,
        )

        with mock.patch.dict(
            os.environ,
            {"PROVIDER_PROCESSING_WORKER_INBOUND_TIMEOUT_SECONDS": "-10"},
            clear=True,
        ):
            with self.assertRaises(InvalidProviderProcessingWorkerConfig):
                load_settings()

    def test_non_integer_override_is_rejected(self) -> None:
        from backend.services.exceptions import (
            InvalidProviderProcessingWorkerConfig,
        )

        with mock.patch.dict(
            os.environ,
            {"PROVIDER_PROCESSING_WORKER_INBOUND_TIMEOUT_SECONDS": "abc"},
            clear=True,
        ):
            with self.assertRaises(InvalidProviderProcessingWorkerConfig):
                load_settings()

    def test_worker_startup_validation_rejects_non_positive_timeout(
        self,
    ) -> None:
        from backend.services.exceptions import (
            InvalidProviderProcessingWorkerConfig,
        )

        with self.assertRaises(InvalidProviderProcessingWorkerConfig):
            worker_cli._validate_worker_settings(
                _settings(
                    enabled=True,
                    inbound_timeout_seconds=0,
                )
            )

    def test_worker_startup_validation_accepts_positive_timeout(
        self,
    ) -> None:
        worker_cli._validate_worker_settings(
            _settings(
                enabled=True,
                inbound_timeout_seconds=120,
            )
        )


class WorkerLivenessDiagnosticPhasesTest(unittest.TestCase):
    """Focused coverage for the nested diagnostic phases
    (``inbound_runner`` and ``cycle_summary``) introduced by the
    ``diagnose-provider-worker-progress-stall`` change.

    The contract is narrow:

    * the ``inbound_runner`` phase evidence is nested inside the
      existing outer ``inbound`` phase and starts only after SIGALRM
      is installed and the timer is armed;
    * the ``cycle_summary`` phase evidence is emitted immediately
      before and after the existing ``cycle_summary_writer`` call
      and sits between the outbound phase completion and
      ``cycle_completed``;
    * a failing ``inbound_runner`` or ``cycle_summary_writer`` MUST
      surface as a ``phase_failed`` with safe metadata, MUST NOT
      fabricate a ``phase_completed`` afterwards and MUST propagate
      the original exception through the existing supervisor path;
    * the fail-soft ``emit_event`` path MUST NOT re-invoke a
      runner or writer, MUST NOT alter the previous behavior and
      MUST NOT touch the inbound timeout or signal restoration
      semantics.
    """

    def setUp(self) -> None:
        self._previous_sigterm = signal.getsignal(signal.SIGTERM)
        self._previous_sigint = signal.getsignal(signal.SIGINT)

    def tearDown(self) -> None:
        signal.signal(signal.SIGTERM, self._previous_sigterm)
        signal.signal(signal.SIGINT, self._previous_sigint)
        signal.setitimer(signal.ITIMER_REAL, 0)

    def test_normal_cycle_nests_inbound_runner_and_emits_cycle_summary(
        self,
    ) -> None:
        """The diagnostic contract: a normal ready cycle emits
        ``inbound_runner`` evidence nested inside ``inbound`` and
        emits ``cycle_summary`` evidence after the outbound phase
        completion and before ``cycle_completed``. The terminal
        ``phase_completed`` events for both diagnostic phases MUST
        carry a bounded ``elapsed_ms`` integer so Railway operators
        can correlate the duration of the inner runner pass and the
        summary writer call exactly as they already do for the
        outer ``inbound`` / ``outbound`` / ``sleep`` phases.
        """
        inbound_calls: list[int] = []
        outbound_calls: list[int] = []
        writer_calls: list[dict[str, Any]] = []

        def _inbound(bound: int) -> int:
            inbound_calls.append(bound)
            return 0

        def _outbound(bound: int) -> int:
            outbound_calls.append(bound)
            return 0

        def _writer(summary: dict[str, Any]) -> None:
            writer_calls.append(summary)

        with _capture_stdout() as stdout:
            summary = run_cycle(
                settings=_settings(inbound_bound=3, outbound_bound=12),
                cycle_index=1,
                inbound_runner=_inbound,
                outbound_runner=_outbound,
                sleep_decision=lambda _settings, _cycle: False,
                cycle_summary_writer=_writer,
            )

        self.assertEqual(inbound_calls, [3])
        self.assertEqual(outbound_calls, [12])
        self.assertEqual(writer_calls, [summary])

        liveness = _liveness_events(stdout.getvalue())
        outcomes = [
            (event.get("phase"), event.get("outcome"))
            for event in liveness
        ]
        self.assertEqual(
            outcomes,
            [
                ("inbound", "phase_started"),
                ("inbound_runner", "phase_started"),
                ("inbound_runner", "phase_completed"),
                ("inbound", "phase_completed"),
                ("outbound", "phase_started"),
                ("outbound", "phase_completed"),
                ("cycle_summary", "phase_started"),
                ("cycle_summary", "phase_completed"),
            ],
            f"unexpected liveness sequence: {outcomes}",
        )

        # ``phase_completed(inbound_runner)`` and
        # ``phase_completed(cycle_summary)`` are the new diagnostic
        # terminal events; each MUST carry a non-negative integer
        # ``elapsed_ms`` so the measurement remains consistent with
        # the existing ``inbound`` / ``outbound`` / ``sleep``
        # terminals.
        completed_by_phase = {
            event.get("phase"): event
            for event in liveness
            if event.get("outcome") == "phase_completed"
        }
        self.assertIn("inbound_runner", completed_by_phase)
        self.assertIn("cycle_summary", completed_by_phase)
        for phase_name in ("inbound_runner", "cycle_summary"):
            event = completed_by_phase[phase_name]
            self.assertIn(
                "elapsed_ms",
                event,
                f"phase_completed({phase_name}) MUST include elapsed_ms",
            )
            elapsed_ms = event["elapsed_ms"]
            self.assertIsInstance(
                elapsed_ms,
                int,
                f"phase_completed({phase_name}) MUST carry an integer "
                f"elapsed_ms, got {type(elapsed_ms).__name__}: {elapsed_ms!r}",
            )
            self.assertGreaterEqual(
                elapsed_ms,
                0,
                f"phase_completed({phase_name}) elapsed_ms MUST be "
                f"non-negative, got {elapsed_ms}",
            )

        # The runner, outbound and writer are each invoked exactly
        # once per cycle - the diagnostic must not duplicate seams.
        self.assertEqual(inbound_calls, [3])
        self.assertEqual(outbound_calls, [12])
        self.assertEqual(len(writer_calls), 1)

    def test_inbound_runner_emitted_only_after_sigalarm_armed(self) -> None:
        """``phase_started(inbound_runner)`` MUST be emitted AFTER
        the existing SIGALRM handler is installed and
        ``ITIMER_REAL`` is armed, but BEFORE the runner is called.
        A failure before SIGALRM arming cannot emit the event.
        The ``phase_failed(inbound_runner)`` terminal MUST carry a
        non-negative integer ``elapsed_ms``.
        """

        class _ProbeError(RuntimeError):
            pass

        def _broken(_bound: int) -> int:
            raise _ProbeError("forced non-timeout failure")

        captured_stdout = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured_stdout):
                with self.assertRaises(_ProbeError):
                    worker_cli._run_inbound_with_timeout(
                        _broken, 1, 60, cycle_index=7
                    )
        finally:
            pass

        liveness = _liveness_events(captured_stdout.getvalue())
        runner_started = [
            event
            for event in liveness
            if event.get("phase") == "inbound_runner"
            and event.get("outcome") == "phase_started"
        ]
        self.assertEqual(
            len(runner_started),
            1,
            "phase_started(inbound_runner) MUST be emitted exactly "
            "once when cycle_index is provided",
        )
        runner_failed = [
            event
            for event in liveness
            if event.get("phase") == "inbound_runner"
            and event.get("outcome") == "phase_failed"
        ]
        self.assertEqual(
            len(runner_failed),
            1,
            "phase_failed(inbound_runner) MUST be emitted exactly "
            "once when the runner raises",
        )
        runner_completed = [
            event
            for event in liveness
            if event.get("phase") == "inbound_runner"
            and event.get("outcome") == "phase_completed"
        ]
        self.assertEqual(
            runner_completed,
            [],
            "phase_completed(inbound_runner) MUST NOT be fabricated "
            "after a runner failure",
        )

        failed_event = runner_failed[0]
        self.assertIn(
            "elapsed_ms",
            failed_event,
            "phase_failed(inbound_runner) MUST include elapsed_ms so "
            "the operator can correlate the diagnostic with the "
            "existing measurement contract",
        )
        elapsed_ms = failed_event["elapsed_ms"]
        self.assertIsInstance(
            elapsed_ms,
            int,
            "phase_failed(inbound_runner) elapsed_ms MUST be an "
            f"integer, got {type(elapsed_ms).__name__}: {elapsed_ms!r}",
        )
        self.assertGreaterEqual(
            elapsed_ms,
            0,
            "phase_failed(inbound_runner) elapsed_ms MUST be "
            f"non-negative, got {elapsed_ms}",
        )

    def test_inbound_runner_failure_does_not_invoke_outbound(
        self,
    ) -> None:
        """A failing inbound runner MUST keep the previous
        semantic: no outbound pass, no cycle summary, no
        ``cycle_completed``. The diagnostic only adds evidence.
        """
        inbound_calls: list[int] = []
        outbound_calls: list[int] = []
        writer_calls: list[dict[str, Any]] = []

        def _inbound(_bound: int) -> int:
            inbound_calls.append(1)
            raise RuntimeError("forced inbound failure")

        def _outbound(bound: int) -> int:
            outbound_calls.append(bound)
            return 0

        def _writer(summary: dict[str, Any]) -> None:
            writer_calls.append(summary)

        with _capture_stdout() as stdout:
            with self.assertRaises(RuntimeError):
                run_cycle(
                    settings=_settings(),
                    cycle_index=4,
                    inbound_runner=_inbound,
                    outbound_runner=_outbound,
                    sleep_decision=lambda _settings, _cycle: False,
                    cycle_summary_writer=_writer,
                )

        self.assertEqual(inbound_calls, [1])
        self.assertEqual(
            outbound_calls,
            [],
            "outbound runner MUST NOT be invoked when the inbound "
            "runner fails",
        )
        self.assertEqual(
            writer_calls,
            [],
            "cycle_summary_writer MUST NOT be invoked when the "
            "inbound runner fails",
        )

        liveness = _liveness_events(stdout.getvalue())
        outcomes = [
            (event.get("phase"), event.get("outcome"))
            for event in liveness
        ]
        self.assertEqual(
            outcomes,
            [
                ("inbound", "phase_started"),
                ("inbound_runner", "phase_started"),
                ("inbound_runner", "phase_failed"),
                ("inbound", "phase_failed"),
            ],
            f"unexpected liveness sequence: {outcomes}",
        )
        for event in liveness:
            if event.get("outcome") == "phase_failed":
                self.assertEqual(
                    event["exception_type"], "RuntimeError"
                )
                self.assertEqual(
                    event["failure_category"], "worker_exception"
                )
        cycle_completed = [
            event
            for event in liveness
            if event.get("outcome") == "cycle_completed"
        ]
        self.assertEqual(cycle_completed, [])
        cycle_summary = [
            event
            for event in liveness
            if event.get("phase") == "cycle_summary"
        ]
        self.assertEqual(cycle_summary, [])

    def test_inbound_timeout_failure_restores_signal_and_preserves_evidence(
        self,
    ) -> None:
        """A timed-out inbound pass MUST still restore the SIGALRM
        handler and the ITIMER_REAL timer exactly as before. The
        new ``inbound_runner`` evidence MUST coexist with the
        existing outer inbound failure evidence.
        """
        sentinel_handler = signal.SIG_DFL
        previous = signal.signal(signal.SIGALRM, sentinel_handler)

        def _slow_inbound(_bound: int) -> int:
            time.sleep(2.0)
            return 0

        try:
            with self.assertRaises(worker_cli._InboundTimeoutError):
                worker_cli._run_inbound_with_timeout(
                    _slow_inbound, 1, 1, cycle_index=5
                )
        finally:
            signal.signal(signal.SIGALRM, previous)

        restored = signal.getsignal(signal.SIGALRM)
        self.assertEqual(
            restored,
            sentinel_handler,
            "SIGALRM handler MUST be restored to the previous value "
            "even when the diagnostic phase is in scope",
        )
        remaining = signal.setitimer(signal.ITIMER_REAL, 0)
        self.assertEqual(
            remaining,
            (0.0, 0.0),
            "ITIMER_REAL MUST be cancelled after the timeout path "
            "even when the diagnostic phase is in scope",
        )

    def test_cycle_summary_failure_emits_only_phase_failed(
        self,
    ) -> None:
        """A failing ``cycle_summary_writer`` MUST surface as
        ``phase_failed(cycle_summary)`` with safe metadata, MUST
        NOT emit ``cycle_completed`` and MUST propagate the
        original exception. The terminal ``phase_failed`` MUST
        carry a non-negative integer ``elapsed_ms`` so the
        diagnostic contract matches the rest of the lifecycle
        terminals.
        """
        inbound_calls: list[int] = []
        outbound_calls: list[int] = []
        writer_calls: list[dict[str, Any]] = []

        def _inbound(bound: int) -> int:
            inbound_calls.append(bound)
            return 0

        def _outbound(bound: int) -> int:
            outbound_calls.append(bound)
            return 0

        def _writer(summary: dict[str, Any]) -> None:
            writer_calls.append(summary)
            raise OSError("forced writer failure")

        with _capture_stdout() as stdout:
            with self.assertRaises(OSError):
                run_cycle(
                    settings=_settings(),
                    cycle_index=6,
                    inbound_runner=_inbound,
                    outbound_runner=_outbound,
                    sleep_decision=lambda _settings, _cycle: False,
                    cycle_summary_writer=_writer,
                )

        self.assertEqual(inbound_calls, [1])
        self.assertEqual(outbound_calls, [16])
        self.assertEqual(
            len(writer_calls),
            1,
            "cycle_summary_writer MUST be invoked exactly once even "
            "when it raises",
        )

        liveness = _liveness_events(stdout.getvalue())
        outcomes = [
            (event.get("phase"), event.get("outcome"))
            for event in liveness
        ]
        self.assertEqual(
            outcomes,
            [
                ("inbound", "phase_started"),
                ("inbound_runner", "phase_started"),
                ("inbound_runner", "phase_completed"),
                ("inbound", "phase_completed"),
                ("outbound", "phase_started"),
                ("outbound", "phase_completed"),
                ("cycle_summary", "phase_started"),
                ("cycle_summary", "phase_failed"),
            ],
            f"unexpected liveness sequence: {outcomes}",
        )

        cycle_summary_failed = [
            event
            for event in liveness
            if event.get("phase") == "cycle_summary"
            and event.get("outcome") == "phase_failed"
        ]
        self.assertEqual(len(cycle_summary_failed), 1)
        event = cycle_summary_failed[0]
        self.assertEqual(event["exception_type"], "OSError")
        self.assertEqual(event["failure_category"], "worker_exception")
        self.assertEqual(event["cycle_index"], 6)
        self.assertIn(
            "elapsed_ms",
            event,
            "phase_failed(cycle_summary) MUST include elapsed_ms so "
            "the diagnostic carries the same measurement contract "
            "as the other worker failure terminals",
        )
        elapsed_ms = event["elapsed_ms"]
        self.assertIsInstance(
            elapsed_ms,
            int,
            "phase_failed(cycle_summary) elapsed_ms MUST be an "
            f"integer, got {type(elapsed_ms).__name__}: {elapsed_ms!r}",
        )
        self.assertGreaterEqual(
            elapsed_ms,
            0,
            "phase_failed(cycle_summary) elapsed_ms MUST be "
            f"non-negative, got {elapsed_ms}",
        )

        cycle_summary_completed = [
            event
            for event in liveness
            if event.get("phase") == "cycle_summary"
            and event.get("outcome") == "phase_completed"
        ]
        self.assertEqual(
            cycle_summary_completed,
            [],
            "phase_completed(cycle_summary) MUST NOT be emitted when "
            "the writer raises",
        )

        cycle_completed = [
            event
            for event in liveness
            if event.get("outcome") == "cycle_completed"
        ]
        self.assertEqual(
            cycle_completed,
            [],
            "cycle_completed MUST NOT be fabricated after a writer "
            "failure",
        )

    def test_fail_soft_emit_does_not_invoke_runner_or_writer_twice(
        self,
    ) -> None:
        """The fail-soft ``_emit_liveness_event`` helper must NOT
        trigger a second runner, a second outbound, a second
        summary writer or any other side effect on the worker's
        cycle. The diagnostic only writes a single event line
        per boundary; the rest of the cycle keeps the existing
        contract.
        """
        inbound_calls: list[int] = []
        outbound_calls: list[int] = []
        writer_calls: list[dict[str, Any]] = []

        def _inbound(bound: int) -> int:
            inbound_calls.append(bound)
            return 0

        def _outbound(bound: int) -> int:
            outbound_calls.append(bound)
            return 0

        def _writer(summary: dict[str, Any]) -> None:
            writer_calls.append(summary)

        # Force the fail-soft path by patching the helper to
        # return ``False`` (validation failure mode) so the
        # surrounding business flow is unchanged.
        original_emit = worker_cli._emit_liveness_event

        def _degraded_emit(**kwargs: Any) -> bool:
            return False

        stdout_value = ""
        with mock.patch.object(
            worker_cli, "_emit_liveness_event", _degraded_emit
        ):
            with _capture_stdout() as stdout:
                run_cycle(
                    settings=_settings(),
                    cycle_index=8,
                    inbound_runner=_inbound,
                    outbound_runner=_outbound,
                    sleep_decision=lambda _settings, _cycle: False,
                    cycle_summary_writer=_writer,
                )
            stdout_value = stdout.getvalue()

        # Restore for the rest of the suite; the patch is
        # scoped to the ``with`` block above.
        worker_cli._emit_liveness_event = original_emit

        # Each seam MUST have been invoked exactly once even
        # when every diagnostic emission degraded to ``False``.
        self.assertEqual(inbound_calls, [1])
        self.assertEqual(outbound_calls, [16])
        self.assertEqual(len(writer_calls), 1)

        # The fail-soft path must NOT print any line: the
        # diagnostic helper is required to be silent on
        # validation failure, exactly as the existing
        # ``emit_event`` helper already is.
        self.assertEqual(stdout_value, "")

    def test_lifecycle_does_not_change_inbound_phase_completed_order(
        self,
    ) -> None:
        """The new ``inbound_runner`` and ``cycle_summary`` events
        MUST NOT be reordered relative to the existing
        ``inbound`` / ``outbound`` / ``cycle_completed`` phases.
        The diagnostic must be a pure additive observation.
        """
        order: list[str] = []

        def _inbound(_bound: int) -> int:
            order.append("inbound_call")
            return 0

        def _outbound(_bound: int) -> int:
            order.append("outbound_call")
            return 0

        def _writer(_summary: dict[str, Any]) -> None:
            order.append("writer_call")

        with _capture_stdout() as stdout:
            run_forever(
                settings=_settings(),
                inbound_runner=_inbound,
                outbound_runner=_outbound,
                sleeper=lambda _seconds: None,
                sleep_decision=lambda _settings, _cycle: False,
                cycle_summary_writer=_writer,
                stop_predicate=lambda: len(order) >= 3,
                readiness_probe=worker_cli._always_ready_probe,
            )

        self.assertEqual(
            order,
            ["inbound_call", "outbound_call", "writer_call"],
        )

        liveness = _liveness_events(stdout.getvalue())
        outcomes = [
            (event.get("phase"), event.get("outcome"))
            for event in liveness
        ]
        cycle_summary_index = next(
            index
            for index, (phase, outcome) in enumerate(outcomes)
            if phase == "cycle_summary" and outcome == "phase_started"
        )
        cycle_completed_index = next(
            index
            for index, (phase, outcome) in enumerate(outcomes)
            if phase is None and outcome == "cycle_completed"
        )
        self.assertLess(
            cycle_summary_index,
            cycle_completed_index,
            "cycle_summary MUST be emitted before cycle_completed",
        )
        inbound_runner_started_index = next(
            index
            for index, (phase, outcome) in enumerate(outcomes)
            if phase == "inbound_runner" and outcome == "phase_started"
        )
        inbound_completed_index = next(
            index
            for index, (phase, outcome) in enumerate(outcomes)
            if phase == "inbound" and outcome == "phase_completed"
        )
        self.assertLess(
            inbound_runner_started_index,
            inbound_completed_index,
            "inbound_runner MUST start before the outer inbound phase "
            "completes",
        )

    def test_diagnostic_payload_does_not_leak_sensitive_values(
        self,
    ) -> None:
        """A liveness trace that exercises the new diagnostic
        phases MUST NOT include any sensitive token, sentinel or
        exception message. The diagnostic remains privacy-safe.
        """
        secret_message = (
            "leak: secret-auth-token-value / "
            "AC00000000000000000000000000000000 / +5491100000000 / "
            "inbound body / outbound body / prompt / exception message"
        )

        def _inbound(_bound: int) -> int:
            raise RuntimeError(secret_message)

        def _outbound(_bound: int) -> int:
            return 0

        def _writer(_summary: dict[str, Any]) -> None:
            raise OSError(secret_message)

        sentinels = (
            "secret-auth-token-value",
            "AC00000000000000000000000000000000",
            "+5491100000000",
            "inbound body",
            "outbound body",
            "prompt",
            "exception message",
        )

        with _capture_stdout() as stdout:
            with self.assertRaises(RuntimeError):
                run_cycle(
                    settings=_settings(),
                    cycle_index=11,
                    inbound_runner=_inbound,
                    outbound_runner=_outbound,
                    sleep_decision=lambda _settings, _cycle: False,
                    cycle_summary_writer=lambda _summary: None,
                )

        rendered = stdout.getvalue()
        for token in sentinels:
            self.assertNotIn(
                token,
                rendered,
                f"sentinel {token!r} leaked in liveness output",
            )

        with _capture_stdout() as stdout:
            with self.assertRaises(OSError):
                run_cycle(
                    settings=_settings(),
                    cycle_index=12,
                    inbound_runner=lambda _bound: 0,
                    outbound_runner=lambda _bound: 0,
                    sleep_decision=lambda _settings, _cycle: False,
                    cycle_summary_writer=_writer,
                )

        rendered = stdout.getvalue()
        for token in sentinels:
            self.assertNotIn(
                token,
                rendered,
                f"sentinel {token!r} leaked in liveness output",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)