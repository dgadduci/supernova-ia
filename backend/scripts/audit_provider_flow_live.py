"""Read-only live audit of the integrated provider flow.

The CLI is intended to be started before the operator sends Twilio test
messages from the ``supernova-ia`` Railway service shell. It polls the
durable provider receipt, processing, LLM timing and outbound rows
without mutating application state so the operator can locate the last
persisted boundary in the message pipeline while real messages flow.

The auditor never reads stdout from ``supernova-ia``, never invokes
Railway, never sends HTTP provider requests, never claims work, never
commits, never flushes, never updates and never deletes. Each polling
iteration opens a read-only application session, performs bounded
``SELECT`` s, closes the session, and discards the result. Output
contains only safe numeric ids, opaque receipt fingerprints, closed
state/category values, bounded counts and timestamps so the timeline
remains shareable over a chat channel without leaking payloads.

The exit code is::

    * ``0`` on clean termination (duration elapsed or ``Ctrl-C``);
    * ``2`` when arguments fail validation;
    * ``1`` when a polling read fails — only the closed category is
      emitted, no exception text or connection details.

The command can be executed as::

    PYTHONPATH=. python -m backend.scripts.audit_provider_flow_live \\
        --duration-seconds 600 \\
        --interval-seconds 1
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import os
import signal
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config.database_url import normalize_database_url
from backend.models.mensaje_proveedor_saliente import MensajeProveedorSaliente
from backend.models.procesamiento_mensaje_proveedor import (
    ProcesamientoMensajeProveedor,
)
from backend.models.recepcion_mensaje_proveedor import RecepcionMensajeProveedor

__all__ = [
    "DEFAULT_DURATION_SECONDS",
    "DEFAULT_INTERVAL_SECONDS",
    "MAX_RECEPCIONES_PER_POLL",
    "ProviderSnapshot",
    "build_arg_parser",
    "collect_provider_snapshot",
    "diff_snapshots",
    "format_snapshot",
    "main",
    "select_session_factory",
]


DEFAULT_DATABASE_URL = "postgresql+psycopg:///supernova_test"
DEFAULT_INTERVAL_SECONDS = 1.0
DEFAULT_DURATION_SECONDS = 600.0
MAX_RECEPCIONES_PER_POLL = 500
CLOCK_SKEW_SECONDS = 5
FINGERPRINT_HEX_CHARS = 16
_PROCESSING_FIELDS_MAX_LEN = 48
_OUTBOX_STATE_MAX_LEN = 32
_TERMINAL_OBSERVATION_BANNER = "procesado + outbox_row_count=0"


def _now_utc() -> _dt.datetime:
    """Return the current UTC time as a timezone-aware ``datetime``."""
    return _dt.datetime.now(_dt.timezone.utc)


def _coerce_utc(value: _dt.datetime | None) -> _dt.datetime | None:
    """Return ``value`` as a timezone-aware UTC datetime."""
    if value is None:
        return None
    if not isinstance(value, _dt.datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=_dt.timezone.utc)
    return value.astimezone(_dt.timezone.utc)


def _iso_utc(value: _dt.datetime | None) -> str:
    """Return ``value`` formatted as an ISO-8601 UTC string.

    ``None`` returns an empty string so the caller can render missing
    timestamps without printing the literal word ``None``.
    """
    coerced = _coerce_utc(value)
    if coerced is None:
        return ""
    return coerced.isoformat()


def _short_fingerprint(proveedor: str, identificador_recepcion: str) -> str:
    """Return a short SHA-256 fingerprint of the provider receipt key.

    The fingerprint is opaque and never reveals the raw provider key.
    It is stable per ``(proveedor, identificador_recepcion)`` pair so
    successive polls can group observations without exposing the
    underlying value.
    """
    joined = f"{proveedor}|{identificador_recepcion}".encode()
    return hashlib.sha256(joined).hexdigest()[:FINGERPRINT_HEX_CHARS]


def _bounded_str(
    value: Any,
    *,
    max_len: int,
) -> str | None:
    """Return ``value`` as a bounded string or ``None``.

    The helper strips surrounding whitespace, caps the length and
    treats ``None`` / empty / non-string values as ``None`` so a safe
    snapshot never echoes unexpected payload bytes.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:max_len]


def _coerce_optional_int(value: Any) -> int | None:
    """Return ``value`` as ``int`` when reasonable, else ``None``."""

    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        try:
            return int(cleaned)
        except ValueError:
            return None
    return None


@dataclass(frozen=True, slots=True)
class ProviderSnapshot:
    """Safe read-only snapshot of one provider receipt.

    The dataclass is the single audit output boundary. Every field is
    either a closed enum value, a bounded count, an opaque hash or a
    numeric row identifier — never raw provider payloads.
    """

    recepcion_id: int
    fingerprint: str
    fecha_recepcion: _dt.datetime
    procesamiento_id: int | None
    procesamiento_estado: str | None
    intentos: int | None
    categoria_ultimo_fallo: str | None
    codigo_ultimo_fallo: str | None
    llm_resultado: str | None
    llm_solicitado_en: _dt.datetime | None
    llm_finalizado_en: _dt.datetime | None
    outbox_row_count: int
    outbox_first_id: int | None
    outbox_estados: tuple[str, ...]
    observado_en: _dt.datetime

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dict representation."""

        def _ts(value: _dt.datetime | None) -> str | None:
            iso = _iso_utc(value)
            return iso or None

        return {
            "recepcion_id": int(self.recepcion_id),
            "fingerprint": self.fingerprint,
            "fecha_recepcion": _ts(self.fecha_recepcion),
            "procesamiento_id": (
                int(self.procesamiento_id)
                if self.procesamiento_id is not None
                else None
            ),
            "procesamiento_estado": self.procesamiento_estado,
            "intentos": self.intentos,
            "categoria_ultimo_fallo": self.categoria_ultimo_fallo,
            "codigo_ultimo_fallo": self.codigo_ultimo_fallo,
            "llm_resultado": self.llm_resultado,
            "llm_solicitado_en": _ts(self.llm_solicitado_en),
            "llm_finalizado_en": _ts(self.llm_finalizado_en),
            "outbox_row_count": int(self.outbox_row_count),
            "outbox_first_id": (
                int(self.outbox_first_id) if self.outbox_first_id is not None else None
            ),
            "outbox_estados": list(self.outbox_estados),
            "observado_en": _ts(self.observado_en),
        }


def _safe_failure_category(value: Any) -> str | None:
    return _bounded_str(value, max_len=_PROCESSING_FIELDS_MAX_LEN)


def _safe_failure_code(value: Any) -> str | None:
    return _bounded_str(value, max_len=_PROCESSING_FIELDS_MAX_LEN)


def _safe_processing_estado(value: Any) -> str | None:
    return _bounded_str(value, max_len=32)


def _safe_outbox_estado(value: Any) -> str | None:
    return _bounded_str(value, max_len=_OUTBOX_STATE_MAX_LEN)


def _row_to_snapshot(
    *,
    row: Any,
    outbox_counts: dict[int, int],
    outbox_first_ids: dict[int, int | None],
    outbox_estados: dict[int, tuple[str, ...]],
    now: _dt.datetime,
) -> ProviderSnapshot:
    """Build a :class:`ProviderSnapshot` from a single joined row."""

    (
        recepcion_id,
        proveedor,
        identificador_recepcion,
        fecha_recepcion,
        procesamiento_id,
        procesamiento_estado,
        intentos,
        categoria_ultimo_fallo,
        codigo_ultimo_fallo,
        llm_resultado,
        llm_solicitado_en,
        llm_finalizado_en,
    ) = row

    fingerprint = _short_fingerprint(
        str(proveedor),
        str(identificador_recepcion),
    )
    recepcion_id_int = int(recepcion_id)
    fecha_recepcion_utc = _coerce_utc(fecha_recepcion)
    if fecha_recepcion_utc is None:
        raise ValueError("recepcion fecha_recepcion must be timezone-aware")
    return ProviderSnapshot(
        recepcion_id=recepcion_id_int,
        fingerprint=fingerprint,
        fecha_recepcion=fecha_recepcion_utc,
        procesamiento_id=(
            int(procesamiento_id) if procesamiento_id is not None else None
        ),
        procesamiento_estado=_safe_processing_estado(
            procesamiento_estado,
        ),
        intentos=int(intentos) if intentos is not None else None,
        categoria_ultimo_fallo=_safe_failure_category(
            categoria_ultimo_fallo,
        ),
        codigo_ultimo_fallo=_safe_failure_code(
            codigo_ultimo_fallo,
        ),
        llm_resultado=_bounded_str(llm_resultado, max_len=16),
        llm_solicitado_en=_coerce_utc(llm_solicitado_en),
        llm_finalizado_en=_coerce_utc(llm_finalizado_en),
        outbox_row_count=int(outbox_counts.get(recepcion_id_int, 0)),
        outbox_first_id=_coerce_optional_int(
            outbox_first_ids.get(recepcion_id_int),
        ),
        outbox_estados=outbox_estados.get(recepcion_id_int, ()),
        observado_en=now,
    )


def _load_outbox_state(
    session: Session,
    *,
    recepcion_ids: Iterable[int],
) -> tuple[
    dict[int, int],
    dict[int, int | None],
    dict[int, tuple[str, ...]],
]:
    """Return bounded outbox counts, first ids and states by receipt.

    The query projects only ``id``, ``estado`` and the foreign key; it
    never touches ``cuerpo``, ``destinatario_e164`` or
    ``identificador_proveedor``.
    """
    outbox_counts: dict[int, int] = {}
    outbox_first_ids: dict[int, int | None] = {}
    outbox_estados: dict[int, tuple[str, ...]] = {}

    recepcion_id_tuple = tuple(recepcion_ids)
    if not recepcion_id_tuple:
        return outbox_counts, outbox_first_ids, outbox_estados

    stmt = (
        select(
            MensajeProveedorSaliente.recepcion_mensaje_proveedor_id,
            func.min(MensajeProveedorSaliente.id),
            func.array_agg(
                func.coalesce(MensajeProveedorSaliente.estado, ""),
            ),
        )
        .where(
            MensajeProveedorSaliente.recepcion_mensaje_proveedor_id.in_(
                recepcion_id_tuple,
            )
        )
        .group_by(MensajeProveedorSaliente.recepcion_mensaje_proveedor_id)
    )

    for (
        recepcion_id,
        first_id,
        estados,
    ) in session.execute(stmt).all():
        safe_estados = tuple(
            value
            for value in (_safe_outbox_estado(item) for item in (estados or []))
            if value is not None
        )
        rid = int(recepcion_id)
        outbox_counts[rid] = len(safe_estados)
        outbox_first_ids[rid] = int(first_id) if first_id is not None else None
        outbox_estados[rid] = safe_estados
    return outbox_counts, outbox_first_ids, outbox_estados


def collect_provider_snapshot(
    session: Session,
    *,
    start_window: _dt.datetime,
    now: _dt.datetime,
    max_rows: int = MAX_RECEPCIONES_PER_POLL,
    clock_skew_seconds: int = CLOCK_SKEW_SECONDS,
) -> dict[int, ProviderSnapshot]:
    """Return a safe snapshot keyed by numeric ``recepcion_id``.

    ``session`` is consumed strictly read-only: the helper only issues
    bounded ``SELECT`` statements, never ``INSERT``, ``UPDATE``,
    ``DELETE``, claim, lease, retry, replay or dispatcher code, and the
    caller is expected to close the session on return. ``start_window``
    is the inclusive lower bound (in UTC) on ``fecha_recepcion`` with
    a small ``clock_skew_seconds`` allowance to absorb clock drift
    between the auditor and the database server.
    """
    start_window_lower = start_window - _dt.timedelta(seconds=clock_skew_seconds)

    receipt_stmt = (
        select(
            RecepcionMensajeProveedor.id,
            RecepcionMensajeProveedor.proveedor,
            RecepcionMensajeProveedor.identificador_recepcion,
            RecepcionMensajeProveedor.fecha_recepcion,
            ProcesamientoMensajeProveedor.id,
            ProcesamientoMensajeProveedor.estado,
            ProcesamientoMensajeProveedor.intentos,
            ProcesamientoMensajeProveedor.categoria_ultimo_fallo,
            ProcesamientoMensajeProveedor.codigo_ultimo_fallo,
            ProcesamientoMensajeProveedor.llm_resultado,
            ProcesamientoMensajeProveedor.llm_solicitado_en,
            ProcesamientoMensajeProveedor.llm_finalizado_en,
        )
        .select_from(RecepcionMensajeProveedor)
        .outerjoin(
            ProcesamientoMensajeProveedor,
            ProcesamientoMensajeProveedor.recepcion_mensaje_proveedor_id
            == RecepcionMensajeProveedor.id,
        )
        .where(RecepcionMensajeProveedor.fecha_recepcion >= start_window_lower)
        .order_by(RecepcionMensajeProveedor.id)
        .limit(int(max_rows))
    )

    rows = list(session.execute(receipt_stmt).all())
    if not rows:
        return {}
    recepcion_ids = sorted({int(row[0]) for row in rows})
    outbox_counts, outbox_first_ids, outbox_estados = _load_outbox_state(
        session,
        recepcion_ids=recepcion_ids,
    )

    snapshots: dict[int, ProviderSnapshot] = {}
    for row in rows:
        snapshot = _row_to_snapshot(
            row=row,
            outbox_counts=outbox_counts,
            outbox_first_ids=outbox_first_ids,
            outbox_estados=outbox_estados,
            now=now,
        )
        snapshots[snapshot.recepcion_id] = snapshot
    return snapshots


def _snapshots_differ(
    previous: ProviderSnapshot,
    current: ProviderSnapshot,
) -> bool:
    """Return ``True`` when two snapshots differ in any safe field."""

    return (
        previous.fingerprint != current.fingerprint
        or previous.fecha_recepcion != current.fecha_recepcion
        or previous.procesamiento_id != current.procesamiento_id
        or previous.procesamiento_estado != current.procesamiento_estado
        or previous.intentos != current.intentos
        or previous.categoria_ultimo_fallo != current.categoria_ultimo_fallo
        or previous.codigo_ultimo_fallo != current.codigo_ultimo_fallo
        or previous.llm_resultado != current.llm_resultado
        or previous.llm_solicitado_en != current.llm_solicitado_en
        or previous.llm_finalizado_en != current.llm_finalizado_en
        or previous.outbox_row_count != current.outbox_row_count
        or previous.outbox_first_id != current.outbox_first_id
        or previous.outbox_estados != current.outbox_estados
    )


def diff_snapshots(
    previous: dict[int, ProviderSnapshot],
    current: dict[int, ProviderSnapshot],
) -> list[ProviderSnapshot]:
    """Return new and changed snapshots in ascending ``recepcion_id``.

    A receipt appears in the diff the first time it is observed and
    again whenever any safe field changes. Identical snapshots are
    suppressed so the operator timeline is not flooded. A snapshot
    that transitions to ``processed`` with ``outbox_row_count == 0``
    remains an observable terminal observation; it is emitted exactly
    once, just like any other state transition.
    """
    changed: list[ProviderSnapshot] = []
    for recepcion_id in sorted(current):
        snap = current[recepcion_id]
        previous_snap = previous.get(recepcion_id)
        if previous_snap is None or _snapshots_differ(previous_snap, snap):
            changed.append(snap)
    return changed


def format_snapshot(snap: ProviderSnapshot) -> str:
    """Return a human-readable rendering of ``snap``.

    The output only contains safe fields, the explicit
    ``procesado + outbox_row_count=0`` marker, and the observation
    timestamp. It never prints message bodies, recipients, provider
    SIDs, prompts, responses, exception text or connection strings.
    """
    lines: list[str] = []
    lines.append(f"obs: {_iso_utc(snap.observado_en)}")
    lines.append(f"  recepcion_id             : {snap.recepcion_id}")
    lines.append(f"  fingerprint              : {snap.fingerprint}")
    lines.append(f"  fecha_recepcion          : {_iso_utc(snap.fecha_recepcion)}")
    if snap.procesamiento_id is None:
        lines.append("  procesamiento_id         : <absent>")
        lines.append("  procesamiento_estado     : <absent>")
        lines.append("  intentos                 : <absent>")
        lines.append("  categoria_ultimo_fallo   : <none>")
        lines.append("  codigo_ultimo_fallo      : <none>")
        lines.append("  llm_resultado            : <none>")
        lines.append("  llm_solicitado_en        : ")
        lines.append("  llm_finalizado_en        : ")
    else:
        lines.append(f"  procesamiento_id         : {snap.procesamiento_id}")
        lines.append(
            f"  procesamiento_estado     : {snap.procesamiento_estado or '<none>'}"
        )
        lines.append(f"  intentos                 : {snap.intentos}")
        lines.append(
            f"  categoria_ultimo_fallo   : {snap.categoria_ultimo_fallo or '<none>'}"
        )
        lines.append(
            f"  codigo_ultimo_fallo      : {snap.codigo_ultimo_fallo or '<none>'}"
        )
        lines.append(f"  llm_resultado            : {snap.llm_resultado or '<none>'}")
        lines.append(f"  llm_solicitado_en        : {_iso_utc(snap.llm_solicitado_en)}")
        lines.append(f"  llm_finalizado_en        : {_iso_utc(snap.llm_finalizado_en)}")
    lines.append(f"  outbox_row_count         : {snap.outbox_row_count}")
    if snap.outbox_first_id is not None:
        lines.append(f"  outbox_first_id          : {snap.outbox_first_id}")
    if snap.outbox_estados:
        lines.append(f"  outbox_estados           : {','.join(snap.outbox_estados)}")
    if snap.procesamiento_estado == "processed" and snap.outbox_row_count == 0:
        lines.append(f"  observation              : {_TERMINAL_OBSERVATION_BANNER}")
    return "\n".join(lines)


def _validate_positive(value: float, *, name: str) -> float:
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero (got {value!r})")
    return float(value)


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""

    parser = argparse.ArgumentParser(
        prog="audit_provider_flow_live",
        description=(
            "Read-only live audit of the integrated provider flow. "
            "Polls the durable receipt, processing, LLM timing and "
            "outbound rows without mutating application state."
        ),
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help=(
            "Polling interval in seconds; must be > 0. "
            f"Default: {DEFAULT_INTERVAL_SECONDS}."
        ),
    )
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=DEFAULT_DURATION_SECONDS,
        help=(
            "Maximum audit duration in seconds; must be > 0. "
            f"Default: {DEFAULT_DURATION_SECONDS}."
        ),
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help=(
            "SQLAlchemy database URL. Default: SUPERNOVA_DATABASE_URL or "
            f"the {DEFAULT_DATABASE_URL!r} fallback."
        ),
    )
    return parser


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    return build_arg_parser().parse_args(argv)


def select_session_factory(database_url: str) -> tuple[Engine, Callable[[], Session]]:
    """Build an engine and a sessionmaker for read-only auditing."""

    engine = create_engine(normalize_database_url(database_url))
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    return engine, factory


def _safe_error_label(exc: BaseException) -> str:
    """Return the closed ``module.Class`` label of an exception."""

    cls = type(exc)
    return f"{cls.__module__}.{cls.__qualname__}"


def _sleep_until(
    target: _dt.datetime,
    *,
    is_stop_requested: Callable[[], bool],
) -> bool:
    """Sleep until ``target`` returns ``True`` if interrupted."""

    while True:
        if is_stop_requested():
            return True
        remaining = (target - _now_utc()).total_seconds()
        if remaining <= 0:
            return False
        time.sleep(min(remaining, 0.25))


def main(argv: list[str] | None = None) -> int:
    """Run the audit CLI.

    Returns the documented exit code (``0`` on clean termination, ``2``
    on invalid arguments, ``1`` when a polling read fails). The
    function is safe to invoke from tests without side effects by
    passing ``argv`` explicitly.
    """
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2) if isinstance(exc.code, int) else 2

    try:
        interval = _validate_positive(
            args.interval_seconds,
            name="--interval-seconds",
        )
        duration = _validate_positive(
            args.duration_seconds,
            name="--duration-seconds",
        )
    except (ValueError, argparse.ArgumentTypeError) as exc:
        print(f"audit: invalid arguments: {exc}", file=sys.stderr)
        return 2

    database_url = (
        args.database_url
        if args.database_url
        else os.environ.get("SUPERNOVA_DATABASE_URL", DEFAULT_DATABASE_URL)
    )

    engine, session_factory = select_session_factory(database_url)
    start = _now_utc()
    end = start + _dt.timedelta(seconds=duration)

    stop_requested = {"flag": False}

    def _request_stop() -> None:
        stop_requested["flag"] = True

    previous_handler = signal.signal(signal.SIGINT, lambda *_: _request_stop())

    print(
        "audit: start="
        f"{_iso_utc(start)} duration_seconds={duration} "
        f"interval_seconds={interval}"
    )
    sys.stdout.flush()

    previous_snapshot: dict[int, ProviderSnapshot] = {}
    exit_code = 0
    try:
        while True:
            now = _now_utc()
            if stop_requested["flag"] or now >= end:
                break

            current_snapshot: dict[int, ProviderSnapshot] = {}
            try:
                with session_factory() as session:
                    current_snapshot = collect_provider_snapshot(
                        session,
                        start_window=start,
                        now=now,
                    )
            except Exception as exc:  # noqa: BLE001
                category = _safe_error_label(exc)
                print(
                    "audit: read_error category="
                    f"{category} observado_en={_iso_utc(now)}",
                    file=sys.stderr,
                )
                sys.stderr.flush()
                exit_code = 1
                current_snapshot = {}

            changed = diff_snapshots(previous_snapshot, current_snapshot)
            for snap in changed:
                print(format_snapshot(snap))
                print()
                sys.stdout.flush()

            previous_snapshot = current_snapshot

            interval_target = now + _dt.timedelta(seconds=interval)
            sleep_until = min(interval_target, end)
            interrupted = _sleep_until(
                sleep_until,
                is_stop_requested=lambda: stop_requested["flag"],
            )
            if interrupted:
                break
    finally:
        try:
            signal.signal(signal.SIGINT, previous_handler)
        except (TypeError, ValueError):
            pass
        engine.dispose()

    print(f"audit: terminated observado_en={_iso_utc(_now_utc())}")
    sys.stdout.flush()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
