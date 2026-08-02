import unittest
import uuid
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from backend.intents.orchestration.incoming_message_orchestrator import (
    process_incoming_message,
)
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


def _seed() -> dict:
    s = _suffix()
    estado_id = _estado_id_activo()

    with TestingSessionLocal() as db, db.begin():
        comercio = Comercio(
            nombre_fantasia=f"Test {s}",
            nombre_corto=f"TC {s}",
            razon_social=f"Test Comercio SRL {s}",
            cuit=f"30-{s[:8]}-{s[8]}",
            whatsapp=f"+5491{s[:8]}",
            calle="Av. Test",
            numero="1234",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"test-comercio-{s}",
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
            id_comercio=comercio.id,
            descripcion=f"Categoria {s}",
            activo=True,
            orden=0,
        )
        db.add(categoria)
        db.flush()

        producto = Producto(
            id_categoria_producto=categoria.id,
            nombre=f"Pizza Mozzarella {s}",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        db.add(producto)
        db.flush()

        presentaciones: dict[str, Presentacion] = {}
        asociaciones: dict[str, ProductoPresentacion] = {}
        for codigo, orden in (("chica", 0), ("grande", 1)):
            presentacion = Presentacion(
                id_comercio=comercio.id,
                codigo=codigo,
                descripcion=f"Presentacion {codigo} {s}",
                activo=True,
                orden=orden,
            )
            db.add(presentacion)
            db.flush()
            presentaciones[codigo] = presentacion

            assoc = ProductoPresentacion(
                id_producto=producto.id,
                id_presentacion=presentacion.id,
                activo=True,
                orden=orden,
            )
            db.add(assoc)
            db.flush()
            asociaciones[codigo] = assoc

            precio = Precio(
                id_producto_presentacion=assoc.id,
                precio=Decimal("12345.67"),
            )
            db.add(precio)
            db.flush()

        ids = {
            "comercio_id": comercio.id,
            "cliente_id": cliente.id,
            "session_id": session_row.id,
            "pedido_id": pedido.id,
            "producto_id": producto.id,
            "chica_pp_id": asociaciones["chica"].id,
            "grande_pp_id": asociaciones["grande"].id,
        }

    return ids


def _cleanup(
    *,
    comercio_id: int,
    cliente_id: int,
    pedido_id: int,
    session_id: int,
    producto_id: int,
) -> None:
    with TestingSessionLocal() as db, db.begin():
        sess_row = db.get(SessionModel, session_id)
        if sess_row is not None:
            sess_row.id_pedido = None
            db.flush()
        db.execute(delete(PedidoProducto).where(PedidoProducto.id_pedido == pedido_id))
        db.execute(
            delete(Precio).where(
                Precio.id_producto_presentacion.in_(
                    select(ProductoPresentacion.id).where(
                        ProductoPresentacion.id_producto == producto_id
                    )
                )
            )
        )
        db.execute(
            delete(ProductoPresentacion).where(
                ProductoPresentacion.id_producto == producto_id
            )
        )
        db.execute(delete(Producto).where(Producto.id == producto_id))
        db.execute(delete(CategoriaProducto).where(CategoriaProducto.id_comercio == comercio_id))
        db.execute(delete(Pedido).where(Pedido.id == pedido_id))
        db.execute(delete(SessionModel).where(SessionModel.id == session_id))
        db.execute(delete(Cliente).where(Cliente.id == cliente_id))
        db.execute(delete(Comercio).where(Comercio.id == comercio_id))


class _PatchedClassifier:
    """IntentClassifier subclass with MagicMock-tracking constructor and query."""

    constructor_calls: list = []
    query_calls: list = []

    def __init__(self, *args, **kwargs) -> None:
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
    """Yield a patched IntentClassifier that returns one agregar_producto intent.

    Patches `backend.intents.orchestration.initial_intent_dispatcher.IntentClassifier`
    and MUST be exited in a `finally:` block.
    """
    from backend.intents.orchestration import initial_intent_dispatcher as _dispatcher

    _PatchedClassifier.constructor_calls = []
    _PatchedClassifier.query_calls = []

    patcher = patch.object(_dispatcher, "IntentClassifier", _PatchedClassifier)
    patcher.start()
    try:
        yield _PatchedClassifier
    finally:
        patcher.stop()


class IncomingMessageInitialBranchIntegrationTest(unittest.TestCase):
    def test_initial_message_branch_creates_pending_context(self) -> None:
        ids = _seed()
        try:
            with _patched_classifier("quiero 2 pizzas de mozzarella") as patched:
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None

                    result = process_incoming_message(
                        db,
                        session_row,
                        "quiero 2 pizzas de mozzarella",
                    )

                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "pending_resolution")
                    self.assertEqual(result[0].intent, "agregar_producto")
                    self.assertEqual(len(patched.constructor_calls), 1)
                    self.assertEqual(patched.query_calls, ["quiero 2 pizzas de mozzarella"])

                    db.commit()

            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                self.assertEqual(session_row.context_type, "product_selection")

                pending = session_row.pending_intents or {}
                self.assertIn("active", pending)
                active = pending["active"]
                self.assertEqual(active["intent"], "agregar_producto")
                self.assertEqual(active["status"], "pending_resolution")

                lines = db.execute(
                    select(PedidoProducto).where(PedidoProducto.id_pedido == ids["pedido_id"])
                ).scalars().all()
                self.assertEqual(lines, [])
        finally:
            _cleanup(
                comercio_id=ids["comercio_id"],
                cliente_id=ids["cliente_id"],
                pedido_id=ids["pedido_id"],
                session_id=ids["session_id"],
                producto_id=ids["producto_id"],
            )


class IncomingMessagePendingBranchIntegrationTest(unittest.TestCase):
    def test_pending_context_branch_executes_order_line(self) -> None:
        ids = _seed()
        try:
            with _patched_classifier("quiero 2 pizzas de mozzarella") as patched:
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None

                    process_incoming_message(
                        db,
                        session_row,
                        "quiero 2 pizzas de mozzarella",
                    )

                    db.commit()

            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                self.assertEqual(session_row.context_type, "product_selection")
                self.assertEqual(len(patched.constructor_calls), 1)

            with _patched_classifier("pizza grande") as patched:
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None

                    result = process_incoming_message(
                        db,
                        session_row,
                        "pizza grande",
                    )

                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "executed")
                    self.assertEqual(result[0].intent, "agregar_producto")
                    self.assertEqual(patched.constructor_calls, [])

                    db.commit()

            with TestingSessionLocal() as db:
                lines = db.execute(
                    select(PedidoProducto).where(PedidoProducto.id_pedido == ids["pedido_id"])
                ).scalars().all()
                self.assertEqual(len(lines), 1)
                self.assertEqual(lines[0].id_producto_presentacion, ids["grande_pp_id"])
                self.assertEqual(lines[0].cantidad, 2)

                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                pending = session_row.pending_intents or {}
                active = pending.get("active")
                self.assertIsNone(active)
                self.assertIsNone(session_row.context_type)
        finally:
            _cleanup(
                comercio_id=ids["comercio_id"],
                cliente_id=ids["cliente_id"],
                pedido_id=ids["pedido_id"],
                session_id=ids["session_id"],
                producto_id=ids["producto_id"],
            )


class IncomingMessageExactMatchFirstMessageIntegrationTest(unittest.TestCase):
    def test_exact_unique_match_on_first_message_executes_in_same_turn(self) -> None:
        ids = _seed()
        try:
            with _patched_classifier("pizza mozzarella grande") as patched:
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None

                    result = process_incoming_message(
                        db,
                        session_row,
                        "pizza mozzarella grande",
                    )

                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "executed")
                    self.assertEqual(result[0].intent, "agregar_producto")
                    self.assertEqual(
                        result[0].resolved_data.get("producto_presentacion_id"),
                        ids["grande_pp_id"],
                    )
                    self.assertEqual(result[0].resolved_data.get("cantidad"), 1)

                    db.commit()

            with TestingSessionLocal() as db:
                lines = db.execute(
                    select(PedidoProducto).where(PedidoProducto.id_pedido == ids["pedido_id"])
                ).scalars().all()
                self.assertEqual(len(lines), 1)
                self.assertEqual(lines[0].id_producto_presentacion, ids["grande_pp_id"])
                self.assertEqual(lines[0].cantidad, 1)

                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                pending = session_row.pending_intents or {}
                self.assertIsNone(pending.get("active"))
                self.assertIsNone(session_row.context_type)
        finally:
            _cleanup(
                comercio_id=ids["comercio_id"],
                cliente_id=ids["cliente_id"],
                pedido_id=ids["pedido_id"],
                session_id=ids["session_id"],
                producto_id=ids["producto_id"],
            )


if __name__ == "__main__":
    unittest.main()
