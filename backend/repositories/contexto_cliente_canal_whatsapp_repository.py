"""SQLAlchemy queries for ``contextos_clientes_canales_whatsapp``.

Confined to the customer-channel context table. The repository exists
so the service layer can look up and mutate the routing context
without leaking SQLAlchemy through the public API.

The repository never widens the candidate set: ``find_by_canal_and_cliente``
matches exactly one row by the unconditional ``(canal_id, cliente_id)``
unique key. The repository NEVER commits, rolls back, begins, flushes
or closes; the caller owns transaction control.

Phase 5.3 adds staged mutation helpers for ``comercio_id_seleccionado``
and ``comercio_id_cambio_pendiente``. The helpers only stage attribute
updates on the already-tracked ORM row — they MUST NOT be used to
widen the candidate set or to invoke business pipeline code.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.contexto_cliente_canal_whatsapp import (
    ContextoClienteCanalWhatsapp,
)


class ContextoClienteCanalWhatsappRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_by_canal_and_cliente(
        self,
        canal_id: int,
        cliente_id: int,
    ) -> ContextoClienteCanalWhatsapp | None:
        stmt = select(ContextoClienteCanalWhatsapp).where(
            ContextoClienteCanalWhatsapp.canal_id == canal_id,
            ContextoClienteCanalWhatsapp.cliente_id == cliente_id,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def create(
        self,
        canal_id: int,
        cliente_id: int,
        comercio_id_seleccionado: int,
        mensaje_original_pendiente: str,
    ) -> ContextoClienteCanalWhatsapp:
        row = ContextoClienteCanalWhatsapp(
            canal_id=canal_id,
            cliente_id=cliente_id,
            comercio_id_seleccionado=comercio_id_seleccionado,
            mensaje_original_pendiente=mensaje_original_pendiente,
        )
        self._session.add(row)
        return row

    def set_selected_comercio(
        self,
        contexto: ContextoClienteCanalWhatsapp,
        comercio_id_seleccionado: int,
    ) -> ContextoClienteCanalWhatsapp:
        contexto.comercio_id_seleccionado = comercio_id_seleccionado
        return contexto

    def stage_pending_target(
        self,
        contexto: ContextoClienteCanalWhatsapp,
        comercio_id_cambio_pendiente: int,
    ) -> ContextoClienteCanalWhatsapp:
        contexto.comercio_id_cambio_pendiente = (
            comercio_id_cambio_pendiente
        )
        return contexto

    def clear_pending_target(
        self,
        contexto: ContextoClienteCanalWhatsapp,
    ) -> ContextoClienteCanalWhatsapp:
        contexto.comercio_id_cambio_pendiente = None
        return contexto

    def commit_pending_target_to_selection(
        self,
        contexto: ContextoClienteCanalWhatsapp,
    ) -> ContextoClienteCanalWhatsapp:
        contexto.comercio_id_seleccionado = (
            contexto.comercio_id_cambio_pendiente
        )
        contexto.comercio_id_cambio_pendiente = None
        return contexto


__all__ = ["ContextoClienteCanalWhatsappRepository"]
