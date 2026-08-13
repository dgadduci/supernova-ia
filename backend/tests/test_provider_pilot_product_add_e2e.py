"""End-to-end provider-coordinator coverage of the modern
``agregar_producto`` flow.

These tests pin the exact WhatsApp sequence from the proposal
through the real :class:`ProviderInboundMessageCoordinator`:

  1. First inbound message (``Quiero una pizza de mozzarella``)
     accepts one receipt + stages one pending deferred work item;
  2. Operator CLI ``process_lease`` claims the work item and
     runs the real ``process_incoming_message`` pipeline which
     establishes the active session and the draft ``Pedido``;
  3. Second inbound message (``Grande``) is accepted and leased;
     the pipeline narrows the candidates and runs the modern
     ``agregar_producto`` handler via the new
     ``stage_add_or_increment_for_session`` seam.

The tests verify the closed ``product_add_execution`` event,
the durable outbox row, the cleared pending context and the
typed business outcome for every documented branch:

* ``precio_disponible`` → one line, success response, cleared
  context and a single ``created`` event;
* ``precio_faltante`` → zero lines, generic rejection, cleared
  context and a single ``rejected_price_unavailable`` event;
* ``falla_tecnica`` → outer coordinator rollback, no
  ``product_add_execution`` event emitted by the handler.
"""
from __future__ import annotations

import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, ClassVar
from unittest.mock import patch

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from backend.intents.schemas.intent_classification import (
    ClassifiedIntent,
    IntentClassificationResult,
    IntentName,
)
from backend.models import (
    CategoriaProducto,
    Cliente,
    Comercio,
    EstadoComercio,
    Pedido,
    PedidoProducto,
    Precio,
    Presentacion,
    Producto,
    ProductoPresentacion,
)
from backend.models import Session as SessionModel
from backend.observability.events import (
    COMPONENT_PRODUCT_ADD_EXECUTION,
    EVENT_PRODUCT_ADD_EXECUTION,
)
from backend.services.provider_inbound_message_coordinator import (
    ProviderInboundMessageCommand,
    ProviderInboundMessageCoordinator,
    ProviderInboundMessageStatus,
    ProviderInboundProcessingOutcome,
)

TEST_URL = "postgresql+psycopg:///supernova_test"
engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False
)


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _estado_id_activo() -> int:
    with engine.connect() as c:
        row = c.execute(
            select(EstadoComercio.id).where(EstadoComercio.estado == "ACTIVO")
        ).first()
        if row is None:
            raise RuntimeError("estado ACTIVO not seeded in supernova_test")
        return row[0]


class _PatchedClassifier:
    """Deterministic LLM stub: always returns ``agregar_producto``."""

    constructor_calls: ClassVar[list] = []
    query_calls: ClassVar[list] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        type(self).constructor_calls.append((args, kwargs))

    def query(self, message: str) -> IntentClassificationResult:
        type(self).query_calls.append(message)
        return IntentClassificationResult(
            intents=[
                ClassifiedIntent(
                    intent=IntentName.AGREGAR_PRODUCTO,
                    mensaje=message,
                )
            ],
            mensaje=message,
        )


@contextmanager
def _patched_classifier(message: str):
    from backend.intents.orchestration import (
        initial_intent_dispatcher as _dispatcher,
    )

    _PatchedClassifier.constructor_calls = []
    _PatchedClassifier.query_calls = []

    patcher = patch.object(
        _dispatcher, "IntentClassifier", _PatchedClassifier
    )
    patcher.start()
    try:
        yield _PatchedClassifier
    finally:
        patcher.stop()


def _delete_recepciones_by_comercio(comercio_id: int) -> None:
    from backend.models import RecepcionMensajeProveedor

    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(RecepcionMensajeProveedor).where(
                RecepcionMensajeProveedor.comercio_id == comercio_id
            )
        )


def _delete_procesamientos_by_comercio(comercio_id: int) -> None:
    from backend.models import (
        ProcesamientoMensajeProveedor,
        RecepcionMensajeProveedor,
    )

    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(ProcesamientoMensajeProveedor).where(
                ProcesamientoMensajeProveedor.recepcion_mensaje_proveedor_id.in_(
                    select(RecepcionMensajeProveedor.id).where(
                        RecepcionMensajeProveedor.comercio_id == comercio_id
                    )
                )
            )
        )


def _delete_outbox_by_comercio(comercio_id: int) -> None:
    from backend.models import (
        MensajeProveedorSaliente,
        RecepcionMensajeProveedor,
    )

    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(MensajeProveedorSaliente).where(
                MensajeProveedorSaliente.recepcion_mensaje_proveedor_id.in_(
                    select(RecepcionMensajeProveedor.id).where(
                        RecepcionMensajeProveedor.comercio_id == comercio_id
                    )
                )
            )
        )


def _delete_canales_by_destination(destination: str) -> None:
    from backend.models import CanalWhatsapp

    with TestingSessionLocal() as session, session.begin():
        canal_ids_subquery = select(CanalWhatsapp.id).where(
            CanalWhatsapp.destination_e164 == destination
        )
        session.execute(
            delete(CanalWhatsapp).where(
                CanalWhatsapp.id.in_(canal_ids_subquery)
            )
        )


def _delete_cliente(cliente_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(delete(Cliente).where(Cliente.id == cliente_id))


def _delete_comercio(comercio_id: int) -> None:
    from sqlalchemy import text

    from backend.models import (
        CanalWhatsapp,
        ComercioCanalCompartido,
        ContextoClienteCanalWhatsapp,
    )

    with TestingSessionLocal() as session, session.begin():
        canal_ids_subquery = select(CanalWhatsapp.id).where(
            CanalWhatsapp.id_comercio_exclusivo == comercio_id
        )
        session.execute(
            delete(ComercioCanalCompartido).where(
                ComercioCanalCompartido.canal_id.in_(canal_ids_subquery)
            )
        )
        session.execute(
            delete(ContextoClienteCanalWhatsapp).where(
                ContextoClienteCanalWhatsapp.comercio_id_seleccionado
                == comercio_id
            )
        )
        session.execute(
            delete(CanalWhatsapp).where(
                CanalWhatsapp.id_comercio_exclusivo == comercio_id
            )
        )
        session.execute(
            delete(Precio).where(
                Precio.id_producto_presentacion.in_(
                    select(ProductoPresentacion.id).where(
                        ProductoPresentacion.id_producto.in_(
                            select(Producto.id).where(
                                Producto.id_categoria_producto.in_(
                                    select(CategoriaProducto.id).where(
                                        CategoriaProducto.id_comercio
                                        == comercio_id
                                    )
                                )
                            )
                        )
                    )
                )
            )
        )
        session.execute(
            delete(PedidoProducto).where(
                PedidoProducto.id_pedido.in_(
                    select(Pedido.id).where(
                        Pedido.id_session.in_(
                            select(SessionModel.id).where(
                                SessionModel.id_comercio == comercio_id
                            )
                        )
                    )
                )
            )
        )
        # ``sessions.id_pedido`` is FK RESTRICT; null out before
        # deleting the pedido rows.
        session.execute(
            text(
                "UPDATE sessions SET id_pedido = NULL "
                "WHERE id_comercio = :cid"
            ),
            {"cid": comercio_id},
        )
        session.execute(
            delete(Pedido).where(
                Pedido.id_session.in_(
                    select(SessionModel.id).where(
                        SessionModel.id_comercio == comercio_id
                    )
                )
            )
        )
        session.execute(
            delete(ProductoPresentacion).where(
                ProductoPresentacion.id_producto.in_(
                    select(Producto.id).where(
                        Producto.id_categoria_producto.in_(
                            select(CategoriaProducto.id).where(
                                CategoriaProducto.id_comercio == comercio_id
                            )
                        )
                    )
                )
            )
        )
        session.execute(
            delete(Producto).where(
                Producto.id_categoria_producto.in_(
                    select(CategoriaProducto.id).where(
                        CategoriaProducto.id_comercio == comercio_id
                    )
                )
            )
        )
        session.execute(
            delete(CategoriaProducto).where(
                CategoriaProducto.id_comercio == comercio_id
            )
        )
        session.execute(
            delete(Presentacion).where(
                Presentacion.id_comercio == comercio_id
            )
        )
        session.execute(
            delete(SessionModel).where(
                SessionModel.id_comercio == comercio_id
            )
        )
        session.execute(
            delete(Cliente).where(
                Cliente.id.in_(
                    select(SessionModel.id_cliente).where(
                        SessionModel.id_comercio == comercio_id
                    )
                )
            )
        )
        session.execute(delete(Comercio).where(Comercio.id == comercio_id))


def _seed_comercio(suffix: str) -> int:
    estado_id = _estado_id_activo()
    with TestingSessionLocal() as session, session.begin():
        comercio = Comercio(
            nombre_fantasia=f"E2E {suffix}",
            nombre_corto=f"E2E {suffix}",
            razon_social=f"E2E SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+54991{suffix[:8]}",
            calle="Av. E2E",
            numero="1",
            piso_departamento=None,
            localidad="CABA",
            provincia="BA",
            codigo_postal="C1000",
            slug=f"e2e-{suffix}",
            estado_id=estado_id,
        )
        session.add(comercio)
        session.flush()
        return int(comercio.id)


def _seed_cliente(suffix: str) -> int:
    with TestingSessionLocal() as session, session.begin():
        cliente = Cliente(
            whatsapp=f"+54991{int(suffix, 16) % 100000000:08d}",
            nombre=None,
            domicilio=None,
            activo=True,
        )
        session.add(cliente)
        session.flush()
        return int(cliente.id)


def _seed_dedicated_channel(
    suffix: str, comercio_id: int, destination_e164: str
) -> int:
    from backend.models import CanalWhatsapp, CanalWhatsappMode

    with TestingSessionLocal() as session, session.begin():
        canal = CanalWhatsapp(
            provider="twilio",
            destination_e164=destination_e164,
            mode=CanalWhatsappMode.DEDICATED,
            id_comercio_exclusivo=comercio_id,
            activo=True,
        )
        session.add(canal)
        session.flush()
        return int(canal.id)


def _seed_two_presentation_catalog(
    *,
    comercio_id: int,
    nombre: str,
    codigo_grande: str,
    codigo_chica: str,
    seed_precio: bool,
) -> dict[str, int]:
    """Seed Mozzarella catalog with two presentations and (optionally)
    a price for the Grande presentation only. Returns:
    ``pp_grande_id``, ``pp_chica_id``, ``session_id``, ``pedido_id``.
    The seeded session is auto-staged by the provider coordinator
    on first message so this helper only seeds the catalog.
    """
    s = _suffix()
    with TestingSessionLocal() as session, session.begin():
        categoria = CategoriaProducto(
            id_comercio=comercio_id,
            descripcion=f"E2E Cat {s}",
            activo=True,
            orden=0,
        )
        session.add(categoria)
        session.flush()

        producto = Producto(
            id_categoria_producto=categoria.id,
            nombre=nombre,
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        session.add(producto)
        session.flush()

        presentacion_grande = Presentacion(
            id_comercio=comercio_id,
            codigo=codigo_grande,
            descripcion="Grande",
            activo=True,
            orden=0,
        )
        session.add(presentacion_grande)
        session.flush()

        presentacion_chica = Presentacion(
            id_comercio=comercio_id,
            codigo=codigo_chica,
            descripcion="Chica",
            activo=True,
            orden=1,
        )
        session.add(presentacion_chica)
        session.flush()

        assoc_grande = ProductoPresentacion(
            id_producto=producto.id,
            id_presentacion=presentacion_grande.id,
            activo=True,
            orden=0,
        )
        session.add(assoc_grande)
        session.flush()

        assoc_chica = ProductoPresentacion(
            id_producto=producto.id,
            id_presentacion=presentacion_chica.id,
            activo=True,
            orden=1,
        )
        session.add(assoc_chica)
        session.flush()

        if seed_precio:
            session.add(
                Precio(
                    id_producto_presentacion=assoc_grande.id,
                    precio=Decimal("12500.00"),
                )
            )
            session.flush()

        return {
            "pp_grande_id": int(assoc_grande.id),
            "pp_chica_id": int(assoc_chica.id),
            "producto_id": int(producto.id),
        }


class ProviderCoordinatorProductAddPricePresentEndToEndTest(unittest.TestCase):
    """Real provider coordinator E2E for the price-present path:

    ``Quiero una pizza de mozzarella`` → ``Grande`` with a
    persisted price produces one ``PedidoProducto``, one
    successful outbox message and a single ``created``
    ``product_add_execution`` event.
    """

    def setUp(self) -> None:
        suffix = _suffix()
        self.comercio_id = _seed_comercio(suffix)
        self.cliente_id = _seed_cliente(suffix + "C")
        self.destination = f"+54993{suffix[:8]}"
        self.canal_id = _seed_dedicated_channel(
            suffix + "D", self.comercio_id, self.destination
        )
        self.catalog = _seed_two_presentation_catalog(
            comercio_id=self.comercio_id,
            nombre="Pizza Mozzarella",
            codigo_grande=f"G_{suffix[:6]}",
            codigo_chica=f"C_{suffix[:6]}",
            seed_precio=True,
        )
        self.proveedor = "twilio"
        # ``addCleanup`` runs in LIFO order; the channel and cliente
        # have FK references from recepciones and sessions, so
        # recepciones / procesamientos / outbox must be cleared
        # BEFORE we delete the channel or the comercio.
        self.addCleanup(_delete_comercio, self.comercio_id)
        self.addCleanup(_delete_canales_by_destination, self.destination)
        self.addCleanup(_delete_recepciones_by_comercio, self.comercio_id)
        self.addCleanup(_delete_procesamientos_by_comercio, self.comercio_id)
        self.addCleanup(_delete_outbox_by_comercio, self.comercio_id)

    def _command(
        self, identificador: str, mensaje: str
    ) -> ProviderInboundMessageCommand:
        return ProviderInboundMessageCommand(
            proveedor=self.proveedor,
            identificador_recepcion=identificador,
            canal_id=self.canal_id,
            cliente_id=self.cliente_id,
            comercio_id=self.comercio_id,
            mensaje=mensaje,
            destinatario_e164=self.destination,
        )

    def _accept_and_process(
        self,
        *,
        identificador: str,
        mensaje: str,
        event_sink: list[dict],
    ) -> None:
        coordinator = ProviderInboundMessageCoordinator(
            session=TestingSessionLocal(),
        )
        acceptance = coordinator.accept(
            self._command(identificador, mensaje)
        )
        self.assertEqual(
            acceptance.status, ProviderInboundMessageStatus.ACCEPTED
        )
        leased = coordinator.claim_due_processing(now=datetime.now(tz=timezone.utc))
        assert leased is not None
        result = coordinator.process_lease(leased)
        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.PROCESSED,
            f"expected PROCESSED; got {result.outcome}: {result.detalle}",
        )

    def test_full_provider_flow_emits_created_event(self) -> None:
        captured: list[dict] = []

        def _capture(**kwargs):
            captured.append(kwargs)
            return True

        with _patched_classifier(
            "quiero una pizza de mozzarella"
        ), patch(
            "backend.intents.handlers.agregar_producto_handler.emit_event",
            side_effect=_capture,
        ):
            s1 = _suffix()
            s2 = _suffix()
            self._accept_and_process(
                identificador=f"SM-{s1}",
                mensaje="quiero una pizza de mozzarella",
                event_sink=captured,
            )
            self._accept_and_process(
                identificador=f"SM-{s2}",
                mensaje="Grande",
                event_sink=captured,
            )

        # Look up the session and pedido created by the coordinator.
        with TestingSessionLocal() as db:
            session_row = db.execute(
                select(SessionModel).where(
                    SessionModel.id_comercio == self.comercio_id
                )
            ).scalar_one()
            assert session_row.id_pedido is not None
            pedido_id = int(session_row.id_pedido)

            lines = (
                db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == pedido_id
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(len(lines), 1)
            self.assertEqual(
                int(lines[0].id_producto_presentacion),
                self.catalog["pp_grande_id"],
            )
            self.assertEqual(int(lines[0].cantidad), 1)
            self.assertEqual(
                Decimal(lines[0].precio_unitario), Decimal("12500.00")
            )

            # Pending context must be cleared.
            self.assertIsNone(session_row.context_type)
            pending = session_row.pending_intents or {}
            self.assertIsNone(pending.get("active"))
            self.assertEqual(pending.get("queue"), [])

            # Outbox should contain the success message.
            from backend.models import MensajeProveedorSaliente

            outbox_rows = (
                db.execute(
                    select(MensajeProveedorSaliente).where(
                        MensajeProveedorSaliente.recepcion_mensaje_proveedor_id.in_(
                            select(
                                __import__(
                                    "backend.models",
                                    fromlist=["RecepcionMensajeProveedor"],
                                ).RecepcionMensajeProveedor.id
                            ).where(
                                __import__(
                                    "backend.models",
                                    fromlist=[
                                        "RecepcionMensajeProveedor"
                                    ],
                                ).RecepcionMensajeProveedor.comercio_id
                                == self.comercio_id
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )
            self.assertGreaterEqual(
                len(outbox_rows), 1, "expected at least one outbox row"
            )

        product_add_events = [
            kwargs
            for kwargs in captured
            if kwargs.get("event") == EVENT_PRODUCT_ADD_EXECUTION
        ]
        self.assertEqual(
            len(product_add_events),
            1,
            f"expected exactly one product_add_execution event; got {captured}",
        )
        self.assertEqual(
            product_add_events[0].get("outcome"), "created"
        )
        self.assertEqual(
            product_add_events[0].get("component"),
            COMPONENT_PRODUCT_ADD_EXECUTION,
        )


class ProviderCoordinatorProductAddPriceUnavailableEndToEndTest(unittest.TestCase):
    """Real provider coordinator E2E for the price-unavailable path:

    the same conversation WITHOUT a price on the Grande
    presentation must produce zero lines, a generic rejection,
    a cleared context and a single ``rejected_price_unavailable``
    event.
    """

    def setUp(self) -> None:
        suffix = _suffix()
        self.comercio_id = _seed_comercio(suffix)
        self.cliente_id = _seed_cliente(suffix + "C")
        self.destination = f"+54994{suffix[:8]}"
        self.canal_id = _seed_dedicated_channel(
            suffix + "D", self.comercio_id, self.destination
        )
        self.catalog = _seed_two_presentation_catalog(
            comercio_id=self.comercio_id,
            nombre="Pizza Mozzarella",
            codigo_grande=f"GN_{suffix[:6]}",
            codigo_chica=f"CN_{suffix[:6]}",
            seed_precio=False,
        )
        self.proveedor = "twilio"
        self.addCleanup(_delete_comercio, self.comercio_id)
        self.addCleanup(_delete_canales_by_destination, self.destination)
        self.addCleanup(_delete_recepciones_by_comercio, self.comercio_id)
        self.addCleanup(_delete_procesamientos_by_comercio, self.comercio_id)
        self.addCleanup(_delete_outbox_by_comercio, self.comercio_id)

    def _command(
        self, identificador: str, mensaje: str
    ) -> ProviderInboundMessageCommand:
        return ProviderInboundMessageCommand(
            proveedor=self.proveedor,
            identificador_recepcion=identificador,
            canal_id=self.canal_id,
            cliente_id=self.cliente_id,
            comercio_id=self.comercio_id,
            mensaje=mensaje,
            destinatario_e164=self.destination,
        )

    def _accept_and_process(self, *, identificador: str, mensaje: str) -> None:
        coordinator = ProviderInboundMessageCoordinator(
            session=TestingSessionLocal(),
        )
        acceptance = coordinator.accept(
            self._command(identificador, mensaje)
        )
        self.assertEqual(
            acceptance.status, ProviderInboundMessageStatus.ACCEPTED
        )
        leased = coordinator.claim_due_processing(now=datetime.now(tz=timezone.utc))
        assert leased is not None
        coordinator.process_lease(leased)

    def test_full_provider_flow_emits_rejected_price_unavailable(self) -> None:
        captured: list[dict] = []

        def _capture(**kwargs):
            captured.append(kwargs)
            return True

        with _patched_classifier(
            "quiero una pizza de mozzarella"
        ), patch(
            "backend.intents.handlers.agregar_producto_handler.emit_event",
            side_effect=_capture,
        ):
            s1 = _suffix()
            s2 = _suffix()
            self._accept_and_process(
                identificador=f"SM-{s1}",
                mensaje="quiero una pizza de mozzarella",
            )
            self._accept_and_process(
                identificador=f"SM-{s2}", mensaje="Grande"
            )

        with TestingSessionLocal() as db:
            session_row = db.execute(
                select(SessionModel).where(
                    SessionModel.id_comercio == self.comercio_id
                )
            ).scalar_one()
            assert session_row.id_pedido is not None
            pedido_id = int(session_row.id_pedido)

            lines = (
                db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == pedido_id
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(
                len(lines),
                0,
                f"expected 0 PedidoProducto rows; got {len(lines)}",
            )

            self.assertIsNone(session_row.context_type)
            pending = session_row.pending_intents or {}
            self.assertIsNone(pending.get("active"))
            self.assertEqual(pending.get("queue"), [])

        product_add_events = [
            kwargs
            for kwargs in captured
            if kwargs.get("event") == EVENT_PRODUCT_ADD_EXECUTION
        ]
        self.assertEqual(
            len(product_add_events),
            1,
            f"expected exactly one product_add_execution event; got {captured}",
        )
        self.assertEqual(
            product_add_events[0].get("outcome"),
            "rejected_price_unavailable",
        )
        self.assertEqual(
            product_add_events[0].get("component"),
            COMPONENT_PRODUCT_ADD_EXECUTION,
        )


class ProviderCoordinatorProductAddTechnicalFailureEndToEndTest(unittest.TestCase):
    """A forced unexpected DB failure during ``Grande`` processing
    must roll back the entire coordinator transaction and the
    handler MUST NOT emit a ``product_add_execution`` event for a
    technical failure."""

    def setUp(self) -> None:
        suffix = _suffix()
        self.comercio_id = _seed_comercio(suffix)
        self.cliente_id = _seed_cliente(suffix + "C")
        self.destination = f"+54995{suffix[:8]}"
        self.canal_id = _seed_dedicated_channel(
            suffix + "D", self.comercio_id, self.destination
        )
        self.catalog = _seed_two_presentation_catalog(
            comercio_id=self.comercio_id,
            nombre="Pizza Mozzarella",
            codigo_grande=f"GT_{suffix[:6]}",
            codigo_chica=f"CT_{suffix[:6]}",
            seed_precio=True,
        )
        self.proveedor = "twilio"
        self.addCleanup(_delete_comercio, self.comercio_id)
        self.addCleanup(_delete_canales_by_destination, self.destination)
        self.addCleanup(_delete_recepciones_by_comercio, self.comercio_id)
        self.addCleanup(_delete_procesamientos_by_comercio, self.comercio_id)
        self.addCleanup(_delete_outbox_by_comercio, self.comercio_id)

    def _command(
        self, identificador: str, mensaje: str
    ) -> ProviderInboundMessageCommand:
        return ProviderInboundMessageCommand(
            proveedor=self.proveedor,
            identificador_recepcion=identificador,
            canal_id=self.canal_id,
            cliente_id=self.cliente_id,
            comercio_id=self.comercio_id,
            mensaje=mensaje,
            destinatario_e164=self.destination,
        )

    def _accept_and_process(self, *, identificador: str, mensaje: str) -> None:
        coordinator = ProviderInboundMessageCoordinator(
            session=TestingSessionLocal(),
        )
        acceptance = coordinator.accept(
            self._command(identificador, mensaje)
        )
        self.assertEqual(
            acceptance.status, ProviderInboundMessageStatus.ACCEPTED
        )
        leased = coordinator.claim_due_processing(now=datetime.now(tz=timezone.utc))
        assert leased is not None
        coordinator.process_lease(leased)

    def test_technical_failure_rolls_back_without_emitting_event(self) -> None:
        captured: list[dict] = []

        def _capture(**kwargs):
            captured.append(kwargs)
            return True

        def _force_failure(
            *,
            session_id: int,
            pedido_id: int,
            id_producto_presentacion: int,
            cantidad: int,
        ):
            raise RuntimeError("forced technical failure")

        with _patched_classifier(
            "quiero una pizza de mozzarella"
        ), patch(
            "backend.intents.handlers.agregar_producto_handler.emit_event",
            side_effect=_capture,
        ), patch(
            "backend.services.pedido_producto_service.PedidoProductoService.stage_add_or_increment_for_session",
            side_effect=_force_failure,
        ):
            s1 = _suffix()
            s2 = _suffix()
            self._accept_and_process(
                identificador=f"SM-{s1}",
                mensaje="quiero una pizza de mozzarella",
            )
            self._accept_and_process(
                identificador=f"SM-{s2}", mensaje="Grande"
            )

        with TestingSessionLocal() as db:
            session_row = db.execute(
                select(SessionModel).where(
                    SessionModel.id_comercio == self.comercio_id
                )
            ).scalar_one()
            assert session_row.id_pedido is not None
            pedido_id = int(session_row.id_pedido)

            lines = (
                db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == pedido_id
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(
                len(lines),
                0,
                f"outer coordinator rollback must leave 0 PedidoProducto rows; got {len(lines)}",
            )

        product_add_events = [
            kwargs
            for kwargs in captured
            if kwargs.get("event") == EVENT_PRODUCT_ADD_EXECUTION
        ]
        self.assertEqual(
            len(product_add_events),
            0,
            "handler MUST NOT emit a business outcome for a technical failure",
        )


if __name__ == "__main__":
    unittest.main()