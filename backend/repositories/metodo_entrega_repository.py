from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import ComercioMetodoEntrega, MetodosEntrega


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

    def list_active_for_comercio(self, comercio_id: int) -> list[MetodosEntrega]:
        """Return the metodos_entrega rows that are globally active and enabled
        for the supplied comercio. The join enforces commerce isolation.
        """
        stmt = (
            select(MetodosEntrega)
            .join(
                ComercioMetodoEntrega,
                ComercioMetodoEntrega.id_metodo_entrega == MetodosEntrega.id,
            )
            .where(ComercioMetodoEntrega.id_comercio == comercio_id)
            .where(ComercioMetodoEntrega.activo.is_(True))
            .where(MetodosEntrega.activo.is_(True))
            .order_by(MetodosEntrega.orden, MetodosEntrega.id)
        )
        return list(self._session.execute(stmt).scalars())

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

    def update(
        self,
        row: MetodosEntrega,
        *,
        descripcion: str | None,
        orden: int | None,
        activo: bool | None,
    ) -> MetodosEntrega:
        """Stage a global ``MetodosEntrega`` update.

        The repository is intentionally limited to staging the
        in-memory mutations the service has already validated: the
        ``codigo`` is immutable by contract (the global catalog
        identifier must stay stable across edits) and bridge /
        per-commerce state is not touched by this repository. The
        caller is responsible for the surrounding commit / rollback
        sequence; the repository never opens a transaction.
        """
        if descripcion is not None:
            row.descripcion = descripcion
        if orden is not None:
            row.orden = orden
        if activo is not None:
            row.activo = activo
        self._session.flush()
        return row
