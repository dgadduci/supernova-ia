from sqlalchemy.orm import Session

from backend.models import MetodosEntrega
from backend.repositories.metodo_entrega_repository import MetodoEntregaRepository
from backend.services.exceptions import (
    DuplicateMetodoEntrega,
    InvalidMetodoEntrega,
    MetodoEntregaNotFound,
)


class MetodoEntregaService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = MetodoEntregaRepository(session)

    def list_all(self) -> list[MetodosEntrega]:
        return self._repo.list_all()

    def get_by_id(self, metodo_entrega_id: int) -> MetodosEntrega:
        row = self._repo.get_by_id(metodo_entrega_id)
        if row is None:
            raise MetodoEntregaNotFound(metodo_entrega_id)
        return row

    def create(
        self,
        codigo: str,
        descripcion: str,
        orden: int,
        activo: bool,
    ) -> MetodosEntrega:
        cleaned_codigo = codigo.strip()
        cleaned_descripcion = descripcion.strip()
        if not cleaned_codigo:
            raise InvalidMetodoEntrega("codigo must not be empty")
        if not cleaned_descripcion:
            raise InvalidMetodoEntrega("descripcion must not be empty")
        if self._repo.get_by_codigo(cleaned_codigo) is not None:
            raise DuplicateMetodoEntrega(cleaned_codigo)
        try:
            row = self._repo.create(
                cleaned_codigo,
                cleaned_descripcion,
                orden,
                activo,
            )
            self._session.commit()
            return row
        except Exception:
            self._session.rollback()
            raise
