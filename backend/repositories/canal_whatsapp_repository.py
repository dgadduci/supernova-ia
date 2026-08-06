"""SQLAlchemy queries for ``canales_whatsapp``.

Confined to the ``canales_whatsapp`` table. Services MUST NOT issue
queries directly; they call into this repository so the resolver and
channel service stay free of infrastructure code.

The repository is read-mostly: the only mutation is the initial
``create`` performed by the channel service after it has validated the
provider, destination and (for dedicated channels) exclusive
commerce. It adds pending ORM state to the caller-owned session without
synchronizing or controlling the transaction.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.canal_whatsapp import CanalWhatsapp, CanalWhatsappMode


class CanalWhatsappRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_active_by_provider_destination(
        self,
        provider: str,
        destination_e164: str,
    ) -> CanalWhatsapp | None:
        stmt = (
            select(CanalWhatsapp)
            .where(
                CanalWhatsapp.provider == provider,
                CanalWhatsapp.destination_e164 == destination_e164,
                CanalWhatsapp.activo.is_(True),
            )
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def find_by_provider_destination_any(
        self,
        provider: str,
        destination_e164: str,
    ) -> CanalWhatsapp | None:
        stmt = (
            select(CanalWhatsapp)
            .where(
                CanalWhatsapp.provider == provider,
                CanalWhatsapp.destination_e164 == destination_e164,
            )
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def find_by_id(self, canal_id: int) -> CanalWhatsapp | None:
        return self._session.get(CanalWhatsapp, canal_id)

    def find_active_dedicated_by_id(
        self, canal_id: int
    ) -> CanalWhatsapp | None:
        stmt = select(CanalWhatsapp).where(
            CanalWhatsapp.id == canal_id,
            CanalWhatsapp.activo.is_(True),
            CanalWhatsapp.mode == CanalWhatsappMode.DEDICATED,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def create(
        self,
        provider: str,
        destination_e164: str,
        mode: CanalWhatsappMode,
        id_comercio_exclusivo: int | None,
        activo: bool,
    ) -> CanalWhatsapp:
        row = CanalWhatsapp(
            provider=provider,
            destination_e164=destination_e164,
            mode=mode,
            id_comercio_exclusivo=id_comercio_exclusivo,
            activo=activo,
        )
        self._session.add(row)
        return row


__all__ = ["CanalWhatsappRepository"]