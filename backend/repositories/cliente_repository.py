from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Cliente


class ClienteRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_all(self) -> list[Cliente]:
        stmt = select(Cliente).order_by(Cliente.id)
        return list(self._session.execute(stmt).scalars())

    def get_by_id(self, cliente_id: int) -> Cliente | None:
        return self._session.get(Cliente, cliente_id)

    def get_by_whatsapp(self, whatsapp: str) -> Cliente | None:
        stmt = select(Cliente).where(Cliente.whatsapp == whatsapp)
        return self._session.execute(stmt).scalar_one_or_none()

    def create(
        self,
        whatsapp: str,
        nombre: str | None,
        domicilio: str | None,
        activo: bool,
    ) -> Cliente:
        row = Cliente(
            whatsapp=whatsapp,
            nombre=nombre,
            domicilio=domicilio,
            activo=activo,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def update(
        self,
        cliente: Cliente,
        nombre: str | None,
        domicilio: str | None,
        activo: bool | None,
    ) -> Cliente:
        if nombre is not None:
            cliente.nombre = nombre
        if domicilio is not None:
            cliente.domicilio = domicilio
        if activo is not None:
            cliente.activo = activo
        self._session.flush()
        return cliente