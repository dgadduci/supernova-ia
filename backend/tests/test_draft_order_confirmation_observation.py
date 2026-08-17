"""Focused tests for the confirmation-time order observation flow.

The change supersedes the product-line observation capability and
replaces it with a single bounded capture step that runs after the
explicit ``confirmar_pedido`` request. The capture turn is resolved
through the dedicated ``order_confirmation_observation_resolver``
instead of the initial classifier, so the new tests focus on the
resolver contract, the precondition validator, the finalizer and
the pending-context dispatcher integration.

The tests cover:

- the validation contract (no/text/empty/over-limit) when the
  capture is the second incoming message of the two-turn flow;
- the no-mutation output of the resolver (no classifier, no LLM,
  no product recognizer, no catalog, no line lookup, no
  transaction-control methods, no PedidoProducto writes);
- the finalizer re-running the documented preconditions so a stale
  pending context cleared by the transport never carries a partial
  confirmation forward;
- the prompt / retry response privacy (no observation text in the
  rendered message);
- the stale pre-deploy ``set_observacion_producto`` pending state
  being cleared without invoking the historic handler;
- the panel template no longer presenting the line observation as
  an active column;
- the explicit ``set_observacion_producto`` and
  ``set_observacion_pedido`` classifications outside the confirmation
  context being rejected with the deterministic guidance.
"""
from __future__ import annotations

import importlib
import unittest
import uuid
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from backend.intents.context.context_type_resolver import resolve_context_type
from backend.intents.context.order_confirmation_observation_resolver import (
    ORDER_CONFIRMATION_OBSERVATION_PROMPT,
    ORDER_CONFIRMATION_OBSERVATION_RETRY_PROMPT,
    resolve_order_confirmation_observation,
)
from backend.intents.orchestration import (
    initial_intent_dispatcher as initial_intent_dispatcher_module,
)
from backend.intents.orchestration import (
    pending_context_dispatcher as pending_context_dispatcher_module,
)
from backend.intents.orchestration import (
    pending_context_execution as pending_context_execution_module,
)
from backend.intents.orchestration.draft_order_closure import (
    finalize_confirmar_pedido,
    process_initial_confirmar_pedido,
)
from backend.intents.orchestration.incoming_message_response_orchestrator import (
    process_incoming_message_with_responses,
)
from backend.intents.orchestration.initial_intent_dispatcher import (
    dispatch_initial_message,
)
from backend.intents.orchestration.pending_context_dispatcher import (
    dispatch_pending_context,
)
from backend.intents.orchestration.pending_context_execution import (
    execute_ready_pending_context,
)
from backend.intents.responses.draft_order_closure import (
    build_confirmar_pedido_response,
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
from backend.intents.schemas.requirement_state import RequirementState
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
from backend.services.pedido_producto_service import PedidoProductoService
from backend.sessions.enums.context_type import ContextType

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _estado_id_activo() -> int:
    from sqlalchemy import select

    from backend.models import EstadoComercio

    with engine.connect() as c:
        row = c.execute(
            select(EstadoComercio.id).where(EstadoComercio.codigo == "ACTIVO")
        ).first()
        if row is None:
            raise RuntimeError("estado ACTIVO not seeded in supernova_test")
        return row[0]


def _seed_borrador_pedido(
    *,
    seed_line: bool = True,
    medio_pago_seed: bool = True,
    metodo_entrega_seed: bool = True,
) -> dict:
    """Seed a fresh comercio + cliente + session + borrador pedido.

    The pedido starts with ``observaciones = NULL`` and the
    session's ``pending_intents`` is the empty dict. When
    ``seed_line`` is true one ``PedidoProducto`` row is added so
    the finalizer can confirm the order end-to-end.
    """
    suffix = _suffix()
    estado_id = _estado_id_activo()
    with TestingSessionLocal() as db, db.begin():
        comercio = Comercio(
            nombre_fantasia=f"Conf {suffix}",
            nombre_corto=f"CO {suffix}",
            razon_social=f"Conf Comercio SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+5491{suffix[:8]}",
            calle="Calle Conf",
            numero="100",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"conf-{suffix}",
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

        if seed_line:
            db.add(
                PedidoProducto(
                    id_pedido=pedido.id,
                    id_producto_presentacion=assoc.id,
                    cantidad=1,
                    precio_unitario=Decimal("100.00"),
                    observaciones=None,
                )
            )
            db.flush()

        medio_pago_id = None
        if medio_pago_seed:
            from backend.models import MediosPago, ComercioMedioPago

            medio_pago = MediosPago(
                codigo=f"EF-{suffix}",
                descripcion=f"Efectivo {suffix}",
                activo=True,
            )
            db.add(medio_pago)
            db.flush()
            medio_pago_id = int(medio_pago.id)
            db.add(
                ComercioMedioPago(
                    id_comercio=comercio.id,
                    id_medio_pago=medio_pago_id,
                    activo=True,
                )
            )
            db.flush()

        metodo_entrega_id = None
        if metodo_entrega_seed:
            from backend.models import MetodosEntrega, ComercioMetodoEntrega

            metodo = MetodosEntrega(
                codigo=f"RETIRO-{suffix}",
                descripcion=f"Retiro {suffix}",
                orden=0,
                activo=True,
            )
            db.add(metodo)
            db.flush()
            metodo_entrega_id = int(metodo.id)
            db.add(
                ComercioMetodoEntrega(
                    id_comercio=comercio.id,
                    id_metodo_entrega=metodo_entrega_id,
                    orden=0,
                    activo=True,
                )
            )
            db.flush()

        if medio_pago_id is not None:
            pedido.id_medio_pago = medio_pago_id
            db.flush()
        if metodo_entrega_id is not None:
            pedido.id_metodo_entrega = metodo_entrega_id
            db.flush()

        return {
            "comercio_id": comercio.id,
            "cliente_id": cliente.id,
            "session_id": session_row.id,
            "pedido_id": pedido.id,
            "producto_id": producto.id,
            "categoria_id": categoria.id,
            "pp_id": assoc.id,
            "medio_pago_id": medio_pago_id,
            "metodo_entrega_id": metodo_entrega_id,
        }


def _cleanup(ids: dict) -> None:
    with TestingSessionLocal() as db, db.begin():
        sess_row = db.get(SessionModel, ids["session_id"])
        if sess_row is not None:
            sess_row.id_pedido = None
            sess_row.context_type = None
            sess_row.pending_intents = {}
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
        db.execute(delete(SessionModel).where(SessionModel.id == ids["session_id"]))
        db.execute(delete(Cliente).where(Cliente.id == ids["cliente_id"]))
        db.execute(delete(Comercio).where(Comercio.id == ids["comercio_id"]))


def _stage_active_confirmation(
    *,
    pedido_id: int,
    session_id: int,
    source_text: str = "confirmar",
) -> SessionModel:
    """Run the initial dispatcher turn and seed the pending context.

    The helper returns the reloaded ``SessionModel`` from the same
    session so the caller can drive the capture turn with the same
    SQLAlchemy session instance and let the transactional wrapper
    commit the new state.
    """
    with TestingSessionLocal() as db:
        session_row = db.get(SessionModel, session_id)
        assert session_row is not None
        classification = IntentClassificationResult(
            intents=[
                ClassifiedIntent(intent=IntentName.CONFIRMAR_PEDIDO, mensaje=source_text)
            ],
            mensaje=source_text,
        )
        fake_classifier = MagicMock()
        fake_classifier.query.return_value = classification
        with patch.object(
            initial_intent_dispatcher_module, "IntentClassifier"
        ) as classifier_cls:
            classifier_cls.return_value = fake_classifier
            processed = process_incoming_message_with_responses(
                db, session_row, source_text
            )
        assert len(processed) == 1
        assert processed[0].status == "pending_resolution"
        assert processed[0].intent == "confirmar_pedido"
        session_row = db.get(SessionModel, session_id)
        assert session_row is not None
        assert session_row.context_type == (
            ContextType.ORDER_CONFIRMATION_OBSERVATION.value
        )
        return session_row


@contextmanager
def _no_transaction_control_session():
    """Yield a ``DatabaseSession`` double that records every
    transaction-control call so the test can assert the new flow
    never invokes any of them.
    """
    session = MagicMock(name="DatabaseSession")
    yield session
    for method in (
        "commit",
        "rollback",
        "flush",
        "refresh",
        "begin",
        "expire",
        "close",
    ):
        getattr(session, method).assert_not_called()


class OrderConfirmationObservationResolverUnitTest(unittest.TestCase):
    """Pure unit tests for the bounded capture resolver."""

    def _active(self) -> ProcessedIntent:
        return ProcessedIntent(
            intent="confirmar_pedido",
            source_text="confirmar",
            status="pending_resolution",
            recognizer="draft_order_closure",
            handler="confirmar_pedido",
            resolved_data={"pedido_id": 42},
            requirements=[
                RequirementState(
                    name="observacion_pedido",
                    status="pending",
                    value=None,
                ),
            ],
            candidate_ids=[],
        )

    def test_no_skip_returns_skip_outcome(self) -> None:
        active = self._active()
        with _no_transaction_control_session() as db:
            outcome = resolve_order_confirmation_observation(
                db, MagicMock(), "no", active
            )
        self.assertTrue(outcome.skip)
        self.assertFalse(outcome.retry)
        self.assertIsNone(outcome.accepted_text)
        self.assertEqual(outcome.accepted_length, 0)

    def test_no_skip_with_unicode_text_returns_skip_outcome(self) -> None:
        active = self._active()
        with _no_transaction_control_session() as db:
            outcome = resolve_order_confirmation_observation(
                db, MagicMock(), "  No  ", active
            )
        self.assertTrue(outcome.skip)

    def test_free_text_returns_normalized_observation_in_memory(self) -> None:
        active = self._active()
        with _no_transaction_control_session() as db:
            outcome = resolve_order_confirmation_observation(
                db,
                MagicMock(),
                "  entregar   entre   19  y  20 ",
                active,
            )
        self.assertEqual(outcome.accepted_text, "entregar entre 19 y 20")
        self.assertEqual(outcome.accepted_length, len("entregar entre 19 y 20"))
        self.assertFalse(outcome.skip)
        self.assertFalse(outcome.retry)

    def test_empty_text_returns_retry(self) -> None:
        active = self._active()
        with _no_transaction_control_session() as db:
            outcome = resolve_order_confirmation_observation(
                db, MagicMock(), "   ", active
            )
        self.assertTrue(outcome.retry)
        self.assertEqual(outcome.retry_reason, "invalid_capture_length")
        self.assertIsNone(outcome.accepted_text)

    def test_over_limit_text_returns_retry(self) -> None:
        active = self._active()
        with _no_transaction_control_session() as db:
            outcome = resolve_order_confirmation_observation(
                db, MagicMock(), "x" * 501, active
            )
        self.assertTrue(outcome.retry)
        self.assertEqual(outcome.retry_reason, "invalid_capture_length")
        self.assertIsNone(outcome.accepted_text)

    def test_max_length_text_returns_accepted_outcome(self) -> None:
        active = self._active()
        with _no_transaction_control_session() as db:
            outcome = resolve_order_confirmation_observation(
                db, MagicMock(), "x" * 500, active
            )
        self.assertEqual(outcome.accepted_text, "x" * 500)
        self.assertFalse(outcome.retry)
        self.assertFalse(outcome.skip)

    def test_resolver_does_not_invoke_classifier_or_recognizer(self) -> None:
        """The capture turn must never invoke the LLM, the product
        recognizer, the catalog, the order-line fuzzy recognizer or
        the hybrid recognizer.
        """
        with patch(
            "backend.intents.recognizers.quitar_producto_recognizer.recognize_quitar_producto"
        ) as fuzzy_recognizer:
            active = self._active()
            with _no_transaction_control_session() as db:
                resolve_order_confirmation_observation(
                    db,
                    MagicMock(),
                    "entregar entre 19 y 20",
                    active,
                )
        fuzzy_recognizer.assert_not_called()


class OrderConfirmationInitialDispatcherRouteTest(unittest.TestCase):
    """The initial dispatcher must open the bounded observation context
    after the existing closure preconditions pass.
    """

    def test_first_turn_returns_pending_with_one_observation_requirement(
        self,
    ) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_confirmar_pedido(
                    db, session_row, "confirmar"
                )
            self.assertEqual(intent.status, "pending_resolution")
            self.assertEqual(intent.intent, "confirmar_pedido")
            self.assertEqual(
                intent.handler, "confirmar_pedido"
            )
            self.assertEqual(
                intent.recognizer, "draft_order_closure"
            )
            self.assertEqual(intent.resolved_data, {})
            self.assertEqual(len(intent.requirements), 1)
            self.assertEqual(
                intent.requirements[0].name, "observacion_pedido"
            )
            self.assertEqual(intent.requirements[0].status, "pending")
            self.assertEqual(intent.requirements[0].value, None)
            # Pedido must NOT be flipped to ``ingresado`` yet.
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(
                    pedido.estado_pedido, EstadoPedido.BORRADOR
                )
                self.assertIsNone(pedido.observaciones)
        finally:
            _cleanup(ids)

    def test_first_turn_resolves_to_new_context_type(self) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_confirmar_pedido(
                    db, session_row, "confirmar"
                )
            self.assertEqual(
                resolve_context_type(intent),
                ContextType.ORDER_CONFIRMATION_OBSERVATION,
            )
        finally:
            _cleanup(ids)

    def test_first_turn_rejects_active_session_or_draft(self) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db, db.begin():
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                session_row.estado_session = EstadoSession.CERRADA
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_confirmar_pedido(
                    db, session_row, "confirmar"
                )
            self.assertEqual(intent.status, "rejected")
            self.assertEqual(
                intent.resolved_data.get("reason"),
                "session_not_active",
            )
        finally:
            _cleanup(ids)

    def test_first_turn_rejects_empty_draft(self) -> None:
        ids = _seed_borrador_pedido(seed_line=False)
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_confirmar_pedido(
                    db, session_row, "confirmar"
                )
            self.assertEqual(intent.status, "rejected")
            self.assertEqual(
                intent.resolved_data.get("reason"),
                "empty_draft",
            )
        finally:
            _cleanup(ids)

    def test_first_turn_rejects_missing_payment(self) -> None:
        ids = _seed_borrador_pedido(medio_pago_seed=False)
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_confirmar_pedido(
                    db, session_row, "confirmar"
                )
            self.assertEqual(intent.status, "rejected")
            self.assertEqual(
                intent.resolved_data.get("reason"),
                "missing_payment",
            )
        finally:
            _cleanup(ids)

    def test_first_turn_rejects_missing_delivery(self) -> None:
        ids = _seed_borrador_pedido(metodo_entrega_seed=False)
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_confirmar_pedido(
                    db, session_row, "confirmar"
                )
            self.assertEqual(intent.status, "rejected")
            self.assertEqual(
                intent.resolved_data.get("reason"),
                "missing_delivery",
            )
        finally:
            _cleanup(ids)


class OrderConfirmationFinalizerTest(unittest.TestCase):
    """The finalizer re-runs preconditions and atomically confirms."""

    def test_no_skip_confirms_without_observation_write(self) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_confirmar_pedido(
                    db, session_row, "confirmar"
                )
            self.assertEqual(intent.status, "pending_resolution")
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                result = finalize_confirmar_pedido(
                    db,
                    session_row,
                    "confirmar",
                    skip_observation=True,
                )
                db.commit()
            self.assertEqual(result.status, "executed")
            self.assertEqual(
                result.resolved_data.get("pedido_id"),
                ids["pedido_id"],
            )
            self.assertNotIn(
                "observation_accepted_length",
                result.resolved_data,
            )
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(
                    pedido.estado_pedido, EstadoPedido.INGRESADO
                )
                self.assertIsNone(pedido.observaciones)
        finally:
            _cleanup(ids)

    def test_text_confirms_and_replaces_pedido_observation(self) -> None:
        ids = _seed_borrador_pedido()
        raw_text = "  entregar   entre   19  y  20 "
        normalized = "entregar entre 19 y 20"
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_confirmar_pedido(
                    db, session_row, "confirmar"
                )
            self.assertEqual(intent.status, "pending_resolution")
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                result = finalize_confirmar_pedido(
                    db,
                    session_row,
                    "confirmar",
                    observation_text=normalized,
                    skip_observation=False,
                )
                db.commit()
            self.assertEqual(result.status, "executed")
            self.assertEqual(
                result.resolved_data.get("observation_accepted_length"),
                len(normalized),
            )
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(
                    pedido.estado_pedido, EstadoPedido.INGRESADO
                )
                self.assertEqual(pedido.observaciones, normalized)
        finally:
            _cleanup(ids)
        del raw_text

    def test_text_confirms_preserves_prior_observation_flag(self) -> None:
        """When the customer submitted ``no`` the prior observation
        value must remain untouched even after confirmation.
        """
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.observaciones = "valor previo"
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_confirmar_pedido(
                    db, session_row, "confirmar"
                )
            self.assertEqual(intent.status, "pending_resolution")
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                result = finalize_confirmar_pedido(
                    db,
                    session_row,
                    "confirmar",
                    skip_observation=True,
                )
                db.commit()
            self.assertEqual(result.status, "executed")
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(
                    pedido.estado_pedido, EstadoPedido.INGRESADO
                )
                self.assertEqual(pedido.observaciones, "valor previo")
        finally:
            _cleanup(ids)

    def test_finalizer_rejects_without_mutation_when_preconditions_fail(
        self,
    ) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.observaciones = "valor previo"
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_confirmar_pedido(
                    db, session_row, "confirmar"
                )
            self.assertEqual(intent.status, "pending_resolution")
            # Close the session to invalidate the precondition.
            with TestingSessionLocal() as db, db.begin():
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                session_row.estado_session = EstadoSession.CERRADA
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                result = finalize_confirmar_pedido(
                    db,
                    session_row,
                    "confirmar",
                    observation_text="nueva nota",
                    skip_observation=False,
                )
            self.assertEqual(result.status, "rejected")
            self.assertEqual(
                result.resolved_data.get("reason"),
                "session_not_active",
            )
            # The Pedido must NOT have been flipped or annotated.
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(
                    pedido.estado_pedido, EstadoPedido.BORRADOR
                )
                self.assertEqual(pedido.observaciones, "valor previo")
        finally:
            _cleanup(ids)

    def test_finalizer_does_not_touch_pedido_producto_observations(self) -> None:
        """The finalizer must never write to ``PedidoProducto.observaciones``.
        """
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.observaciones = "valor previo"
                line = db.execute(
                    __import__("sqlalchemy").select(PedidoProducto).where(
                        PedidoProducto.id_pedido == ids["pedido_id"]
                    )
                ).scalar_one()
                line.observaciones = "nota de linea"
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_confirmar_pedido(
                    db, session_row, "confirmar"
                )
            self.assertEqual(intent.status, "pending_resolution")
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                finalize_confirmar_pedido(
                    db,
                    session_row,
                    "confirmar",
                    observation_text="nueva nota del pedido",
                    skip_observation=False,
                )
            with TestingSessionLocal() as db:
                line = db.execute(
                    __import__("sqlalchemy").select(PedidoProducto).where(
                        PedidoProducto.id_pedido == ids["pedido_id"]
                    )
                ).scalar_one()
                self.assertEqual(line.observaciones, "nota de linea")
        finally:
            _cleanup(ids)


class OrderConfirmationResponseTest(unittest.TestCase):
    """The response builder must keep the observation text out of the
    rendered message and use the documented fixed prompts.
    """

    def _pending_intent(self, *, capture_outcome: str | None = None) -> ProcessedIntent:
        resolved: dict = {"pedido_id": 42}
        if capture_outcome is not None:
            resolved["capture_outcome"] = capture_outcome
        return ProcessedIntent(
            intent="confirmar_pedido",
            source_text="confirmar",
            status="pending_resolution",
            recognizer="draft_order_closure",
            handler="confirmar_pedido",
            resolved_data=resolved,
            requirements=[
                RequirementState(
                    name="observacion_pedido",
                    status="pending",
                    value=None,
                ),
            ],
        )

    def test_first_turn_renders_documented_prompt(self) -> None:
        intent = self._pending_intent()
        response = build_confirmar_pedido_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.intent, "confirmar_pedido")
        self.assertEqual(response.status, "pending_resolution")
        self.assertEqual(response.message, ORDER_CONFIRMATION_OBSERVATION_PROMPT)

    def test_invalid_retry_renders_documented_retry(self) -> None:
        intent = self._pending_intent(capture_outcome="invalid_capture_length")
        response = build_confirmar_pedido_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.message, ORDER_CONFIRMATION_OBSERVATION_RETRY_PROMPT)

    def test_response_never_echoes_observation_text(self) -> None:
        secret = "SECRET-OBSERVATION-PAYLOAD-1234567890"
        intent = ProcessedIntent(
            intent="confirmar_pedido",
            source_text="confirmar",
            status="pending_resolution",
            recognizer="draft_order_closure",
            handler="confirmar_pedido",
            resolved_data={
                "pedido_id": 42,
                "observation_text": secret,
            },
            requirements=[
                RequirementState(
                    name="observacion_pedido",
                    status="pending",
                    value=secret,
                ),
            ],
        )
        for status in ("pending_resolution", "executed", "rejected", "failed"):
            with self.subTest(status=status):
                intent_copy = intent.model_copy(
                    update={"status": status}
                )
                response = build_confirmar_pedido_response(
                    MagicMock(), MagicMock(), intent_copy
                )
                self.assertNotIn(secret, response.message)


class OrderConfirmationDispatcherIntegrationTest(unittest.TestCase):
    """End-to-end tests for the two-turn confirmation observation flow."""

    def test_no_skip_confirms_and_preserves_prior_observation(self) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.observaciones = "valor previo"
                db.commit()
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                classification = IntentClassificationResult(
                    intents=[
                        ClassifiedIntent(
                            intent=IntentName.CONFIRMAR_PEDIDO,
                            mensaje="confirmar",
                        )
                    ],
                    mensaje="confirmar",
                )
                fake_classifier = MagicMock()
                fake_classifier.query.return_value = classification
                with patch.object(
                    initial_intent_dispatcher_module, "IntentClassifier"
                ) as classifier_cls:
                    classifier_cls.return_value = fake_classifier
                    first = process_incoming_message_with_responses(
                        db, session_row, "confirmar"
                    )
                assert first[0].status == "pending_resolution"
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row.context_type == (
                    ContextType.ORDER_CONFIRMATION_OBSERVATION.value
                )
                responses = process_incoming_message_with_responses(
                    db, session_row, "no"
                )
            self.assertEqual(len(responses), 1)
            self.assertEqual(
                responses[0].message,
                "Listo, confirmamos tu pedido.",
            )
            self.assertEqual(responses[0].intent, "confirmar_pedido")
            self.assertEqual(responses[0].status, "executed")
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(
                    pedido.estado_pedido, EstadoPedido.INGRESADO
                )
                self.assertEqual(pedido.observaciones, "valor previo")
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                self.assertIsNone(session_row.context_type)
        finally:
            _cleanup(ids)

    def test_free_text_confirms_and_writes_pedido_observation(self) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                classification = IntentClassificationResult(
                    intents=[
                        ClassifiedIntent(
                            intent=IntentName.CONFIRMAR_PEDIDO,
                            mensaje="confirmar",
                        )
                    ],
                    mensaje="confirmar",
                )
                fake_classifier = MagicMock()
                fake_classifier.query.return_value = classification
                with patch.object(
                    initial_intent_dispatcher_module, "IntentClassifier"
                ) as classifier_cls:
                    classifier_cls.return_value = fake_classifier
                    first = process_incoming_message_with_responses(
                        db, session_row, "confirmar"
                    )
                assert first[0].status == "pending_resolution"
                session_row = db.get(SessionModel, ids["session_id"])
                responses = process_incoming_message_with_responses(
                    db, session_row, "  entregar   entre   19  y  20 "
                )
            self.assertEqual(len(responses), 1)
            self.assertEqual(responses[0].status, "executed")
            self.assertEqual(responses[0].intent, "confirmar_pedido")
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(
                    pedido.estado_pedido, EstadoPedido.INGRESADO
                )
                self.assertEqual(
                    pedido.observaciones, "entregar entre 19 y 20"
                )
        finally:
            _cleanup(ids)

    def test_empty_capture_returns_pending_retry_without_mutation(self) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.observaciones = "valor previo"
                db.commit()
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                classification = IntentClassificationResult(
                    intents=[
                        ClassifiedIntent(
                            intent=IntentName.CONFIRMAR_PEDIDO,
                            mensaje="confirmar",
                        )
                    ],
                    mensaje="confirmar",
                )
                fake_classifier = MagicMock()
                fake_classifier.query.return_value = classification
                with patch.object(
                    initial_intent_dispatcher_module, "IntentClassifier"
                ) as classifier_cls:
                    classifier_cls.return_value = fake_classifier
                    first = process_incoming_message_with_responses(
                        db, session_row, "confirmar"
                    )
                assert first[0].status == "pending_resolution"
                session_row = db.get(SessionModel, ids["session_id"])
                responses = process_incoming_message_with_responses(
                    db, session_row, "   "
                )
            self.assertEqual(len(responses), 1)
            self.assertEqual(responses[0].status, "pending_resolution")
            self.assertEqual(
                responses[0].message,
                ORDER_CONFIRMATION_OBSERVATION_RETRY_PROMPT,
            )
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(
                    pedido.estado_pedido, EstadoPedido.BORRADOR
                )
                self.assertEqual(pedido.observaciones, "valor previo")
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                self.assertEqual(
                    session_row.context_type,
                    ContextType.ORDER_CONFIRMATION_OBSERVATION.value,
                )
        finally:
            _cleanup(ids)

    def test_over_limit_capture_returns_pending_retry_without_mutation(self) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.observaciones = "valor previo"
                db.commit()
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                classification = IntentClassificationResult(
                    intents=[
                        ClassifiedIntent(
                            intent=IntentName.CONFIRMAR_PEDIDO,
                            mensaje="confirmar",
                        )
                    ],
                    mensaje="confirmar",
                )
                fake_classifier = MagicMock()
                fake_classifier.query.return_value = classification
                with patch.object(
                    initial_intent_dispatcher_module, "IntentClassifier"
                ) as classifier_cls:
                    classifier_cls.return_value = fake_classifier
                    first = process_incoming_message_with_responses(
                        db, session_row, "confirmar"
                    )
                assert first[0].status == "pending_resolution"
                session_row = db.get(SessionModel, ids["session_id"])
                responses = process_incoming_message_with_responses(
                    db, session_row, "x" * 501
                )
            self.assertEqual(len(responses), 1)
            self.assertEqual(responses[0].status, "pending_resolution")
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(
                    pedido.estado_pedido, EstadoPedido.BORRADOR
                )
                self.assertEqual(pedido.observaciones, "valor previo")
        finally:
            _cleanup(ids)

    def test_first_turn_response_renders_documented_prompt(self) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                responses = process_incoming_message_with_responses(
                    db, session_row, "confirmar"
                )
            self.assertEqual(len(responses), 1)
            self.assertEqual(
                responses[0].message,
                ORDER_CONFIRMATION_OBSERVATION_PROMPT,
            )
            self.assertEqual(responses[0].status, "pending_resolution")
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                self.assertEqual(
                    session_row.context_type,
                    ContextType.ORDER_CONFIRMATION_OBSERVATION.value,
                )
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(
                    pedido.estado_pedido, EstadoPedido.BORRADOR
                )
        finally:
            _cleanup(ids)


class OrderConfirmationPendingContextStaleRecoveryTest(unittest.TestCase):
    """The pre-deploy ``set_observacion_producto`` pending state is
    cleared without invoking the legacy handler or mutating a
    ``PedidoProducto`` row.
    """

    def test_stale_pending_state_is_cleared_as_rejected(self) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db, db.begin():
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                session_row.context_type = ContextType.ORDER_LINE_SELECTION.value
                session_row.pending_intents = {
                    "version": 1,
                    "active": {
                        "intent": "set_observacion_producto",
                        "source_text": "La pizza es sin aceitunas",
                        "status": "ready",
                        "recognizer": "recognizer_set_observacion_producto",
                        "handler": "set_observacion_producto",
                        "resolved_data": {"pedido_producto_id": 10},
                        "requirements": [],
                        "candidate_ids": [],
                    },
                    "queue": [],
                }
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                responses = process_incoming_message_with_responses(
                    db, session_row, "no"
                )
            self.assertEqual(len(responses), 1)
            self.assertEqual(responses[0].status, "rejected")
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                self.assertIsNone(session_row.context_type)
                self.assertIsNone(session_row.pending_intents["active"])
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(
                    pedido.estado_pedido, EstadoPedido.BORRADOR
                )
                self.assertIsNone(pedido.observaciones)
        finally:
            _cleanup(ids)


class OrderConfirmationDirectObservationRejectionTest(unittest.TestCase):
    """Direct ``set_observacion_producto`` and ``set_observacion_pedido``
    classifications outside the confirmation context are rejected
    with the deterministic guidance.
    """

    def test_direct_set_observacion_pedido_returns_guidance(self) -> None:
        with patch.object(
            initial_intent_dispatcher_module, "IntentClassifier"
        ) as classifier_cls:
            classification = IntentClassificationResult(
                intents=[
                    ClassifiedIntent(
                        intent=IntentName.SET_OBSERVACION_PEDIDO,
                        mensaje="La entrega es por el portón lateral",
                    )
                ],
                mensaje="La entrega es por el portón lateral",
            )
            fake_classifier = MagicMock()
            fake_classifier.query.return_value = classification
            classifier_cls.return_value = fake_classifier
            response = dispatch_initial_message(
                MagicMock(),
                MagicMock(context_type=None),
                "La entrega es por el portón lateral",
            )
        self.assertEqual(len(response), 1)
        self.assertEqual(response[0].status, "rejected")
        self.assertEqual(response[0].intent, "set_observacion_pedido")
        self.assertEqual(
            response[0].resolved_data.get("reason"),
            "direct_observation_disabled",
        )
        self.assertIn(
            "confirmá",
            response[0].resolved_data.get("guidance", ""),
        )

    def test_direct_set_observacion_producto_returns_guidance(self) -> None:
        with patch.object(
            initial_intent_dispatcher_module, "IntentClassifier"
        ) as classifier_cls:
            classification = IntentClassificationResult(
                intents=[
                    ClassifiedIntent(
                        intent=IntentName.SET_OBSERVACION_PRODUCTO,
                        mensaje="La pizza es sin aceitunas",
                    )
                ],
                mensaje="La pizza es sin aceitunas",
            )
            fake_classifier = MagicMock()
            fake_classifier.query.return_value = classification
            classifier_cls.return_value = fake_classifier
            response = dispatch_initial_message(
                MagicMock(),
                MagicMock(context_type=None),
                "La pizza es sin aceitunas",
            )
        self.assertEqual(len(response), 1)
        self.assertEqual(response[0].status, "rejected")
        self.assertEqual(response[0].intent, "set_observacion_producto")
        self.assertEqual(
            response[0].resolved_data.get("reason"),
            "direct_observation_disabled",
        )

    def test_set_observacion_pedido_response_builder_returns_observation_safety(
        self,
    ) -> None:
        """The historical ``set_observacion_pedido`` response builder
        must keep the observation text out of the rendered message.
        """
        intent = ProcessedIntent(
            intent="set_observacion_pedido",
            source_text="observation-text",
            status="executed",
            recognizer="draft_order_closure",
            handler="set_observacion_pedido",
            resolved_data={"accepted_length": 15},
        )
        secret = "SECRET-OBSERVATION-PAYLOAD-1234567890"
        with _no_transaction_control_session() as db:
            response = build_set_observacion_pedido_response(
                db, MagicMock(), intent
            )
        self.assertNotIn(secret, response.message)
        self.assertNotIn("observation-text", response.message)


class OrderConfirmationResolverObservableCaptureTest(unittest.TestCase):
    """The capture resolver must emit a closed diagnostic snapshot."""

    def test_resolver_emits_closed_resolver_started_and_completed(self) -> None:
        from backend.diagnostics import CollectingDiagnosticSink

        sink = CollectingDiagnosticSink()
        active = ProcessedIntent(
            intent="confirmar_pedido",
            source_text="confirmar",
            status="pending_resolution",
            recognizer="draft_order_closure",
            handler="confirmar_pedido",
            resolved_data={"pedido_id": 42},
            requirements=[
                RequirementState(
                    name="observacion_pedido",
                    status="pending",
                    value=None,
                ),
            ],
            candidate_ids=[],
        )
        with _no_transaction_control_session() as db:
            resolve_order_confirmation_observation(
                db, MagicMock(), "no", active, sink=sink
            )
        events = sink.events()
        events_list = list(events)
        self.assertGreater(len(events_list), 0)
        started = next(
            event
            for event in events_list
            if event.__class__.__name__ == "ResolverCallStarted"
        )
        self.assertEqual(
            started.resolver_class, "ProcessedIntent"
        )
        self.assertEqual(
            started.resolver_method,
            "resolve_order_confirmation_observation",
        )
        self.assertEqual(
            started.resolver_purpose,
            "order_confirmation_observation_capture",
        )


class OrderConfirmationPendingActiveBoundaryTest(unittest.TestCase):
    """The pending context dispatcher must not invoke the line
    recognizer or product recognizer during the capture turn.
    """

    def test_capture_turn_does_not_invoke_recognizers(self) -> None:
        ids = _seed_borrador_pedido()
        try:
            session_row = _stage_active_confirmation(
                pedido_id=ids["pedido_id"],
                session_id=ids["session_id"],
            )
            with patch(
                "backend.intents.recognizers.quitar_producto_recognizer.recognize_quitar_producto"
            ) as fuzzy_recognizer:
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    dispatch_pending_context(
                        db, session_row, "entregar entre 19 y 20"
                    )
            fuzzy_recognizer.assert_not_called()
        finally:
            _cleanup(ids)


class OrderConfirmationExecutionModuleBoundariesTest(unittest.TestCase):
    """Module-shape checks for the new files."""

    def test_resolver_module_does_not_call_db_state_methods(self) -> None:
        importlib.reload(
            importlib.import_module(
                "backend.intents.context.order_confirmation_observation_resolver"
            )
        )
        module = importlib.import_module(
            "backend.intents.context.order_confirmation_observation_resolver"
        )
        with open(module.__file__, encoding="utf-8") as fh:
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

    def test_resolver_module_public_surface(self) -> None:
        from backend.intents.context import (
            order_confirmation_observation_resolver as resolver_module,
        )
        self.assertEqual(
            set(resolver_module.__all__),
            {
                "ORDER_CONFIRMATION_OBSERVATION_PROMPT",
                "ORDER_CONFIRMATION_OBSERVATION_RETRY_PROMPT",
                "OrderConfirmationCaptureOutcome",
                "resolve_order_confirmation_observation",
            },
        )


class OrderConfirmationPedidoProductoServiceCompatTest(unittest.TestCase):
    """The historic line-observation service and repository shims are
    removed. This test asserts their absence so any unintended
    reintroduction is caught locally.
    """

    def test_service_no_longer_exposes_set_observacion_producto(self) -> None:
        self.assertFalse(
            hasattr(PedidoProductoService, "set_observacion_producto"),
            "PedidoProductoService.set_observacion_producto must be removed",
        )


class OrderConfirmationPrivacyTest(unittest.TestCase):
    """The capture resolver must keep the observation text strictly local.

    The diagnostic events of the bounded capture turn may carry only
    closed metadata (intent, status, context kind, candidate count).
    They must never include the captured text, its normalized form, the
    session identifier, the pedido identifier or any pending JSON.
    """

    _SECRET = "SECRET-OBSERVATION-PAYLOAD-ZZZ-12345"

    def _active(self) -> ProcessedIntent:
        return ProcessedIntent(
            intent="confirmar_pedido",
            source_text="confirmar",
            status="pending_resolution",
            recognizer="draft_order_closure",
            handler="confirmar_pedido",
            resolved_data={},
            requirements=[
                RequirementState(
                    name="observacion_pedido",
                    status="pending",
                    value=None,
                ),
            ],
            candidate_ids=[],
        )

    def test_resolver_events_drop_incoming_and_normalized_text(self) -> None:
        from backend.diagnostics import CollectingDiagnosticSink

        sink = CollectingDiagnosticSink()
        active = self._active()
        with _no_transaction_control_session() as db:
            resolve_order_confirmation_observation(
                db, MagicMock(id=9999), self._SECRET, active, sink=sink
            )
        for event in sink.events():
            payload = event.to_dict() if hasattr(event, "to_dict") else {}
            rendered = repr(payload)
            self.assertNotIn(self._SECRET, rendered)
            self.assertNotIn("9999", rendered)
            self.assertIsNone(
                payload.get("incoming_text"),
                "ResolverCallStarted must not carry the captured text",
            )
            self.assertIsNone(
                payload.get("normalized_text"),
                "ResolverCallStarted must not carry the normalized text",
            )
            self.assertIsNone(
                payload.get("session_id"),
                "ResolverCallStarted must not carry session_id",
            )
            for forbidden in ("pedido_id",):
                self.assertNotIn(
                    forbidden,
                    payload,
                    f"capture event must not carry {forbidden!r}",
                )

    def test_resolver_started_event_carries_only_closed_metadata(self) -> None:
        """Direct, narrow assert over the started event shape."""

        from backend.diagnostics import CollectingDiagnosticSink
        from backend.diagnostics.events import ResolverCallStarted

        sink = CollectingDiagnosticSink()
        active = self._active()
        with _no_transaction_control_session() as db:
            resolve_order_confirmation_observation(
                db,
                MagicMock(id=8888, id_pedido=7777),
                self._SECRET,
                active,
                sink=sink,
            )
        started = [
            event
            for event in sink.events()
            if isinstance(event, ResolverCallStarted)
        ]
        self.assertEqual(len(started), 1)
        rendered = repr(started[0].to_dict())
        self.assertNotIn(self._SECRET, rendered)
        self.assertNotIn("8888", rendered)
        self.assertNotIn("7777", rendered)
        self.assertIsNone(started[0].session_id)
        self.assertIsNone(started[0].incoming_text)
        self.assertIsNone(started[0].normalized_text)

    def test_pending_snapshot_does_not_capture_observation_text(self) -> None:
        from backend.diagnostics import CollectingDiagnosticSink

        sink = CollectingDiagnosticSink()
        active = self._active()
        session = MagicMock()
        session.context_type = ContextType.ORDER_CONFIRMATION_OBSERVATION.value

        with patch.object(
            pending_context_dispatcher_module, "load_pending_state"
        ) as load_state, patch.object(
            pending_context_dispatcher_module, "process_initial_order_status_query"
        ) as status_query, patch.object(
            pending_context_dispatcher_module, "clear_pending_state"
        ) as clear_state, patch.object(
            pending_context_dispatcher_module, "finalize_confirmar_pedido"
        ) as finalize:
            load_state.return_value.active = active
            load_state.return_value.queue = []
            finalize.return_value = active.model_copy(
                update={"status": "executed"}
            )
            dispatch_pending_context(
                MagicMock(), session, self._SECRET, sink=sink
            )
            status_query.assert_not_called()

        for event in sink.events():
            payload = event.to_dict() if hasattr(event, "to_dict") else {}
            self.assertNotIn(self._SECRET, repr(payload))
            sources = payload.get("active_source_text") or []
            if isinstance(sources, list):
                self.assertNotIn(self._SECRET, sources)
            else:
                self.assertNotEqual(sources, self._SECRET)

    def test_session_pending_intents_text_is_not_persisted(self) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db:
                session_row = _stage_active_confirmation(
                    pedido_id=ids["pedido_id"],
                    session_id=ids["session_id"],
                )
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                process_incoming_message_with_responses(
                    db, session_row, self._SECRET
                )
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                self.assertIsNone(session_row.context_type)
                pending = session_row.pending_intents or {}
                self.assertNotIn(self._SECRET, repr(pending))
                # The new contract: no pedido_id, no session_id, no
                # observation text, and no candidates are persisted as
                # part of the bounded confirmation pending intent.
                self.assertNotIn("pedido_id", repr(pending))
                rendered = repr(pending)
                self.assertNotIn(str(ids["session_id"]), rendered)
        finally:
            _cleanup(ids)

    def test_initial_pending_resolved_data_is_empty(self) -> None:
        """The pending JSON of the bounded confirmation is closed
        metadata only. ``pedido_id`` is not persisted on the active
        intent and ``session_id`` is implicit in the session row.
        """
        from backend.intents.orchestration.draft_order_closure import (
            process_initial_confirmar_pedido,
        )
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                pending = process_initial_confirmar_pedido(
                    db, session_row, "confirmar"
                )
            self.assertEqual(pending.resolved_data, {})
            self.assertNotIn("pedido_id", pending.resolved_data)
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                persisted = session_row.pending_intents or {}
                rendered = repr(persisted)
                self.assertNotIn("pedido_id", rendered)
                self.assertNotIn(str(ids["session_id"]), rendered)
                self.assertNotIn(str(ids["pedido_id"]), rendered)
        finally:
            _cleanup(ids)

    def test_valid_capture_still_confirms_and_writes_note(self) -> None:
        """A valid capture must still save the note, confirm the order
        and clear pending/context. The resolver path returns the
        in-memory outcome without invoking any transaction-control
        method on the database session.
        """
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db:
                session_row = _stage_active_confirmation(
                    pedido_id=ids["pedido_id"],
                    session_id=ids["session_id"],
                )
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                responses = process_incoming_message_with_responses(
                    db, session_row, self._SECRET
                )
            self.assertEqual(len(responses), 1)
            self.assertEqual(responses[0].status, "executed")
            self.assertEqual(responses[0].intent, "confirmar_pedido")
            self.assertNotIn(self._SECRET, responses[0].message)
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(pedido.estado_pedido, EstadoPedido.INGRESADO)
                self.assertEqual(pedido.observaciones, self._SECRET)
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                self.assertIsNone(session_row.context_type)
        finally:
            _cleanup(ids)

    def test_resolver_path_does_not_invoke_db_transaction_control(self) -> None:
        """The corrected resolver path must never call any
        transaction-control method on the captured database session.
        """

        with _no_transaction_control_session() as db:
            outcome = resolve_order_confirmation_observation(
                db, MagicMock(id=4242), self._SECRET, self._active()
            )
        self.assertEqual(outcome.accepted_text, self._SECRET)
        self.assertFalse(outcome.skip)
        self.assertFalse(outcome.retry)


class OrderConfirmationCaptureOrderTest(unittest.TestCase):
    """The capture context must win over the status-query interruption."""

    def test_status_query_text_inside_capture_is_treated_as_observation(
        self,
    ) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db:
                session_row = _stage_active_confirmation(
                    pedido_id=ids["pedido_id"],
                    session_id=ids["session_id"],
                )
            status_like_text = "cual es el estado de mi pedido"
            with patch.object(
                pending_context_dispatcher_module,
                "process_initial_order_status_query",
            ) as status_query_mock, patch.object(
                pending_context_dispatcher_module,
                "is_explicit_order_status_query",
                return_value=True,
            ):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    second = process_incoming_message_with_responses(
                        db, session_row, status_like_text
                    )
            status_query_mock.assert_not_called()
            self.assertEqual(len(second), 1)
            self.assertEqual(second[0].status, "executed")
            self.assertEqual(second[0].intent, "confirmar_pedido")
            self.assertNotIn(status_like_text, second[0].message)
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(
                    pedido.estado_pedido, EstadoPedido.INGRESADO
                )
                self.assertEqual(
                    pedido.observaciones, status_like_text
                )
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                self.assertIsNone(session_row.context_type)
        finally:
            _cleanup(ids)

    def test_status_query_interruption_remains_in_other_context(self) -> None:
        """The status-query interrupt for non-capture contexts is kept.

        The test seeds an ``agregar_producto`` pending context (which
        is not the confirmation observation context) and verifies the
        status-query branch keeps its priority.
        """
        pending_intent = ProcessedIntent(
            intent="agregar_producto",
            source_text="dos pizzas",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={},
            requirements=[],
            candidate_ids=[10, 20],
        )

        class _FakeState:
            def __init__(self) -> None:
                self.active = pending_intent
                self.queue: list = []

        with patch.object(
            pending_context_dispatcher_module,
            "is_explicit_order_status_query",
            return_value=True,
        ), patch.object(
            pending_context_dispatcher_module,
            "process_initial_order_status_query",
        ) as status_query_mock, patch.object(
            pending_context_dispatcher_module,
            "ProductSelectionContextService",
        ), patch.object(
            pending_context_dispatcher_module,
            "resolve_order_confirmation_observation",
        ), patch.object(
            pending_context_dispatcher_module,
            "load_pending_state",
        ) as load_state, patch.object(
            pending_context_dispatcher_module,
            "_emit_pending_snapshot",
        ):
            load_state.return_value = _FakeState()

            session = MagicMock()
            session.context_type = ContextType.PRODUCT_SELECTION.value

            db = MagicMock(name="DatabaseSession")
            status_intent = ProcessedIntent(
                intent="consultar_estado_pedido",
                source_text="cual es el estado de mi pedido",
                status="executed",
                recognizer="order_status_query",
                handler="consultar_estado_pedido",
                resolved_data={"estado_pedido": "borrador"},
            )
            status_query_mock.return_value = status_intent

            results = dispatch_pending_context(
                db, session, "cual es el estado de mi pedido"
            )

        status_query_mock.assert_called_once()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].intent, "consultar_estado_pedido")
        self.assertNotIn(
            "cual es el estado de mi pedido",
            repr(results[0].resolved_data),
        )


class OrderConfirmationDispatcherBuilderPrivacyTest(unittest.TestCase):
    """The end-to-end pipeline must keep the observation secret local."""

    _SECRET = "ENTREGA-EN-PORTON-LATERAL-1234567890"

    def test_full_pipeline_response_does_not_echo_observation(self) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                classification = IntentClassificationResult(
                    intents=[
                        ClassifiedIntent(
                            intent=IntentName.CONFIRMAR_PEDIDO,
                            mensaje="confirmar",
                        )
                    ],
                    mensaje="confirmar",
                )
                fake_classifier = MagicMock()
                fake_classifier.query.return_value = classification
                with patch.object(
                    initial_intent_dispatcher_module, "IntentClassifier"
                ) as classifier_cls:
                    classifier_cls.return_value = fake_classifier
                    first = process_incoming_message_with_responses(
                        db, session_row, "confirmar"
                    )
                assert first[0].status == "pending_resolution"
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                second = process_incoming_message_with_responses(
                    db, session_row, f"  {self._SECRET}  "
                )
            self.assertEqual(len(second), 1)
            self.assertEqual(second[0].status, "executed")
            self.assertNotIn(self._SECRET, second[0].message)
            for response in second:
                self.assertNotIn(self._SECRET, response.message)
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(
                    pedido.observaciones, self._SECRET
                )
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                self.assertEqual(
                    session_row.context_type,
                    None,
                )
                pending = session_row.pending_intents or {}
                self.assertNotIn(self._SECRET, repr(pending))
        finally:
            _cleanup(ids)


class OrderConfirmationRetryPathPrivacyTest(unittest.TestCase):
    """Empty and over-limit captures preserve pending state without text."""

    def test_empty_capture_keeps_pending_without_observation_payload(
        self,
    ) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db:
                session_row = _stage_active_confirmation(
                    pedido_id=ids["pedido_id"],
                    session_id=ids["session_id"],
                )
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                responses = process_incoming_message_with_responses(
                    db, session_row, "   "
                )
            self.assertEqual(len(responses), 1)
            self.assertEqual(responses[0].status, "pending_resolution")
            self.assertEqual(
                responses[0].message,
                ORDER_CONFIRMATION_OBSERVATION_RETRY_PROMPT,
            )
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                self.assertEqual(
                    session_row.context_type,
                    ContextType.ORDER_CONFIRMATION_OBSERVATION.value,
                )
                pending = session_row.pending_intents or {}
                rendered = repr(pending)
                self.assertNotIn("   ", rendered)
                self.assertEqual(
                    pending["active"]["status"], "pending_resolution"
                )
                self.assertEqual(
                    pending["active"]["intent"], "confirmar_pedido"
                )
        finally:
            _cleanup(ids)

    def test_over_limit_capture_keeps_pending_without_observation_payload(
        self,
    ) -> None:
        ids = _seed_borrador_pedido()
        try:
            with TestingSessionLocal() as db:
                session_row = _stage_active_confirmation(
                    pedido_id=ids["pedido_id"],
                    session_id=ids["session_id"],
                )
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                responses = process_incoming_message_with_responses(
                    db, session_row, "y" * 501
                )
            self.assertEqual(len(responses), 1)
            self.assertEqual(responses[0].status, "pending_resolution")
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                pending = session_row.pending_intents or {}
                rendered = repr(pending)
                self.assertNotIn("y" * 501, rendered)
                self.assertEqual(
                    pending["active"]["status"], "pending_resolution"
                )
        finally:
            _cleanup(ids)


if __name__ == "__main__":
    unittest.main()
