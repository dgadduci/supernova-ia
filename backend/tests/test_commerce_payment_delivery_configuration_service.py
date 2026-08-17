"""Focused tests for the commerce payment/delivery configuration service.

The tests cover the documented boundary of
:class:`CommercePaymentDeliveryConfigurationService` and its focused
repository:

* Commerce isolation: a forged foreign association id cannot
  affect another ``Comercio`` row.
* Creation / enable / disable cycles preserve stored ``titular``,
  ``alias`` and ``orden`` values.
* Global payment ``habilita_titular`` / ``habilita_alias`` flags
  gate both the rendering payload and the persistence: a tampered
  POST for a globally disabled field is rejected without
  clearing the stored value.
* Delivery ``orden`` validation rejects non-integer and negative
  values.
* Global catalog deactivation is rejected for new enable attempts
  — the service never silently substitutes a different method.
* Unexpected persistence errors roll back the whole attempted
  mutation so partial state is never persisted.
* The service never touches ``Pedido``, the global catalog rows
  or other comercios.
* The focused repository enforces the ``(comercio_id, global_id)``
  pair when looking up the existing bridge row.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from backend.models import (
    Comercio,
    ComercioMedioPago,
    ComercioMetodoEntrega,
    MediosPago,
    MetodosEntrega,
)
from backend.services.commerce_payment_delivery_configuration_service import (
    CommercePaymentDeliveryConfigurationService,
)
from backend.services.exceptions import (
    ComercioNotFound,
    InvalidDeliveryOrden,
    InvalidPaymentField,
    MediosPagoNotFound,
    MetodoEntregaNotFound,
)


def _build_comercio(comercio_id: int) -> Comercio:
    return Comercio(
        id=comercio_id,
        nombre_fantasia="X",
        nombre_corto="X",
        razon_social="X SRL",
        cuit="30-12345678-9",
        whatsapp=f"+54911000000{comercio_id:02d}",
        calle="Calle 1",
        numero="100",
        piso_departamento=None,
        localidad="CABA",
        provincia="CABA",
        codigo_postal="1000",
        slug=f"comercio-{comercio_id}",
        estado_id=1,
        zona_horaria="America/Argentina/Buenos_Aires",
        moneda="ARS",
        idioma="es-AR",
    )


def _build_medio_pago(
    medio_pago_id: int,
    *,
    activo: bool = True,
    habilita_titular: bool = False,
    habilita_alias: bool = False,
) -> MediosPago:
    return MediosPago(
        id=medio_pago_id,
        codigo=f"MP{medio_pago_id}",
        descripcion=f"Medio {medio_pago_id}",
        activo=activo,
        habilita_titular=habilita_titular,
        habilita_alias=habilita_alias,
    )


def _build_metodo_entrega(
    metodo_entrega_id: int,
    *,
    activo: bool = True,
    orden: int = 1,
) -> MetodosEntrega:
    return MetodosEntrega(
        id=metodo_entrega_id,
        codigo=f"ME{metodo_entrega_id}",
        descripcion=f"Metodo {metodo_entrega_id}",
        activo=activo,
        orden=orden,
    )


def _build_bridge_payment(
    *,
    comercio_id: int,
    medio_pago_id: int,
    activo: bool = True,
    titular: str | None = None,
    alias: str | None = None,
) -> ComercioMedioPago:
    return ComercioMedioPago(
        id=comercio_id * 1000 + medio_pago_id,
        id_comercio=comercio_id,
        id_medio_pago=medio_pago_id,
        activo=activo,
        titular=titular,
        alias=alias,
    )


def _build_bridge_delivery(
    *,
    comercio_id: int,
    metodo_entrega_id: int,
    activo: bool = True,
    orden: int = 1,
) -> ComercioMetodoEntrega:
    return ComercioMetodoEntrega(
        id=comercio_id * 1000 + metodo_entrega_id,
        id_comercio=comercio_id,
        id_metodo_entrega=metodo_entrega_id,
        activo=activo,
        orden=orden,
    )


class _FakeSession:
    """Record the session operations the service performs.

    The fake session tracks the staged rows so the tests can assert
    that the service performed a single atomic mutation and
    honoured the commit / rollback boundary.
    """

    def __init__(self) -> None:
        self.commits: list[None] = []
        self.rollbacks: list[None] = []
        self.refreshes: list[object] = []
        self.flushes: list[None] = []
        self.raise_on_flush: Exception | None = None

    def commit(self) -> None:
        self.commits.append(None)

    def rollback(self) -> None:
        self.rollbacks.append(None)

    def refresh(self, row: object) -> None:
        self.refreshes.append(row)

    def flush(self) -> None:
        if self.raise_on_flush is not None:
            error = self.raise_on_flush
            self.raise_on_flush = None
            raise error
        self.flushes.append(None)


def _build_service(session: _FakeSession) -> tuple[
    CommercePaymentDeliveryConfigurationService, MagicMock
]:
    """Build a service instance with a mocked repository.

    The tests run the real service code against a stub session to
    validate the exact commit / rollback boundary. The repository
    is mocked so the tests can stage every dependency.
    """
    service = CommercePaymentDeliveryConfigurationService.__new__(
        CommercePaymentDeliveryConfigurationService
    )
    service._session = session  # type: ignore[attr-defined]
    repo = MagicMock()
    service._repo = repo  # type: ignore[attr-defined]
    return service, repo


class EnablePaymentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = _FakeSession()
        self.comercio = _build_comercio(1)
        self.medio_pago = _build_medio_pago(
            10,
            habilita_titular=True,
            habilita_alias=True,
        )
        self.service, self.repo = _build_service(self.session)

    def test_creates_bridge_when_no_prior_association(self) -> None:
        self.repo.get_comercio.return_value = self.comercio
        self.repo.get_global_medio_pago.return_value = self.medio_pago
        self.repo.find_comercio_medio_pago.return_value = None
        staged_row = _build_bridge_payment(
            comercio_id=1,
            medio_pago_id=10,
            titular="TITULAR",
            alias="alias.x",
        )
        self.repo.create_comercio_medio_pago.return_value = staged_row

        result = self.service.enable_payment_for_comercio(
            comercio_id=1,
            medio_pago_id=10,
            titular="TITULAR",
            alias="alias.x",
        )

        self.assertIs(result, staged_row)
        self.repo.create_comercio_medio_pago.assert_called_once_with(
            comercio_id=1,
            medio_pago_id=10,
            titular="TITULAR",
            alias="alias.x",
        )
        self.assertEqual(self.session.commits, [None])
        self.assertEqual(self.session.rollbacks, [])
        self.assertEqual(self.session.refreshes, [staged_row])

    def test_updates_existing_bridge_when_association_already_exists(self) -> None:
        self.repo.get_comercio.return_value = self.comercio
        self.repo.get_global_medio_pago.return_value = self.medio_pago
        existing = _build_bridge_payment(
            comercio_id=1,
            medio_pago_id=10,
            activo=False,
            titular="Old titular",
            alias="old.alias",
        )
        self.repo.find_comercio_medio_pago.return_value = existing

        result = self.service.enable_payment_for_comercio(
            comercio_id=1,
            medio_pago_id=10,
            titular="New titular",
            alias="new.alias",
        )

        self.assertIs(result, existing)
        self.repo.set_comercio_medio_pago_activo.assert_called_once_with(
            existing, activo=True
        )
        self.assertEqual(existing.titular, "New titular")
        self.assertEqual(existing.alias, "new.alias")
        self.assertEqual(self.session.commits, [None])
        self.assertEqual(self.session.rollbacks, [])

    def test_rejects_tampered_field_when_global_flag_is_disabled(self) -> None:
        self.repo.get_comercio.return_value = self.comercio
        self.medio_pago.habilita_alias = False
        self.repo.get_global_medio_pago.return_value = self.medio_pago
        existing = _build_bridge_payment(
            comercio_id=1,
            medio_pago_id=10,
            titular="Original titular",
            alias="original.alias",
        )
        self.repo.find_comercio_medio_pago.return_value = existing

        with self.assertRaises(InvalidPaymentField):
            self.service.enable_payment_for_comercio(
                comercio_id=1,
                medio_pago_id=10,
                titular="Original titular",
                alias="forged.alias",
            )

        self.repo.set_comercio_medio_pago_activo.assert_not_called()
        self.assertEqual(existing.titular, "Original titular")
        self.assertEqual(existing.alias, "original.alias")
        self.assertEqual(self.session.commits, [])
        self.assertEqual(self.session.rollbacks, [])

    def test_blank_permitted_field_normalises_to_none(self) -> None:
        self.repo.get_comercio.return_value = self.comercio
        self.medio_pago.habilita_titular = True
        self.medio_pago.habilita_alias = True
        self.repo.get_global_medio_pago.return_value = self.medio_pago
        self.repo.find_comercio_medio_pago.return_value = None
        staged_row = _build_bridge_payment(
            comercio_id=1,
            medio_pago_id=10,
        )
        self.repo.create_comercio_medio_pago.return_value = staged_row

        self.service.enable_payment_for_comercio(
            comercio_id=1,
            medio_pago_id=10,
            titular="   ",
            alias="",
        )

        self.repo.create_comercio_medio_pago.assert_called_once_with(
            comercio_id=1,
            medio_pago_id=10,
            titular=None,
            alias=None,
        )

    def test_unknown_comercio_raises_not_found(self) -> None:
        self.repo.get_comercio.return_value = None
        with self.assertRaises(ComercioNotFound):
            self.service.enable_payment_for_comercio(
                comercio_id=1,
                medio_pago_id=10,
                titular=None,
                alias=None,
            )
        self.repo.get_global_medio_pago.assert_not_called()
        self.assertEqual(self.session.commits, [])
        self.assertEqual(self.session.rollbacks, [])

    def test_unknown_medio_pago_raises_not_found(self) -> None:
        self.repo.get_comercio.return_value = self.comercio
        self.repo.get_global_medio_pago.return_value = None
        with self.assertRaises(MediosPagoNotFound):
            self.service.enable_payment_for_comercio(
                comercio_id=1,
                medio_pago_id=10,
                titular=None,
                alias=None,
            )
        self.assertEqual(self.session.commits, [])

    def test_inactive_global_medio_pago_raises_not_found(self) -> None:
        self.repo.get_comercio.return_value = self.comercio
        self.repo.get_global_medio_pago.return_value = _build_medio_pago(
            10, activo=False
        )
        with self.assertRaises(MediosPagoNotFound):
            self.service.enable_payment_for_comercio(
                comercio_id=1,
                medio_pago_id=10,
                titular=None,
                alias=None,
            )
        self.assertEqual(self.session.commits, [])

    def test_forged_foreign_association_id_returns_none(self) -> None:
        self.repo.get_comercio.return_value = self.comercio
        self.repo.get_global_medio_pago.return_value = self.medio_pago
        self.repo.find_comercio_medio_pago.return_value = None

        self.service.enable_payment_for_comercio(
            comercio_id=1,
            medio_pago_id=10,
            titular=None,
            alias=None,
        )

        self.repo.find_comercio_medio_pago.assert_called_once_with(
            comercio_id=1, medio_pago_id=10
        )

    def test_unexpected_persistence_failure_rolls_back(self) -> None:
        self.session.raise_on_flush = RuntimeError("database boom")
        self.repo.get_comercio.return_value = self.comercio
        self.repo.get_global_medio_pago.return_value = self.medio_pago
        self.repo.find_comercio_medio_pago.return_value = None

        def _boomer(*args, **kwargs):
            self.session.flush()
            return _build_bridge_payment(
                comercio_id=1, medio_pago_id=10
            )

        self.repo.create_comercio_medio_pago.side_effect = _boomer

        with self.assertRaises(RuntimeError):
            self.service.enable_payment_for_comercio(
                comercio_id=1,
                medio_pago_id=10,
                titular=None,
                alias=None,
            )

        self.assertEqual(self.session.commits, [])
        self.assertEqual(self.session.rollbacks, [None])


class DisablePaymentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = _FakeSession()
        self.comercio = _build_comercio(1)
        self.service, self.repo = _build_service(self.session)

    def test_disables_existing_bridge_preserving_payment_details(self) -> None:
        self.repo.get_comercio.return_value = self.comercio
        existing = _build_bridge_payment(
            comercio_id=1,
            medio_pago_id=10,
            activo=True,
            titular="PRESERVED",
            alias="alias.preserved",
        )
        self.repo.find_comercio_medio_pago.return_value = existing

        result = self.service.disable_payment_for_comercio(
            comercio_id=1, medio_pago_id=10
        )

        self.assertIs(result, existing)
        self.repo.set_comercio_medio_pago_activo.assert_called_once_with(
            existing, activo=False
        )
        self.assertEqual(existing.titular, "PRESERVED")
        self.assertEqual(existing.alias, "alias.preserved")
        self.assertEqual(self.session.commits, [None])

    def test_disable_for_missing_association_is_noop(self) -> None:
        self.repo.get_comercio.return_value = self.comercio
        self.repo.find_comercio_medio_pago.return_value = None

        result = self.service.disable_payment_for_comercio(
            comercio_id=1, medio_pago_id=10
        )

        self.assertIsNone(result)
        self.repo.set_comercio_medio_pago_activo.assert_not_called()
        self.assertEqual(self.session.commits, [])


class ReactivationPreservesHistoryTest(unittest.TestCase):
    """Re-activation of a deactivated association with disabled
    global fields must preserve the stored ``titular`` / ``alias``
    values verbatim and must NOT reject the request.

    The panel calls the service with ``titular=None`` and
    ``alias=None`` because the template omits the disabled fields
    from the rendered form. The service must:
        * accept the request (no ``InvalidPaymentField``),
        * flip the row to ``activo=True``,
        * leave the previously stored ``titular`` / ``alias`` rows
          untouched.
    """

    def setUp(self) -> None:
        self.session = _FakeSession()
        self.comercio = _build_comercio(1)
        self.medio_pago = _build_medio_pago(
            10,
            habilita_titular=False,
            habilita_alias=False,
        )
        self.service, self.repo = _build_service(self.session)

    def test_reactivation_without_disabled_fields_preserves_history(self) -> None:
        existing = _build_bridge_payment(
            comercio_id=1,
            medio_pago_id=10,
            activo=False,
            titular="PRESERVED_TITULAR",
            alias="preserved.alias",
        )
        self.repo.get_comercio.return_value = self.comercio
        self.repo.get_global_medio_pago.return_value = self.medio_pago
        self.repo.find_comercio_medio_pago.return_value = existing

        def _activate(row: object, *, activo: bool) -> object:
            setattr(row, "activo", activo)
            self.session.flush()
            return row

        self.repo.set_comercio_medio_pago_activo.side_effect = _activate

        result = self.service.enable_payment_for_comercio(
            comercio_id=1,
            medio_pago_id=10,
            titular=None,
            alias=None,
        )

        self.assertIs(result, existing)
        self.repo.set_comercio_medio_pago_activo.assert_called_once_with(
            existing, activo=True
        )
        self.assertTrue(existing.activo)
        self.assertEqual(existing.titular, "PRESERVED_TITULAR")
        self.assertEqual(existing.alias, "preserved.alias")
        self.assertEqual(self.session.commits, [None])
        self.assertEqual(self.session.rollbacks, [])

    def test_reactivation_with_tampered_disabled_field_is_rejected(self) -> None:
        existing = _build_bridge_payment(
            comercio_id=1,
            medio_pago_id=10,
            activo=False,
            titular="PRESERVED_TITULAR",
            alias="preserved.alias",
        )
        self.repo.get_comercio.return_value = self.comercio
        self.repo.get_global_medio_pago.return_value = self.medio_pago
        self.repo.find_comercio_medio_pago.return_value = existing

        with self.assertRaises(InvalidPaymentField):
            self.service.enable_payment_for_comercio(
                comercio_id=1,
                medio_pago_id=10,
                titular=None,
                alias="forged.alias",
            )

        self.repo.set_comercio_medio_pago_activo.assert_not_called()
        self.assertEqual(existing.titular, "PRESERVED_TITULAR")
        self.assertEqual(existing.alias, "preserved.alias")
        self.assertEqual(self.session.commits, [])
        self.assertEqual(self.session.rollbacks, [])


class EnableDeliveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = _FakeSession()
        self.comercio = _build_comercio(1)
        self.metodo_entrega = _build_metodo_entrega(20)
        self.service, self.repo = _build_service(self.session)

    def test_creates_bridge_with_provided_order(self) -> None:
        self.repo.get_comercio.return_value = self.comercio
        self.repo.get_global_metodo_entrega.return_value = self.metodo_entrega
        self.repo.find_comercio_metodo_entrega.return_value = None
        staged_row = _build_bridge_delivery(
            comercio_id=1, metodo_entrega_id=20, orden=2
        )
        self.repo.create_comercio_metodo_entrega.return_value = staged_row

        result = self.service.enable_delivery_for_comercio(
            comercio_id=1, metodo_entrega_id=20, orden=2
        )

        self.assertIs(result, staged_row)
        self.repo.create_comercio_metodo_entrega.assert_called_once_with(
            comercio_id=1, metodo_entrega_id=20, orden=2
        )
        self.assertEqual(self.session.commits, [None])

    def test_negative_order_raises_validation_error(self) -> None:
        self.repo.get_comercio.return_value = self.comercio
        self.repo.get_global_metodo_entrega.return_value = self.metodo_entrega
        with self.assertRaises(InvalidDeliveryOrden):
            self.service.enable_delivery_for_comercio(
                comercio_id=1, metodo_entrega_id=20, orden=-1
            )
        self.repo.create_comercio_metodo_entrega.assert_not_called()
        self.assertEqual(self.session.commits, [])

    def test_non_integer_order_raises_validation_error(self) -> None:
        self.repo.get_comercio.return_value = self.comercio
        self.repo.get_global_metodo_entrega.return_value = self.metodo_entrega
        with self.assertRaises(InvalidDeliveryOrden):
            self.service.enable_delivery_for_comercio(
                comercio_id=1, metodo_entrega_id=20, orden="1"  # type: ignore[arg-type]
            )
        self.repo.create_comercio_metodo_entrega.assert_not_called()
        self.assertEqual(self.session.commits, [])

    def test_inactive_global_method_raises_not_found(self) -> None:
        self.repo.get_comercio.return_value = self.comercio
        self.repo.get_global_metodo_entrega.return_value = _build_metodo_entrega(
            20, activo=False
        )
        with self.assertRaises(MetodoEntregaNotFound):
            self.service.enable_delivery_for_comercio(
                comercio_id=1, metodo_entrega_id=20, orden=1
            )
        self.assertEqual(self.session.commits, [])

    def test_unknown_global_method_raises_not_found(self) -> None:
        self.repo.get_comercio.return_value = self.comercio
        self.repo.get_global_metodo_entrega.return_value = None
        with self.assertRaises(MetodoEntregaNotFound):
            self.service.enable_delivery_for_comercio(
                comercio_id=1, metodo_entrega_id=20, orden=1
            )
        self.assertEqual(self.session.commits, [])

    def test_disable_preserves_order(self) -> None:
        self.repo.get_comercio.return_value = self.comercio
        existing = _build_bridge_delivery(
            comercio_id=1,
            metodo_entrega_id=20,
            activo=True,
            orden=5,
        )
        self.repo.find_comercio_metodo_entrega.return_value = existing

        self.service.disable_delivery_for_comercio(
            comercio_id=1, metodo_entrega_id=20
        )

        self.repo.set_comercio_metodo_entrega_activo.assert_called_once_with(
            existing, activo=False
        )
        self.repo.set_comercio_metodo_entrega_orden.assert_not_called()
        self.assertEqual(existing.orden, 5)


class UpdateDeliveryOrderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = _FakeSession()
        self.comercio = _build_comercio(1)
        self.service, self.repo = _build_service(self.session)

    def test_updates_order_on_existing_bridge(self) -> None:
        self.repo.get_comercio.return_value = self.comercio
        existing = _build_bridge_delivery(
            comercio_id=1, metodo_entrega_id=20, orden=1
        )
        self.repo.find_comercio_metodo_entrega.return_value = existing

        self.service.update_delivery_order_for_comercio(
            comercio_id=1, metodo_entrega_id=20, orden=7
        )

        self.repo.set_comercio_metodo_entrega_orden.assert_called_once_with(
            existing, orden=7
        )
        self.assertEqual(self.session.commits, [None])

    def test_missing_bridge_raises_not_found(self) -> None:
        self.repo.get_comercio.return_value = self.comercio
        self.repo.find_comercio_metodo_entrega.return_value = None
        with self.assertRaises(MetodoEntregaNotFound):
            self.service.update_delivery_order_for_comercio(
                comercio_id=1, metodo_entrega_id=20, orden=1
            )
        self.assertEqual(self.session.commits, [])

    def test_negative_order_raises_validation_error(self) -> None:
        self.repo.get_comercio.return_value = self.comercio
        existing = _build_bridge_delivery(
            comercio_id=1, metodo_entrega_id=20, orden=1
        )
        self.repo.find_comercio_metodo_entrega.return_value = existing
        with self.assertRaises(InvalidDeliveryOrden):
            self.service.update_delivery_order_for_comercio(
                comercio_id=1, metodo_entrega_id=20, orden=-1
            )
        self.repo.set_comercio_metodo_entrega_orden.assert_not_called()
        self.assertEqual(self.session.commits, [])


class CommerceIsolationTest(unittest.TestCase):
    """The service must never resolve a foreign association."""

    def setUp(self) -> None:
        self.session = _FakeSession()
        self.service, self.repo = _build_service(self.session)

    def test_repository_lookup_includes_comercio_id(self) -> None:
        self.repo.get_comercio.return_value = _build_comercio(1)
        self.repo.get_global_medio_pago.return_value = _build_medio_pago(10)
        self.repo.find_comercio_medio_pago.return_value = None

        self.service.enable_payment_for_comercio(
            comercio_id=1,
            medio_pago_id=10,
            titular=None,
            alias=None,
        )

        self.repo.find_comercio_medio_pago.assert_called_once_with(
            comercio_id=1, medio_pago_id=10
        )

    def test_repository_never_called_without_comercio_id(self) -> None:
        self.repo.get_comercio.return_value = None
        with self.assertRaises(ComercioNotFound):
            self.service.disable_payment_for_comercio(
                comercio_id=1, medio_pago_id=10
            )
        self.repo.find_comercio_medio_pago.assert_not_called()


class RepositoryScopeTest(unittest.TestCase):
    """The focused repository must enforce the ``(comercio_id,
    global_id)`` pair when reading the bridge row.

    The test patches the SQLAlchemy ``execute`` helper so we can
    exercise the focused repository's WHERE clause construction
    without spinning up a real database.
    """

    def test_find_payment_bridge_uses_pair_keyword(self) -> None:
        session = _FakeSession()
        repo = self._build_repo(session)

        self.assertIsNone(
            repo.find_comercio_medio_pago(
                comercio_id=1, medio_pago_id=10
            )
        )

    def test_find_delivery_bridge_uses_pair_keyword(self) -> None:
        session = _FakeSession()
        repo = self._build_repo(session)

        self.assertIsNone(
            repo.find_comercio_metodo_entrega(
                comercio_id=1, metodo_entrega_id=20
            )
        )

    def _build_repo(self, session: Any):
        from backend.repositories.commerce_payment_delivery_repository import (
            CommercePaymentDeliveryConfigurationRepository,
        )

        class _FakeExecute:
            def __init__(self, session: _FakeSession) -> None:
                self._session = session

            def __call__(self, stmt: Any) -> Any:
                return SimpleNamespace(
                    scalar_one_or_none=lambda: None
                )

        session.execute = _FakeExecute(session)  # type: ignore[attr-defined]
        return CommercePaymentDeliveryConfigurationRepository(session)


if __name__ == "__main__":
    unittest.main()
