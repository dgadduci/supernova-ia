"""Dedicated Railway calibration catalog provisioning CLI.

The CLI is the single, manually invoked entry point that ensures an
empty, dedicated Railway database has the static, deterministic
calibration catalog defined by
:mod:`backend.services.seed_dedicated_railway_calibration_catalog_data`.
It is the only mutation surface for the dedicated calibration
catalog data; the controlled Railway pilot fixture seeder, the
inbound coordinator, the recognizer, the outbox dispatcher and the
existing dedicated-routing provisioner are untouched.

The CLI is deliberately narrow:

* it defaults to ``--verify-only`` and refuses to perform any
  database mutation without an explicit ``--apply`` flag;
* it loads the static catalog definitions from the application
  package and NEVER reads, exports, cleans, resets or compares
  against a local source database;
* it requires the non-secret dedicated target marker
  (``RAILWAY_CALIBRATION_CATALOG_TARGET=dedicated``) before any
  verify or apply run; a missing or wrong marker returns
  ``target_marker_missing`` / ``target_marker_mismatch`` without
  touching the database;
* it refuses a pre-existing partial or non-catalog row in any of
  the catalog-owned tables — including the ``estado_comercio``
  table — and reports a ``conflict`` status instead of repairing,
  overwriting or merging the data;
* it owns the single setup transaction: the staging service in
  :class:`backend.services.seed_dedicated_railway_calibration_catalog_service.DedicatedRailwayCalibrationCatalogService`
  never ``commit`` / ``rollback`` / ``begin`` / ``flush``; the CLI
  may ``flush`` once to expose the staged state to the final
  read-back verification, performs the exact shape verification on
  the same session, commits once only when that verification is
  exact, and rolls back on every exception or non-exact
  verification result;
* it prints ONLY safe operational summaries: mode, status, the
  static ``CatalogApplyStatus`` enum value, the per-table counts,
  the catalog fixture version, the manifest coverage summary and
  the persisted numeric commerce IDs. It NEVER prints, logs or
  includes in an exception the database URL, a phone number, a
  message body, a credential, a signature, the target marker value
  or raw caught exception text.

The CLI exposes one injectable seam so focused tests can wire a
real factory without monkey-patching the global SQLAlchemy session
or the real ``_SessionLocal``:

* ``_open_session`` returns a callable producing one short-lived
  ``Session`` per call.

Exit codes:

* ``0`` — verification reports ``ready`` or apply reports
  ``provisioned`` after the final read-back verification confirmed
  the full catalog set is staged.
* ``1`` — typed technical failure that escaped the staging service
  or a generic uncaught exception.
* ``2`` — input rejection: invalid ``--apply`` value or unexpected
  CLI argument.
* ``3`` — typed non-ready state: ``not_ready``, ``conflict``,
  ``target_marker_missing`` or ``target_marker_mismatch`` in
  either mode. The CLI never exits ``0`` for these states.

The CLI is the sole owner of one setup transaction. It does not
import or invoke any inbound, recognition, outbox, dispatcher or
callback component.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Callable, Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.dependencies import _SessionLocal
from backend.services.seed_dedicated_railway_calibration_catalog_data import (
    DEDICATED_TARGET_ENV_VAR,
    DEDICATED_TARGET_MARKER,
    audit_manifest_coverage,
    get_catalog_fixture_version,
    get_dedicated_target_env_var,
    get_dedicated_target_marker,
)
from backend.services.seed_dedicated_railway_calibration_catalog_service import (
    CatalogApplyMode,
    CatalogApplyResult,
    CatalogApplyStatus,
    CatalogCounts,
    DedicatedRailwayCalibrationCatalogService,
    build_service,
)

logger = logging.getLogger(__name__)


EXIT_OK = 0
EXIT_TECHNICAL_FAILURE = 1
EXIT_INPUT_INVALID = 2
EXIT_NOT_READY = 3


def _read_target_marker() -> str | None:
    """Read the dedicated target marker from the operator environment.

    The function reads the marker value WITHOUT printing it. The
    CLI never echoes the marker value back to stdout/stderr so the
    marker can be safely logged elsewhere without leaking the
    sentinel. The comparison itself happens inside the staging
    service.
    """
    raw = os.environ.get(DEDICATED_TARGET_ENV_VAR)
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    return stripped


def _open_session() -> Session:
    """Open one short-lived ``Session`` for the CLI transaction.

    The seam exists so focused tests can supply their own session
    factory without monkey-patching ``_SessionLocal``. The default
    mirrors the dependency already used by every other project CLI.
    """
    return _SessionLocal()


def _format_counts(counts: CatalogCounts) -> str:
    return (
        f"comercios={counts.comercios} "
        f"categorias={counts.categorias} "
        f"presentaciones={counts.presentaciones} "
        f"productos={counts.productos} "
        f"producto_presentaciones={counts.producto_presentaciones} "
        f"precios={counts.precios}"
    )


def _format_manifest_coverage(extra: dict[str, object] | None) -> str:
    if not extra:
        return ""
    manifest_tokens = extra.get("manifest_tokens")
    covered_tokens = extra.get("covered_tokens")
    missing_tokens = extra.get("missing_tokens")
    ambiguous_tokens = extra.get("ambiguous_tokens")
    if not all(
        isinstance(value, int)
        for value in (
            manifest_tokens,
            covered_tokens,
            missing_tokens,
            ambiguous_tokens,
        )
    ):
        return ""
    return (
        f" manifest_coverage=covered={covered_tokens}"
        f"/total={manifest_tokens}"
        f" missing={missing_tokens}"
        f" ambiguous={ambiguous_tokens}"
    )


def _format_commerce_ids(result: CatalogApplyResult) -> str:
    if not result.comercio_ids:
        return ""
    return " comercio_ids=" + ",".join(
        str(value) for value in result.comercio_ids
    )


def _format_result(result: CatalogApplyResult) -> str:
    """Render a single safe operational summary line.

    The summary is the only thing the CLI writes to stdout for the
    result. It contains the mode, status, counts, catalog fixture
    version, manifest coverage summary and the persisted numeric
    commerce IDs. It NEVER contains a phone number, the database
    URL, credentials, message bodies, signatures, the target
    marker value or raw caught exception text.
    """
    detalle_segment = (
        f" detalle={result.detalle}" if result.detalle else ""
    )
    return (
        f"mode={result.mode.value} status={result.status.value} "
        f"counts={_format_counts(result.counts)}"
        f" fixture_version={get_catalog_fixture_version()}"
        f"{_format_commerce_ids(result)}"
        f"{_format_manifest_coverage(result.extra)}"
        f"{detalle_segment}"
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "Verify or apply the dedicated Railway calibration "
            f"catalog for an empty production-shaped database. The "
            f"CLI requires the non-secret marker "
            f"{get_dedicated_target_env_var()}={get_dedicated_target_marker()} "
            f"in the environment. Default mode is read-only "
            f"verification. The CLI never reads, exports or "
            f"compares against a local development database."
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
            "Explicit apply mode. Stages the static catalog "
            "dataset and commits once after the final read-back "
            "verification. Without this flag the CLI performs a "
            "read-only verification. The CLI refuses to mutate an "
            "empty namespace unless this flag is set."
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


def _exit_code_for_status(status: CatalogApplyStatus) -> int:
    """Map a typed catalog status to the CLI exit code."""
    if status is CatalogApplyStatus.READY:
        return EXIT_OK
    if status is CatalogApplyStatus.PROVISIONED:
        return EXIT_OK
    if status is CatalogApplyStatus.NOT_READY:
        return EXIT_NOT_READY
    if status is CatalogApplyStatus.CONFLICT:
        return EXIT_NOT_READY
    if status is CatalogApplyStatus.TARGET_MARKER_MISSING:
        return EXIT_NOT_READY
    if status is CatalogApplyStatus.TARGET_MARKER_MISMATCH:
        return EXIT_NOT_READY
    return EXIT_TECHNICAL_FAILURE


def _handle_typed_exception(
    exc: Exception,
    *,
    mode: CatalogApplyMode,
    counts: CatalogCounts,
) -> CatalogApplyResult:
    """Translate a typed exception into a sanitized result row.

    The CLI NEVER echoes the exception message because exception
    text could contain the database URL or a fixture identifier.
    The mapping is the only thing the CLI prints.
    """
    return CatalogApplyResult(
        mode=mode,
        status=CatalogApplyStatus.TECHNICAL_FAILURE,
        counts=counts,
        detalle=type(exc).__name__,
    )


def _finalize_post_apply(
    *,
    service: DedicatedRailwayCalibrationCatalogService,
    counts: CatalogCounts,
) -> CatalogApplyResult:
    """Refresh the result with the persisted commerce ids and the
    manifest coverage summary after the exact post-flush
    verification passed.

    The staging service deliberately never flushes. The CLI
    flushes once, performs the exact shape verification on the same
    session, asks the service for the persisted commerce numeric
    IDs and the static manifest coverage only after the
    verification is exact and rebuilds the result so the operator
    evidence row records the canonical, persisted IDs that survive
    the commit.
    """
    commerce_ids = service.staged_commerce_ids()
    return CatalogApplyResult(
        mode=CatalogApplyMode.APPLY,
        status=CatalogApplyStatus.PROVISIONED,
        counts=counts,
        comercio_ids=commerce_ids,
        detalle="resolver_resolved",
        extra={
            "manifest_tokens": audit_manifest_coverage()["manifest_tokens"],
            "covered_tokens": audit_manifest_coverage()["covered_tokens"],
            "missing_tokens": audit_manifest_coverage()["missing_tokens"],
            "ambiguous_tokens": audit_manifest_coverage()["ambiguous_tokens"],
        },
    )


def _build_post_flush_conflict_result(
    *,
    counts: CatalogCounts,
) -> CatalogApplyResult:
    """Build the sanitized conflict result for a failed
    post-flush verification.

    The CLI performs exactly one flush and then verifies the
    staged dataset is the exact catalog shape. When that
    verification does not match the locked catalog the CLI rolls
    back its transaction and reports a typed ``conflict`` so the
    operator can diagnose without ever committing a partial or
    non-catalog dataset.
    """
    return CatalogApplyResult(
        mode=CatalogApplyMode.APPLY,
        status=CatalogApplyStatus.CONFLICT,
        counts=counts,
        detalle="post_flush_verification_failed",
        extra={
            "manifest_tokens": audit_manifest_coverage()["manifest_tokens"],
            "covered_tokens": audit_manifest_coverage()["covered_tokens"],
            "missing_tokens": audit_manifest_coverage()["missing_tokens"],
            "ambiguous_tokens": audit_manifest_coverage()["ambiguous_tokens"],
        },
    )


def _marker_payload(missing: bool) -> CatalogApplyResult:
    """Build the typed marker-missing / marker-mismatch payload.

    The CLI echoes only the static enum value and a sanitized
    detail marker; the marker value is never printed so the
    sentinel can be safely stored in the environment.
    """
    counts = CatalogCounts(0, 0, 0, 0, 0, 0)
    if missing:
        return CatalogApplyResult(
            mode=CatalogApplyMode.VERIFY,
            status=CatalogApplyStatus.TARGET_MARKER_MISSING,
            counts=counts,
            detalle="target_marker_missing",
        )
    return CatalogApplyResult(
        mode=CatalogApplyMode.VERIFY,
        status=CatalogApplyStatus.TARGET_MARKER_MISMATCH,
        counts=counts,
        detalle="target_marker_mismatch",
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory: Callable[[], Session] | None = None,
    target_marker: str | None = None,
    flush_recorder: Callable[[str], None] | None = None,
    verification_recorder: Callable[[bool], None] | None = None,
) -> int:
    """Run one dedicated Railway calibration catalog verification
    or apply pass.

    The CLI opens a single short-lived ``Session`` and delegates to
    :class:`DedicatedRailwayCalibrationCatalogService`. The CLI is
    the sole owner of the setup transaction: it may ``flush``
    exactly once after staging the dataset, performs the exact
    post-flush verification on the same session, then commits once
    only when that verification is exact or rolls back on every
    exception and on every non-exact verification result.

    The ``target_marker`` parameter is injectable so focused tests
    can drive the guard independently of the operator environment.
    When the parameter is ``None`` the CLI reads the marker from
    the environment (only when ``RAILWAY_CALIBRATION_CATALOG_TARGET``
    is set); an explicit empty string is treated as "missing".
    """
    open_session_fn = session_factory or _open_session
    record_flush = flush_recorder
    record_verification = verification_recorder

    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_args(args)

    mode = (
        CatalogApplyMode.APPLY
        if bool(getattr(args, "apply", False))
        else CatalogApplyMode.VERIFY
    )

    effective_marker = (
        target_marker
        if target_marker is not None
        else _read_target_marker()
    )
    if effective_marker is None:
        result = _marker_payload(missing=True)
        if mode is CatalogApplyMode.APPLY:
            result = CatalogApplyResult(
                mode=CatalogApplyMode.APPLY,
                status=result.status,
                counts=result.counts,
                comercio_ids=result.comercio_ids,
                detalle=result.detalle,
                extra=result.extra,
            )
        print(_format_result(result))
        return _exit_code_for_status(result.status)
    if effective_marker != DEDICATED_TARGET_MARKER:
        result = _marker_payload(missing=False)
        if mode is CatalogApplyMode.APPLY:
            result = CatalogApplyResult(
                mode=CatalogApplyMode.APPLY,
                status=result.status,
                counts=result.counts,
                comercio_ids=result.comercio_ids,
                detalle=result.detalle,
                extra=result.extra,
            )
        print(_format_result(result))
        return _exit_code_for_status(result.status)

    session_factory_exc: Exception | None = None
    try:
        session = open_session_fn()
    except Exception as exc:  # noqa: BLE001 - defensive: CLI must surface any session-open failure as a sanitized technical status
        session_factory_exc = exc
        session = None

    if session is None:
        logger.info(
            "dedicated_railway_calibration_session_open_failed",
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
        technical_counts = CatalogCounts(0, 0, 0, 0, 0, 0)
        technical_result = CatalogApplyResult(
            mode=mode,
            status=CatalogApplyStatus.TECHNICAL_FAILURE,
            counts=technical_counts,
            detalle=(
                type(session_factory_exc).__name__
                if session_factory_exc is not None
                else "session_factory_returned_none"
            ),
        )
        print(_format_result(technical_result))
        return EXIT_TECHNICAL_FAILURE

    final = CatalogApplyResult(
        mode=mode,
        status=CatalogApplyStatus.TECHNICAL_FAILURE,
        counts=CatalogCounts(0, 0, 0, 0, 0, 0),
    )
    try:
        service = build_service(session)
        try:
            if mode is CatalogApplyMode.VERIFY:
                staged = service.verify(
                    target_marker=effective_marker,
                    expected_marker=DEDICATED_TARGET_MARKER,
                )
                final = staged
            else:
                staged = service.apply(
                    target_marker=effective_marker,
                    expected_marker=DEDICATED_TARGET_MARKER,
                )
                if staged.status is CatalogApplyStatus.PROVISIONED:
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
                    if staged.status in (
                        CatalogApplyStatus.CONFLICT,
                        CatalogApplyStatus.READY,
                    ):
                        session.rollback()
        except IntegrityError as exc:
            logger.info(
                "dedicated_railway_calibration_integrity_error",
                extra={"reason": type(exc).__name__},
            )
            session.rollback()
            final = _handle_typed_exception(
                exc, mode=mode, counts=CatalogCounts(0, 0, 0, 0, 0, 0)
            )
        except Exception as exc:  # noqa: BLE001 - defensive: CLI must not leak provider exceptions or internal type names beyond the safe prefix
            logger.info(
                "dedicated_railway_calibration_unexpected_failure",
                extra={"reason": type(exc).__name__},
            )
            session.rollback()
            final = _handle_typed_exception(
                exc, mode=mode, counts=CatalogCounts(0, 0, 0, 0, 0, 0)
            )
    finally:
        session.close()

    print(_format_result(final))
    if final.status is CatalogApplyStatus.TECHNICAL_FAILURE:
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
