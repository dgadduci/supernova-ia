from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Comercio, EstadoComercio


class ComercioRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_all(self) -> list[Comercio]:
        stmt = select(Comercio).order_by(Comercio.id)
        return list(self._session.execute(stmt).scalars())

    def get_by_id(self, comercio_id: int) -> Comercio | None:
        return self._session.get(Comercio, comercio_id)

    def get_by_whatsapp(self, whatsapp: str) -> Comercio | None:
        stmt = select(Comercio).where(Comercio.whatsapp == whatsapp)
        return self._session.execute(stmt).scalar_one_or_none()

    def get_by_slug(self, slug: str) -> Comercio | None:
        stmt = select(Comercio).where(Comercio.slug == slug)
        return self._session.execute(stmt).scalar_one_or_none()

    def create(self, payload: dict) -> Comercio:
        comercio = Comercio(**payload)
        self._session.add(comercio)
        self._session.flush()
        return comercio

    def estado_exists(self, estado_id: int) -> bool:
        return self._session.get(EstadoComercio, estado_id) is not None
