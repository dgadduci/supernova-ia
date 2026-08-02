from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import MetodosEntrega


class MetodoEntregaRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_all(self) -> list[MetodosEntrega]:
        stmt = select(MetodosEntrega).order_by(MetodosEntrega.id)
        return list(self._session.execute(stmt).scalars())

    def get_by_id(self, metodo_entrega_id: int) -> MetodosEntrega | None:
        return self._session.get(MetodosEntrega, metodo_entrega_id)

    def get_by_codigo(self, codigo: str) -> MetodosEntrega | None:
        stmt = select(MetodosEntrega).where(MetodosEntrega.codigo == codigo)
        return self._session.execute(stmt).scalar_one_or_none()

    def create(
        self,
        codigo: str,
        descripcion: str,
        orden: int,
        activo: bool,
    ) -> MetodosEntrega:
        row = MetodosEntrega(
            codigo=codigo,
            descripcion=descripcion,
            orden=orden,
            activo=activo,
        )
        self._session.add(row)
        self._session.flush()
        return row
