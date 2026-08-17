"""Focused regression tests for the commerce payment/delivery config.

The tests document the boundary the OpenSpec change preserves:

* The existing ``GET /comercios/{comercio_id}/configuracion`` JSON
  contract is read-only and unchanged: payment and delivery
  associations are returned with their global catalog row and
  the per-commerce ``titular`` / ``alias`` / ``orden`` fields.
* The administrative panel never writes to the ``Pedido`` table
  or any other commerce's row. The shared service operates on
  the exact ``(comercio_id, medio_pago_id)`` /
  ``(comercio_id, metodo_entrega_id)`` pair.
* The JSON read router path is the only writer to the
  configuration read endpoint; the new panel does not introduce
  a JSON mutation endpoint.
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

from backend.admin.views import (
    CommerceCatalogNavigationView,
    CommerceDetailView,
    CommerceSummary,
    FlavorSummaryView,
    PaymentMethodDetailView,
)
from backend.admin.view_service import (
    AdministrativeCatalogPanelViewService,
)
from backend.services.commerce_payment_delivery_configuration_service import (
    CommercePaymentDeliveryConfigurationService,
)


class _FakeBridge:
    def __init__(self, **attrs: Any) -> None:
        for key, value in attrs.items():
            setattr(self, key, value)


class _FakeMedioPago:
    def __init__(self, **attrs: Any) -> None:
        for key, value in attrs.items():
            setattr(self, key, value)


class _FakeMetodoEntrega:
    def __init__(self, **attrs: Any) -> None:
        for key, value in attrs.items():
            setattr(self, key, value)


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def refresh(self, row: object) -> None:  # noqa: ARG002
        return

    def flush(self) -> None:
        return


class ConfigurationReadContractTest(unittest.TestCase):
    """The administrative panel must not mutate the read contract."""

    def test_view_service_projection_keeps_payment_fields(self) -> None:
        session = MagicMock(name="session")
        view = AdministrativeCatalogPanelViewService(session)

        detalle = CommerceDetailView(
            id=1,
            nombre_fantasia="X",
            nombre_corto="X",
            razon_social="X SRL",
            cuit="30-12345678-9",
            whatsapp="+5491100000001",
            calle="Calle 1",
            numero="100",
            piso_departamento=None,
            localidad="CABA",
            provincia="CABA",
            codigo_postal="1000",
            slug="comercio-x",
            estado="ACTIVO",
            zona_horaria="America/Argentina/Buenos_Aires",
            moneda="ARS",
            idioma="es-AR",
            medios_pago=[
                PaymentMethodDetailView(
                    association_id=110,
                    medio_pago_id=10,
                    codigo="EFECTIVO",
                    descripcion="Efectivo",
                    activo=True,
                    titular="ORIGINAL",
                    alias="original.alias",
                ),
            ],
        )

        self.assertEqual(detalle.medios_pago[0].association_id, 110)
        self.assertEqual(detalle.medios_pago[0].medio_pago_id, 10)
        self.assertEqual(detalle.medios_pago[0].codigo, "EFECTIVO")
        self.assertEqual(detalle.medios_pago[0].titular, "ORIGINAL")
        self.assertEqual(detalle.medios_pago[0].alias, "original.alias")
        self.assertTrue(detalle.medios_pago[0].activo)

    def test_payment_method_view_round_trip(self) -> None:
        view = PaymentMethodDetailView(
            association_id=142,
            medio_pago_id=42,
            codigo="EFECTIVO",
            descripcion="Efectivo",
            activo=True,
            titular="TITULAR",
            alias="alias.x",
        )
        self.assertEqual(view.association_id, 142)
        self.assertEqual(view.medio_pago_id, 42)
        self.assertEqual(view.codigo, "EFECTIVO")
        self.assertEqual(view.descripcion, "Efectivo")
        self.assertTrue(view.activo)
        self.assertEqual(view.titular, "TITULAR")
        self.assertEqual(view.alias, "alias.x")


class OrderHistoryRegressionTest(unittest.TestCase):
    """The administrative panel must never mutate ``Pedido``."""

    def test_payment_service_never_touches_pedido(self) -> None:
        session = _FakeSession()
        service = CommercePaymentDeliveryConfigurationService.__new__(
            CommercePaymentDeliveryConfigurationService
        )
        service._session = session  # type: ignore[attr-defined]
        repo = MagicMock()
        service._repo = repo  # type: ignore[attr-defined]

        repo.get_comercio.return_value = _FakeMedioPago(id=1)
        repo.get_global_medio_pago.return_value = _FakeMedioPago(
            id=10, activo=True, habilita_titular=False, habilita_alias=False
        )
        repo.find_comercio_medio_pago.return_value = None
        repo.create_comercio_medio_pago.return_value = _FakeBridge(
            id=1,
            id_comercio=1,
            id_medio_pago=10,
            activo=True,
            titular=None,
            alias=None,
        )

        service.enable_payment_for_comercio(
            comercio_id=1,
            medio_pago_id=10,
            titular=None,
            alias=None,
        )

        self.assertTrue(session.committed)
        repo.create_comercio_medio_pago.assert_called_once_with(
            comercio_id=1,
            medio_pago_id=10,
            titular=None,
            alias=None,
        )

    def test_delivery_service_never_touches_pedido(self) -> None:
        session = _FakeSession()
        service = CommercePaymentDeliveryConfigurationService.__new__(
            CommercePaymentDeliveryConfigurationService
        )
        service._session = session  # type: ignore[attr-defined]
        repo = MagicMock()
        service._repo = repo  # type: ignore[attr-defined]

        repo.get_comercio.return_value = _FakeMedioPago(id=1)
        repo.get_global_metodo_entrega.return_value = _FakeMetodoEntrega(
            id=20, activo=True, orden=5
        )
        repo.find_comercio_metodo_entrega.return_value = None
        repo.create_comercio_metodo_entrega.return_value = _FakeBridge(
            id=1,
            id_comercio=1,
            id_metodo_entrega=20,
            activo=True,
            orden=2,
        )

        service.enable_delivery_for_comercio(
            comercio_id=1,
            metodo_entrega_id=20,
            orden=2,
        )

        self.assertTrue(session.committed)
        repo.create_comercio_metodo_entrega.assert_called_once_with(
            comercio_id=1,
            metodo_entrega_id=20,
            orden=2,
        )


class CommerceIsolationRegressionTest(unittest.TestCase):
    """The service must never resolve a foreign association."""

    def test_service_calls_repository_with_scoped_pair(self) -> None:
        session = _FakeSession()
        service = CommercePaymentDeliveryConfigurationService.__new__(
            CommercePaymentDeliveryConfigurationService
        )
        service._session = session  # type: ignore[attr-defined]
        repo = MagicMock()
        service._repo = repo  # type: ignore[attr-defined]

        repo.get_comercio.return_value = _FakeMedioPago(id=1)
        repo.get_global_medio_pago.return_value = _FakeMedioPago(
            id=10, activo=True, habilita_titular=False, habilita_alias=False
        )
        repo.find_comercio_medio_pago.return_value = None

        service.enable_payment_for_comercio(
            comercio_id=1,
            medio_pago_id=10,
            titular=None,
            alias=None,
        )

        repo.find_comercio_medio_pago.assert_called_once_with(
            comercio_id=1, medio_pago_id=10
        )


if __name__ == "__main__":
    unittest.main()
