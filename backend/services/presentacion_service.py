from sqlalchemy.orm import Session

from backend.models import Presentacion
from backend.repositories.presentacion_repository import PresentacionRepository
from backend.services.exceptions import (
    ComercioNotFound,
    DuplicatePresentacionCodigo,
    DuplicatePresentacionDescripcion,
    InvalidPresentacion,
    PresentacionNotFound,
)


class PresentacionService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = PresentacionRepository(session)

    def list_by_comercio(self, comercio_id: int) -> list[Presentacion]:
        self._require_comercio(comercio_id)
        return self._repo.list_by_comercio(comercio_id)

    def get_by_id(self, presentacion_id: int) -> Presentacion:
        row = self._repo.get_by_id(presentacion_id)
        if row is None:
            raise PresentacionNotFound(presentacion_id)
        return row

    def create(
        self,
        comercio_id: int,
        codigo: str,
        descripcion: str,
        activo: bool | None,
        orden: int | None,
    ) -> Presentacion:
        self._require_comercio(comercio_id)
        cleaned_codigo = codigo.strip().lower()
        cleaned_descripcion = descripcion.strip()
        if not cleaned_codigo:
            raise InvalidPresentacion("codigo must not be empty")
        if not cleaned_descripcion:
            raise InvalidPresentacion("descripcion must not be empty")
        if self._repo.get_by_codigo(comercio_id, cleaned_codigo) is not None:
            raise DuplicatePresentacionCodigo(cleaned_codigo)
        if self._repo.get_by_descripcion(comercio_id, cleaned_descripcion) is not None:
            raise DuplicatePresentacionDescripcion(cleaned_descripcion)
        return self._repo.create(
            comercio_id,
            cleaned_codigo,
            cleaned_descripcion,
            activo,
            orden,
        )

    def _require_comercio(self, comercio_id: int) -> None:
        if not self._repo.comercio_exists(comercio_id):
            raise ComercioNotFound(comercio_id)
