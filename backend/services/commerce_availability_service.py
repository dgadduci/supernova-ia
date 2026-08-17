"""Central typed commerce-availability policy.

This service is the single authority that decides whether a
:class:`backend.models.Comercio` can accept or confirm customer
work. The policy:

* reads ONLY ``EstadoComercio.modo_operacion`` and the per-commerce
  trial columns; it never compares a status code or display label
  (``ACTIVO`` / ``INACTIVO`` / ``PRUEBA`` / ``SUSPENDIDO`` / ``BAJA``)
  as a behavior branch;
* returns one of the typed outcomes
  :class:`CommerceAvailabilityOutcome` (``available``,
  ``unavailable`` with a bounded reason ``blocked_state``,
  ``trial_expired`` or ``trial_quota_exhausted``);
* never commits, rolls back, opens, flushes, refreshes or closes
  the caller's transaction.

The single transactional ``reserve_confirmed_order`` entry point
locks the exact :class:`Comercio` row, re-evaluates the trial
window and quota inside the lock, and increments the counter only
on success. The caller owns commit / rollback so a failed
confirmation rolls back both the pedido transition and the counter
staging atomically.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Comercio, EstadoComercio
from backend.models.estado_comercio import EstadoComercioModoOperacion


class CommerceAvailabilityStatus(str, enum.Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class CommerceUnavailableReason(str, enum.Enum):
    BLOCKED_STATE = "blocked_state"
    TRIAL_EXPIRED = "trial_expired"
    TRIAL_QUOTA_EXHAUSTED = "trial_quota_exhausted"


@dataclass(frozen=True)
class CommerceAvailabilityOutcome:
    """Closed outcome returned by every public entry point.

    ``status`` is the single branching attribute. ``reason`` is
    populated only for unavailable outcomes and always carries one
    of the documented :class:`CommerceUnavailableReason` values.
    """

    status: CommerceAvailabilityStatus
    reason: CommerceUnavailableReason | None
    comercio_id: int
    modo_operacion: EstadoComercioModoOperacion | None
    prueba_hasta: datetime | None
    prueba_max_pedidos: int | None
    prueba_pedidos_consumidos: int

    @property
    def is_available(self) -> bool:
        return self.status is CommerceAvailabilityStatus.AVAILABLE


class CommerceAvailabilityService:
    """Single non-committing availability policy.

    The service holds a SQLAlchemy ``Session`` and one repository
    (the same :class:`Comercio` ORM model). It performs no
    transaction control and never instantiates a pedido row.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def evaluate(
        self,
        comercio_id: int,
        *,
        now: datetime | None = None,
    ) -> CommerceAvailabilityOutcome:
        """Return the typed availability for ``comercio_id``.

        A missing :class:`Comercio` row or a missing
        :class:`EstadoComercio` row collapse to
        ``unavailable`` / ``blocked_state`` so the caller can branch
        on a single attribute.
        """
        comercio = self._session.get(Comercio, comercio_id)
        if comercio is None:
            return CommerceAvailabilityOutcome(
                status=CommerceAvailabilityStatus.UNAVAILABLE,
                reason=CommerceUnavailableReason.BLOCKED_STATE,
                comercio_id=comercio_id,
                modo_operacion=None,
                prueba_hasta=None,
                prueba_max_pedidos=None,
                prueba_pedidos_consumidos=0,
            )
        estado = self._session.get(EstadoComercio, int(comercio.estado_id))
        if estado is None:
            return CommerceAvailabilityOutcome(
                status=CommerceAvailabilityStatus.UNAVAILABLE,
                reason=CommerceUnavailableReason.BLOCKED_STATE,
                comercio_id=comercio_id,
                modo_operacion=None,
                prueba_hasta=comercio.prueba_hasta,
                prueba_max_pedidos=comercio.prueba_max_pedidos,
                prueba_pedidos_consumidos=int(
                    comercio.prueba_pedidos_consumidos
                ),
            )
        return self._build_outcome(
            comercio=comercio,
            estado=estado,
            now=now,
        )

    def reserve_confirmed_order(
        self,
        comercio_id: int,
        *,
        now: datetime | None = None,
    ) -> CommerceAvailabilityOutcome:
        """Lock the commerce row, re-evaluate trial and reserve one unit.

        The caller MUST own the surrounding transaction. The
        reservation stages the counter increment on the locked row;
        a subsequent technical failure rolled back by the caller
        therefore reverts the counter together with the pedido
        transition. The method never calls ``commit`` /
        ``rollback``.
        """
        stmt = (
            select(Comercio)
            .where(Comercio.id == comercio_id)
            .with_for_update()
        )
        comercio = self._session.execute(stmt).scalar_one_or_none()
        if comercio is None:
            return CommerceAvailabilityOutcome(
                status=CommerceAvailabilityStatus.UNAVAILABLE,
                reason=CommerceUnavailableReason.BLOCKED_STATE,
                comercio_id=comercio_id,
                modo_operacion=None,
                prueba_hasta=None,
                prueba_max_pedidos=None,
                prueba_pedidos_consumidos=0,
            )
        estado = self._session.get(EstadoComercio, int(comercio.estado_id))
        if estado is None:
            return CommerceAvailabilityOutcome(
                status=CommerceAvailabilityStatus.UNAVAILABLE,
                reason=CommerceUnavailableReason.BLOCKED_STATE,
                comercio_id=comercio_id,
                modo_operacion=None,
                prueba_hasta=comercio.prueba_hasta,
                prueba_max_pedidos=comercio.prueba_max_pedidos,
                prueba_pedidos_consumidos=int(
                    comercio.prueba_pedidos_consumidos
                ),
            )

        outcome = self._build_outcome(
            comercio=comercio,
            estado=estado,
            now=now,
        )
        if not outcome.is_available:
            return outcome

        if estado.modo_operacion is EstadoComercioModoOperacion.PRUEBA:
            comercio.prueba_pedidos_consumidos = (
                int(comercio.prueba_pedidos_consumidos) + 1
            )

        return CommerceAvailabilityOutcome(
            status=CommerceAvailabilityStatus.AVAILABLE,
            reason=None,
            comercio_id=comercio_id,
            modo_operacion=estado.modo_operacion,
            prueba_hasta=comercio.prueba_hasta,
            prueba_max_pedidos=comercio.prueba_max_pedidos,
            prueba_pedidos_consumidos=int(
                comercio.prueba_pedidos_consumidos
            ),
        )

    def _build_outcome(
        self,
        *,
        comercio: Comercio,
        estado: EstadoComercio,
        now: datetime | None,
    ) -> CommerceAvailabilityOutcome:
        modo = EstadoComercioModoOperacion(estado.modo_operacion)
        base = CommerceAvailabilityOutcome(
            status=CommerceAvailabilityStatus.UNAVAILABLE,
            reason=CommerceUnavailableReason.BLOCKED_STATE,
            comercio_id=int(comercio.id),
            modo_operacion=modo,
            prueba_hasta=comercio.prueba_hasta,
            prueba_max_pedidos=comercio.prueba_max_pedidos,
            prueba_pedidos_consumidos=int(
                comercio.prueba_pedidos_consumidos
            ),
        )
        if modo is EstadoComercioModoOperacion.HABILITADO:
            return CommerceAvailabilityOutcome(
                status=CommerceAvailabilityStatus.AVAILABLE,
                reason=None,
                comercio_id=base.comercio_id,
                modo_operacion=base.modo_operacion,
                prueba_hasta=base.prueba_hasta,
                prueba_max_pedidos=base.prueba_max_pedidos,
                prueba_pedidos_consumidos=base.prueba_pedidos_consumidos,
            )
        if modo is not EstadoComercioModoOperacion.PRUEBA:
            return base

        reference = now if now is not None else _utcnow()
        if comercio.prueba_hasta is None:
            return CommerceAvailabilityOutcome(
                status=CommerceAvailabilityStatus.UNAVAILABLE,
                reason=CommerceUnavailableReason.TRIAL_EXPIRED,
                comercio_id=base.comercio_id,
                modo_operacion=base.modo_operacion,
                prueba_hasta=base.prueba_hasta,
                prueba_max_pedidos=base.prueba_max_pedidos,
                prueba_pedidos_consumidos=base.prueba_pedidos_consumidos,
            )
        until = comercio.prueba_hasta
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        if reference >= until:
            return CommerceAvailabilityOutcome(
                status=CommerceAvailabilityStatus.UNAVAILABLE,
                reason=CommerceUnavailableReason.TRIAL_EXPIRED,
                comercio_id=base.comercio_id,
                modo_operacion=base.modo_operacion,
                prueba_hasta=base.prueba_hasta,
                prueba_max_pedidos=base.prueba_max_pedidos,
                prueba_pedidos_consumidos=base.prueba_pedidos_consumidos,
            )
        if (
            comercio.prueba_max_pedidos is None
            or int(comercio.prueba_pedidos_consumidos)
            >= int(comercio.prueba_max_pedidos)
        ):
            return CommerceAvailabilityOutcome(
                status=CommerceAvailabilityStatus.UNAVAILABLE,
                reason=CommerceUnavailableReason.TRIAL_QUOTA_EXHAUSTED,
                comercio_id=base.comercio_id,
                modo_operacion=base.modo_operacion,
                prueba_hasta=base.prueba_hasta,
                prueba_max_pedidos=base.prueba_max_pedidos,
                prueba_pedidos_consumidos=base.prueba_pedidos_consumidos,
            )
        return CommerceAvailabilityOutcome(
            status=CommerceAvailabilityStatus.AVAILABLE,
            reason=None,
            comercio_id=base.comercio_id,
            modo_operacion=base.modo_operacion,
            prueba_hasta=base.prueba_hasta,
            prueba_max_pedidos=base.prueba_max_pedidos,
            prueba_pedidos_consumidos=base.prueba_pedidos_consumidos,
        )


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


__all__ = [
    "CommerceAvailabilityOutcome",
    "CommerceAvailabilityService",
    "CommerceAvailabilityStatus",
    "CommerceUnavailableReason",
]