from sqlalchemy.orm import Session

from backend.models import Cliente
from backend.repositories.cliente_repository import ClienteRepository
from backend.services.exceptions import (
    ClienteNotFound,
    DuplicateWhatsapp,
    InvalidWhatsApp,
)


def normalize_whatsapp(raw: str) -> str:
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        raise InvalidWhatsApp("whatsapp must contain at least one digit")
    return f"+{digits}"


def _trim_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class ClienteService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = ClienteRepository(session)

    def get_by_id(self, cliente_id: int) -> Cliente:
        row = self._repo.get_by_id(cliente_id)
        if row is None:
            raise ClienteNotFound(cliente_id)
        return row

    def get_by_whatsapp(self, whatsapp: str) -> Cliente:
        canonical = normalize_whatsapp(whatsapp)
        row = self._repo.get_by_whatsapp(canonical)
        if row is None:
            raise ClienteNotFound(whatsapp)
        return row

    def create(
        self,
        whatsapp: str,
        nombre: str | None,
        domicilio: str | None,
        activo: bool,
    ) -> Cliente:
        canonical = normalize_whatsapp(whatsapp)
        cleaned_nombre = _trim_to_none(nombre)
        cleaned_domicilio = _trim_to_none(domicilio)
        if self._repo.get_by_whatsapp(canonical) is not None:
            raise DuplicateWhatsapp(canonical)
        try:
            row = self._repo.create(
                canonical,
                cleaned_nombre,
                cleaned_domicilio,
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
        cliente_id: int,
        nombre: str | None,
        domicilio: str | None,
        activo: bool | None,
    ) -> Cliente:
        cliente = self._repo.get_by_id(cliente_id)
        if cliente is None:
            raise ClienteNotFound(cliente_id)
        cleaned_nombre = _trim_to_none(nombre) if nombre is not None else None
        cleaned_domicilio = _trim_to_none(domicilio) if domicilio is not None else None
        try:
            row = self._repo.update(
                cliente,
                cleaned_nombre,
                cleaned_domicilio,
                activo,
            )
            self._session.commit()
            self._session.refresh(row)
            return row
        except Exception:
            self._session.rollback()
            raise

    def set_activo(self, cliente_id: int, activo: bool) -> Cliente:
        cliente = self._repo.get_by_id(cliente_id)
        if cliente is None:
            raise ClienteNotFound(cliente_id)
        try:
            row = self._repo.update(cliente, None, None, activo)
            self._session.commit()
            self._session.refresh(row)
            return row
        except Exception:
            self._session.rollback()
            raise