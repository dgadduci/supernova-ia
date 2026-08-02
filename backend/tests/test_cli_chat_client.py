import importlib
import io
import json
import os
import sys
import unittest
import urllib.error
from unittest import mock


class FakeResponse:
    def __init__(self, body, status=200):
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.status = status
        self._code = status

    def read(self):
        return self._body

    def getcode(self):
        return self._code

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _fake_urlopen(responses):
    """Return a side_effect callable that yields one response per urlopen call."""

    iterator = iter(responses)

    def _side_effect(request, timeout=None):
        try:
            return next(iterator)
        except StopIteration:
            raise AssertionError(f"unexpected urlopen call: {request.full_url}")

    return _side_effect


def _bootstrap_responses(
    session_id=42, pedido_id=77, existing_active_session_id=None
):
    """Standard happy-path bootstrap.

    When ``existing_active_session_id`` is None, the CLI sees a 404 on
    ``GET /sessions/.../activa`` and proceeds straight to the create flow.
    When it is set, the CLI gets a 200 with that id, closes the active
    session, then proceeds to the create flow.
    """
    if existing_active_session_id is None:
        get_activa = FakeResponse({"detail": "no active"}, status=404)
        bootstrap = []
    else:
        get_activa = FakeResponse(
            {"id": existing_active_session_id, "activa": True}, status=200
        )
        bootstrap = [
            FakeResponse(
                {"id": existing_active_session_id, "activa": False}, status=200
            )
        ]
    bootstrap += [
        FakeResponse({"id": session_id, "id_comercio": 1, "id_cliente": 8}, status=201),
        FakeResponse({"id": pedido_id}, status=201),
        FakeResponse({"id": session_id, "id_pedido": pedido_id}, status=200),
    ]
    return [get_activa, *bootstrap]


def _import_cli():
    sys.path.insert(0, os.getcwd())
    if "backend.scripts.cli_chat_client" in sys.modules:
        del sys.modules["backend.scripts.cli_chat_client"]
    return importlib.import_module("backend.scripts.cli_chat_client")


class CliChatClientTest(unittest.TestCase):
    def test_creates_session_on_start(self):
        cli = _import_cli()
        responses = _bootstrap_responses() + [
            FakeResponse({"id": 42, "activa": False}, status=200),
        ]
        buffer = io.StringIO()
        with mock.patch.object(cli.urllib.request, "urlopen",
                               side_effect=_fake_urlopen(responses)) as mock_urlopen, \
             mock.patch("builtins.input", side_effect=["1", "8", "exit"]), \
             mock.patch("sys.stdout", buffer):
            with self.assertRaises(SystemExit) as ctx:
                cli.main()
        self.assertEqual(ctx.exception.code, 0)
        create_calls = [c for c in mock_urlopen.call_args_list
                        if "/sessions" in c.args[0].full_url
                        and c.args[0].method == "POST"
                        and not c.args[0].full_url.rstrip("/").endswith(("42/cerrar", "42/cerrar/"))]
        self.assertGreaterEqual(len(create_calls), 1)
        create_req = create_calls[0].args[0]
        self.assertTrue(create_req.full_url.endswith("/sessions"))
        body = json.loads(create_req.data.decode("utf-8"))
        self.assertEqual(body, {"id_comercio": 1, "id_cliente": 8})
        printed = buffer.getvalue()
        self.assertIn("<session 42>", printed)

    def test_reuses_session_for_each_message(self):
        cli = _import_cli()
        responses = _bootstrap_responses() + [
            FakeResponse({"responses": [{"message": "uno"}]}, status=200),
            FakeResponse({"responses": [{"message": "dos"}]}, status=200),
            FakeResponse({"id": 42, "activa": False}, status=200),
        ]
        with mock.patch.object(cli.urllib.request, "urlopen",
                               side_effect=_fake_urlopen(responses)) as mock_urlopen, \
             mock.patch("builtins.input", side_effect=["1", "8", "hola", "adios", "exit"]):
            with self.assertRaises(SystemExit):
                cli.main()
        calls = mock_urlopen.call_args_list
        create_calls = [c for c in calls if c.args[0].full_url.endswith("/sessions")
                        and c.args[0].method == "POST"]
        msg_calls = [c for c in calls
                     if "/incoming-messages" in c.args[0].full_url]
        self.assertEqual(len(create_calls), 1)
        self.assertEqual(len(msg_calls), 2)
        self.assertEqual(json.loads(msg_calls[0].args[0].data.decode("utf-8")),
                         {"message": "hola"})
        self.assertEqual(json.loads(msg_calls[1].args[0].data.decode("utf-8")),
                         {"message": "adios"})

    def test_prints_pipeline_responses(self):
        cli = _import_cli()
        responses = _bootstrap_responses(session_id=7, pedido_id=99) + [
            FakeResponse(
                {"responses": [{"message": "Hola", "intent": "saludo", "status": "rejected"}]},
                status=200,
            ),
            FakeResponse(
                {"responses": [{"intent": "x", "status": "y"}]},
                status=200,
            ),
            FakeResponse({"id": 7, "activa": False}, status=200),
        ]
        buffer = io.StringIO()
        with mock.patch.object(cli.urllib.request, "urlopen",
                               side_effect=_fake_urlopen(responses)), \
             mock.patch("builtins.input", side_effect=["1", "8", "hola", "chau", "exit"]), \
             mock.patch("sys.stdout", buffer):
            with self.assertRaises(SystemExit):
                cli.main()
        output = buffer.getvalue()
        self.assertIn("<- message=Hola", output)
        self.assertIn('<- raw={"intent": "x", "status": "y"}', output)

    def test_empty_input_makes_no_http_call(self):
        cli = _import_cli()
        responses = _bootstrap_responses(session_id=9, pedido_id=33) + [
            FakeResponse({"responses": [{"message": "after-blank"}]}, status=200),
            FakeResponse({"id": 9, "activa": False}, status=200),
        ]
        with mock.patch.object(cli.urllib.request, "urlopen",
                               side_effect=_fake_urlopen(responses)) as mock_urlopen, \
             mock.patch("builtins.input", side_effect=["1", "8", "", "hola", "exit"]):
            with self.assertRaises(SystemExit):
                cli.main()
        calls = mock_urlopen.call_args_list
        msg_calls = [c for c in calls if "/incoming-messages" in c.args[0].full_url]
        self.assertEqual(len(msg_calls), 1)
        self.assertEqual(json.loads(msg_calls[0].args[0].data.decode("utf-8")),
                         {"message": "hola"})

    def test_exit_breaks_loop_and_closes_session(self):
        cli = _import_cli()
        responses = _bootstrap_responses(session_id=11, pedido_id=88) + [
            FakeResponse({"id": 11, "activa": False}, status=200),
        ]
        with mock.patch.object(cli.urllib.request, "urlopen",
                               side_effect=_fake_urlopen(responses)) as mock_urlopen, \
             mock.patch("builtins.input", side_effect=["1", "8", "  EXIT  "]):
            with self.assertRaises(SystemExit) as ctx:
                cli.main()
        self.assertEqual(ctx.exception.code, 0)
        calls = mock_urlopen.call_args_list
        close_calls = [c for c in calls if "/sessions/11/cerrar" in c.args[0].full_url]
        self.assertEqual(len(close_calls), 1)

    def test_close_failure_is_non_fatal(self):
        cli = _import_cli()
        responses = _bootstrap_responses(session_id=13, pedido_id=21) + [
            urllib.error.URLError("connection refused"),
        ]
        buffer = io.StringIO()
        with mock.patch.object(cli.urllib.request, "urlopen",
                               side_effect=_fake_urlopen(responses)), \
             mock.patch("builtins.input", side_effect=["1", "8", "exit"]), \
             mock.patch("sys.stdout", buffer):
            with self.assertRaises(SystemExit) as ctx:
                cli.main()
        self.assertEqual(ctx.exception.code, 0)
        output = buffer.getvalue()
        self.assertIn("warning: failed to close session 13:", output)

    def test_base_url_resolution(self):
        cli = _import_cli()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INCOMING_MESSAGES_BASE_URL", None)
            self.assertEqual(
                cli._resolve_base_url(["--base-url", "http://flag:9000/"]),
                "http://flag:9000",
            )
            self.assertEqual(
                cli._resolve_base_url(["--base-url", "http://flag:9000"]),
                "http://flag:9000",
            )
            os.environ["INCOMING_MESSAGES_BASE_URL"] = "http://env:8000/"
            self.assertEqual(cli._resolve_base_url([]), "http://env:8000")
            os.environ["INCOMING_MESSAGES_BASE_URL"] = "http://env:8000"
            self.assertEqual(cli._resolve_base_url([]), "http://env:8000")
            os.environ.pop("INCOMING_MESSAGES_BASE_URL", None)
            self.assertEqual(cli._resolve_base_url([]), "http://127.0.0.1:8000")

    def test_import_boundary(self):
        cli = _import_cli()
        banned = {
            "fastapi",
            "sqlalchemy",
            "uvicorn",
            "requests",
            "httpx",
            "aiohttp",
            "websockets",
        }
        banned_backend_prefixes = (
            "backend.routers",
            "backend.services",
            "backend.repositories",
            "backend.intents",
            "backend.llm",
            "backend.models",
            "backend.alembic",
            "backend.dependencies",
        )
        self.assertTrue(hasattr(cli, "response_modified_order"))
        self.assertTrue(hasattr(cli, "format_order_table"))
        self.assertTrue(hasattr(cli, "_fetch_pedido_detalle"))
        violations = []
        for value in vars(cli).values():
            mod_name = getattr(value, "__name__", None)
            if not mod_name:
                continue
            if mod_name in banned or mod_name.split(".")[0] in banned:
                violations.append(mod_name)
                continue
            if any(mod_name == p or mod_name.startswith(p + ".") for p in banned_backend_prefixes):
                violations.append(mod_name)
        self.assertEqual(
            violations,
            [],
            f"banned modules imported: {violations}",
        )
        source_path = cli.__file__ or ""
        if source_path:
            with open(source_path, "r", encoding="utf-8") as f:
                source = f.read()
        else:
            source = ""
        self.assertNotIn("import fastapi", source)
        self.assertNotIn("import sqlalchemy", source)
        self.assertNotIn("import uvicorn", source)
        self.assertNotIn("import requests", source)
        self.assertNotIn("import httpx", source)
        self.assertNotIn("import aiohttp", source)
        self.assertNotIn("import websockets", source)


class CliBootstrapSequenceTest(unittest.TestCase):
    def test_bootstrap_issues_three_calls_in_order_with_payloads(self):
        cli = _import_cli()
        session_id = 123
        pedido_id = 456
        responses = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id) + [
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        buffer = io.StringIO()
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ) as mock_urlopen, mock.patch(
            "builtins.input", side_effect=["1", "8", "exit"]
        ), mock.patch("sys.stdout", buffer):
            with self.assertRaises(SystemExit):
                cli.main()

        calls = mock_urlopen.call_args_list
        bootstrap_calls = [c for c in calls if c.args[0].full_url.rstrip("/") not in (
            f"http://127.0.0.1:8000/sessions/{session_id}/cerrar",
        ) and (
            c.args[0].full_url.endswith("/sessions")
            or c.args[0].full_url == "http://127.0.0.1:8000/pedidos"
            or c.args[0].full_url == f"http://127.0.0.1:8000/sessions/{session_id}/pedido"
        )]
        self.assertEqual(len(bootstrap_calls), 3)
        first_req = bootstrap_calls[0].args[0]
        self.assertTrue(first_req.full_url.endswith("/sessions"))
        self.assertEqual(first_req.method, "POST")
        self.assertEqual(
            json.loads(first_req.data.decode("utf-8")),
            {"id_comercio": 1, "id_cliente": 8},
        )

        second_req = bootstrap_calls[1].args[0]
        self.assertTrue(second_req.full_url.endswith("/pedidos"))
        self.assertEqual(second_req.method, "POST")
        self.assertEqual(
            json.loads(second_req.data.decode("utf-8")),
            {"id_session": session_id},
        )

        third_req = bootstrap_calls[2].args[0]
        self.assertTrue(
            third_req.full_url.endswith(f"/sessions/{session_id}/pedido")
        )
        self.assertEqual(third_req.method, "PUT")
        self.assertEqual(
            json.loads(third_req.data.decode("utf-8")),
            {"id_pedido": pedido_id},
        )

        printed = buffer.getvalue()
        self.assertIn(f"<session {session_id}>", printed)
        self.assertIn(f"<pedido {pedido_id}>", printed)


class CliBootstrapErrorHandlingTest(unittest.TestCase):
    def test_post_pedidos_failure_closes_session_and_exits_nonzero(self):
        cli = _import_cli()
        session_id = 321
        responses = [
            FakeResponse({"detail": "no active"}, status=404),
            FakeResponse({"id": session_id, "id_comercio": 1, "id_cliente": 8}, status=201),
            FakeResponse({"detail": "boom from pedidos"}, status=500),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        stderr = io.StringIO()
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ) as mock_urlopen, mock.patch(
            "builtins.input", side_effect=["1", "8"]
        ), mock.patch("sys.stderr", stderr):
            with self.assertRaises(SystemExit) as ctx:
                cli.main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("boom from pedidos", stderr.getvalue())
        calls = mock_urlopen.call_args_list
        close_calls = [c for c in calls if f"/sessions/{session_id}/cerrar" in c.args[0].full_url]
        self.assertEqual(len(close_calls), 1)

    def test_put_associate_pedido_failure_closes_session_and_exits_nonzero(self):
        cli = _import_cli()
        session_id = 654
        responses = [
            FakeResponse({"detail": "no active"}, status=404),
            FakeResponse({"id": session_id, "id_comercio": 1, "id_cliente": 8}, status=201),
            FakeResponse({"id": 987}, status=201),
            FakeResponse({"detail": "incompatible pedido"}, status=400),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        stderr = io.StringIO()
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ) as mock_urlopen, mock.patch(
            "builtins.input", side_effect=["1", "8"]
        ), mock.patch("sys.stderr", stderr):
            with self.assertRaises(SystemExit) as ctx:
                cli.main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("incompatible pedido", stderr.getvalue())
        calls = mock_urlopen.call_args_list
        close_calls = [c for c in calls if f"/sessions/{session_id}/cerrar" in c.args[0].full_url]
        self.assertEqual(len(close_calls), 1)


class CliBootstrapExistingActiveSessionTest(unittest.TestCase):
    def test_existing_active_session_is_closed_before_create(self):
        cli = _import_cli()
        existing_session_id = 999
        new_session_id = 42
        new_pedido_id = 77
        responses = _bootstrap_responses(
            session_id=new_session_id,
            pedido_id=new_pedido_id,
            existing_active_session_id=existing_session_id,
        ) + [
            FakeResponse({"id": new_session_id, "activa": False}, status=200),
        ]
        stderr = io.StringIO()
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ) as mock_urlopen, mock.patch(
            "builtins.input", side_effect=["1", "8", "exit"]
        ), mock.patch("sys.stderr", stderr):
            with self.assertRaises(SystemExit) as ctx:
                cli.main()

        self.assertEqual(ctx.exception.code, 0)
        self.assertIn(f"<closing existing session {existing_session_id}>", stderr.getvalue())

        calls = mock_urlopen.call_args_list
        urls = [c.args[0].full_url for c in calls]
        methods = [(c.args[0].full_url, c.args[0].method) for c in calls]
        get_activa_calls = [
            url for url in urls if url.endswith("/activa")
        ]
        self.assertEqual(len(get_activa_calls), 1)
        first_close = [
            c for c in calls
            if f"/sessions/{existing_session_id}/cerrar" in c.args[0].full_url
        ]
        self.assertEqual(len(first_close), 1)
        bootstrap_calls = [
            (url, method) for url, method in methods
            if url.endswith("/sessions") and method == "POST"
            or url.endswith("/pedidos")
            or (f"/sessions/{new_session_id}/pedido" in url and method == "PUT")
        ]
        self.assertEqual(len(bootstrap_calls), 3)
        exit_close = [
            c for c in calls
            if f"/sessions/{new_session_id}/cerrar" in c.args[0].full_url
        ]
        self.assertEqual(len(exit_close), 1)

    def test_no_active_session_skips_existing_close(self):
        cli = _import_cli()
        responses = _bootstrap_responses() + [
            FakeResponse({"id": 42, "activa": False}, status=200),
        ]
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ) as mock_urlopen, mock.patch(
            "builtins.input", side_effect=["1", "8", "exit"]
        ):
            with self.assertRaises(SystemExit):
                cli.main()

        calls = mock_urlopen.call_args_list
        urls = [c.args[0].full_url for c in calls]
        close_calls = [url for url in urls if "/cerrar" in url]
        self.assertEqual(len(close_calls), 1)
        self.assertTrue(close_calls[0].endswith("/sessions/42/cerrar"))


class CliCleanupTest(unittest.TestCase):
    def test_exit_handler_closes_only_session(self):
        cli = _import_cli()
        session_id = 202
        pedido_id = 303
        responses = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id) + [
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ) as mock_urlopen, mock.patch(
            "builtins.input", side_effect=["1", "8", "exit"]
        ):
            with self.assertRaises(SystemExit):
                cli.main()

        calls = mock_urlopen.call_args_list
        bootstrap_urls = {c.args[0].full_url for c in calls}
        pedido_post = "http://127.0.0.1:8000/pedidos"
        pedido_put = f"http://127.0.0.1:8000/sessions/{session_id}/pedido"
        session_post = "http://127.0.0.1:8000/sessions"
        close = f"http://127.0.0.1:8000/sessions/{session_id}/cerrar"
        self.assertIn(pedido_post, bootstrap_urls)
        self.assertIn(pedido_put, bootstrap_urls)
        self.assertIn(session_post, bootstrap_urls)
        self.assertIn(close, bootstrap_urls)
        self.assertEqual(sum(1 for c in calls if c.args[0].full_url == close), 1)
        self.assertEqual(sum(1 for c in calls if c.args[0].full_url == pedido_post), 1)
        self.assertEqual(sum(1 for c in calls if c.args[0].full_url == pedido_put), 1)


def _detalle_url(pedido_id):
    return f"http://127.0.0.1:8000/pedidos/{pedido_id}/detalle"


def _linea_dict(cantidad, producto, presentacion):
    return {
        "cantidad": cantidad,
        "producto_nombre": producto,
        "presentacion_descripcion": presentacion,
    }


class CliPedidoTableTest(unittest.TestCase):
    def test_agregar_producto_executed_triggers_one_detail_retrieval(self):
        cli = _import_cli()
        session_id, pedido_id = 42, 77
        bootstrap = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id)
        detalle_body = {"lineas": [_linea_dict(2, "Pizza de Muzzarella", "Grande")]}
        responses = bootstrap + [
            FakeResponse(
                {"responses": [{"intent": "agregar_producto", "status": "executed", "message": "Listo"}]},
                status=200,
            ),
            FakeResponse(detalle_body, status=200),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        buffer = io.StringIO()
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ) as mock_urlopen, mock.patch(
            "builtins.input", side_effect=["1", "8", "quiero 2 pizzas", "exit"]
        ), mock.patch("sys.stdout", buffer):
            with self.assertRaises(SystemExit):
                cli.main()
        detalle_calls = [c for c in mock_urlopen.call_args_list
                        if c.args[0].full_url == _detalle_url(pedido_id)]
        self.assertEqual(len(detalle_calls), 1)
        self.assertEqual(detalle_calls[0].args[0].method, "GET")

    def test_quitar_producto_executed_triggers_one_detail_retrieval(self):
        cli = _import_cli()
        session_id, pedido_id = 11, 22
        bootstrap = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id)
        detalle_body = {"lineas": [_linea_dict(1, "Pizza de Muzzarella", "Grande")]}
        responses = bootstrap + [
            FakeResponse(
                {"responses": [{"intent": "quitar_producto", "status": "executed", "message": "Ok"}]},
                status=200,
            ),
            FakeResponse(detalle_body, status=200),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ) as mock_urlopen, mock.patch(
            "builtins.input", side_effect=["1", "8", "sacate 1 pizza", "exit"]
        ):
            with self.assertRaises(SystemExit):
                cli.main()
        detalle_calls = [c for c in mock_urlopen.call_args_list
                        if c.args[0].full_url == _detalle_url(pedido_id)]
        self.assertEqual(len(detalle_calls), 1)
        self.assertEqual(detalle_calls[0].args[0].method, "GET")

    def test_non_mutation_responses_trigger_zero_detail_retrievals(self):
        cli = _import_cli()
        session_id, pedido_id = 9, 33
        bootstrap = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id)
        cases = [
            {"intent": "agregar_producto", "status": "pending_resolution", "message": "?"},
            {"intent": "quitar_producto", "status": "rejected", "message": "no"},
            {"intent": "agregar_producto", "status": "failed", "message": "boom"},
            {"intent": "saludo", "status": "rejected", "message": "Hola"},
        ]
        responses = bootstrap + [
            FakeResponse({"responses": [cases[0]]}, status=200),
            FakeResponse({"responses": [cases[1]]}, status=200),
            FakeResponse({"responses": [cases[2]]}, status=200),
            FakeResponse({"responses": [cases[3]]}, status=200),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ) as mock_urlopen, mock.patch(
            "builtins.input", side_effect=["1", "8", "a", "b", "c", "d", "exit"]
        ):
            with self.assertRaises(SystemExit):
                cli.main()
        detalle_calls = [c for c in mock_urlopen.call_args_list
                        if c.args[0].full_url == _detalle_url(pedido_id)]
        self.assertEqual(len(detalle_calls), 0)

    def test_multiple_executed_mutations_trigger_one_detail_retrieval(self):
        cli = _import_cli()
        session_id, pedido_id = 7, 99
        bootstrap = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id)
        detalle_body = {"lineas": [_linea_dict(1, "X", "Y")]}
        responses = bootstrap + [
            FakeResponse(
                {
                    "responses": [
                        {"intent": "agregar_producto", "status": "executed", "message": "Add"},
                        {"intent": "quitar_producto", "status": "executed", "message": "Sub"},
                    ]
                },
                status=200,
            ),
            FakeResponse(detalle_body, status=200),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ) as mock_urlopen, mock.patch(
            "builtins.input", side_effect=["1", "8", "haz cosas", "exit"]
        ):
            with self.assertRaises(SystemExit):
                cli.main()
        detalle_calls = [c for c in mock_urlopen.call_args_list
                        if c.args[0].full_url == _detalle_url(pedido_id)]
        self.assertEqual(len(detalle_calls), 1)

    def test_customer_responses_printed_before_table(self):
        cli = _import_cli()
        session_id, pedido_id = 6, 12
        bootstrap = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id)
        detalle_body = {"lineas": [_linea_dict(2, "Pizza", "Grande")]}
        responses = bootstrap + [
            FakeResponse(
                {"responses": [{"intent": "agregar_producto", "status": "executed", "message": "Listo"}]},
                status=200,
            ),
            FakeResponse(detalle_body, status=200),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        buffer = io.StringIO()
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ), mock.patch(
            "builtins.input", side_effect=["1", "8", "x", "exit"]
        ), mock.patch("sys.stdout", buffer):
            with self.assertRaises(SystemExit):
                cli.main()
        out = buffer.getvalue()
        message_idx = out.find("<- message=Listo")
        table_idx = out.find("Pedido actual:")
        self.assertNotEqual(message_idx, -1)
        self.assertNotEqual(table_idx, -1)
        self.assertLess(message_idx, table_idx)

    def test_table_contains_required_columns(self):
        cli = _import_cli()
        table = cli.format_order_table([
            _linea_dict(1, "Pizza de Muzzarella", "Grande"),
            _linea_dict(3, "Empanada de Carne", "Unidad"),
        ])
        self.assertIn("Producto", table)
        self.assertIn("Presentación", table)
        self.assertIn("Cantidad", table)
        self.assertIn("Pizza de Muzzarella", table)
        self.assertIn("Empanada de Carne", table)
        self.assertIn("Grande", table)
        self.assertIn("Unidad", table)

    def test_table_does_not_expose_database_ids(self):
        cli = _import_cli()
        session_id, pedido_id = 5, 10
        bootstrap = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id)
        detalle_body = {
            "id": pedido_id,
            "id_session": session_id,
            "id_medio_pago": None,
            "id_metodo_entrega": None,
            "lineas": [_linea_dict(1, "Pizza", "Grande")],
        }
        responses = bootstrap + [
            FakeResponse(
                {"responses": [{"intent": "agregar_producto", "status": "executed", "message": "ok"}]},
                status=200,
            ),
            FakeResponse(detalle_body, status=200),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        buffer = io.StringIO()
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ) as mock_urlopen, mock.patch(
            "builtins.input", side_effect=["1", "8", "x", "exit"]
        ), mock.patch("sys.stdout", buffer):
            with self.assertRaises(SystemExit):
                cli.main()
        detalle_calls = [c for c in mock_urlopen.call_args_list
                        if c.args[0].full_url == _detalle_url(pedido_id)]
        self.assertEqual(len(detalle_calls), 1)
        self.assertEqual(detalle_calls[0].args[0].method, "GET")
        out = buffer.getvalue()
        table_segment = out[out.find("Pedido actual:"):]
        for forbidden in ("id_session", "id_pedido", "id_producto", "id_presentacion", "id_comercio"):
            self.assertNotIn(forbidden, table_segment)


class CliPedidoTableHelpersTest(unittest.TestCase):
    def test_response_modified_order_true_for_executed_mutation(self):
        cli = _import_cli()
        self.assertTrue(cli.response_modified_order([
            {"intent": "agregar_producto", "status": "executed", "message": "ok"}
        ]))
        self.assertTrue(cli.response_modified_order([
            {"intent": "quitar_producto", "status": "executed", "message": "ok"}
        ]))

    def test_response_modified_order_false_for_rejected(self):
        cli = _import_cli()
        self.assertFalse(cli.response_modified_order([
            {"intent": "agregar_producto", "status": "rejected", "message": "no"}
        ]))
        self.assertFalse(cli.response_modified_order([
            {"intent": "quitar_producto", "status": "rejected", "message": "no"}
        ]))

    def test_response_modified_order_false_for_pending_resolution(self):
        cli = _import_cli()
        self.assertFalse(cli.response_modified_order([
            {"intent": "agregar_producto", "status": "pending_resolution", "message": "?"}
        ]))

    def test_response_modified_order_false_for_failed(self):
        cli = _import_cli()
        self.assertFalse(cli.response_modified_order([
            {"intent": "agregar_producto", "status": "failed", "message": "x"}
        ]))

    def test_response_modified_order_false_for_conversational(self):
        cli = _import_cli()
        self.assertFalse(cli.response_modified_order([
            {"intent": "saludo", "status": "executed", "message": "hola"}
        ]))

    def test_response_modified_order_false_for_unknown_intent(self):
        cli = _import_cli()
        self.assertFalse(cli.response_modified_order([
            {"intent": "consultar_producto", "status": "executed", "message": "x"}
        ]))

    def test_response_modified_order_false_for_empty_responses(self):
        cli = _import_cli()
        self.assertFalse(cli.response_modified_order([]))

    def test_response_modified_order_false_for_non_dict_responses(self):
        cli = _import_cli()
        self.assertFalse(cli.response_modified_order([None, "x", 1]))
        self.assertFalse(cli.response_modified_order([{"intent": None, "status": "executed"}]))

    def test_format_order_table_empty_returns_vacio(self):
        cli = _import_cli()
        self.assertEqual(cli.format_order_table([]), "Pedido actual: vacío\n")

    def test_format_order_table_single_row_contains_columns_and_values(self):
        cli = _import_cli()
        out = cli.format_order_table([_linea_dict(2, "Pizza", "Grande")])
        self.assertIn("Producto", out)
        self.assertIn("Presentación", out)
        self.assertIn("Cantidad", out)
        self.assertIn("Pizza", out)
        self.assertIn("Grande", out)
        self.assertIn("2", out)

    def test_format_order_table_adapts_to_long_names(self):
        cli = _import_cli()
        out = cli.format_order_table([
            _linea_dict(1, "Pizza de Muzzarella con Rucula y Tomate", "Extra Grande")
        ])
        self.assertIn("Pizza de Muzzarella con Rucula y Tomate", out)
        self.assertIn("Extra Grande", out)
        self.assertIn("+", out)

    def test_format_order_table_falls_back_to_em_dash_for_missing_presentation(self):
        cli = _import_cli()
        out = cli.format_order_table([
            _linea_dict(1, "Pizza", None),
            _linea_dict(1, "Pizza", ""),
        ])
        self.assertIn("—", out)

    def test_format_order_table_renders_integer_quantity(self):
        cli = _import_cli()
        out = cli.format_order_table([_linea_dict(7, "X", "Y")])
        self.assertIn("7", out)
        self.assertNotIn("7.0", out)


class CliDetailRetrievalFailureTest(unittest.TestCase):
    def test_detail_retrieval_failure_prints_warning_and_continues_loop(self):
        cli = _import_cli()
        session_id, pedido_id = 3, 8
        bootstrap = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id)
        responses = bootstrap + [
            FakeResponse(
                {"responses": [{"intent": "agregar_producto", "status": "executed", "message": "ok"}]},
                status=200,
            ),
            FakeResponse({"detail": "boom"}, status=500),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        buffer = io.StringIO()
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ), mock.patch(
            "builtins.input", side_effect=["1", "8", "x", "y", "exit"]
        ), mock.patch("sys.stdout", buffer):
            with self.assertRaises(SystemExit) as ctx:
                cli.main()
        self.assertEqual(ctx.exception.code, 0)
        out = buffer.getvalue()
        self.assertIn("<- message=ok", out)
        self.assertEqual(
            out.count("Warning: the order was modified, but its updated detail could not be retrieved."),
            1,
        )


class CliDebugFlowTest(unittest.TestCase):
    def _diagnostics_response(self, pedido_id):
        return {
            "responses": [
                {
                    "intent": "agregar_producto",
                    "status": "executed",
                    "message": "Listo",
                }
            ],
            "diagnostics": [
                {
                    "call_id": "CLS-001",
                    "turn_id": 1,
                    "phase": "classifier",
                    "method": "query",
                    "raw_message": "quiero una empanada",
                    "active_context_type": None,
                    "has_active_pending_intent": False,
                    "active_pending_intent": None,
                    "queued_intent_count": 0,
                    "classifier_class": "IntentClassifier",
                    "classifier_method": "query",
                    "prompt_name": "intent_classification",
                    "model": "test-model",
                },
                {
                    "call_id": "CLS-001",
                    "turn_id": 1,
                    "phase": "classifier",
                    "method": "emit_completed",
                    "result": {
                        "intents": [
                            {"intent": "agregar_producto", "mensaje": "una empanada"}
                        ],
                        "mensaje": "quiero una empanada",
                    },
                    "intent_count": 1,
                    "parse_errors": [],
                },
            ],
        }

    def test_debug_flow_flag_disabled_keeps_default_output(self):
        cli = _import_cli()
        session_id, pedido_id = 11, 22
        bootstrap = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id)
        responses = bootstrap + [
            FakeResponse(
                {
                    "responses": [
                        {
                            "intent": "agregar_producto",
                            "status": "executed",
                            "message": "ok",
                        }
                    ]
                },
                status=200,
            ),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        buffer = io.StringIO()
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ) as mock_urlopen, mock.patch(
            "builtins.input", side_effect=["1", "8", "agregar", "exit"]
        ), mock.patch("sys.stdout", buffer):
            with self.assertRaises(SystemExit):
                cli.main()
        out = buffer.getvalue()
        self.assertNotIn("CLASSIFIER INPUT", out)
        self.assertNotIn("RESOLVER INPUT", out)
        msg_calls = [
            c
            for c in mock_urlopen.call_args_list
            if "/incoming-messages" in c.args[0].full_url
        ]
        self.assertGreaterEqual(len(msg_calls), 1)
        headers = msg_calls[0].args[0].headers
        self.assertNotIn("X-debug-flow", headers)
        self.assertNotIn("X-Debug-Flow", headers)

    def test_debug_flow_flag_enabled_sends_header_and_renders_tables(self):
        cli = _import_cli()
        session_id, pedido_id = 12, 23
        bootstrap = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id)
        responses = bootstrap + [
            FakeResponse(self._diagnostics_response(pedido_id), status=200),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        buffer = io.StringIO()
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ) as mock_urlopen, mock.patch(
            "sys.argv", ["cli_chat_client", "--debug-flow"]
        ), mock.patch(
            "builtins.input", side_effect=["1", "8", "agregar", "exit"]
        ), mock.patch("sys.stdout", buffer):
            with self.assertRaises(SystemExit):
                cli.main()
        out = buffer.getvalue()
        msg_calls = [
            c
            for c in mock_urlopen.call_args_list
            if "/incoming-messages" in c.args[0].full_url
        ]
        self.assertGreaterEqual(len(msg_calls), 1)
        headers = msg_calls[0].args[0].headers
        header_value = headers.get("X-debug-flow")
        if header_value is None:
            header_value = headers.get("X-Debug-Flow")
        self.assertEqual(header_value, "1")
        message_idx = out.find("<- message=Listo")
        classifier_input_idx = out.find("CLASSIFIER INPUT")
        classifier_output_idx = out.find("CLASSIFIER OUTPUT")
        self.assertNotEqual(message_idx, -1)
        self.assertNotEqual(classifier_input_idx, -1)
        self.assertNotEqual(classifier_output_idx, -1)
        self.assertLess(message_idx, classifier_input_idx)
        self.assertLess(classifier_input_idx, classifier_output_idx)

    def test_debug_components_filter_limits_output(self):
        cli = _import_cli()
        session_id, pedido_id = 13, 24
        bootstrap = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id)
        responses = bootstrap + [
            FakeResponse(
                {
                    "responses": [
                        {
                            "intent": "agregar_producto",
                            "status": "executed",
                            "message": "ok",
                        }
                    ],
                    "diagnostics": [
                        {
                            "call_id": "CLS-001",
                            "turn_id": 1,
                            "phase": "classifier",
                            "method": "query",
                            "raw_message": "x",
                        },
                        {
                            "call_id": "RES-001",
                            "turn_id": 1,
                            "phase": "resolver",
                            "method": "resolve",
                            "incoming_text": "x",
                        },
                    ],
                },
                status=200,
            ),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        buffer = io.StringIO()
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ), mock.patch(
            "sys.argv", ["cli_chat_client", "--debug-flow", "--debug-components", "classifier"]
        ), mock.patch(
            "builtins.input", side_effect=["1", "8", "x", "exit"]
        ), mock.patch("sys.stdout", buffer):
            with self.assertRaises(SystemExit):
                cli.main()
        out = buffer.getvalue()
        self.assertIn("CLASSIFIER INPUT", out)
        self.assertNotIn("RESOLVER INPUT", out)

    def test_debug_components_unknown_value_exits_with_error(self):
        cli = _import_cli()
        stderr = io.StringIO()
        with mock.patch(
            "sys.argv", ["cli_chat_client", "--debug-flow", "--debug-components", "foo"]
        ), mock.patch("builtins.input", side_effect=["1", "8"]), mock.patch(
            "sys.stderr", stderr
        ):
            with self.assertRaises(SystemExit) as ctx:
                cli.main()
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("foo", stderr.getvalue())

    def test_debug_flow_redacts_secret_fields(self):
        cli = _import_cli()
        session_id, pedido_id = 14, 25
        bootstrap = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id)
        secret_payload = {
            "responses": [
                {
                    "intent": "agregar_producto",
                    "status": "executed",
                    "message": "ok",
                }
            ],
            "diagnostics": [
                {
                    "call_id": "CLS-001",
                    "turn_id": 1,
                    "phase": "classifier",
                    "method": "query",
                    "raw_message": "x",
                    "password": "super-secret",
                }
            ],
        }
        responses = bootstrap + [
            FakeResponse(secret_payload, status=200),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        buffer = io.StringIO()
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ), mock.patch(
            "sys.argv", ["cli_chat_client", "--debug-flow"]
        ), mock.patch(
            "builtins.input", side_effect=["1", "8", "x", "exit"]
        ), mock.patch("sys.stdout", buffer):
            with self.assertRaises(SystemExit):
                cli.main()
        out = buffer.getvalue()
        self.assertIn("<redacted>", out)
        self.assertNotIn("super-secret", out)

    def test_debug_flow_renders_classifier_output_with_multiple_intents(self):
        cli = _import_cli()
        session_id, pedido_id = 15, 26
        bootstrap = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id)
        payload = {
            "responses": [
                {
                    "intent": "agregar_producto",
                    "status": "executed",
                    "message": "ok",
                }
            ],
            "diagnostics": [
                {
                    "call_id": "CLS-001",
                    "turn_id": 1,
                    "phase": "classifier",
                    "method": "emit_completed",
                    "result": {
                        "intents": [
                            {
                                "intent": "agregar_producto",
                                "mensaje": "empanada de carne",
                                "quantity": 1,
                                "confidence": 0.9,
                                "status": "ready",
                                "resolved_data": {"cantidad": 1},
                                "requirements": [],
                                "candidate_ids": [11],
                            },
                            {
                                "intent": "agregar_producto",
                                "mensaje": "pizza de muzarella",
                                "quantity": 1,
                                "confidence": 0.8,
                                "status": "pending_resolution",
                                "resolved_data": {"cantidad": 1},
                                "requirements": [],
                                "candidate_ids": [21, 22],
                            },
                        ]
                    },
                }
            ],
        }
        responses = bootstrap + [
            FakeResponse(payload, status=200),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        buffer = io.StringIO()
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ), mock.patch(
            "sys.argv", ["cli_chat_client", "--debug-flow"]
        ), mock.patch(
            "builtins.input", side_effect=["1", "8", "x", "exit"]
        ), mock.patch("sys.stdout", buffer):
            with self.assertRaises(SystemExit):
                cli.main()
        out = buffer.getvalue()
        self.assertIn("empanada de carne", out)
        self.assertIn("pizza de muzarella", out)
        first = out.find("empanada de carne")
        second = out.find("pizza de muzarella")
        self.assertLess(first, second)

    def test_debug_flow_renders_resolver_candidates_table(self):
        cli = _import_cli()
        session_id, pedido_id = 16, 27
        bootstrap = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id)
        payload = {
            "responses": [
                {
                    "intent": "agregar_producto",
                    "status": "executed",
                    "message": "ok",
                }
            ],
            "diagnostics": [
                {
                    "call_id": "RES-001",
                    "turn_id": 1,
                    "phase": "resolver",
                    "method": "resolve",
                    "candidate_catalog": [
                        {
                            "producto_presentacion_id": 1,
                            "producto_id": 1,
                            "producto_nombre": "Empanada de Carne",
                            "presentacion_id": 1,
                            "presentacion_codigo": "PICANTE",
                            "presentacion_descripcion": "Picante",
                            "categoria_id": 1,
                            "categoria_nombre": "Empanadas",
                            "activo": True,
                            "disponible": True,
                        },
                        {
                            "producto_presentacion_id": 2,
                            "producto_id": 1,
                            "producto_nombre": "Empanada de Carne",
                            "presentacion_id": 2,
                            "presentacion_codigo": "TRADICIONAL",
                            "presentacion_descripcion": "Tradicional",
                            "categoria_id": 1,
                            "categoria_nombre": "Empanadas",
                            "activo": True,
                            "disponible": True,
                        },
                        {
                            "producto_presentacion_id": 3,
                            "producto_id": 1,
                            "producto_nombre": "Empanada de Carne",
                            "presentacion_id": 3,
                            "presentacion_codigo": "GRANDE",
                            "presentacion_descripcion": "Grande",
                            "categoria_id": 1,
                            "categoria_nombre": "Empanadas",
                            "activo": True,
                            "disponible": True,
                        },
                    ],
                }
            ],
        }
        responses = bootstrap + [
            FakeResponse(payload, status=200),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        buffer = io.StringIO()
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ), mock.patch(
            "sys.argv", ["cli_chat_client", "--debug-flow"]
        ), mock.patch(
            "builtins.input", side_effect=["1", "8", "x", "exit"]
        ), mock.patch("sys.stdout", buffer):
            with self.assertRaises(SystemExit):
                cli.main()
        out = buffer.getvalue()
        self.assertIn("RESOLVER CANDIDATES", out)
        self.assertIn("PICANTE", out)
        self.assertIn("TRADICIONAL", out)
        self.assertIn("GRANDE", out)
        self.assertEqual(out.count("Empanada de Carne"), 3)

    def test_debug_flow_renders_pending_state_snapshot(self):
        cli = _import_cli()
        session_id, pedido_id = 17, 28
        bootstrap = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id)
        payload = {
            "responses": [
                {
                    "intent": "agregar_producto",
                    "status": "executed",
                    "message": "ok",
                }
            ],
            "diagnostics": [
                {
                    "call_id": "PEND-001",
                    "turn_id": 1,
                    "phase": "pending",
                    "snapshot_phase": "before_resolver",
                    "active_intent": "agregar_producto",
                    "active_status": "pending_resolution",
                    "active_source_text": "una pizza",
                    "active_quantity": 1,
                    "active_candidate_ids": [12, 13, 14],
                    "queue_length": 1,
                    "queue_intents": ["agregar_producto"],
                    "queue_sources": ["una empanada de carne"],
                    "context_type": "product_selection",
                }
            ],
        }
        responses = bootstrap + [
            FakeResponse(payload, status=200),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        buffer = io.StringIO()
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ), mock.patch(
            "sys.argv", ["cli_chat_client", "--debug-flow"]
        ), mock.patch(
            "builtins.input", side_effect=["1", "8", "x", "exit"]
        ), mock.patch("sys.stdout", buffer):
            with self.assertRaises(SystemExit):
                cli.main()
        out = buffer.getvalue()
        self.assertIn("PENDING STATE", out)
        self.assertIn("agregar_producto", out)
        self.assertIn("pending_resolution", out)
        self.assertIn("product_selection", out)

    def test_debug_flow_renders_pending_queue_table(self):
        cli = _import_cli()
        session_id, pedido_id = 18, 29
        bootstrap = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id)
        payload = {
            "responses": [
                {
                    "intent": "agregar_producto",
                    "status": "executed",
                    "message": "ok",
                }
            ],
            "diagnostics": [
                {
                    "call_id": "PEND-001",
                    "turn_id": 1,
                    "phase": "pending",
                    "snapshot_phase": "after_resolver",
                    "active_intent": "agregar_producto",
                    "queue_length": 2,
                    "queue_intents": [
                        "agregar_producto",
                        "agregar_producto",
                    ],
                    "queue_sources": [
                        "una empanada de carne",
                        "una pizza",
                    ],
                }
            ],
        }
        responses = bootstrap + [
            FakeResponse(payload, status=200),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        buffer = io.StringIO()
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ), mock.patch(
            "sys.argv", ["cli_chat_client", "--debug-flow"]
        ), mock.patch(
            "builtins.input", side_effect=["1", "8", "x", "exit"]
        ), mock.patch("sys.stdout", buffer):
            with self.assertRaises(SystemExit):
                cli.main()
        out = buffer.getvalue()
        self.assertIn("PENDING QUEUE", out)
        first = out.find("una empanada de carne")
        second = out.find("una pizza")
        self.assertNotEqual(first, -1)
        self.assertNotEqual(second, -1)
        self.assertLess(first, second)

    def test_debug_flow_renders_resolver_matches_table(self):
        cli = _import_cli()
        session_id, pedido_id = 19, 30
        bootstrap = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id)
        payload = {
            "responses": [
                {
                    "intent": "agregar_producto",
                    "status": "executed",
                    "message": "ok",
                }
            ],
            "diagnostics": [
                {
                    "call_id": "RES-001",
                    "turn_id": 1,
                    "phase": "resolver",
                    "method": "emit_completed",
                    "matches": [
                        {
                            "candidate_id": 11,
                            "candidate": "Empanada Picante",
                            "score": 0.92,
                            "match_type": "exact",
                            "matched_text": "picante",
                            "accepted": True,
                        },
                        {
                            "candidate_id": 12,
                            "candidate": "Empanada Tradicional",
                            "score": 0.4,
                            "match_type": "partial",
                            "matched_text": "carne",
                            "accepted": False,
                        },
                        {
                            "candidate_id": 13,
                            "candidate": "Empanada Especial",
                            "score": 0.3,
                            "match_type": "partial",
                            "matched_text": "carne",
                            "accepted": False,
                        },
                    ],
                }
            ],
        }
        responses = bootstrap + [
            FakeResponse(payload, status=200),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        buffer = io.StringIO()
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ), mock.patch(
            "sys.argv", ["cli_chat_client", "--debug-flow"]
        ), mock.patch(
            "builtins.input", side_effect=["1", "8", "x", "exit"]
        ), mock.patch("sys.stdout", buffer):
            with self.assertRaises(SystemExit):
                cli.main()
        out = buffer.getvalue()
        self.assertIn("RESOLVER MATCHES", out)
        self.assertIn("Empanada Picante", out)
        self.assertIn("Empanada Tradicional", out)
        self.assertIn("Empanada Especial", out)

    def test_debug_flow_call_id_correlation(self):
        cli = _import_cli()
        session_id, pedido_id = 20, 31
        bootstrap = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id)
        payload = {
            "responses": [
                {
                    "intent": "agregar_producto",
                    "status": "executed",
                    "message": "ok",
                }
            ],
            "diagnostics": [
                {
                    "call_id": "RES-001",
                    "turn_id": 1,
                    "phase": "resolver",
                    "method": "resolve",
                    "incoming_text": "picante",
                },
                {
                    "call_id": "RES-001",
                    "turn_id": 1,
                    "phase": "resolver",
                    "method": "emit_completed",
                    "status_after": "ready",
                },
            ],
        }
        responses = bootstrap + [
            FakeResponse(payload, status=200),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        buffer = io.StringIO()
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ), mock.patch(
            "sys.argv", ["cli_chat_client", "--debug-flow"]
        ), mock.patch(
            "builtins.input", side_effect=["1", "8", "x", "exit"]
        ), mock.patch("sys.stdout", buffer):
            with self.assertRaises(SystemExit):
                cli.main()
        out = buffer.getvalue()
        self.assertEqual(out.count("RES-001"), 4)

    def test_debug_flow_unicode_preserved(self):
        cli = _import_cli()
        session_id, pedido_id = 21, 32
        bootstrap = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id)
        payload = {
            "responses": [
                {
                    "intent": "agregar_producto",
                    "status": "executed",
                    "message": "ok",
                }
            ],
            "diagnostics": [
                {
                    "call_id": "CLS-001",
                    "turn_id": 1,
                    "phase": "classifier",
                    "method": "emit_completed",
                    "result": {
                        "intents": [
                            {
                                "intent": "agregar_producto",
                                "mensaje": "Empanada de Jamón y Queso",
                            },
                            {
                                "intent": "agregar_producto",
                                "mensaje": "Pizza de Muzzarella",
                            },
                        ]
                    },
                }
            ],
        }
        responses = bootstrap + [
            FakeResponse(payload, status=200),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        buffer = io.StringIO()
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ), mock.patch(
            "sys.argv", ["cli_chat_client", "--debug-flow"]
        ), mock.patch(
            "builtins.input", side_effect=["1", "8", "x", "exit"]
        ), mock.patch("sys.stdout", buffer):
            with self.assertRaises(SystemExit):
                cli.main()
        out = buffer.getvalue()
        self.assertIn("Empanada de Jamón y Queso", out)
        self.assertIn("Pizza de Muzzarella", out)
        self.assertNotIn("\\u00f3", out)
        self.assertNotIn("\\u00f1", out)

    def test_debug_flow_error_path_prints_error_table(self):
        cli = _import_cli()
        session_id, pedido_id = 22, 33
        bootstrap = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id)
        payload = {
            "responses": [
                {
                    "intent": "agregar_producto",
                    "status": "executed",
                    "message": "ok",
                }
            ],
            "diagnostics": [
                {
                    "call_id": "CLS-001",
                    "turn_id": 1,
                    "phase": "classifier",
                    "method": "emit_completed",
                    "result": None,
                    "result_type": "ClassifierError",
                    "parse_errors": ["ValueError"],
                }
            ],
        }
        responses = bootstrap + [
            FakeResponse(payload, status=200),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        buffer = io.StringIO()
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ), mock.patch(
            "sys.argv", ["cli_chat_client", "--debug-flow"]
        ), mock.patch(
            "builtins.input", side_effect=["1", "8", "x", "exit"]
        ), mock.patch("sys.stdout", buffer):
            with self.assertRaises(SystemExit):
                cli.main()
        out = buffer.getvalue()
        self.assertIn("CLASSIFIER OUTPUT", out)
        self.assertIn("ClassifierError", out)

    def test_debug_flow_no_duplicate_classifier_or_resolver_calls(self):
        cli = _import_cli()
        session_id, pedido_id = 23, 34
        bootstrap = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id)
        responses = bootstrap + [
            FakeResponse(self._diagnostics_response(pedido_id), status=200),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        buffer = io.StringIO()
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ) as mock_urlopen, mock.patch(
            "sys.argv", ["cli_chat_client", "--debug-flow", "--debug-flow"]
        ), mock.patch(
            "builtins.input", side_effect=["1", "8", "x", "exit"]
        ), mock.patch("sys.stdout", buffer):
            with self.assertRaises(SystemExit):
                cli.main()
        out = buffer.getvalue()
        msg_calls = [
            c
            for c in mock_urlopen.call_args_list
            if "/incoming-messages" in c.args[0].full_url
        ]
        self.assertEqual(len(msg_calls), 1)
        headers = msg_calls[0].args[0].headers
        header_value = headers.get("X-debug-flow")
        if header_value is None:
            header_value = headers.get("X-Debug-Flow")
        self.assertEqual(header_value, "1")
        diagnostics_table_count = out.count("[CLS-001]")
        self.assertEqual(diagnostics_table_count, 2)

    def test_debug_flow_does_not_affect_existing_business_flow(self):
        cli = _import_cli()
        session_id, pedido_id = 24, 35
        bootstrap = _bootstrap_responses(session_id=session_id, pedido_id=pedido_id)
        detalle_body = {"lineas": [_linea_dict(2, "Pizza", "Grande")]}
        payload = dict(self._diagnostics_response(pedido_id))
        payload["responses"] = [
            {
                "intent": "agregar_producto",
                "status": "executed",
                "message": "Listo",
            }
        ]
        responses = bootstrap + [
            FakeResponse(payload, status=200),
            FakeResponse(detalle_body, status=200),
            FakeResponse({"id": session_id, "activa": False}, status=200),
        ]
        buffer = io.StringIO()
        with mock.patch.object(
            cli.urllib.request, "urlopen", side_effect=_fake_urlopen(responses)
        ) as mock_urlopen, mock.patch(
            "sys.argv", ["cli_chat_client", "--debug-flow"]
        ), mock.patch(
            "builtins.input", side_effect=["1", "8", "x", "exit"]
        ), mock.patch("sys.stdout", buffer):
            with self.assertRaises(SystemExit):
                cli.main()
        detalle_calls = [
            c
            for c in mock_urlopen.call_args_list
            if c.args[0].full_url == _detalle_url(pedido_id)
        ]
        self.assertEqual(len(detalle_calls), 1)
        out = buffer.getvalue()
        self.assertIn("Pedido actual:", out)
        diagnostics_idx = out.find("CLASSIFIER INPUT")
        table_idx = out.find("Pedido actual:")
        self.assertLess(diagnostics_idx, table_idx)


if __name__ == "__main__":
    unittest.main()
