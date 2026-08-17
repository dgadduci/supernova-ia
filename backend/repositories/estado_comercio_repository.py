from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Comercio, EstadoComercio
from backend.models.estado_comercio import EstadoComercioModoOperacion


class EstadoComercioRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_all(self) -> list[EstadoComercio]:
        stmt = select(EstadoComercio).order_by(EstadoComercio.id)
        return list(self._session.execute(stmt).scalars())

    def list_seleccionable(self) -> list[EstadoComercio]:
        """Return the estados marked ``seleccionable=True``.

        The panel uses the listing as the closed source of state
        options; the policy itself never inspects the flag, only
        ``modo_operacion``.
        """
        stmt = (
            select(EstadoComercio)
            .where(EstadoComercio.seleccionable.is_(True))
            .order_by(EstadoComercio.id)
        )
        return list(self._session.execute(stmt).scalars())

    def get_by_id(self, estado_id: int) -> EstadoComercio | None:
        return self._session.get(EstadoComercio, estado_id)

    def get_by_codigo(self, codigo: str) -> EstadoComercio | None:
        stmt = select(EstadoComercio).where(EstadoComercio.codigo == codigo)
        return self._session.execute(stmt).scalar_one_or_none()

    def find_canonical_selectable(
        self, modo: EstadoComercioModoOperacion
    ) -> EstadoComercio | None:
        """Return the canonical ``seleccionable`` row for ``modo``.

        Used by the seed-time bootstrap and by the unit-test
        fixtures that need to resolve the canonical trial /
        enabled / blocked row without hardcoding ``id`` values.
        """

        stmt = (
            select(EstadoComercio)
            .where(EstadoComercio.modo_operacion == modo)
            .where(EstadoComercio.seleccionable.is_(True))
            .order_by(EstadoComercio.id)
        )
        return self._session.execute(stmt).scalars().first()

    def estado_in_use(self, estado_id: int) -> bool:
        stmt = select(Comercio.id).where(Comercio.estado_id == estado_id).limit(1)
        return self._session.execute(stmt).first() is not None


__all__ = ["EstadoComercioRepository"]