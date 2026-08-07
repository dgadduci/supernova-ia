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

    def stage_create(
        self,
        whatsapp: str,
        nombre: str | None,
        domicilio: str | None,
        activo: bool,
    ) -> Cliente:
        """Stage an active ``Cliente`` without flushing.

        The pilot routing CLI owns its single setup transaction.
        The existing ``create`` method flushes so it can surface a
        duplicate-key error eagerly; the pilot staging path needs
        the pending state to remain invisible until the CLI flushes
        once after staging both the client and the channel and runs
        the final ``CommerceChannelResolver`` check.
        """
        row = Cliente(
            whatsapp=whatsapp,
            nombre=nombre,
            domicilio=domicilio,
            activo=activo,
        )
        self._session.add(row)
        return row

    def stage_set_activo(self, cliente: Cliente, activo: bool) -> None:
        """Stage a change to ``cliente.activo`` without flushing.

        Mirrors the no-flush contract of :meth:`stage_create` so the
        pilot CLI can stage client reactivation alongside a fresh
        channel row before the single flush that exposes the new
        routing state to the final resolver check.
        """
        cliente.activo = activo

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