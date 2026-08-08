"""Phase-7.4 deferred inbound processing CLI entry point.

The CLI is the only manually invoked entry point that drives the
Phase-7.4 deferred inbound work items through the existing
``ProviderInboundMessageCoordinator.process_lease`` path. It performs
three narrow responsibilities:

1. Open a short-lived session per claim / per processing iteration so
   the lease is durable before any business work begins and so the
   finalization transaction is independent of the claim transaction.
2. Lease at most ``--max-items-per-pass N`` due work items per
   invocation (defaulting to ``1``), invoking the coordinator's
   ``process_lease`` method on each leased row in receipt-creation
   order so the bounded pass never processes a later item while an
   earlier one remains pending, leased or retryable.
3. Print a single safe operational summary: counts of each
   ``ProviderInboundProcessingOutcome``, per-attempt work ids,
   attempt counts, safe failure category/code. The summary NEVER
   contains the inbound message text, the customer E.164, the
   provider signature, the auth token, the account SID or any raw
   exception message.

The CLI is deliberately minimal and explicit:

* no FastAPI endpoint;
* no background loop, scheduler, cron or polling pass;
* no automatic inbound processing — every invocation is a single
  explicit operator action;
* no daemonization, no operator UI, no metrics export.

The CLI exposes four injectable seams so focused tests can wire the
real factory and a stub coordinator / session factory without
monkey-patching the global ``ProviderInboundMessageCoordinator``:

* ``_load_settings`` returns the ``Settings`` instance;
* ``_build_session_factory`` returns a callable producing one
  ``Session`` per call;
* ``_build_coordinator`` returns the coordinator constructed with
  the supplied session;
* ``_now`` returns the current datetime used by the coordinator
  (overridable by tests for deterministic backoff).
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, Protocol

from backend.dependencies import _SessionLocal
from backend.services.provider_inbound_message_coordinator import (
    DEFAULT_MAX_ATTEMPTS,
    ProviderInboundMessageCoordinator,
    ProviderInboundProcessingOutcome,
    ProviderInboundProcessingResult,
)

logger = logging.getLogger(__name__)


DEFAULT_MAX_ITEMS_PER_PASS = 1


class SessionFactoryLike(Protocol):
    def __call__(self) -> Any: ...


def _load_settings() -> Any:
    """Default settings loader.

    The seam exists so focused tests can supply a fixed ``Settings``
    instance without polluting the environment. The CLI does not
    actually depend on any Twilio / Ollama setting; it is loaded for
    symmetry with the existing CLIs and so future settings (such as
    inbound retry bounds) have a typed seam.
    """
    from backend.config.settings import load_settings

    return load_settings()


def _build_session_factory() -> SessionFactoryLike:
    """Default session factory.

    Returns a callable that opens one short-lived ``Session`` per
    call, mirroring the dependency ``_SessionLocal`` already used by
    every other project CLI.
    """
    return _SessionLocal


def _build_coordinator(
    *,
    session: Any,
    settings: Any,
    now: datetime,
) -> ProviderInboundMessageCoordinator:
    """Default coordinator factory.

    Returns a fully wired ``ProviderInboundMessageCoordinator`` that
    uses the supplied ``session`` and the supplied ``now`` clock.
    The CLI is the only caller of the coordinator's
    ``claim_due_processing`` / ``process_lease`` methods so the
    transaction model of the existing dispatcher is preserved.
    """
    return ProviderInboundMessageCoordinator(
        session=session,
        max_attempts=int(
            getattr(
                settings,
                "twilio_inbound_max_attempts",
                DEFAULT_MAX_ATTEMPTS,
            )
        )
        if settings is not None
        else DEFAULT_MAX_ATTEMPTS,
        now=now,
    )


def _format_summary(
    results: Sequence[ProviderInboundProcessingResult],
) -> str:
    """Render a single safe operational summary line.

    The summary is the only thing the CLI writes to stdout. It
    contains the per-outcome counts and the per-attempt stable
    identifiers (work id, attempt count, safe failure category/code).
    It NEVER contains credentials, signatures, inbound text or
    customer E.164 numbers.
    """
    processed = sum(
        1
        for r in results
        if r.outcome is ProviderInboundProcessingOutcome.PROCESSED
    )
    retry = sum(
        1
        for r in results
        if r.outcome is ProviderInboundProcessingOutcome.RETRY_SCHEDULED
    )
    failed = sum(
        1
        for r in results
        if r.outcome is ProviderInboundProcessingOutcome.FAILED_TERMINAL
    )
    return (
        f"processed={processed} retry_scheduled={retry} "
        f"failed_terminal={failed} total={len(results)}"
    )


def _print_per_attempt(
    results: Sequence[ProviderInboundProcessingResult],
) -> None:
    """Print one safe per-attempt summary line.

    The line includes the work id, the resolved outcome, the attempt
    count and the safe failure category/code when the row was not
    processed. The inbound body, signature, account SID and auth
    token never appear in this line.
    """
    for result in results:
        if result.outcome is ProviderInboundProcessingOutcome.PROCESSED:
            print(
                f"procesamiento_id={result.procesamiento_id} "
                f"outcome=processed"
            )
            continue
        categoria = (
            result.categoria.value
            if result.categoria is not None
            else "unknown"
        )
        print(
            f"procesamiento_id={result.procesamiento_id} "
            f"outcome={result.outcome.value} intentos={result.intentos} "
            f"categoria={categoria} codigo={result.codigo}"
        )


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "Run one bounded Phase-7.4 inbound processing pass over the "
            "durable provider-message work items. The CLI never "
            "schedules a background loop and exits after the pass."
        ),
    )
    parser.add_argument(
        "--max-items-per-pass",
        type=int,
        default=DEFAULT_MAX_ITEMS_PER_PASS,
        help=(
            "Maximum number of due work items the CLI processes in "
            "this invocation. Must be a positive integer. The CLI "
            "exits as soon as the claim phase reports no due row or "
            "the budget is exhausted. "
            f"Default: {DEFAULT_MAX_ITEMS_PER_PASS}."
        ),
    )
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if args.max_items_per_pass <= 0:
        print(
            "--max-items-per-pass must be a positive integer "
            f"(got {args.max_items_per_pass})",
            file=sys.stderr,
        )
        raise SystemExit(2)


def _now() -> datetime:
    from datetime import timezone

    return datetime.now(tz=timezone.utc)


def main(
    argv: Sequence[str] | None = None,
    *,
    settings_loader: Callable[[], Any] | None = None,
    session_factory_builder: Callable[[], SessionFactoryLike] | None = None,
    coordinator_builder: Callable[..., ProviderInboundMessageCoordinator]
    | None = None,
    clock: Callable[[], datetime] | None = None,
) -> int:
    """Run one bounded Phase-7.4 inbound processing pass.

    The CLI loads the project's real ``Settings``, opens the project's
    real ``_SessionLocal`` factory, claims at most
    ``--max-items-per-pass`` due work items and processes each through
    the coordinator's ``process_lease`` method.

    Exit codes:

    * ``0`` when the pass completes and no row hit
      ``failed_terminal``;
    * ``1`` when at least one row hit ``failed_terminal`` or a
      technical processing failure escaped the coordinator;
    * ``2`` when ``--max-items-per-pass`` is missing / non-positive.

    The CLI never prints credentials, signatures, inbound text or
    customer E.164 numbers. The summary line contains only stable
    identifiers and outcome categories.
    """
    load_settings_fn = settings_loader or _load_settings
    build_session_factory_fn = (
        session_factory_builder or _build_session_factory
    )
    build_coordinator_fn = coordinator_builder or _build_coordinator
    clock_fn = clock or _now

    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_args(args)

    try:
        settings = load_settings_fn()
    except Exception as exc:  # noqa: BLE001 - defensive: CLI must surface any settings failure as exit code 2 without leaking credentials
        logger.info(
            "twilio_inbound_processing_settings_load_failed",
            extra={"reason": type(exc).__name__},
        )
        print(
            f"invalid_inbound_settings: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 2

    session_factory = build_session_factory_fn()
    now = clock_fn()

    results: list[ProviderInboundProcessingResult] = []
    for _ in range(int(args.max_items_per_pass)):
        claim_session = session_factory()
        try:
            coordinator = build_coordinator_fn(
                session=claim_session,
                settings=settings,
                now=now,
            )
            leased = coordinator.claim_due_processing(now=now)
        except Exception as exc:  # noqa: BLE001 - defensive: CLI must surface any claim failure as exit code 1 without leaking provider payloads
            logger.info(
                "twilio_inbound_processing_claim_failed",
                extra={"reason": type(exc).__name__},
            )
            print(
                f"inbound_processing_claim_failed: {type(exc).__name__}",
                file=sys.stderr,
            )
            return 1
        finally:
            try:
                claim_session.close()
            except Exception:
                logger.exception(
                    "twilio_inbound_processing_claim_session_close_failed"
                )

        if leased is None:
            break

        process_session = session_factory()
        try:
            process_coordinator = build_coordinator_fn(
                session=process_session,
                settings=settings,
                now=now,
            )
            try:
                result = process_coordinator.process_lease(leased)
            except Exception as exc:  # noqa: BLE001 - defensive: CLI must surface any processing failure as exit code 1 without leaking provider payloads
                logger.info(
                    "twilio_inbound_processing_pass_failed",
                    extra={"reason": type(exc).__name__},
                )
                print(
                    f"inbound_processing_failed: {type(exc).__name__}",
                    file=sys.stderr,
                )
                return 1
        finally:
            try:
                process_session.close()
            except Exception:
                logger.exception(
                    "twilio_inbound_processing_process_session_close_failed"
                )

        results.append(result)

    _print_per_attempt(results)
    print(_format_summary(results))

    if any(
        r.outcome is ProviderInboundProcessingOutcome.FAILED_TERMINAL
        for r in results
    ):
        return 1
    return 0


__all__ = [
    "DEFAULT_MAX_ITEMS_PER_PASS",
    "build_parser",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())