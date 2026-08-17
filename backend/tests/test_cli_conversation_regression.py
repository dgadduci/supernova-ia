import importlib
import io
import json
import sys
import unittest
import uuid
import urllib.error
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

import backend.dependencies as dependencies_module
from backend.dependencies import get_session
from backend.main import app
from backend.intents.orchestration.incoming_message_orchestrator import (
    process_incoming_message,
)
from backend.intents.orchestration.transactional_message_processor import (
    process_incoming_message_transactional,
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

test_client = TestClient(app)
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


class _URLLibResponseAdapter:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        if isinstance(payload, (dict, list)):
            self._body = json.dumps(payload).encode("utf-8")
        elif isinstance(payload, bytes):
            self._body = payload
        elif isinstance(payload, str):
            self._body = payload.encode("utf-8")
        else:
            self._body = b""
        self._code = status_code

    def read(self):
        return self._body

    def getcode(self):
        return self._code

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _URLLibHTTPErrorAdapter(urllib.error.HTTPError):
    def __init__(self, status_code: int, payload, url: str) -> None:
        body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        super().__init__(url, status_code, "HTTP Error", {}, None)
        self._body = body

    def read(self, n=-1):
        return self._body


def _http_via_test_client(request, timeout=None):
    """Side-effect that forwards urllib.request calls to the in-process TestClient."""
    url = request.full_url
    if not url.startswith(BASE_URL):
        raise AssertionError(f"unexpected URL host: {url}")
    path = url[len(BASE_URL):]
    method = (request.method or "GET").upper()
    body_bytes = request.data
    json_body = json.loads(body_bytes) if body_bytes else None
    response = test_client.request(method, path, json=json_body)
    if response.status_code >= 400:
        raise _URLLibHTTPErrorAdapter(response.status_code, response.json(), url)
    return _URLLibResponseAdapter(response.status_code, response.json())


def _seed_five_pizza_catalog(db) -> dict:
    s = _suffix()
    estado_id = _estado_id_activo()

    comercio = Comercio(
        nombre_fantasia=f"Test Pizza {s}",
        nombre_corto=f"TP {s}",
        razon_social=f"Test Pizza SRL {s}",
        cuit=f"30-{s[:8]}-{s[8]}",
        whatsapp=f"+5491{s[:8]}",
        calle="Av. Pizza",
        numero="1234",
        piso_departamento=None,
        localidad="CABA",
        provincia="Buenos Aires",
        codigo_postal="C1000",
        slug=f"test-pizza-{s}",
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

    categoria = CategoriaProducto(
        id_comercio=comercio.id,
        descripcion=f"Pizzas {s}",
        activo=True,
        orden=0,
    )
    db.add(categoria)
    db.flush()

    presentaciones: dict[str, Presentacion] = {}
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

    nombres_productos = ["Pizza Mozzarella", "Pizza Napolitana", "Pizza Margherita"]
    variantes_presentacion = {
        "Pizza Mozzarella": ("chica", "grande"),
        "Pizza Napolitana": ("chica", "grande"),
        "Pizza Margherita": ("grande", None),
    }
    precios_unitarios: dict[tuple[str, str], Decimal] = {
        ("Pizza Mozzarella", "chica"): Decimal("8500.00"),
        ("Pizza Mozzarella", "grande"): Decimal("12500.00"),
        ("Pizza Napolitana", "chica"): Decimal("9000.00"),
        ("Pizza Napolitana", "grande"): Decimal("13000.00"),
        ("Pizza Margherita", "grande"): Decimal("12000.00"),
    }

    asociaciones: dict[str, ProductoPresentacion] = {}
    for nombre in nombres_productos:
        producto = Producto(
            id_categoria_producto=categoria.id,
            nombre=nombre,
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        db.add(producto)
        db.flush()
        for codigo in variantes_presentacion[nombre]:
            if codigo is None:
                continue
            assoc = ProductoPresentacion(
                id_producto=producto.id,
                id_presentacion=presentaciones[codigo].id,
                activo=True,
                orden=0,
            )
            db.add(assoc)
            db.flush()
            asociaciones[f"{nombre} {codigo}"] = assoc
            precio = Precio(
                id_producto_presentacion=assoc.id,
                precio=precios_unitarios[(nombre, codigo)],
            )
            db.add(precio)
            db.flush()

    muzzarella_grande_pp = asociaciones["Pizza Mozzarella grande"]
    muzzarella_grande_precio = precios_unitarios[("Pizza Mozzarella", "grande")]

    return {
        "comercio_id": comercio.id,
        "cliente_id": cliente.id,
        "producto_presentacion_ids": {key: assoc.id for key, assoc in asociaciones.items()},
        "muzzarella_grande_pp_id": muzzarella_grande_pp.id,
        "muzzarella_grande_precio": muzzarella_grande_precio,
    }


def _cleanup(*, comercio_id: int, cliente_id: int) -> None:
    with TestingSessionLocal() as db, db.begin():
        sess_row = db.execute(
            select(SessionModel).where(
                SessionModel.id_comercio == comercio_id,
                SessionModel.id_cliente == cliente_id,
            )
        ).scalar_one_or_none()
        if sess_row is not None:
            sess_row.id_pedido = None
            db.flush()
        db.execute(
            delete(PedidoProducto).where(
                PedidoProducto.id_pedido.in_(
                    select(Pedido.id).where(Pedido.id_session.in_(
                        select(SessionModel.id).where(
                            SessionModel.id_comercio == comercio_id,
                            SessionModel.id_cliente == cliente_id,
                        )
                    ))
                )
            )
        )
        db.execute(
            delete(Pedido).where(
                Pedido.id_session.in_(
                    select(SessionModel.id).where(
                        SessionModel.id_comercio == comercio_id,
                        SessionModel.id_cliente == cliente_id,
                    )
                )
            )
        )
        db.execute(
            delete(SessionModel).where(
                SessionModel.id_comercio == comercio_id,
                SessionModel.id_cliente == cliente_id,
            )
        )
        db.execute(
            delete(Precio).where(
                Precio.id_producto_presentacion.in_(
                    select(ProductoPresentacion.id).where(
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
            )
        )
        db.execute(
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
        db.execute(
            delete(Producto).where(
                Producto.id_categoria_producto.in_(
                    select(CategoriaProducto.id).where(
                        CategoriaProducto.id_comercio == comercio_id
                    )
                )
            )
        )
        db.execute(
            delete(Presentacion).where(Presentacion.id_comercio == comercio_id)
        )
        db.execute(
            delete(CategoriaProducto).where(
                CategoriaProducto.id_comercio == comercio_id
            )
        )
        db.execute(delete(Cliente).where(Cliente.id == cliente_id))
        db.execute(delete(Comercio).where(Comercio.id == comercio_id))


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


@contextmanager
def _patched_classifier():
    from backend.intents.orchestration import initial_intent_dispatcher as _dispatcher

    _PatchedClassifier.constructor_calls = []
    _PatchedClassifier.query_calls = []

    patcher = patch.object(_dispatcher, "IntentClassifier", _PatchedClassifier)
    patcher.start()
    try:
        yield _PatchedClassifier
    finally:
        patcher.stop()


def _import_cli():
    if "backend.scripts.cli_chat_client" in sys.modules:
        del sys.modules["backend.scripts.cli_chat_client"]
    return importlib.import_module("backend.scripts.cli_chat_client")


class FullConversationHappyPathTest(unittest.TestCase):
    def test_full_conversation_executes_without_extra_turn(self):
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_five_pizza_catalog(db)
        comercio_id = ids["comercio_id"]
        cliente_id = ids["cliente_id"]
        try:
            cli = _import_cli()
            comercio_id = ids["comercio_id"]
            cliente_id = ids["cliente_id"]
            muzzarella_grande_pp_id = ids["muzzarella_grande_pp_id"]
            expected_precio = ids["muzzarella_grande_precio"]

            with _patched_classifier():
                buffer = io.StringIO()
                with patch.object(
                    cli.urllib.request, "urlopen", side_effect=_http_via_test_client
                ), patch.object(
                    dependencies_module,
                    "_SessionLocal",
                    TestingSessionLocal,
                ), patch(
                    "builtins.input",
                    side_effect=[
                        str(comercio_id),
                        str(cliente_id),
                        "quiero dos pizzas",
                        "pizza grande",
                        "Pizza de Muzzarella Grande",
                        "exit",
                    ],
                ), patch("sys.stdout", buffer):
                    with self.assertRaises(SystemExit):
                        cli.main()

            printed = buffer.getvalue()
            self.assertIn(f"<session ", printed)
            self.assertIn("<pedido ", printed)
            self.assertIn("Listo, se agregaron 2 Pizza Mozzarella Presentacion grande", printed)
            self.assertIn("Pizza Margherita Presentacion grande", printed)
            self.assertIn("Pizza Napolitana Presentacion grande", printed)

            with TestingSessionLocal() as db:
                lines = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_producto_presentacion == muzzarella_grande_pp_id
                    )
                ).scalars().all()
                self.assertEqual(len(lines), 1)
                self.assertEqual(lines[0].cantidad, 2)
                self.assertEqual(lines[0].precio_unitario, expected_precio)

                pedido_row = db.execute(
                    select(Pedido).where(
                        Pedido.id_session.in_(
                            select(SessionModel.id).where(
                                SessionModel.id_comercio == comercio_id,
                                SessionModel.id_cliente == cliente_id,
                            )
                        )
                    )
                ).scalar_one()
                self.assertEqual(pedido_row.estado_pedido, EstadoPedido.BORRADOR)
        finally:
            _cleanup(comercio_id=comercio_id, cliente_id=cliente_id)


class ExactUniqueCandidateTest(unittest.TestCase):
    def test_exact_unique_candidate_executes_in_same_turn(self):
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_five_pizza_catalog(db)
        comercio_id = ids["comercio_id"]
        cliente_id = ids["cliente_id"]
        try:
            cli = _import_cli()
            comercio_id = ids["comercio_id"]
            cliente_id = ids["cliente_id"]
            muzzarella_grande_pp_id = ids["muzzarella_grande_pp_id"]

            with _patched_classifier():
                buffer = io.StringIO()
                with patch.object(
                    cli.urllib.request, "urlopen", side_effect=_http_via_test_client
                ), patch.object(
                    dependencies_module,
                    "_SessionLocal",
                    TestingSessionLocal,
                ), patch(
                    "builtins.input",
                    side_effect=[
                        str(comercio_id),
                        str(cliente_id),
                        "quiero dos pizzas",
                        "Pizza de Muzzarella Grande",
                        "exit",
                    ],
                ), patch("sys.stdout", buffer):
                    with self.assertRaises(SystemExit):
                        cli.main()

            printed = buffer.getvalue()
            self.assertIn(
                "Listo, se agregaron 2 Pizza Mozzarella Presentacion grande", printed
            )

            with TestingSessionLocal() as db:
                lines = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_producto_presentacion == muzzarella_grande_pp_id
                    )
                ).scalars().all()
                self.assertEqual(len(lines), 1)
                self.assertEqual(lines[0].cantidad, 2)
        finally:
            _cleanup(comercio_id=comercio_id, cliente_id=cliente_id)


class ExactUniqueCandidateFirstMessageTest(unittest.TestCase):
    def test_exact_unique_candidate_as_first_message_executes_in_same_turn(self):
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_five_pizza_catalog(db)
        comercio_id = ids["comercio_id"]
        cliente_id = ids["cliente_id"]
        try:
            cli = _import_cli()
            comercio_id = ids["comercio_id"]
            cliente_id = ids["cliente_id"]
            muzzarella_grande_pp_id = ids["muzzarella_grande_pp_id"]

            with _patched_classifier():
                buffer = io.StringIO()
                with patch.object(
                    cli.urllib.request, "urlopen", side_effect=_http_via_test_client
                ), patch.object(
                    dependencies_module,
                    "_SessionLocal",
                    TestingSessionLocal,
                ), patch(
                    "builtins.input",
                    side_effect=[
                        str(comercio_id),
                        str(cliente_id),
                        "Pizza de Muzzarella Grande",
                        "exit",
                    ],
                ), patch("sys.stdout", buffer):
                    with self.assertRaises(SystemExit):
                        cli.main()

            printed = buffer.getvalue()
            self.assertIn("Listo, agregué 1 Pizza Mozzarella Presentacion grande", printed)
            self.assertNotIn("No pude procesar tu pedido", printed)

            with TestingSessionLocal() as db:
                lines = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_producto_presentacion == muzzarella_grande_pp_id
                    )
                ).scalars().all()
                self.assertEqual(len(lines), 1)
                self.assertEqual(lines[0].cantidad, 1)
        finally:
            _cleanup(comercio_id=comercio_id, cliente_id=cliente_id)


class TamanioOnlyRefinementTest(unittest.TestCase):
    def test_size_only_refinement_after_candidates_executes(self):
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_five_pizza_catalog(db)
        comercio_id = ids["comercio_id"]
        cliente_id = ids["cliente_id"]
        try:
            cli = _import_cli()
            comercio_id = ids["comercio_id"]
            cliente_id = ids["cliente_id"]
            muzzarella_grande_pp_id = ids["muzzarella_grande_pp_id"]

            with _patched_classifier():
                buffer = io.StringIO()
                with patch.object(
                    cli.urllib.request, "urlopen", side_effect=_http_via_test_client
                ), patch.object(
                    dependencies_module,
                    "_SessionLocal",
                    TestingSessionLocal,
                ), patch(
                    "builtins.input",
                    side_effect=[
                        str(comercio_id),
                        str(cliente_id),
                        "Pizza de Muzzarella",
                        "grande",
                        "exit",
                    ],
                ), patch("sys.stdout", buffer):
                    with self.assertRaises(SystemExit):
                        cli.main()

            printed = buffer.getvalue()
            self.assertIn("Elegí entre", printed)
            self.assertIn(
                "Listo, agregué 1 Pizza Mozzarella Presentacion grande", printed
            )
            self.assertNotIn("No pude procesar tu pedido", printed)

            with TestingSessionLocal() as db:
                lines = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_producto_presentacion == muzzarella_grande_pp_id
                    )
                ).scalars().all()
                self.assertEqual(len(lines), 1)
                self.assertEqual(lines[0].cantidad, 1)
        finally:
            _cleanup(comercio_id=comercio_id, cliente_id=cliente_id)


class RejectedClearsPendingContextTest(unittest.TestCase):
    def test_rejected_clears_pending_context(self):
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_five_pizza_catalog(db)
            session_row = SessionModel(
                id_comercio=ids["comercio_id"],
                id_cliente=ids["cliente_id"],
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

            from backend.intents.context.context_type_resolver import resolve_context_type
            from backend.intents.schemas.pending_intents import PendingIntents
            from backend.intents.schemas.processed_intent import ProcessedIntent
            from backend.intents.schemas.requirement_state import RequirementState

            candidate_ids = list(ids["producto_presentacion_ids"].values())
            first_intent = ProcessedIntent(
                intent="agregar_producto",
                source_text="quiero dos pizzas",
                status="pending_resolution",
                recognizer="recognizer_productos",
                handler="agregar_producto",
                resolved_data={"cantidad": 2},
                requirements=[
                    RequirementState(
                        name="producto_presentacion_id", status="pending", value=None
                    )
                ],
                candidate_ids=candidate_ids,
            )
            context_type_value = resolve_context_type(first_intent)
            assert context_type_value is not None
            session_row.pending_intents = PendingIntents(active=first_intent).model_dump(mode="json")
            session_row.context_type = context_type_value.value
            db.flush()
            session_id = session_row.id
            pedido_id = pedido.id

        try:
            with TestingSessionLocal() as db, db.begin():
                db.execute(
                    delete(Precio).where(
                        Precio.id_producto_presentacion.in_(
                            select(ProductoPresentacion.id).where(
                                ProductoPresentacion.id_producto.in_(
                                    select(Producto.id).where(
                                        Producto.id_categoria_producto.in_(
                                            select(CategoriaProducto.id).where(
                                                CategoriaProducto.id_comercio == ids["comercio_id"]
                                            )
                                        )
                                    )
                                )
                            )
                        )
                    )
                )

            with _patched_classifier() as patched:
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, session_id)
                    assert session_row is not None
                    result = process_incoming_message_transactional(
                        db, session_row, "Pizza de Muzzarella Grande"
                    )
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "rejected")
                    self.assertEqual(session_row.context_type, None)
                    pending = session_row.pending_intents or {}
                    self.assertIsNone(pending.get("active"))

                    unrelated = process_incoming_message(
                        db,
                        session_row,
                        "hola",
                    )
                    self.assertEqual(len(unrelated), 1)
                    self.assertEqual(unrelated[0].status, "pending_resolution")
                    self.assertGreaterEqual(len(patched.query_calls), 1)
                    self.assertEqual(patched.query_calls[-1], "hola")
                    db.commit()
        finally:
            _cleanup(comercio_id=ids["comercio_id"], cliente_id=ids["cliente_id"])


class RaisedExceptionPropagatesTest(unittest.TestCase):
    def test_raised_integrity_error_propagates_and_no_row_inserted(self):
        from backend.intents.orchestration import pending_context_execution as execution_module
        from sqlalchemy.exc import IntegrityError

        with TestingSessionLocal() as db, db.begin():
            ids = _seed_five_pizza_catalog(db)
            session_row = SessionModel(
                id_comercio=ids["comercio_id"],
                id_cliente=ids["cliente_id"],
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

            from backend.intents.schemas.pending_intents import PendingIntents
            from backend.intents.schemas.processed_intent import ProcessedIntent
            from backend.intents.schemas.requirement_state import RequirementState
            from backend.sessions.enums.context_type import ContextType

            muzzarella_grande_pp_id = ids["muzzarella_grande_pp_id"]
            first_intent = ProcessedIntent(
                intent="agregar_producto",
                source_text="quiero dos pizzas",
                status="pending_resolution",
                recognizer="recognizer_productos",
                handler="agregar_producto",
                resolved_data={
                    "cantidad": 2,
                    "producto_presentacion_id": muzzarella_grande_pp_id,
                },
                requirements=[
                    RequirementState(
                        name="producto_presentacion_id",
                        status="completed",
                        value=muzzarella_grande_pp_id,
                    )
                ],
                candidate_ids=[muzzarella_grande_pp_id],
            )
            session_row.pending_intents = PendingIntents(active=first_intent).model_dump(mode="json")
            session_row.context_type = ContextType.PRODUCT_SELECTION.value
            db.flush()
            session_id = session_row.id

        try:
            with patch.object(
                execution_module,
                "execute_agregar_producto",
                side_effect=IntegrityError("INSERT", {}, Exception("forced db error")),
            ):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, session_id)
                    assert session_row is not None
                    with self.assertRaises(IntegrityError):
                        process_incoming_message_transactional(
                            db, session_row, "Pizza de Muzzarella Grande"
                        )

            with TestingSessionLocal() as db:
                lines = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_producto_presentacion == muzzarella_grande_pp_id
                    )
                ).scalars().all()
                self.assertEqual(lines, [])
        finally:
            _cleanup(comercio_id=ids["comercio_id"], cliente_id=ids["cliente_id"])


class CliCleanupTest(unittest.TestCase):
    def test_cli_cleanup_closes_only_session(self):
        with TestingSessionLocal() as db, db.begin():
            ids = _seed_five_pizza_catalog(db)
        comercio_id = ids["comercio_id"]
        cliente_id = ids["cliente_id"]
        try:
            cli = _import_cli()
            comercio_id = ids["comercio_id"]
            cliente_id = ids["cliente_id"]

            with _patched_classifier():
                with patch.object(
                    cli.urllib.request, "urlopen", side_effect=_http_via_test_client
                ) as mock_urlopen, patch.object(
                    dependencies_module,
                    "_SessionLocal",
                    TestingSessionLocal,
                ), patch(
                    "builtins.input",
                    side_effect=[str(comercio_id), str(cliente_id), "exit"],
                ):
                    with self.assertRaises(SystemExit):
                        cli.main()

            bootstrap_calls = [
                c
                for c in mock_urlopen.call_args_list
                if c.args[0].full_url.endswith("/sessions")
                or c.args[0].full_url.endswith("/pedidos")
                or "/sessions/" in c.args[0].full_url
            ]
            post_pedidos = [
                c for c in bootstrap_calls if c.args[0].full_url.endswith("/pedidos")
            ]
            put_asociar = [
                c
                for c in bootstrap_calls
                if "/pedido" in c.args[0].full_url and "PUT" in (c.args[0].method or "").upper()
            ]
            close_calls = [
                c
                for c in bootstrap_calls
                if c.args[0].full_url.endswith("/cerrar")
            ]
            self.assertEqual(len(post_pedidos), 1)
            self.assertEqual(len(put_asociar), 1)
            self.assertEqual(len(close_calls), 1)

            method = (close_calls[0].args[0].method or "GET").upper()
            self.assertEqual(method, "POST")

            with TestingSessionLocal() as db:
                rows = db.execute(
                    select(SessionModel).where(
                        SessionModel.id_comercio == comercio_id,
                        SessionModel.id_cliente == cliente_id,
                    )
                ).scalars().all()
                self.assertGreaterEqual(len(rows), 1)
                for row in rows:
                    self.assertEqual(row.estado_session, EstadoSession.CERRADA)
        finally:
            _cleanup(comercio_id=comercio_id, cliente_id=cliente_id)


if __name__ == "__main__":
    unittest.main()
