"""Automatic provider-processing worker CLI entry point.

The CLI is the opt-in long-running orchestrator that drives the
existing ``run_inbound_processing`` and ``run_outbound_dispatch``
passes on a fixed cadence so a valid WhatsApp receipt reaches its
existing outbox and provider delivery without an operator invoking
two CLIs by hand.

The CLI performs five narrow responsibilities:

1. Load ``Settings`` once and refuse to start when the flag is
   enabled with a non-positive interval, a non-positive inbound
   bound, a non-positive outbound bound, or when the existing
   outbound dispatch configuration is missing or invalid. The
   startup check runs BEFORE ``uvicorn`` accepts traffic in the
   Railway entrypoint, so a misconfigured deployment never
   silently degrades to manual operation.
2. Keep a process-local ``ollama_ready`` flag, initially ``False``.
   The first inbound pass is gated on a controlled fixed-input
   generate + embedding readiness probe
   (:func:`backend.scripts.check_railway_ollama_contracts.check_ollama_readiness`).
   The probe never opens a database session, never sends a provider
   message, never mutates business state. Until the probe passes,
   inbound is skipped, the bounded outbound pass still runs, and the
   worker only records a safe ``not_ready`` category plus the probe
   duration. After the first success the flag is cached for the
   worker process and subsequent cycles run the existing bounded
   inbound-then-outbound sequence without re-probing.
3. On every cycle, invoke the existing bounded inbound CLI with
   the configured inbound bound (only when ``ollama_ready`` is
   ``True``), then invoke the existing bounded outbound CLI with
   the configured outbound bound (every cycle). The worker never
   claims a row, opens a business transaction or sends through
   Twilio directly; those seams remain owned by the coordinator /
   dispatcher.
4. Sleep for the configured positive interval regardless of the
   pass outcomes. ``no_due_row``, retryable and terminal results
   are normal business outcomes: they never stop the loop and
   never alter lease / retry / ordering semantics outside the
   existing pass implementation.
5. Emit only safe cycle-level summaries: ready flag, safe not-ready
   category, configured bounds, exit codes, sleep decision, probe
   duration. The summary never contains inbound / outbound bodies,
   customer E.164 numbers, LLM content, provider signatures, account
   SIDs, tokens, probe text, vectors or environment dumps.

The CLI is deliberately minimal:

* no FastAPI endpoint, no inline webhook handling;
* no scheduler, no Redis / Celery / SQS / cron dependency;
* no parallel pipeline, no second queue, no daemonization;
* no subprocess invocation of the existing CLIs - the worker
  calls their ``main()`` seams directly through injectable
  factories so focused tests can run the loop without spawning
  child processes or sleeping.

The CLI exposes eight injectable seams so focused tests can drive
the loop without touching the real ``Settings``, the real CLIs,
the real sleep, the real summary printer or the real readiness
probe:

* ``settings_loader`` returns the ``Settings`` instance;
* ``inbound_runner`` invokes one bounded inbound pass and returns
  its exit code;
* ``outbound_runner`` invokes one bounded outbound pass and
  returns its exit code;
* ``sleeper`` sleeps for the supplied positive number of seconds;
* ``sleep_decision`` decides whether the loop should sleep after a
  cycle (always ``True`` by default);
* ``cycle_summary_writer`` writes one safe per-cycle summary
  line;
* ``stop_predicate`` returns ``True`` to stop the loop (used by
  tests to bound cycles without sleeping);
* ``readiness_probe`` returns one :class:`OllamaReadinessResult`
  and is consulted only while ``ollama_ready`` is ``False``; once
  the result is ready the flag is cached and the probe is never
  called again for the lifetime of the process.

Production code uses the defaults. Tests substitute the seams.
"""
from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from typing import Any

from backend.cli.run_inbound_processing import (
    main as run_inbound_processing_main,
)
from backend.cli.run_outbound_dispatch import (
    _validate_outbound_settings,
)
from backend.cli.run_outbound_dispatch import (
    main as run_outbound_dispatch_main,
)
from backend.config.settings import (
    DEFAULT_PROVIDER_PROCESSING_WORKER_ENABLED,
    DEFAULT_PROVIDER_PROCESSING_WORKER_INBOUND_MAX_ITEMS_PER_PASS,
    DEFAULT_PROVIDER_PROCESSING_WORKER_OUTBOUND_MAX_ATTEMPTS_PER_PASS,
    DEFAULT_PROVIDER_PROCESSING_WORKER_POLL_INTERVAL_SECONDS,
    Settings,
    load_settings,
)
from backend.scripts.check_railway_ollama_contracts import (
    OllamaReadinessResult,
    check_ollama_readiness,
)
from backend.services.exceptions import (
    InvalidProviderProcessingWorkerConfig,
)

logger = logging.getLogger(__name__)


DEFAULT_CYCLE_INTERVAL_SECONDS = (
    DEFAULT_PROVIDER_PROCESSING_WORKER_POLL_INTERVAL_SECONDS
)


InboundRunner = Callable[[int], int]
OutboundRunner = Callable[[int], int]
Sleeper = Callable[[float], None]
CycleSummaryWriter = Callable[[dict[str, Any]], None]
SettingsLoader = Callable[[], Settings]
ReadinessProbe = Callable[[], OllamaReadinessResult]


_NOT_READY_FALLBACK_RESULT = OllamaReadinessResult(
    ready=False,
    generate_category="probe_unexpected_error",
    embed_category="probe_unexpected_error",
    embed_dimension=None,
    generate_duration_seconds=0.0,
    embed_duration_seconds=0.0,
)


def _default_settings_loader() -> Settings:
    return load_settings()


def _default_inbound_runner(max_items_per_pass: int) -> int:
    return run_inbound_processing_main(
        argv=["--max-items-per-pass", str(int(max_items_per_pass))],
    )


def _default_outbound_runner(max_attempts_per_pass: int) -> int:
    return run_outbound_dispatch_main(
        argv=[
            "--max-attempts-per-pass",
            str(int(max_attempts_per_pass)),
        ],
    )


def _default_sleeper(seconds: float) -> None:
    time.sleep(float(seconds))


def _default_sleep_decision(_settings: Settings, _cycle_index: int) -> bool:
    return True


def _default_stop_predicate() -> bool:
    return False


def _default_readiness_probe_factory(settings: Settings) -> ReadinessProbe:
    """Default factory that builds a probe bound to ``settings``.

    The factory exists so ``main()`` can build a probe from the same
    ``Settings`` instance used for the rest of the worker loop while
    focused tests can substitute an arbitrary probe.
    """
    captured_settings = settings

    def _probe() -> OllamaReadinessResult:
        return check_ollama_readiness(settings=captured_settings)

    return _probe


def _always_ready_probe() -> OllamaReadinessResult:
    """Probe stub used by tests that need to bypass the gate.

    Returns a successful readiness result so the worker's
    ``ollama_ready`` flag flips to ``True`` on the first cycle and
    the loop behaves exactly as it did before the gate existed.
    """
    return OllamaReadinessResult(
        ready=True,
        generate_category="passed",
        embed_category="passed",
        embed_dimension=None,
        generate_duration_seconds=0.0,
        embed_duration_seconds=0.0,
    )


def _default_cycle_summary_writer(summary: dict[str, Any]) -> None:
    """Default cycle summary writer.

    Emits one line per cycle containing only safe metadata: cycle
    index, readiness flag, optional safe not-ready category, optional
    probe duration, inbound / outbound exit codes (or ``None`` when
    inbound was skipped), configured bounds, sleep decision and
    configured poll interval. The summary NEVER contains the
    inbound / outbound body, the customer E.164 number, the LLM
    content, the provider signature, the account SID, the auth
    token, the probe text, the embedding vector or any environment
    dump.
    """
    parts: list[str] = [
        "provider_worker_cycle",
        f"cycle_index={summary['cycle_index']}",
        f"ollama_ready={summary['ollama_ready']}",
    ]
    if summary.get("not_ready_category") is not None:
        parts.append(
            f"not_ready_category={summary['not_ready_category']}"
        )
    if summary.get("probe_duration_seconds") is not None:
        parts.append(
            f"probe_duration_seconds={summary['probe_duration_seconds']}"
        )
    parts.extend(
        [
            f"inbound_exit_code={summary['inbound_exit_code']}",
            f"outbound_exit_code={summary['outbound_exit_code']}",
            f"inbound_bound={summary['inbound_bound']}",
            f"outbound_bound={summary['outbound_bound']}",
            f"poll_interval_seconds={summary['poll_interval_seconds']}",
            f"sleep_after={summary['sleep_after']}",
        ]
    )
    print(" ".join(parts), file=sys.stdout)


def _default_unexpected_exception_log(
    *, cycle_index: int, reason: str, exc: BaseException
) -> None:
    """Log an unexpected worker exception without leaking any
    payload or provider/customer content.

    The record is intentionally minimal: a fixed event name, the
    cycle index and the exception class name. The function MUST
    NOT call ``logger.exception`` (which attaches ``exc_info`` and
    therefore the formatted traceback, including ``str(exc)``) and
    MUST NOT include the exception message, the exception
    arguments, the inbound/outbound body, the customer E.164
    number, the LLM content, the provider signature, the account
    SID, the auth token, the proxy URL, the Tailscale hostname or
    any environment dump.

    The ``exc`` parameter is accepted for caller/contract
    compatibility with :func:`run_forever` and is intentionally
    unused: the only safe piece of information about an
    unexpected exception is its class name, already passed via
    ``reason``.
    """
    del exc
    logger.error(
        "provider_processing_worker_unexpected_failure",
        extra={
            "cycle_index": int(cycle_index),
            "reason": str(reason),
        },
    )


def _validate_worker_settings(settings: Settings) -> None:
    """Validate worker settings when the worker is enabled.

    Refuses non-positive interval or bounds so the operator gets a
    typed error before ``uvicorn`` accepts traffic. The check is
    independent of the existing outbound dispatch validation:
    enabling the worker with bad outbound configuration must also
    fail startup, even when the worker-only bounds are positive.
    """
    if not settings.provider_processing_worker_enabled:
        return
    if settings.provider_processing_worker_poll_interval_seconds <= 0:
        raise InvalidProviderProcessingWorkerConfig(
            "PROVIDER_PROCESSING_WORKER_POLL_INTERVAL_SECONDS must be "
            "greater than zero when the worker is enabled"
        )
    if (
        settings.provider_processing_worker_inbound_max_items_per_pass
        <= 0
    ):
        raise InvalidProviderProcessingWorkerConfig(
            "PROVIDER_PROCESSING_WORKER_INBOUND_MAX_ITEMS_PER_PASS must "
            "be greater than zero when the worker is enabled"
        )
    if (
        settings.provider_processing_worker_outbound_max_attempts_per_pass
        <= 0
    ):
        raise InvalidProviderProcessingWorkerConfig(
            "PROVIDER_PROCESSING_WORKER_OUTBOUND_MAX_ATTEMPTS_PER_PASS "
            "must be greater than zero when the worker is enabled"
        )


def validate_worker_startup_or_exit() -> None:
    """Startup-time validation entry point used by the entrypoint.

    Loads the real ``Settings`` and runs the worker-only
    validation plus the existing outbound dispatch validation. A
    failure raises :class:`InvalidProviderProcessingWorkerConfig`
    so the entrypoint can fail before ``uvicorn`` accepts traffic.
    """
    settings = load_settings()
    _validate_worker_settings(settings)
    if settings.provider_processing_worker_enabled:
        _validate_outbound_settings(settings)


def _build_cycle_summary(
    *,
    cycle_index: int,
    inbound_exit_code: int | None,
    outbound_exit_code: int,
    settings: Settings,
    sleep_after: bool,
    ollama_ready: bool = True,
    not_ready_category: str | None = None,
    probe_duration_seconds: float | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "cycle_index": int(cycle_index),
        "inbound_exit_code": inbound_exit_code,
        "outbound_exit_code": int(outbound_exit_code),
        "inbound_bound": int(
            settings.provider_processing_worker_inbound_max_items_per_pass
        ),
        "outbound_bound": int(
            settings.provider_processing_worker_outbound_max_attempts_per_pass
        ),
        "poll_interval_seconds": int(
            settings.provider_processing_worker_poll_interval_seconds
        ),
        "sleep_after": bool(sleep_after),
        "ollama_ready": bool(ollama_ready),
    }
    if not_ready_category is not None:
        summary["not_ready_category"] = str(not_ready_category)
    if probe_duration_seconds is not None:
        summary["probe_duration_seconds"] = float(probe_duration_seconds)
    return summary


def run_cycle(
    *,
    settings: Settings,
    cycle_index: int,
    inbound_runner: InboundRunner,
    outbound_runner: OutboundRunner,
    sleep_decision: Callable[[Settings, int], bool],
    cycle_summary_writer: CycleSummaryWriter,
    ollama_ready: bool = True,
    not_ready_category: str | None = None,
    probe_duration_seconds: float | None = None,
) -> dict[str, Any]:
    """Run one inbound-then-outbound cycle.

    When ``ollama_ready`` is ``False`` the inbound pass is SKIPPED —
    the bounded outbound pass always runs. ``inbound_exit_code``
    reports ``None`` when inbound was skipped. The bounded outbound
    pass uses the configured outbound bound independently of the
    inbound gate, so ready outbound work is never delayed by the
    readiness probe.

    Returns the safe summary dictionary written to the cycle
    summary writer. The function never raises on business
    outcomes: pass exit codes are recorded but do not interrupt
    the loop. Exceptions raised by the runners or the writer
    propagate to the caller so the supervisor path can restart
    the service.
    """
    if ollama_ready:
        inbound_exit_code: int | None = int(
            inbound_runner(
                int(
                    settings.provider_processing_worker_inbound_max_items_per_pass
                )
            )
        )
    else:
        inbound_exit_code = None

    outbound_exit_code = int(
        outbound_runner(
            int(
                settings.provider_processing_worker_outbound_max_attempts_per_pass
            )
        )
    )
    sleep_after = bool(sleep_decision(settings, int(cycle_index)))
    summary = _build_cycle_summary(
        cycle_index=int(cycle_index),
        inbound_exit_code=inbound_exit_code,
        outbound_exit_code=outbound_exit_code,
        settings=settings,
        sleep_after=sleep_after,
        ollama_ready=bool(ollama_ready),
        not_ready_category=not_ready_category,
        probe_duration_seconds=probe_duration_seconds,
    )
    cycle_summary_writer(summary)
    return summary


def run_forever(
    *,
    settings: Settings,
    inbound_runner: InboundRunner,
    outbound_runner: OutboundRunner,
    sleeper: Sleeper,
    sleep_decision: Callable[[Settings, int], bool] | None = None,
    cycle_summary_writer: CycleSummaryWriter | None = None,
    stop_predicate: Callable[[], bool] | None = None,
    unexpected_exception_log: Callable[..., None] | None = None,
    readiness_probe: ReadinessProbe | None = None,
) -> int:
    """Run the worker loop until ``stop_predicate`` returns ``True``.

    The function maintains one process-local ``ollama_ready`` flag,
    initially ``False``. While the flag is ``False`` the readiness
    probe is consulted once per cycle; the bounded outbound pass
    always runs. The first cycle whose probe reports ``ready=True``
    flips the flag, runs the normal inbound-then-outbound cycle and
    never probes again for the lifetime of the process.

    The function NEVER catches business outcomes from the runners:
    their exit codes are recorded in the cycle summary and the
    loop continues. Unexpected exceptions are logged safely and
    re-raised so the Railway entrypoint supervisor can stop the
    web process and exit non-zero for service restart.

    When ``readiness_probe`` is ``None`` the gate is bypassed and
    the loop runs the existing inbound-then-outbound sequence on
    every cycle, preserving backward compatibility for focused
    tests and direct ``run_forever`` callers that drive the loop
    with stubs.

    Returns the number of completed cycles when ``stop_predicate``
    becomes truthy.
    """
    sleep_decision_fn = sleep_decision or _default_sleep_decision
    cycle_summary_writer_fn = (
        cycle_summary_writer or _default_cycle_summary_writer
    )
    stop_predicate_fn = stop_predicate or _default_stop_predicate
    unexpected_log = (
        unexpected_exception_log or _default_unexpected_exception_log
    )

    ollama_ready = False
    readiness_probe_fn: ReadinessProbe | None = readiness_probe
    if readiness_probe_fn is None:
        # No probe provided: skip the gate entirely. This preserves
        # backward compatibility for focused tests and direct
        # ``run_forever`` callers that drive the loop with stubs.
        ollama_ready = True

    cycle_index = 0
    while not stop_predicate_fn():
        cycle_index += 1
        readiness_category: str | None = None
        probe_duration_seconds: float | None = None
        if not ollama_ready:
            assert readiness_probe_fn is not None
            try:
                readiness_result = readiness_probe_fn()
            except Exception as exc:  # noqa: BLE001 - probe must never crash the worker
                # Defensive guard: the readiness seam is required to
                # swallow every exception internally. If a buggy
                # probe ever escapes, log safely and treat the cycle
                # as not-ready so the worker loop and the web service
                # never crash on probe failures.
                unexpected_log(
                    cycle_index=cycle_index,
                    reason=type(exc).__name__,
                    exc=exc,
                )
                readiness_result = _NOT_READY_FALLBACK_RESULT
            if readiness_result.ready:
                ollama_ready = True
                logger.info(
                    "provider_processing_worker_ollama_ready",
                    extra={
                        "cycle_index": int(cycle_index),
                        "probe_duration_seconds": float(
                            readiness_result.generate_duration_seconds
                            + readiness_result.embed_duration_seconds
                        ),
                    },
                )
            else:
                readiness_category = _select_not_ready_category(
                    readiness_result
                )
                probe_duration_seconds = float(
                    readiness_result.generate_duration_seconds
                    + readiness_result.embed_duration_seconds
                )
        try:
            summary = run_cycle(
                settings=settings,
                cycle_index=cycle_index,
                inbound_runner=inbound_runner,
                outbound_runner=outbound_runner,
                sleep_decision=sleep_decision_fn,
                cycle_summary_writer=cycle_summary_writer_fn,
                ollama_ready=ollama_ready,
                not_ready_category=readiness_category,
                probe_duration_seconds=probe_duration_seconds,
            )
        except BaseException as exc:
            unexpected_log(
                cycle_index=cycle_index,
                reason=type(exc).__name__,
                exc=exc,
            )
            raise

        if summary["sleep_after"]:
            sleeper(
                float(settings.provider_processing_worker_poll_interval_seconds)
            )
    return cycle_index


def _select_not_ready_category(
    readiness_result: OllamaReadinessResult,
) -> str:
    """Pick the single safe category for a not-ready probe.

    The probe is short-circuit, so the generate outcome is reported
    first whenever it differs from ``"passed"``. When the generate
    probe passes but the embed probe fails, the embed category is
    surfaced. This mirrors the diagnostic CLI: the operator sees
    which probe failed first.
    """
    if readiness_result.generate_category != "passed":
        return str(readiness_result.generate_category)
    return str(readiness_result.embed_category)


def main(
    settings_loader: SettingsLoader | None = None,
    inbound_runner: InboundRunner | None = None,
    outbound_runner: OutboundRunner | None = None,
    sleeper: Sleeper | None = None,
    sleep_decision: Callable[[Settings, int], bool] | None = None,
    cycle_summary_writer: CycleSummaryWriter | None = None,
    stop_predicate: Callable[[], bool] | None = None,
    unexpected_exception_log: Callable[..., None] | None = None,
    readiness_probe: ReadinessProbe | None = None,
) -> int:
    """Run the automatic provider-processing worker.

    Returns the number of completed cycles (always zero for the
    production loop, which is unbounded; tests substitute
    ``stop_predicate`` to bound cycles without sleeping).
    """
    settings = (settings_loader or _default_settings_loader)()
    _validate_worker_settings(settings)
    if not settings.provider_processing_worker_enabled:
        logger.info(
            "provider_processing_worker_disabled",
            extra={
                "reason": "flag_disabled",
                "default_enabled": (
                    DEFAULT_PROVIDER_PROCESSING_WORKER_ENABLED
                ),
                "default_inbound_bound": (
                    DEFAULT_PROVIDER_PROCESSING_WORKER_INBOUND_MAX_ITEMS_PER_PASS
                ),
                "default_outbound_bound": (
                    DEFAULT_PROVIDER_PROCESSING_WORKER_OUTBOUND_MAX_ATTEMPTS_PER_PASS
                ),
                "default_poll_interval_seconds": (
                    DEFAULT_PROVIDER_PROCESSING_WORKER_POLL_INTERVAL_SECONDS
                ),
            },
        )
        return 0

    _validate_outbound_settings(settings)

    inbound_runner_fn = inbound_runner or _default_inbound_runner
    outbound_runner_fn = outbound_runner or _default_outbound_runner
    sleeper_fn = sleeper or _default_sleeper
    readiness_probe_fn = (
        readiness_probe
        if readiness_probe is not None
        else _default_readiness_probe_factory(settings)
    )

    return run_forever(
        settings=settings,
        inbound_runner=inbound_runner_fn,
        outbound_runner=outbound_runner_fn,
        sleeper=sleeper_fn,
        sleep_decision=sleep_decision,
        cycle_summary_writer=cycle_summary_writer,
        stop_predicate=stop_predicate,
        unexpected_exception_log=unexpected_exception_log,
        readiness_probe=readiness_probe_fn,
    )


__all__ = [
    "DEFAULT_CYCLE_INTERVAL_SECONDS",
    "CycleSummaryWriter",
    "InboundRunner",
    "OutboundRunner",
    "ReadinessProbe",
    "SettingsLoader",
    "Sleeper",
    "main",
    "run_cycle",
    "run_forever",
    "validate_worker_startup_or_exit",
]


if __name__ == "__main__":
    sys.exit(main())