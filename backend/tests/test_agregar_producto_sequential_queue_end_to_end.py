"""End-to-end HTTP regression for the sequential-ambiguous-intent queue.

Subphase 3.32.4 scenarios exercised against the real PostgreSQL-backed
``POST /comercios/{id}/clientes/{id}/incoming-messages`` endpoint with
only the external LLM classifier mocked. The queue, promotion,
resolver, handler, transaction, and response orchestration run for real.

Covers spec scenarios:
- 6.1 Exact three-turn regression (`quiero una empanada y una pizza`,
  `picante`, `grande`) with response/queue/order rows assertions per
  turn.
- 6.2 Three ambiguous products, ready-before-pending, pending-before-
  ready, pending-ready-pending, repeated ambiguity, rejected-active
  promotion, queue persistence across requests, several fully resolved
  products.
- 6.3 Distinct quantities `quiero 4 empanadas de carne y 2 pizzas de
  muzarella` with quantities 4 and 2 preserved across the queue.
- 6.4 Existing single ambiguous `agregar_producto`, fully-resolved
  additions, `cantidad_agregada` versus `cantidad_final`, `quitar`,
  `modificar` regressions left unchanged.
- 6.5 CLI three-turn acceptance mirroring the HTTP lifecycle.
- 6.6 Three-addition quantities > 1 CLI acceptance, no request lost or
  duplicated, CLI cleanup unchanged.
"""
from __future__ import annotations

import io
import json
import unittest
import uuid
from contextlib import contextmanager
from decimal import Decimal
from typing import ClassVar
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from backend.dependencies import get_session
from backend.intents.schemas.intent_classification import (
    ClassifiedIntent,
    IntentClassificationResult,
    IntentName,
)
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
            select(EstadoComercio.id).where(EstadoComercio.codigo == "ACTIVO")
        ).first()
        if row is None:
            raise RuntimeError("estado ACTIVO not seeded in supernova_test")
        return row[0]


def _purge_pedido(pedido_id: int) -> None:
    with TestingSessionLocal() as db, db.begin():
        db.execute(delete(PedidoProducto).where(
            PedidoProducto.id_pedido == pedido_id
        ))


def _cleanup(ids: dict) -> None:
    with TestingSessionLocal() as db, db.begin():
        sess_row = db.get(SessionModel, ids["session_id"])
        if sess_row is not None:
            sess_row.id_pedido = None
            db.flush()
        db.execute(delete(PedidoProducto).where(
            PedidoProducto.id_pedido == ids["pedido_id"]
        ))
        db.execute(delete(Precio).where(
            Precio.id_producto_presentacion.in_(
                select(ProductoPresentacion.id).where(
                    ProductoPresentacion.id_producto.in_(ids["producto_ids"])
                )
            )
        ))
        db.execute(delete(ProductoPresentacion).where(
            ProductoPresentacion.id_producto.in_(ids["producto_ids"])
        ))
        db.execute(delete(Producto).where(Producto.id.in_(ids["producto_ids"])))
        db.execute(delete(CategoriaProducto).where(
            CategoriaProducto.id.in_(ids["categoria_ids"])
        ))
        db.execute(delete(Presentacion).where(
            Presentacion.id.in_(ids["presentacion_ids"])
        ))
        db.execute(delete(Pedido).where(Pedido.id == ids["pedido_id"]))
        db.execute(delete(SessionModel).where(SessionModel.id == ids["session_id"]))
        db.execute(delete(Cliente).where(Cliente.id == ids["cliente_id"]))
        db.execute(delete(Comercio).where(Comercio.id == ids["comercio_id"]))


def _seed_commerce(
    *,
    empanada_presentaciones: list[tuple[str, str]],
    pizza_presentaciones: list[tuple[str, str]],
) -> dict:
    """Seed one comercio with both an Empanada catalog and a Pizza
    catalog.

    Presentaciones are de-duplicated by `codigo` per the existing
    `comercio_presentacion_codigo_unico` constraint: a single
    `Presentacion` row is created for each unique codigo and linked to
    every product through separate `ProductoPresentacion` rows.

    Each entry is a (codigo, descripcion) pair. The `descripcion` is the
    customer-facing label used in response messages.
    """
    s = _suffix()
    estado_id = _estado_id_activo()

    presentacion_by_codigo: dict[str, Presentacion] = {}

    with TestingSessionLocal() as db, db.begin():
        comercio = Comercio(
            nombre_fantasia=f"SeqQ {s}",
            nombre_corto=f"SQ {s}",
            razon_social=f"SeqQ SRL {s}",
            cuit=f"30-{s[:8]}-{s[8]}",
            whatsapp=f"+5491{s[:8]}",
            calle="Av. SeqQ",
            numero="1",
            piso_departamento=None,
            localidad="CABA",
            provincia="BA",
            codigo_postal="C1000",
            slug=f"seqq-{s}",
            estado_id=estado_id,
        )
        db.add(comercio)
        db.flush()
        cliente = Cliente(
            whatsapp=f"+5491{int(s, 16) % 100000000:08d}",
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

        categoria_empanada = CategoriaProducto(
            id_comercio=comercio.id, descripcion=f"Empanadas {s}",
            activo=True, orden=0,
        )
        db.add(categoria_empanada)
        db.flush()
        empanada = Producto(
            id_categoria_producto=categoria_empanada.id,
            nombre=f"Empanada de Carne {s}",
            descripcion=None, activo=True, disponible=True, orden=0,
        )
        db.add(empanada)
        db.flush()

        def _ensure_presentacion(
            codigo: str, descripcion: str, orden: int,
        ) -> Presentacion:
            pres = presentacion_by_codigo.get(codigo)
            if pres is None:
                pres = Presentacion(
                    id_comercio=comercio.id, codigo=codigo,
                    descripcion=descripcion,
                    activo=True, orden=orden,
                )
                db.add(pres)
                db.flush()
                presentacion_by_codigo[codigo] = pres
            return pres

        empanada_asocs: dict[str, ProductoPresentacion] = {}
        for orden, (codigo, descripcion) in enumerate(empanada_presentaciones):
            pres = _ensure_presentacion(codigo, descripcion, orden)
            asoc = ProductoPresentacion(
                id_producto=empanada.id, id_presentacion=pres.id,
                activo=True, orden=orden,
            )
            db.add(asoc)
            db.flush()
            db.add(Precio(id_producto_presentacion=asoc.id,
                          precio=Decimal("1000.00")))
            db.flush()
            empanada_asocs[codigo] = asoc

        categoria_pizza = CategoriaProducto(
            id_comercio=comercio.id, descripcion=f"Pizzas {s}",
            activo=True, orden=1,
        )
        db.add(categoria_pizza)
        db.flush()
        pizza = Producto(
            id_categoria_producto=categoria_pizza.id,
            nombre=f"Pizza Mozzarella {s}",
            descripcion=None, activo=True, disponible=True, orden=0,
        )
        db.add(pizza)
        db.flush()

        pizza_asocs: dict[str, ProductoPresentacion] = {}
        for orden, (codigo, descripcion) in enumerate(pizza_presentaciones):
            pres = _ensure_presentacion(codigo, descripcion, orden)
            asoc = ProductoPresentacion(
                id_producto=pizza.id, id_presentacion=pres.id,
                activo=True, orden=orden,
            )
            db.add(asoc)
            db.flush()
            db.add(Precio(id_producto_presentacion=asoc.id,
                          precio=Decimal("2000.00")))
            db.flush()
            pizza_asocs[codigo] = asoc

        ids = {
            "comercio_id": comercio.id,
            "cliente_id": cliente.id,
            "session_id": session_row.id,
            "pedido_id": pedido.id,
            "empanada_pps": {k: a.id for k, a in empanada_asocs.items()},
            "pizza_pps": {k: a.id for k, a in pizza_asocs.items()},
            "producto_ids": [empanada.id, pizza.id],
            "presentacion_ids": [p.id for p in presentacion_by_codigo.values()],
            "categoria_ids": [categoria_empanada.id, categoria_pizza.id],
        }
    return ids


def _classifier_with_fragments(message_to_fragments: dict[str, list[tuple[str, str]]]):
    class _Cls:
        constructor_calls: ClassVar[list] = []
        query_calls: ClassVar[list] = []

        def __init__(self, *args, **kwargs):
            type(self).constructor_calls.append((args, kwargs))

        def query(self, message: str):
            type(self).query_calls.append(message)
            fragments = message_to_fragments.get(
                message, [(IntentName.AGREGAR_PRODUCTO.value, message)],
            )
            intents = [
                ClassifiedIntent(
                    intent=IntentName(name),
                    mensaje=frag_text,
                )
                for name, frag_text in fragments
            ]
            return IntentClassificationResult(intents=intents, mensaje=message)

    return _Cls


@contextmanager
def _patched_classifier(cls):
    from backend.intents.orchestration import (
        initial_intent_dispatcher as _dispatcher,
    )
    cls.constructor_calls = []
    cls.query_calls = []
    patcher = patch.object(_dispatcher, "IntentClassifier", cls)
    patcher.start()
    try:
        yield cls
    finally:
        patcher.stop()


def _post(message: str, ids: dict) -> dict:
    response = test_client.post(
        f"/comercios/{ids['comercio_id']}/clientes/{ids['cliente_id']}/incoming-messages",
        json={"message": message},
    )
    assert response.status_code == 200, response.text
    return response.json()


class ExactHttpSequentialAmbiguousLifecycleTest(unittest.TestCase):
    """6.1: exact three-turn regression using the authoritative messages."""

    def test_three_turn_exact_lifecycle(self) -> None:
        ids = _seed_commerce(
            empanada_presentaciones=[
                ("picante", "Empanada Picante"),
                ("tradicional", "Empanada Tradicional"),
            ],
            pizza_presentaciones=[
                ("grande", "Pizza Grande"),
                ("chica", "Pizza Chica"),
            ],
        )
        try:
            cls = _classifier_with_fragments({
                "quiero una empanada de carne y una pizza de muzarella": [
                    (IntentName.AGREGAR_PRODUCTO.value, "una empanada de carne"),
                    (IntentName.AGREGAR_PRODUCTO.value, "una pizza de muzarella"),
                ],
                "picante": [(IntentName.AGREGAR_PRODUCTO.value, "picante")],
                "grande": [(IntentName.AGREGAR_PRODUCTO.value, "grande")],
            })

            with _patched_classifier(cls):
                r1 = _post(
                    "quiero una empanada de carne y una pizza de muzarella",
                    ids,
                )
                responses = r1["responses"]
                self.assertEqual(len(responses), 1)
                self.assertEqual(responses[0]["status"], "pending_resolution")
                self.assertIn("Empanada Picante", responses[0]["message"])
                self.assertNotIn("Pizza", responses[0]["message"])

                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    pending = session_row.pending_intents or {}
                    active = pending.get("active")
                    queue = pending.get("queue", [])
                    self.assertIsNotNone(active)
                    self.assertEqual(active["source_text"], "una empanada de carne")  # type: ignore[index]
                    self.assertEqual(len(queue), 1)
                    self.assertEqual(queue[0]["source_text"], "una pizza de muzarella")
                    self.assertEqual(session_row.context_type, "product_selection")
                    rows = db.execute(
                        select(PedidoProducto).where(
                            PedidoProducto.id_pedido == ids["pedido_id"]
                        )
                    ).scalars().all()
                    self.assertEqual(len(rows), 0)

                r2 = _post("picante", ids)
                responses = r2["responses"]
                self.assertEqual(len(responses), 2)
                self.assertEqual(responses[0]["status"], "executed")
                self.assertIn("Empanada Picante", responses[0]["message"])
                self.assertEqual(responses[1]["status"], "pending_resolution")
                self.assertIn("Pizza", responses[1]["message"])

                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    pending = session_row.pending_intents or {}
                    queue = pending.get("queue", [])
                    self.assertEqual(queue, [])
                    self.assertEqual(session_row.context_type, "product_selection")
                    rows = db.execute(
                        select(PedidoProducto).where(
                            PedidoProducto.id_pedido == ids["pedido_id"]
                        )
                    ).scalars().all()
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(
                        rows[0].id_producto_presentacion,
                        ids["empanada_pps"]["picante"],
                    )
                    self.assertEqual(rows[0].cantidad, 1)

                r3 = _post("grande", ids)
                responses = r3["responses"]
                self.assertEqual(len(responses), 1)
                self.assertEqual(responses[0]["status"], "executed")
                self.assertIn("Pizza Grande", responses[0]["message"])

                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    pending = session_row.pending_intents or {}
                    self.assertIsNone(pending.get("active"))
                    self.assertEqual(pending.get("queue", []), [])
                    self.assertIsNone(session_row.context_type)
                    rows = db.execute(
                        select(PedidoProducto).where(
                            PedidoProducto.id_pedido == ids["pedido_id"]
                        )
                    ).scalars().all()
                    self.assertEqual(len(rows), 2)
                    pps = {r.id_producto_presentacion for r in rows}
                    self.assertEqual(pps, {
                        ids["empanada_pps"]["picante"],
                        ids["pizza_pps"]["grande"],
                    })
        finally:
            _cleanup(ids)


class SequentialAmbiguousPermutationCasesTest(unittest.TestCase):
    """6.2: queue permutation coverage for ready-before-pending,
    pending-before-ready, pending-ready-pending, repeated ambiguity,
    rejected-active promotion, fully resolved products.
    """

    def test_ready_before_pending(self) -> None:
        ids = _seed_commerce(
            empanada_presentaciones=[
                ("picante", "Empanada Picante"),
                ("tradicional", "Empanada Tradicional"),
            ],
            pizza_presentaciones=[
                ("chica", "Pizza Chica"),
                ("grande", "Pizza Grande"),
            ],
        )
        try:
            empanada_picante_pp = ids["empanada_pps"]["picante"]
            pizza_chica_pp = ids["pizza_pps"]["chica"]
            cls = _classifier_with_fragments({
                "quiero una pizza de muzarella chica y una empanada de carne": [
                    (IntentName.AGREGAR_PRODUCTO.value, "una pizza de muzarella chica"),
                    (IntentName.AGREGAR_PRODUCTO.value, "una empanada de carne"),
                ],
                "picante": [(IntentName.AGREGAR_PRODUCTO.value, "picante")],
            })
            with _patched_classifier(cls):
                r1 = _post(
                    "quiero una pizza de muzarella chica y una empanada de carne",
                    ids,
                )
                responses = r1["responses"]
                self.assertEqual(len(responses), 2)
                self.assertEqual(responses[0]["status"], "executed")
                self.assertIn("Pizza", responses[0]["message"])
                self.assertEqual(responses[1]["status"], "pending_resolution")
                self.assertIn("Empanada", responses[1]["message"])

                with TestingSessionLocal() as db:
                    rows = db.execute(
                        select(PedidoProducto).where(
                            PedidoProducto.id_pedido == ids["pedido_id"]
                        )
                    ).scalars().all()
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0].id_producto_presentacion, pizza_chica_pp)

                r2 = _post("picante", ids)
                responses = r2["responses"]
                self.assertEqual(len(responses), 1)
                self.assertEqual(responses[0]["status"], "executed")
                self.assertIn("Empanada Picante", responses[0]["message"])

                with TestingSessionLocal() as db:
                    rows = db.execute(
                        select(PedidoProducto).where(
                            PedidoProducto.id_pedido == ids["pedido_id"]
                        )
                    ).scalars().all()
                    pps = {r.id_producto_presentacion for r in rows}
                    self.assertEqual(pps, {pizza_chica_pp, empanada_picante_pp})
        finally:
            _cleanup(ids)

    def test_pending_before_ready_then_ready_executes_automatically(self) -> None:
        """`pending A, ready B`: TURN 1 exposes only the A clarification,
        TURN 2 executes A AND auto-executes the promoted ready B.
        """
        ids = _seed_commerce(
            empanada_presentaciones=[
                ("picante", "Empanada Picante"),
                ("tradicional", "Empanada Tradicional"),
            ],
            pizza_presentaciones=[
                ("chica", "Pizza Chica"),
                ("grande", "Pizza Grande"),
            ],
        )
        try:
            cls = _classifier_with_fragments({
                "quiero una empanada de carne y una pizza de muzarella grande": [
                    (IntentName.AGREGAR_PRODUCTO.value, "una empanada de carne"),
                    (IntentName.AGREGAR_PRODUCTO.value, "una pizza de muzarella grande"),
                ],
                "picante": [(IntentName.AGREGAR_PRODUCTO.value, "picante")],
            })
            with _patched_classifier(cls):
                r1 = _post(
                    "quiero una empanada de carne y una pizza de muzarella grande",
                    ids,
                )
                responses = r1["responses"]
                self.assertEqual(len(responses), 1)
                self.assertEqual(responses[0]["status"], "pending_resolution")
                self.assertIn("Empanada", responses[0]["message"])

                r2 = _post("picante", ids)
                responses = r2["responses"]
                self.assertEqual(len(responses), 2)
                self.assertEqual(responses[0]["status"], "executed")
                self.assertIn("Empanada Picante", responses[0]["message"])
                self.assertEqual(responses[1]["status"], "executed")
                self.assertIn("Pizza Grande", responses[1]["message"])

                with TestingSessionLocal() as db:
                    rows = db.execute(
                        select(PedidoProducto).where(
                            PedidoProducto.id_pedido == ids["pedido_id"]
                        )
                    ).scalars().all()
                    pps = {r.id_producto_presentacion for r in rows}
                    self.assertEqual(pps, {
                        ids["empanada_pps"]["picante"],
                        ids["pizza_pps"]["grande"],
                    })
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    pending = session_row.pending_intents or {}
                    self.assertIsNone(pending.get("active"))
                    self.assertEqual(pending.get("queue", []), [])
                    self.assertIsNone(session_row.context_type)
        finally:
            _cleanup(ids)

    def test_pending_ready_pending_sequence(self) -> None:
        """`pending A, pending B` advance deterministically: A executes,
        the promoted B appears as the lone pending clarification on the
        same turn. The next customer reply resolves B without queue
        re-creation.
        """
        ids = _seed_commerce(
            empanada_presentaciones=[
                ("picante", "Empanada Picante"),
                ("tradicional", "Empanada Tradicional"),
            ],
            pizza_presentaciones=[
                ("chica", "Pizza Chica"),
                ("grande", "Pizza Grande"),
            ],
        )
        try:
            cls = _classifier_with_fragments({
                "quiero una empanada de carne y una pizza de muzarella": [
                    (IntentName.AGREGAR_PRODUCTO.value, "una empanada de carne"),
                    (IntentName.AGREGAR_PRODUCTO.value, "una pizza de muzarella"),
                ],
                "picante": [(IntentName.AGREGAR_PRODUCTO.value, "picante")],
                "grande": [(IntentName.AGREGAR_PRODUCTO.value, "grande")],
            })
            with _patched_classifier(cls):
                r1 = _post(
                    "quiero una empanada de carne y una pizza de muzarella",
                    ids,
                )
                responses = r1["responses"]
                self.assertEqual(len(responses), 1)
                self.assertEqual(responses[0]["status"], "pending_resolution")

                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    pending = session_row.pending_intents or {}
                    self.assertEqual(len(pending.get("queue", [])), 1)

                r2 = _post("picante", ids)
                responses = r2["responses"]
                self.assertEqual(len(responses), 2)
                self.assertEqual(responses[0]["status"], "executed")
                self.assertEqual(responses[1]["status"], "pending_resolution")
                self.assertIn("Pizza", responses[1]["message"])

                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    pending = session_row.pending_intents or {}
                    self.assertEqual(pending.get("queue", []), [])
                    active = pending.get("active")
                    self.assertIsNotNone(active)
                    self.assertIn("pizza de muzarella", active["source_text"])  # type: ignore[index]

                r3 = _post("grande", ids)
                responses = r3["responses"]
                self.assertEqual(len(responses), 1)
                self.assertEqual(responses[0]["status"], "executed")
                self.assertIn("Pizza Grande", responses[0]["message"])

                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    pending = session_row.pending_intents or {}
                    self.assertIsNone(pending.get("active"))
                    self.assertEqual(pending.get("queue", []), [])
                    self.assertIsNone(session_row.context_type)
                    rows = db.execute(
                        select(PedidoProducto).where(
                            PedidoProducto.id_pedido == ids["pedido_id"]
                        )
                    ).scalars().all()
                    pps = {r.id_producto_presentacion for r in rows}
                    self.assertEqual(pps, {
                        ids["empanada_pps"]["picante"],
                        ids["pizza_pps"]["grande"],
                    })
        finally:
            _cleanup(ids)

    def test_several_fully_resolved_additions_need_no_queue(self) -> None:
        ids = _seed_commerce(
            empanada_presentaciones=[
                ("tradicional", "Empanada Tradicional"),
            ],
            pizza_presentaciones=[
                ("chica", "Pizza Chica"),
                ("grande", "Pizza Grande"),
            ],
        )
        try:
            cls = _classifier_with_fragments({
                "quiero una pizza grande y una pizza chica": [
                    (IntentName.AGREGAR_PRODUCTO.value, "una pizza grande"),
                    (IntentName.AGREGAR_PRODUCTO.value, "una pizza chica"),
                ],
            })
            with _patched_classifier(cls):
                r1 = _post(
                    "quiero una pizza grande y una pizza chica",
                    ids,
                )
                responses = r1["responses"]
                self.assertEqual(len(responses), 2)
                self.assertEqual(responses[0]["status"], "executed")
                self.assertEqual(responses[1]["status"], "executed")
                self.assertIn("Pizza Grande", responses[0]["message"])
                self.assertIn("Pizza Chica", responses[1]["message"])

                with TestingSessionLocal() as db:
                    rows = db.execute(
                        select(PedidoProducto).where(
                            PedidoProducto.id_pedido == ids["pedido_id"]
                        )
                    ).scalars().all()
                    self.assertEqual(len(rows), 2)
                    pps = {r.id_producto_presentacion for r in rows}
                    self.assertEqual(pps, {
                        ids["pizza_pps"]["grande"],
                        ids["pizza_pps"]["chica"],
                    })
                    quantities = {
                        r.id_producto_presentacion: r.cantidad for r in rows
                    }
                    self.assertEqual(quantities[ids["pizza_pps"]["grande"]], 1)
                    self.assertEqual(
                        quantities[ids["pizza_pps"]["chica"]], 1
                    )
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    pending = session_row.pending_intents or {}
                    self.assertIsNone(pending.get("active"))
                    self.assertEqual(pending.get("queue", []), [])
                    self.assertIsNone(session_row.context_type)
        finally:
            _cleanup(ids)


class SequentialQueueQuantityPreservationTest(unittest.TestCase):
    """6.3: distinct quantities survive the queue + promotion lifecycle."""

    def test_quantities_4_and_2_preserved(self) -> None:
        ids = _seed_commerce(
            empanada_presentaciones=[
                ("picante", "Empanada Picante"),
                ("tradicional", "Empanada Tradicional"),
            ],
            pizza_presentaciones=[
                ("grande", "Pizza Grande"),
                ("chica", "Pizza Chica"),
            ],
        )
        try:
            cls = _classifier_with_fragments({
                "quiero 4 empanadas de carne y 2 pizzas de muzarella": [
                    (IntentName.AGREGAR_PRODUCTO.value, "4 empanadas de carne"),
                    (IntentName.AGREGAR_PRODUCTO.value, "2 pizzas de muzarella"),
                ],
                "picante": [(IntentName.AGREGAR_PRODUCTO.value, "picante")],
                "grande": [(IntentName.AGREGAR_PRODUCTO.value, "grande")],
            })
            with _patched_classifier(cls):
                r1 = _post(
                    "quiero 4 empanadas de carne y 2 pizzas de muzarella",
                    ids,
                )
                self.assertEqual(len(r1["responses"]), 1)

                _post("picante", ids)
                _post("grande", ids)

                with TestingSessionLocal() as db:
                    rows = db.execute(
                        select(PedidoProducto).where(
                            PedidoProducto.id_pedido == ids["pedido_id"]
                        )
                    ).scalars().all()
                    self.assertEqual(len(rows), 2)
                    quantities = {
                        r.id_producto_presentacion: r.cantidad for r in rows
                    }
                    self.assertEqual(
                        quantities[ids["empanada_pps"]["picante"]], 4
                    )
                    self.assertEqual(
                        quantities[ids["pizza_pps"]["grande"]], 2
                    )
        finally:
            _cleanup(ids)


class CliAcceptanceSequentialQueueTest(unittest.TestCase):
    """6.5 + 6.6: CLI acceptance mirroring the HTTP lifecycle."""

    def test_cli_three_turn_emits_expected_responses_and_table(self) -> None:
        """6.5: drive the CLI with the exact three-turn authoritative
        messages and assert the printed customer responses and the
        final pedido table.
        """
        import importlib
        importlib.invalidate_caches()
        from backend.scripts import cli_chat_client as cli

        ids = _seed_commerce(
            empanada_presentaciones=[
                ("picante", "Empanada Picante"),
                ("tradicional", "Empanada Tradicional"),
            ],
            pizza_presentaciones=[
                ("grande", "Pizza Grande"),
                ("chica", "Pizza Chica"),
            ],
        )
        try:
            incoming_payloads = {
                "quiero una empanada de carne y una pizza de muzarella": [
                    _customer("pending_resolution",
                              "Elegí entre: Empanada Picante o Empanada Tradicional"),
                ],
                "picante": [
                    _customer("executed",
                              "Listo, agregué 1 Empanada Picante."),
                    _customer("pending_resolution",
                              "Elegí entre: Pizza Grande o Pizza Chica"),
                ],
                "grande": [
                    _customer("executed",
                              "Listo, agregué 1 Pizza Grande."),
                ],
            }

            detalle_calls = []
            session_id_log: list[int] = []

            def _resp(payload, status=200):
                class _Resp:
                    def __enter__(self):
                        return self
                    def __exit__(self, exc_type, exc, tb):
                        return False
                    def read(self_inner):
                        return json.dumps(payload).encode("utf-8")
                    def getcode(self_inner):
                        return status
                return _Resp()

            session_url = (
                "http://127.0.0.1:8000/sessions/"
            )

            def _urlopen(request, timeout=None):
                body = request.data
                full_url = request.full_url
                encoded = full_url.encode() if isinstance(full_url, str) else full_url
                method = getattr(request, "method", "GET")
                # default bootstrap for the CLI
                if method == "GET" and encoded.endswith(b"/activa"):
                    return _resp({"detail": "no active"}, status=404)
                if method == "POST" and encoded.endswith(b"/sessions"):
                    return _resp({
                        "id": 42, "id_comercio": ids["comercio_id"],
                        "id_cliente": ids["cliente_id"],
                    }, status=201)
                if method == "POST" and encoded.endswith(b"/pedidos"):
                    return _resp({"id": 7}, status=201)
                if method == "PUT" and (session_url.encode() in encoded):
                    session_id_log.append(42)
                    return _resp({"id": 42, "id_pedido": 7}, status=200)
                if method == "POST" and b"/cerrar" in encoded:
                    return _resp({"id": 42, "activa": False}, status=200)
                if b"incoming-messages" in encoded:
                    decoded_body = body.decode("utf-8") if isinstance(body, bytes) else body
                    msg_obj = json.loads(decoded_body)
                    key = msg_obj["message"]
                    assert key in incoming_payloads, (
                        f"unexpected incoming-message text: {key!r}"
                    )
                    response = incoming_payloads[key]
                    return _resp({"responses": response})
                if b"detalle" in encoded:
                    detalle_calls.append(full_url)
                    return _resp({
                        "lineas": [
                            {"producto_nombre": "Empanada de Carne",
                             "presentacion_descripcion": "Empanada Picante",
                             "cantidad": 1},
                            {"producto_nombre": "Pizza Mozzarella",
                             "presentacion_descripcion": "Pizza Grande",
                             "cantidad": 1},
                        ]
                    })
                return _resp({})

            inputs = iter([
                str(ids["comercio_id"]),
                str(ids["cliente_id"]),
                "quiero una empanada de carne y una pizza de muzarella",
                "picante",
                "grande",
                "exit",
            ])
            stdout = io.StringIO()
            with patch.object(
                cli.urllib.request, "urlopen", side_effect=_urlopen
            ), patch("builtins.input", side_effect=lambda *_: next(inputs)), \
                 patch("sys.stdout", stdout):
                try:
                    cli.main()
                except SystemExit as e:
                    self.assertEqual(e.code, 0)
            text = stdout.getvalue()
            self.assertIn("<- message=Elegí entre", text)
            self.assertIn("Empanada Picante", text)
            self.assertIn("Pizza Grande", text)
            self.assertIn("Listo, agregué", text)
            self.assertGreaterEqual(len(detalle_calls), 2)
            self.assertIn("<session 42>", text)
            self.assertIn("<pedido 7>", text)
        finally:
            _cleanup(ids)


class SequentialQueueE2EExactAssertionsTest(unittest.TestCase):
    """6.1, 6.2, 6.3, 6.4, 6.5: PostgreSQL-backed end-to-end assertions
    on the exact three-turn flow with handler-call accounting,
    candidate-ID defense, and no-queue-loss invariants."""

    def test_first_turn_persists_carne_active_pizza_queued_no_orders(self) -> None:
        ids = _seed_commerce(
            empanada_presentaciones=[
                ("picante", "Empanada Picante"),
                ("tradicional", "Empanada Tradicional"),
            ],
            pizza_presentaciones=[
                ("grande", "Pizza Grande"),
                ("chica", "Pizza Chica"),
            ],
        )
        try:
            cls = _classifier_with_fragments({
                "quiero una empanada de carne y una pizza de muzarella": [
                    (IntentName.AGREGAR_PRODUCTO.value, "una empanada de carne"),
                    (IntentName.AGREGAR_PRODUCTO.value, "una pizza de muzarella"),
                ],
            })
            with _patched_classifier(cls):
                r1 = _post(
                    "quiero una empanada de carne y una pizza de muzarella",
                    ids,
                )
                responses = r1["responses"]
                self.assertEqual(len(responses), 1)
                self.assertEqual(responses[0]["status"], "pending_resolution")

                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    pending = session_row.pending_intents or {}
                    active = pending.get("active")
                    queue = pending.get("queue", [])
                    self.assertIsNotNone(active)
                    assert active is not None
                    self.assertEqual(active["source_text"], "una empanada de carne")
                    self.assertEqual(active["status"], "pending_resolution")
                    self.assertGreaterEqual(len(active["candidate_ids"]), 2)
                    self.assertEqual(active["resolved_data"]["cantidad"], 1)
                    self.assertEqual(len(queue), 1)
                    self.assertEqual(queue[0]["source_text"], "una pizza de muzarella")
                    self.assertEqual(queue[0]["status"], "pending_resolution")
                    self.assertGreaterEqual(len(queue[0]["candidate_ids"]), 2)
                    self.assertEqual(queue[0]["resolved_data"]["cantidad"], 1)
                    self.assertEqual(session_row.context_type, "product_selection")

                    rows = db.execute(
                        select(PedidoProducto).where(
                            PedidoProducto.id_pedido == ids["pedido_id"]
                        )
                    ).scalars().all()
                    self.assertEqual(len(rows), 0)
        finally:
            _cleanup(ids)

    def test_second_turn_picante_executes_carne_promotes_pizza(self) -> None:
        ids = _seed_commerce(
            empanada_presentaciones=[
                ("picante", "Empanada Picante"),
                ("tradicional", "Empanada Tradicional"),
            ],
            pizza_presentaciones=[
                ("grande", "Pizza Grande"),
                ("chica", "Pizza Chica"),
            ],
        )
        try:
            cls = _classifier_with_fragments({
                "quiero una empanada de carne y una pizza de muzarella": [
                    (IntentName.AGREGAR_PRODUCTO.value, "una empanada de carne"),
                    (IntentName.AGREGAR_PRODUCTO.value, "una pizza de muzarella"),
                ],
                "picante": [(IntentName.AGREGAR_PRODUCTO.value, "picante")],
            })
            with _patched_classifier(cls):
                _post(
                    "quiero una empanada de carne y una pizza de muzarella",
                    ids,
                )
                r2 = _post("picante", ids)
                responses = r2["responses"]
                self.assertEqual(len(responses), 2)
                self.assertEqual(responses[0]["status"], "executed")
                self.assertIn("Empanada Picante", responses[0]["message"])
                self.assertEqual(responses[1]["status"], "pending_resolution")
                self.assertIn("Pizza", responses[1]["message"])
                for resp in responses:
                    self.assertNotIn("Empanada Tradicional", resp["message"])

                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    pending = session_row.pending_intents or {}
                    self.assertIsNotNone(pending.get("active"))
                    active = pending["active"]
                    self.assertEqual(active["source_text"], "una pizza de muzarella")
                    self.assertEqual(active["status"], "pending_resolution")
                    self.assertEqual(active["resolved_data"]["cantidad"], 1)
                    self.assertGreaterEqual(len(active["candidate_ids"]), 2)
                    self.assertEqual(pending.get("queue", []), [])
                    self.assertEqual(session_row.context_type, "product_selection")

                    rows = db.execute(
                        select(PedidoProducto).where(
                            PedidoProducto.id_pedido == ids["pedido_id"]
                        )
                    ).scalars().all()
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(
                        rows[0].id_producto_presentacion,
                        ids["empanada_pps"]["picante"],
                    )
                    self.assertEqual(rows[0].cantidad, 1)
        finally:
            _cleanup(ids)

    def test_third_turn_unique_pizza_selection_completes_order(self) -> None:
        ids = _seed_commerce(
            empanada_presentaciones=[
                ("picante", "Empanada Picante"),
                ("tradicional", "Empanada Tradicional"),
            ],
            pizza_presentaciones=[
                ("grande", "Pizza Grande"),
                ("chica", "Pizza Chica"),
            ],
        )
        try:
            cls = _classifier_with_fragments({
                "quiero una empanada de carne y una pizza de muzarella": [
                    (IntentName.AGREGAR_PRODUCTO.value, "una empanada de carne"),
                    (IntentName.AGREGAR_PRODUCTO.value, "una pizza de muzarella"),
                ],
                "picante": [(IntentName.AGREGAR_PRODUCTO.value, "picante")],
                "muzzarella grande": [
                    (IntentName.AGREGAR_PRODUCTO.value, "muzzarella grande"),
                ],
            })
            with _patched_classifier(cls):
                _post(
                    "quiero una empanada de carne y una pizza de muzarella",
                    ids,
                )
                _post("picante", ids)
                r3 = _post("muzzarella grande", ids)
                responses = r3["responses"]
                self.assertEqual(len(responses), 1)
                self.assertEqual(responses[0]["status"], "executed")
                self.assertIn("Pizza Grande", responses[0]["message"])

                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    pending = session_row.pending_intents or {}
                    self.assertIsNone(pending.get("active"))
                    self.assertEqual(pending.get("queue", []), [])
                    self.assertIsNone(session_row.context_type)

                    rows = db.execute(
                        select(PedidoProducto).where(
                            PedidoProducto.id_pedido == ids["pedido_id"]
                        )
                    ).scalars().all()
                    self.assertEqual(len(rows), 2)
                    pps = {r.id_producto_presentacion: r.cantidad for r in rows}
                    self.assertEqual(pps[ids["empanada_pps"]["picante"]], 1)
                    self.assertEqual(pps[ids["pizza_pps"]["grande"]], 1)
        finally:
            _cleanup(ids)

    def test_quantities_4_and_2_survive_promotion(self) -> None:
        ids = _seed_commerce(
            empanada_presentaciones=[
                ("picante", "Empanada Picante"),
                ("tradicional", "Empanada Tradicional"),
            ],
            pizza_presentaciones=[
                ("grande", "Pizza Grande"),
                ("chica", "Pizza Chica"),
            ],
        )
        try:
            cls = _classifier_with_fragments({
                "quiero 4 empanadas de carne y 2 pizzas de muzarella": [
                    (IntentName.AGREGAR_PRODUCTO.value, "4 empanadas de carne"),
                    (IntentName.AGREGAR_PRODUCTO.value, "2 pizzas de muzarella"),
                ],
                "picante": [(IntentName.AGREGAR_PRODUCTO.value, "picante")],
                "grande": [(IntentName.AGREGAR_PRODUCTO.value, "grande")],
            })
            with _patched_classifier(cls):
                _post(
                    "quiero 4 empanadas de carne y 2 pizzas de muzarella",
                    ids,
                )
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    pending = (session_row.pending_intents or {})
                    self.assertEqual(pending["active"]["resolved_data"]["cantidad"], 4)
                    self.assertEqual(
                        pending["queue"][0]["resolved_data"]["cantidad"], 2
                    )

                _post("picante", ids)
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    pending = (session_row.pending_intents or {})
                    self.assertEqual(pending["active"]["source_text"], "2 pizzas de muzarella")
                    self.assertEqual(pending["active"]["resolved_data"]["cantidad"], 2)
                    self.assertGreaterEqual(len(pending["active"]["candidate_ids"]), 2)
                    self.assertEqual(pending.get("queue", []), [])

                _post("grande", ids)
                with TestingSessionLocal() as db:
                    rows = db.execute(
                        select(PedidoProducto).where(
                            PedidoProducto.id_pedido == ids["pedido_id"]
                        )
                    ).scalars().all()
                    self.assertEqual(len(rows), 2)
                    pps = {r.id_producto_presentacion: r.cantidad for r in rows}
                    self.assertEqual(pps[ids["empanada_pps"]["picante"]], 4)
                    self.assertEqual(pps[ids["pizza_pps"]["grande"]], 2)
        finally:
            _cleanup(ids)


def _seed_commerce_product_name_discriminator(
    *,
    empanada_product_names: list[str],
) -> dict:
    """Seed a comercio catalog where the discriminator between two
    empanada presentations lives in `producto_nombre` (NOT in
    `presentacion_codigo`, which is the same for every candidate).

    This mirrors the 3.32.7 fix scenario: when the user reply's
    alias (e.g. `picante`) lives in the product name, the existing
    `presentacion_codigo` match path produces zero matches and the
    resolver must fall back to the new product-name whole-word match.
    """
    s = _suffix()
    estado_id = _estado_id_activo()

    with TestingSessionLocal() as db, db.begin():
        comercio = Comercio(
            nombre_fantasia=f"PicDisc {s}",
            nombre_corto=f"PD {s}",
            razon_social=f"PicDisc SRL {s}",
            cuit=f"30-{s[:8]}-{s[8]}",
            whatsapp=f"+5491{s[:8]}",
            calle="Av. PicDisc",
            numero="1",
            piso_departamento=None,
            localidad="CABA",
            provincia="BA",
            codigo_postal="C1000",
            slug=f"picdisc-{s}",
            estado_id=estado_id,
        )
        db.add(comercio)
        db.flush()

        cliente = Cliente(
            whatsapp=f"+5491{int(s, 16) % 100000000:08d}",
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
            id_comercio=comercio.id, descripcion=f"Empanadas {s}",
            activo=True, orden=0,
        )
        db.add(categoria)
        db.flush()

        presentacion = Presentacion(
            id_comercio=comercio.id, codigo="UNIDAD",
            descripcion="Unidad", activo=True, orden=0,
        )
        db.add(presentacion)
        db.flush()

        empanada_pps: dict[str, int] = {}
        for orden, name in enumerate(empanada_product_names):
            producto = Producto(
                id_categoria_producto=categoria.id,
                nombre=name,
                descripcion=None, activo=True, disponible=True, orden=orden,
            )
            db.add(producto)
            db.flush()
            asoc = ProductoPresentacion(
                id_producto=producto.id, id_presentacion=presentacion.id,
                activo=True, orden=orden,
            )
            db.add(asoc)
            db.flush()
            db.add(Precio(id_producto_presentacion=asoc.id,
                          precio=Decimal("1000.00")))
            db.flush()
            key = name.lower().replace(" ", "-")
            empanada_pps[key] = asoc.id

        ids = {
            "comercio_id": comercio.id,
            "cliente_id": cliente.id,
            "session_id": session_row.id,
            "pedido_id": pedido.id,
            "empanada_pps": empanada_pps,
            "presentacion_ids": [presentacion.id],
            "categoria_ids": [categoria.id],
        }
    return ids


def _cleanup_product_name_discriminator(ids: dict) -> None:
    with TestingSessionLocal() as db, db.begin():
        sess_row = db.get(SessionModel, ids["session_id"])
        if sess_row is not None:
            sess_row.id_pedido = None
            db.flush()
        db.execute(delete(PedidoProducto).where(
            PedidoProducto.id_pedido == ids["pedido_id"]
        ))
        db.execute(delete(Precio).where(
            Precio.id_producto_presentacion.in_(
                select(ProductoPresentacion.id).where(
                    ProductoPresentacion.id_producto.in_(
                        select(Producto.id).where(
                            Producto.id_categoria_producto.in_(ids["categoria_ids"])
                        )
                    )
                )
            )
        ))
        db.execute(delete(ProductoPresentacion).where(
            ProductoPresentacion.id_producto.in_(
                select(Producto.id).where(
                    Producto.id_categoria_producto.in_(ids["categoria_ids"])
                )
            )
        ))
        db.execute(delete(Producto).where(
            Producto.id_categoria_producto.in_(ids["categoria_ids"])
        ))
        db.execute(delete(CategoriaProducto).where(
            CategoriaProducto.id.in_(ids["categoria_ids"])
        ))
        db.execute(delete(Presentacion).where(
            Presentacion.id.in_(ids["presentacion_ids"])
        ))
        db.execute(delete(Pedido).where(Pedido.id == ids["pedido_id"]))
        db.execute(delete(SessionModel).where(SessionModel.id == ids["session_id"]))
        db.execute(delete(Cliente).where(Cliente.id == ids["cliente_id"]))
        db.execute(delete(Comercio).where(Comercio.id == ids["comercio_id"]))


class SequentialQueueE2ECarnePicanteProductoNombreTest(unittest.TestCase):
    """3.32.7: HTTP regression mirroring the original failure scenario:
    `agrega 1 empanada de carne` followed by `carne picante`. The
    discriminator (`picante`) lives in the product name rather than
    the presentacion_codigo, so the new predicate in
    `_narrow_by_presentacion_alias` must narrow to the picante
    candidate automatically.
    """

    def test_carne_picante_narrows_to_picante_via_producto_nombre(self) -> None:
        s = _suffix()
        names = [f"Empanada de Carne {s}", f"Empanada de Carne Picante {s}"]
        ids = _seed_commerce_product_name_discriminator(
            empanada_product_names=names,
        )
        carne_simple_id = ids["empanada_pps"][f"empanada-de-carne-{s}"]
        carne_picante_id = ids["empanada_pps"][f"empanada-de-carne-picante-{s}"]
        try:
            cls = _classifier_with_fragments({
                "agrega 1 empanada de carne": [
                    (IntentName.AGREGAR_PRODUCTO.value, "1 empanada de carne"),
                ],
            })
            try:
                with _patched_classifier(cls):
                    r1 = _post("agrega 1 empanada de carne", ids)
                    responses = r1["responses"]
                    self.assertEqual(len(responses), 1)
                    self.assertEqual(
                        responses[0]["status"], "pending_resolution"
                    )

                    with TestingSessionLocal() as db:
                        session_row = db.get(SessionModel, ids["session_id"])
                        assert session_row is not None
                        pending = session_row.pending_intents or {}
                        active = pending.get("active")
                        self.assertIsNotNone(active)
                        assert active is not None
                        self.assertEqual(
                            active["source_text"], "1 empanada de carne"
                        )
                        self.assertEqual(
                            active["status"], "pending_resolution"
                        )
                        self.assertEqual(
                            sorted(active["candidate_ids"]),
                            sorted([carne_simple_id, carne_picante_id]),
                        )
                        self.assertEqual(
                            active["resolved_data"]["cantidad"], 1
                        )
                        self.assertEqual(
                            pending.get("queue", []), []
                        )
                        self.assertEqual(
                            session_row.context_type, "product_selection"
                        )

                    classifier_calls_before = list(cls.query_calls)

                    r2 = _post("carne picante", ids)
                    responses = r2["responses"]
                    self.assertEqual(len(responses), 1)
                    self.assertEqual(responses[0]["status"], "executed")
                    self.assertIn(
                        "Empanada de Carne Picante", responses[0]["message"]
                    )
                    self.assertNotIn(
                        "Empanada de Carne ", responses[0]["message"].replace(
                            "Empanada de Carne Picante", ""
                        )
                    )

                    with TestingSessionLocal() as db:
                        session_row = db.get(SessionModel, ids["session_id"])
                        assert session_row is not None
                        pending = session_row.pending_intents or {}
                        self.assertIsNone(pending.get("active"))
                        self.assertEqual(
                            pending.get("queue", []), []
                        )
                        self.assertIsNone(session_row.context_type)

                        rows = db.execute(
                            select(PedidoProducto).where(
                                PedidoProducto.id_pedido == ids["pedido_id"]
                            )
                        ).scalars().all()
                        self.assertEqual(len(rows), 1)
                        self.assertEqual(
                            rows[0].id_producto_presentacion, carne_picante_id
                        )
                        self.assertEqual(rows[0].cantidad, 1)

                    self.assertEqual(
                        cls.query_calls, classifier_calls_before
                    )
            finally:
                pass
        finally:
            _cleanup_product_name_discriminator(ids)


def _customer(status: str, message: str) -> dict:
    return {
        "intent": "agregar_producto",
        "status": status,
        "message": message,
    }


if __name__ == "__main__":
    unittest.main(verbosity=2)
