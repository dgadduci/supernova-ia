"""Real-flow CLI regression for `modificar_producto`.

Drives ``backend.scripts.cli_chat_client`` end-to-end against the real
``POST /comercios/{id}/clientes/{id}/incoming-messages`` endpoint with the
exact two reproduction phrases from subphase 3.32.2.

The CLI driver is a pure HTTP client. This test imports the CLI module and
patches ``urllib.request.urlopen`` with a real adapter that forwards every
HTTP call to the FastAPI ``TestClient`` running with
``app.dependency_overrides`` against ``supernova_test``. The CLI's input
loop is driven by patching ``builtins.input``. The printed stdout is
asserted for the customer response message and the printed order table.

The CLI module is NOT modified; only its HTTP and input seams are patched.
The intent classifier is NOT patched; the LLM-based pipeline runs for real.

The test sets up the initial Pedido lines via ``agregar_producto`` messages
through the CLI itself, then drives the modification. This mirrors how a
real customer would build up a Pedido before issuing a modification.
"""
import importlib
import io
import json
import sys
import unittest
import urllib.error
import urllib.request
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
            select(EstadoComercio.id).where(EstadoComercio.codigo == "ACTIVO")
        ).first()
        if row is None:
            raise RuntimeError("estado ACTIVO not seeded in supernova_test")
        return row[0]


def _seed_commerce(suffix: str) -> dict:
    estado_id = _estado_id_activo()
    with TestingSessionLocal() as db, db.begin():
        comercio = Comercio(
            nombre_fantasia=f"RealFlowCli-{suffix}",
            nombre_corto=f"RFC-{suffix}",
            razon_social=f"RealFlowCli SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+5499{suffix[:8]}",
            calle="RealCli",
            numero="1",
            piso_departamento=None,
            localidad="CABA",
            provincia="BA",
            codigo_postal="C1000",
            slug=f"realflowcli-{suffix}",
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

        pres_v = Presentacion(
            id_comercio=comercio.id,
            codigo=f"v-{suffix}",
            descripcion=f"unidad-v-{suffix}",
            activo=True,
            orden=0,
        )
        db.add(pres_v)
        db.flush()

        pres_c = Presentacion(
            id_comercio=comercio.id,
            codigo=f"c-{suffix}",
            descripcion=f"unidad-c-{suffix}",
            activo=True,
            orden=0,
        )
        db.add(pres_c)
        db.flush()

        pres_j = Presentacion(
            id_comercio=comercio.id,
            codigo=f"j-{suffix}",
            descripcion=f"unidad-j-{suffix}",
            activo=True,
            orden=0,
        )
        db.add(pres_j)
        db.flush()

        pp_v = ProductoPresentacion(
            id_producto=prod_verdura.id,
            id_presentacion=pres_v.id,
            activo=True,
            orden=0,
        )
        db.add(pp_v)
        db.flush()

        pp_c = ProductoPresentacion(
            id_producto=prod_carne.id,
            id_presentacion=pres_c.id,
            activo=True,
            orden=0,
        )
        db.add(pp_c)
        db.flush()

        pp_j = ProductoPresentacion(
            id_producto=prod_jq.id,
            id_presentacion=pres_j.id,
            activo=True,
            orden=0,
        )
        db.add(pp_j)
        db.flush()

        db.add(Precio(id_producto_presentacion=pp_v.id, precio=Decimal("100.00")))
        db.add(Precio(id_producto_presentacion=pp_c.id, precio=Decimal("120.00")))
        db.add(Precio(id_producto_presentacion=pp_j.id, precio=Decimal("110.00")))
        db.flush()

        return {
            "comercio_id": comercio.id,
            "cliente_id": cliente.id,
            "pp_v": pp_v.id,
            "pp_c": pp_c.id,
            "pp_j": pp_j.id,
        }


def _cleanup_commerce(base: dict) -> None:
    with TestingSessionLocal() as db, db.begin():
        db.execute(
            delete(PedidoProducto).where(
                PedidoProducto.id_producto_presentacion.in_(
                    [base["pp_v"], base["pp_c"], base["pp_j"]]
                )
            )
        )
        sess_rows = list(
            db.execute(
                select(SessionModel).where(
                    SessionModel.id_comercio == base["comercio_id"]
                )
            ).scalars()
        )
        for sess in sess_rows:
            sess.id_pedido = None
            sess.context_type = None
            sess.pending_intents = {}
            db.flush()
            db.execute(delete(Pedido).where(Pedido.id_session == sess.id))
            db.flush()
        db.execute(
            delete(SessionModel).where(
                SessionModel.id_comercio == base["comercio_id"]
            )
        )
        db.execute(
            delete(Precio).where(
                Precio.id_producto_presentacion.in_(
                    [base["pp_v"], base["pp_c"], base["pp_j"]]
                )
            )
        )
        db.execute(
            delete(ProductoPresentacion).where(
                ProductoPresentacion.id.in_([base["pp_v"], base["pp_c"], base["pp_j"]])
            )
        )


def _import_cli():
    if "backend.scripts.cli_chat_client" in sys.modules:
        del sys.modules["backend.scripts.cli_chat_client"]
    return importlib.import_module("backend.scripts.cli_chat_client")


def _run_cli_through_test_client(phrases: list[str], comercio_id: int, cliente_id: int) -> str:
    """Drive the CLI driver through the FastAPI TestClient."""
    cli = _import_cli()

    def _adapter(request, timeout=None):
        method = request.method or "GET"
        url = request.full_url
        path = url.split("127.0.0.1:8000", 1)[-1] if "127.0.0.1:8000" in url else url
        body = request.data
        headers = dict(request.headers.items())
        try:
            resp = test_client.request(method, path, content=body, headers=headers)
        except Exception as exc:
            raise urllib.error.URLError(str(exc))

        class _Resp:
            def __init__(self, status_code, payload):
                self.status_code = status_code
                self._payload = payload
                self._code = status_code

            def read(self):
                if isinstance(self._payload, (dict, list)):
                    return json.dumps(self._payload).encode("utf-8")
                if isinstance(self._payload, bytes):
                    return self._payload
                if isinstance(self._payload, str):
                    return self._payload.encode("utf-8")
                return b""

            def getcode(self):
                return self._code

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return _Resp(
            resp.status_code,
            resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else resp.text,
        )

    input_iter = iter([str(comercio_id), str(cliente_id), *phrases, "exit"])

    def _input(_prompt):
        return next(input_iter)

    buffer = io.StringIO()

    import unittest.mock as mock
    with mock.patch.object(cli.urllib.request, "urlopen", side_effect=_adapter), \
         mock.patch("builtins.input", side_effect=_input), \
         mock.patch("sys.stdout", buffer):
        try:
            cli.main()
        except SystemExit:
            pass

    return buffer.getvalue()


def _get_current_pedido_id(comercio_id: int) -> int | None:
    with TestingSessionLocal() as db:
        row = db.execute(
            select(SessionModel.id_pedido).where(
                SessionModel.id_comercio == comercio_id
            )
        ).first()
        if row is None:
            return None
        return row[0]


def _assert_session_clean(comercio_id: int) -> None:
    with TestingSessionLocal() as db:
        sess = db.execute(
            select(SessionModel).where(
                SessionModel.id_comercio == comercio_id
            )
        ).scalar_one()
        assert sess is not None
        assert sess.context_type is None


class ModificarProductoRealFlowCliTest(unittest.TestCase):
    def test_defect_1_cli_full_transfer_on_omitted_quantity(self):
        suffix = _suffix()
        base = _seed_commerce(suffix)
        try:
            setup_msgs = [
                "agregar 4 empanadas de verdura",
                "agregar 5 empanadas de jamon y queso",
            ]
            modify_msg = "cambia las empanadas de verdura por empanadas carne picante"
            stdout = _run_cli_through_test_client(
                setup_msgs + [modify_msg],
                base["comercio_id"],
                base["cliente_id"],
            )
            self.assertIn("Pedido actual:", stdout)

            pedido_id = _get_current_pedido_id(base["comercio_id"])
            self.assertIsNotNone(pedido_id)
            with TestingSessionLocal() as db:
                lines = list(
                    db.execute(
                        select(PedidoProducto).where(
                            PedidoProducto.id_pedido == pedido_id
                        )
                    ).scalars()
                )
                v_lines = [
                    l for l in lines if l.id_producto_presentacion == base["pp_v"]
                ]
                c_lines = [
                    l for l in lines if l.id_producto_presentacion == base["pp_c"]
                ]
                j_lines = [
                    l for l in lines if l.id_producto_presentacion == base["pp_j"]
                ]
                self.assertEqual(
                    len(v_lines),
                    0,
                    f"Source verdura should be removed, found {len(v_lines)}",
                )
                self.assertEqual(
                    len(c_lines),
                    1,
                    f"Destination carne should exist, found {len(c_lines)}",
                )
                self.assertEqual(c_lines[0].cantidad, 4)
                self.assertEqual(
                    len(j_lines),
                    1,
                    f"Untouched jamon y queso should remain, found {len(j_lines)}",
                )
                self.assertEqual(j_lines[0].cantidad, 5)

            _assert_session_clean(base["comercio_id"])
        finally:
            _cleanup_commerce(base)

    def test_defect_2_cli_unknown_destination_preserves_source(self):
        suffix = _suffix()
        base = _seed_commerce(suffix)
        try:
            setup_msgs = [
                "agregar 5 empanadas de jamon y queso",
                "agregar 4 empanadas de verdura",
            ]
            modify_msg = (
                "cambia las 5 empanadas de jamon y queso por un caramelo"
            )
            stdout = _run_cli_through_test_client(
                setup_msgs + [modify_msg],
                base["comercio_id"],
                base["cliente_id"],
            )
            self.assertIn("Tu pedido no fue modificado", stdout)

            pedido_id = _get_current_pedido_id(base["comercio_id"])
            self.assertIsNotNone(pedido_id)
            with TestingSessionLocal() as db:
                lines = list(
                    db.execute(
                        select(PedidoProducto).where(
                            PedidoProducto.id_pedido == pedido_id
                        )
                    ).scalars()
                )
                j_lines = [
                    l for l in lines if l.id_producto_presentacion == base["pp_j"]
                ]
                self.assertEqual(
                    len(j_lines),
                    1,
                    f"Source jamon y queso should be preserved, found {len(j_lines)}",
                )
                self.assertEqual(j_lines[0].cantidad, 5)

            _assert_session_clean(base["comercio_id"])
        finally:
            _cleanup_commerce(base)


if __name__ == "__main__":
    unittest.main()
