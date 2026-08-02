"""Real-flow HTTP regression for `modificar_producto`.

Drives the real ``POST /comercios/{id}/clientes/{id}/incoming-messages``
endpoint with the exact two reproduction phrases from subphase 3.32.2:

- ``cambia las empanadas de verdura por empanadas carne picante`` against a
  Pedido with ``Empanada de Verdura x4``. Expected: source removed,
  destination created with ``cantidad == 4``, deterministic full-transfer
  message, ``Session.context_type`` cleared.
- ``cambia las 5 empanadas de jamon y queso por un caramelo`` against a
  Pedido with ``Empanada de Jamón y Queso x5`` where ``caramelo`` is absent
  from the catalog. Expected: source unchanged with ``cantidad == 5``, no
  destination row, deterministic unknown-destination message, ``Session.
  context_type`` cleared.

The tests do NOT patch the intent classifier and do NOT hand-craft
``ProcessedIntent`` payloads. They exercise the real HTTP router, the real
session lookup, the real transactional processor, the real handler, the
real service, and the real response builder.
"""
import unittest
import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

import backend.dependencies as dependencies_module
from backend.dependencies import get_session
from backend.main import app
from backend.models import (
    CategoriaProducto,
    Cliente,
    Comercio,
    EstadoComercio,
    EstadoPedido,
    Pedido,
    PedidoProducto,
    Precio,
    Presentacion,
    Producto,
    ProductoPresentacion,
)
from backend.models import Session as SessionModel
from backend.models.session import EstadoSession


TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _override_session():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


app.dependency_overrides[get_session] = _override_session

test_client = TestClient(app)


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


def _seed_commerce(suffix: str) -> dict:
    estado_id = _estado_id_activo()
    with TestingSessionLocal() as db, db.begin():
        comercio = Comercio(
            nombre_fantasia=f"RealFlow-{suffix}",
            nombre_corto=f"RF-{suffix}",
            razon_social=f"RealFlow SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+5499{suffix[:8]}",
            calle="Real",
            numero="1",
            piso_departamento=None,
            localidad="CABA",
            provincia="BA",
            codigo_postal="C1000",
            slug=f"realflow-{suffix}",
            estado_id=estado_id,
        )
        db.add(comercio)
        db.flush()

        cliente = Cliente(
            whatsapp=f"+5499{int(suffix, 16) % 100000000:08d}",
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
            descripcion=f"Empanadas-{suffix}",
            activo=True,
            orden=0,
        )
        db.add(categoria)
        db.flush()

        prod_verdura = Producto(
            id_categoria_producto=categoria.id,
            nombre=f"Empanada de Verdura {suffix}",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        db.add(prod_verdura)
        db.flush()

        prod_carne = Producto(
            id_categoria_producto=categoria.id,
            nombre=f"Empanada de Carne Picante {suffix}",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        db.add(prod_carne)
        db.flush()

        prod_jq = Producto(
            id_categoria_producto=categoria.id,
            nombre=f"Empanada de Jamón y Queso {suffix}",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        db.add(prod_jq)
        db.flush()

        pres_unidad_verdura = Presentacion(
            id_comercio=comercio.id,
            codigo=f"verdura-unidad-{suffix}",
            descripcion=f"unidad-verdura-{suffix}",
            activo=True,
            orden=0,
        )
        db.add(pres_unidad_verdura)
        db.flush()

        pres_unidad_carne = Presentacion(
            id_comercio=comercio.id,
            codigo=f"carne-unidad-{suffix}",
            descripcion=f"unidad-carne-{suffix}",
            activo=True,
            orden=0,
        )
        db.add(pres_unidad_carne)
        db.flush()

        pres_unidad_jq = Presentacion(
            id_comercio=comercio.id,
            codigo=f"jq-unidad-{suffix}",
            descripcion=f"unidad-jq-{suffix}",
            activo=True,
            orden=0,
        )
        db.add(pres_unidad_jq)
        db.flush()

        pp_verdura = ProductoPresentacion(
            id_producto=prod_verdura.id,
            id_presentacion=pres_unidad_verdura.id,
            activo=True,
            orden=0,
        )
        db.add(pp_verdura)
        db.flush()

        pp_carne = ProductoPresentacion(
            id_producto=prod_carne.id,
            id_presentacion=pres_unidad_carne.id,
            activo=True,
            orden=0,
        )
        db.add(pp_carne)
        db.flush()

        pp_jq = ProductoPresentacion(
            id_producto=prod_jq.id,
            id_presentacion=pres_unidad_jq.id,
            activo=True,
            orden=0,
        )
        db.add(pp_jq)
        db.flush()

        db.add(Precio(id_producto_presentacion=pp_verdura.id, precio=Decimal("100.00")))
        db.add(Precio(id_producto_presentacion=pp_carne.id, precio=Decimal("120.00")))
        db.add(Precio(id_producto_presentacion=pp_jq.id, precio=Decimal("110.00")))
        db.flush()

        line_verdura = PedidoProducto(
            id_pedido=pedido.id,
            id_producto_presentacion=pp_verdura.id,
            cantidad=4,
            precio_unitario=Decimal("100.00"),
        )
        db.add(line_verdura)
        db.flush()

        line_jq = PedidoProducto(
            id_pedido=pedido.id,
            id_producto_presentacion=pp_jq.id,
            cantidad=5,
            precio_unitario=Decimal("110.00"),
        )
        db.add(line_jq)
        db.flush()

        return {
            "comercio_id": comercio.id,
            "cliente_id": cliente.id,
            "session_id": session_row.id,
            "pedido_id": pedido.id,
            "pp_verdura": pp_verdura.id,
            "pp_carne": pp_carne.id,
            "pp_jq": pp_jq.id,
            "line_verdura_id": line_verdura.id,
            "line_jq_id": line_jq.id,
            "prod_verdura_nombre": prod_verdura.nombre,
            "prod_carne_nombre": prod_carne.nombre,
            "prod_jq_nombre": prod_jq.nombre,
        }


def _cleanup(base: dict) -> None:
    with TestingSessionLocal() as db, db.begin():
        sess = db.get(SessionModel, base["session_id"])
        if sess is not None:
            sess.id_pedido = None
            sess.context_type = None
            sess.pending_intents = {}
            db.flush()
        db.execute(
            delete(PedidoProducto).where(PedidoProducto.id_pedido == base["pedido_id"])
        )
        for pp_id in (base["pp_verdura"], base["pp_carne"], base["pp_jq"]):
            db.execute(delete(Precio).where(Precio.id_producto_presentacion == pp_id))
            db.execute(
                delete(ProductoPresentacion).where(ProductoPresentacion.id == pp_id)
            )


class ModificarProductoRealFlowHttpTest(unittest.TestCase):
    def test_defect_1_full_transfer_on_omitted_quantity(self):
        suffix = _suffix()
        base = _seed_commerce(suffix)
        try:
            response = test_client.post(
                f"/comercios/{base['comercio_id']}/clientes/{base['cliente_id']}/incoming-messages",
                json={"message": "cambia las empanadas de verdura por empanadas carne picante"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            responses = payload.get("responses", [])
            self.assertEqual(len(responses), 1, payload)
            cr = responses[0]
            self.assertEqual(cr["intent"], "modificar_producto")
            self.assertEqual(cr["status"], "executed")
            self.assertIn("4", cr["message"])
            self.assertNotIn(" por 1 ", cr["message"])

            with TestingSessionLocal() as db:
                lines = list(
                    db.execute(
                        select(PedidoProducto).where(
                            PedidoProducto.id_pedido == base["pedido_id"]
                        )
                    ).scalars()
                )
                verdura_lines = [
                    l
                    for l in lines
                    if l.id_producto_presentacion == base["pp_verdura"]
                ]
                carne_lines = [
                    l
                    for l in lines
                    if l.id_producto_presentacion == base["pp_carne"]
                ]
                self.assertEqual(
                    len(verdura_lines),
                    0,
                    f"Source verdura line should be removed, found {len(verdura_lines)}",
                )
                self.assertEqual(
                    len(carne_lines),
                    1,
                    f"Destination carne line should exist, found {len(carne_lines)}",
                )
                self.assertEqual(carne_lines[0].cantidad, 4)

                sess = db.get(SessionModel, base["session_id"])
                assert sess is not None
                self.assertIsNone(sess.context_type)
        finally:
            _cleanup(base)

    def test_defect_2_unknown_destination_preserves_source(self):
        suffix = _suffix()
        base = _seed_commerce(suffix)
        try:
            response = test_client.post(
                f"/comercios/{base['comercio_id']}/clientes/{base['cliente_id']}/incoming-messages",
                json={
                    "message": "cambia las 5 empanadas de jamon y queso por un caramelo"
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            responses = payload.get("responses", [])
            self.assertEqual(len(responses), 1, payload)
            cr = responses[0]
            self.assertEqual(cr["intent"], "modificar_producto")
            self.assertEqual(cr["status"], "rejected")
            self.assertIn("Tu pedido no fue modificado", cr["message"])

            with TestingSessionLocal() as db:
                lines = list(
                    db.execute(
                        select(PedidoProducto).where(
                            PedidoProducto.id_pedido == base["pedido_id"]
                        )
                    ).scalars()
                )
                jq_lines = [
                    l
                    for l in lines
                    if l.id_producto_presentacion == base["pp_jq"]
                ]
                self.assertEqual(
                    len(jq_lines),
                    1,
                    f"Source jamon y queso line should be preserved, found {len(jq_lines)}",
                )
                self.assertEqual(jq_lines[0].cantidad, 5)

                sess = db.get(SessionModel, base["session_id"])
                if sess is None:
                    self.fail("Session not found after response")
                self.assertIsNone(sess.context_type)
        finally:
            _cleanup(base)


if __name__ == "__main__":
    unittest.main()
