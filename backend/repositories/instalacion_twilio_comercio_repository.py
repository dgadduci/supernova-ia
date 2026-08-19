"""SQLAlchemy queries for ``instalaciones_twilio_comercio``.

The repository is the only boundary that knows the unique ``instalacion_id``
rule and the FK to ``comercios``. The bounded provisioning CLI and the
internal ingress dependency both call into it so the service layer stays
free of SQLAlchemy details.

The repository is read-mostly and never invokes transaction-control
methods: callers own the surrounding transaction and the final
``commit`` / ``rollback``. The mutations ``add`` and ``mark_inactive``
only stage ORM state on the caller-owned session; they never flush or
commit.

The "exactly one active installation per comercio" invariant is
enforced by the database-level partial unique index
``uq_instalacion_twilio_one_active_per_comercio``. The repository's
``create_installation_for_comercio`` helper relies on that constraint
to refuse concurrent duplicates — it stages the ORM row, commits the
surrounding transaction, and lets the partial unique index raise the
typed exception when two provisioners race.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.instalacion_twilio_comercio import InstalacionTwilioComercio


class InstalacionTwilioComercioRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_by_instalacion_id(
        self, instalacion_id: str
    ) -> InstalacionTwilioComercio | None:
        return self._session.execute(
            select(InstalacionTwilioComercio).where(
                InstalacionTwilioComercio.instalacion_id == instalacion_id
            )
        ).scalar_one_or_none()

    def find_active_by_instalacion_id(
        self, instalacion_id: str
    ) -> InstalacionTwilioComercio | None:
        return self._session.execute(
            select(InstalacionTwilioComercio).where(
                InstalacionTwilioComercio.instalacion_id == instalacion_id,
                InstalacionTwilioComercio.activo.is_(True),
            )
        ).scalar_one_or_none()

    def find_active_by_comercio_id(
        self, comercio_id: int
    ) -> InstalacionTwilioComercio | None:
        return self._session.execute(
            select(InstalacionTwilioComercio).where(
                InstalacionTwilioComercio.id_comercio == int(comercio_id),
                InstalacionTwilioComercio.activo.is_(True),
            )
        ).scalar_one_or_none()

    def find_by_id(self, instalacion_pk: int) -> InstalacionTwilioComercio | None:
        return self._session.get(InstalacionTwilioComercio, int(instalacion_pk))

    def add(
        self,
        *,
        id_comercio: int,
        tc_service_url: str,
        instalacion_id: str,
        secreto_envelope: str,
        secreto_envelope_kid: str,
        activo: bool,
    ) -> InstalacionTwilioComercio:
        """Stage a new installation row.

        The caller owns the surrounding transaction. The repository does
        not commit, rollback or flush; it only ``add``s the new ORM row
        so the service layer can compose multi-row operations.
        """
        row = InstalacionTwilioComercio(
            id_comercio=int(id_comercio),
            tc_service_url=str(tc_service_url),
            instalacion_id=str(instalacion_id),
            secreto_envelope=str(secreto_envelope),
            secreto_envelope_kid=str(secreto_envelope_kid),
            activo=bool(activo),
        )
        self._session.add(row)
        return row

    def mark_inactive(
        self,
        *,
        instalacion_id: str,
        fecha_baja: Any | None,
    ) -> bool:
        """Mark an installation inactive without committing.

        Returns ``True`` when the update affected the row, ``False``
        when no matching active row exists. The caller owns the
        surrounding transaction.
        """
        row = self.find_active_by_instalacion_id(instalacion_id)
        if row is None:
            return False
        row.activo = False
        row.fecha_baja = (
            fecha_baja
            if fecha_baja is not None
            else datetime.now(tz=datetime.now().astimezone().tzinfo)
        )
        return True


__all__ = ["InstalacionTwilioComercioRepository"]