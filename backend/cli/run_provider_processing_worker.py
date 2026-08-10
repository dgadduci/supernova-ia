"""Automatic provider-processing worker CLI entry point.

The CLI is the opt-in long-running orchestrator that drives the
existing ``run_inbound_processing`` and ``run_outbound_dispatch``
passes on a fixed cadence so a valid WhatsApp receipt reaches its
existing outbox and provider delivery without an operator invoking
two CLIs by hand.

The CLI performs four narrow responsibilities:

1. Load ``Settings`` once and refuse to start when the flag is
   enabled with a non-positive interval, a non-positive inbound
   bound, a non-positive outbound bound, or when the existing
   outbound dispatch configuration is missing or invalid. The
   startup check runs BEFORE ``uvicorn`` accepts traffic in the
   Railway entrypoint, so a misconfigured deployment never
   silently degrades to manual operation.
2. On every cycle, invoke the existing bounded inbound CLI with
   the configured inbound bound, then invoke the existing bounded
   outbound CLI with the configured outbound bound. The worker
   never claims a row, opens a business transaction or sends
   through Twilio directly; those seams remain owned by the
   coordinator / dispatcher.
3. Sleep for the configured positive interval regardless of the
   pass outcomes. ``no_due_row``, retryable and terminal results
   are normal business outcomes: they never stop the loop and
   never alter lease / retry / ordering semantics outside the
   existing pass implementation.
4. Emit only safe cycle-level summaries: counts, configured
   bounds, duration, exit codes. The summary never contains
   inbound / outbound bodies, customer E.164 numbers, LLM content,
   provider signatures, account SIDs, tokens or environment
   dumps.

The CLI is deliberately minimal:

* no FastAPI endpoint, no inline webhook handling;
* no scheduler, no Redis / Celery / SQS / cron dependency;
* no parallel pipeline, no second queue, no daemonization;
* no subprocess invocation of the existing CLIs - the worker
  calls their ``main()`` seams directly through injectable
  factories so focused tests can run the loop without spawning
  child processes or sleeping.

The CLI exposes seven injectable seams so focused tests can drive
the loop without touching the real ``Settings``, the real CLIs,
the real sleep, or the real summary printer:

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
  tests to bound cycles without sleeping).

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


def _default_cycle_summary_writer(summary: dict[str, Any]) -> None:
    """Default cycle summary writer.

    Emits one line per cycle containing only safe metadata: cycle
    index, inbound / outbound exit codes, configured bounds, sleep
    decision and configured poll interval. The summary NEVER
    contains the inbound / outbound body, the customer E.164
    number, the LLM content, the provider signature, the account
    SID, the auth token or any environment dump.
    """
    print(
        "provider_worker_cycle "
        f"cycle_index={summary['cycle_index']} "
        f"inbound_exit_code={summary['inbound_exit_code']} "
        f"outbound_exit_code={summary['outbound_exit_code']} "
        f"inbound_bound={summary['inbound_bound']} "
        f"outbound_bound={summary['outbound_bound']} "
        f"poll_interval_seconds={summary['poll_interval_seconds']} "
        f"sleep_after={summary['sleep_after']}",
        file=sys.stdout,
    )


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
    inbound_exit_code: int,
    outbound_exit_code: int,
    settings: Settings,
    sleep_after: bool,
) -> dict[str, Any]:
    return {
        "cycle_index": int(cycle_index),
        "inbound_exit_code": int(inbound_exit_code),
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
    }


def run_cycle(
    *,
    settings: Settings,
    cycle_index: int,
    inbound_runner: InboundRunner,
    outbound_runner: OutboundRunner,
    sleep_decision: Callable[[Settings, int], bool],
    cycle_summary_writer: CycleSummaryWriter,
) -> dict[str, Any]:
    """Run one inbound-then-outbound cycle.

    Returns the safe summary dictionary written to the cycle
    summary writer. The function never raises on business
    outcomes: pass exit codes are recorded but do not interrupt
    the loop. Exceptions raised by the runners or the writer
    propagate to the caller so the supervisor path can restart
    the service.
    """
    inbound_exit_code = int(
        inbound_runner(
            int(
                settings.provider_processing_worker_inbound_max_items_per_pass
            )
        )
    )
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
) -> int:
    """Run the worker loop until ``stop_predicate`` returns ``True``.

    The function NEVER catches business outcomes from the runners:
    their exit codes are recorded in the cycle summary and the
    loop continues. Unexpected exceptions are logged safely and
    re-raised so the Railway entrypoint supervisor can stop the
    web process and exit non-zero for service restart.

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

    cycle_index = 0
    while not stop_predicate_fn():
        cycle_index += 1
        try:
            summary = run_cycle(
                settings=settings,
                cycle_index=cycle_index,
                inbound_runner=inbound_runner,
                outbound_runner=outbound_runner,
                sleep_decision=sleep_decision_fn,
                cycle_summary_writer=cycle_summary_writer_fn,
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


def main(
    settings_loader: SettingsLoader | None = None,
    inbound_runner: InboundRunner | None = None,
    outbound_runner: OutboundRunner | None = None,
    sleeper: Sleeper | None = None,
    sleep_decision: Callable[[Settings, int], bool] | None = None,
    cycle_summary_writer: CycleSummaryWriter | None = None,
    stop_predicate: Callable[[], bool] | None = None,
    unexpected_exception_log: Callable[..., None] | None = None,
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

    return run_forever(
        settings=settings,
        inbound_runner=inbound_runner_fn,
        outbound_runner=outbound_runner_fn,
        sleeper=sleeper_fn,
        sleep_decision=sleep_decision,
        cycle_summary_writer=cycle_summary_writer,
        stop_predicate=stop_predicate,
        unexpected_exception_log=unexpected_exception_log,
    )


__all__ = [
    "DEFAULT_CYCLE_INTERVAL_SECONDS",
    "CycleSummaryWriter",
    "InboundRunner",
    "OutboundRunner",
    "SettingsLoader",
    "Sleeper",
    "main",
    "run_cycle",
    "run_forever",
    "validate_worker_startup_or_exit",
]


if __name__ == "__main__":
    sys.exit(main())