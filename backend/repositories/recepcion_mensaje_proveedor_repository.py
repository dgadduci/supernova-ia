"""SQLAlchemy queries for ``recepciones_mensajes_proveedor``.

The repository is the sole boundary that knows the
``(proveedor, identificador_recepcion)`` uniqueness rule and the
PostgreSQL ``INSERT ... ON CONFLICT DO NOTHING RETURNING`` idiom used
to claim a provider receipt safely under concurrent retry.

The repository is read-mostly and never invokes transaction-control
methods: callers own the surrounding transaction and the final
``commit`` / ``rollback``. The only mutation is ``claim`` which
returns ``True`` when this caller became the first valid claim for
the ``(proveedor, identificador_recepcion)`` pair, or ``False`` when
a committed row for that pair already exists. The PostgreSQL
``ON CONFLICT DO NOTHING`` semantics guarantee that no second
concurrent caller can ever observe an empty ``RETURNING`` while the
winner is still in flight: an empty ``RETURNING`` proves a committed
row already exists, so the coordinator can safely roll back its own
still-open transaction and return ``already_processed``.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session as SqlSession

from backend.models.recepcion_mensaje_proveedor import (
    RecepcionMensajeProveedor,
)


class RecepcionMensajeProveedorRepository:
    def __init__(self, session: SqlSession) -> None:
        self._session = session

    def find_by_proveedor_y_recepcion(
        self,
        proveedor: str,
        identificador_recepcion: str,
    ) -> RecepcionMensajeProveedor | None:
        stmt = select(RecepcionMensajeProveedor).where(
            RecepcionMensajeProveedor.proveedor == proveedor,
            RecepcionMensajeProveedor.identificador_recepcion
            == identificador_recepcion,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def find_by_id(
        self, recepcion_id: int
    ) -> RecepcionMensajeProveedor | None:
        return self._session.get(
            RecepcionMensajeProveedor, int(recepcion_id)
        )

    def claim(
        self,
        proveedor: str,
        identificador_recepcion: str,
        canal_id: int,
        cliente_id: int,
        comercio_id: int,
    ) -> int | None:
        """Conflict-safe insert.

        Returns the staged ``id`` when this caller became the first
        valid claim for the ``(proveedor, identificador_recepcion)``
        pair, or ``None`` when a committed row for that pair
        already exists. The returned id is observable to other
        ``SELECT`` statements in the same transaction; the
        surrounding transaction still owns the actual commit.
        """
        stmt = (
            pg_insert(RecepcionMensajeProveedor)
            .values(
                proveedor=proveedor,
                identificador_recepcion=identificador_recepcion,
                canal_id=canal_id,
                cliente_id=cliente_id,
                comercio_id=comercio_id,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    "proveedor",
                    "identificador_recepcion",
                ],
            )
            .returning(RecepcionMensajeProveedor.id)
        )
        result = self._session.execute(stmt)
        value = result.scalar_one_or_none()
        if value is None:
            return None
        return int(value)


__all__ = ["RecepcionMensajeProveedorRepository"]
