"""Controlled Railway fixture provisioning CLI.

The CLI is the single, manually invoked entry point that ensures an
empty production-shaped database has the static, deterministic
fixture catalog defined by
:mod:`backend.services.seed_controlled_railway_fixtures_data`. It is
the only mutation surface for the controlled Railway fixture data;
the inbound coordinator, the recognizer, the outbox dispatcher and
the existing dedicated-routing provisioner are untouched.

The CLI is deliberately narrow:

* it defaults to ``--verify-only`` and refuses to perform any
  database mutation without an explicit ``--apply`` flag;
* it loads the static fixture definitions from the application
  package and NEVER reads, exports, cleans, resets or compares
  against a local source database;
* it refuses a pre-existing partial or non-fixture row in any of the
  fixture-owned tables — including the ``estado_comercio`` table —
  and reports a ``conflict`` status instead of repairing,
  overwriting or merging the data;
* it owns the single setup transaction: the staging service in
  :class:`backend.services.seed_controlled_railway_fixtures_service.ControlledRailwayFixtureService`
  never ``commit`` / ``rollback`` / ``begin`` / ``flush``; the CLI
  may ``flush`` once to expose the staged state to the final
  read-back verification, performs the exact shape verification on
  the same session, commits once only when that verification is
  exact, and rolls back on every exception or non-exact
  verification result;
* it prints ONLY safe operational summaries: mode, status, the
  static ``FixtureApplyStatus`` enum value, the per-table counts,
  the stable fixture slugs and the persisted numeric commerce IDs.
  It NEVER prints, logs or includes in an exception the database
  URL, a phone number, a message body, a credential, a signature or
  raw caught exception text.

The CLI exposes one injectable seam so focused tests can wire a real
factory without monkey-patching the global SQLAlchemy session or the
real ``_SessionLocal``:

* ``_open_session`` returns a callable producing one short-lived
  ``Session`` per call.

Exit codes:

* ``0`` — verification reports ``ready`` or apply reports
  ``provisioned`` after the final read-back verification confirmed
  the full fixture set is staged.
* ``1`` — typed technical failure that escaped the staging service
  or a generic uncaught exception.
* ``2`` — input rejection: invalid ``--apply`` value or unexpected
  CLI argument.
* ``3`` — typed non-ready state: ``not_ready`` or ``conflict`` in
  either mode. The CLI never exits ``0`` for these states.

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

from backend.dependencies import _SessionLocal
from backend.services.seed_controlled_railway_fixtures_service import (
    ControlledRailwayFixtureService,
    FixtureApplyMode,
    FixtureApplyResult,
    FixtureApplyStatus,
    FixtureCounts,
    build_service,
)

logger = logging.getLogger(__name__)


EXIT_OK = 0
EXIT_TECHNICAL_FAILURE = 1
EXIT_INPUT_INVALID = 2
EXIT_NOT_READY = 3


def _open_session() -> Session:
    """Open one short-lived ``Session`` for the CLI transaction.

    The seam exists so focused tests can supply their own session
    factory without monkey-patching ``_SessionLocal``. The default
    mirrors the dependency already used by every other project CLI.
    """
    return _SessionLocal()


def _format_counts(counts: FixtureCounts) -> str:
    return (
        f"comercios={counts.comercios} "
        f"categorias={counts.categorias} "
        f"presentaciones={counts.presentaciones} "
        f"productos={counts.productos} "
        f"producto_presentaciones={counts.producto_presentaciones} "
        f"precios={counts.precios}"
    )


def _format_commerce_ids(result: FixtureApplyResult) -> str:
    if not result.comercio_ids:
        return ""
    return " comercio_ids=" + ",".join(
        str(value) for value in result.comercio_ids
    )


def _format_result(result: FixtureApplyResult) -> str:
    """Render a single safe operational summary line.

    The summary is the only thing the CLI writes to stdout for the
    result. It contains the mode, status, counts, stable fixture
    slugs and the persisted numeric commerce IDs. It NEVER contains
    a phone number, the database URL, credentials, message bodies,
    signatures or raw caught exception text.
    """
    detalle_segment = (
        f" detalle={result.detalle}" if result.detalle else ""
    )
    return (
        f"mode={result.mode.value} status={result.status.value} "
        f"counts={_format_counts(result.counts)}"
        f"{_format_commerce_ids(result)}"
        f"{detalle_segment}"
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "Verify or apply the controlled Railway fixture dataset "
            "for an empty production-shaped database. Default mode is "
            "read-only verification. The CLI never reads, exports or "
            "compares against a local development database."
        ),
    )
    apply_group = parser.add_mutually_exclusive_group()
    apply_group.add_argument(
        "--verify-only",
        action="store_true",
        help=(
            "Read-only verification. Refuses any insert, update, "
            "delete, flush, commit or rollback. This is the default "
            "mode and is implied when neither flag is supplied."
        ),
    )
    apply_group.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Explicit apply mode. Stages the static fixture dataset "
            "and commits once after the final read-back verification. "
            "Without this flag the CLI performs a read-only "
            "verification. The CLI refuses to mutate an empty "
            "namespace unless this flag is set."
        ),
    )
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if not isinstance(getattr(args, "verify_only", False), bool):
        print("--verify-only must be a boolean flag", file=sys.stderr)
        raise SystemExit(EXIT_INPUT_INVALID)
    if not isinstance(getattr(args, "apply", False), bool):
        print("--apply must be a boolean flag", file=sys.stderr)
        raise SystemExit(EXIT_INPUT_INVALID)


def _exit_code_for_status(status: FixtureApplyStatus) -> int:
    """Map a typed fixture status to the CLI exit code."""
    if status is FixtureApplyStatus.READY:
        return EXIT_OK
    if status is FixtureApplyStatus.PROVISIONED:
        return EXIT_OK
    if status is FixtureApplyStatus.NOT_READY:
        return EXIT_NOT_READY
    if status is FixtureApplyStatus.CONFLICT:
        return EXIT_NOT_READY
    return EXIT_TECHNICAL_FAILURE


def _handle_typed_exception(
    exc: Exception,
    *,
    mode: FixtureApplyMode,
    counts: FixtureCounts,
) -> FixtureApplyResult:
    """Translate a typed exception into a sanitized result row.

    The CLI NEVER echoes the exception message because exception
    text could contain the database URL or a fixture identifier.
    The mapping is the only thing the CLI prints.
    """
    return FixtureApplyResult(
        mode=mode,
        status=FixtureApplyStatus.TECHNICAL_FAILURE,
        counts=counts,
        detalle=type(exc).__name__,
    )


def _finalize_post_apply(
    *,
    service: ControlledRailwayFixtureService,
    counts: FixtureCounts,
) -> FixtureApplyResult:
    """Refresh the result with the persisted commerce ids after the
    exact post-flush verification passed.

    The staging service deliberately never flushes. The CLI flushes
    once, performs the exact shape verification on the same session,
    asks the service for the persisted commerce numeric IDs only
    after the verification is exact and rebuilds the result so the
    operator evidence row records the canonical, persisted IDs that
    survive the commit.
    """
    commerce_ids = service.staged_commerce_ids()
    return FixtureApplyResult(
        mode=FixtureApplyMode.APPLY,
        status=FixtureApplyStatus.PROVISIONED,
        counts=counts,
        comercio_ids=commerce_ids,
        detalle="resolver_resolved",
    )


def _build_post_flush_conflict_result(
    *,
    counts: FixtureCounts,
) -> FixtureApplyResult:
    """Build the sanitized conflict result for a failed
    post-flush verification.

    The CLI performs exactly one flush and then verifies the staged
    dataset is the exact fixture shape. When that verification does
    not match the locked catalog the CLI rolls back its transaction
    and reports a typed ``conflict`` so the operator can diagnose
    without ever committing a partial or non-fixture dataset.
    """
    return FixtureApplyResult(
        mode=FixtureApplyMode.APPLY,
        status=FixtureApplyStatus.CONFLICT,
        counts=counts,
        detalle="post_flush_verification_failed",
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory: Callable[[], Session] | None = None,
    flush_recorder: Callable[[str], None] | None = None,
    verification_recorder: Callable[[bool], None] | None = None,
) -> int:
    """Run one controlled Railway fixture verification or apply pass.

    The CLI opens a single short-lived ``Session`` and delegates to
    :class:`ControlledRailwayFixtureService`. The CLI is the sole
    owner of the setup transaction: it may ``flush`` exactly once
    after staging the dataset, performs the exact post-flush
    verification on the same session, then commits once only when
    that verification is exact or rolls back on every exception and
    on every non-exact verification result.
    """
    open_session_fn = session_factory or _open_session
    record_flush = flush_recorder
    record_verification = verification_recorder

    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_args(args)

    mode = (
        FixtureApplyMode.APPLY
        if bool(getattr(args, "apply", False))
        else FixtureApplyMode.VERIFY
    )

    session_factory_exc: Exception | None = None
    try:
        session = open_session_fn()
    except Exception as exc:  # noqa: BLE001 - defensive: CLI must surface any session-open failure as a sanitized technical status
        session_factory_exc = exc
        session = None

    if session is None:
        logger.info(
            "controlled_railway_fixture_session_open_failed",
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
        technical_counts = FixtureCounts(0, 0, 0, 0, 0, 0)
        technical_result = FixtureApplyResult(
            mode=mode,
            status=FixtureApplyStatus.TECHNICAL_FAILURE,
            counts=technical_counts,
            detalle=(
                type(session_factory_exc).__name__
                if session_factory_exc is not None
                else "session_factory_returned_none"
            ),
        )
        print(_format_result(technical_result))
        return EXIT_TECHNICAL_FAILURE

    final = FixtureApplyResult(
        mode=mode,
        status=FixtureApplyStatus.TECHNICAL_FAILURE,
        counts=FixtureCounts(0, 0, 0, 0, 0, 0),
    )
    try:
        service = build_service(session)
        try:
            staged = service.verify() if mode is FixtureApplyMode.VERIFY else service.apply()
            if mode is FixtureApplyMode.VERIFY:
                final = staged
            else:
                if staged.status is FixtureApplyStatus.PROVISIONED:
                    if record_flush is not None:
                        record_flush("apply")
                    session.flush()
                    verification_ok = service.verify_staged_dataset_is_exact(
                        staged.counts
                    )
                    if record_verification is not None:
                        record_verification(verification_ok)
                    if verification_ok:
                        final = _finalize_post_apply(
                            service=service,
                            counts=staged.counts,
                        )
                        session.commit()
                    else:
                        session.rollback()
                        final = _build_post_flush_conflict_result(
                            counts=staged.counts,
                        )
                else:
                    final = staged
                    session.rollback()
        except IntegrityError as exc:
            logger.info(
                "controlled_railway_fixture_integrity_error",
                extra={"reason": type(exc).__name__},
            )
            session.rollback()
            final = _handle_typed_exception(
                exc, mode=mode, counts=FixtureCounts(0, 0, 0, 0, 0, 0)
            )
        except Exception as exc:  # noqa: BLE001 - defensive: CLI must not leak provider exceptions or internal type names beyond the safe prefix
            logger.info(
                "controlled_railway_fixture_unexpected_failure",
                extra={"reason": type(exc).__name__},
            )
            session.rollback()
            final = _handle_typed_exception(
                exc, mode=mode, counts=FixtureCounts(0, 0, 0, 0, 0, 0)
            )
    finally:
        session.close()

    print(_format_result(final))
    if final.status is FixtureApplyStatus.TECHNICAL_FAILURE:
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
