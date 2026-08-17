"""Guided draft-order closure provider-path integration tests.

Complements `test_draft_order_closure.py` by exercising the provider
mapping contract: a single business result from the closure orchestrator
must produce exactly one staged outbound response row. The mapping uses
the existing `stage_outbound_rows` boundary without modifying the
provider mapper; the dedicated closure response builders are exercised
separately in `test_draft_order_closure.py`.
"""
from __future__ import annotations

import unittest
import uuid
from decimal import Decimal
from unittest.mock import MagicMock

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from backend.intents.orchestration.draft_order_closure import (
    process_initial_confirmar_pedido,
    process_initial_consultar_resumen_pedido,
    process_initial_set_metodo_de_pago,
)
from backend.models import (
    CategoriaProducto,
    Cliente,
    Comercio,
    ComercioMedioPago,
    ComercioMetodoEntrega,
    EstadoComercio,
    EstadoPedido,
    MediosPago,
    MetodosEntrega,
    Pedido,
    PedidoProducto,
    Precio,
    Presentacion,
    Producto,
    ProductoPresentacion,
)
from backend.models import Session as SessionModel
from backend.models.session import EstadoSession
from backend.services.outbound_response_mapper import stage_outbound_rows

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


def _seed() -> dict:
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

        medio = MediosPago(
            codigo=f"EF-{suffix}",
            descripcion=f"Efectivo {suffix}",
            activo=True,
        )
        db.add(medio)
        db.flush()
        db.add(
            ComercioMedioPago(
                id_comercio=comercio.id,
                id_medio_pago=medio.id,
                activo=True,
            )
        )
        db.flush()

        metodo = MetodosEntrega(
            codigo=f"RETIRO-{suffix}",
            descripcion=f"Retiro {suffix}",
            orden=0,
            activo=True,
        )
        db.add(metodo)
        db.flush()
        db.add(
            ComercioMetodoEntrega(
                id_comercio=comercio.id,
                id_metodo_entrega=metodo.id,
                activo=True,
                orden=0,
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
            "medio_pago_id": medio.id,
            "medio_pago_codigo": medio.codigo,
            "metodo_entrega_id": metodo.id,
        }


def _seed_line(*, pedido_id: int, pp_id: int) -> int:
    with TestingSessionLocal() as db, db.begin():
        line = PedidoProducto(
            id_pedido=pedido_id,
            id_producto_presentacion=pp_id,
            cantidad=1,
            precio_unitario=Decimal("100.00"),
        )
        db.add(line)
        db.flush()
        return line.id


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
            delete(ComercioMedioPago).where(
                ComercioMedioPago.id_medio_pago == ids["medio_pago_id"]
            )
        )
        db.execute(
            delete(ComercioMetodoEntrega).where(
                ComercioMetodoEntrega.id_metodo_entrega == ids["metodo_entrega_id"]
            )
        )
        db.execute(delete(MediosPago).where(MediosPago.id == ids["medio_pago_id"]))
        db.execute(
            delete(MetodosEntrega).where(
                MetodosEntrega.id == ids["metodo_entrega_id"]
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
        db.execute(
            delete(SessionModel).where(SessionModel.id == ids["session_id"])
        )
        db.execute(delete(Cliente).where(Cliente.id == ids["cliente_id"]))
        db.execute(delete(Comercio).where(Comercio.id == ids["comercio_id"]))


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


class ProviderInboundClosureOneOutboundRowTest(unittest.TestCase):
    """One provider-path scenario asserting that a single business
    result from the closure orchestrator produces exactly one staged
    outbound response row, and that the staged body is the
    specialized guided-closure response (not the generic fallback).
    """

    def test_confirmar_pedido_produces_one_outbound_row(self) -> None:
        ids = _seed()
        try:
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.id_medio_pago = ids["medio_pago_id"]
                pedido.id_metodo_entrega = ids["metodo_entrega_id"]
                _seed_line(pedido_id=ids["pedido_id"], pp_id=ids["pp_id"])
                db.commit()
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_confirmar_pedido(
                    db, session_row, "confirmar"
                )
                self.assertEqual(intent.status, "executed")
                staged = stage_outbound_rows(
                    db,
                    session_row,
                    proveedor="twilio",
                    recepcion_mensaje_proveedor_id=1,
                    destinatario_e164="+5491100000000",
                    intents=(intent,),
                    outbox_repo=_mock_outbox_repo(),
                )
                self.assertEqual(len(staged), 1)
                self.assertEqual(
                    staged[0].customer_response.intent, "confirmar_pedido"
                )
                self.assertEqual(
                    staged[0].customer_response.message,
                    "Listo, confirmamos tu pedido.",
                )
                self.assertNotIn("Disculpá", staged[0].customer_response.message)
                db.rollback()
        finally:
            _cleanup(ids)

    def test_set_metodo_de_pago_produces_one_outbound_row(self) -> None:
        ids = _seed()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_set_metodo_de_pago(
                    db, session_row, ids["medio_pago_codigo"]
                )
                self.assertEqual(intent.status, "executed")
                staged = stage_outbound_rows(
                    db,
                    session_row,
                    proveedor="twilio",
                    recepcion_mensaje_proveedor_id=1,
                    destinatario_e164="+5491100000000",
                    intents=(intent,),
                    outbox_repo=_mock_outbox_repo(),
                )
                self.assertEqual(len(staged), 1)
                self.assertEqual(
                    staged[0].customer_response.intent, "set_metodo_de_pago"
                )
                self.assertIn(
                    "Listo, medio de pago elegido:",
                    staged[0].customer_response.message,
                )
                self.assertIn(
                    ids["medio_pago_codigo"],
                    staged[0].customer_response.message,
                )
                self.assertNotIn("Disculpá", staged[0].customer_response.message)
                db.rollback()
        finally:
            _cleanup(ids)

    def test_set_metodo_de_entrega_produces_one_outbound_row(self) -> None:
        ids = _seed()
        try:
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.id_medio_pago = ids["medio_pago_id"]
                db.commit()
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                from backend.intents.orchestration.draft_order_closure import (
                    process_initial_set_metodo_de_entrega,
                )
                from backend.models import MetodosEntrega
                metodo = db.get(MetodosEntrega, ids["metodo_entrega_id"])
                assert metodo is not None
                intent = process_initial_set_metodo_de_entrega(
                    db, session_row, metodo.codigo
                )
                self.assertEqual(intent.status, "executed")
                staged = stage_outbound_rows(
                    db,
                    session_row,
                    proveedor="twilio",
                    recepcion_mensaje_proveedor_id=1,
                    destinatario_e164="+5491100000000",
                    intents=(intent,),
                    outbox_repo=_mock_outbox_repo(),
                )
                self.assertEqual(len(staged), 1)
                self.assertEqual(
                    staged[0].customer_response.intent, "set_metodo_de_entrega"
                )
                self.assertIn(
                    "Listo, método de entrega elegido:",
                    staged[0].customer_response.message,
                )
                self.assertIn(
                    metodo.codigo, staged[0].customer_response.message
                )
                self.assertNotIn("Disculpá", staged[0].customer_response.message)
                db.rollback()
        finally:
            _cleanup(ids)

    def test_consultar_resumen_pedido_produces_one_outbound_row(self) -> None:
        ids = _seed()
        try:
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.id_medio_pago = ids["medio_pago_id"]
                pedido.id_metodo_entrega = ids["metodo_entrega_id"]
                _seed_line(pedido_id=ids["pedido_id"], pp_id=ids["pp_id"])
                db.commit()
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_consultar_resumen_pedido(
                    db, session_row, "ver resumen"
                )
                self.assertEqual(intent.status, "executed")
                staged = stage_outbound_rows(
                    db,
                    session_row,
                    proveedor="twilio",
                    recepcion_mensaje_proveedor_id=1,
                    destinatario_e164="+5491100000000",
                    intents=(intent,),
                    outbox_repo=_mock_outbox_repo(),
                )
                self.assertEqual(len(staged), 1)
                self.assertEqual(
                    staged[0].customer_response.intent,
                    "consultar_resumen_pedido",
                )
                message = staged[0].customer_response.message
                self.assertIn("Tu pedido:", message)
                self.assertIn("- 1", message)
                self.assertIn(ids["medio_pago_codigo"], message)
                self.assertNotIn("Disculpá", message)
                db.rollback()
        finally:
            _cleanup(ids)


if __name__ == "__main__":
    unittest.main()
