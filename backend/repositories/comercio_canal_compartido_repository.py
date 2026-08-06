"""SQLAlchemy queries for ``comercios_canales_compartidos``.

Confined to the shared-membership table. The repository exists so the
service layer can enforce the permanent ``(canal_id,
routing_code_normalizado)`` reservation rule without leaking
SQLAlchemy through the public API.

The repository never widens the candidate set: ``find_active`` looks
only at active rows; ``find_any`` exists only for the uniqueness check
that prevents a deactivated code from being reassigned to another
commerce — the calling service translates that match into the
``DuplicateRoutingCodeReservation`` typed exception.

Phase 5.3 adds ``list_active_by_canal`` so the service can expose
manual-selection options as channel-scoped active memberships only.
It never reads memberships from another channel.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.comercio_canal_compartido import ComercioCanalCompartido


class ComercioCanalCompartidoRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_active_by_canal_and_code(
        self,
        canal_id: int,
        routing_code_normalizado: str,
    ) -> ComercioCanalCompartido | None:
        stmt = select(ComercioCanalCompartido).where(
            ComercioCanalCompartido.canal_id == canal_id,
            ComercioCanalCompartido.routing_code_normalizado
            == routing_code_normalizado,
            ComercioCanalCompartido.activo.is_(True),
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def find_any_by_canal_and_code(
        self,
        canal_id: int,
        routing_code_normalizado: str,
    ) -> ComercioCanalCompartido | None:
        stmt = select(ComercioCanalCompartido).where(
            ComercioCanalCompartido.canal_id == canal_id,
            ComercioCanalCompartido.routing_code_normalizado
            == routing_code_normalizado,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def find_by_id(
        self, membership_id: int
    ) -> ComercioCanalCompartido | None:
        return self._session.get(ComercioCanalCompartido, membership_id)

    def list_active_by_canal(
        self, canal_id: int
    ) -> list[ComercioCanalCompartido]:
        stmt = (
            select(ComercioCanalCompartido)
            .where(
                ComercioCanalCompartido.canal_id == canal_id,
                ComercioCanalCompartido.activo.is_(True),
            )
            .order_by(ComercioCanalCompartido.id)
        )
        return list(self._session.execute(stmt).scalars())

    def find_active_by_canal_and_id(
        self, canal_id: int, membership_id: int
    ) -> ComercioCanalCompartido | None:
        stmt = select(ComercioCanalCompartido).where(
            ComercioCanalCompartido.canal_id == canal_id,
            ComercioCanalCompartido.id == membership_id,
            ComercioCanalCompartido.activo.is_(True),
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def find_active_by_canal_and_comercio(
        self, canal_id: int, comercio_id: int
    ) -> ComercioCanalCompartido | None:
        stmt = select(ComercioCanalCompartido).where(
            ComercioCanalCompartido.canal_id == canal_id,
            ComercioCanalCompartido.comercio_id == comercio_id,
            ComercioCanalCompartido.activo.is_(True),
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def create(
        self,
        canal_id: int,
        comercio_id: int,
        routing_code: str,
        routing_code_normalizado: str,
        activo: bool,
    ) -> ComercioCanalCompartido:
        row = ComercioCanalCompartido(
            canal_id=canal_id,
            comercio_id=comercio_id,
            routing_code=routing_code,
            routing_code_normalizado=routing_code_normalizado,
            activo=activo,
        )
        self._session.add(row)
        return row


__all__ = ["ComercioCanalCompartidoRepository"]
