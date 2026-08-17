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

    def list_active_for_comercio(self, comercio_id: int) -> list[MetodosEntrega]:
        return self._repo.list_active_for_comercio(comercio_id)

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
        if orden < 0:
            raise InvalidMetodoEntrega(
                "orden must be a non-negative integer"
            )
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
            self._session.refresh(row)
            return row
        except Exception:
            self._session.rollback()
            raise

    def update(
        self,
        metodo_entrega_id: int,
        *,
        descripcion: str | None = None,
        orden: int | None = None,
        activo: bool | None = None,
    ) -> MetodosEntrega:
        """Apply a typed update to a single global ``MetodosEntrega``.

        The operation intentionally omits ``codigo`` from the
        signature: the global catalog code is the natural identifier
        the rest of the system keys off, and the OpenSpec change
        makes it immutable after creation. The service resolves the
        exact id, validates the supplied description (trimmed, must
        not be empty) and order (must be non-negative), delegates
        staging to the repository and owns the surrounding
        commit / rollback sequence. The repository never opens a
        transaction of its own, so this method is the only place
        that can commit the global catalog edit.

        No ``ComercioMetodoEntrega`` bridge row or ``Pedido`` row
        is mutated: the global deactivation is a valid business
        outcome (not an error) and it leaves the bridge state
        untouched.
        """
        row = self._repo.get_by_id(metodo_entrega_id)
        if row is None:
            raise MetodoEntregaNotFound(metodo_entrega_id)
        cleaned_descripcion: str | None = None
        if descripcion is not None:
            cleaned = descripcion.strip()
            if not cleaned:
                raise InvalidMetodoEntrega("descripcion must not be empty")
            cleaned_descripcion = cleaned
        if orden is not None and orden < 0:
            raise InvalidMetodoEntrega(
                "orden must be a non-negative integer"
            )
        try:
            updated = self._repo.update(
                row,
                descripcion=cleaned_descripcion,
                orden=orden,
                activo=activo,
            )
            self._session.commit()
            self._session.refresh(updated)
            return updated
        except Exception:
            self._session.rollback()
            raise
