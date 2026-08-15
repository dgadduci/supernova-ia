"""Read-only repository for the global communication flavor catalog.

The catalog is system-managed global seed data. There is no application
write API for creating, editing or describing flavors. The repository
exposes only the safe read shapes used by the configuration surface.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import FlavorComunicacion


class FlavorComunicacionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_active(self) -> list[FlavorComunicacion]:
        stmt = (
            select(FlavorComunicacion)
            .where(FlavorComunicacion.activo.is_(True))
            .order_by(FlavorComunicacion.id)
        )
        return list(self._session.execute(stmt).scalars())

    def get_by_id(self, flavor_id: int) -> FlavorComunicacion | None:
        return self._session.get(FlavorComunicacion, flavor_id)

    def get_by_codigo(self, codigo: str) -> FlavorComunicacion | None:
        stmt = select(FlavorComunicacion).where(
            FlavorComunicacion.codigo == codigo
        )
        return self._session.execute(stmt).scalar_one_or_none()


__all__ = ["FlavorComunicacionRepository"]
