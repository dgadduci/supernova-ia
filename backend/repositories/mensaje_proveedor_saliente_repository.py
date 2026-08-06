"""SQLAlchemy queries for ``mensajes_proveedor_salientes``.

The repository is the only boundary that knows the
``(recepcion_mensaje_proveedor_id, sequence)`` uniqueness rule, the
state machine and the lease-protected claim/finalization contract used
by the Phase-5.6 dispatcher and callback service.

The repository is read-mostly and never invokes transaction-control
methods: callers own the surrounding transaction and the final
``commit`` / ``rollback``. The claim/finalization mutations are
expressed as conditional ``UPDATE`` statements that pin the lease
token or the previous state so a late network result cannot overwrite
a later attempt.

The ``stage`` method performs an ``INSERT`` inside the caller's
transaction. The unique constraint on
``(recepcion_mensaje_proveedor_id, sequence)`` guarantees that no
duplicate staging is observable after the surrounding commit.
"""
from __future__ import annotations

import secrets
from collections.abc import Sequence as SequenceABC
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session as SqlSession

from backend.models.mensaje_proveedor_saliente import (
    MensajeProveedorSaliente,
    OutboundFailureCategory,
    OutboundProviderMessageState,
)


class MensajeProveedorSalienteRepository:
    def __init__(self, session: SqlSession) -> None:
        self._session = session

    def stage(
        self,
        *,
        proveedor: str,
        recepcion_mensaje_proveedor_id: int,
        destinatario_e164: str,
        cuerpo: str,
        sequence: int,
    ) -> MensajeProveedorSaliente:
        """Stage one outbound row inside the caller's transaction.

        The repository never flushes or commits; the surrounding
        coordinator transaction owns both. The
        ``(recepcion_mensaje_proveedor_id, sequence)`` unique
        constraint is checked at commit time so the partial staged
        row is never observable to a concurrent reader before the
        inbound transaction commits.
        """
        row = MensajeProveedorSaliente(
            proveedor=proveedor,
            recepcion_mensaje_proveedor_id=recepcion_mensaje_proveedor_id,
            destinatario_e164=destinatario_e164,
            cuerpo=cuerpo,
            sequence=sequence,
            estado=OutboundProviderMessageState.PENDING.value,
            identificador_proveedor=None,
            intentos=0,
            proximo_intento_en=None,
            token_lease=None,
            lease_expira_en=None,
            categoria_ultimo_fallo=None,
            codigo_ultimo_fallo=None,
            estado_proveedor=None,
            estado_proveedor_en=None,
        )
        self._session.add(row)
        return row

    def find_by_id(
        self, mensaje_proveedor_saliente_id: int
    ) -> MensajeProveedorSaliente | None:
        return self._session.get(
            MensajeProveedorSaliente, mensaje_proveedor_saliente_id
        )

    def find_by_provider_sid(
        self, proveedor: str, identificador_proveedor: str
    ) -> MensajeProveedorSaliente | None:
        stmt = select(MensajeProveedorSaliente).where(
            MensajeProveedorSaliente.proveedor == proveedor,
            MensajeProveedorSaliente.identificador_proveedor
            == identificador_proveedor,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def list_by_recepcion(
        self, recepcion_mensaje_proveedor_id: int
    ) -> SequenceABC[MensajeProveedorSaliente]:
        stmt = (
            select(MensajeProveedorSaliente)
            .where(
                MensajeProveedorSaliente.recepcion_mensaje_proveedor_id
                == recepcion_mensaje_proveedor_id
            )
            .order_by(MensajeProveedorSaliente.sequence.asc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def count_by_recepcion(
        self, recepcion_mensaje_proveedor_id: int
    ) -> int:
        stmt = select(MensajeProveedorSaliente).where(
            MensajeProveedorSaliente.recepcion_mensaje_proveedor_id
            == recepcion_mensaje_proveedor_id
        )
        return len(list(self._session.execute(stmt).scalars().all()))

    def claim_due(
        self,
        *,
        now: datetime,
        lease_seconds: int,
    ) -> MensajeProveedorSaliente | None:
        """Claim exactly one due row and emit a lease token.

        Three eligibility paths are combined so the dispatcher
        recovers rows whose lease expired and so a single ``UPDATE``
        cannot accidentally lease multiple rows:

        * a ``pending`` row (``proximo_intento_en`` is ``NULL``);
        * a ``retryable`` row whose ``proximo_intento_en`` is due;
        * a ``leased`` row whose ``lease_expira_en`` is in the past
          (recovery path; the lease is treated as abandoned).

        The candidate ``id`` is selected with
        ``ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED`` so two
        concurrent dispatchers cannot claim the same row. Only that
        single id is then placed in ``leased`` state with a fresh
        random lease token; every other due row remains eligible.
        The caller is responsible for committing the surrounding
        transaction so the lease is durable before the network call.
        """
        lease_token = secrets.token_urlsafe(24)
        eligible_subquery = (
            select(MensajeProveedorSaliente.id)
            .where(_claim_eligible_predicate(now))
            .order_by(MensajeProveedorSaliente.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        stmt = (
            update(MensajeProveedorSaliente)
            .where(MensajeProveedorSaliente.id == eligible_subquery.scalar_subquery())
            .values(
                estado=OutboundProviderMessageState.LEASED.value,
                token_lease=lease_token,
                lease_expira_en=_add_seconds(now, lease_seconds),
                intentos=MensajeProveedorSaliente.intentos + 1,
            )
            .returning(MensajeProveedorSaliente)
        )
        return self._session.execute(stmt).scalars().first()

    def finalize_accepted(
        self,
        *,
        mensaje_id: int,
        lease_token: str,
        identificador_proveedor: str,
    ) -> bool:
        """Record a Twilio acceptance and lock the row in ``accepted``.

        Returns ``True`` only when the matching lease token is still
        present; a late result from a prior attempt cannot overwrite a
        later attempt's accepted state.
        """
        stmt = (
            update(MensajeProveedorSaliente)
            .where(MensajeProveedorSaliente.id == mensaje_id)
            .where(MensajeProveedorSaliente.token_lease == lease_token)
            .where(
                MensajeProveedorSaliente.estado
                == OutboundProviderMessageState.LEASED.value
            )
            .values(
                estado=OutboundProviderMessageState.ACCEPTED.value,
                identificador_proveedor=identificador_proveedor,
                token_lease=None,
                lease_expira_en=None,
                proximo_intento_en=None,
                categoria_ultimo_fallo=None,
                codigo_ultimo_fallo=None,
            )
            .returning(MensajeProveedorSaliente.id)
        )
        result = self._session.execute(stmt).scalar_one_or_none()
        return result is not None

    def finalize_retryable(
        self,
        *,
        mensaje_id: int,
        lease_token: str,
        categoria: OutboundFailureCategory,
        codigo: str | None,
        proximo_intento_en: datetime,
    ) -> bool:
        """Release the lease and stage the row for a future explicit
        retry. Returns ``True`` only when the matching lease token is
        still present."""
        stmt = (
            update(MensajeProveedorSaliente)
            .where(MensajeProveedorSaliente.id == mensaje_id)
            .where(MensajeProveedorSaliente.token_lease == lease_token)
            .where(
                MensajeProveedorSaliente.estado
                == OutboundProviderMessageState.LEASED.value
            )
            .values(
                estado=OutboundProviderMessageState.RETRYABLE.value,
                categoria_ultimo_fallo=categoria.value,
                codigo_ultimo_fallo=codigo,
                proximo_intento_en=proximo_intento_en,
                token_lease=None,
                lease_expira_en=None,
            )
            .returning(MensajeProveedorSaliente.id)
        )
        result = self._session.execute(stmt).scalar_one_or_none()
        return result is not None

    def finalize_terminal(
        self,
        *,
        mensaje_id: int,
        lease_token: str,
        categoria: OutboundFailureCategory,
        codigo: str | None,
    ) -> bool:
        """Release the lease and lock the row in ``failed_terminal``.

        Returns ``True`` only when the matching lease token is still
        present.
        """
        stmt = (
            update(MensajeProveedorSaliente)
            .where(MensajeProveedorSaliente.id == mensaje_id)
            .where(MensajeProveedorSaliente.token_lease == lease_token)
            .where(
                MensajeProveedorSaliente.estado
                == OutboundProviderMessageState.LEASED.value
            )
            .values(
                estado=OutboundProviderMessageState.FAILED_TERMINAL.value,
                categoria_ultimo_fallo=categoria.value,
                codigo_ultimo_fallo=codigo,
                token_lease=None,
                lease_expira_en=None,
                proximo_intento_en=None,
            )
            .returning(MensajeProveedorSaliente.id)
        )
        result = self._session.execute(stmt).scalar_one_or_none()
        return result is not None

    def record_provider_status(
        self,
        *,
        mensaje_id: int,
        estado_proveedor: str,
        estado_proveedor_en: datetime,
        estado_final: str,
    ) -> bool:
        """Apply a monotonic provider-status transition to the row.

        Returns ``True`` only when the row currently allows the
        transition. The callback service enforces the monotonic
        rules; this method is the single source of mutation for the
        state machine.
        """
        stmt = (
            update(MensajeProveedorSaliente)
            .where(MensajeProveedorSaliente.id == mensaje_id)
            .where(_monotonic_predicate(estado_final))
            .values(
                estado=estado_final,
                estado_proveedor=estado_proveedor,
                estado_proveedor_en=estado_proveedor_en,
            )
            .returning(MensajeProveedorSaliente.id)
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

    ``accepted``, ``delivered`` and ``failed_terminal`` rows are
    intentionally excluded so a row whose callback is in flight or
    whose outcome is terminal cannot be re-claimed.
    """
    pending_or_due_retryable = and_(
        MensajeProveedorSaliente.estado.in_(
            [
                OutboundProviderMessageState.PENDING.value,
                OutboundProviderMessageState.RETRYABLE.value,
            ]
        ),
        MensajeProveedorSaliente.token_lease.is_(None),
        or_(
            MensajeProveedorSaliente.proximo_intento_en.is_(None),
            MensajeProveedorSaliente.proximo_intento_en <= now,
        ),
    )
    expired_lease = and_(
        MensajeProveedorSaliente.estado
        == OutboundProviderMessageState.LEASED.value,
        MensajeProveedorSaliente.lease_expira_en.is_not(None),
        MensajeProveedorSaliente.lease_expira_en <= now,
    )
    return or_(pending_or_due_retryable, expired_lease)


def _monotonic_predicate(target_state: str) -> Any:
    """Return the SQL predicate that gates a target monotonic
    transition.

    The ``accepted -> delivered`` and ``accepted -> failed_terminal``
    branches are the only permitted forward edges. Any other source
    state, or a regressive callback for an already-delivered row,
    leaves the row untouched so the callback becomes an idempotent
    no-op.
    """
    if target_state == OutboundProviderMessageState.DELIVERED.value:
        return and_(
            MensajeProveedorSaliente.estado
            == OutboundProviderMessageState.ACCEPTED.value
        )
    if target_state == OutboundProviderMessageState.FAILED_TERMINAL.value:
        return and_(
            MensajeProveedorSaliente.estado.in_(
                [
                    OutboundProviderMessageState.ACCEPTED.value,
                    OutboundProviderMessageState.LEASED.value,
                ]
            )
        )
    raise ValueError(
        f"unsupported monotonic target state: {target_state}"
    )


__all__ = ["MensajeProveedorSalienteRepository"]