"""Service-level tests for ``PedidoProductoService``.

These tests cover the modern ``agregar_producto`` caller-owned
seam :meth:`PedidoProductoService.stage_add_or_increment_for_session`
and the supporting repository helpers. They use ``MagicMock`` for
the SQLAlchemy session so no real database is touched and every
guarded branch can be exercised deterministically.

Each test asserts:

* the typed business outcome is one of the documented closed
  reasons;
* the seam never invokes ``commit`` / ``rollback`` / ``flush`` /
  ``refresh`` / ``begin`` / ``close`` on the session;
* the legacy ``add_or_increment`` contract is untouched.
"""
from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as SqlSession

from backend.models import EstadoPedido
from backend.models.session import EstadoSession
from backend.services import pedido_producto_service as service_module
from backend.services.pedido_producto_service import PedidoProductoService
from backend.services.product_add_result import (
    REJECTED_INVALID_INPUT,
    REJECTED_MISSING_PRESENTATION,
    REJECTED_NOT_EDITABLE,
    REJECTED_PRICE_UNAVAILABLE,
    REJECTED_SESSION_OR_PEDIDO,
    STATUS_EXECUTED,
    STATUS_REJECTED,
    ProductAddResult,
)


def _session_stub() -> MagicMock:
    session = MagicMock(spec=SqlSession, name="DatabaseSession")
    session.commit = MagicMock(name="commit")
    session.rollback = MagicMock(name="rollback")
    session.flush = MagicMock(name="flush")
    session.refresh = MagicMock(name="refresh")
    session.begin = MagicMock(name="begin")
    session.close = MagicMock(name="close")
    session.expire = MagicMock(name="expire")
    return session


def _assert_no_transaction_control(session: MagicMock) -> None:
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.flush.assert_not_called()
    session.refresh.assert_not_called()
    session.begin.assert_not_called()
    session.close.assert_not_called()
    session.expire.assert_not_called()


def _pedido(estado_borrador: bool, session_id: int = 7) -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        id_session=session_id,
        estado_pedido=(
            EstadoPedido.BORRADOR if estado_borrador else EstadoPedido.INGRESADO
        ),
    )


def _session_row(
    *,
    session_id: int = 7,
    activa: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=session_id,
        estado_session=EstadoSession.ACTIVA if activa else EstadoSession.CERRADA,
    )


def _precio(value: Decimal) -> SimpleNamespace:
    return SimpleNamespace(precio=value)


class StageAddOrIncrementInvalidInputTest(unittest.TestCase):
    """The seam must reject bad inputs before touching the
    repository."""

    def setUp(self) -> None:
        self.session = _session_stub()

    def test_bool_cantidad_is_rejected(self) -> None:
        service = PedidoProductoService(self.session)
        result = service.stage_add_or_increment_for_session(
            session_id=7,
            pedido_id=42,
            id_producto_presentacion=99,
            cantidad=True,
        )
        self.assertEqual(
            result,
            ProductAddResult(
                status=STATUS_REJECTED, reason=REJECTED_INVALID_INPUT
            ),
        )
        _assert_no_transaction_control(self.session)

    def test_non_positive_cantidad_is_rejected(self) -> None:
        service = PedidoProductoService(self.session)
        for bad in (0, -1):
            result = service.stage_add_or_increment_for_session(
                session_id=7,
                pedido_id=42,
                id_producto_presentacion=99,
                cantidad=bad,
            )
            self.assertEqual(result.reason, REJECTED_INVALID_INPUT)
        _assert_no_transaction_control(self.session)

    def test_bool_pp_id_is_rejected(self) -> None:
        service = PedidoProductoService(self.session)
        result = service.stage_add_or_increment_for_session(
            session_id=7,
            pedido_id=42,
            id_producto_presentacion=True,
            cantidad=1,
        )
        self.assertEqual(result.reason, REJECTED_INVALID_INPUT)
        _assert_no_transaction_control(self.session)

    def test_non_positive_pp_id_is_rejected(self) -> None:
        service = PedidoProductoService(self.session)
        result = service.stage_add_or_increment_for_session(
            session_id=7,
            pedido_id=42,
            id_producto_presentacion=0,
            cantidad=1,
        )
        self.assertEqual(result.reason, REJECTED_INVALID_INPUT)
        _assert_no_transaction_control(self.session)


class StageAddOrIncrementSessionValidationTest(unittest.TestCase):
    """The seam must validate that the conversation session
    exists and is in ``EstadoSession.ACTIVA`` before any other
    step."""

    def setUp(self) -> None:
        self.session = _session_stub()

    def test_missing_session_is_rejected(self) -> None:
        with patch.object(service_module, "PedidoProductoRepository") as repo_cls:
            repo = MagicMock()
            repo_cls.return_value = repo
            repo.session.return_value = None

            service = PedidoProductoService(self.session)
            result = service.stage_add_or_increment_for_session(
                session_id=7,
                pedido_id=42,
                id_producto_presentacion=99,
                cantidad=1,
            )
        self.assertEqual(result.reason, REJECTED_SESSION_OR_PEDIDO)
        self.assertEqual(result.status, STATUS_REJECTED)
        repo.pedido.assert_not_called()
        repo.producto_presentacion_exists.assert_not_called()
        repo.stage_increment_existing_line.assert_not_called()
        repo.stage_create_with_price_snapshot_no_flush.assert_not_called()
        _assert_no_transaction_control(self.session)

    def test_closed_session_is_rejected(self) -> None:
        with patch.object(service_module, "PedidoProductoRepository") as repo_cls:
            repo = MagicMock()
            repo_cls.return_value = repo
            repo.session.return_value = _session_row(activa=False)

            service = PedidoProductoService(self.session)
            result = service.stage_add_or_increment_for_session(
                session_id=7,
                pedido_id=42,
                id_producto_presentacion=99,
                cantidad=1,
            )
        self.assertEqual(result.reason, REJECTED_SESSION_OR_PEDIDO)
        self.assertEqual(result.status, STATUS_REJECTED)
        repo.pedido.assert_not_called()
        repo.producto_presentacion_exists.assert_not_called()
        repo.stage_increment_existing_line.assert_not_called()
        repo.stage_create_with_price_snapshot_no_flush.assert_not_called()
        _assert_no_transaction_control(self.session)


class StageAddOrIncrementSessionOrPedidoTest(unittest.TestCase):
    """The seam rejects when the pedido is missing or foreign."""

    def setUp(self) -> None:
        self.session = _session_stub()

    def test_missing_pedido_is_rejected(self) -> None:
        with patch.object(service_module, "PedidoProductoRepository") as repo_cls:
            repo = MagicMock()
            repo_cls.return_value = repo
            repo.session.return_value = _session_row()
            repo.pedido.return_value = None

            service = PedidoProductoService(self.session)
            result = service.stage_add_or_increment_for_session(
                session_id=7,
                pedido_id=42,
                id_producto_presentacion=99,
                cantidad=1,
            )
        self.assertEqual(result.reason, REJECTED_SESSION_OR_PEDIDO)
        self.assertEqual(result.status, STATUS_REJECTED)
        _assert_no_transaction_control(self.session)

    def test_pedido_owned_by_other_session_is_rejected(self) -> None:
        with patch.object(service_module, "PedidoProductoRepository") as repo_cls:
            repo = MagicMock()
            repo_cls.return_value = repo
            repo.session.return_value = _session_row()
            repo.pedido.return_value = _pedido(
                estado_borrador=True, session_id=99
            )

            service = PedidoProductoService(self.session)
            result = service.stage_add_or_increment_for_session(
                session_id=7,
                pedido_id=42,
                id_producto_presentacion=99,
                cantidad=1,
            )
        self.assertEqual(result.reason, REJECTED_SESSION_OR_PEDIDO)
        _assert_no_transaction_control(self.session)


class StageAddOrIncrementNotEditableTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = _session_stub()

    def test_non_borrador_pedido_is_rejected(self) -> None:
        with patch.object(service_module, "PedidoProductoRepository") as repo_cls:
            repo = MagicMock()
            repo_cls.return_value = repo
            repo.session.return_value = _session_row()
            repo.pedido.return_value = _pedido(estado_borrador=False)

            service = PedidoProductoService(self.session)
            result = service.stage_add_or_increment_for_session(
                session_id=7,
                pedido_id=42,
                id_producto_presentacion=99,
                cantidad=1,
            )
        self.assertEqual(result.reason, REJECTED_NOT_EDITABLE)
        _assert_no_transaction_control(self.session)


class StageAddOrIncrementMissingPresentationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = _session_stub()

    def test_missing_presentation_is_rejected(self) -> None:
        with patch.object(service_module, "PedidoProductoRepository") as repo_cls:
            repo = MagicMock()
            repo_cls.return_value = repo
            repo.session.return_value = _session_row()
            repo.pedido.return_value = _pedido(estado_borrador=True)
            repo.producto_presentacion_exists.return_value = False

            service = PedidoProductoService(self.session)
            result = service.stage_add_or_increment_for_session(
                session_id=7,
                pedido_id=42,
                id_producto_presentacion=99,
                cantidad=1,
            )
        self.assertEqual(result.reason, REJECTED_MISSING_PRESENTATION)
        _assert_no_transaction_control(self.session)


class StageAddOrIncrementPriceUnavailableTest(unittest.TestCase):
    """Zero or multiple current prices must produce a deterministic
    ``rejected_price_unavailable`` business outcome without
    mutating state."""

    def setUp(self) -> None:
        self.session = _session_stub()

    def test_zero_prices_is_rejected(self) -> None:
        with patch.object(service_module, "PedidoProductoRepository") as repo_cls:
            repo = MagicMock()
            repo_cls.return_value = repo
            repo.session.return_value = _session_row()
            repo.pedido.return_value = _pedido(estado_borrador=True)
            repo.producto_presentacion_exists.return_value = True
            repo.current_precio_count.return_value = 0

            service = PedidoProductoService(self.session)
            result = service.stage_add_or_increment_for_session(
                session_id=7,
                pedido_id=42,
                id_producto_presentacion=99,
                cantidad=1,
            )
        self.assertEqual(result.reason, REJECTED_PRICE_UNAVAILABLE)
        self.assertEqual(result.status, STATUS_REJECTED)
        repo.stage_increment_existing_line.assert_not_called()
        repo.stage_create_with_price_snapshot_no_flush.assert_not_called()
        repo.current_precio.assert_not_called()
        _assert_no_transaction_control(self.session)

    def test_multiple_prices_is_rejected(self) -> None:
        with patch.object(service_module, "PedidoProductoRepository") as repo_cls:
            repo = MagicMock()
            repo_cls.return_value = repo
            repo.session.return_value = _session_row()
            repo.pedido.return_value = _pedido(estado_borrador=True)
            repo.producto_presentacion_exists.return_value = True
            repo.current_precio_count.return_value = 2

            service = PedidoProductoService(self.session)
            result = service.stage_add_or_increment_for_session(
                session_id=7,
                pedido_id=42,
                id_producto_presentacion=99,
                cantidad=1,
            )
        self.assertEqual(result.reason, REJECTED_PRICE_UNAVAILABLE)
        repo.stage_increment_existing_line.assert_not_called()
        repo.stage_create_with_price_snapshot_no_flush.assert_not_called()
        repo.current_precio.assert_not_called()
        _assert_no_transaction_control(self.session)


class StageAddOrIncrementSuccessTest(unittest.TestCase):
    """A priced presentation must stage one line or increment
    without invoking transaction control."""

    def setUp(self) -> None:
        self.session = _session_stub()

    def test_increments_existing_line(self) -> None:
        with patch.object(service_module, "PedidoProductoRepository") as repo_cls:
            repo = MagicMock()
            repo_cls.return_value = repo
            repo.session.return_value = _session_row()
            repo.pedido.return_value = _pedido(estado_borrador=True)
            repo.producto_presentacion_exists.return_value = True
            repo.current_precio_count.return_value = 1
            repo.current_precio.return_value = _precio(Decimal("1500.00"))

            existing = SimpleNamespace(id=10, id_pedido=42, cantidad=2)

            def _simulate_increment(
                *, pedido_id: int, id_producto_presentacion: int, cantidad: int
            ):
                existing.cantidad = existing.cantidad + cantidad
                return existing

            repo.stage_increment_existing_line.side_effect = _simulate_increment
            repo.stage_create_with_price_snapshot_no_flush.return_value = (
                SimpleNamespace(cantidad=1)
            )

            service = PedidoProductoService(self.session)
            result = service.stage_add_or_increment_for_session(
                session_id=7,
                pedido_id=42,
                id_producto_presentacion=99,
                cantidad=3,
            )
        self.assertEqual(result.status, STATUS_EXECUTED)
        self.assertFalse(result.linea_creada)
        self.assertEqual(result.cantidad_final, 5)
        self.assertEqual(result.precio_unitario, Decimal("1500.00"))
        repo.stage_increment_existing_line.assert_called_once_with(
            pedido_id=42, id_producto_presentacion=99, cantidad=3
        )
        repo.stage_create_with_price_snapshot_no_flush.assert_not_called()
        _assert_no_transaction_control(self.session)

    def test_creates_new_line_with_price_snapshot(self) -> None:
        with patch.object(service_module, "PedidoProductoRepository") as repo_cls:
            repo = MagicMock()
            repo_cls.return_value = repo
            repo.session.return_value = _session_row()
            repo.pedido.return_value = _pedido(estado_borrador=True)
            repo.producto_presentacion_exists.return_value = True
            repo.current_precio_count.return_value = 1
            repo.current_precio.return_value = _precio(Decimal("2200.50"))
            repo.stage_increment_existing_line.return_value = None
            repo.stage_create_with_price_snapshot_no_flush.return_value = (
                SimpleNamespace(cantidad=1)
            )

            service = PedidoProductoService(self.session)
            result = service.stage_add_or_increment_for_session(
                session_id=7,
                pedido_id=42,
                id_producto_presentacion=99,
                cantidad=1,
            )
        self.assertEqual(result.status, STATUS_EXECUTED)
        self.assertTrue(result.linea_creada)
        self.assertEqual(result.cantidad_final, 1)
        self.assertEqual(result.precio_unitario, Decimal("2200.50"))
        repo.stage_increment_existing_line.assert_called_once_with(
            pedido_id=42, id_producto_presentacion=99, cantidad=1
        )
        repo.stage_create_with_price_snapshot_no_flush.assert_called_once()
        kwargs = repo.stage_create_with_price_snapshot_no_flush.call_args.kwargs
        self.assertEqual(kwargs["precio_unitario"], Decimal("2200.50"))
        _assert_no_transaction_control(self.session)


class LegacyAddOrIncrementUnchangedTest(unittest.TestCase):
    """The legacy public ``add_or_increment`` method must remain
    untouched: it still owns the transaction and still raises the
    legacy sentinels for the existing callers."""

    def setUp(self) -> None:
        self.session = _session_stub()

    def test_legacy_add_or_increment_still_owns_commit(self) -> None:
        with patch.object(service_module, "PedidoProductoRepository") as repo_cls:
            repo = MagicMock()
            repo_cls.return_value = repo
            repo.pedido.return_value = _pedido(estado_borrador=True)
            repo.producto_presentacion_exists.return_value = True
            existing = SimpleNamespace(cantidad=1)
            repo.get_by_pedido_and_producto_presentacion.return_value = existing
            repo.current_precio.return_value = _precio(Decimal("100.00"))

            service = PedidoProductoService(self.session)
            service.add_or_increment(
                pedido_id=42,
                id_producto_presentacion=99,
                cantidad=1,
                observaciones=None,
            )
        self.session.commit.assert_called()
        self.session.flush.assert_called()


if __name__ == "__main__":
    unittest.main()