from sqlalchemy.orm import Session

from backend.models import MediosPago
from backend.repositories.medios_pago_repository import MediosPagoRepository
from backend.services.exceptions import DuplicateMedioPago, InvalidMedioPago, MediosPagoNotFound


class MediosPagoService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = MediosPagoRepository(session)

    def list_all(self) -> list[MediosPago]:
        return self._repo.list_all()

    def list_active_for_comercio(self, comercio_id: int) -> list[MediosPago]:
        return self._repo.list_active_for_comercio(comercio_id)

    def get_by_id(self, medio_pago_id: int) -> MediosPago:
        row = self._repo.get_by_id(medio_pago_id)
        if row is None:
            raise MediosPagoNotFound(medio_pago_id)
        return row

    def create(
        self,
        codigo: str,
        descripcion: str,
        activo: bool,
        habilita_titular: bool = False,
        habilita_alias: bool = False,
    ) -> MediosPago:
        cleaned_codigo = codigo.strip()
        cleaned_descripcion = descripcion.strip()
        if not cleaned_codigo:
            raise InvalidMedioPago("codigo must not be empty")
        if not cleaned_descripcion:
            raise InvalidMedioPago("descripcion must not be empty")
        if self._repo.get_by_codigo(cleaned_codigo) is not None:
            raise DuplicateMedioPago(cleaned_codigo)
        try:
            row = self._repo.create(
                cleaned_codigo,
                cleaned_descripcion,
                activo,
                habilita_titular,
                habilita_alias,
            )
            self._session.commit()
            self._session.refresh(row)
            return row
        except Exception:
            self._session.rollback()
            raise

    def update(
        self,
        medio_pago_id: int,
        *,
        descripcion: str | None = None,
        activo: bool | None = None,
        habilita_titular: bool | None = None,
        habilita_alias: bool | None = None,
    ) -> MediosPago:
        row = self._repo.get_by_id(medio_pago_id)
        if row is None:
            raise MediosPagoNotFound(medio_pago_id)
        cleaned_descripcion: str | None = None
        if descripcion is not None:
            cleaned = descripcion.strip()
            if not cleaned:
                raise InvalidMedioPago("descripcion must not be empty")
            cleaned_descripcion = cleaned
        try:
            updated = self._repo.update(
                row,
                descripcion=cleaned_descripcion,
                activo=activo,
                habilita_titular=habilita_titular,
                habilita_alias=habilita_alias,
            )
            self._session.commit()
            self._session.refresh(updated)
            return updated
        except Exception:
            self._session.rollback()
            raise