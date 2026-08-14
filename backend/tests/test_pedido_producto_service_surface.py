import importlib
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as SqlSession

from backend.repositories import (
    pedido_producto_repository as repo_module,
)
from backend.repositories.pedido_producto_repository import PedidoProductoRepository
from backend.services import pedido_producto_service as service_module
from backend.services.exceptions import PedidoProductoNotFound
from backend.services.pedido_producto_service import PedidoProductoService


class PedidoProductoRepositoryListByPedidoTest(unittest.TestCase):
    def test_repository_eager_loads_product_and_presentacion(self):
        session = MagicMock(spec=SqlSession)
        repo = PedidoProductoRepository(session)

        with patch.object(repo_module, "select") as select_mock:
            stmt_mock = MagicMock()
            select_mock.return_value = stmt_mock
            stmt_mock.where.return_value = stmt_mock
            stmt_mock.order_by.return_value = stmt_mock
            stmt_mock.options.return_value = stmt_mock
            scalars_mock = MagicMock()
            scalars_mock.unique.return_value = []
            session.execute.return_value.scalars.return_value = scalars_mock

            repo.list_by_pedido(7)

            select_mock.assert_called_once_with(repo_module.PedidoProducto)
            stmt_mock.options.assert_called_once()
            session.execute.assert_called_once()

    def test_repository_eager_loads_product_category(self):
        session = MagicMock(spec=SqlSession)
        repo = PedidoProductoRepository(session)

        chain_calls: list[int] = []

        class _ChainTracker:
            def __init__(self) -> None:
                self.depth = 0

            def joinedload(self, *_args, **_kwargs) -> "_ChainTracker":
                self.depth += 1
                return self

        tracker_a = _ChainTracker()
        tracker_b = _ChainTracker()

        def _joinedload_factory(_arg):
            if not chain_calls:
                chain_calls.append(0)
                return tracker_a
            chain_calls.append(1)
            return tracker_b

        with patch.object(repo_module, "joinedload", side_effect=_joinedload_factory):
            with patch.object(repo_module, "select") as select_mock:
                stmt_mock = MagicMock()
                select_mock.return_value = stmt_mock
                stmt_mock.where.return_value = stmt_mock
                stmt_mock.order_by.return_value = stmt_mock
                stmt_mock.options.return_value = stmt_mock
                scalars_mock = MagicMock()
                scalars_mock.unique.return_value = []
                session.execute.return_value.scalars.return_value = scalars_mock

                repo.list_by_pedido(7)

        self.assertEqual(tracker_a.depth, 2)
        self.assertEqual(tracker_b.depth, 1)
        self.assertEqual(len(chain_calls), 2)
        self.assertEqual(stmt_mock.options.call_count, 1)
        self.assertEqual(len(stmt_mock.options.call_args.args), 2)

    def test_repository_public_contract_is_unchanged(self):
        self.assertEqual(
            PedidoProductoRepository.list_by_pedido.__name__,
            "list_by_pedido",
        )


class PedidoProductoRepositoryGetForPedidoTest(unittest.TestCase):
    def test_returns_none_when_line_does_not_exist(self):
        session = MagicMock(spec=SqlSession)
        session.get.return_value = None
        repo = PedidoProductoRepository(session)

        result = repo.get_for_pedido(7, 99)

        self.assertIsNone(result)
        session.get.assert_called_once()

    def test_returns_none_when_line_belongs_to_other_pedido(self):
        session = MagicMock(spec=SqlSession)
        item = MagicMock(id_pedido=42)
        session.get.return_value = item
        repo = PedidoProductoRepository(session)

        result = repo.get_for_pedido(7, 99)

        self.assertIsNone(result)

    def test_returns_item_when_line_belongs_to_pedido(self):
        session = MagicMock(spec=SqlSession)
        item = MagicMock(id_pedido=7)
        session.get.return_value = item
        repo = PedidoProductoRepository(session)

        result = repo.get_for_pedido(7, 99)

        self.assertIs(result, item)


class PedidoProductoServiceListByPedidoTest(unittest.TestCase):
    def test_service_delegates_to_repository(self):
        session = MagicMock(spec=SqlSession)
        pedido = MagicMock()
        session.get.return_value = pedido

        with patch.object(service_module, "PedidoProductoRepository") as repo_cls:
            repo = MagicMock()
            repo_cls.return_value = repo
            repo.pedido.return_value = pedido
            repo.list_by_pedido.return_value = ["a", "b"]

            service = PedidoProductoService(session)
            result = service.list_by_pedido(7)

            repo.pedido.assert_called_once_with(7)
            repo.list_by_pedido.assert_called_once_with(7)
            self.assertEqual(result, ["a", "b"])


class PedidoProductoServiceGetForPedidoTest(unittest.TestCase):
    def test_get_for_pedido_raises_when_line_missing(self):
        session = MagicMock(spec=SqlSession)
        with patch.object(service_module, "PedidoProductoRepository") as repo_cls:
            repo = MagicMock()
            repo_cls.return_value = repo
            repo.get_for_pedido.return_value = None
            service = PedidoProductoService(session)

            with self.assertRaises(PedidoProductoNotFound):
                service.get_for_pedido(7, 99)

    def test_get_for_pedido_returns_item_when_present(self):
        session = MagicMock(spec=SqlSession)
        item = MagicMock(id_pedido=7, id=10)
        with patch.object(service_module, "PedidoProductoRepository") as repo_cls:
            repo = MagicMock()
            repo_cls.return_value = repo
            repo.get_for_pedido.return_value = item
            service = PedidoProductoService(session)

            result = service.get_for_pedido(7, 99)

            self.assertIs(result, item)


class PedidoProductoServiceUpdateDeleteGuardTest(unittest.TestCase):
    def test_update_enforces_borrador_only_guard(self):
        session = MagicMock(spec=SqlSession)
        service = PedidoProductoService(session)

        item = MagicMock(id_pedido=7, id=10)
        pedido = MagicMock(estado_pedido="confirmado")
        with patch.object(service_module, "PedidoProductoRepository") as repo_cls:
            repo = MagicMock()
            repo_cls.return_value = repo
            repo.get.return_value = item
            repo.pedido.return_value = pedido

            from backend.services.exceptions import PedidoProductoNotEditable
            with self.assertRaises(PedidoProductoNotEditable):
                service.update(10, cantidad=1, observaciones=None)

    def test_delete_enforces_borrador_only_guard(self):
        session = MagicMock(spec=SqlSession)
        service = PedidoProductoService(session)

        item = MagicMock(id_pedido=7, id=10)
        pedido = MagicMock(estado_pedido="confirmado")
        with patch.object(service_module, "PedidoProductoRepository") as repo_cls:
            repo = MagicMock()
            repo_cls.return_value = repo
            repo.get.return_value = item
            repo.pedido.return_value = pedido

            from backend.services.exceptions import PedidoProductoNotEditable
            with self.assertRaises(PedidoProductoNotEditable):
                service.delete(10)


if __name__ == "__main__":
    unittest.main()