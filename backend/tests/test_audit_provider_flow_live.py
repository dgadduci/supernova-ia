"""Focused tests for :mod:`backend.scripts.audit_provider_flow_live`.

The auditor is a read-only CLI that must:

* poll bounded safe fields only;
* never write, mutate, claim, lease, retry or replay;
* detect new receipts and durable state transitions;
* expose the ``procesado + outbox_row_count=0`` terminal observation;
* terminate cleanly on duration and ``Ctrl-C``;
* keep message bodies, recipients, provider SIDs and credentials out
  of the printed timeline.

The tests use an in-process fake session that records every
``execute`` call and returns pre-canned rows so the script logic is
exercised without requiring a live PostgreSQL database.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import unittest
from collections.abc import Iterable
from contextlib import redirect_stderr, redirect_stdout
from typing import Any
from unittest import mock

from sqlalchemy import select

from backend.scripts.audit_provider_flow_live import (
    DEFAULT_DURATION_SECONDS,
    DEFAULT_INTERVAL_SECONDS,
    FINGERPRINT_HEX_CHARS,
    MAX_RECEPCIONES_PER_POLL,
    ProviderSnapshot,
    build_arg_parser,
    collect_provider_snapshot,
    diff_snapshots,
    format_snapshot,
    main,
)

_UTC = _dt.timezone.utc


def _utc(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
):
    return _dt.datetime(year, month, day, hour, minute, second, tzinfo=_UTC)


class _FakeResult:
    """Minimal stand-in for the SQLAlchemy result ``.all()`` chain."""

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = list(rows)

    def all(self) -> list[tuple]:
        return list(self._rows)


class _FakeSession:
    """Minimal Session that records every ``execute`` call.

    The first call returns ``receipt_rows``; subsequent calls return
    ``outbox_rows``. This mirrors the exact order
    :func:`collect_provider_snapshot` issues statements in.
    """

    def __init__(
        self,
        receipt_rows: Iterable[tuple] | None = None,
        outbox_rows: Iterable[tuple] | None = None,
    ) -> None:
        self.receipt_rows = list(receipt_rows or [])
        self.outbox_rows = list(outbox_rows or [])
        self.executed_statements: list[Any] = []
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.flushed = False
        self.add_calls: list[Any] = []
        self.delete_calls: list[Any] = []
        self.update_calls: list[Any] = []

    def __enter__(self) -> Any:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def close(self) -> None:
        self.closed = True

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def flush(self) -> None:
        self.flushed = True

    def add(self, row: Any) -> None:
        self.add_calls.append(row)

    def delete(self, row: Any) -> None:
        self.delete_calls.append(row)

    def execute(self, stmt: Any) -> _FakeResult:
        self.executed_statements.append(stmt)
        if len(self.executed_statements) == 1:
            return _FakeResult(self.receipt_rows)
        return _FakeResult(self.outbox_rows)


def _snapshot(
    session: _FakeSession,
    start_window: _dt.datetime,
    now: _dt.datetime,
    *,
    max_rows: int = MAX_RECEPCIONES_PER_POLL,
    clock_skew_seconds: int = 5,
) -> dict[int, ProviderSnapshot]:
    return collect_provider_snapshot(
        session,  # type: ignore[arg-type]
        start_window=start_window,
        now=now,
        max_rows=max_rows,
        clock_skew_seconds=clock_skew_seconds,
    )


def _receipt_row(
    *,
    recepcion_id: int,
    proveedor: str = "twilio",
    identificador_recepcion: str | None = None,
    fecha_recepcion: _dt.datetime | None = None,
    procesamiento_id: int | None = None,
    procesamiento_estado: str | None = None,
    intentos: int | None = None,
    categoria_ultimo_fallo: str | None = None,
    codigo_ultimo_fallo: str | None = None,
    llm_resultado: str | None = None,
    llm_solicitado_en: _dt.datetime | None = None,
    llm_finalizado_en: _dt.datetime | None = None,
) -> tuple:
    """Build a fake joined row tuple in the projection order."""
    if identificador_recepcion is None:
        identificador_recepcion = f"SM-{recepcion_id:04d}"
    if fecha_recepcion is None:
        fecha_recepcion = _utc(2026, 8, 24, 12, 0, 0)
    return (
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
    )


def _outbox_row(
    *,
    recepcion_id: int,
    first_id: int | None,
    estados: list[object],
) -> tuple:
    return (recepcion_id, first_id, estados)


class InitialBaselineTest(unittest.TestCase):
    """No pre-existing durable rows; the start line is emitted cleanly."""

    def test_no_rows_returns_empty_snapshot(self) -> None:
        session = _FakeSession(receipt_rows=[])
        start = _utc(2026, 8, 24, 12, 0, 0)
        snap = _snapshot(
            session,
            start_window=start,
            now=_utc(2026, 8, 24, 12, 0, 1),
        )
        self.assertEqual(snap, {})
        self.assertEqual(len(session.executed_statements), 1)
        compiled_first = str(
            session.executed_statements[0].compile(
                compile_kwargs={"literal_binds": True}
            )
        )
        self.assertIn("FROM recepciones_mensajes_proveedor", compiled_first)
        self.assertIn(
            "LEFT OUTER JOIN procesamientos_mensajes_proveedor",
            compiled_first,
        )


class NewReceiptTest(unittest.TestCase):
    """A new receipt is observed as a safe snapshot."""

    def test_new_receipt_without_processing_is_safe_snapshot(self) -> None:
        fecha = _utc(2026, 8, 24, 12, 0, 0)
        session = _FakeSession(
            receipt_rows=[
                _receipt_row(
                    recepcion_id=10,
                    proveedor="twilio",
                    identificador_recepcion="SM-secret-aaaaaaaa-bbbb-cccc",
                    fecha_recepcion=fecha,
                )
            ]
        )
        snap = _snapshot(
            session,
            start_window=fecha,
            now=fecha,
        )
        self.assertEqual(set(snap), {10})
        row = snap[10]
        self.assertIsNone(row.procesamiento_id)
        self.assertEqual(row.procesamiento_estado, None)
        self.assertEqual(row.intentos, None)
        self.assertEqual(row.outbox_row_count, 0)
        self.assertEqual(row.outbox_estados, ())
        self.assertEqual(row.outbox_first_id, None)
        self.assertEqual(len(row.fingerprint), FINGERPRINT_HEX_CHARS)
        self.assertTrue(all(c in "0123456789abcdef" for c in row.fingerprint))

    def test_receipt_string_is_replaced_by_fingerprint(self) -> None:
        identifier = "SM-SECRET-NEVER-PRINT"
        fecha = _utc(2026, 8, 24, 12, 0, 0)
        session = _FakeSession(
            receipt_rows=[
                _receipt_row(
                    recepcion_id=11,
                    identificador_recepcion=identifier,
                    fecha_recepcion=fecha,
                )
            ]
        )
        snap = _snapshot(
            session,
            start_window=fecha,
            now=fecha,
        )
        text = format_snapshot(snap[11])
        self.assertNotIn(identifier, text)
        self.assertNotIn("SM-SECRET", text)
        self.assertIn(snap[11].fingerprint, text)

    def test_snapshot_to_dict_does_not_leak_provider_string(self) -> None:
        identifier = "SM-SECRET-DICT"
        fecha = _utc(2026, 8, 24, 12, 0, 0)
        session = _FakeSession(
            receipt_rows=[
                _receipt_row(
                    recepcion_id=12,
                    identificador_recepcion=identifier,
                    fecha_recepcion=fecha,
                )
            ]
        )
        snap = _snapshot(
            session,
            start_window=fecha,
            now=fecha,
        )
        rendered = json.dumps(snap[12].to_dict())
        self.assertNotIn(identifier, rendered)
        self.assertNotIn("SM-SECRET", rendered)


class ProcessingLifecycleTest(unittest.TestCase):
    """State transitions and LLM timing fields are projected safely."""

    def test_pending_processing_projects_llm_null(self) -> None:
        fecha = _utc(2026, 8, 24, 12, 0, 0)
        session = _FakeSession(
            receipt_rows=[
                _receipt_row(
                    recepcion_id=20,
                    fecha_recepcion=fecha,
                    procesamiento_id=200,
                    procesamiento_estado="pending",
                    intentos=0,
                )
            ]
        )
        snap = _snapshot(
            session,
            start_window=fecha,
            now=fecha,
        )
        row = snap[20]
        self.assertEqual(row.procesamiento_id, 200)
        self.assertEqual(row.procesamiento_estado, "pending")
        self.assertEqual(row.intentos, 0)
        self.assertIsNone(row.llm_solicitado_en)
        self.assertIsNone(row.llm_finalizado_en)

    def test_leased_processing_increments_attempts(self) -> None:
        fecha = _utc(2026, 8, 24, 12, 0, 0)
        session = _FakeSession(
            receipt_rows=[
                _receipt_row(
                    recepcion_id=21,
                    fecha_recepcion=fecha,
                    procesamiento_id=201,
                    procesamiento_estado="leased",
                    intentos=1,
                    llm_solicitado_en=_utc(2026, 8, 24, 12, 0, 1),
                )
            ]
        )
        snap = _snapshot(
            session,
            start_window=fecha,
            now=fecha,
        )
        row = snap[21]
        self.assertEqual(row.intentos, 1)
        self.assertEqual(row.procesamiento_estado, "leased")
        self.assertEqual(row.llm_solicitado_en, _utc(2026, 8, 24, 12, 0, 1))
        self.assertIsNone(row.llm_finalizado_en)

    def test_retryable_processing_exposes_failure_category_and_code(self) -> None:
        fecha = _utc(2026, 8, 24, 12, 0, 0)
        session = _FakeSession(
            receipt_rows=[
                _receipt_row(
                    recepcion_id=22,
                    fecha_recepcion=fecha,
                    procesamiento_id=202,
                    procesamiento_estado="retryable",
                    intentos=2,
                    categoria_ultimo_fallo="pipeline_error",
                    codigo_ultimo_fallo="timeout",
                    llm_resultado="timeout",
                    llm_solicitado_en=_utc(2026, 8, 24, 12, 0, 1),
                    llm_finalizado_en=_utc(2026, 8, 24, 12, 0, 5),
                )
            ]
        )
        snap = _snapshot(
            session,
            start_window=fecha,
            now=fecha,
        )
        row = snap[22]
        self.assertEqual(row.procesamiento_estado, "retryable")
        self.assertEqual(row.intentos, 2)
        self.assertEqual(row.categoria_ultimo_fallo, "pipeline_error")
        self.assertEqual(row.codigo_ultimo_fallo, "timeout")
        self.assertEqual(row.llm_resultado, "timeout")

    def test_processed_processing_preserves_terminal_state(self) -> None:
        fecha = _utc(2026, 8, 24, 12, 0, 0)
        session = _FakeSession(
            receipt_rows=[
                _receipt_row(
                    recepcion_id=23,
                    fecha_recepcion=fecha,
                    procesamiento_id=203,
                    procesamiento_estado="processed",
                    intentos=1,
                    llm_resultado="completed",
                    llm_solicitado_en=_utc(2026, 8, 24, 12, 0, 1),
                    llm_finalizado_en=_utc(2026, 8, 24, 12, 0, 3),
                )
            ]
        )
        snap = _snapshot(
            session,
            start_window=fecha,
            now=fecha,
        )
        row = snap[23]
        self.assertEqual(row.procesamiento_estado, "processed")
        self.assertEqual(row.llm_resultado, "completed")


class FailedProcessingTest(unittest.TestCase):
    def test_failed_terminal_processing_exposes_safe_failure(self) -> None:
        fecha = _utc(2026, 8, 24, 12, 0, 0)
        session = _FakeSession(
            receipt_rows=[
                _receipt_row(
                    recepcion_id=24,
                    fecha_recepcion=fecha,
                    procesamiento_id=204,
                    procesamiento_estado="failed_terminal",
                    intentos=3,
                    categoria_ultimo_fallo="budget_exhausted",
                    codigo_ultimo_fallo="max_attempts",
                    llm_resultado="error",
                    llm_solicitado_en=_utc(2026, 8, 24, 12, 0, 1),
                    llm_finalizado_en=_utc(2026, 8, 24, 12, 0, 2),
                )
            ]
        )
        snap = _snapshot(
            session,
            start_window=fecha,
            now=fecha,
        )
        row = snap[24]
        self.assertEqual(row.procesamiento_estado, "failed_terminal")
        self.assertEqual(row.intentos, 3)
        self.assertEqual(row.categoria_ultimo_fallo, "budget_exhausted")
        self.assertEqual(row.codigo_ultimo_fallo, "max_attempts")
        self.assertEqual(row.llm_resultado, "error")


class OutboxProjectionTest(unittest.TestCase):
    def test_outbox_row_count_and_states_are_bounded(self) -> None:
        fecha = _utc(2026, 8, 24, 12, 0, 0)
        session = _FakeSession(
            receipt_rows=[
                _receipt_row(
                    recepcion_id=30,
                    fecha_recepcion=fecha,
                    procesamiento_id=300,
                    procesamiento_estado="processed",
                )
            ],
            outbox_rows=[
                _outbox_row(
                    recepcion_id=30,
                    first_id=900,
                    estados=["accepted", "delivered"],
                )
            ],
        )
        snap = _snapshot(
            session,
            start_window=fecha,
            now=fecha,
        )
        row = snap[30]
        self.assertEqual(row.outbox_row_count, 2)
        self.assertEqual(row.outbox_first_id, 900)
        self.assertEqual(row.outbox_estados, ("accepted", "delivered"))

    def test_outbox_states_with_null_or_unknown_are_dropped(self) -> None:
        fecha = _utc(2026, 8, 24, 12, 0, 0)
        session = _FakeSession(
            receipt_rows=[
                _receipt_row(
                    recepcion_id=31,
                    fecha_recepcion=fecha,
                    procesamiento_id=301,
                    procesamiento_estado="processed",
                )
            ],
            outbox_rows=[
                _outbox_row(
                    recepcion_id=31,
                    first_id=901,
                    estados=["accepted", None, ""],
                )
            ],
        )
        snap = _snapshot(
            session,
            start_window=fecha,
            now=fecha,
        )
        row = snap[31]
        self.assertEqual(row.outbox_row_count, 1)
        self.assertEqual(row.outbox_estados, ("accepted",))

    def test_processed_with_zero_outbox_is_visible_observation(self) -> None:
        fecha = _utc(2026, 8, 24, 12, 0, 0)
        session = _FakeSession(
            receipt_rows=[
                _receipt_row(
                    recepcion_id=32,
                    fecha_recepcion=fecha,
                    procesamiento_id=302,
                    procesamiento_estado="processed",
                    intentos=1,
                    llm_resultado="completed",
                    llm_solicitado_en=_utc(2026, 8, 24, 12, 0, 1),
                    llm_finalizado_en=_utc(2026, 8, 24, 12, 0, 3),
                )
            ],
            outbox_rows=[],
        )
        snap = _snapshot(
            session,
            start_window=fecha,
            now=fecha,
        )
        text = format_snapshot(snap[32])
        self.assertIn("procesado + outbox_row_count=0", text)
        self.assertEqual(snap[32].outbox_row_count, 0)

    def test_processed_with_outbox_does_not_print_terminal_marker(self) -> None:
        fecha = _utc(2026, 8, 24, 12, 0, 0)
        session = _FakeSession(
            receipt_rows=[
                _receipt_row(
                    recepcion_id=33,
                    fecha_recepcion=fecha,
                    procesamiento_id=303,
                    procesamiento_estado="processed",
                )
            ],
            outbox_rows=[
                _outbox_row(recepcion_id=33, first_id=902, estados=["accepted"])
            ],
        )
        snap = _snapshot(
            session,
            start_window=fecha,
            now=fecha,
        )
        text = format_snapshot(snap[33])
        self.assertNotIn("procesado + outbox_row_count=0", text)


class StartWindowFilterTest(unittest.TestCase):
    def test_filter_lower_bound_is_applied(self) -> None:
        start = _utc(2026, 8, 24, 12, 0, 0)
        session = _FakeSession(receipt_rows=[])
        _snapshot(
            session,
            start_window=start,
            now=start,
        )
        compiled = str(
            session.executed_statements[0].compile(
                compile_kwargs={"literal_binds": True}
            )
        )
        self.assertIn("fecha_recepcion >=", compiled)
        self.assertIn("LIMIT", compiled)

    def test_limit_is_bounded_by_max_rows(self) -> None:
        start = _utc(2026, 8, 24, 12, 0, 0)
        session = _FakeSession(receipt_rows=[])
        _snapshot(
            session,
            start_window=start,
            now=start,
            max_rows=MAX_RECEPCIONES_PER_POLL,
        )
        compiled = str(
            session.executed_statements[0].compile(
                compile_kwargs={"literal_binds": True}
            )
        )
        self.assertIn(f"LIMIT {MAX_RECEPCIONES_PER_POLL}", compiled)


class ChangeDetectionTest(unittest.TestCase):
    """The diff emits first observations and changed snapshots only."""

    def test_first_observation_is_emitted(self) -> None:
        fecha = _utc(2026, 8, 24, 12, 0, 0)
        snap = ProviderSnapshot(
            recepcion_id=40,
            fingerprint="ab" * 8,
            fecha_recepcion=fecha,
            procesamiento_id=400,
            procesamiento_estado="pending",
            intentos=0,
            categoria_ultimo_fallo=None,
            codigo_ultimo_fallo=None,
            llm_resultado=None,
            llm_solicitado_en=None,
            llm_finalizado_en=None,
            outbox_row_count=0,
            outbox_first_id=None,
            outbox_estados=(),
            observado_en=fecha,
        )
        diff = diff_snapshots({}, {40: snap})
        self.assertEqual([s.recepcion_id for s in diff], [40])

    def test_unchanged_snapshot_is_suppressed(self) -> None:
        fecha = _utc(2026, 8, 24, 12, 0, 0)
        snap = ProviderSnapshot(
            recepcion_id=41,
            fingerprint="cd" * 8,
            fecha_recepcion=fecha,
            procesamiento_id=401,
            procesamiento_estado="pending",
            intentos=0,
            categoria_ultimo_fallo=None,
            codigo_ultimo_fallo=None,
            llm_resultado=None,
            llm_solicitado_en=None,
            llm_finalizado_en=None,
            outbox_row_count=0,
            outbox_first_id=None,
            outbox_estados=(),
            observado_en=fecha,
        )
        later = ProviderSnapshot(
            recepcion_id=snap.recepcion_id,
            fingerprint=snap.fingerprint,
            fecha_recepcion=snap.fecha_recepcion,
            procesamiento_id=snap.procesamiento_id,
            procesamiento_estado=snap.procesamiento_estado,
            intentos=snap.intentos,
            categoria_ultimo_fallo=snap.categoria_ultimo_fallo,
            codigo_ultimo_fallo=snap.codigo_ultimo_fallo,
            llm_resultado=snap.llm_resultado,
            llm_solicitado_en=snap.llm_solicitado_en,
            llm_finalizado_en=snap.llm_finalizado_en,
            outbox_row_count=snap.outbox_row_count,
            outbox_first_id=snap.outbox_first_id,
            outbox_estados=snap.outbox_estados,
            observado_en=_utc(2026, 8, 24, 12, 0, 10),
        )
        diff = diff_snapshots({41: snap}, {41: later})
        self.assertEqual(diff, [])

    def test_state_change_triggers_emission(self) -> None:
        fecha = _utc(2026, 8, 24, 12, 0, 0)
        pending = ProviderSnapshot(
            recepcion_id=42,
            fingerprint="ef" * 8,
            fecha_recepcion=fecha,
            procesamiento_id=402,
            procesamiento_estado="pending",
            intentos=0,
            categoria_ultimo_fallo=None,
            codigo_ultimo_fallo=None,
            llm_resultado=None,
            llm_solicitado_en=None,
            llm_finalizado_en=None,
            outbox_row_count=0,
            outbox_first_id=None,
            outbox_estados=(),
            observado_en=fecha,
        )
        leased = ProviderSnapshot(
            recepcion_id=pending.recepcion_id,
            fingerprint=pending.fingerprint,
            fecha_recepcion=pending.fecha_recepcion,
            procesamiento_id=pending.procesamiento_id,
            procesamiento_estado="leased",
            intentos=1,
            categoria_ultimo_fallo=pending.categoria_ultimo_fallo,
            codigo_ultimo_fallo=pending.codigo_ultimo_fallo,
            llm_resultado=pending.llm_resultado,
            llm_solicitado_en=pending.llm_solicitado_en,
            llm_finalizado_en=pending.llm_finalizado_en,
            outbox_row_count=pending.outbox_row_count,
            outbox_first_id=pending.outbox_first_id,
            outbox_estados=pending.outbox_estados,
            observado_en=pending.observado_en,
        )
        diff = diff_snapshots({42: pending}, {42: leased})
        self.assertEqual(len(diff), 1)
        self.assertEqual(diff[0].procesamiento_estado, "leased")

    def test_outbox_appearance_triggers_emission(self) -> None:
        fecha = _utc(2026, 8, 24, 12, 0, 0)
        no_outbox = ProviderSnapshot(
            recepcion_id=43,
            fingerprint="01" * 8,
            fecha_recepcion=fecha,
            procesamiento_id=403,
            procesamiento_estado="processed",
            intentos=1,
            categoria_ultimo_fallo=None,
            codigo_ultimo_fallo=None,
            llm_resultado="completed",
            llm_solicitado_en=_utc(2026, 8, 24, 12, 0, 1),
            llm_finalizado_en=_utc(2026, 8, 24, 12, 0, 3),
            outbox_row_count=0,
            outbox_first_id=None,
            outbox_estados=(),
            observado_en=fecha,
        )
        with_outbox = ProviderSnapshot(
            recepcion_id=no_outbox.recepcion_id,
            fingerprint=no_outbox.fingerprint,
            fecha_recepcion=no_outbox.fecha_recepcion,
            procesamiento_id=no_outbox.procesamiento_id,
            procesamiento_estado=no_outbox.procesamiento_estado,
            intentos=no_outbox.intentos,
            categoria_ultimo_fallo=no_outbox.categoria_ultimo_fallo,
            codigo_ultimo_fallo=no_outbox.codigo_ultimo_fallo,
            llm_resultado=no_outbox.llm_resultado,
            llm_solicitado_en=no_outbox.llm_solicitado_en,
            llm_finalizado_en=no_outbox.llm_finalizado_en,
            outbox_row_count=1,
            outbox_first_id=800,
            outbox_estados=("accepted",),
            observado_en=no_outbox.observado_en,
        )
        diff = diff_snapshots({43: no_outbox}, {43: with_outbox})
        self.assertEqual(len(diff), 1)
        self.assertEqual(diff[0].outbox_row_count, 1)

    def test_processed_with_zero_outbox_is_emitted_once(self) -> None:
        fecha = _utc(2026, 8, 24, 12, 0, 0)
        terminal = ProviderSnapshot(
            recepcion_id=44,
            fingerprint="02" * 8,
            fecha_recepcion=fecha,
            procesamiento_id=404,
            procesamiento_estado="processed",
            intentos=1,
            categoria_ultimo_fallo=None,
            codigo_ultimo_fallo=None,
            llm_resultado="completed",
            llm_solicitado_en=_utc(2026, 8, 24, 12, 0, 1),
            llm_finalizado_en=_utc(2026, 8, 24, 12, 0, 3),
            outbox_row_count=0,
            outbox_first_id=None,
            outbox_estados=(),
            observado_en=fecha,
        )
        first = diff_snapshots({}, {44: terminal})
        again = diff_snapshots({44: terminal}, {44: terminal})
        self.assertEqual([s.recepcion_id for s in first], [44])
        self.assertEqual(again, [])


class PrivacyTest(unittest.TestCase):
    """The audit never prints sensitive provider / payload data."""

    def test_format_does_not_print_body_phone_or_sid(self) -> None:
        fecha = _utc(2026, 8, 24, 12, 0, 0)
        snap = ProviderSnapshot(
            recepcion_id=50,
            fingerprint="03" * 8,
            fecha_recepcion=fecha,
            procesamiento_id=500,
            procesamiento_estado="processed",
            intentos=1,
            categoria_ultimo_fallo=None,
            codigo_ultimo_fallo=None,
            llm_resultado="completed",
            llm_solicitado_en=_utc(2026, 8, 24, 12, 0, 1),
            llm_finalizado_en=_utc(2026, 8, 24, 12, 0, 3),
            outbox_row_count=1,
            outbox_first_id=850,
            outbox_estados=("accepted",),
            observado_en=fecha,
        )
        text = format_snapshot(snap)
        forbidden = {
            "cuerpo",
            "body",
            "telefono",
            "teléfono",
            "phone",
            "destinatario",
            "identificador_proveedor",
            "twilio_sid",
            "credentials",
            "connection",
            "traceback",
            "prompt",
            "response",
            "exception",
            "SM-SECRET",
            "+54911",
            "token_lease",
        }
        for needle in forbidden:
            self.assertNotIn(
                needle.casefold(),
                text.casefold(),
                f"audit output leaked {needle!r}",
            )

    def test_to_dict_does_not_include_sensitive_keys(self) -> None:
        fecha = _dt.datetime(2026, 8, 24, 12, 0, 0, tzinfo=_UTC)
        snap = ProviderSnapshot(
            recepcion_id=51,
            fingerprint="04" * 8,
            fecha_recepcion=fecha,
            procesamiento_id=501,
            procesamiento_estado="processed",
            intentos=1,
            categoria_ultimo_fallo=None,
            codigo_ultimo_fallo=None,
            llm_resultado="completed",
            llm_solicitado_en=fecha,
            llm_finalizado_en=fecha,
            outbox_row_count=0,
            outbox_first_id=None,
            outbox_estados=(),
            observado_en=fecha,
        )
        forbidden_keys = {
            "proveedor",
            "identificador_recepcion",
            "cuerpo",
            "destinatario_e164",
            "mensaje",
            "token_lease",
            "identificador_proveedor",
            "prompt",
            "response",
        }
        self.assertTrue(forbidden_keys.isdisjoint(snap.to_dict().keys()))


class ReadOnlyTest(unittest.TestCase):
    """The audit never writes, commits, flushes, updates or deletes."""

    def test_session_is_consumed_read_only(self) -> None:
        fecha = _utc(2026, 8, 24, 12, 0, 0)
        session = _FakeSession(
            receipt_rows=[
                _receipt_row(
                    recepcion_id=60,
                    fecha_recepcion=fecha,
                    procesamiento_id=600,
                    procesamiento_estado="pending",
                )
            ]
        )
        _snapshot(
            session,
            start_window=fecha,
            now=fecha,
        )
        self.assertFalse(session.committed)
        self.assertFalse(session.rolled_back)
        self.assertFalse(session.flushed)
        self.assertEqual(session.add_calls, [])
        self.assertEqual(session.delete_calls, [])
        self.assertEqual(len(session.executed_statements), 2)
        for stmt in session.executed_statements:
            self.assertIsInstance(stmt, type(select(1)))


class CLIContractTest(unittest.TestCase):
    """CLI argument validation and exit codes."""

    def test_parser_defaults_match_documented_contract(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args([])
        self.assertEqual(args.interval_seconds, DEFAULT_INTERVAL_SECONDS)
        self.assertEqual(args.duration_seconds, DEFAULT_DURATION_SECONDS)

    def test_negative_interval_returns_invalid_arguments(self) -> None:
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            code = main(["--interval-seconds", "0"])
        self.assertEqual(code, 2)
        self.assertIn("interval-seconds", buffer.getvalue().casefold())

    def test_zero_duration_returns_invalid_arguments(self) -> None:
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            code = main(["--duration-seconds", "0"])
        self.assertEqual(code, 2)
        self.assertIn("duration-seconds", buffer.getvalue().casefold())

    def test_argument_error_does_not_open_session(self) -> None:
        with mock.patch(
            "backend.scripts.audit_provider_flow_live.create_engine"
        ) as create_engine_mock:
            buffer = io.StringIO()
            with redirect_stderr(buffer):
                code = main(["--interval-seconds", "-1"])
        self.assertEqual(code, 2)
        create_engine_mock.assert_not_called()


class LoopTerminationTest(unittest.TestCase):
    """The loop respects duration, Ctrl-C and read errors."""

    def _factory_sequence(self, sessions: list[_FakeSession]) -> Any:
        """Build a session factory callable that yields the next session."""

        index = {"value": 0}

        def _factory() -> _FakeSession:
            current = sessions[min(index["value"], len(sessions) - 1)]
            index["value"] += 1
            return current

        return _factory

    def test_loop_exits_zero_after_duration(self) -> None:
        session = _FakeSession(receipt_rows=[])
        factory = self._factory_sequence([session])

        sleeps: list[float] = []
        start_clock = _utc(2026, 8, 24, 12, 0, 0)
        clock = {"value": start_clock}

        def _sleep_until(_target, *, is_stop_requested):
            sleeps.append(1.0)
            return False

        def _fake_now_utc() -> _dt.datetime:
            current = clock["value"]
            clock["value"] = current + _dt.timedelta(seconds=0.5)
            return current

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch(
                "backend.scripts.audit_provider_flow_live.select_session_factory",
                return_value=(mock.MagicMock(), factory),
            ),
            mock.patch(
                "backend.scripts.audit_provider_flow_live._sleep_until",
                side_effect=_sleep_until,
            ),
            mock.patch(
                "backend.scripts.audit_provider_flow_live._now_utc",
                side_effect=_fake_now_utc,
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = main(
                [
                    "--interval-seconds",
                    "0.5",
                    "--duration-seconds",
                    "1",
                    "--database-url",
                    "postgresql+psycopg://noop",
                ]
            )
        self.assertEqual(code, 0)
        self.assertIn("audit: terminated", stdout.getvalue())
        self.assertGreaterEqual(len(sleeps), 1)

    def test_loop_returns_one_on_read_error_and_keeps_polling(self) -> None:
        class _RaisingSession(_FakeSession):
            def execute(self, stmt: Any) -> Any:
                raise RuntimeError("simulated DB outage")

        raising = _RaisingSession()

        sleeps: list[float] = []
        clock = {"value": _utc(2026, 8, 24, 12, 0, 0)}

        def _sleep_until(_target, *, is_stop_requested):
            sleeps.append(1.0)
            return False

        def _fake_now_utc() -> _dt.datetime:
            current = clock["value"]
            clock["value"] = current + _dt.timedelta(seconds=0.5)
            return current

        factory_calls = {"count": 0}

        def _factory() -> Any:
            factory_calls["count"] += 1
            if factory_calls["count"] == 1:
                return raising
            return _FakeSession(receipt_rows=[])

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch(
                "backend.scripts.audit_provider_flow_live.select_session_factory",
                return_value=(mock.MagicMock(), _factory),
            ),
            mock.patch(
                "backend.scripts.audit_provider_flow_live._sleep_until",
                side_effect=_sleep_until,
            ),
            mock.patch(
                "backend.scripts.audit_provider_flow_live._now_utc",
                side_effect=_fake_now_utc,
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = main(
                [
                    "--interval-seconds",
                    "0.5",
                    "--duration-seconds",
                    "1",
                    "--database-url",
                    "postgresql+psycopg://noop",
                ]
            )

        self.assertEqual(code, 1)
        self.assertIn("read_error category=", stderr.getvalue())
        # The class label is allowed because it is a closed category.
        self.assertIn("builtins.RuntimeError", stderr.getvalue())
        # Only exception text and connection details must be omitted.
        self.assertNotIn("simulated DB outage", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())
        self.assertNotIn("postgres", stderr.getvalue())
        self.assertIn("audit: terminated", stdout.getvalue())

    def test_keyboard_interrupt_yields_clean_termination(self) -> None:
        session = _FakeSession(receipt_rows=[])

        def _sleep_until(_target, *, is_stop_requested):
            return True

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch(
                "backend.scripts.audit_provider_flow_live.select_session_factory",
                return_value=(mock.MagicMock(), lambda: session),
            ),
            mock.patch(
                "backend.scripts.audit_provider_flow_live._sleep_until",
                side_effect=_sleep_until,
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = main(
                [
                    "--interval-seconds",
                    "0.5",
                    "--duration-seconds",
                    "600",
                    "--database-url",
                    "postgresql+psycopg://noop",
                ]
            )

        self.assertEqual(code, 0)
        self.assertIn("audit: terminated", stdout.getvalue())


class FingerprintTest(unittest.TestCase):
    def test_fingerprint_is_short_and_opaque(self) -> None:
        from backend.scripts.audit_provider_flow_live import (
            _short_fingerprint,
        )

        value = _short_fingerprint("twilio", "SM-SECRET-12")
        self.assertEqual(len(value), FINGERPRINT_HEX_CHARS)
        self.assertNotIn("SM-SECRET", value)
        self.assertEqual(
            _short_fingerprint("twilio", "SM-SECRET-12"),
            _short_fingerprint("twilio", "SM-SECRET-12"),
        )
        self.assertNotEqual(
            _short_fingerprint("twilio", "SM-SECRET-12"),
            _short_fingerprint("twilio", "SM-SECRET-13"),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
