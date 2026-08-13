"""Focused tests for the `set_observacion_producto` handler.

The handler must validate:

- active session state and a positive ``session.id_pedido``;
- the supplied ``pedido_producto_id`` is a positive integer;
- the local ``observation_action`` is exactly ``"set"`` or ``"clear"``;
- for ``set``, the ``observation_text`` is a non-empty trimmed string;
- the service seam's ownership/draft/line-membership invariants
  through typed exception → ``rejected`` translation;
- a successful set preserves the trimmed source text;
- a successful clear assigns ``None`` (explicit NULL assignment).
"""
import importlib
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.handlers import (
    set_observacion_producto_handler as handler_module,
)
from backend.intents.handlers.set_observacion_producto_handler import (
    execute_set_observacion_producto,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
from backend.models.session import EstadoSession, Session as ConversationSession
from backend.services.exceptions import (
    PedidoNotFound,
    PedidoProductoNotEditable,
    PedidoProductoNotFound,
    PedidoSessionMismatch,
)


def _ready_intent(
    *,
    pedido_producto_id: int | None = 10,
    observation_action: str | None = "set",
    observation_text: str | None = "La pizza es sin aceitunas",
    intent: str = "set_observacion_producto",
    handler: str = "set_observacion_producto",
    status: str = "ready",
) -> ProcessedIntent:
    literal_status = "ready" if status == "ready" else status
    resolved_data: dict = {
        "pedido_producto_id": pedido_producto_id,
        "observation_action": observation_action,
    }
    if observation_action == "set" and observation_text is not None:
        resolved_data["observation_text"] = observation_text
    return ProcessedIntent(
        intent=intent,
        source_text=observation_text or "x",
        status=literal_status,  # type: ignore[arg-type]
        recognizer="recognizer_set_observacion_producto",
        handler=handler,
        resolved_data=resolved_data,
        requirements=[
            RequirementState(
                name="pedido_producto_id",
                status="completed",
                value=pedido_producto_id,
            ),
            RequirementState(
                name="observacion",
                status="completed",
                value=observation_action,
            ),
        ],
        candidate_ids=[],
    )


def _session(
    *,
    pedido_id: int | None = 7,
    session_id: int = 1,
    estado: EstadoSession = EstadoSession.ACTIVA,
) -> MagicMock:
    s = MagicMock(spec=ConversationSession)
    s.id = session_id
    s.id_pedido = pedido_id
    s.estado_session = estado
    return s


class ExecuteSetObservacionProductoGuardsTest(unittest.TestCase):
    @patch.object(handler_module, "PedidoProductoService")
    def test_invalid_intent_returns_rejected(self, service_cls):
        service_cls.return_value = MagicMock()
        db = MagicMock(spec=DatabaseSession)
        session = _session()
        intent = _ready_intent(intent="quitar_producto", handler="quitar_producto")

        result = execute_set_observacion_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_non_ready_status_returns_rejected(self, service_cls):
        service_cls.return_value = MagicMock()
        db = MagicMock(spec=DatabaseSession)
        session = _session()
        intent = _ready_intent(status="pending_resolution")

        result = execute_set_observacion_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_invalid_handler_returns_rejected(self, service_cls):
        service_cls.return_value = MagicMock()
        db = MagicMock(spec=DatabaseSession)
        session = _session()
        intent = _ready_intent(handler="unknown")

        result = execute_set_observacion_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_non_integer_pedido_producto_id_returns_rejected(self, service_cls):
        service_cls.return_value = MagicMock()
        db = MagicMock(spec=DatabaseSession)
        session = _session()
        intent = ProcessedIntent(
            intent="set_observacion_producto",
            source_text="x",
            status="ready",
            recognizer="recognizer_set_observacion_producto",
            handler="set_observacion_producto",
            resolved_data={
                "pedido_producto_id": "not-int",
                "observation_action": "set",
                "observation_text": "x",
            },
            requirements=[
                RequirementState(
                    name="pedido_producto_id",
                    status="completed",
                    value="not-int",
                ),
                RequirementState(
                    name="observacion",
                    status="completed",
                    value="set",
                ),
            ],
        )

        result = execute_set_observacion_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_zero_pedido_producto_id_returns_rejected(self, service_cls):
        service_cls.return_value = MagicMock()
        db = MagicMock(spec=DatabaseSession)
        session = _session()
        intent = _ready_intent(pedido_producto_id=0)

        result = execute_set_observacion_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_missing_action_returns_rejected(self, service_cls):
        service_cls.return_value = MagicMock()
        db = MagicMock(spec=DatabaseSession)
        session = _session()
        intent = _ready_intent(observation_action=None)

        result = execute_set_observacion_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_set_without_text_returns_rejected(self, service_cls):
        service_cls.return_value = MagicMock()
        db = MagicMock(spec=DatabaseSession)
        session = _session()
        intent = _ready_intent(observation_action="set", observation_text=None)

        result = execute_set_observacion_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_set_with_blank_text_returns_rejected(self, service_cls):
        service_cls.return_value = MagicMock()
        db = MagicMock(spec=DatabaseSession)
        session = _session()
        intent = _ready_intent(observation_action="set", observation_text="   ")

        result = execute_set_observacion_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_inactive_session_returns_rejected(self, service_cls):
        service_cls.return_value = MagicMock()
        db = MagicMock(spec=DatabaseSession)
        session = _session(estado=EstadoSession.CERRADA)
        intent = _ready_intent()

        result = execute_set_observacion_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()

    @patch.object(handler_module, "PedidoProductoService")
    def test_missing_pedido_id_returns_rejected(self, service_cls):
        service_cls.return_value = MagicMock()
        db = MagicMock(spec=DatabaseSession)
        session = _session(pedido_id=None)
        intent = _ready_intent()

        result = execute_set_observacion_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")
        service_cls.assert_not_called()


class ExecuteSetObservacionProductoSetSuccessTest(unittest.TestCase):
    @patch.object(handler_module, "PedidoProductoService")
    def test_set_preserves_trimmed_source_text(self, service_cls):
        line = MagicMock(id=10)
        line.observaciones = None
        pp_assoc = line.producto_presentacion
        presentacion = pp_assoc.presentacion
        producto = pp_assoc.producto
        producto.nombre = "Pizza Mozzarella"
        presentacion.codigo = "grande"
        presentacion.descripcion = "Pizza grande"

        service = MagicMock()
        service.set_observacion_producto.return_value = line
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        session = _session()
        intent = _ready_intent(
            pedido_producto_id=10,
            observation_action="set",
            observation_text="  La pizza es sin aceitunas  ",
        )

        result = execute_set_observacion_producto(db, session, intent)

        self.assertEqual(result.status, "executed")
        self.assertEqual(result.resolved_data["observation_action"], "set")
        self.assertEqual(
            result.resolved_data["producto_nombre"], "Pizza Mozzarella"
        )
        self.assertEqual(
            result.resolved_data["presentacion_codigo"], "grande"
        )
        service.set_observacion_producto.assert_called_once_with(
            session_id=1,
            pedido_id=7,
            pedido_producto_id=10,
            observacion="La pizza es sin aceitunas",
        )


class ExecuteSetObservacionProductoClearSuccessTest(unittest.TestCase):
    @patch.object(handler_module, "PedidoProductoService")
    def test_clear_passes_none_observation(self, service_cls):
        line = MagicMock(id=10)
        line.observaciones = "stale-text"
        pp_assoc = line.producto_presentacion
        presentacion = pp_assoc.presentacion
        producto = pp_assoc.producto
        producto.nombre = "Pizza Mozzarella"
        presentacion.codigo = "grande"
        presentacion.descripcion = "Pizza grande"

        service = MagicMock()
        service.set_observacion_producto.return_value = line
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        session = _session()
        intent = _ready_intent(
            pedido_producto_id=10,
            observation_action="clear",
            observation_text=None,
        )

        result = execute_set_observacion_producto(db, session, intent)

        self.assertEqual(result.status, "executed")
        self.assertEqual(result.resolved_data["observation_action"], "clear")
        self.assertEqual(
            result.resolved_data["producto_nombre"], "Pizza Mozzarella"
        )
        service.set_observacion_producto.assert_called_once_with(
            session_id=1,
            pedido_id=7,
            pedido_producto_id=10,
            observacion=None,
        )


class ExecuteSetObservacionProductoOwnershipTest(unittest.TestCase):
    def _patch_service(self, service_cls, side_effect):
        service = MagicMock()
        service.set_observacion_producto.side_effect = side_effect
        service_cls.return_value = service

    @patch.object(handler_module, "PedidoProductoService")
    def test_foreign_pedido_returns_rejected(self, service_cls):
        self._patch_service(
            service_cls,
            PedidoSessionMismatch(99, 1),
        )
        db = MagicMock(spec=DatabaseSession)
        session = _session(pedido_id=99)
        intent = _ready_intent(pedido_producto_id=10)

        result = execute_set_observacion_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")

    @patch.object(handler_module, "PedidoProductoService")
    def test_missing_pedido_returns_rejected(self, service_cls):
        self._patch_service(service_cls, PedidoNotFound(7))
        db = MagicMock(spec=DatabaseSession)
        session = _session()
        intent = _ready_intent(pedido_producto_id=10)

        result = execute_set_observacion_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")

    @patch.object(handler_module, "PedidoProductoService")
    def test_non_borrador_pedido_returns_rejected(self, service_cls):
        self._patch_service(
            service_cls,
            PedidoProductoNotEditable(7, "confirmado"),
        )
        db = MagicMock(spec=DatabaseSession)
        session = _session()
        intent = _ready_intent(pedido_producto_id=10)

        result = execute_set_observacion_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")

    @patch.object(handler_module, "PedidoProductoService")
    def test_foreign_line_returns_rejected(self, service_cls):
        self._patch_service(service_cls, PedidoProductoNotFound(99))
        db = MagicMock(spec=DatabaseSession)
        session = _session()
        intent = _ready_intent(pedido_producto_id=99)

        result = execute_set_observacion_producto(db, session, intent)

        self.assertEqual(result.status, "rejected")

    @patch.object(handler_module, "PedidoProductoService")
    def test_unexpected_exception_propagates_to_outer_owner(self, service_cls):
        self._patch_service(service_cls, RuntimeError("boom"))
        db = MagicMock(spec=DatabaseSession)
        session = _session()
        intent = _ready_intent(pedido_producto_id=10)

        with self.assertRaises(RuntimeError):
            execute_set_observacion_producto(db, session, intent)


class ExecuteSetObservacionProductoBoundariesTest(unittest.TestCase):
    def test_module_does_not_import_disallowed_side_effects(self):
        importlib.reload(handler_module)
        with open(handler_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "db.commit",
            "db.rollback",
            "db.flush",
            "db.refresh",
            "db.expire",
            "db.begin",
            "db.close",
            "from sqlalchemy import select",
            "joinedload",
            "from backend.repositories",
            "from backend.routers",
            "from backend.llm",
            "backend.old_project",
            "HTTPException",
            "import requests",
            "from requests",
            "import fastapi",
            "from fastapi",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_public_surface_is_limited(self):
        self.assertEqual(
            handler_module.__all__,
            ["execute_set_observacion_producto"],
        )


if __name__ == "__main__":
    unittest.main()
