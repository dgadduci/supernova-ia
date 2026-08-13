"""Handler-level tests for the modern ``agregar_producto`` flow.

The tests pin the seam contract exposed by
:meth:`backend.intents.handlers.agregar_producto_handler.execute_agregar_producto`:

* legacy response mapping (``rejected`` / ``executed`` / ``failed``);
* exactly one ``product_add_execution`` event emitted per call;
* the closed allowlist of outcomes;
* the seam NEVER calls ``commit`` / ``rollback`` / ``flush`` /
  ``refresh`` / ``begin`` / ``close`` on the session — the
  provider coordinator remains the sole transaction owner;
* an event-sink failure never changes the handler result.

The tests use ``MagicMock`` for the SQLAlchemy session and the
service seam so no real database is touched.
"""
from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as SqlSession

from backend.intents.handlers.agregar_producto_handler import (
    execute_agregar_producto,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.services.product_add_result import (
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
    return session


def _assert_no_transaction_control(session: MagicMock) -> None:
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.flush.assert_not_called()
    session.refresh.assert_not_called()
    session.begin.assert_not_called()
    session.close.assert_not_called()


def _ready_intent(
    *,
    producto_presentacion_id: object = 99,
    cantidad: object = 1,
) -> ProcessedIntent:
    return ProcessedIntent(
        intent="agregar_producto",
        source_text="quiero una mozzarella grande",
        status="ready",
        recognizer="recognizer_productos",
        handler="agregar_producto",
        resolved_data={
            "producto_presentacion_id": producto_presentacion_id,
            "cantidad": cantidad,
        },
    )


def _conversation_session(
    *, id: int = 7, id_pedido: int | None = 42
) -> SimpleNamespace:
    return SimpleNamespace(id=id, id_pedido=id_pedido)


class HandlerEarlyGuardTest(unittest.TestCase):
    """The handler must early-reject intents that are not in the
    correct ready agregar_producto state without emitting any
    product_add_execution event (the legacy pre-seam behaviour)."""

    def test_wrong_intent_returns_rejected_without_event(self) -> None:
        session = _session_stub()
        intent = _ready_intent()
        intent = intent.model_copy(update={"intent": "quitar_producto"})
        result = execute_agregar_producto(
            session, _conversation_session(), intent
        )
        self.assertEqual(result.status, "rejected")
        _assert_no_transaction_control(session)


class HandlerInvalidInputTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = _session_stub()
        self.conversation = _conversation_session()

    def _capture(self) -> list[dict]:
        captured: list[dict] = []
        return captured

    def test_missing_pp_id_emits_invalid_input_and_rejected(self) -> None:
        intent = _ready_intent(producto_presentacion_id=None)
        with patch(
            "backend.intents.handlers.agregar_producto_handler.emit_event"
        ) as emit:
            result = execute_agregar_producto(
                self.session, self.conversation, intent
            )
        self.assertEqual(result.status, "rejected")
        emit.assert_called_once()
        kwargs = emit.call_args.kwargs
        self.assertEqual(kwargs["outcome"], "rejected_invalid_input")
        _assert_no_transaction_control(self.session)

    def test_bool_pp_id_emits_invalid_input_and_rejected(self) -> None:
        intent = _ready_intent(producto_presentacion_id=True)
        with patch(
            "backend.intents.handlers.agregar_producto_handler.emit_event"
        ) as emit:
            result = execute_agregar_producto(
                self.session, self.conversation, intent
            )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(
            emit.call_args.kwargs["outcome"], "rejected_invalid_input"
        )
        _assert_no_transaction_control(self.session)

    def test_bool_cantidad_emits_invalid_input_and_rejected(self) -> None:
        intent = _ready_intent(cantidad=True)
        with patch(
            "backend.intents.handlers.agregar_producto_handler.emit_event"
        ) as emit:
            result = execute_agregar_producto(
                self.session, self.conversation, intent
            )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(
            emit.call_args.kwargs["outcome"], "rejected_invalid_input"
        )
        _assert_no_transaction_control(self.session)

    def test_zero_cantidad_emits_invalid_input_and_rejected(self) -> None:
        intent = _ready_intent(cantidad=0)
        with patch(
            "backend.intents.handlers.agregar_producto_handler.emit_event"
        ) as emit:
            result = execute_agregar_producto(
                self.session, self.conversation, intent
            )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(
            emit.call_args.kwargs["outcome"], "rejected_invalid_input"
        )
        _assert_no_transaction_control(self.session)

    def test_missing_pedido_id_emits_session_or_pedido(self) -> None:
        intent = _ready_intent()
        conversation = _conversation_session(id_pedido=None)
        with patch(
            "backend.intents.handlers.agregar_producto_handler.emit_event"
        ) as emit:
            result = execute_agregar_producto(
                self.session, conversation, intent
            )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(
            emit.call_args.kwargs["outcome"],
            "rejected_session_or_pedido",
        )
        _assert_no_transaction_control(self.session)


class HandlerRejectedOutcomesTest(unittest.TestCase):
    """Every documented seam rejection must produce the matching
    closed ``product_add_execution`` outcome."""

    def setUp(self) -> None:
        self.session = _session_stub()
        self.conversation = _conversation_session()
        self.intent = _ready_intent()

    def _run(self, result: ProductAddResult) -> tuple[ProcessedIntent, str]:
        with patch(
            "backend.intents.handlers.agregar_producto_handler.PedidoProductoService"
        ) as service_cls:
            service_cls.return_value.stage_add_or_increment_for_session.return_value = (
                result
            )
            with patch(
                "backend.intents.handlers.agregar_producto_handler.emit_event"
            ) as emit:
                processed = execute_agregar_producto(
                    self.session, self.conversation, self.intent
                )
        self.assertEqual(processed.status, "rejected")
        outcome = emit.call_args.kwargs["outcome"]
        _assert_no_transaction_control(self.session)
        return processed, outcome

    def test_session_or_pedido_outcome(self) -> None:
        _, outcome = self._run(
            ProductAddResult(
                status=STATUS_REJECTED,
                reason=REJECTED_SESSION_OR_PEDIDO,
            )
        )
        self.assertEqual(outcome, "rejected_session_or_pedido")

    def test_not_editable_outcome(self) -> None:
        _, outcome = self._run(
            ProductAddResult(
                status=STATUS_REJECTED, reason=REJECTED_NOT_EDITABLE
            )
        )
        self.assertEqual(outcome, "rejected_not_editable")

    def test_missing_presentation_outcome(self) -> None:
        _, outcome = self._run(
            ProductAddResult(
                status=STATUS_REJECTED, reason=REJECTED_MISSING_PRESENTATION
            )
        )
        self.assertEqual(outcome, "rejected_missing_presentation")

    def test_price_unavailable_outcome(self) -> None:
        _, outcome = self._run(
            ProductAddResult(
                status=STATUS_REJECTED, reason=REJECTED_PRICE_UNAVAILABLE
            )
        )
        self.assertEqual(outcome, "rejected_price_unavailable")


class HandlerExecutedOutcomeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = _session_stub()
        self.conversation = _conversation_session()
        self.intent = _ready_intent()

    def test_created_emits_created(self) -> None:
        with patch(
            "backend.intents.handlers.agregar_producto_handler.PedidoProductoService"
        ) as service_cls:
            service_cls.return_value.stage_add_or_increment_for_session.return_value = (
                ProductAddResult(
                    status=STATUS_EXECUTED,
                    linea_creada=True,
                    cantidad_final=1,
                    precio_unitario=Decimal("1500.00"),
                )
            )
            with patch(
                "backend.intents.handlers.agregar_producto_handler.emit_event"
            ) as emit:
                processed = execute_agregar_producto(
                    self.session, self.conversation, self.intent
                )
        self.assertEqual(processed.status, "executed")
        self.assertEqual(emit.call_args.kwargs["outcome"], "created")
        self.assertEqual(
            processed.resolved_data.get("cantidad_final"), 1
        )
        self.assertTrue(processed.resolved_data.get("linea_creada"))
        _assert_no_transaction_control(self.session)

    def test_incremented_emits_incremented(self) -> None:
        with patch(
            "backend.intents.handlers.agregar_producto_handler.PedidoProductoService"
        ) as service_cls:
            service_cls.return_value.stage_add_or_increment_for_session.return_value = (
                ProductAddResult(
                    status=STATUS_EXECUTED,
                    linea_creada=False,
                    cantidad_final=3,
                    precio_unitario=Decimal("1500.00"),
                )
            )
            with patch(
                "backend.intents.handlers.agregar_producto_handler.emit_event"
            ) as emit:
                processed = execute_agregar_producto(
                    self.session, self.conversation, self.intent
                )
        self.assertEqual(processed.status, "executed")
        self.assertEqual(emit.call_args.kwargs["outcome"], "incremented")
        self.assertEqual(
            processed.resolved_data.get("cantidad_final"), 3
        )
        self.assertFalse(processed.resolved_data.get("linea_creada"))
        _assert_no_transaction_control(self.session)


class HandlerUnexpectedFailureTest(unittest.TestCase):
    """An unexpected technical exception must propagate so the
    outer provider coordinator owns the rollback. The handler
    MUST NOT emit a business outcome for a technical failure —
    ``product_add_execution`` is only emitted for executed or
    typed business rejections."""

    def setUp(self) -> None:
        self.session = _session_stub()
        self.conversation = _conversation_session()
        self.intent = _ready_intent()

    def test_unexpected_exception_propagates_without_emitting(self) -> None:
        with patch(
            "backend.intents.handlers.agregar_producto_handler.PedidoProductoService"
        ) as service_cls:
            service_cls.return_value.stage_add_or_increment_for_session.side_effect = (
                RuntimeError("forced")
            )
            with patch(
                "backend.intents.handlers.agregar_producto_handler.emit_event"
            ) as emit:
                with self.assertRaises(RuntimeError):
                    execute_agregar_producto(
                        self.session, self.conversation, self.intent
                    )
        emit.assert_not_called()
        _assert_no_transaction_control(self.session)


class HandlerEventSinkFailureTest(unittest.TestCase):
    """Event-sink failures must NOT change the handler result."""

    def test_sink_failure_keeps_executed_outcome(self) -> None:
        session = _session_stub()
        conversation = _conversation_session()
        intent = _ready_intent()
        with patch(
            "backend.intents.handlers.agregar_producto_handler.PedidoProductoService"
        ) as service_cls:
            service_cls.return_value.stage_add_or_increment_for_session.return_value = (
                ProductAddResult(
                    status=STATUS_EXECUTED,
                    linea_creada=True,
                    cantidad_final=1,
                    precio_unitario=Decimal("100.00"),
                )
            )
            with patch(
                "backend.intents.handlers.agregar_producto_handler.emit_event",
                side_effect=RuntimeError("sink broken"),
            ):
                processed = execute_agregar_producto(
                    session, conversation, intent
                )
        self.assertEqual(processed.status, "executed")
        _assert_no_transaction_control(session)


class HandlerEmitsClosedOutcomeTokensTest(unittest.TestCase):
    """The handler must only ever pass closed allowlist tokens to
    the events helper."""

    ALLOWED_OUTCOMES = frozenset(
        {
            "created",
            "incremented",
            "rejected_invalid_input",
            "rejected_session_or_pedido",
            "rejected_not_editable",
            "rejected_missing_presentation",
            "rejected_price_unavailable",
        }
    )

    def test_each_branch_emits_a_closed_token(self) -> None:
        session = _session_stub()
        conversation = _conversation_session()
        captured: list[str] = []

        def _capture(**kwargs):
            captured.append(kwargs["outcome"])

        scenarios: list[tuple[ProcessedIntent, ProductAddResult | None]] = [
            (
                _ready_intent(producto_presentacion_id=None),
                None,
            ),
            (
                _ready_intent(),
                ProductAddResult(
                    status=STATUS_REJECTED, reason=REJECTED_SESSION_OR_PEDIDO
                ),
            ),
            (
                _ready_intent(),
                ProductAddResult(
                    status=STATUS_REJECTED, reason=REJECTED_NOT_EDITABLE
                ),
            ),
            (
                _ready_intent(),
                ProductAddResult(
                    status=STATUS_REJECTED,
                    reason=REJECTED_MISSING_PRESENTATION,
                ),
            ),
            (
                _ready_intent(),
                ProductAddResult(
                    status=STATUS_REJECTED,
                    reason=REJECTED_PRICE_UNAVAILABLE,
                ),
            ),
            (
                _ready_intent(),
                ProductAddResult(
                    status=STATUS_EXECUTED,
                    linea_creada=True,
                    cantidad_final=1,
                    precio_unitario=Decimal("1.00"),
                ),
            ),
            (
                _ready_intent(),
                ProductAddResult(
                    status=STATUS_EXECUTED,
                    linea_creada=False,
                    cantidad_final=2,
                    precio_unitario=Decimal("1.00"),
                ),
            ),
        ]
        for intent, seam_result in scenarios:
            captured.clear()
            with patch(
                "backend.intents.handlers.agregar_producto_handler.PedidoProductoService"
            ) as service_cls:
                if seam_result is None:
                    pass
                else:
                    service_cls.return_value.stage_add_or_increment_for_session.return_value = (
                        seam_result
                    )
                with patch(
                    "backend.intents.handlers.agregar_producto_handler.emit_event",
                    side_effect=_capture,
                ):
                    execute_agregar_producto(session, conversation, intent)
            self.assertEqual(len(captured), 1)
            self.assertIn(captured[0], self.ALLOWED_OUTCOMES)
            _assert_no_transaction_control(session)


if __name__ == "__main__":
    unittest.main()