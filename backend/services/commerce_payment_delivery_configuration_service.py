"""Commerce payment/delivery configuration service.

The service is the single panel mutation boundary for the
``ComercioMedioPago`` and ``ComercioMetodoEntrega`` bridge rows. It
owns the *one* commit / rollback per successful POST and resolves the
exact commerce, global catalog row and existing association in one
scope.

The service is intentionally NOT a parallel pipeline. It does not
call any HTTP API, does not import the catalog / flavor /
configuration services and does not touch the ``Pedido`` table, the
global ``MediosPago`` / ``MetodosEntrega`` rows, the product catalog,
the embeddings service or the provider outbox. A failure rolls back
the entire attempted mutation; a successful POST returns the staged
bridge row so the panel can render the post-redirect detail.

Expected outcomes
-----------------

* Authoritative business outcomes
    * ``enable_payment_for_comercio`` activates the exact
      ``ComercioMedioPago`` row. Missing rows are created. The
      per-commerce ``titular`` / ``alias`` fields are written only
      when the global ``MediosPago`` row has ``habilita_titular``
      / ``habilita_alias`` enabled. A disabled field can never be
      cleared by a tampered POST; the existing value is preserved.
    * ``disable_payment_for_comercio`` deactivates the exact
      ``ComercioMedioPago`` row. ``titular`` / ``alias`` are
      preserved.
    * ``enable_delivery_for_comercio`` activates the exact
      ``ComercioMetodoEntrega`` row with a non-negative integer
      ``orden``. Missing rows are created. The order is validated
      through the same gate as the ``orden`` edit path.
    * ``disable_delivery_for_comercio`` deactivates the exact
      ``ComercioMetodoEntrega`` row. ``orden`` is preserved.
    * ``update_delivery_order_for_comercio`` replaces the order of
      the exact ``ComercioMetodoEntrega`` row. The row is kept
      active; the gate is the same non-negative integer check.

* Validation outcomes (no commit, scoped error)
    * Invalid ``id_comercio`` / ``id_medio_pago`` /
      ``id_metodo_entrega`` from the URL path: ``ComercioNotFound`` /
      ``MediosPagoNotFound`` / ``MetodoEntregaNotFound``.
    * Submitting a tampered ``titular`` / ``alias`` for a globally
      disabled field: ``InvalidPaymentField``.
    * Submitting a non-integer or negative ``orden``: ``InvalidDeliveryOrden``.

* Technical failures (rollback)
    * Unexpected repository / persistence failure: the service
      rolls back the whole transaction and propagates the
      exception to the route. The route translates it to a
      bounded ``400`` panel error.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.repositories.commerce_payment_delivery_repository import (
    CommercePaymentDeliveryConfigurationRepository,
)
from backend.services.exceptions import (
    ComercioNotFound,
    InvalidDeliveryOrden,
    InvalidPaymentField,
    MediosPagoNotFound,
    MetodoEntregaNotFound,
)


class CommercePaymentDeliveryConfigurationService:
    """Application service for the commerce payment/delivery panel.

    The service is the single mutation boundary the routes call
    into. Every public method resolves the exact commerce, the
    exact global row and (when present) the exact scoped bridge
    row before staging any change. The service owns the commit /
    rollback boundary: a successful return means the row was
    committed and refreshed; any raised exception means the
    transaction was rolled back.
    """

    _TITULAR_MAX_LENGTH = 150
    _ALIAS_MAX_LENGTH = 100

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = CommercePaymentDeliveryConfigurationRepository(session)

    def enable_payment_for_comercio(
        self,
        *,
        comercio_id: int,
        medio_pago_id: int,
        titular: str | None,
        alias: str | None,
    ):
        """Enable or create the exact ``ComercioMedioPago`` row.

        A missing association is created only when the global
        ``MediosPago`` row is active; an existing association is
        activated and its payment-detail fields are updated only
        when the corresponding global flags allow them. A
        tampered POST for a disabled field is rejected with
        ``InvalidPaymentField``; the stored value is preserved.
        """
        self._ensure_comercio(comercio_id)
        medio_pago = self._repo.get_global_medio_pago(medio_pago_id)
        if medio_pago is None:
            raise MediosPagoNotFound(medio_pago_id)
        if not medio_pago.activo:
            raise MediosPagoNotFound(medio_pago_id)

        cleaned_titular = self._validate_payment_field(
            raw_value=titular,
            field_name="titular",
            enabled=bool(medio_pago.habilita_titular),
            max_length=self._TITULAR_MAX_LENGTH,
        )
        cleaned_alias = self._validate_payment_field(
            raw_value=alias,
            field_name="alias",
            enabled=bool(medio_pago.habilita_alias),
            max_length=self._ALIAS_MAX_LENGTH,
        )

        existing = self._repo.find_comercio_medio_pago(
            comercio_id=comercio_id, medio_pago_id=medio_pago_id
        )

        try:
            if existing is None:
                row = self._repo.create_comercio_medio_pago(
                    comercio_id=comercio_id,
                    medio_pago_id=medio_pago_id,
                    titular=cleaned_titular,
                    alias=cleaned_alias,
                )
            else:
                self._repo.set_comercio_medio_pago_activo(
                    existing, activo=True
                )
                if medio_pago.habilita_titular:
                    existing.titular = cleaned_titular
                if medio_pago.habilita_alias:
                    existing.alias = cleaned_alias
                self._session.flush()
                row = existing
            self._session.commit()
            self._session.refresh(row)
            return row
        except Exception:
            self._session.rollback()
            raise

    def disable_payment_for_comercio(
        self,
        *,
        comercio_id: int,
        medio_pago_id: int,
    ):
        """Disable the exact ``ComercioMedioPago`` row if it exists.

        A missing association is a no-op business outcome: the
        service does not create a disabled row on a disable POST.
        The disable operation preserves the stored ``titular`` /
        ``alias`` values so the operator can re-enable the
        association later without losing the original data.
        """
        self._ensure_comercio(comercio_id)
        existing = self._repo.find_comercio_medio_pago(
            comercio_id=comercio_id, medio_pago_id=medio_pago_id
        )
        if existing is None:
            return None
        try:
            self._repo.set_comercio_medio_pago_activo(
                existing, activo=False
            )
            self._session.commit()
            self._session.refresh(existing)
            return existing
        except Exception:
            self._session.rollback()
            raise

    def enable_delivery_for_comercio(
        self,
        *,
        comercio_id: int,
        metodo_entrega_id: int,
        orden: int,
    ):
        """Activate or create the exact ``ComercioMetodoEntrega`` row.

        A missing association is created with the supplied
        ``orden``; an existing association is activated without
        losing its previous order. The disable path keeps the
        order untouched.
        """
        self._ensure_comercio(comercio_id)
        metodo_entrega = self._repo.get_global_metodo_entrega(
            metodo_entrega_id
        )
        if metodo_entrega is None:
            raise MetodoEntregaNotFound(metodo_entrega_id)
        if not metodo_entrega.activo:
            raise MetodoEntregaNotFound(metodo_entrega_id)

        cleaned_orden = self._validate_delivery_orden(orden)

        existing = self._repo.find_comercio_metodo_entrega(
            comercio_id=comercio_id, metodo_entrega_id=metodo_entrega_id
        )

        try:
            if existing is None:
                row = self._repo.create_comercio_metodo_entrega(
                    comercio_id=comercio_id,
                    metodo_entrega_id=metodo_entrega_id,
                    orden=cleaned_orden,
                )
            else:
                self._repo.set_comercio_metodo_entrega_activo(
                    existing, activo=True
                )
                self._repo.set_comercio_metodo_entrega_orden(
                    existing, orden=cleaned_orden
                )
                row = existing
            self._session.commit()
            self._session.refresh(row)
            return row
        except Exception:
            self._session.rollback()
            raise

    def disable_delivery_for_comercio(
        self,
        *,
        comercio_id: int,
        metodo_entrega_id: int,
    ):
        """Disable the exact ``ComercioMetodoEntrega`` row if it exists.

        A missing association is a no-op business outcome. The
        disable operation preserves the ``orden`` value so it can
        be restored on a future enable.
        """
        self._ensure_comercio(comercio_id)
        existing = self._repo.find_comercio_metodo_entrega(
            comercio_id=comercio_id, metodo_entrega_id=metodo_entrega_id
        )
        if existing is None:
            return None
        try:
            self._repo.set_comercio_metodo_entrega_activo(
                existing, activo=False
            )
            self._session.commit()
            self._session.refresh(existing)
            return existing
        except Exception:
            self._session.rollback()
            raise

    def update_delivery_order_for_comercio(
        self,
        *,
        comercio_id: int,
        metodo_entrega_id: int,
        orden: int,
    ):
        """Replace the order of the exact ``ComercioMetodoEntrega`` row.

        The operation is a valid business outcome only when the
        bridge row already exists. The activation flag is left
        untouched — the operation is open to the active and
        inactive associations so the panel can keep the operator's
        order visible even after a disable / re-enable cycle.
        """
        self._ensure_comercio(comercio_id)
        existing = self._repo.find_comercio_metodo_entrega(
            comercio_id=comercio_id, metodo_entrega_id=metodo_entrega_id
        )
        if existing is None:
            raise MetodoEntregaNotFound(metodo_entrega_id)
        cleaned_orden = self._validate_delivery_orden(orden)
        try:
            self._repo.set_comercio_metodo_entrega_orden(
                existing, orden=cleaned_orden
            )
            self._session.commit()
            self._session.refresh(existing)
            return existing
        except Exception:
            self._session.rollback()
            raise

    def _ensure_comercio(self, comercio_id: int) -> None:
        comercio = self._repo.get_comercio(comercio_id)
        if comercio is None:
            raise ComercioNotFound(comercio_id)

    @staticmethod
    def _validate_payment_field(
        *,
        raw_value: str | None,
        field_name: str,
        enabled: bool,
        max_length: int,
    ) -> str | None:
        """Normalize and validate a per-commerce payment field.

        Disabled fields can never be set. The service rejects a
        submitted value for a disabled field with a typed
        ``InvalidPaymentField`` so the route renders a bounded
        ``400`` without ever touching the stored value. A blank
        permitted value normalises to ``None``; a non-blank
        permitted value is stripped and bounded to the column
        length.
        """
        if isinstance(raw_value, str):
            cleaned = raw_value.strip()
        elif raw_value is None:
            cleaned = ""
        else:
            raise InvalidPaymentField(
                f"{field_name} must be a string or null"
            )
        if cleaned == "":
            cleaned = None
        if not enabled:
            if cleaned is not None:
                raise InvalidPaymentField(
                    f"{field_name} cannot be set when the global method "
                    "disables it"
                )
            return None
        if cleaned is None:
            return None
        if len(cleaned) > max_length:
            raise InvalidPaymentField(
                f"{field_name} exceeds the maximum allowed length"
            )
        return cleaned

    @staticmethod
    def _validate_delivery_orden(orden: int) -> int:
        """Validate the per-commerce ``orden`` of a delivery method.

        The order must be an integer ``>= 0``; the database
        constraint enforces the same gate.
        """
        if isinstance(orden, bool) or not isinstance(orden, int):
            raise InvalidDeliveryOrden(
                "orden must be a non-negative integer"
            )
        if orden < 0:
            raise InvalidDeliveryOrden(
                "orden must be a non-negative integer"
            )
        return orden


__all__ = ["CommercePaymentDeliveryConfigurationService"]
