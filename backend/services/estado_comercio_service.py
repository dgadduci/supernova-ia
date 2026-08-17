from sqlalchemy.orm import Session

from backend.models import EstadoComercio
from backend.repositories.estado_comercio_repository import EstadoComercioRepository
from backend.services.exceptions import EstadoComercioNotFound


class EstadoComercioService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = EstadoComercioRepository(session)

    def list_all(self) -> list[EstadoComercio]:
        return self._repo.list_all()

    def get_by_id(self, estado_id: int) -> EstadoComercio:
        row = self._repo.get_by_id(estado_id)
        if row is None:
            raise EstadoComercioNotFound(estado_id)
        return row


__all__ = ["EstadoComercioService"]