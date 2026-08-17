"""Focused tests for the ``set_observacion_pedido`` pipeline.

Covers the following acceptance scenarios required by the
``set-draft-order-observation`` change:

1. Successful replacement of a NULL observation.
2. Successful replacement of an existing observation.
3. Idempotence: same observation as the current value still replaces
   (no special-cased skip), and accepted_length is recomputed.
4. Unicode whitespace (NBSP, tab, mixed line terminators) is
   collapsed before the 1..500 length check.
5. Length 1 (minimum) and length 500 (maximum) are accepted.
6. Length 501 (just over the maximum) is rejected with
   ``text_too_long`` and preserves the prior value.
7. Empty / whitespace-only text is rejected with ``text_empty`` and
   preserves the prior value.
8. Missing associated pedido -> ``rejected`` ``no_draft``, no write.
9. Foreign-session pedido -> ``rejected`` ``session_mismatch``,
   no write.
10. Non-borrador pedido -> ``rejected`` ``pedido_not_borrador``,
    no write.
11. Dispatcher branch routes the new intent to the new orchestrator.
12. Shared mapper renders the same ``CustomerResponse`` for the local
    path and the outbox staging path.
13. The orchestrator, response builder, dispatcher branch and mapper
    branch do not call any SQLAlchemy transaction-control method.
14. Pending-context short circuit: an active pending context keeps
    priority over a ``set_observacion_pedido`` request.
15. ``pedido.estado_pedido`` is not changed by a successful
    ``set_observacion_pedido`` turn; the pedido is not confirmed,
    cancelled, or replaced.
16. Regression: a pre-existing ``PedidoProducto.observaciones`` value
    is not read, written, or cleared by the new orchestrator.
17. ``session.pending_intents`` is not modified by the new turn.
18. A technical exception raised after the attribute write is staged
    propagates to the outer transaction owner and rolls the entire
    turn back (no durable annotation).
19. Response safety: the raw observation text never appears in
    ``CustomerResponse.message``, in ``resolved_data``, in the outbox
    row ``cuerpo``, or in the structured observability snapshots.
"""
from __future__ import annotations

import importlib
import unittest
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from backend.intents.orchestration import (
    draft_order_closure as closure_module,
)
from backend.intents.orchestration.draft_order_closure import (
    process_initial_set_observacion_pedido,
)
from backend.intents.orchestration.incoming_message_response_orchestrator import (
    process_incoming_message_with_responses,
)
from backend.intents.orchestration.initial_intent_dispatcher import (
    dispatch_initial_message,
)
from backend.intents.responses import (
    draft_order_closure as response_module,
)
from backend.intents.responses.draft_order_closure import (
    build_set_observacion_pedido_response,
)
from backend.intents.schemas.intent_classification import (
    ClassifiedIntent,
    IntentClassificationResult,
    IntentName,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models import (
    CategoriaProducto,
    Cliente,
    Comercio,
    EstadoComercio,
    EstadoPedido,
    Pedido,
    PedidoProducto,
    Presentacion,
    Producto,
    ProductoPresentacion,
)
from backend.models import Session as SessionModel
from backend.models.session import EstadoSession
from backend.services.outbound_response_mapper import (
    build_customer_responses,
    stage_outbound_rows,
)

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _estado_id_activo() -> int:
    with engine.connect() as c:
        row = c.execute(
            select(EstadoComercio.id).where(EstadoComercio.codigo == "ACTIVO")
        ).first()
        if row is None:
            raise RuntimeError("estado ACTIVO not seeded in supernova_test")
        return row[0]


def _seed_borrador_pedido(
    *,
    seed_line: bool = False,
    seed_producto_observacion: str | None = None,
) -> dict:
    """Create a fresh comercio + cliente + session + borrador pedido.

    The pedido's ``observaciones`` starts as ``NULL`` and the session's
    ``pending_intents`` is the empty dict. When ``seed_line`` is true
    one ``PedidoProducto`` row is added so we can verify the orchestrator
    does not touch ``PedidoProducto.observaciones``.
    """
    suffix = _suffix()
    estado_id = _estado_id_activo()
    with TestingSessionLocal() as db, db.begin():
        comercio = Comercio(
            nombre_fantasia=f"Obs {suffix}",
            nombre_corto=f"OB {suffix}",
            razon_social=f"Obs Comercio SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+5491{suffix[:8]}",
            calle="Av. Test",
            numero="1234",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"obs-{suffix}",
            estado_id=estado_id,
        )
        db.add(comercio)
        db.flush()

        cliente = Cliente(
            whatsapp=f"+5491{int(suffix, 16) % 100000000:08d}",
            nombre=None,
            domicilio=None,
            activo=True,
        )
        db.add(cliente)
        db.flush()

        session_row = SessionModel(
            id_comercio=comercio.id,
            id_cliente=cliente.id,
            id_pedido=None,
            estado_session=EstadoSession.ACTIVA,
            pending_intents={},
            context_type=None,
        )
        db.add(session_row)
        db.flush()

        pedido = Pedido(
            id_session=session_row.id,
            id_medio_pago=None,
            id_metodo_entrega=None,
            datetime_entrega_programada=None,
            estado_pedido=EstadoPedido.BORRADOR,
            observaciones=None,
        )
        db.add(pedido)
        db.flush()
        session_row.id_pedido = pedido.id
        db.flush()

        categoria = CategoriaProducto(
            id_comercio=comercio.id,
            descripcion=f"Categoria {suffix}",
            activo=True,
            orden=0,
        )
        db.add(categoria)
        db.flush()

        producto = Producto(
            id_categoria_producto=categoria.id,
            nombre=f"Empanada {suffix}",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        db.add(producto)
        db.flush()

        presentacion = Presentacion(
            id_comercio=comercio.id,
            codigo=f"docena-{suffix}",
            descripcion=f"Docena {suffix}",
            activo=True,
            orden=0,
        )
        db.add(presentacion)
        db.flush()
        assoc = ProductoPresentacion(
            id_producto=producto.id,
            id_presentacion=presentacion.id,
            activo=True,
            orden=0,
        )
        db.add(assoc)
        db.flush()

        line_id: int | None = None
        if seed_line:
            line = PedidoProducto(
                id_pedido=pedido.id,
                id_producto_presentacion=assoc.id,
                cantidad=2,
                precio_unitario=Decimal("100.00"),
                observaciones=seed_producto_observacion,
            )
            db.add(line)
            db.flush()
            line_id = line.id

        return {
            "comercio_id": comercio.id,
            "cliente_id": cliente.id,
            "session_id": session_row.id,
            "pedido_id": pedido.id,
            "producto_id": producto.id,
            "categoria_id": categoria.id,
            "pp_id": assoc.id,
            "line_id": line_id,
        }


def _cleanup(ids: dict) -> None:
    with TestingSessionLocal() as db, db.begin():
        sess_row = db.get(SessionModel, ids["session_id"])
        if sess_row is not None:
            sess_row.id_pedido = None
            db.flush()
        db.execute(
            delete(PedidoProducto).where(
                PedidoProducto.id_pedido == ids["pedido_id"]
            )
        )
        db.execute(delete(Pedido).where(Pedido.id == ids["pedido_id"]))
        db.execute(
            delete(ProductoPresentacion).where(
                ProductoPresentacion.id == ids["pp_id"]
            )
        )
        db.execute(delete(Producto).where(Producto.id == ids["producto_id"]))
        db.execute(
            delete(CategoriaProducto).where(
                CategoriaProducto.id == ids["categoria_id"]
            )
        )
        db.execute(
            delete(SessionModel).where(SessionModel.id == ids["session_id"])
        )
        db.execute(delete(Cliente).where(Cliente.id == ids["cliente_id"]))
        db.execute(delete(Comercio).where(Comercio.id == ids["comercio_id"]))


def _load_pedido(pedido_id: int) -> Pedido:
    with TestingSessionLocal() as db:
        return db.get(Pedido, pedido_id)


class _DispatchProbe:
    """Capture the routed orchestrator without running the real one.

    The intent-classifier and the pending-context machinery are
    untouched. The test substitutes the real
    ``process_initial_set_observacion_pedido`` symbol with a stub that
    records the call and returns an ``executed`` ProcessedIntent, then
    asserts the dispatcher called it exactly once with the expected
    arguments.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.stub = self._stub

    def _stub(self, db, session, source_text):
        self.calls.append(
            {
                "db": db,
                "session": session,
                "source_text": source_text,
            }
        )
        return ProcessedIntent(
            intent="set_observacion_pedido",
            source_text=source_text,
            status="executed",
            recognizer="draft_order_closure",
            handler="set_observacion_pedido",
            resolved_data={"accepted_length": len(source_text)},
        )


class _RecordingOrchestrator:
    """Track the call args and return a fixed processed intent.

    Used by the dispatcher test to verify the orchestrator was called
    with the classified ``mensaje`` and the supplied session.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, db, session, source_text):
        self.calls.append(
            {"db": db, "session": session, "source_text": source_text}
        )
        return ProcessedIntent(
            intent="set_observacion_pedido",
            source_text=source_text,
            status="executed",
            recognizer="draft_order_closure",
            handler="set_observacion_pedido",
            resolved_data={"accepted_length": 17},
        )


class SetObservationPedidoModuleTest(unittest.TestCase):
    def test_orchestrator_module_does_not_call_db_state_methods(self) -> None:
        importlib.reload(closure_module)
        module_path = closure_module.__file__
        assert module_path is not None
        with open(module_path, encoding="utf-8") as fh:
            source = fh.read()
        for token in (
            ".commit(",
            ".rollback(",
            ".flush(",
            ".refresh(",
            ".begin(",
            ".close(",
            ".expire(",
        ):
            self.assertNotIn(token, source)

    def test_response_module_does_not_call_db_state_methods(self) -> None:
        importlib.reload(response_module)
        module_path = response_module.__file__
        assert module_path is not None
        with open(module_path, encoding="utf-8") as fh:
            source = fh.read()
        for token in (
            ".commit(",
            ".rollback(",
            ".flush(",
            ".refresh(",
            ".begin(",
            ".close(",
            ".expire(",
        ):
            self.assertNotIn(token, source)


class SetObservationPedidoUnitTest(unittest.TestCase):
    """Pure unit tests for the orchestrator using mocked sessions/db."""

    def _session(
        self,
        *,
        session_id: int = 10,
        pedido_id: int | None = 20,
        estado_session=EstadoSession.ACTIVA,
    ):
        session = MagicMock(
            id=session_id,
            id_pedido=pedido_id,
            estado_session=estado_session,
        )
        return session

    def test_no_pedido_associated_rejects_without_lookup(self) -> None:
        db = MagicMock()
        result = process_initial_set_observacion_pedido(
            db, self._session(pedido_id=None), "hola"
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.resolved_data.get("reason"), "no_draft")
        db.get.assert_not_called()

    def test_closed_session_rejects_without_reading_pedido(self) -> None:
        db = MagicMock()
        result = process_initial_set_observacion_pedido(
            db,
            self._session(estado_session=EstadoSession.CERRADA),
            "hola",
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(
            result.resolved_data.get("reason"), "session_not_active"
        )
        db.get.assert_not_called()

    def test_missing_pedido_row_rejects(self) -> None:
        db = MagicMock()
        db.get.return_value = None
        result = process_initial_set_observacion_pedido(
            db, self._session(), "hola"
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.resolved_data.get("reason"), "no_draft")

    def test_foreign_session_pedido_rejects(self) -> None:
        db = MagicMock()
        pedido = MagicMock(
            id_session=99,
            estado_pedido=EstadoPedido.BORRADOR,
        )
        db.get.return_value = pedido
        result = process_initial_set_observacion_pedido(
            db, self._session(), "hola"
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.resolved_data.get("reason"), "session_mismatch")
        pedido.observaciones.assert_not_called()

    def test_non_borrador_pedido_rejects_for_each_state(self) -> None:
        for state in (
            EstadoPedido.INGRESADO,
            EstadoPedido.PREPARACION,
            EstadoPedido.TERMINADO,
            EstadoPedido.ENTREGADO,
            EstadoPedido.CANCELADO,
        ):
            with self.subTest(state=state.value):
                db = MagicMock()
                pedido = MagicMock(
                    id_session=10,
                    estado_pedido=state,
                )
                db.get.return_value = pedido
                result = process_initial_set_observacion_pedido(
                    db, self._session(), "hola"
                )
                self.assertEqual(result.status, "rejected")
                self.assertEqual(
                    result.resolved_data.get("reason"), "pedido_not_borrador"
                )
                pedido.observaciones.assert_not_called()

    def test_empty_text_rejects_and_preserves(self) -> None:
        pedido = MagicMock(
            id_session=10,
            estado_pedido=EstadoPedido.BORRADOR,
            observaciones="existing",
        )
        db = MagicMock()
        db.get.return_value = pedido
        for empty in ("", "   ", "\t\n", "\u00a0\u202f\u3000"):
            with self.subTest(raw=empty):
                result = process_initial_set_observacion_pedido(
                    db, self._session(), empty
                )
                self.assertEqual(result.status, "rejected")
                self.assertEqual(
                    result.resolved_data.get("reason"), "text_empty"
                )
        self.assertEqual(pedido.observaciones, "existing")

    def test_too_long_text_rejects_and_preserves(self) -> None:
        pedido = MagicMock(
            id_session=10,
            estado_pedido=EstadoPedido.BORRADOR,
            observaciones="existing",
        )
        db = MagicMock()
        db.get.return_value = pedido
        too_long = "x" * 501
        result = process_initial_set_observacion_pedido(
            db, self._session(), too_long
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(
            result.resolved_data.get("reason"), "text_too_long"
        )
        self.assertEqual(pedido.observaciones, "existing")

    def test_unicode_whitespace_collapses_before_length_check(self) -> None:
        pedido = MagicMock(
            id_session=10,
            estado_pedido=EstadoPedido.BORRADOR,
            observaciones=None,
        )
        db = MagicMock()
        db.get.return_value = pedido
        weird = (
            "\u00a0\u00a0hola\u202fmundo\u3000adios\tcruel\n"
        )
        result = process_initial_set_observacion_pedido(
            db, self._session(), weird
        )
        self.assertEqual(result.status, "executed")
        self.assertEqual(pedido.observaciones, "hola mundo adios cruel")
        self.assertEqual(
            result.resolved_data.get("accepted_length"),
            len("hola mundo adios cruel"),
        )

    def test_accepted_length_one_is_accepted(self) -> None:
        pedido = MagicMock(
            id_session=10,
            estado_pedido=EstadoPedido.BORRADOR,
            observaciones=None,
        )
        db = MagicMock()
        db.get.return_value = pedido
        result = process_initial_set_observacion_pedido(
            db, self._session(), "x"
        )
        self.assertEqual(result.status, "executed")
        self.assertEqual(pedido.observaciones, "x")
        self.assertEqual(result.resolved_data.get("accepted_length"), 1)

    def test_accepted_length_500_is_accepted(self) -> None:
        pedido = MagicMock(
            id_session=10,
            estado_pedido=EstadoPedido.BORRADOR,
            observaciones=None,
        )
        db = MagicMock()
        db.get.return_value = pedido
        text = "a" * 500
        result = process_initial_set_observacion_pedido(
            db, self._session(), text
        )
        self.assertEqual(result.status, "executed")
        self.assertEqual(pedido.observaciones, text)
        self.assertEqual(result.resolved_data.get("accepted_length"), 500)

    def test_no_transaction_control_methods_called(self) -> None:
        db = MagicMock()
        db.get.return_value = MagicMock(
            id_session=10,
            estado_pedido=EstadoPedido.BORRADOR,
            observaciones=None,
        )
        process_initial_set_observacion_pedido(
            db, self._session(), "ok"
        )
        for method in (
            "commit",
            "rollback",
            "begin",
            "flush",
            "refresh",
            "expire",
            "close",
        ):
            getattr(db, method).assert_not_called()

    def test_does_not_leak_raw_text_into_resolved_data(self) -> None:
        pedido = MagicMock(
            id_session=10,
            estado_pedido=EstadoPedido.BORRADOR,
            observaciones=None,
        )
        db = MagicMock()
        db.get.return_value = pedido
        secret = "secret-observation-payload-aaa"
        result = process_initial_set_observacion_pedido(
            db, self._session(), secret
        )
        self.assertNotIn(secret, result.resolved_data.values())
        for value in result.resolved_data.values():
            self.assertNotIn(secret, repr(value))


class SetObservationPedidoResponseTest(unittest.TestCase):
    def _intent(self, *, status, reason=None, length=None):
        resolved: dict = {}
        if reason is not None:
            resolved["reason"] = reason
        if length is not None:
            resolved["accepted_length"] = length
        return ProcessedIntent(
            intent="set_observacion_pedido",
            source_text="some text",
            status=status,
            recognizer="draft_order_closure",
            handler="set_observacion_pedido",
            resolved_data=resolved,
        )

    def test_executed_renders_confirmation(self) -> None:
        intent = self._intent(status="executed", length=42)
        response = build_set_observacion_pedido_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.status, "executed")
        self.assertEqual(response.intent, "set_observacion_pedido")
        self.assertIn("observación", response.message.lower())
        self.assertNotIn("42", response.message)
        self.assertNotIn("some text", response.message)

    def test_rejected_renders_safe_message(self) -> None:
        for reason in (
            "text_empty",
            "text_too_long",
            "no_draft",
            "session_mismatch",
            "pedido_not_borrador",
        ):
            with self.subTest(reason=reason):
                intent = self._intent(status="rejected", reason=reason)
                response = build_set_observacion_pedido_response(
                    MagicMock(), MagicMock(), intent
                )
                self.assertEqual(response.status, "rejected")
                self.assertEqual(response.intent, "set_observacion_pedido")
                self.assertNotIn(reason, response.message)
                self.assertNotIn("some text", response.message)

    def test_failed_renders_generic_message(self) -> None:
        intent = self._intent(status="failed")
        response = build_set_observacion_pedido_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.status, "failed")
        self.assertIn("técnico", response.message.lower())

    def test_wrong_intent_renders_generic_message(self) -> None:
        intent = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="executed",
            handler="agregar_producto",
        )
        response = build_set_observacion_pedido_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.intent, "agregar_producto")
        self.assertIn("técnico", response.message.lower())


class SetObservationPedidoMapperTest(unittest.TestCase):
    def test_mapper_local_and_shared_builder_are_equivalent(self) -> None:
        intent = ProcessedIntent(
            intent="set_observacion_pedido",
            source_text="some text",
            status="executed",
            recognizer="draft_order_closure",
            handler="set_observacion_pedido",
            resolved_data={"accepted_length": 7},
        )
        db = MagicMock()
        session = MagicMock()
        local = build_set_observacion_pedido_response(db, session, intent)
        mapped = build_customer_responses(db, session, [intent])[0]
        self.assertEqual(mapped, local)
        self.assertNotIn("some text", mapped.message)

    def test_outbox_staging_uses_the_same_message(self) -> None:
        intent = ProcessedIntent(
            intent="set_observacion_pedido",
            source_text="some text",
            status="executed",
            recognizer="draft_order_closure",
            handler="set_observacion_pedido",
            resolved_data={"accepted_length": 7},
        )
        db = MagicMock()
        session = MagicMock()
        expected = build_customer_responses(db, session, [intent])[0]
        outbox_repo = MagicMock()
        staged_row = MagicMock()
        staged_row.id = 100
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
        self.assertEqual(result[0].customer_response, expected)
        outbox_repo.stage.assert_called_once()
        self.assertEqual(
            outbox_repo.stage.call_args.kwargs["cuerpo"], expected.message
        )
        self.assertEqual(result[0].sequence, 0)


class SetObservationPedidoDispatcherTest(unittest.TestCase):
    def test_dispatcher_direct_observacion_pedido_returns_deterministic_rejection(
        self,
    ) -> None:
        """A direct ``set_observacion_pedido`` outside the confirmation
        context is rejected with the fixed guidance to confirm first.
        The product-line observation capability is removed so the
        new flow only accepts pedido observations through the bounded
        confirmation context.
        """
        from backend.intents.orchestration import (
            initial_intent_dispatcher as dispatcher_module,
        )

        classification = IntentClassificationResult(
            intents=[
                ClassifiedIntent(
                    intent=IntentName.SET_OBSERVACION_PEDIDO,
                    mensaje="entregar a las 19",
                )
            ],
            mensaje="entregar a las 19",
        )
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = classification

        db = MagicMock(name="DatabaseSession")
        session = MagicMock(name="ConversationSession")
        session.context_type = None
        session.id_pedido = None
        session.pending_intents = None
        session.estado_session = EstadoSession.ACTIVA

        with patch.object(
            dispatcher_module, "IntentClassifier"
        ) as classifier_cls:
            classifier_cls.return_value = classifier_instance
            processed = dispatch_initial_message(
                db, session, "entregar a las 19"
            )

        self.assertEqual(len(processed), 1)
        self.assertEqual(processed[0].status, "rejected")
        self.assertEqual(processed[0].intent, "set_observacion_pedido")
        self.assertEqual(
            processed[0].resolved_data.get("reason"),
            "direct_observation_disabled",
        )
        self.assertIn(
            "confirmá", processed[0].resolved_data.get("guidance", "")
        )

    def test_pending_context_short_circuits_initial_dispatch(self) -> None:
        from backend.intents.orchestration import (
            initial_intent_dispatcher as dispatcher_module,
        )

        db = MagicMock(name="DatabaseSession")
        session = MagicMock(name="ConversationSession")
        session.context_type = "order_clear_confirmation"
        session.id_pedido = 20
        session.pending_intents = {}

        with patch.object(
            dispatcher_module, "IntentClassifier"
        ) as classifier_cls:
            processed = dispatch_initial_message(db, session, "alguna nota")

        self.assertEqual(processed, [])
        classifier_cls.assert_not_called()


class SetObservationPedidoIntegrationTest(unittest.TestCase):
    """PostgreSQL-backed tests for the full orchestrator + mapper chain."""

    def test_closed_session_rejects_without_mutation(self) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                pedido.observaciones = "valor previo"
                session = db.get(SessionModel, ids["session_id"])
                session.estado_session = EstadoSession.CERRADA

            with TestingSessionLocal() as db:
                session = db.get(SessionModel, ids["session_id"])
                self.assertEqual(session.estado_session, EstadoSession.CERRADA)
                result = process_initial_set_observacion_pedido(
                    db, session, "  intento escribir igual  "
                )
                self.assertEqual(result.status, "rejected")
                self.assertEqual(
                    result.resolved_data.get("reason"), "session_not_active"
                )
                db.commit()

            pedido = _load_pedido(ids["pedido_id"])
            self.assertEqual(pedido.observaciones, "valor previo")
            self.assertEqual(pedido.estado_pedido, EstadoPedido.BORRADOR)
            with TestingSessionLocal() as db:
                session = db.get(SessionModel, ids["session_id"])
                self.assertEqual(
                    session.estado_session, EstadoSession.CERRADA
                )
        finally:
            _cleanup(ids)

    def test_successful_replacement_of_null_observation_persists(self) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db:
                session = db.get(SessionModel, ids["session_id"])
                result = process_initial_set_observacion_pedido(
                    db, session, "  entregar  entre  19  y  20 "
                )
                self.assertEqual(result.status, "executed")
                self.assertEqual(
                    result.resolved_data.get("accepted_length"),
                    len("entregar entre 19 y 20"),
                )
                db.commit()

            pedido = _load_pedido(ids["pedido_id"])
            self.assertEqual(pedido.observaciones, "entregar entre 19 y 20")
            self.assertEqual(pedido.estado_pedido, EstadoPedido.BORRADOR)
        finally:
            _cleanup(ids)

    def test_successful_replacement_of_existing_observation(self) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                pedido.observaciones = "valor previo"

            with TestingSessionLocal() as db:
                session = db.get(SessionModel, ids["session_id"])
                result = process_initial_set_observacion_pedido(
                    db, session, "  nuevo valor "
                )
                self.assertEqual(result.status, "executed")
                db.commit()

            pedido = _load_pedido(ids["pedido_id"])
            self.assertEqual(pedido.observaciones, "nuevo valor")
            self.assertEqual(pedido.estado_pedido, EstadoPedido.BORRADOR)
        finally:
            _cleanup(ids)

    def test_idempotent_same_value_replaces(self) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                pedido.observaciones = "sin cebolla"

            with TestingSessionLocal() as db:
                session = db.get(SessionModel, ids["session_id"])
                result = process_initial_set_observacion_pedido(
                    db, session, "  sin   cebolla "
                )
                self.assertEqual(result.status, "executed")
                db.commit()

            pedido = _load_pedido(ids["pedido_id"])
            self.assertEqual(pedido.observaciones, "sin cebolla")
        finally:
            _cleanup(ids)

    def test_too_long_text_does_not_overwrite_existing(self) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                pedido.observaciones = "valor previo"

            text = "x" * 501
            with TestingSessionLocal() as db:
                session = db.get(SessionModel, ids["session_id"])
                result = process_initial_set_observacion_pedido(
                    db, session, text
                )
                self.assertEqual(result.status, "rejected")
                self.assertEqual(
                    result.resolved_data.get("reason"), "text_too_long"
                )
                db.commit()

            pedido = _load_pedido(ids["pedido_id"])
            self.assertEqual(pedido.observaciones, "valor previo")
        finally:
            _cleanup(ids)

    def test_empty_text_does_not_overwrite_existing(self) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                pedido.observaciones = "valor previo"

            with TestingSessionLocal() as db:
                session = db.get(SessionModel, ids["session_id"])
                result = process_initial_set_observacion_pedido(
                    db, session, "   \u00a0  "
                )
                self.assertEqual(result.status, "rejected")
                self.assertEqual(
                    result.resolved_data.get("reason"), "text_empty"
                )
                db.commit()

            pedido = _load_pedido(ids["pedido_id"])
            self.assertEqual(pedido.observaciones, "valor previo")
        finally:
            _cleanup(ids)

    def test_does_not_change_pedido_producto_observaciones(self) -> None:
        ids = _seed_borrador_pedido(
            seed_line=True, seed_producto_observacion="nota de producto"
        )
        try:
            with TestingSessionLocal() as db:
                session = db.get(SessionModel, ids["session_id"])
                result = process_initial_set_observacion_pedido(
                    db, session, "nota del pedido"
                )
                self.assertEqual(result.status, "executed")
                db.commit()

            with TestingSessionLocal() as db:
                line = db.get(PedidoProducto, ids["line_id"])
                self.assertEqual(line.observaciones, "nota de producto")
            pedido = _load_pedido(ids["pedido_id"])
            self.assertEqual(pedido.observaciones, "nota del pedido")
            self.assertEqual(pedido.estado_pedido, EstadoPedido.BORRADOR)
        finally:
            _cleanup(ids)

    def test_successful_turn_does_not_alter_pending_state(self) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db, db.begin():
                session = db.get(SessionModel, ids["session_id"])
                session.pending_intents = {
                    "active": {
                        "intent": "vaciar_pedido",
                        "status": "pending_resolution",
                        "source_text": "vaciar",
                        "recognizer": "vaciar_pedido",
                        "handler": "vaciar_pedido",
                        "resolved_data": {"pedido_id": ids["pedido_id"]},
                        "requirements": [
                            {"name": "confirmacion", "status": "pending", "value": None}
                        ],
                        "candidate_ids": [],
                    },
                    "queue": [],
                }
            with TestingSessionLocal() as db:
                session = db.get(SessionModel, ids["session_id"])
                process_initial_set_observacion_pedido(
                    db, session, "entregar a las 19"
                )
                db.commit()
            with TestingSessionLocal() as db:
                session = db.get(SessionModel, ids["session_id"])
                self.assertIsNotNone(session.pending_intents)
                self.assertEqual(
                    session.pending_intents["active"]["intent"],
                    "vaciar_pedido",
                )
        finally:
            _cleanup(ids)

    def test_technical_failure_after_staging_rolls_back_entire_turn(
        self,
    ) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                pedido.observaciones = "valor previo"

            class _BoomOnCommit(Exception):
                pass

            class _ExplodingSession:
                def __init__(self, real) -> None:
                    self._real = real

                def get(self, *args, **kwargs):
                    return self._real.get(*args, **kwargs)

                def commit(self):
                    raise _BoomOnCommit("simulated technical failure")

                def rollback(self):
                    self._real.rollback()

            with TestingSessionLocal() as db:
                session = db.get(SessionModel, ids["session_id"])
                wrapped = _ExplodingSession(db)
                process_initial_set_observacion_pedido(
                    wrapped, session, "entregar a las 19"
                )
                with self.assertRaises(_BoomOnCommit):
                    wrapped.commit()
                wrapped.rollback()

            pedido = _load_pedido(ids["pedido_id"])
            self.assertEqual(pedido.observaciones, "valor previo")
        finally:
            _cleanup(ids)

    def test_shared_mapper_response_matches_local(self) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db:
                session = db.get(SessionModel, ids["session_id"])
                secret = "observation-secret-xyz"
                result = process_initial_set_observacion_pedido(
                    db, session, secret
                )
                local = build_set_observacion_pedido_response(
                    db, session, result
                )
                mapped_list = build_customer_responses(
                    db, session, [result]
                )
                mapped = mapped_list[0]
                db.commit()
            self.assertEqual(mapped, local)
            self.assertNotIn(secret, local.message)
            self.assertNotIn(secret, mapped.message)
        finally:
            _cleanup(ids)

    def test_full_incoming_pipeline_returns_mapped_response(self) -> None:
        from backend.intents.orchestration import (
            initial_intent_dispatcher as dispatcher_module,
        )

        ids = _seed_borrador_pedido()
        try:
            classification = IntentClassificationResult(
                intents=[
                    ClassifiedIntent(
                        intent=IntentName.SET_OBSERVACION_PEDIDO,
                        mensaje="observation-text",
                    )
                ],
                mensaje="observation-text",
            )
            fake_classifier = MagicMock()
            fake_classifier.query.return_value = classification
            with TestingSessionLocal() as db, db.begin():
                session = db.get(SessionModel, ids["session_id"])
                with patch.object(
                    dispatcher_module, "IntentClassifier"
                ) as classifier_cls:
                    classifier_cls.return_value = fake_classifier
                    responses = process_incoming_message_with_responses(
                        db, session, "observation-text"
                    )
            self.assertEqual(len(responses), 1)
            self.assertEqual(
                responses[0].intent, "set_observacion_pedido"
            )
            self.assertEqual(responses[0].status, "rejected")
            # The pedido must NOT be mutated: the direct observation
            # intent is rejected with the deterministic guidance so
            # the customer is asked to confirm the order first.
            pedido = _load_pedido(ids["pedido_id"])
            assert pedido is not None
            self.assertIsNone(pedido.observaciones)
            self.assertEqual(pedido.estado_pedido, EstadoPedido.BORRADOR)
        finally:
            _cleanup(ids)


if __name__ == "__main__":
    unittest.main()
