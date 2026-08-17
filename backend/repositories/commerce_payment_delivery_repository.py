"""Focused repository for the commerce payment/delivery configuration panel.

The repository is the panel's only read/write path into the
``ComercioMedioPago`` and ``ComercioMetodoEntrega`` bridge tables for
the documented admin mutation flow. It exposes the smallest possible
surface to satisfy the OpenSpec change:

* Locate the exact commerce (:data:`comercio_id`).
* Locate the exact global ``MediosPago`` / ``MetodosEntrega`` row
  (:data:`global_id`).
* Locate the existing bridge row for the *exact* commerce + global
  pair, scoped so a foreign association is never returned.
* Stage ``ComercioMedioPago`` and ``ComercioMetodoEntrega`` rows for
  enable / disable / edit operations carried out by the shared
  :class:`CommercePaymentDeliveryConfigurationService`.

The repository does NOT open transactions of its own, does NOT call
``commit`` / ``rollback`` and does NOT mutate any other table
(``Pedido``, ``MediosPago``, ``MetodosEntrega``, product catalog,
etc.). It never reads or traverses other comercios. The returned
rows are scoped to the supplied ``comercio_id`` so a forged
client cannot reach a foreign association through this boundary.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.models import (
    Comercio,
    ComercioMedioPago,
    ComercioMetodoEntrega,
    MediosPago,
    MetodosEntrega,
)


class CommercePaymentDeliveryConfigurationRepository:
    """Focused read/write helper for the commerce bridge configuration.

    All read methods are scoped by ``comercio_id`` so a foreign row is
    never returned. The mutator methods stage an ORM row and call
    ``flush`` so the surrounding service owns the commit / rollback
    boundary.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_comercio(self, comercio_id: int) -> Comercio | None:
        """Return the exact ``Comercio`` row or ``None`` when missing.

        The lookup does not eager-load any association collection; the
        service is responsible for the staged bridge row resolution.
        """
        return self._session.get(Comercio, comercio_id)

    def get_global_medio_pago(self, medio_pago_id: int) -> MediosPago | None:
        """Return the exact global ``MediosPago`` row or ``None``."""
        return self._session.get(MediosPago, medio_pago_id)

    def get_global_metodo_entrega(
        self, metodo_entrega_id: int
    ) -> MetodosEntrega | None:
        """Return the exact global ``MetodosEntrega`` row or ``None``."""
        return self._session.get(MetodosEntrega, metodo_entrega_id)

    def find_comercio_medio_pago(
        self,
        *,
        comercio_id: int,
        medio_pago_id: int,
    ) -> ComercioMedioPago | None:
        """Return the scoped ``ComercioMedioPago`` row or ``None``.

        The lookup is intentionally scoped by ``comercio_id`` so a
        forged client-supplied association that targets a foreign
        comercio is resolved against the foreign ``id_comercio`` /
        ``id_medio_pago`` pair and never matches the supplied
        ``comercio_id``. The join eagerly loads the global catalog
        row so the service does not issue a second query.
        """
        stmt = (
            select(ComercioMedioPago)
            .where(ComercioMedioPago.id_comercio == comercio_id)
            .where(ComercioMedioPago.id_medio_pago == medio_pago_id)
            .options(joinedload(ComercioMedioPago.medio_pago))
        )
        result = self._session.execute(stmt).scalar_one_or_none()
        if result is None:
            return None
        if result.id_comercio != comercio_id:
            return None
        return result

    def find_comercio_metodo_entrega(
        self,
        *,
        comercio_id: int,
        metodo_entrega_id: int,
    ) -> ComercioMetodoEntrega | None:
        """Return the scoped ``ComercioMetodoEntrega`` row or ``None``.

        The lookup is intentionally scoped by ``comercio_id`` so a
        forged client-supplied association that targets a foreign
        comercio is resolved against the foreign ``id_comercio`` /
        ``id_metodo_entrega`` pair and never matches the supplied
        ``comercio_id``. The join eagerly loads the global catalog
        row so the service does not issue a second query.
        """
        stmt = (
            select(ComercioMetodoEntrega)
            .where(ComercioMetodoEntrega.id_comercio == comercio_id)
            .where(ComercioMetodoEntrega.id_metodo_entrega == metodo_entrega_id)
            .options(joinedload(ComercioMetodoEntrega.metodo_entrega))
        )
        result = self._session.execute(stmt).scalar_one_or_none()
        if result is None:
            return None
        if result.id_comercio != comercio_id:
            return None
        return result

    def create_comercio_medio_pago(
        self,
        *,
        comercio_id: int,
        medio_pago_id: int,
        titular: str | None,
        alias: str | None,
    ) -> ComercioMedioPago:
        """Stage a new ``ComercioMedioPago`` row for the exact pair.

        The caller is responsible for guaranteeing the global
        ``MediosPago`` row is active and that the supplied per-field
        values are allowed by the global ``habilita_titular`` /
        ``habilita_alias`` flags. The repository never inspects
        those flags; the service is the single source of truth.
        """
        row = ComercioMedioPago(
            id_comercio=comercio_id,
            id_medio_pago=medio_pago_id,
            activo=True,
            titular=titular,
            alias=alias,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def set_comercio_medio_pago_activo(
        self,
        row: ComercioMedioPago,
        *,
        activo: bool,
    ) -> ComercioMedioPago:
        """Toggle the bridge row's ``activo`` flag without touching
        ``titular`` / ``alias``."""
        row.activo = bool(activo)
        self._session.flush()
        return row

    def update_comercio_medio_pago_payment_details(
        self,
        row: ComercioMedioPago,
        *,
        titular: str | None,
        alias: str | None,
    ) -> ComercioMedioPago:
        """Update the per-commerce payment-detail fields.

        The caller is responsible for the global ``habilita_titular``
        / ``habilita_alias`` gating; the repository simply stages the
        values the service already validated.
        """
        row.titular = titular
        row.alias = alias
        self._session.flush()
        return row

    def create_comercio_metodo_entrega(
        self,
        *,
        comercio_id: int,
        metodo_entrega_id: int,
        orden: int,
    ) -> ComercioMetodoEntrega:
        """Stage a new ``ComercioMetodoEntrega`` row for the exact pair.

        The caller must guarantee the global ``MetodosEntrega`` row is
        active and that ``orden`` is a non-negative integer; the
        repository only stages the row.
        """
        row = ComercioMetodoEntrega(
            id_comercio=comercio_id,
            id_metodo_entrega=metodo_entrega_id,
            activo=True,
            orden=orden,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def set_comercio_metodo_entrega_activo(
        self,
        row: ComercioMetodoEntrega,
        *,
        activo: bool,
    ) -> ComercioMetodoEntrega:
        """Toggle the bridge row's ``activo`` flag without touching
        ``orden``."""
        row.activo = bool(activo)
        self._session.flush()
        return row

    def set_comercio_metodo_entrega_orden(
        self,
        row: ComercioMetodoEntrega,
        *,
        orden: int,
    ) -> ComercioMetodoEntrega:
        """Replace the per-commerce ``orden`` value without changing
        the bridge row's ``activo`` flag."""
        row.orden = orden
        self._session.flush()
        return row


__all__ = ["CommercePaymentDeliveryConfigurationRepository"]
