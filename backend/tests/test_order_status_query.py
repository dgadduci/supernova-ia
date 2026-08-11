from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.intents.orchestration.order_status_query import (
    process_initial_order_status_query,
)
from backend.intents.responses.order_status_query import (
    build_order_status_query_response,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.pedido import EstadoPedido, Pedido
from backend.services.outbound_response_mapper import (
    build_customer_responses,
    stage_outbound_rows,
)


class OrderStatusQueryTest(unittest.TestCase):
    def _session(self, *, session_id=10, pedido_id=20):
        session = MagicMock(id=session_id, id_pedido=pedido_id)
        return session

    def test_missing_association_rejects_without_lookup(self):
        db = MagicMock()
        result = process_initial_order_status_query(db, self._session(pedido_id=None), "estado")
        self.assertEqual(result.status, "rejected")
        db.get.assert_not_called()

    def test_missing_order_rejects_without_alternative_lookup(self):
        db = MagicMock()
        db.get.return_value = None
        result = process_initial_order_status_query(db, self._session(), "estado")
        self.assertEqual(result.resolved_data, {"reason": "no_pedido_asociado"})
        db.get.assert_called_once_with(Pedido, 20)

    def test_foreign_order_rejects(self):
        db = MagicMock()
        db.get.return_value = MagicMock(id_session=99)
        result = process_initial_order_status_query(db, self._session(), "estado")
        self.assertEqual(result.resolved_data, {"reason": "session_mismatch"})

    def test_each_state_is_executed_and_rendered(self):
        for state in EstadoPedido:
            with self.subTest(state=state.value):
                db = MagicMock()
                db.get.return_value = MagicMock(
                    id_session=10, estado_pedido=state
                )
                result = process_initial_order_status_query(
                    db, self._session(), "estado"
                )
                self.assertEqual(result.status, "executed")
                response = build_order_status_query_response(db, self._session(), result)
                self.assertEqual(response.status, "executed")
                self.assertNotIn("20", response.message)
                self.assertNotIn("10", response.message)

    def test_builder_rejects_without_sensitive_detail(self):
        intent = ProcessedIntent(
            intent="consultar_estado_pedido",
            source_text="estado",
            status="rejected",
            handler="consultar_estado_pedido",
            resolved_data={
                "reason": "session_mismatch",
                "pedido_id": 20,
                "customer": "secret",
            },
        )
        response = build_order_status_query_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.message, "No tenés un pedido activo para consultar.")
        self.assertNotIn("secret", response.message)
        self.assertNotIn("20", response.message)

    def test_mapper_local_and_shared_builder_are_equivalent(self):
        intent = ProcessedIntent(
            intent="consultar_estado_pedido",
            source_text="estado",
            status="executed",
            handler="consultar_estado_pedido",
            resolved_data={"estado_pedido": "preparacion"},
        )
        db = MagicMock()
        session = MagicMock()
        local = build_order_status_query_response(db, session, intent)
        mapped = build_customer_responses(db, session, [intent])[0]
        self.assertEqual(mapped, local)

    def test_no_transaction_control_methods_are_called(self):
        db = MagicMock()
        db.get.return_value = MagicMock(id_session=10, estado_pedido=EstadoPedido.BORRADOR)
        process_initial_order_status_query(db, self._session(), "estado")
        build_order_status_query_response(db, self._session(), ProcessedIntent(
            intent="consultar_estado_pedido",
            source_text="estado",
            status="executed",
            handler="consultar_estado_pedido",
            resolved_data={"estado_pedido": "borrador"},
        ))
        for method in ("commit", "rollback", "begin", "flush", "refresh", "expire", "close"):
            getattr(db, method).assert_not_called()

    def test_stage_outbound_rows_preserves_shared_mapper_response(self):
        intent = ProcessedIntent(
            intent="consultar_estado_pedido",
            source_text="estado",
            status="executed",
            handler="consultar_estado_pedido",
            resolved_data={"estado_pedido": "preparacion"},
        )

        db = MagicMock()
        session = MagicMock()

        expected = build_customer_responses(db, session, [intent])[0]

        outbox_repo = MagicMock()
        staged_row = MagicMock()
        staged_row.id = 42
        outbox_repo.stage.return_value = staged_row

        result = stage_outbound_rows(
            db,
            session,
            proveedor="twilio",
            recepcion_mensaje_proveedor_id=1,
            destinatario_e164="+5491112345678",
            intents=[intent],
            outbox_repo=outbox_repo,
        )

        self.assertEqual(len(result), 1)
        staged = result[0]
        self.assertEqual(staged.sequence, 0)
        self.assertEqual(staged.mensaje_proveedor_saliente_id, 42)
        self.assertEqual(staged.customer_response.message, expected.message)
        self.assertEqual(staged.customer_response.intent, expected.intent)
        self.assertEqual(staged.customer_response.status, expected.status)

        outbox_repo.stage.assert_called_once()
        call_kwargs = outbox_repo.stage.call_args.kwargs
        self.assertEqual(call_kwargs["cuerpo"], expected.message)
        self.assertEqual(call_kwargs["sequence"], 0)


if __name__ == "__main__":
    unittest.main()
