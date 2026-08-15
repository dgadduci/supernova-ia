from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from backend.models import Comercio, ComercioMedioPago, ComercioMetodoEntrega


class ConfiguracionComercioRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, comercio_id: int) -> Comercio | None:
        stmt = (
            select(Comercio)
            .where(Comercio.id == comercio_id)
            .options(
                joinedload(Comercio.estado),
                joinedload(Comercio.flavor_comunicacion),
                selectinload(Comercio.medios_pago).joinedload(
                    ComercioMedioPago.medio_pago
                ),
                selectinload(Comercio.metodos_entrega).joinedload(
                    ComercioMetodoEntrega.metodo_entrega
                ),
            )
        )
        comercio = self._session.execute(stmt).scalar_one_or_none()
        if comercio is not None:
            comercio.medios_pago.sort(key=lambda association: association.id)
            comercio.metodos_entrega.sort(
                key=lambda association: (association.orden, association.id)
            )
        return comercio
