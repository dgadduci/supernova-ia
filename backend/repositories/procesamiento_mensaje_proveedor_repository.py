"""SQLAlchemy queries for ``procesamientos_mensajes_proveedor``.

The repository is the sole boundary that knows the
``(recepcion_mensaje_proveedor_id)`` uniqueness rule, the
state machine and the lease-protected claim/finalization contract used
by the Phase-7.4 deferred inbound processor.

The repository is read-mostly and never invokes transaction-control
methods: callers own the surrounding transaction and the final
``commit`` / ``rollback``. The ``stage`` mutation performs an
``INSERT`` inside the caller's transaction; the
``claim_due`` / ``finalize_processed`` / ``finalize_retryable`` /
``finalize_terminal`` mutations are expressed as conditional
``UPDATE`` statements that pin the lease token or the previous state
so a late result cannot overwrite a later attempt.

The repository intentionally exposes only the documented seams used by
the deferred processor:

* ``stage`` inserts one pending work item inside the caller's
  transaction; the unique key guarantees that a second ``INSERT`` for
  the same receipt raises a unique-constraint violation rather than
  duplicating the work.
* ``claim_due`` selects one due row with ``FOR UPDATE SKIP LOCKED``
  and emits a fresh lease token; the lease is durable after the
  surrounding transaction commits. Conversational order is preserved
  by the ``_earlier_unresolved_blocker_exists`` predicate, which
  excludes any candidate whose ``(canal_id, cliente_id)`` already owns
  a receipt created earlier whose work is still in any non-terminal
  state (``pending``, ``leased`` or ``retryable``). The conversational
  block is unconditional based on state: it does NOT depend on
  ``lease_expira_en`` or ``proximo_intento_en``. Only ``processed``
  and ``failed_terminal`` rows never block a later item in the same
  conversation.
* ``finalize_processed`` clears the transient body and locks the row
  in the terminal ``processed`` state.
* ``finalize_retryable`` releases the lease and stages the row for a
  future explicit retry without clearing the body.
* ``finalize_terminal`` clears the transient body and locks the row
  in the ``failed_terminal`` state.
"""
from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import and_, exists, not_, or_, select, update
from sqlalchemy.orm import Session as SqlSession

from backend.models.procesamiento_mensaje_proveedor import (
    ProcesamientoMensajeProveedor,
    ProcesamientoMensajeProveedorEstado,
)
from backend.models.recepcion_mensaje_proveedor import RecepcionMensajeProveedor

_PROCESAMIENTO_TABLE = ProcesamientoMensajeProveedor.__table__
_RECEPCION_TABLE = RecepcionMensajeProveedor.__table__


class ProcesamientoMensajeProveedorRepository:
    def __init__(self, session: SqlSession) -> None:
        self._session = session

    def stage(
        self,
        *,
        recepcion_mensaje_proveedor_id: int,
        mensaje: str,
    ) -> ProcesamientoMensajeProveedor:
        """Stage one pending work item inside the caller's transaction.

        The repository never flushes or commits; the surrounding
        webhook acceptance transaction owns both. The
        ``recepcion_mensaje_proveedor_id`` unique constraint is
        checked at commit time so a duplicate stage raises only when
        the surrounding transaction attempts to commit.
        """
        row = ProcesamientoMensajeProveedor(
            recepcion_mensaje_proveedor_id=recepcion_mensaje_proveedor_id,
            estado=ProcesamientoMensajeProveedorEstado.PENDING.value,
            intentos=0,
            proximo_intento_en=None,
            token_lease=None,
            lease_expira_en=None,
            categoria_ultimo_fallo=None,
            codigo_ultimo_fallo=None,
            mensaje=mensaje,
            fecha_finalizacion=None,
        )
        self._session.add(row)
        return row

    def find_by_id(
        self, procesamiento_id: int
    ) -> ProcesamientoMensajeProveedor | None:
        return self._session.get(
            ProcesamientoMensajeProveedor, procesamiento_id
        )

    def find_by_recepcion(
        self, recepcion_mensaje_proveedor_id: int
    ) -> ProcesamientoMensajeProveedor | None:
        stmt = select(ProcesamientoMensajeProveedor).where(
            ProcesamientoMensajeProveedor.recepcion_mensaje_proveedor_id
            == recepcion_mensaje_proveedor_id
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def claim_due(
        self,
        *,
        now: datetime,
        lease_seconds: int,
    ) -> ProcesamientoMensajeProveedor | None:
        """Claim exactly one due row and emit a lease token.

        Three eligibility paths are combined so the processor
        recovers rows whose lease expired and so a single ``UPDATE``
        cannot accidentally lease multiple rows:

        * a ``pending`` row (``proximo_intento_en`` is ``NULL``);
        * a ``retryable`` row whose ``proximo_intento_en`` is due;
        * a ``leased`` row whose ``lease_expira_en`` is in the past
          (recovery path; the lease is treated as abandoned).

        Conversational order is preserved by excluding any candidate
        whose ``(canal_id, cliente_id)`` already owns an earlier
        receipt whose work is ``pending``, ``leased`` or
        ``retryable``. The conversational block is unconditional based
        on state and is independent of ``lease_expira_en`` and
        ``proximo_intento_en``: any non-terminal earlier work in the
        same conversation blocks a later candidate. Rows that belong
        to a different conversation remain eligible. "Earlier" follows
        the receipt creation order, using
        ``recepciones_mensajes_proveedor.fecha_recepcion`` as the
        primary key and ``recepciones_mensajes_proveedor.id`` as a
        stable tiebreaker; it does not depend on the autoincrement
        identifier of the work item itself.

        The candidate ``id`` is selected with
        ``ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED`` so two
        concurrent processors cannot claim the same row. Only that
        single id is then placed in ``leased`` state with a fresh
        random lease token; every other due row remains eligible.
        The caller is responsible for committing the surrounding
        transaction so the lease is durable before the processing
        pass begins.
        """
        lease_token = secrets.token_urlsafe(24)
        eligible_subquery = (
            select(ProcesamientoMensajeProveedor.id)
            .where(_claim_eligible_predicate(now))
            .where(
                not_(
                    _earlier_unresolved_blocker_exists(now=now)
                )
            )
            .order_by(ProcesamientoMensajeProveedor.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        stmt = (
            update(ProcesamientoMensajeProveedor)
            .where(
                ProcesamientoMensajeProveedor.id
                == eligible_subquery.scalar_subquery()
            )
            .values(
                estado=ProcesamientoMensajeProveedorEstado.LEASED.value,
                token_lease=lease_token,
                lease_expira_en=_add_seconds(now, lease_seconds),
                intentos=ProcesamientoMensajeProveedor.intentos + 1,
            )
            .returning(ProcesamientoMensajeProveedor)
        )
        return self._session.execute(stmt).scalars().first()

    def finalize_processed(
        self,
        *,
        procesamiento_id: int,
        lease_token: str,
        fecha_finalizacion: datetime,
        llm_solicitado_en: datetime | None = None,
        llm_finalizado_en: datetime | None = None,
        llm_resultado: str | None = None,
    ) -> bool:
        """Clear the transient body and lock the row in ``processed``.

        Returns ``True`` only when the matching lease token is still
        present; a late result from a prior attempt cannot overwrite
        the terminal state. Optional ``llm_*`` kwargs let the
        coordinator persist the bounded LLM timing metadata captured
        during the same lease/finalization transaction.
        """
        values: dict[str, Any] = {
            "estado": ProcesamientoMensajeProveedorEstado.PROCESSED.value,
            "mensaje": None,
            "token_lease": None,
            "lease_expira_en": None,
            "proximo_intento_en": None,
            "categoria_ultimo_fallo": None,
            "codigo_ultimo_fallo": None,
            "fecha_finalizacion": fecha_finalizacion,
        }
        if llm_solicitado_en is not None:
            values["llm_solicitado_en"] = llm_solicitado_en
        if llm_finalizado_en is not None:
            values["llm_finalizado_en"] = llm_finalizado_en
        if llm_resultado is not None:
            values["llm_resultado"] = llm_resultado
        stmt = (
            update(ProcesamientoMensajeProveedor)
            .where(
                ProcesamientoMensajeProveedor.id == procesamiento_id
            )
            .where(
                ProcesamientoMensajeProveedor.token_lease == lease_token
            )
            .where(
                ProcesamientoMensajeProveedor.estado
                == ProcesamientoMensajeProveedorEstado.LEASED.value
            )
            .values(**values)
            .returning(ProcesamientoMensajeProveedor.id)
        )
        result = self._session.execute(stmt).scalar_one_or_none()
        return result is not None

    def finalize_retryable(
        self,
        *,
        procesamiento_id: int,
        lease_token: str,
        categoria: str,
        codigo: str | None,
        proximo_intento_en: datetime,
        llm_solicitado_en: datetime | None = None,
        llm_finalizado_en: datetime | None = None,
        llm_resultado: str | None = None,
    ) -> bool:
        """Release the lease and stage the row for a future explicit
        retry. Returns ``True`` only when the matching lease token is
        still present. The transient body is preserved so the next
        pass can replay it. Optional ``llm_*`` kwargs let the
        coordinator persist the bounded LLM timing metadata captured
        during the same lease/finalization transaction so the retry
        attempt retains the diagnosis of the previous one.
        """
        values: dict[str, Any] = {
            "estado": ProcesamientoMensajeProveedorEstado.RETRYABLE.value,
            "categoria_ultimo_fallo": categoria,
            "codigo_ultimo_fallo": codigo,
            "proximo_intento_en": proximo_intento_en,
            "token_lease": None,
            "lease_expira_en": None,
        }
        if llm_solicitado_en is not None:
            values["llm_solicitado_en"] = llm_solicitado_en
        if llm_finalizado_en is not None:
            values["llm_finalizado_en"] = llm_finalizado_en
        if llm_resultado is not None:
            values["llm_resultado"] = llm_resultado
        stmt = (
            update(ProcesamientoMensajeProveedor)
            .where(
                ProcesamientoMensajeProveedor.id == procesamiento_id
            )
            .where(
                ProcesamientoMensajeProveedor.token_lease == lease_token
            )
            .where(
                ProcesamientoMensajeProveedor.estado
                == ProcesamientoMensajeProveedorEstado.LEASED.value
            )
            .values(**values)
            .returning(ProcesamientoMensajeProveedor.id)
        )
        result = self._session.execute(stmt).scalar_one_or_none()
        return result is not None

    def finalize_terminal(
        self,
        *,
        procesamiento_id: int,
        lease_token: str,
        categoria: str,
        codigo: str | None,
        fecha_finalizacion: datetime,
        llm_solicitado_en: datetime | None = None,
        llm_finalizado_en: datetime | None = None,
        llm_resultado: str | None = None,
    ) -> bool:
        """Clear the transient body and lock the row in
        ``failed_terminal``. Returns ``True`` only when the matching
        lease token is still present. Optional ``llm_*`` kwargs let
        the coordinator persist the bounded LLM timing metadata
        captured during the same lease/finalization transaction so
        the terminal row retains the diagnosis of the final
        attempt.
        """
        values: dict[str, Any] = {
            "estado": ProcesamientoMensajeProveedorEstado.FAILED_TERMINAL.value,
            "mensaje": None,
            "categoria_ultimo_fallo": categoria,
            "codigo_ultimo_fallo": codigo,
            "token_lease": None,
            "lease_expira_en": None,
            "proximo_intento_en": None,
            "fecha_finalizacion": fecha_finalizacion,
        }
        if llm_solicitado_en is not None:
            values["llm_solicitado_en"] = llm_solicitado_en
        if llm_finalizado_en is not None:
            values["llm_finalizado_en"] = llm_finalizado_en
        if llm_resultado is not None:
            values["llm_resultado"] = llm_resultado
        stmt = (
            update(ProcesamientoMensajeProveedor)
            .where(
                ProcesamientoMensajeProveedor.id == procesamiento_id
            )
            .where(
                ProcesamientoMensajeProveedor.token_lease == lease_token
            )
            .where(
                ProcesamientoMensajeProveedor.estado
                == ProcesamientoMensajeProveedorEstado.LEASED.value
            )
            .values(**values)
            .returning(ProcesamientoMensajeProveedor.id)
        )
        result = self._session.execute(stmt).scalar_one_or_none()
        return result is not None


def _add_seconds(base: datetime, seconds: int) -> datetime:
    from datetime import timedelta

    return base + timedelta(seconds=int(seconds))


def _claim_eligible_predicate(now: datetime) -> Any:
    """Return the SQL predicate that gates a single-row claim.

    The predicate covers the three documented eligibility paths:

    * a ``pending`` row with no lease and no ``proximo_intento_en``;
    * a ``retryable`` row with no lease whose ``proximo_intento_en``
      is due (``<= now``);
    * a ``leased`` row whose ``lease_expira_en`` is in the past
      (lease-recovery path).

    ``processed`` and ``failed_terminal`` rows are intentionally
    excluded so a row whose outcome is terminal cannot be re-claimed.
    """
    pending_or_due_retryable = and_(
        ProcesamientoMensajeProveedor.estado.in_(
            [
                ProcesamientoMensajeProveedorEstado.PENDING.value,
                ProcesamientoMensajeProveedorEstado.RETRYABLE.value,
            ]
        ),
        ProcesamientoMensajeProveedor.token_lease.is_(None),
        or_(
            ProcesamientoMensajeProveedor.proximo_intento_en.is_(None),
            ProcesamientoMensajeProveedor.proximo_intento_en <= now,
        ),
    )
    expired_lease = and_(
        ProcesamientoMensajeProveedor.estado
        == ProcesamientoMensajeProveedorEstado.LEASED.value,
        ProcesamientoMensajeProveedor.lease_expira_en.is_not(None),
        ProcesamientoMensajeProveedor.lease_expira_en <= now,
    )
    return or_(pending_or_due_retryable, expired_lease)


def _earlier_unresolved_blocker_exists(*, now: datetime) -> Any:
    """Return an ``EXISTS`` subquery enforcing the conversational
    ordering rule for a candidate inbound work row.

    A candidate is blocked when there exists another work row whose
    receipt was created earlier for the same ``(canal_id,
    cliente_id)`` pair and whose state is still unresolved:

    * ``pending`` (no lease, no due time);
    * ``leased`` regardless of ``lease_expira_en``; or
    * ``retryable`` regardless of ``proximo_intento_en``.

    The conversational block is unconditional based on state and is
    INDEPENDENT of ``lease_expira_en`` and ``proximo_intento_en``:
    any non-terminal earlier work in the same conversation blocks a
    later candidate. A ``leased`` row whose lease has already expired
    remains a blocker for a later candidate even though it stays
    eligible for its own lease-recovery claim; a ``retryable`` row
    whose ``proximo_intento_en`` is in the future is also a blocker.
    ``processed`` and ``failed_terminal`` rows never block.

    The candidate's own eligibility remains time-bounded (see
    ``_claim_eligible_predicate``): a ``retryable`` candidate is
    still only claimable when its ``proximo_intento_en`` is due (or
    unset), and a ``leased`` candidate is still only claimable
    through the lease-recovery path when its ``lease_expira_en`` is
    in the past. The conversational block targets STRICTLY later
    rows, so a candidate that is its own earliest unresolved row
    remains eligible.

    "Earlier" follows the receipt creation order: primary sort by
    ``recepciones_mensajes_proveedor.fecha_recepcion`` with
    ``recepciones_mensajes_proveedor.id`` as a stable tiebreaker so
    the conversational order is the order in which Twilio committed
    the receipts, not the autoincrement of the work item. The
    comparison joins the candidate's own receipt with the blocker
    receipt through the shared ``(canal_id, cliente_id)`` pair and
    the candidate receipt is correlated with the outer work row.
    """
    candidate_receipt = _RECEPCION_TABLE.alias("candidate_recepcion")
    blocker_receipt = _RECEPCION_TABLE.alias("blocker_recepcion")
    blocker_work = _PROCESAMIENTO_TABLE.alias("blocker_work")
    subquery = (
        select(1)
        .select_from(blocker_work)
        .join(
            candidate_receipt,
            candidate_receipt.c.id
            == _PROCESAMIENTO_TABLE.c.recepcion_mensaje_proveedor_id,
        )
        .join(
            blocker_receipt,
            blocker_receipt.c.id
            == blocker_work.c.recepcion_mensaje_proveedor_id,
        )
        .where(
            or_(
                candidate_receipt.c.fecha_recepcion
                > blocker_receipt.c.fecha_recepcion,
                and_(
                    candidate_receipt.c.fecha_recepcion
                    == blocker_receipt.c.fecha_recepcion,
                    candidate_receipt.c.id > blocker_receipt.c.id,
                ),
            )
        )
        .where(
            and_(
                blocker_receipt.c.canal_id == candidate_receipt.c.canal_id,
                blocker_receipt.c.cliente_id == candidate_receipt.c.cliente_id,
            )
        )
        .where(
            or_(
                blocker_work.c.estado
                == ProcesamientoMensajeProveedorEstado.PENDING.value,
                blocker_work.c.estado
                == ProcesamientoMensajeProveedorEstado.LEASED.value,
                blocker_work.c.estado
                == ProcesamientoMensajeProveedorEstado.RETRYABLE.value,
            )
        )
    )
    return exists(subquery)


__all__ = ["ProcesamientoMensajeProveedorRepository"]