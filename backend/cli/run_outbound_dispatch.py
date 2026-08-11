"""Phase-5.6 outbound dispatch CLI entry point.

The CLI is the only manually invoked entry point that drives the
Phase-5.6 outbound message dispatcher. It performs three narrow
responsibilities:

1. Load ``Settings`` and validate that the project has the minimum
   outbound credentials / routing configuration needed to build a
   real ``twilio.rest.Client``. Missing configuration fails
   non-zero before any database or network access so an operator
   gets a single typed error instead of a runtime failure mid-call.
2. Construct ``OutboundMessageDispatcher`` with the project's real
   ``_SessionLocal`` factory and the real ``twilio.rest.Client``
   ``messages`` seam, then invoke ``run_retry_pass`` with the
   operator-supplied bounded per-pass maximum.
3. Print a single safe operational summary: counts of each
   ``OutboundDispatchOutcome``, per-attempt outbox ids and Twilio
   SIDs. The summary NEVER contains the auth token, the account
   SID, the raw outbound body, the Twilio signature or any other
   inbound text. It is the only thing the CLI writes to stdout.

The CLI is deliberately minimal and explicit:

* no FastAPI endpoint;
* no background loop or scheduler;
* no transaction ownership beyond the existing dispatcher's
  narrow claim / finalize transactions;
* no inbound pipeline invocation;
* no daemonization, no operator UI, no metrics export.

The CLI exposes four injectable seams so focused tests can wire
the real factory, the real Twilio messages client and a fake
dispatcher without monkey-patching the global ``twilio.rest``
module:

* ``_load_settings`` returns the ``Settings`` instance;
* ``_build_session_factory`` returns a callable producing one
  ``Session`` per call;
* ``_build_messages_client`` returns the ``TwilioMessagesClient``
  seam (the SDK ``Client.messages`` instance);
* ``_build_dispatcher`` returns the ``OutboundMessageDispatcher``
  constructed with those dependencies.

Production code uses the defaults; tests substitute the seams.
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from typing import Any

from backend.config.settings import Settings, load_settings
from backend.dependencies import _SessionLocal
from backend.services.exceptions import (
    InvalidTwilioOutboundDispatchConfig,
    InvalidTwilioWebhookAuthToken,
)
from backend.services.outbound_dispatch_types import (
    OutboundCycleAggregate,
    OutboundDispatchOutcome,
    OutboundDispatchResult,
    OutboundPassEvidence,
)
from backend.services.outbound_message_dispatcher import (
    OutboundMessageDispatcher,
)

logger = logging.getLogger(__name__)


DEFAULT_MAX_ATTEMPTS_PER_PASS = 16

CycleAggregateWriter = Callable[[OutboundCycleAggregate], None]


def _build_cycle_aggregate(
    *,
    results: Sequence[OutboundDispatchResult],
    technical_exceptions: Sequence[BaseException],
) -> OutboundCycleAggregate:
    """Build one safe per-cycle aggregate from the pass evidence.

    The aggregate includes counts by outcome and a per-failure
    category breakdown so the worker cycle summary is operationally
    diagnosable without reducing a terminal Twilio failure to a
    single exit code. No bodies, addresses, signatures, payloads
    or exception text are included.
    """
    sent = sum(
        1
        for r in results
        if r.outcome is OutboundDispatchOutcome.SENT
    )
    retry = sum(
        1
        for r in results
        if r.outcome is OutboundDispatchOutcome.RETRY_SCHEDULED
    )
    failed = sum(
        1
        for r in results
        if r.outcome is OutboundDispatchOutcome.FAILED_TERMINAL
    )
    no_due = sum(
        1
        for r in results
        if r.outcome is OutboundDispatchOutcome.NO_DUE_ROW
    )
    category_counts: dict[str, int] = {}
    for r in results:
        if r.outcome not in (
            OutboundDispatchOutcome.RETRY_SCHEDULED,
            OutboundDispatchOutcome.FAILED_TERMINAL,
        ):
            continue
        if r.categoria is None:
            key = "unknown"
        else:
            key = str(r.categoria.value)
        category_counts[key] = category_counts.get(key, 0) + 1
    return OutboundCycleAggregate(
        sent=sent,
        retry_scheduled=retry,
        failed_terminal=failed,
        no_due_row=no_due,
        technical_failure=len(technical_exceptions),
        failure_category_counts=category_counts,
    )


def _load_settings() -> Settings:
    """Default settings loader.

    The seam exists so focused tests can supply a fixed ``Settings``
    instance without polluting the environment.
    """
    return load_settings()


def _build_session_factory() -> Callable[[], Any]:
    """Default session factory.

    Returns a callable that opens one short-lived ``Session`` per
    call, mirroring the dependency ``_SessionLocal`` already used by
    every other project CLI.
    """
    return _SessionLocal


def _build_messages_client(
    *, account_sid: str, auth_token: str
) -> Any:
    """Default Twilio messages client.

    The Twilio REST ``Client`` is constructed lazily so importing
    this module never imports ``twilio.rest`` at top level.
    Tests inject a stub that satisfies the structural seam.
    """
    from twilio.rest import Client

    return Client(account_sid, auth_token).messages


def _build_dispatcher(
    *,
    settings: Settings,
    session_factory: Callable[[], Any],
    messages_client: Any,
) -> OutboundMessageDispatcher:
    """Default dispatcher factory.

    Returns a fully wired ``OutboundMessageDispatcher`` that uses
    the real ``MensajeProveedorSalienteRepository`` factory and
    the supplied ``session_factory`` / ``messages_client`` seams.
    """
    return OutboundMessageDispatcher(
        session_factory=session_factory,
        messages_client=messages_client,
        settings=settings,
    )


def _validate_outbound_settings(settings: Settings) -> None:
    """Reject missing outbound settings before any I/O.

    The dispatcher constructor would otherwise raise a
    ``RuntimeError`` mid-construction. This wrapper converts the
    missing / empty / malformed configuration into a typed
    ``InvalidTwilioOutboundDispatchConfig`` so the CLI can fail
    non-zero with a clear operational message instead of an
    obscure ``RuntimeError`` trace.
    """
    if not settings.twilio_auth_token:
        raise InvalidTwilioOutboundDispatchConfig(
            "TWILIO_AUTH_TOKEN is required by the outbound dispatch CLI"
        )
    if not settings.twilio_account_sid:
        raise InvalidTwilioOutboundDispatchConfig(
            "TWILIO_ACCOUNT_SID is required by the outbound dispatch CLI"
        )
    account_sid = str(settings.twilio_account_sid)
    if (
        not account_sid.startswith("AC")
        or len(account_sid) != 34
        or not all(
            ch in "0123456789abcdefABCDEF" for ch in account_sid[2:]
        )
    ):
        raise InvalidTwilioOutboundDispatchConfig(
            "TWILIO_ACCOUNT_SID must be a canonical Twilio account SID "
            "starting with 'AC' and 34 hexadecimal characters total"
        )
    if not settings.twilio_outbound_sender_e164:
        raise InvalidTwilioOutboundDispatchConfig(
            "TWILIO_OUTBOUND_SENDER_E164 is required by the outbound "
            "dispatch CLI"
        )
    if not settings.twilio_callback_status_url:
        raise InvalidTwilioOutboundDispatchConfig(
            "TWILIO_CALLBACK_STATUS_URL is required by the outbound "
            "dispatch CLI"
        )


def _format_summary(
    results: Sequence[OutboundDispatchResult],
    technical_failure_count: int = 0,
) -> str:
    """Render a single safe operational summary line.

    The summary is the only thing the CLI writes to stdout. It
    contains the per-outcome counts and the per-attempt stable
    identifiers (outbox id and Twilio SID). It NEVER contains
    credentials, signatures, inbound text or outbound body.
    """
    sent = sum(1 for r in results if r.outcome is OutboundDispatchOutcome.SENT)
    retry = sum(
        1
        for r in results
        if r.outcome is OutboundDispatchOutcome.RETRY_SCHEDULED
    )
    failed = sum(
        1
        for r in results
        if r.outcome is OutboundDispatchOutcome.FAILED_TERMINAL
    )
    no_due = sum(
        1
        for r in results
        if r.outcome is OutboundDispatchOutcome.NO_DUE_ROW
    )
    total = len(results) + int(technical_failure_count)
    return (
        f"sent={sent} retry_scheduled={retry} "
        f"failed_terminal={failed} no_due_row={no_due} "
        f"technical_failure={int(technical_failure_count)} "
        f"total={total}"
    )


def _print_per_attempt(
    results: Sequence[OutboundDispatchResult],
    technical_exceptions: Sequence[BaseException] = (),
) -> None:
    """Print one safe per-attempt summary line.

    The line includes the outbox id, the resolved outcome, the
    Twilio SID when the row was accepted, the safe failure
    category / provider code / HTTP status when the row was a
    classified failure, and the exception class when a technical
    failure aborted the loop. The outbound body, signature,
    account SID, auth token, raw exception text, tracebacks and
    provider payloads never appear in this line.
    """
    for result in results:
        if result.outcome is OutboundDispatchOutcome.SENT:
            print(
                f"mensaje_id={result.mensaje_id} outcome=sent "
                f"identificador_proveedor={result.identificador_proveedor} "
                f"durable_state={result.durable_state or 'accepted'}"
            )
            continue
        if result.outcome is OutboundDispatchOutcome.RETRY_SCHEDULED:
            categoria = (
                result.categoria.value
                if result.categoria is not None
                else "unknown"
            )
            http_status = (
                f" http_status={int(result.http_status)}"
                if result.http_status is not None
                else ""
            )
            print(
                f"mensaje_id={result.mensaje_id} outcome=retry_scheduled "
                f"intentos={result.intentos} categoria={categoria} "
                f"codigo={result.codigo} "
                f"durable_state={result.durable_state or 'retryable'}"
                f"{http_status}"
            )
            continue
        if result.outcome is OutboundDispatchOutcome.FAILED_TERMINAL:
            categoria = (
                result.categoria.value
                if result.categoria is not None
                else "unknown"
            )
            http_status = (
                f" http_status={int(result.http_status)}"
                if result.http_status is not None
                else ""
            )
            print(
                f"mensaje_id={result.mensaje_id} outcome=failed_terminal "
                f"intentos={result.intentos} categoria={categoria} "
                f"codigo={result.codigo} "
                f"durable_state={result.durable_state or 'failed_terminal'}"
                f"{http_status}"
            )
            continue
        print(
            f"mensaje_id={result.mensaje_id} outcome=no_due_row "
            f"detalle={result.detalle}"
        )

    for exc in technical_exceptions:
        print(
            f"outcome=technical_failure "
            f"exception_type={type(exc).__name__}"
        )


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "Run one bounded Phase-5.6 outbound dispatch pass over the "
            "Twilio outbox. The CLI never schedules a background loop "
            "and exits after the pass."
        ),
    )
    parser.add_argument(
        "--max-attempts-per-pass",
        type=int,
        default=DEFAULT_MAX_ATTEMPTS_PER_PASS,
        help=(
            "Maximum number of dispatch attempts the CLI performs in this "
            "invocation. Must be a positive integer. The CLI exits as soon "
            "as the dispatcher reports no_due_row or the budget is "
            f"exhausted. Default: {DEFAULT_MAX_ATTEMPTS_PER_PASS}."
        ),
    )
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if args.max_attempts_per_pass <= 0:
        print(
            "--max-attempts-per-pass must be a positive integer "
            f"(got {args.max_attempts_per_pass})",
            file=sys.stderr,
        )
        raise SystemExit(2)


def main(
    argv: Sequence[str] | None = None,
    *,
    settings_loader: Callable[[], Settings] | None = None,
    session_factory_builder: Callable[[], Callable[[], Any]] | None = None,
    messages_client_builder: Callable[..., Any] | None = None,
    dispatcher_builder: Callable[..., OutboundMessageDispatcher] | None = None,
    cycle_aggregate_writer: CycleAggregateWriter | None = None,
) -> int:
    """Run one bounded Phase-5.6 outbound dispatch pass.

    The CLI loads the project's real ``Settings``, validates that
    the outbound credentials and routing configuration are
    present, builds the dispatcher with the real
    ``_SessionLocal`` factory and the real ``twilio.rest.Client``
    ``messages`` seam, and invokes ``run_pass_with_evidence``
    with the operator-supplied ``--max-attempts-per-pass`` bound.

    Exit codes:

    * ``0`` when the pass completes and no row hit
      ``failed_terminal``;
    * ``1`` when at least one row hit ``failed_terminal`` or a
      technical dispatch failure escaped the dispatcher;
    * ``2`` when ``--max-attempts-per-pass`` is missing /
      non-positive or an invalid Twilio ``MessageSid`` / outbound
      configuration was provided;
    * ``3`` when the Twilio ``Client`` cannot be constructed.

    The CLI never prints credentials, signatures, inbound text or
    outbound message bodies. The summary line contains only stable
    identifiers and outcome categories.

    ``cycle_aggregate_writer``, when provided, receives one safe
    :class:`OutboundCycleAggregate` per pass so the worker can
    emit per-cycle aggregates without re-running the dispatcher.
    """
    load_settings_fn = settings_loader or _load_settings
    build_session_factory_fn = session_factory_builder or _build_session_factory
    build_messages_client_fn = messages_client_builder or _build_messages_client
    build_dispatcher_fn = dispatcher_builder or _build_dispatcher

    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_args(args)

    try:
        settings = load_settings_fn()
    except (
        InvalidTwilioOutboundDispatchConfig,
        InvalidTwilioWebhookAuthToken,
    ) as exc:
        print(f"invalid_outbound_settings: {type(exc).__name__}", file=sys.stderr)
        if cycle_aggregate_writer is not None:
            cycle_aggregate_writer(
                _build_cycle_aggregate(
                    results=(),
                    technical_exceptions=(exc,),
                )
            )
        return 2

    try:
        _validate_outbound_settings(settings)
    except InvalidTwilioOutboundDispatchConfig as exc:
        print(f"invalid_outbound_settings: {exc}", file=sys.stderr)
        if cycle_aggregate_writer is not None:
            cycle_aggregate_writer(
                _build_cycle_aggregate(
                    results=(),
                    technical_exceptions=(exc,),
                )
            )
        return 2

    session_factory = build_session_factory_fn()

    try:
        messages_client = build_messages_client_fn(
            account_sid=str(settings.twilio_account_sid),
            auth_token=str(settings.twilio_auth_token),
        )
    except Exception as exc:  # noqa: BLE001 - defensive: CLI must not leak provider exceptions or internal type names beyond the safe prefix
        logger.info(
            "twilio_outbound_dispatch_client_construction_failed",
            extra={"reason": type(exc).__name__},
        )
        print(
            "twilio_client_construction_failed: "
            f"{type(exc).__name__}",
            file=sys.stderr,
        )
        if cycle_aggregate_writer is not None:
            cycle_aggregate_writer(
                _build_cycle_aggregate(
                    results=(),
                    technical_exceptions=(exc,),
                )
            )
        return 3

    dispatcher = build_dispatcher_fn(
        settings=settings,
        session_factory=session_factory,
        messages_client=messages_client,
    )

    try:
        evidence: OutboundPassEvidence = dispatcher.run_pass_with_evidence(
            max_attempts_per_pass=int(args.max_attempts_per_pass)
        )
    except Exception as exc:  # noqa: BLE001 - defensive: CLI must surface any dispatch failure as exit code 1 without leaking credentials or body bytes
        logger.info(
            "twilio_outbound_dispatch_pass_failed",
            extra={"reason": type(exc).__name__},
        )
        print(
            f"dispatch_pass_failed: {type(exc).__name__}",
            file=sys.stderr,
        )
        if cycle_aggregate_writer is not None:
            cycle_aggregate_writer(
                _build_cycle_aggregate(
                    results=(),
                    technical_exceptions=(exc,),
                )
            )
        return 1

    aggregate = _build_cycle_aggregate(
        results=evidence.results,
        technical_exceptions=evidence.technical_exceptions,
    )
    if cycle_aggregate_writer is not None:
        cycle_aggregate_writer(aggregate)

    _print_per_attempt(
        evidence.results, evidence.technical_exceptions
    )
    print(
        _format_summary(
            evidence.results,
            technical_failure_count=aggregate.technical_failure,
        )
    )

    if any(
        result.outcome is OutboundDispatchOutcome.FAILED_TERMINAL
        for result in evidence.results
    ):
        return 1
    return 0


__all__ = [
    "DEFAULT_MAX_ATTEMPTS_PER_PASS",
    "build_parser",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
