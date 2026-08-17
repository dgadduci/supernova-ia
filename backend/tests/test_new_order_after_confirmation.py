"""Focused tests for the explicit `iniciar_pedido` dispatch and transition.

Covers:

* dispatcher branch routing, executed transition persistence, and the
  per-state outcomes for `ingresado`, `preparacion`, `terminado`,
  `entregado`, `cancelado`, `borrador`, missing pedido, and non-active
  session;
* preservation of history (no copy of lines, payment, delivery,
  observaciones, pending state, or session context) and
  commerce/client isolation;
* provider-coordinator rollback after a technical failure;
* deterministic response mapping for the new intent, including the
  dispatcher unit guarantee that later intents are not executed after a
  successful transition;
* focused dispatcher regression regressions.
"""
from __future__ import annotations

import importlib
import unittest
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import sessionmaker

from backend.intents.orchestration import (
    initial_intent_dispatcher as dispatcher_module,
)
from backend.intents.orchestration import (
    new_order_after_confirmation as orchestrator_module,
)
from backend.intents.orchestration.initial_intent_dispatcher import (
    dispatch_initial_message,
)
from backend.intents.orchestration.new_order_after_confirmation import (
    process_initial_iniciar_pedido,
)
from backend.intents.responses import (
    new_order_after_confirmation as response_module,
)
from backend.intents.responses.new_order_after_confirmation import (
    build_iniciar_pedido_response,
)
from backend.intents.schemas.intent_classification import (
    ClassifiedIntent,
    IntentClassificationResult,
    IntentName,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models import (
    CanalWhatsapp,
    CanalWhatsappMode,
    CategoriaProducto,
    Cliente,
    Comercio,
    ComercioCanalCompartido,
    ContextoClienteCanalWhatsapp,
    EstadoComercio,
    EstadoPedido,
    MensajeProveedorSaliente,
    Pedido,
    PedidoProducto,
    Precio,
    Presentacion,
    ProcesamientoMensajeProveedor,
    ProcesamientoMensajeProveedorEstado,
    Producto,
    ProductoPresentacion,
    RecepcionMensajeProveedor,
)
from backend.models import Session as SessionModel
from backend.models.session import EstadoSession
from backend.services.outbound_response_mapper import (
    GENERIC_MESSAGE,
    build_customer_responses,
)
from backend.services.provider_inbound_message_coordinator import (
    ProviderInboundMessageCommand,
    ProviderInboundMessageCoordinator,
    ProviderInboundMessageStatus,
    ProviderInboundProcessingOutcome,
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


def _seed_active_session(
    *,
    pedido_estado: EstadoPedido,
    populate_lines: bool = False,
) -> dict:
    suffix = _suffix()
    estado_id = _estado_id_activo()
    with TestingSessionLocal() as db, db.begin():
        comercio = Comercio(
            nombre_fantasia=f"Test {suffix}",
            nombre_corto=f"TC {suffix}",
            razon_social=f"Test Comercio SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+5491{suffix[:8]}",
            calle="Av. Test",
            numero="1234",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"test-comercio-{suffix}",
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
            pending_intents={
                "noise": "must_not_be_copied",
            },
            context_type="must_not_be_copied",
        )
        db.add(session_row)
        db.flush()

        pedido = Pedido(
            id_session=session_row.id,
            id_medio_pago=None,
            id_metodo_entrega=None,
            datetime_entrega_programada=None,
            estado_pedido=pedido_estado,
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
            nombre=f"Pizza {suffix}",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        db.add(producto)
        db.flush()
        presentacion = Presentacion(
            id_comercio=comercio.id,
            codigo=f"unidad-{suffix}",
            descripcion=f"Unidad {suffix}",
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
        db.add(
            Precio(id_producto_presentacion=assoc.id, precio=Decimal("100.00"))
        )
        db.flush()

        if populate_lines:
            db.add(
                PedidoProducto(
                    id_pedido=pedido.id,
                    id_producto_presentacion=assoc.id,
                    cantidad=2,
                    precio_unitario=Decimal("100.00"),
                )
            )
            db.flush()

        return {
            "comercio_id": comercio.id,
            "cliente_id": cliente.id,
            "session_id": session_row.id,
            "pedido_id": pedido.id,
            "producto_id": producto.id,
            "categoria_id": categoria.id,
            "pp_id": assoc.id,
        }


def _cleanup(ids: dict) -> None:
    with TestingSessionLocal() as db, db.begin():
        db.execute(
            SessionModel.__table__.update()
            .where(
                SessionModel.id_comercio == ids["comercio_id"],
                SessionModel.id_cliente == ids["cliente_id"],
            )
            .values(id_pedido=None)
        )
        db.execute(
            delete(Pedido).where(
                Pedido.id_session.in_(
                    select(SessionModel.id).where(
                        SessionModel.id_comercio == ids["comercio_id"],
                        SessionModel.id_cliente == ids["cliente_id"],
                    )
                )
            )
        )
        db.execute(
            delete(SessionModel).where(
                SessionModel.id_comercio == ids["comercio_id"],
                SessionModel.id_cliente == ids["cliente_id"],
            )
        )
        db.execute(
            delete(Precio).where(Precio.id_producto_presentacion == ids["pp_id"])
        )
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
        db.execute(delete(Cliente).where(Cliente.id == ids["cliente_id"]))
        db.execute(
            delete(Comercio).where(Comercio.id == ids["comercio_id"])
        )


def _seed_provider_iniciar_pedido_scenario(
    *,
    pedido_estado: EstadoPedido,
) -> dict:
    """Seed commerce + cliente + dedicated canal + active session.

    Returns the ids and identifiers needed to drive the real
    ``ProviderInboundMessageCoordinator.accept`` /
    ``claim_due_processing`` / ``process_lease`` path through a
    real receipt/work lease for a session whose associated pedido is
    in the supplied state. ``context_type`` is intentionally ``None``
    so the dispatcher actually runs and reaches
    ``process_initial_iniciar_pedido``.
    """
    suffix = _suffix()
    estado_id = _estado_id_activo()
    destination = f"+54961{suffix[:8]}"
    with TestingSessionLocal() as db, db.begin():
        comercio = Comercio(
            nombre_fantasia=f"Test {suffix}",
            nombre_corto=f"TC {suffix}",
            razon_social=f"Test Comercio SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+5491{suffix[:8]}",
            calle="Av. Test",
            numero="1234",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"test-comercio-{suffix}",
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

        canal = CanalWhatsapp(
            provider="twilio",
            destination_e164=destination,
            mode=CanalWhatsappMode.DEDICATED,
            id_comercio_exclusivo=comercio.id,
            activo=True,
        )
        db.add(canal)
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
            id_session=int(session_row.id),
            id_medio_pago=None,
            id_metodo_entrega=None,
            datetime_entrega_programada=None,
            estado_pedido=pedido_estado,
        )
        db.add(pedido)
        db.flush()
        session_row.id_pedido = int(pedido.id)
        db.flush()

        return {
            "comercio_id": int(comercio.id),
            "cliente_id": int(cliente.id),
            "canal_id": int(canal.id),
            "destination": destination,
            "session_id": int(session_row.id),
            "pedido_id": int(pedido.id),
            "suffix": suffix,
        }


def _cleanup_provider_iniciar_pedido_scenario(ids: dict) -> None:
    """Remove every row created by ``_seed_provider_iniciar_pedido_scenario``.

    Mirrors the cleanup order used in
    ``test_provider_message_receipt_core_integration`` so that
    ``sessions.id_pedido`` FK is nulled before the pedido rows are
    removed, and so the canal/comercio are dropped after every row
    that references them.
    """
    comercio_id = ids["comercio_id"]
    cliente_id = ids["cliente_id"]
    canal_id = ids["canal_id"]

    with TestingSessionLocal() as db, db.begin():
        db.execute(
            delete(MensajeProveedorSaliente).where(
                MensajeProveedorSaliente.recepcion_mensaje_proveedor_id.in_(
                    select(RecepcionMensajeProveedor.id).where(
                        RecepcionMensajeProveedor.comercio_id == comercio_id
                    )
                )
            )
        )
        db.execute(
            delete(ProcesamientoMensajeProveedor).where(
                ProcesamientoMensajeProveedor.recepcion_mensaje_proveedor_id.in_(
                    select(RecepcionMensajeProveedor.id).where(
                        RecepcionMensajeProveedor.comercio_id == comercio_id
                    )
                )
            )
        )
        db.execute(
            delete(RecepcionMensajeProveedor).where(
                RecepcionMensajeProveedor.canal_id == canal_id
            )
        )
        db.execute(
            text(
                "UPDATE sessions SET id_pedido = NULL "
                "WHERE id_comercio = :cid"
            ),
            {"cid": comercio_id},
        )
        db.execute(
            delete(Pedido).where(
                Pedido.id_session.in_(
                    select(SessionModel.id).where(
                        SessionModel.id_comercio == comercio_id
                    )
                )
            )
        )
        db.execute(
            delete(SessionModel).where(
                SessionModel.id_comercio == comercio_id
            )
        )
        db.execute(
            delete(ContextoClienteCanalWhatsapp).where(
                ContextoClienteCanalWhatsapp.canal_id == canal_id
            )
        )
        db.execute(
            delete(ComercioCanalCompartido).where(
                ComercioCanalCompartido.canal_id == canal_id
            )
        )
        db.execute(delete(CanalWhatsapp).where(CanalWhatsapp.id == canal_id))
        db.execute(
            delete(ContextoClienteCanalWhatsapp).where(
                ContextoClienteCanalWhatsapp.cliente_id == cliente_id
            )
        )
        db.execute(delete(Cliente).where(Cliente.id == cliente_id))
        db.execute(delete(Comercio).where(Comercio.id == comercio_id))


def _build_classifier_result(
    *items: tuple[IntentName, str],
) -> IntentClassificationResult:
    return IntentClassificationResult(
        intents=[
            ClassifiedIntent(intent=name, mensaje=message)
            for name, message in items
        ],
        mensaje=items[0][1] if items else "x",
    )


def _mock_session(context_type=None):
    session = MagicMock(name="ConversationSession")
    session.context_type = context_type
    return session


def _mock_outbox_repo() -> MagicMock:
    repo = MagicMock(name="MensajeProveedorSalienteRepository")

    class _Row:
        def __init__(self, sequence: int) -> None:
            self.id = sequence + 1
            self.sequence = sequence

    def _stage(*args, **kwargs):  # type: ignore[no-untyped-def]
        sequence = kwargs.get("sequence", 0)
        return _Row(sequence)

    repo.stage.side_effect = _stage
    return repo


class DispatchIniciarPedidoHappyPathTest(unittest.TestCase):
    @patch.object(dispatcher_module, "process_initial_agregar_producto")
    @patch.object(dispatcher_module, "process_initial_iniciar_pedido")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_iniciar_pedido_calls_new_order_orchestrator(
        self, classifier_cls, orchestrator, agregar_orch
    ):
        sentinel = ProcessedIntent(
            intent="iniciar_pedido",
            source_text="quiero hacer otro pedido",
            status="executed",
            recognizer="new_order_after_confirmation",
            handler="iniciar_pedido",
            resolved_data={
                "predecessor_session_id": 1,
                "predecessor_pedido_id": 2,
                "successor_session_id": 3,
                "successor_pedido_id": 4,
            },
        )
        orchestrator.return_value = sentinel
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_classifier_result(
            (IntentName.INICIAR_PEDIDO, "quiero hacer otro pedido"),
        )
        classifier_cls.return_value = classifier_instance

        db = MagicMock(name="DatabaseSession")
        session = _mock_session(context_type=None)

        result = dispatch_initial_message(
            db, session, "quiero hacer otro pedido"
        )

        classifier_instance.query.assert_called_once_with(
            "quiero hacer otro pedido"
        )
        orchestrator.assert_called_once_with(
            db, session, "quiero hacer otro pedido"
        )
        agregar_orch.assert_not_called()
        self.assertEqual(result, [sentinel])


class DispatchIniciarPedidoActiveBoundaryTest(unittest.TestCase):
    @patch.object(dispatcher_module, "process_initial_agregar_producto")
    @patch.object(dispatcher_module, "process_initial_iniciar_pedido")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_later_intent_is_not_executed_after_successful_iniciar_pedido(
        self, classifier_cls, orchestrator, agregar_orch
    ):
        transition = ProcessedIntent(
            intent="iniciar_pedido",
            source_text="quiero hacer otro pedido",
            status="executed",
            recognizer="new_order_after_confirmation",
            handler="iniciar_pedido",
            resolved_data={
                "successor_session_id": 99,
                "successor_pedido_id": 100,
            },
        )
        orchestrator.return_value = transition
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_classifier_result(
            (IntentName.INICIAR_PEDIDO, "quiero hacer otro pedido"),
            (IntentName.AGREGAR_PRODUCTO, "una pizza"),
        )
        classifier_cls.return_value = classifier_instance

        db = MagicMock(name="DatabaseSession")
        session = _mock_session(context_type=None)

        result = dispatch_initial_message(
            db, session, "otro pedido y una pizza"
        )

        self.assertEqual(result, [transition])
        orchestrator.assert_called_once_with(
            db, session, "quiero hacer otro pedido"
        )
        agregar_orch.assert_not_called()

    @patch.object(dispatcher_module, "process_initial_agregar_producto")
    @patch.object(dispatcher_module, "process_initial_iniciar_pedido")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_later_intent_still_processed_when_iniciar_pedido_was_rejected(
        self, classifier_cls, orchestrator, agregar_orch
    ):
        rejected = ProcessedIntent(
            intent="iniciar_pedido",
            source_text="hace otro pedido",
            status="rejected",
            recognizer="new_order_after_confirmation",
            handler="iniciar_pedido",
            resolved_data={"reason": "pedido_borrador_activo"},
        )
        aggregated = ProcessedIntent(
            intent="agregar_producto",
            source_text="una pizza",
            status="ready",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )
        orchestrator.return_value = rejected
        agregar_orch.return_value = aggregated
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_classifier_result(
            (IntentName.INICIAR_PEDIDO, "hace otro pedido"),
            (IntentName.AGREGAR_PRODUCTO, "una pizza"),
        )
        classifier_cls.return_value = classifier_instance

        db = MagicMock(name="DatabaseSession")
        session = _mock_session(context_type=None)

        result = dispatch_initial_message(
            db, session, "hace otro pedido y una pizza"
        )

        self.assertEqual(result, [rejected, aggregated])
        agregar_orch.assert_called_once_with(db, session, "una pizza")


class OrchestratorIngresadoTransitionTest(unittest.TestCase):
    def test_ingresado_creates_one_closed_predecessor_one_active_successor(
        self,
    ) -> None:
        ids = _seed_active_session(
            pedido_estado=EstadoPedido.INGRESADO, populate_lines=True
        )
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_iniciar_pedido(
                    db, session_row, "hago otro pedido"
                )
                self.assertEqual(intent.status, "executed")
                self.assertEqual(intent.intent, "iniciar_pedido")
                self.assertEqual(
                    intent.resolved_data["predecessor_session_id"],
                    ids["session_id"],
                )
                self.assertEqual(
                    intent.resolved_data["predecessor_pedido_id"],
                    ids["pedido_id"],
                )
                successor_session_id = int(
                    intent.resolved_data["successor_session_id"]
                )
                successor_pedido_id = int(
                    intent.resolved_data["successor_pedido_id"]
                )
                db.commit()

            with TestingSessionLocal() as db:
                predecessor = db.get(SessionModel, ids["session_id"])
                assert predecessor is not None
                self.assertEqual(predecessor.estado_session, EstadoSession.CERRADA)
                self.assertEqual(predecessor.id_pedido, ids["pedido_id"])
                predecessor_pedido = db.get(Pedido, ids["pedido_id"])
                assert predecessor_pedido is not None
                self.assertEqual(
                    predecessor_pedido.estado_pedido, EstadoPedido.INGRESADO
                )

                successor_session = db.get(SessionModel, successor_session_id)
                assert successor_session is not None
                self.assertEqual(
                    successor_session.id_comercio, ids["comercio_id"]
                )
                self.assertEqual(
                    successor_session.id_cliente, ids["cliente_id"]
                )
                self.assertEqual(
                    successor_session.estado_session, EstadoSession.ACTIVA
                )
                self.assertEqual(
                    successor_session.id_pedido, successor_pedido_id
                )
                self.assertIsNone(successor_session.context_type)
                self.assertEqual(successor_session.pending_intents, {})

                successor_pedido = db.get(Pedido, successor_pedido_id)
                assert successor_pedido is not None
                self.assertEqual(
                    successor_pedido.estado_pedido, EstadoPedido.BORRADOR
                )
                self.assertIsNone(successor_pedido.id_medio_pago)
                self.assertIsNone(successor_pedido.id_metodo_entrega)
                self.assertIsNone(successor_pedido.datetime_entrega_programada)

                predecessor_lines = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == ids["pedido_id"]
                    )
                ).scalars().all()
                self.assertEqual(len(predecessor_lines), 1)
                successor_lines = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == successor_pedido_id
                    )
                ).scalars().all()
                self.assertEqual(successor_lines, [])
                db.rollback()
        finally:
            _cleanup(ids)


class OrchestratorNonBorradorStatesTest(unittest.TestCase):
    def test_preparacion_terminado_entregado_cancelado_each_create_successor(
        self,
    ) -> None:
        for state in (
            EstadoPedido.PREPARACION,
            EstadoPedido.TERMINADO,
            EstadoPedido.ENTREGADO,
            EstadoPedido.CANCELADO,
        ):
            with self.subTest(state=state.value):
                ids = _seed_active_session(pedido_estado=state)
                successor_session_id: int | None = None
                successor_pedido_id: int | None = None
                try:
                    with TestingSessionLocal() as db:
                        session_row = db.get(SessionModel, ids["session_id"])
                        assert session_row is not None
                        intent = process_initial_iniciar_pedido(
                            db, session_row, "hago otro pedido"
                        )
                        self.assertEqual(intent.status, "executed")
                        successor_session_id = int(
                            intent.resolved_data["successor_session_id"]
                        )
                        successor_pedido_id = int(
                            intent.resolved_data["successor_pedido_id"]
                        )
                        db.commit()

                    with TestingSessionLocal() as db:
                        successor_session = db.get(
                            SessionModel, successor_session_id
                        )
                        assert successor_session is not None
                        self.assertEqual(
                            successor_session.id_comercio, ids["comercio_id"]
                        )
                        self.assertEqual(
                            successor_session.id_cliente, ids["cliente_id"]
                        )
                        self.assertEqual(
                            successor_session.estado_session,
                            EstadoSession.ACTIVA,
                        )
                        successor_pedido = db.get(Pedido, successor_pedido_id)
                        assert successor_pedido is not None
                        self.assertEqual(
                            successor_pedido.estado_pedido,
                            EstadoPedido.BORRADOR,
                        )
                        db.rollback()
                finally:
                    _cleanup(ids)


class OrchestratorBorradorKeepsActiveTest(unittest.TestCase):
    def test_borrador_returns_rejected_without_mutation(self) -> None:
        ids = _seed_active_session(pedido_estado=EstadoPedido.BORRADOR)
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_iniciar_pedido(
                    db, session_row, "hace otro pedido"
                )
                self.assertEqual(intent.status, "rejected")
                self.assertEqual(
                    intent.resolved_data.get("reason"),
                    "pedido_borrador_activo",
                )
                self.assertEqual(
                    intent.resolved_data.get("pedido_id"), ids["pedido_id"]
                )
                db.rollback()

            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                self.assertEqual(
                    session_row.estado_session, EstadoSession.ACTIVA
                )
                self.assertEqual(session_row.id_pedido, ids["pedido_id"])
                self.assertIsNone(
                    db.execute(
                        select(SessionModel).where(
                            SessionModel.id_comercio == ids["comercio_id"],
                            SessionModel.id_cliente == ids["cliente_id"],
                            SessionModel.id != ids["session_id"],
                        )
                    ).scalar_one_or_none()
                )
                db.rollback()
        finally:
            _cleanup(ids)


class OrchestratorNoPedidoRejectedTest(unittest.TestCase):
    def test_no_pedido_returns_rejected_without_mutation(self) -> None:
        ids = _seed_active_session(pedido_estado=EstadoPedido.INGRESADO)
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                session_row.id_pedido = None
                db.commit()
                intent = process_initial_iniciar_pedido(
                    db, session_row, "hace otro pedido"
                )
                self.assertEqual(intent.status, "rejected")
                self.assertEqual(
                    intent.resolved_data.get("reason"),
                    "no_pedido_asociado",
                )
                db.rollback()
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                self.assertEqual(
                    session_row.estado_session, EstadoSession.ACTIVA
                )
                db.rollback()
        finally:
            _cleanup(ids)


class OrchestratorNonActiveSessionRejectedTest(unittest.TestCase):
    def test_closed_session_returns_rejected_without_mutation(self) -> None:
        ids = _seed_active_session(pedido_estado=EstadoPedido.INGRESADO)
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                session_row.estado_session = EstadoSession.CERRADA
                db.commit()
                intent = process_initial_iniciar_pedido(
                    db, session_row, "hace otro pedido"
                )
                self.assertEqual(intent.status, "rejected")
                self.assertEqual(
                    intent.resolved_data.get("reason"),
                    "session_not_active",
                )
                db.rollback()
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                self.assertEqual(
                    session_row.estado_session, EstadoSession.CERRADA
                )
                db.rollback()
        finally:
            _cleanup(ids)


class OrchestratorCommerceClientIsolationTest(unittest.TestCase):
    def test_successor_uses_supplied_comercio_and_client(self) -> None:
        ids = _seed_active_session(
            pedido_estado=EstadoPedido.INGRESADO,
        )
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_iniciar_pedido(
                    db, session_row, "otro pedido"
                )
                self.assertEqual(intent.status, "executed")
                row = db.execute(
                    select(SessionModel).where(
                        SessionModel.id_comercio == ids["comercio_id"],
                        SessionModel.id_cliente == ids["cliente_id"],
                        SessionModel.estado_session == EstadoSession.ACTIVA,
                    )
                ).scalars().first()
                assert row is not None
                self.assertEqual(
                    int(row.id),
                    int(intent.resolved_data["successor_session_id"]),
                )
                self.assertEqual(
                    row.id_comercio, ids["comercio_id"]
                )
                self.assertEqual(row.id_cliente, ids["cliente_id"])
                self.assertNotEqual(
                    int(row.id), ids["session_id"]
                )
                db.rollback()
        finally:
            _cleanup(ids)


class OrchestratorProviderRollbackTest(unittest.TestCase):
    """Real ``ProviderInboundMessageCoordinator.process_lease`` rollback proof.

    The coordinator is the sole transaction owner of the
    acceptance + deferred processing path. The test seeds a real
    commerce/cliente/canal/active-session quartet with an associated
    ``ingresado`` pedido, claims a real receipt/work lease through
    the coordinator's ``accept``, leases it through
    ``claim_due_processing`` and finally drives the leased row through
    ``process_lease`` end-to-end. The classifier is patched at the
    dispatcher's import site so the inbound message is authoritatively
    classified as ``INICIAR_PEDIDO``, which routes the dispatch to the
    real ``process_initial_iniciar_pedido`` orchestrator and creates
    the predecessor-close/successor-create effect on the leased
    transaction. A forced post-staging failure injected into the real
    outbound staging function — at the exact import the coordinator
    uses — must propagate back to the coordinator, which rolls the
    transaction back and finalizes the work as ``RETRY_SCHEDULED``.

    Durability is asserted from a fresh database session: the
    predecessor session is still ``ACTIVA`` and still associated to
    the original pedido, the original pedido is still ``ingresado``,
    no successor session exists, no successor pedido exists, and no
    outbound row was durably staged. The bounded CLI can re-claim the
    same lease and replay the same body.
    """

    def test_process_lease_failure_after_staging_rolls_back_successor(
        self,
    ) -> None:
        ids = _seed_provider_iniciar_pedido_scenario(
            pedido_estado=EstadoPedido.INGRESADO,
        )
        try:
            accept_coordinator = ProviderInboundMessageCoordinator(
                session=TestingSessionLocal(),
            )
            accept_outcome = accept_coordinator.accept(
                ProviderInboundMessageCommand(
                    proveedor="twilio",
                    identificador_recepcion=f"SM-{ids['suffix']}",
                    canal_id=ids["canal_id"],
                    cliente_id=ids["cliente_id"],
                    comercio_id=ids["comercio_id"],
                    mensaje="quiero hacer otro pedido",
                    destinatario_e164=ids["destination"],
                )
            )
            self.assertEqual(
                accept_outcome.status,
                ProviderInboundMessageStatus.ACCEPTED,
            )
            assert accept_outcome.receipt_id is not None
            assert accept_outcome.procesamiento_id is not None
            receipt_id = int(accept_outcome.receipt_id)
            procesamiento_id = int(accept_outcome.procesamiento_id)

            lease_session = TestingSessionLocal()
            try:
                lease_coordinator = ProviderInboundMessageCoordinator(
                    session=lease_session,
                )
                leased = lease_coordinator.claim_due_processing(
                    now=datetime.now(tz=timezone.utc),
                )
                self.assertIsNotNone(leased)
                assert leased is not None
                self.assertEqual(
                    int(leased.id), procesamiento_id,
                )
                lease_token = str(leased.token_lease or "")

                classifier_instance = MagicMock()
                classifier_instance.query.return_value = (
                    _build_classifier_result(
                        (
                            IntentName.INICIAR_PEDIDO,
                            "quiero hacer otro pedido",
                        ),
                    )
                )

                def _raise(*args, **kwargs):  # type: ignore[no-untyped-def]
                    raise RuntimeError(
                        "forced post-staging outbound failure"
                    )

                with patch.object(
                    dispatcher_module,
                    "IntentClassifier",
                    return_value=classifier_instance,
                ), patch(
                    "backend.services.provider_inbound_message_coordinator"
                    ".stage_outbound_rows",
                    side_effect=_raise,
                ):
                    result = lease_coordinator.process_lease(leased)
            finally:
                lease_session.close()

            self.assertEqual(
                result.outcome,
                ProviderInboundProcessingOutcome.RETRY_SCHEDULED,
            )
            self.assertEqual(int(result.procesamiento_id or 0), procesamiento_id)
            self.assertEqual(int(result.receipt_id or 0), receipt_id)
            self.assertEqual(result.intentos, 1)
            assert result.categoria is not None
            self.assertEqual(result.categoria.value, "pipeline_error")
            self.assertEqual(result.codigo, "pipeline_error")
            self.assertNotEqual(lease_token, "")

            with TestingSessionLocal() as db:
                predecessor = db.get(SessionModel, ids["session_id"])
                assert predecessor is not None
                self.assertEqual(
                    predecessor.estado_session, EstadoSession.ACTIVA,
                )
                self.assertEqual(predecessor.id_pedido, ids["pedido_id"])

                predecessor_pedido = db.get(Pedido, ids["pedido_id"])
                assert predecessor_pedido is not None
                self.assertEqual(
                    predecessor_pedido.estado_pedido,
                    EstadoPedido.INGRESADO,
                )

                other_sessions = (
                    db.execute(
                        select(SessionModel).where(
                            SessionModel.id_comercio == ids["comercio_id"],
                            SessionModel.id_cliente == ids["cliente_id"],
                            SessionModel.id != ids["session_id"],
                        )
                    )
                    .scalars()
                    .all()
                )
                self.assertEqual(
                    other_sessions,
                    [],
                    "no successor session may remain after rollback",
                )

                other_pedidos = (
                    db.execute(
                        select(Pedido).where(
                            Pedido.id_session.in_(
                                select(SessionModel.id).where(
                                    SessionModel.id_comercio
                                    == ids["comercio_id"],
                                    SessionModel.id_cliente
                                    == ids["cliente_id"],
                                )
                            ),
                            Pedido.id != ids["pedido_id"],
                        )
                    )
                    .scalars()
                    .all()
                )
                self.assertEqual(
                    other_pedidos,
                    [],
                    "no successor pedido may remain after rollback",
                )

                outbox_rows = (
                    db.execute(
                        select(MensajeProveedorSaliente).where(
                            MensajeProveedorSaliente.recepcion_mensaje_proveedor_id
                            == receipt_id,
                        )
                    )
                    .scalars()
                    .all()
                )
                self.assertEqual(
                    outbox_rows,
                    [],
                    "no outbound row may be durable after rollback",
                )

                work = db.get(
                    ProcesamientoMensajeProveedor, procesamiento_id,
                )
                assert work is not None
                self.assertEqual(
                    work.estado,
                    ProcesamientoMensajeProveedorEstado.RETRYABLE.value,
                )
                self.assertIsNotNone(work.mensaje)
                self.assertIsNotNone(work.proximo_intento_en)
                self.assertEqual(int(work.intentos), 1)
                self.assertEqual(work.categoria_ultimo_fallo, "pipeline_error")
                self.assertEqual(work.codigo_ultimo_fallo, "pipeline_error")

                db.rollback()
        finally:
            _cleanup_provider_iniciar_pedido_scenario(ids)


class OrchestratorTransactionalOwnershipTest(unittest.TestCase):
    def test_orchestrator_does_not_call_transaction_control_methods(self) -> None:
        importlib.reload(orchestrator_module)
        module = orchestrator_module
        with open(module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            ".commit(",
            ".rollback(",
            ".begin(",
            ".close(",
            ".refresh(",
            ".expire(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_orchestrator_module_surface(self) -> None:
        self.assertEqual(
            orchestrator_module.__all__,
            ["process_initial_iniciar_pedido"],
        )


class ResponseIniciarPedidoTest(unittest.TestCase):
    def test_executed_renders_success_message(self) -> None:
        intent = ProcessedIntent(
            intent="iniciar_pedido",
            source_text="otro pedido",
            status="executed",
            recognizer="new_order_after_confirmation",
            handler="iniciar_pedido",
            resolved_data={
                "successor_session_id": 1,
                "successor_pedido_id": 2,
            },
        )
        response = build_iniciar_pedido_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.intent, "iniciar_pedido")
        self.assertEqual(response.status, "executed")
        self.assertIn("pedido nuevo", response.message)
        self.assertNotIn("Disculpá", response.message)
        self.assertNotIn("Exception", response.message)

    def test_rejected_borrador_renders_continue_message(self) -> None:
        intent = ProcessedIntent(
            intent="iniciar_pedido",
            source_text="otro pedido",
            status="rejected",
            recognizer="new_order_after_confirmation",
            handler="iniciar_pedido",
            resolved_data={"reason": "pedido_borrador_activo"},
        )
        response = build_iniciar_pedido_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.intent, "iniciar_pedido")
        self.assertEqual(response.status, "rejected")
        self.assertIn("ya tenés un pedido", response.message.lower())

    def test_rejected_no_pedido_renders_no_pedido_message(self) -> None:
        intent = ProcessedIntent(
            intent="iniciar_pedido",
            source_text="otro pedido",
            status="rejected",
            recognizer="new_order_after_confirmation",
            handler="iniciar_pedido",
            resolved_data={"reason": "no_pedido_asociado"},
        )
        response = build_iniciar_pedido_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.intent, "iniciar_pedido")
        self.assertEqual(response.status, "rejected")
        self.assertIn(
            "todavía no hay un pedido asociado", response.message.lower()
        )

    def test_rejected_session_not_active_renders_no_pedido_message(self) -> None:
        intent = ProcessedIntent(
            intent="iniciar_pedido",
            source_text="otro pedido",
            status="rejected",
            recognizer="new_order_after_confirmation",
            handler="iniciar_pedido",
            resolved_data={"reason": "session_not_active"},
        )
        response = build_iniciar_pedido_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.intent, "iniciar_pedido")
        self.assertEqual(response.status, "rejected")
        self.assertIn(
            "todavía no hay un pedido asociado", response.message.lower()
        )

    def test_failed_renders_generic_failure_message(self) -> None:
        intent = ProcessedIntent(
            intent="iniciar_pedido",
            source_text="otro pedido",
            status="failed",
            recognizer="new_order_after_confirmation",
            handler="iniciar_pedido",
            resolved_data={},
        )
        response = build_iniciar_pedido_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.intent, "iniciar_pedido")
        self.assertEqual(response.status, "failed")
        self.assertIn("problema técnico", response.message.lower())

    def test_non_iniciar_pedido_returns_failure_message(self) -> None:
        intent = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="executed",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={},
        )
        response = build_iniciar_pedido_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.intent, "agregar_producto")
        self.assertIn("problema técnico", response.message.lower())

    def test_response_module_public_surface(self) -> None:
        self.assertEqual(
            response_module.__all__,
            ["build_iniciar_pedido_response"],
        )

    def test_response_message_has_no_internal_ids(self) -> None:
        intent = ProcessedIntent(
            intent="iniciar_pedido",
            source_text="otro pedido",
            status="executed",
            recognizer="new_order_after_confirmation",
            handler="iniciar_pedido",
            resolved_data={
                "successor_session_id": 1,
                "successor_pedido_id": 2,
            },
        )
        response = build_iniciar_pedido_response(MagicMock(), MagicMock(), intent)
        for forbidden in ("Exception", "Traceback", "Error", "id_session", "id_pedido"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, response.message)


class OutboundMapperIniciarPedidoTest(unittest.TestCase):
    def test_iniciar_pedido_routes_to_response_builder(self) -> None:
        intent = ProcessedIntent(
            intent="iniciar_pedido",
            source_text="otro pedido",
            status="executed",
            recognizer="new_order_after_confirmation",
            handler="iniciar_pedido",
            resolved_data={
                "successor_session_id": 1,
                "successor_pedido_id": 2,
            },
        )
        responses = build_customer_responses(
            MagicMock(), MagicMock(), [intent]
        )
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].intent, "iniciar_pedido")
        self.assertEqual(responses[0].status, "executed")
        self.assertIn("pedido nuevo", responses[0].message)

    def test_generic_message_is_unaffected_for_unknown_intent(self) -> None:
        intent = ProcessedIntent(
            intent="desconocida",
            source_text="x",
            status="rejected",
            recognizer="intent_classifier",
            handler="desconocida",
        )
        responses = build_customer_responses(
            MagicMock(), MagicMock(), [intent]
        )
        self.assertEqual(responses[0].message, GENERIC_MESSAGE)


class DispatchIniciarPedidoRegressionTest(unittest.TestCase):
    @patch.object(dispatcher_module, "process_initial_agregar_producto")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_existing_agregar_producto_branch_still_works(
        self, classifier_cls, agregar_orch
    ):
        agregar_orch.return_value = ProcessedIntent(
            intent="agregar_producto",
            source_text="una empanada",
            status="ready",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_classifier_result(
            (IntentName.AGREGAR_PRODUCTO, "una empanada"),
        )
        classifier_cls.return_value = classifier_instance

        result = dispatch_initial_message(
            MagicMock(), _mock_session(context_type=None), "una empanada"
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].intent, "agregar_producto")

    @patch.object(dispatcher_module, "process_initial_agregar_producto")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_existing_desconocida_rejection_still_works(
        self, classifier_cls, agregar_orch
    ):
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_classifier_result(
            (IntentName.DESCONOCIDA, "asdf"),
        )
        classifier_cls.return_value = classifier_instance

        result = dispatch_initial_message(
            MagicMock(), _mock_session(context_type=None), "asdf"
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "rejected")
        self.assertEqual(result[0].intent, "desconocida")
        agregar_orch.assert_not_called()


class OrchestratorPendingContextPreservedTest(unittest.TestCase):
    def test_pending_intent_state_is_not_carried_over(self) -> None:
        ids = _seed_active_session(pedido_estado=EstadoPedido.INGRESADO)
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_iniciar_pedido(
                    db, session_row, "otro pedido"
                )
                self.assertEqual(intent.status, "executed")
                successor_session_id = int(
                    intent.resolved_data["successor_session_id"]
                )

                sucesor = db.get(SessionModel, successor_session_id)
                assert sucesor is not None
                self.assertEqual(sucesor.pending_intents, {})
                self.assertIsNone(sucesor.context_type)
                db.rollback()
        finally:
            _cleanup(ids)


class OrchestratorNoCopyTest(unittest.TestCase):
    def test_successor_has_no_lines_payment_delivery_or_context(self) -> None:
        ids = _seed_active_session(
            pedido_estado=EstadoPedido.INGRESADO,
            populate_lines=True,
        )
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_iniciar_pedido(
                    db, session_row, "otro pedido"
                )
                successor_pedido_id = int(
                    intent.resolved_data["successor_pedido_id"]
                )
                successor_session_id = int(
                    intent.resolved_data["successor_session_id"]
                )
                db.commit()

            with TestingSessionLocal() as db:
                successor_pedido = db.get(Pedido, successor_pedido_id)
                assert successor_pedido is not None
                self.assertIsNone(successor_pedido.id_medio_pago)
                self.assertIsNone(successor_pedido.id_metodo_entrega)
                self.assertIsNone(successor_pedido.datetime_entrega_programada)
                successor_lines = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == successor_pedido_id
                    )
                ).scalars().all()
                self.assertEqual(successor_lines, [])
                successor_session = db.get(SessionModel, successor_session_id)
                assert successor_session is not None
                self.assertEqual(successor_session.pending_intents, {})
                self.assertIsNone(successor_session.context_type)
                db.rollback()
        finally:
            _cleanup(ids)


if __name__ == "__main__":
    unittest.main()
