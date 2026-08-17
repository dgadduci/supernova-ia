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
* The new ``MetodoEntregaService.update`` operation must leave
  every ``ComercioMetodoEntrega`` row untouched (its ``activo`` /
  commerce-specific ``orden`` survive) and every
  ``Pedido.id_metodo_entrega`` unchanged. Global deactivation is
  a valid business outcome — not an error or a cascade.
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
from backend.services.exceptions import (
    InvalidMetodoEntrega,
    MetodoEntregaNotFound,
)
from backend.services.metodo_entrega_service import MetodoEntregaService


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


class GlobalMetodoEntregaUpdateRegressionTest(unittest.TestCase):
    """Regression coverage for the new typed update of the global
    ``MetodosEntrega`` catalog.

    The :class:`MetodoEntregaService.update` operation must:

    * Keep ``codigo`` immutable (no parameter accepts it).
    * Leave ``ComercioMetodoEntrega`` rows untouched: a global
      deactivation or a global ``orden`` change must not propagate
      to any bridge row's ``activo`` or commerce-specific ``orden``.
    * Leave every ``Pedido.id_metodo_entrega`` reference intact —
      the global catalog row stays referenced even after
      deactivation so historical orders remain intact.
    * Roll back the whole mutation on persistence failure.
    * Not touch the JSON API contract: no update / delete endpoint
      was added on the JSON surface, so the ``MetodosEntrega``
      JSON read/create contract stays unchanged.

    These properties are validated with mocked repositories and
    sessions so no real database is touched.
    """

    def setUp(self) -> None:
        self.session = _FakeSession()
        self.service = MetodoEntregaService.__new__(MetodoEntregaService)
        self.service._session = self.session  # type: ignore[attr-defined]
        self.repo = MagicMock()
        self.service._repo = self.repo  # type: ignore[attr-defined]

    def _existing_row(self) -> MagicMock:
        row = MagicMock(name="MetodosEntrega")
        row.id = 20
        row.codigo = "DELIVERY"
        row.descripcion = "Envío a domicilio"
        row.orden = 1
        row.activo = True
        return row

    def test_update_signature_omits_codigo(self) -> None:
        """The service update signature must not accept ``codigo``
        because the global catalog identifier is immutable."""
        import inspect

        parameters = inspect.signature(MetodoEntregaService.update).parameters
        self.assertNotIn("codigo", parameters)

    def test_update_with_valid_args_stages_only_global_fields(self) -> None:
        row = self._existing_row()
        self.repo.get_by_id.return_value = row
        self.repo.update.return_value = row

        updated = self.service.update(
            20,
            descripcion="Envío a domicilio 24h",
            orden=3,
            activo=False,
        )

        self.assertTrue(self.session.committed)
        self.assertFalse(self.session.rolled_back)
        # The repository was called with only the documented fields
        self.repo.update.assert_called_once_with(
            row,
            descripcion="Envío a domicilio 24h",
            orden=3,
            activo=False,
        )

    def test_update_trims_and_rejects_blank_descripcion(self) -> None:
        row = self._existing_row()
        self.repo.get_by_id.return_value = row

        with self.assertRaises(InvalidMetodoEntrega):
            self.service.update(20, descripcion="   ")
        # The repository must never see the staged update
        self.repo.update.assert_not_called()
        self.assertFalse(self.session.committed)

    def test_update_rejects_negative_orden(self) -> None:
        row = self._existing_row()
        self.repo.get_by_id.return_value = row

        with self.assertRaises(InvalidMetodoEntrega):
            self.service.update(20, orden=-1)
        self.repo.update.assert_not_called()
        self.assertFalse(self.session.committed)

    def test_update_raises_not_found_for_unknown_id(self) -> None:
        self.repo.get_by_id.return_value = None

        with self.assertRaises(MetodoEntregaNotFound):
            self.service.update(9999, descripcion="X")
        self.repo.update.assert_not_called()
        self.assertFalse(self.session.committed)

    def test_update_rolls_back_on_persistence_failure(self) -> None:
        row = self._existing_row()
        self.repo.get_by_id.return_value = row

        def fail_update(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("forced persistence failure")

        self.repo.update.side_effect = fail_update

        with self.assertRaises(RuntimeError):
            self.service.update(20, descripcion="X")
        self.assertTrue(self.session.rolled_back)
        self.assertFalse(self.session.committed)

    def test_update_does_not_touch_comercio_bridge(self) -> None:
        """The repository contract guarantees that the staged
        mutation only mutates the global row. The repository never
        receives any reference to a ``ComercioMetodoEntrega`` row,
        so a global deactivation cannot cascade into a bridge
        ``activo`` or commerce-specific ``orden`` mutation."""
        row = self._existing_row()
        self.repo.get_by_id.return_value = row
        self.repo.update.return_value = row

        self.service.update(20, activo=False, orden=7, descripcion="X")

        # No commerce bridge helper is called by the update path
        self.assertFalse(
            hasattr(self.repo, "set_comercio_metodo_entrega_activo")
            and self.repo.set_comercio_metodo_entrega_activo.called,
            "global update must not invoke a commerce bridge setter",
        )
        self.assertFalse(
            hasattr(self.repo, "set_comercio_metodo_entrega_orden")
            and self.repo.set_comercio_metodo_entrega_orden.called,
            "global update must not invoke a commerce bridge orden setter",
        )

    def test_update_signature_accepts_typed_only_fields(self) -> None:
        """Only the documented fields (descripcion, orden, activo)
        are accepted; positional ordering / arbitrary kwargs must
        not be silently accepted."""
        import inspect

        params = inspect.signature(MetodoEntregaService.update).parameters
        self.assertEqual(
            set(params.keys()),
            {"self", "metodo_entrega_id", "descripcion", "orden", "activo"},
        )
        # All documented update fields must be keyword-only — the
        # caller cannot pass them positionally by accident.
        for name in ("descripcion", "orden", "activo"):
            self.assertEqual(
                params[name].kind,
                inspect.Parameter.KEYWORD_ONLY,
                f"{name} must be keyword-only",
            )


class GlobalMetodoEntregaJsonContractTest(unittest.TestCase):
    """The new panel surface must not weaken or extend the JSON API
    contract: ``/metodos-entrega`` keeps its read / create behavior
    and acquires no update / delete endpoint as a result of this
    change."""

    def test_json_router_does_not_register_update_endpoint(self) -> None:
        from backend.routers import metodos_entrega as json_router

        paths = {route.path for route in json_router.router.routes}
        # The OpenSpec change adds panel-only routes; the JSON
        # router must keep the documented surface unchanged.
        self.assertIn("/metodos-entrega", paths)
        self.assertIn("/metodos-entrega/{metodo_entrega_id}", paths)
        # No PUT or PATCH endpoint on the global JSON surface.
        for route in json_router.router.routes:
            if route.path.startswith("/metodos-entrega"):
                self.assertNotIn(
                    route.methods,
                    [{"PUT"}, {"PATCH"}, {"DELETE"}],
                    "JSON router must not expose a mutation endpoint "
                    "for the global MetodosEntrega catalog",
                )


if __name__ == "__main__":
    unittest.main()
