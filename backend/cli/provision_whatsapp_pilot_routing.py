"""Controlled-WhatsApp pilot routing provisioning CLI.

The CLI is the single, manually invoked entry point that ensures
the pilot client is active and the configured Twilio sender has
exactly one active ``DEDICATED`` channel for the selected active
pilot commerce. It is the only mutation surface for the pilot
routing data; the inbound coordinator, outbox dispatcher and
delivery callback adapter are untouched.

The CLI is deliberately narrow:

* it loads the project's real ``Settings`` and rejects a missing
  or non-canonical ``TWILIO_OUTBOUND_SENDER_E164`` BEFORE any
  database I/O so an operator gets a single typed error;
* it accepts only the operator-supplied ``--cliente-e164`` and
  ``--comercio-id``; the sender is the canonical source of the
  destination and is never repeated as a CLI argument;
* it canonicalises the supplied client address with the same
  ``normalize_destination`` helper the channel service uses;
* it owns the single setup transaction: the staging helpers
  in :class:`backend.repositories.cliente_repository.ClienteRepository`
  and
  :class:`backend.services.canal_whatsapp_service.CanalWhatsappService`
  never ``commit`` / ``rollback`` / ``flush``; the CLI may
  ``flush`` once to expose the staged state to the final
  ``CommerceChannelResolver`` check and then commits once or
  rolls back on every exception;
* it prints ONLY safe operational summaries: mode, status, the
  ``ProvisioningStatus`` enum value, the resolver ``status``,
  internal numeric IDs, and creation / reactivation flags. It
  NEVER prints, logs or includes in an exception the
  ``--cliente-e164`` argument, the configured sender, message
  bodies, credentials, signatures or the database URL.

The CLI exposes two injectable seams so focused tests can wire
real factories without monkey-patching the global SQLAlchemy
session or the real ``Settings`` loader:

* ``_load_settings`` returns the ``Settings`` instance;
* ``_open_session_factory`` returns a callable producing one
  short-lived ``Session`` per call.

Exit codes:

* ``0`` — verification reports ``ready`` or apply reports
  ``provisioned`` and the final resolver check resolved to the
  selected commerce.
* ``1`` — typed technical failure that escaped the service or a
  generic uncaught exception.
* ``2`` — input or configuration rejection: invalid
  ``--comercio-id``, empty / non-canonical ``--cliente-e164``,
  missing ``TWILIO_OUTBOUND_SENDER_E164`` or a malformed CLI
  argument.
* ``3`` — typed non-ready state: ``not_ready``,
  ``inactive_client_requires_acknowledgement``,
  ``configuration_failure``, ``commerce_unavailable``,
  ``duplicate_conflict`` or ``technical_failure``. The CLI never
  exits ``0`` for these states.

The CLI is the sole owner of one setup transaction. It does not
import or invoke any inbound, recognition, outbox, dispatcher or
callback component.
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.config.settings import Settings, load_settings
from backend.dependencies import _SessionLocal
from backend.services.canal_whatsapp_service import (
    DuplicateCanalWhatsappDestination,
    InvalidCanalWhatsappDestination,
    InvalidCanalWhatsappProvider,
)
from backend.services.commerce_channel_resolver import (
    ResolutionStatus,
)
from backend.services.exceptions import (
    DuplicateWhatsapp,
    InvalidWhatsappPilotProvisioningInput,
    WhatsappPilotProvisioningCommerceUnavailable,
)
from backend.services.whatsapp_pilot_routing_provisioning_service import (
    ProvisioningMode,
    ProvisioningResult,
    ProvisioningStatus,
    WhatsappPilotRoutingProvisioningService,
    normalize_cliente_e164,
)

logger = logging.getLogger(__name__)


EXIT_OK = 0
EXIT_TECHNICAL_FAILURE = 1
EXIT_INPUT_INVALID = 2
EXIT_NOT_READY = 3


def _load_settings() -> Settings:
    """Default settings loader.

    The seam exists so focused tests can supply a fixed ``Settings``
    instance without polluting the environment.
    """
    return load_settings()


def _open_session() -> Session:
    """Open one short-lived ``Session`` for the CLI transaction.

    The seam exists so focused tests can supply their own session
    factory without monkey-patching ``_SessionLocal``. The default
    mirrors the dependency already used by every other project CLI.
    """
    return _SessionLocal()


def _resolve_sender_or_raise(settings: Settings) -> str:
    """Validate ``TWILIO_OUTBOUND_SENDER_E164`` and return the
    canonical E.164 sender.

    The sender is the canonical source of the destination; the CLI
    never accepts it as an argument and never prints it.
    """
    raw = settings.twilio_outbound_sender_e164
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidWhatsappPilotProvisioningInput(
            "TWILIO_OUTBOUND_SENDER_E164 is required by the routing "
            "provisioning CLI"
        )
    try:
        from backend.services.canal_whatsapp_service import (
            normalize_destination,
        )
    except ImportError:  # pragma: no cover - defensive
        raise InvalidWhatsappPilotProvisioningInput(
            "sender normalization helper is unavailable"
        )
    return normalize_destination(raw)


def _format_result(result: ProvisioningResult) -> str:
    """Render a single safe operational summary line.

    The summary is the only thing the CLI writes to stdout for the
    result. It contains the mode, status, resolver status, numeric
    IDs and creation / reactivation flags. It NEVER contains the
    supplied client address, the configured sender, message bodies,
    credentials, signatures or the database URL.
    """
    canal_segment = (
        f" canal_id={result.canal_id}" if result.canal_id is not None else ""
    )
    cliente_segment = (
        f" cliente_id={result.cliente_id}"
        if result.cliente_id is not None
        else ""
    )
    resolver_segment = (
        f" resolver_status={result.resolver_status.value}"
        if result.resolver_status is not None
        else ""
    )
    flags: list[str] = []
    if result.client_created:
        flags.append("client_created")
    if result.client_reactivated:
        flags.append("client_reactivated")
    if result.channel_created:
        flags.append("channel_created")
    flags_segment = (
        f" actions={','.join(flags)}" if flags else ""
    )
    detalle_segment = (
        f" detalle={result.detalle}" if result.detalle else ""
    )
    return (
        f"mode={result.mode.value} status={result.status.value} "
        f"comercio_id={result.comercio_id}{cliente_segment}"
        f"{canal_segment}{resolver_segment}{flags_segment}"
        f"{detalle_segment}"
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "Verify or apply the controlled WhatsApp pilot routing "
            "state for one designated test client and one selected "
            "active commerce. Default mode is read-only verification."
        ),
    )
    parser.add_argument(
        "--cliente-e164",
        required=True,
        type=str,
        help=(
            "Canonical E.164 WhatsApp address of the designated test "
            "client. The CLI normalises the value with the existing "
            "channel E.164 helper before any database I/O; the value "
            "is never echoed in the result line."
        ),
    )
    parser.add_argument(
        "--comercio-id",
        required=True,
        type=int,
        help=(
            "Numeric primary key of the selected active pilot "
            "commerce. The CLI rejects any non-positive value."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Explicit apply mode. Stages the missing active client "
            "and dedicated channel and commits once after the final "
            "resolver check. Without this flag the CLI performs a "
            "read-only verification."
        ),
    )
    parser.add_argument(
        "--reactivate-client",
        action="store_true",
        help=(
            "Explicit acknowledgement that an inactive existing test "
            "client MAY be reactivated. Required when the apply mode "
            "encounters an inactive client; without it the CLI "
            "returns inactive_client_requires_acknowledgement and "
            "performs no mutation."
        ),
    )
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if not isinstance(args.comercio_id, int) or args.comercio_id <= 0:
        print(
            "--comercio-id must be a positive integer "
            f"(got {args.comercio_id})",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_INPUT_INVALID)
    if not isinstance(args.cliente_e164, str) or not args.cliente_e164.strip():
        print(
            "--cliente-e164 must be a non-empty string",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_INPUT_INVALID)


def _resolve_post_apply(
    *,
    service: WhatsappPilotRoutingProvisioningService,
    cliente_e164_canonical: str,
    sender_e164_canonical: str,
    comercio_id: int,
    staging: ProvisioningResult,
) -> ProvisioningResult:
    """Run the final resolver check after the CLI flushes staged state.

    The CLI owns this boundary because the staging service deliberately
    does not flush. The CLI flushes once, runs the resolver against
    the staged session and commits only when the resolver confirms
    RESOLVED with the requested commerce; otherwise the staged state
    is rolled back.

    The IDs are read back from the freshly flushed session so the
    ``provisioned`` result always echoes the canonical, persisted
    numeric IDs that survive the commit. The staging flags
    (``client_created``, ``client_reactivated``, ``channel_created``)
    are preserved on the final result so the operator evidence row
    records exactly what the CLI just staged and committed.
    """
    resolution = service.resolve_for_canonical_sender(sender_e164_canonical)
    canal_id = service.find_canal_id_by_destination(sender_e164_canonical)
    cliente_id = service.find_cliente_id_by_whatsapp(cliente_e164_canonical)
    if (
        resolution.status is ResolutionStatus.RESOLVED
        and resolution.comercio_id == comercio_id
        and resolution.routing_mode is not None
    ):
        return ProvisioningResult(
            mode=ProvisioningMode.APPLY,
            status=ProvisioningStatus.PROVISIONED,
            comercio_id=comercio_id,
            cliente_id=cliente_id,
            canal_id=canal_id,
            resolver_status=resolution.status,
            client_created=staging.client_created,
            client_reactivated=staging.client_reactivated,
            channel_created=staging.channel_created,
            detalle="resolver_resolved_to_commerce",
        )
    return ProvisioningResult(
        mode=ProvisioningMode.APPLY,
        status=ProvisioningStatus.CONFIGURATION_FAILURE,
        comercio_id=comercio_id,
        cliente_id=cliente_id,
        canal_id=canal_id,
        resolver_status=resolution.status,
        client_created=staging.client_created,
        client_reactivated=staging.client_reactivated,
        channel_created=staging.channel_created,
        detalle="post_apply_resolver_not_resolved",
    )


def _result_for_unchanged(
    result: ProvisioningResult,
) -> ProvisioningResult:
    """Return a result whose mode matches the requested CLI flag.

    The verify path always echoes ``mode=verify``; the apply path
    echoes ``mode=apply`` even when the staging service reports
    that the state is already ready (because no mutation occurred,
    the canonical ``ready`` status is preserved).
    """
    return result


def _handle_typed_exception(
    exc: Exception,
    *,
    mode: ProvisioningMode,
    comercio_id: int,
) -> ProvisioningResult:
    """Translate a typed exception into a sanitized result row.

    The CLI NEVER echoes the exception message because exception
    text could contain the supplied address, the configured sender
    or the database URL. The mapping is the only thing the CLI
    prints; it always preserves the ``commerce_unavailable``,
    ``duplicate_conflict`` and ``input_invalid`` categories.
    """
    if isinstance(exc, InvalidWhatsappPilotProvisioningInput):
        return ProvisioningResult(
            mode=mode,
            status=ProvisioningStatus.INPUT_INVALID,
            comercio_id=comercio_id,
            cliente_id=None,
            canal_id=None,
            resolver_status=None,
            detalle="invalid_input",
        )
    if isinstance(exc, WhatsappPilotProvisioningCommerceUnavailable):
        return ProvisioningResult(
            mode=mode,
            status=ProvisioningStatus.COMMERCE_UNAVAILABLE,
            comercio_id=comercio_id,
            cliente_id=None,
            canal_id=None,
            resolver_status=None,
            detalle="commerce_missing_or_inactive",
        )
    if isinstance(exc, DuplicateCanalWhatsappDestination):
        return ProvisioningResult(
            mode=mode,
            status=ProvisioningStatus.DUPLICATE_CONFLICT,
            comercio_id=comercio_id,
            cliente_id=None,
            canal_id=None,
            resolver_status=None,
            detalle="channel_duplicate",
        )
    if isinstance(exc, DuplicateWhatsapp):
        return ProvisioningResult(
            mode=mode,
            status=ProvisioningStatus.DUPLICATE_CONFLICT,
            comercio_id=comercio_id,
            cliente_id=None,
            canal_id=None,
            resolver_status=None,
            detalle="client_duplicate",
        )
    if isinstance(exc, InvalidCanalWhatsappDestination):
        return ProvisioningResult(
            mode=mode,
            status=ProvisioningStatus.INPUT_INVALID,
            comercio_id=comercio_id,
            cliente_id=None,
            canal_id=None,
            resolver_status=None,
            detalle="destination_invalid",
        )
    if isinstance(exc, InvalidCanalWhatsappProvider):
        return ProvisioningResult(
            mode=mode,
            status=ProvisioningStatus.INPUT_INVALID,
            comercio_id=comercio_id,
            cliente_id=None,
            canal_id=None,
            resolver_status=None,
            detalle="provider_invalid",
        )
    return ProvisioningResult(
        mode=mode,
        status=ProvisioningStatus.TECHNICAL_FAILURE,
        comercio_id=comercio_id,
        cliente_id=None,
        canal_id=None,
        resolver_status=None,
        detalle=type(exc).__name__,
    )


def _exit_code_for_status(status: ProvisioningStatus) -> int:
    """Map a typed provisioning status to the CLI exit code."""
    if status is ProvisioningStatus.READY:
        return EXIT_OK
    if status is ProvisioningStatus.PROVISIONED:
        return EXIT_OK
    if status is ProvisioningStatus.INPUT_INVALID:
        return EXIT_INPUT_INVALID
    return EXIT_NOT_READY


def main(
    argv: Sequence[str] | None = None,
    *,
    settings_loader: Callable[[], Settings] | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> int:
    """Run one controlled WhatsApp pilot routing provisioning pass.

    The CLI loads the project's real ``Settings``, validates the
    ``TWILIO_OUTBOUND_SENDER_E164`` sender and the supplied
    ``--cliente-e164`` / ``--comercio-id`` BEFORE any database I/O,
    then opens a single short-lived session and delegates to
    :class:`WhatsappPilotRoutingProvisioningService`. The CLI is
    the sole owner of the setup transaction: it may ``flush`` once
    after staging both records, then commits once or rolls back on
    every exception.
    """
    load_settings_fn = settings_loader or _load_settings
    open_session_fn = session_factory or _open_session

    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_args(args)

    try:
        settings = load_settings_fn()
    except (
        InvalidWhatsappPilotProvisioningInput,
        InvalidCanalWhatsappProvider,
        InvalidCanalWhatsappDestination,
    ) as exc:
        logger.info(
            "whatsapp_pilot_routing_settings_invalid",
            extra={"reason": type(exc).__name__},
        )
        print(
            f"invalid_settings: {type(exc).__name__}",
            file=sys.stderr,
        )
        return EXIT_INPUT_INVALID

    try:
        sender_e164_canonical = _resolve_sender_or_raise(settings)
    except (
        InvalidWhatsappPilotProvisioningInput,
        InvalidCanalWhatsappDestination,
    ) as exc:
        logger.info(
            "whatsapp_pilot_routing_sender_invalid",
            extra={"reason": type(exc).__name__},
        )
        print(
            f"invalid_sender: {type(exc).__name__}",
            file=sys.stderr,
        )
        return EXIT_INPUT_INVALID

    try:
        cliente_e164_canonical = normalize_cliente_e164(args.cliente_e164)
    except (InvalidCanalWhatsappDestination, ValueError) as exc:
        logger.info(
            "whatsapp_pilot_routing_client_e164_invalid",
            extra={"reason": type(exc).__name__},
        )
        print(
            f"invalid_cliente_e164: {type(exc).__name__}",
            file=sys.stderr,
        )
        return EXIT_INPUT_INVALID

    mode = (
        ProvisioningMode.APPLY
        if bool(getattr(args, "apply", False))
        else ProvisioningMode.VERIFY
    )

    session_factory_exc: Exception | None = None
    try:
        session = open_session_fn()
    except Exception as exc:  # noqa: BLE001 - defensive: CLI must surface any session-open failure as a sanitized technical status
        session_factory_exc = exc
        session = None

    if session is None:
        logger.info(
            "whatsapp_pilot_routing_session_open_failed",
            extra={
                "reason": (
                    type(session_factory_exc).__name__
                    if session_factory_exc is not None
                    else "session_factory_returned_none"
                )
            },
        )
        print(
            "session_open_failed: "
            f"{type(session_factory_exc).__name__ if session_factory_exc is not None else 'None'}",
            file=sys.stderr,
        )
        technical_result = ProvisioningResult(
            mode=mode,
            status=ProvisioningStatus.TECHNICAL_FAILURE,
            comercio_id=int(args.comercio_id),
            cliente_id=None,
            canal_id=None,
            resolver_status=None,
            detalle=(
                type(session_factory_exc).__name__
                if session_factory_exc is not None
                else "session_factory_returned_none"
            ),
        )
        print(_format_result(technical_result))
        return EXIT_TECHNICAL_FAILURE

    try:
        service = WhatsappPilotRoutingProvisioningService(session)
        try:
            if mode is ProvisioningMode.VERIFY:
                staged = service.verify(
                    cliente_e164_canonical=cliente_e164_canonical,
                    comercio_id=int(args.comercio_id),
                    sender_e164_canonical=sender_e164_canonical,
                )
                final = _result_for_unchanged(staged)
            else:
                staged = service.apply(
                    cliente_e164_canonical=cliente_e164_canonical,
                    comercio_id=int(args.comercio_id),
                    sender_e164_canonical=sender_e164_canonical,
                    reactivate_client_acknowledgement=bool(
                        getattr(args, "reactivate_client", False)
                    ),
                )
                if staged.status is ProvisioningStatus.NOT_READY:
                    session.flush()
                    final = _resolve_post_apply(
                        service=service,
                        cliente_e164_canonical=cliente_e164_canonical,
                        sender_e164_canonical=sender_e164_canonical,
                        comercio_id=int(args.comercio_id),
                        staging=staged,
                    )
                    if final.status is ProvisioningStatus.PROVISIONED:
                        session.commit()
                    else:
                        session.rollback()
                elif staged.status in (
                    ProvisioningStatus.READY,
                    ProvisioningStatus.CONFIGURATION_FAILURE,
                    ProvisioningStatus.INACTIVE_CLIENT_REQUIRES_ACKNOWLEDGEMENT,
                ):
                    session.rollback()
                    final = staged
                else:
                    session.rollback()
                    final = staged
        except IntegrityError as exc:
            logger.info(
                "whatsapp_pilot_routing_integrity_error",
                extra={"reason": type(exc).__name__},
            )
            session.rollback()
            final = _handle_typed_exception(
                DuplicateCanalWhatsappDestination("integrity"),
                mode=mode,
                comercio_id=int(args.comercio_id),
            )
        except (
            InvalidWhatsappPilotProvisioningInput,
            WhatsappPilotProvisioningCommerceUnavailable,
            DuplicateCanalWhatsappDestination,
            DuplicateWhatsapp,
            InvalidCanalWhatsappDestination,
            InvalidCanalWhatsappProvider,
        ) as exc:
            session.rollback()
            final = _handle_typed_exception(
                exc,
                mode=mode,
                comercio_id=int(args.comercio_id),
            )
        except Exception as exc:  # noqa: BLE001 - defensive: CLI must not leak provider exceptions or internal type names beyond the safe prefix
            logger.info(
                "whatsapp_pilot_routing_unexpected_failure",
                extra={"reason": type(exc).__name__},
            )
            session.rollback()
            final = ProvisioningResult(
                mode=mode,
                status=ProvisioningStatus.TECHNICAL_FAILURE,
                comercio_id=int(args.comercio_id),
                cliente_id=None,
                canal_id=None,
                resolver_status=None,
                detalle=type(exc).__name__,
            )
    finally:
        session.close()

    print(_format_result(final))
    if final.status is ProvisioningStatus.TECHNICAL_FAILURE:
        return EXIT_TECHNICAL_FAILURE
    return _exit_code_for_status(final.status)


__all__ = [
    "EXIT_INPUT_INVALID",
    "EXIT_NOT_READY",
    "EXIT_OK",
    "EXIT_TECHNICAL_FAILURE",
    "build_parser",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
