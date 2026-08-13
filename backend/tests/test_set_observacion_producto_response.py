"""Focused tests for the `set_observacion_producto` response builder.

The builder must render a deterministic Spanish message for every
status outcome. The rendered message must never echo the observation
text, the database id, the session id, or the classifier debug
information. The builder must short-circuit on any other intent.
"""
import importlib
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.responses import (
    set_observacion_producto_response as response_module,
)
from backend.intents.responses.set_observacion_producto_response import (
    build_set_observacion_producto_response,
)
from backend.intents.schemas.customer_response import CustomerResponse
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession


def _ready_intent(
    *,
    status: str = "executed",
    observation_action: str | None = "set",
    producto_nombre: str | None = "Pizza Mozzarella",
    presentacion_codigo: str | None = "grande",
    observation_text: str | None = "sec-secret-text",
    candidate_ids: list[int] | None = None,
) -> ProcessedIntent:
    literal_status: str = (
        status
        if status in {
            "pending_resolution",
            "ready",
            "executed",
            "rejected",
            "failed",
        }
        else "pending_resolution"
    )
    resolved_data: dict = {
        "observation_action": observation_action,
    }
    if observation_text is not None:
        resolved_data["observation_text"] = observation_text
    if producto_nombre is not None:
        resolved_data["producto_nombre"] = producto_nombre
    if presentacion_codigo is not None:
        resolved_data["presentacion_codigo"] = presentacion_codigo
    return ProcessedIntent(
        intent="set_observacion_producto",
        source_text="x",
        status=literal_status,  # type: ignore[arg-type]
        recognizer="recognizer_set_observacion_producto",
        handler="set_observacion_producto",
        resolved_data=resolved_data,
        candidate_ids=list(candidate_ids) if candidate_ids is not None else [],
    )


def _pp_label(pp_id: int, nombre: str, codigo: str) -> MagicMock:
    pp = MagicMock(id=pp_id)
    pp_assoc = pp.producto_presentacion
    presentacion = pp_assoc.presentacion
    presentacion.codigo = codigo
    presentacion.descripcion = codigo
    producto = pp_assoc.producto
    producto.nombre = nombre
    return pp


class SetObservacionProductoResponseBuilderExecutedTest(unittest.TestCase):
    def test_set_renders_confirmation_without_text(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _ready_intent(
            status="executed",
            observation_action="set",
            observation_text="sec-secret-text",
            producto_nombre="Pizza Mozzarella",
            presentacion_codigo="grande",
        )

        result = build_set_observacion_producto_response(db, session, intent)

        self.assertEqual(result.intent, "set_observacion_producto")
        self.assertEqual(result.status, "executed")
        self.assertEqual(
            result.message,
            "Actualicé la aclaración de Pizza Mozzarella (grande).",
        )
        self.assertNotIn("sec-secret-text", result.message)

    def test_clear_renders_removal_message(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _ready_intent(
            status="executed",
            observation_action="clear",
            observation_text=None,
            producto_nombre="Pizza Mozzarella",
            presentacion_codigo="grande",
        )

        result = build_set_observacion_producto_response(db, session, intent)

        self.assertEqual(result.intent, "set_observacion_producto")
        self.assertEqual(result.status, "executed")
        self.assertEqual(
            result.message,
            "Eliminé la aclaración de Pizza Mozzarella (grande).",
        )

    def test_missing_labels_render_failed_message(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _ready_intent(
            status="executed",
            observation_action="set",
            producto_nombre=None,
            presentacion_codigo=None,
        )

        result = build_set_observacion_producto_response(db, session, intent)

        self.assertEqual(result.status, "executed")
        self.assertIn("no pude", result.message.lower())


class SetObservacionProductoResponseBuilderPendingTest(unittest.TestCase):
    def test_two_candidates_render_as_documented(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 1

        pp_a = _pp_label(10, "Pizza de Muzzarella Grande", "grande")
        pp_b = _pp_label(11, "Pizza Napolitana Grande", "grande")

        with patch.object(
            response_module, "PedidoProductoService"
        ) as service_cls:
            service_cls.return_value.list_by_pedido.return_value = [pp_a, pp_b]
            intent = _ready_intent(
                status="pending_resolution",
                candidate_ids=[10, 11],
            )
            result = build_set_observacion_producto_response(
                db, session, intent
            )

        self.assertEqual(
            result.message,
            "¿Cuál querés modificar: Pizza de Muzzarella Grande (grande) "
            "o Pizza Napolitana Grande (grande)?",
        )
        self.assertEqual(result.intent, "set_observacion_producto")
        self.assertEqual(result.status, "pending_resolution")

    def test_three_candidates_join_with_o(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 1

        pps = [
            _pp_label(10, "A", "x"),
            _pp_label(11, "B", "x"),
            _pp_label(12, "C", "x"),
        ]
        with patch.object(
            response_module, "PedidoProductoService"
        ) as service_cls:
            service_cls.return_value.list_by_pedido.return_value = pps
            intent = _ready_intent(
                status="pending_resolution", candidate_ids=[10, 11, 12]
            )
            result = build_set_observacion_producto_response(
                db, session, intent
            )

        self.assertEqual(
            result.message,
            "¿Cuál querés modificar: A (x) o B (x) o C (x)?",
        )


class SetObservacionProductoResponseBuilderRejectedTest(unittest.TestCase):
    def test_rejected_renders_absent_message(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _ready_intent(status="rejected")

        result = build_set_observacion_producto_response(db, session, intent)

        self.assertEqual(result.intent, "set_observacion_producto")
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.message, "Ese producto no está en tu pedido.")

    def test_rejected_does_not_echo_observation_text(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _ready_intent(
            status="rejected",
            observation_text="sec-secret-text",
        )

        result = build_set_observacion_producto_response(db, session, intent)

        self.assertNotIn("sec-secret-text", result.message)


class SetObservacionProductoResponseBuilderFailedTest(unittest.TestCase):
    def test_failed_renders_failed_message(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = _ready_intent(status="failed")

        result = build_set_observacion_producto_response(db, session, intent)

        self.assertEqual(result.intent, "set_observacion_producto")
        self.assertEqual(result.status, "failed")
        self.assertEqual(
            result.message,
            "No pude procesar tu pedido. Intentá de nuevo en un momento.",
        )


class SetObservacionProductoResponseBuilderWrongIntentTest(unittest.TestCase):
    def test_unrelated_intent_returns_failed_message(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        intent = ProcessedIntent(
            intent="quitar_producto",
            source_text="x",
            status="executed",
            recognizer="recognizer_quitar_producto",
            handler="quitar_producto",
        )

        result = build_set_observacion_producto_response(db, session, intent)

        self.assertEqual(result.intent, "quitar_producto")
        self.assertEqual(result.status, "executed")
        self.assertIn("no pude", result.message.lower())


class SetObservacionProductoResponseBuilderBoundariesTest(unittest.TestCase):
    def test_module_does_not_import_llm(self):
        importlib.reload(response_module)
        with open(response_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "from backend.llm",
            "QueryLlm",
            "import requests",
            "from requests",
            "from backend.routers",
            "from backend.dependencies",
            "backend.old_project",
            "from backend.repositories",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_public_surface_is_limited(self):
        self.assertEqual(
            response_module.__all__,
            ["build_set_observacion_producto_response"],
        )


if __name__ == "__main__":
    unittest.main()
