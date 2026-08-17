"""Focused regression coverage for subphase 3.30.3 consolidation.

Covers the consolidation contract of ``PedidoProductoService.add_or_increment``
and the related repository, handler, response-builder, HTTP end-to-end, CLI
regression rerun, and ``quitar_producto`` regression rerun scenarios.
"""
import importlib
import io
import sys
import unittest
import uuid
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

import backend.dependencies as dependencies_module
from backend.dependencies import get_session
from backend.intents.handlers.agregar_producto_handler import execute_agregar_producto
from backend.intents.orchestration.incoming_message_orchestrator import (
    process_incoming_message,
)
from backend.intents.orchestration.incoming_message_response_orchestrator import (
    process_incoming_message_with_responses,
)
from backend.intents.responses.agregar_producto_response import (
    build_agregar_producto_response,
)
from backend.intents.schemas.intent_classification import (
    ClassifiedIntent,
    IntentClassificationResult,
    IntentName,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
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
from backend.repositories.pedido_producto_repository import PedidoProductoRepository
from backend.services.exceptions import (
    InvalidCantidad,
    PedidoNotFound,
    PedidoProductoNotEditable,
    PrecioNotFound,
    ProductoPresentacionNotFound,
)
from backend.services.pedido_producto_service import PedidoProductoService


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
test_client = TestClient = None
try:
    from fastapi.testclient import TestClient

    test_client = TestClient(app)
except Exception:  # pragma: no cover
    test_client = None
BASE_URL = "http://127.0.0.1:8000"


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


def _seed_empanada_y_pizza_catalog() -> dict:
    s = _suffix()
    estado_id = _estado_id_activo()
    with TestingSessionLocal() as db, db.begin():
        comercio = Comercio(
            nombre_fantasia=f"Empanadas y Pizzas {s}",
            nombre_corto=f"EP {s}",
            razon_social=f"Empanadas y Pizzas SRL {s}",
            cuit=f"30-{s[:8]}-{s[8]}",
            whatsapp=f"+5491{s[:8]}",
            calle="Av. Test",
            numero="1234",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"empanadas-pizzas-{s}",
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
            descripcion=f"Comidas {s}",
            activo=True,
            orden=0,
        )
        db.add(categoria)
        db.flush()

        empanada_producto = Producto(
            id_categoria_producto=categoria.id,
            nombre=f"Empanada de Verdura {s}",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        db.add(empanada_producto)
        db.flush()

        pizza_muzza_producto = Producto(
            id_categoria_producto=categoria.id,
            nombre=f"Pizza Mozzarella {s}",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=1,
        )
        db.add(pizza_muzza_producto)
        db.flush()

        pizza_napo_producto = Producto(
            id_categoria_producto=categoria.id,
            nombre=f"Pizza Napolitana {s}",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=2,
        )
        db.add(pizza_napo_producto)
        db.flush()

        presentaciones: dict[str, Presentacion] = {}
        for codigo, orden in (("Unidad", 0), ("Chica", 1), ("Grande", 2)):
            presentacion = Presentacion(
                id_comercio=comercio.id,
                codigo=f"{codigo} {s}",
                descripcion=f"{codigo} {s}",
                activo=True,
                orden=orden,
            )
            db.add(presentacion)
            db.flush()
            presentaciones[codigo] = presentacion

        asociaciones: dict[str, ProductoPresentacion] = {}

        assoc = ProductoPresentacion(
            id_producto=empanada_producto.id,
            id_presentacion=presentaciones["Unidad"].id,
            activo=True,
            orden=0,
        )
        db.add(assoc)
        db.flush()
        asociaciones["EmpanadaVerduraUnidad"] = assoc
        db.add(
            Precio(
                id_producto_presentacion=assoc.id,
                precio=Decimal("1500.00"),
            )
        )
        db.flush()

        for codigo, producto_id in (
            ("Chica", pizza_muzza_producto.id),
            ("Grande", pizza_muzza_producto.id),
        ):
            assoc = ProductoPresentacion(
                id_producto=producto_id,
                id_presentacion=presentaciones[codigo].id,
                activo=True,
                orden=0 if codigo == "Chica" else 1,
            )
            db.add(assoc)
            db.flush()
            asociaciones[f"PizzaMuzzarella{codigo}"] = assoc
            db.add(
                Precio(
                    id_producto_presentacion=assoc.id,
                    precio=Decimal("8500.00"),
                )
            )
            db.flush()

        assoc = ProductoPresentacion(
            id_producto=pizza_napo_producto.id,
            id_presentacion=presentaciones["Chica"].id,
            activo=True,
            orden=0,
        )
        db.add(assoc)
        db.flush()
        asociaciones["PizzaNapolitanaChica"] = assoc
        db.add(
            Precio(
                id_producto_presentacion=assoc.id,
                precio=Decimal("9000.00"),
            )
        )
        db.flush()

        return {
            "comercio_id": comercio.id,
            "cliente_id": cliente.id,
            "session_id": session_row.id,
            "pedido_id": pedido.id,
            "producto_ids": [
                empanada_producto.id,
                pizza_muzza_producto.id,
                pizza_napo_producto.id,
            ],
            "presentacion_ids": [p.id for p in presentaciones.values()],
            "pp_ids": {key: assoc.id for key, assoc in asociaciones.items()},
            "suffix": s,
        }


def _cleanup(ids: dict) -> None:
    producto_ids = ids["producto_ids"]
    with TestingSessionLocal() as db, db.begin():
        sess_row = db.get(SessionModel, ids["session_id"])
        if sess_row is not None:
            sess_row.id_pedido = None
            db.flush()
        db.execute(delete(PedidoProducto).where(PedidoProducto.id_pedido == ids["pedido_id"]))
        db.execute(
            delete(Precio).where(
                Precio.id_producto_presentacion.in_(
                    select(ProductoPresentacion.id).where(
                        ProductoPresentacion.id_producto.in_(producto_ids)
                    )
                )
            )
        )
        db.execute(
            delete(ProductoPresentacion).where(
                ProductoPresentacion.id_producto.in_(producto_ids)
            )
        )
        db.execute(delete(Producto).where(Producto.id.in_(producto_ids)))
        db.execute(
            delete(CategoriaProducto).where(CategoriaProducto.id_comercio == ids["comercio_id"])
        )
        db.execute(delete(Pedido).where(Pedido.id == ids["pedido_id"]))
        db.execute(delete(SessionModel).where(SessionModel.id == ids["session_id"]))
        db.execute(delete(Cliente).where(Cliente.id == ids["cliente_id"]))
        db.execute(delete(Comercio).where(Comercio.id == ids["comercio_id"]))


class _PatchedClassifier:
    constructor_calls: list = []
    query_calls: list = []

    def __init__(self, *args, **kwargs) -> None:
        type(self).constructor_calls.append((args, kwargs))

    def query(self, message: str) -> IntentClassificationResult:
        type(self).query_calls.append(message)
        return IntentClassificationResult(
            intents=[ClassifiedIntent(intent=IntentName.AGREGAR_PRODUCTO, mensaje=message)],
            mensaje=message,
        )


class _QuitarProductoClassifier:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def query(self, message: str) -> IntentClassificationResult:
        return IntentClassificationResult(
            intents=[ClassifiedIntent(intent=IntentName.QUITAR_PRODUCTO, mensaje=message)],
            mensaje=message,
        )


@contextmanager
def _patched_classifier_agregar():
    from backend.intents.orchestration import initial_intent_dispatcher as _dispatcher

    _PatchedClassifier.constructor_calls = []
    _PatchedClassifier.query_calls = []
    patcher = patch.object(_dispatcher, "IntentClassifier", _PatchedClassifier)
    patcher.start()
    try:
        yield _PatchedClassifier
    finally:
        patcher.stop()


@contextmanager
def _patched_classifier_quitar():
    from backend.intents.orchestration import initial_intent_dispatcher as _dispatcher

    patcher = patch.object(_dispatcher, "IntentClassifier", _QuitarProductoClassifier)
    patcher.start()
    try:
        yield
    finally:
        patcher.stop()


def _ready_intent(*, pp_id: int, cantidad: int) -> ProcessedIntent:
    return ProcessedIntent(
        intent="agregar_producto",
        source_text="quiero empanadas de verdura",
        status="ready",
        recognizer="recognizer_productos",
        handler="agregar_producto",
        resolved_data={"producto_presentacion_id": pp_id, "cantidad": cantidad},
        requirements=[
            RequirementState(name="producto_presentacion_id", status="completed", value=pp_id),
            RequirementState(name="cantidad", status="completed", value=cantidad),
        ],
        candidate_ids=[],
    )


class ServiceAddOrIncrementTests(unittest.TestCase):
    def test_first_addition_creates_one_row(self) -> None:
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_empanada_y_pizza_catalog()
        try:
            with TestingSessionLocal() as db:
                row = PedidoProductoService(db).add_or_increment(
                    ids["pedido_id"],
                    ids["pp_ids"]["EmpanadaVerduraUnidad"],
                    2,
                    "  con limón  ",
                )
            self.assertEqual(row.cantidad, 2)
            self.assertEqual(row.precio_unitario, Decimal("1500.00"))
            self.assertEqual(row.observaciones, "con limón")

            with TestingSessionLocal() as db:
                lines = db.execute(
                    select(PedidoProducto).where(PedidoProducto.id_pedido == ids["pedido_id"])
                ).scalars().all()
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0].cantidad, 2)
            self.assertEqual(lines[0].precio_unitario, Decimal("1500.00"))
            self.assertEqual(lines[0].observaciones, "con limón")
        finally:
            _cleanup(ids)

    def test_second_addition_increments(self) -> None:
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_empanada_y_pizza_catalog()
        try:
            with TestingSessionLocal() as db:
                first = PedidoProductoService(db).add_or_increment(
                    ids["pedido_id"],
                    ids["pp_ids"]["EmpanadaVerduraUnidad"],
                    2,
                    "con limón",
                )
                first_id = first.id
                second = PedidoProductoService(db).add_or_increment(
                    ids["pedido_id"],
                    ids["pp_ids"]["EmpanadaVerduraUnidad"],
                    1,
                    "sin picante",
                )
            self.assertEqual(second.id, first_id)
            self.assertEqual(second.cantidad, 3)
            self.assertEqual(second.precio_unitario, Decimal("1500.00"))
            self.assertEqual(second.observaciones, "con limón")
        finally:
            _cleanup(ids)

    def test_multiple_identical_additions_keep_one_row(self) -> None:
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_empanada_y_pizza_catalog()
        try:
            with TestingSessionLocal() as db:
                for q in (2, 1, 4):
                    PedidoProductoService(db).add_or_increment(
                        ids["pedido_id"],
                        ids["pp_ids"]["EmpanadaVerduraUnidad"],
                        q,
                        None,
                    )
            with TestingSessionLocal() as db:
                lines = db.execute(
                    select(PedidoProducto).where(PedidoProducto.id_pedido == ids["pedido_id"])
                ).scalars().all()
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0].cantidad, 7)
        finally:
            _cleanup(ids)

    def test_different_presentations_stay_separate(self) -> None:
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_empanada_y_pizza_catalog()
        try:
            with TestingSessionLocal() as db:
                PedidoProductoService(db).add_or_increment(
                    ids["pedido_id"],
                    ids["pp_ids"]["EmpanadaVerduraUnidad"],
                    1,
                    None,
                )
                PedidoProductoService(db).add_or_increment(
                    ids["pedido_id"],
                    ids["pp_ids"]["PizzaMuzzarellaChica"],
                    2,
                    None,
                )
            with TestingSessionLocal() as db:
                lines = db.execute(
                    select(PedidoProducto).where(PedidoProducto.id_pedido == ids["pedido_id"])
                ).scalars().all()
            self.assertEqual(len(lines), 2)
            self.assertEqual(
                {line.id_producto_presentacion for line in lines},
                {
                    ids["pp_ids"]["EmpanadaVerduraUnidad"],
                    ids["pp_ids"]["PizzaMuzzarellaChica"],
                },
            )
        finally:
            _cleanup(ids)

    def test_same_presentation_different_pedidos_stay_separate(self) -> None:
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_empanada_y_pizza_catalog()
            second_pedido = Pedido(
                id_session=ids["session_id"],
                id_medio_pago=None,
                id_metodo_entrega=None,
                datetime_entrega_programada=None,
                estado_pedido=EstadoPedido.BORRADOR,
            )
            db.add(second_pedido)
            db.flush()
            second_pedido_id = second_pedido.id
        try:
            with TestingSessionLocal() as db:
                PedidoProductoService(db).add_or_increment(
                    ids["pedido_id"],
                    ids["pp_ids"]["EmpanadaVerduraUnidad"],
                    1,
                    None,
                )
                PedidoProductoService(db).add_or_increment(
                    second_pedido_id,
                    ids["pp_ids"]["EmpanadaVerduraUnidad"],
                    3,
                    None,
                )
            with TestingSessionLocal() as db:
                a_lines = db.execute(
                    select(PedidoProducto).where(PedidoProducto.id_pedido == ids["pedido_id"])
                ).scalars().all()
                b_lines = db.execute(
                    select(PedidoProducto).where(PedidoProducto.id_pedido == second_pedido_id)
                ).scalars().all()
            self.assertEqual(len(a_lines), 1)
            self.assertEqual(len(b_lines), 1)
            self.assertEqual(a_lines[0].cantidad, 1)
            self.assertEqual(b_lines[0].cantidad, 3)
        finally:
            with TestingSessionLocal() as db, db.begin():
                db.execute(delete(Pedido).where(Pedido.id == second_pedido_id))
            _cleanup(ids)

    def test_price_snapshot_preserved_on_increment(self) -> None:
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_empanada_y_pizza_catalog()
            emp_pp = ids["pp_ids"]["EmpanadaVerduraUnidad"]
            db.execute(
                delete(Precio).where(Precio.id_producto_presentacion == emp_pp)
            )
            db.add(Precio(id_producto_presentacion=emp_pp, precio=Decimal("1000.00")))
        try:
            with TestingSessionLocal() as db:
                PedidoProductoService(db).add_or_increment(
                    ids["pedido_id"], emp_pp, 2, None
                )
            with TestingSessionLocal() as db, db.begin():
                db.execute(
                    Precio.__table__.update()
                    .where(Precio.id_producto_presentacion == emp_pp)
                    .values(precio=Decimal("1200.00"))
                )
            with TestingSessionLocal() as db:
                PedidoProductoService(db).add_or_increment(
                    ids["pedido_id"], emp_pp, 1, None
                )
            with TestingSessionLocal() as db:
                lines = db.execute(
                    select(PedidoProducto).where(PedidoProducto.id_pedido == ids["pedido_id"])
                ).scalars().all()
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0].cantidad, 3)
            self.assertEqual(lines[0].precio_unitario, Decimal("1000.00"))
        finally:
            _cleanup(ids)

    def test_new_line_snapshots_current_price(self) -> None:
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_empanada_y_pizza_catalog()
            emp_pp = ids["pp_ids"]["EmpanadaVerduraUnidad"]
            pizza_pp = ids["pp_ids"]["PizzaMuzzarellaChica"]
            db.execute(delete(Precio).where(Precio.id_producto_presentacion == emp_pp))
            db.execute(delete(Precio).where(Precio.id_producto_presentacion == pizza_pp))
            db.add(Precio(id_producto_presentacion=emp_pp, precio=Decimal("1000.00")))
            db.add(Precio(id_producto_presentacion=pizza_pp, precio=Decimal("1000.00")))
        try:
            with TestingSessionLocal() as db:
                first = PedidoProductoService(db).add_or_increment(
                    ids["pedido_id"], emp_pp, 1, None
                )
            self.assertEqual(first.precio_unitario, Decimal("1000.00"))
            with TestingSessionLocal() as db, db.begin():
                db.execute(
                    Precio.__table__.update()
                    .where(Precio.id_producto_presentacion == pizza_pp)
                    .values(precio=Decimal("1200.00"))
                )
            with TestingSessionLocal() as db:
                second = PedidoProductoService(db).add_or_increment(
                    ids["pedido_id"], pizza_pp, 1, None
                )
            self.assertEqual(second.precio_unitario, Decimal("1200.00"))
        finally:
            _cleanup(ids)

    def test_rejects_invalid_cantidad(self) -> None:
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_empanada_y_pizza_catalog()
        try:
            for bad in (0, -1):
                with self.assertRaises(InvalidCantidad):
                    with TestingSessionLocal() as db:
                        PedidoProductoService(db).add_or_increment(
                            ids["pedido_id"],
                            ids["pp_ids"]["EmpanadaVerduraUnidad"],
                            bad,
                            None,
                        )
            with TestingSessionLocal() as db:
                lines = db.execute(
                    select(PedidoProducto).where(PedidoProducto.id_pedido == ids["pedido_id"])
                ).scalars().all()
            self.assertEqual(lines, [])
        finally:
            _cleanup(ids)

    def test_rejects_non_borrador_pedido(self) -> None:
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_empanada_y_pizza_catalog()
            pedido_row = db.get(Pedido, ids["pedido_id"])
            assert pedido_row is not None
            pedido_row.estado_pedido = EstadoPedido.INGRESADO
        try:
            with self.assertRaises(PedidoProductoNotEditable):
                with TestingSessionLocal() as db:
                    PedidoProductoService(db).add_or_increment(
                        ids["pedido_id"],
                        ids["pp_ids"]["EmpanadaVerduraUnidad"],
                        1,
                        None,
                    )
        finally:
            _cleanup(ids)

    def test_rejects_missing_pedido(self) -> None:
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_empanada_y_pizza_catalog()
        try:
            with self.assertRaises(PedidoNotFound):
                with TestingSessionLocal() as db:
                    PedidoProductoService(db).add_or_increment(
                        99999999,
                        ids["pp_ids"]["EmpanadaVerduraUnidad"],
                        1,
                        None,
                    )
        finally:
            _cleanup(ids)

    def test_rejects_missing_producto_presentacion(self) -> None:
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_empanada_y_pizza_catalog()
        try:
            with self.assertRaises(ProductoPresentacionNotFound):
                with TestingSessionLocal() as db:
                    PedidoProductoService(db).add_or_increment(
                        ids["pedido_id"], 99999999, 1, None
                    )
        finally:
            _cleanup(ids)

    def test_rejects_missing_precio(self) -> None:
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_empanada_y_pizza_catalog()
            db.execute(
                delete(Precio).where(
                    Precio.id_producto_presentacion == ids["pp_ids"]["PizzaNapolitanaChica"]
                )
            )
        try:
            with self.assertRaises(PrecioNotFound):
                with TestingSessionLocal() as db:
                    PedidoProductoService(db).add_or_increment(
                        ids["pedido_id"],
                        ids["pp_ids"]["PizzaNapolitanaChica"],
                        1,
                        None,
                    )
        finally:
            _cleanup(ids)


class RepositoryLookupTests(unittest.TestCase):
    def test_returns_matching_row(self) -> None:
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_empanada_y_pizza_catalog()
        try:
            with TestingSessionLocal() as db:
                row = PedidoProductoService(db).add_or_increment(
                    ids["pedido_id"],
                    ids["pp_ids"]["EmpanadaVerduraUnidad"],
                    1,
                    None,
                )
            with TestingSessionLocal() as db:
                found = PedidoProductoRepository(db).get_by_pedido_and_producto_presentacion(
                    ids["pedido_id"], ids["pp_ids"]["EmpanadaVerduraUnidad"]
                )
            assert found is not None
            self.assertEqual(found.id, row.id)
        finally:
            _cleanup(ids)

    def test_returns_none_when_no_match(self) -> None:
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_empanada_y_pizza_catalog()
        try:
            with TestingSessionLocal() as db:
                found = PedidoProductoRepository(db).get_by_pedido_and_producto_presentacion(
                    ids["pedido_id"], ids["pp_ids"]["EmpanadaVerduraUnidad"]
                )
            self.assertIsNone(found)
        finally:
            _cleanup(ids)

    def test_does_not_return_row_from_different_pedido(self) -> None:
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_empanada_y_pizza_catalog()
            other_pedido = Pedido(
                id_session=ids["session_id"],
                id_medio_pago=None,
                id_metodo_entrega=None,
                datetime_entrega_programada=None,
                estado_pedido=EstadoPedido.BORRADOR,
            )
            db.add(other_pedido)
            db.flush()
            other_id = other_pedido.id
        try:
            with TestingSessionLocal() as db:
                PedidoProductoService(db).add_or_increment(
                    other_id,
                    ids["pp_ids"]["EmpanadaVerduraUnidad"],
                    1,
                    None,
                )
            with TestingSessionLocal() as db:
                found = PedidoProductoRepository(db).get_by_pedido_and_producto_presentacion(
                    ids["pedido_id"], ids["pp_ids"]["EmpanadaVerduraUnidad"]
                )
            self.assertIsNone(found)
        finally:
            with TestingSessionLocal() as db, db.begin():
                db.execute(delete(Pedido).where(Pedido.id == other_id))
            _cleanup(ids)


class HandlerTests(unittest.TestCase):
    def _make_session(self, id_pedido):
        return MagicMock(id_pedido=id_pedido, pending_intents={}, context_type=None)

    def test_creates_and_threads_resolved_data(self) -> None:
        intent = _ready_intent(
            pp_id=42,
            cantidad=2,
        )
        db = MagicMock()
        session = self._make_session(7)
        fake_row = MagicMock(cantidad=2)
        with patch(
            "backend.intents.handlers.agregar_producto_handler.PedidoProductoRepository"
        ) as mock_repo_cls, patch(
            "backend.intents.handlers.agregar_producto_handler.PedidoProductoService"
        ) as mock_service_cls:
            mock_repo_cls.return_value.get_by_pedido_and_producto_presentacion.return_value = None
            mock_service_cls.return_value.add_or_increment.return_value = fake_row
            executed = execute_agregar_producto(db, session, intent)
        self.assertEqual(executed.status, "executed")
        self.assertEqual(executed.resolved_data["cantidad_agregada"], 2)
        self.assertEqual(executed.resolved_data["cantidad_final"], 2)
        self.assertEqual(executed.resolved_data["linea_creada"], True)
        self.assertEqual(executed.resolved_data["producto_presentacion_id"], 42)

    def test_increments_and_threads_resolved_data(self) -> None:
        intent = _ready_intent(pp_id=42, cantidad=2)
        db = MagicMock()
        session = self._make_session(7)
        existing_row = MagicMock(id=99, cantidad=3)
        new_row = MagicMock(cantidad=5)
        with patch(
            "backend.intents.handlers.agregar_producto_handler.PedidoProductoRepository"
        ) as mock_repo_cls, patch(
            "backend.intents.handlers.agregar_producto_handler.PedidoProductoService"
        ) as mock_service_cls:
            mock_repo_cls.return_value.get_by_pedido_and_producto_presentacion.return_value = (
                existing_row
            )
            mock_service_cls.return_value.add_or_increment.return_value = new_row
            executed = execute_agregar_producto(db, session, intent)
        self.assertEqual(executed.status, "executed")
        self.assertEqual(executed.resolved_data["cantidad_agregada"], 2)
        self.assertEqual(executed.resolved_data["cantidad_final"], 5)
        self.assertEqual(executed.resolved_data["linea_creada"], False)

    def test_does_not_query_pedido_producto_directly(self) -> None:
        import pathlib
        import backend.intents.handlers.agregar_producto_handler as module

        source = pathlib.Path(module.__file__).read_text()
        forbidden = [
            "from backend.repositories.pedido_producto_repository",
            "select(PedidoProducto)",
            "session.get(PedidoProducto",
            "session.commit(",
            "session.rollback(",
            "session.flush(",
            "session.refresh(",
            "session.expire(",
            "session.begin(",
            "HTTPException",
        ]
        # Note: importing PedidoProductoRepository from the handler IS permitted
        # per task 5.1, so we replace that one forbidden pattern with an
        # explicit allowance comment for that line only.
        for needle in forbidden:
            if needle == "from backend.repositories.pedido_producto_repository":
                # The handler DOES import the repository (per task 5.1) so
                # this string appears once. Verify it's only the import.
                count = source.count(needle)
                self.assertEqual(
                    count,
                    1,
                    f"Expected exactly one import of {needle}, found {count}",
                )
                continue
            self.assertNotIn(needle, source, f"forbidden handler construct: {needle}")

    def test_rejects_invalid_quantity_without_service_call(self) -> None:
        intent = _ready_intent(pp_id=42, cantidad=0)
        db = MagicMock()
        session = self._make_session(7)
        with patch(
            "backend.intents.handlers.agregar_producto_handler.PedidoProductoService"
        ) as mock_service_cls:
            rejected = execute_agregar_producto(db, session, intent)
        self.assertEqual(rejected.status, "rejected")
        self.assertFalse(mock_service_cls.called)

    def test_rejects_missing_pedido_without_service_call(self) -> None:
        intent = _ready_intent(pp_id=42, cantidad=1)
        db = MagicMock()
        session = self._make_session(None)
        with patch(
            "backend.intents.handlers.agregar_producto_handler.PedidoProductoService"
        ) as mock_service_cls:
            rejected = execute_agregar_producto(db, session, intent)
        self.assertEqual(rejected.status, "rejected")
        self.assertFalse(mock_service_cls.called)

    def test_rejects_non_borrador_pedido(self) -> None:
        intent = _ready_intent(pp_id=42, cantidad=1)
        db = MagicMock()
        session = self._make_session(7)
        with patch(
            "backend.intents.handlers.agregar_producto_handler.PedidoProductoRepository"
        ) as mock_repo_cls, patch(
            "backend.intents.handlers.agregar_producto_handler.PedidoProductoService"
        ) as mock_service_cls:
            mock_repo_cls.return_value.get_by_pedido_and_producto_presentacion.return_value = None
            mock_service_cls.return_value.add_or_increment.side_effect = (
                PedidoProductoNotEditable(7, "ingresado")
            )
            rejected = execute_agregar_producto(db, session, intent)
        self.assertEqual(rejected.status, "rejected")


class ResponseBuilderTests(unittest.TestCase):
    def _executed_intent(self, resolved_data: dict) -> ProcessedIntent:
        return ProcessedIntent(
            intent="agregar_producto",
            source_text="quiero empanadas de verdura",
            status="executed",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data=resolved_data,
            requirements=[],
            candidate_ids=[],
        )

    def test_new_line_cantidad_final_1_singular(self) -> None:
        intent = self._executed_intent(
            {
                "producto_presentacion_id": 42,
                "cantidad": 1,
                "cantidad_agregada": 1,
                "cantidad_final": 1,
                "linea_creada": True,
            }
        )
        with patch(
            "backend.intents.responses.agregar_producto_response.ProductoQueryService"
        ) as mock_q:
            mock_q.return_value.list_presentaciones_by_ids.return_value = [
                {"producto_nombre": "Empanada de Verdura", "presentacion_descripcion": "unidad"}
            ]
            response = build_agregar_producto_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.status, "executed")
        self.assertIn("Empanada de Verdura unidad", response.message)
        self.assertIn("1", response.message)
        self.assertIn("agregué", response.message)
        self.assertNotIn("tenés", response.message)

    def test_new_line_cantidad_final_plural_equal(self) -> None:
        intent = self._executed_intent(
            {
                "producto_presentacion_id": 42,
                "cantidad": 2,
                "cantidad_agregada": 2,
                "cantidad_final": 2,
                "linea_creada": True,
            }
        )
        with patch(
            "backend.intents.responses.agregar_producto_response.ProductoQueryService"
        ) as mock_q:
            mock_q.return_value.list_presentaciones_by_ids.return_value = [
                {"producto_nombre": "Pizza Mozzarella", "presentacion_descripcion": "grande"}
            ]
            response = build_agregar_producto_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.status, "executed")
        self.assertIn("Pizza Mozzarella grande", response.message)
        self.assertIn("2", response.message)
        self.assertIn("se agregaron", response.message)
        self.assertNotIn("agregué 2", response.message)
        self.assertNotIn("tenés", response.message)

    def test_incremented_line_delta_one_total_seven(self) -> None:
        intent = self._executed_intent(
            {
                "producto_presentacion_id": 42,
                "cantidad": 1,
                "cantidad_agregada": 1,
                "cantidad_final": 7,
                "linea_creada": False,
            }
        )
        with patch(
            "backend.intents.responses.agregar_producto_response.ProductoQueryService"
        ) as mock_q:
            mock_q.return_value.list_presentaciones_by_ids.return_value = [
                {"producto_nombre": "Verdura", "presentacion_descripcion": "unidad"}
            ]
            response = build_agregar_producto_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.status, "executed")
        self.assertIn("Verdura unidad", response.message)
        self.assertIn("agregué 1", response.message)
        self.assertIn("tenés 7", response.message)
        self.assertNotIn("se agregaron 7", response.message)
        self.assertNotIn("increment", response.message)
        self.assertNotIn("sumamos", response.message)
        self.assertNotIn("anterior", response.message)

    def test_incremented_line_delta_plural_total_distinct(self) -> None:
        intent = self._executed_intent(
            {
                "producto_presentacion_id": 42,
                "cantidad": 2,
                "cantidad_agregada": 2,
                "cantidad_final": 7,
                "linea_creada": False,
            }
        )
        with patch(
            "backend.intents.responses.agregar_producto_response.ProductoQueryService"
        ) as mock_q:
            mock_q.return_value.list_presentaciones_by_ids.return_value = [
                {"producto_nombre": "Pizza Mozzarella", "presentacion_descripcion": "chica"}
            ]
            response = build_agregar_producto_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.status, "executed")
        self.assertIn("Pizza Mozzarella chica", response.message)
        self.assertIn("se agregaron 2", response.message)
        self.assertIn("tenés 7", response.message)
        self.assertNotIn("se agregaron 7", response.message)

    def test_legacy_resolved_data_falls_back_to_cantidad(self) -> None:
        intent = self._executed_intent(
            {"producto_presentacion_id": 42, "cantidad": 2}
        )
        with patch(
            "backend.intents.responses.agregar_producto_response.ProductoQueryService"
        ) as mock_q:
            mock_q.return_value.list_presentaciones_by_ids.return_value = [
                {"producto_nombre": "Pizza Mozzarella", "presentacion_descripcion": "grande"}
            ]
            response = build_agregar_producto_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.status, "executed")
        self.assertIn("2", response.message)
        self.assertIn("se agregaron", response.message)
        self.assertNotIn("tenés", response.message)

    def test_legacy_resolved_data_only_cantidad_final(self) -> None:
        intent = self._executed_intent(
            {"producto_presentacion_id": 42, "cantidad_final": 3}
        )
        with patch(
            "backend.intents.responses.agregar_producto_response.ProductoQueryService"
        ) as mock_q:
            mock_q.return_value.list_presentaciones_by_ids.return_value = [
                {"producto_nombre": "Pizza Mozzarella", "presentacion_descripcion": "grande"}
            ]
            response = build_agregar_producto_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.status, "executed")
        self.assertIn("3", response.message)
        self.assertIn("se agregaron", response.message)
        self.assertNotIn("tenés", response.message)

    def test_missing_presentation_returns_failed_fallback(self) -> None:
        intent = self._executed_intent(
            {
                "producto_presentacion_id": 42,
                "cantidad": 1,
                "cantidad_final": 1,
                "linea_creada": True,
            }
        )
        with patch(
            "backend.intents.responses.agregar_producto_response.ProductoQueryService"
        ) as mock_q:
            mock_q.return_value.list_presentaciones_by_ids.return_value = []
            response = build_agregar_producto_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.status, "failed")
        self.assertIn("intentar", response.message.lower())

    def test_invalid_quantity_returns_failed_fallback(self) -> None:
        intent = self._executed_intent(
            {"producto_presentacion_id": 42, "cantidad_final": 0}
        )
        response = build_agregar_producto_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.status, "failed")

    def test_inconsistent_modern_quantities_returns_failed_fallback(self) -> None:
        intent = self._executed_intent(
            {
                "producto_presentacion_id": 42,
                "cantidad_agregada": 5,
                "cantidad_final": 2,
                "linea_creada": False,
            }
        )
        response = build_agregar_producto_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.status, "failed")

    def test_invalid_modern_cantidad_agregada_returns_failed_fallback(self) -> None:
        intent = self._executed_intent(
            {
                "producto_presentacion_id": 42,
                "cantidad_agregada": 0,
                "cantidad_final": 5,
                "linea_creada": False,
            }
        )
        response = build_agregar_producto_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.status, "failed")

    def test_bool_modern_cantidad_agregada_returns_failed_fallback(self) -> None:
        intent = self._executed_intent(
            {
                "producto_presentacion_id": 42,
                "cantidad_agregada": True,
                "cantidad_final": 5,
                "linea_creada": False,
            }
        )
        response = build_agregar_producto_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.status, "failed")

    def test_invalid_modern_cantidad_final_returns_failed_fallback(self) -> None:
        intent = self._executed_intent(
            {
                "producto_presentacion_id": 42,
                "cantidad_agregada": 1,
                "cantidad_final": 0,
                "linea_creada": False,
            }
        )
        response = build_agregar_producto_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.status, "failed")

    def test_bool_modern_cantidad_final_returns_failed_fallback(self) -> None:
        intent = self._executed_intent(
            {
                "producto_presentacion_id": 42,
                "cantidad_agregada": 1,
                "cantidad_final": True,
                "linea_creada": False,
            }
        )
        response = build_agregar_producto_response(MagicMock(), MagicMock(), intent)
        self.assertEqual(response.status, "failed")

    def test_response_builder_is_pure_renderer_without_transaction_control(self) -> None:
        import pathlib

        import backend.intents.responses.agregar_producto_response as module

        source = pathlib.Path(module.__file__).read_text()
        forbidden = [
            "session.commit(",
            "session.rollback(",
            "session.flush(",
            "session.refresh(",
            "session.begin(",
            "session.close(",
            "emit_event",
            "PedidoProductoRepository",
            "select(PedidoProducto",
            "session.get(PedidoProducto",
            "from backend.repositories",
            "from backend.intents.handlers",
            "from backend.intents.orchestration",
            "from backend.llm",
            "import requests",
            "import fastapi",
            "import twilio",
        ]
        for needle in forbidden:
            self.assertNotIn(needle, source, f"forbidden builder construct: {needle}")

        intent = self._executed_intent(
            {
                "producto_presentacion_id": 42,
                "cantidad_agregada": 1,
                "cantidad_final": 7,
                "linea_creada": False,
            }
        )
        db = MagicMock(name="DatabaseSession")
        session = MagicMock(name="ConversationSession")
        with patch(
            "backend.intents.responses.agregar_producto_response.ProductoQueryService"
        ) as mock_q:
            mock_q.return_value.list_presentaciones_by_ids.return_value = [
                {"producto_nombre": "Verdura", "presentacion_descripcion": "unidad"}
            ]
            response = build_agregar_producto_response(db, session, intent)
        self.assertEqual(response.status, "executed")
        for method_name in (
            "commit",
            "rollback",
            "flush",
            "refresh",
            "expire",
            "begin",
            "close",
        ):
            getattr(db, method_name).assert_not_called()


class EndToEndHttpTests(unittest.TestCase):
    def test_two_identical_additions_consolidate(self) -> None:
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_empanada_y_pizza_catalog()
        try:
            with _patched_classifier_agregar():
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    first = process_incoming_message(
                        db,
                        session_row,
                        "quiero 2 empanadas de verdura",
                    )
                    db.commit()
                self.assertEqual(first[-1].status, "executed")

                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    second = process_incoming_message(
                        db,
                        session_row,
                        "agregá una empanada de verdura",
                    )
                    db.commit()
                self.assertEqual(second[-1].status, "executed")

            with TestingSessionLocal() as db:
                lines = db.execute(
                    select(PedidoProducto).where(PedidoProducto.id_pedido == ids["pedido_id"])
                ).scalars().all()
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0].cantidad, 3)
        finally:
            _cleanup(ids)

    def test_quitar_producto_regression_rerun(self) -> None:
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_empanada_y_pizza_catalog()
        try:
            with _patched_classifier_agregar():
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    first = process_incoming_message(
                        db,
                        session_row,
                        "quiero 3 empanadas de verdura",
                    )
                    db.commit()
                self.assertEqual(first[-1].status, "executed")

            with _patched_classifier_quitar():
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    decrement = process_incoming_message(
                        db,
                        session_row,
                        "quitar 1 empanada de verdura",
                    )
                    db.commit()
                self.assertEqual(decrement[-1].status, "executed")

            with TestingSessionLocal() as db:
                lines = db.execute(
                    select(PedidoProducto).where(PedidoProducto.id_pedido == ids["pedido_id"])
                ).scalars().all()
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0].cantidad, 2)
        finally:
            _cleanup(ids)


class CliRegressionRerunTests(unittest.TestCase):
    def test_order_table_regression_rerun(self) -> None:
        if test_client is None:
            self.skipTest("TestClient unavailable")
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_empanada_y_pizza_catalog()
        try:
            from backend.intents.orchestration import initial_intent_dispatcher as _dispatcher

            with patch.object(_dispatcher, "IntentClassifier", _PatchedClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    responses_first = process_incoming_message_with_responses(
                        db,
                        session_row,
                        "quiero 2 empanadas de verdura",
                    )
                    db.commit()
                self.assertEqual(responses_first[-1].status, "executed")
                self.assertIn("Empanada de Verdura", responses_first[-1].message)
                self.assertIn("Unidad", responses_first[-1].message)
                self.assertIn("2", responses_first[-1].message)
                self.assertIn("se agregaron", responses_first[-1].message)

                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    responses_second = process_incoming_message_with_responses(
                        db,
                        session_row,
                        "agregá una empanada de verdura",
                    )
                    db.commit()
                self.assertEqual(responses_second[-1].status, "executed")
                self.assertIn("3", responses_second[-1].message)
                self.assertIn("se agregaron", responses_second[-1].message)

            with TestingSessionLocal() as db:
                lines = db.execute(
                    select(PedidoProducto).where(PedidoProducto.id_pedido == ids["pedido_id"])
                ).scalars().all()
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0].cantidad, 3)
        finally:
            _cleanup(ids)


if __name__ == "__main__":
    unittest.main()
