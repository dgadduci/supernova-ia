from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.models import Comercio, EstadoComercio


class ComercioRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_all(self) -> list[Comercio]:
        stmt = (
            select(Comercio)
            .options(joinedload(Comercio.flavor_comunicacion))
            .order_by(Comercio.id)
        )
        return list(self._session.execute(stmt).scalars())

    def get_by_id(self, comercio_id: int) -> Comercio | None:
        stmt = (
            select(Comercio)
            .where(Comercio.id == comercio_id)
            .options(joinedload(Comercio.flavor_comunicacion))
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_by_whatsapp(self, whatsapp: str) -> Comercio | None:
        stmt = (
            select(Comercio)
            .where(Comercio.whatsapp == whatsapp)
            .options(joinedload(Comercio.flavor_comunicacion))
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_by_slug(self, slug: str) -> Comercio | None:
        stmt = (
            select(Comercio)
            .where(Comercio.slug == slug)
            .options(joinedload(Comercio.flavor_comunicacion))
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def create(self, payload: dict) -> Comercio:
        comercio = Comercio(**payload)
        self._session.add(comercio)
        self._session.flush()
        return comercio

    def set_flavor_comunicacion(
        self, comercio: Comercio, flavor_id: int
    ) -> None:
        comercio.flavor_comunicacion_id = flavor_id
        self._session.flush()

    def estado_exists(self, estado_id: int) -> bool:
        return self._session.get(EstadoComercio, estado_id) is not None
