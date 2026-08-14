"""Regression coverage for the sequential add-quantity round-trip
through the real pilot local-test channel.

This module is the focused regression test required by tasks 5.1, 5.3
and 5.4 of the OpenSpec amendment "Sequential add quantity regression
amendment" (``openspec/changes/fix-pilot-product-add-execution``).

The test exercises the *real* operator channel documented in the
amendment, not the isolated handler seam:

``POST /admin/pilot/orders/{pedido_id}/local-test`` (HTTP Basic +
``X-Local-Test-Origin: same-origin``)
  → :func:`local_test_message` in :mod:`backend.routers.admin_pilot_orders`
  → :func:`process_incoming_message_with_responses`
  → :func:`process_incoming_message_transactional`  (transactional owner;
    commits once per turn, rolls back on technical failure)
  → :func:`process_incoming_message`
  → :func:`dispatch_initial_message` (real, no pending context)
  → :class:`IntentClassifier`  (LLM boundary — mocked locally for
    determinism, NOT for hiding a defect)
  → :func:`detectar_productos` / product recognizer
    (mocked locally to pin exactly one priced presentation per turn,
    NOT to hide a defect — the function still returns one valid
    ``encontrados`` entry and the downstream resolver / orchestrator
    / processor run unchanged)
  → :func:`process_initial_agregar_producto`
  → :func:`execute_agregar_producto` (real handler)
  → :func:`PedidoProductoService.stage_add_or_increment_for_session`
    (real seam, no transaction ownership)
  → :class:`PedidoProductoRepository`  (real, no transaction ownership)
  → PostgreSQL ``supernova_test`` via SQLAlchemy  (real persistence,
    the real outer commit from the transactional processor)
  → :func:`build_customer_responses` (real response mapper)
  → :func:`_reload_exact_session_for_snapshot` (real)
  → :class:`PilotOrderOperationsViewService.get_order_lines_snapshot`
    (real snapshot)
  → typed ``LocalTestResponse`` JSON  (real Pydantic schema + ``extra='forbid'``)
  → JSDOM-backed panel render  (the same helper that drives the
    existing ``base.html`` debug script via the documented
    ``__panelDebugLines.updateOrderLines`` hook)

The scenario covers the exact ``1 → 2 → 3`` customer sequence for
one active Session, its own ``BORRADOR`` Pedido and one priced
``ProductoPresentacion``. The assertions pin:

* HTTP 200 on every POST;
* exactly one executed ``responses[0]`` per turn, with the
  CustomerResponse ``message`` carrying the durable final total
  ``1``, ``3``, ``6`` (not the requested delta ``1``, ``2``, ``3``);
* exactly one ``order_lines`` entry per turn with ``cantidad``
  ``1``, ``3``, ``6`` — never derived from the response text;
* after the third turn, a fresh read of ``PedidoProducto.cantidad``
  from a new SQLAlchemy session returns ``6``;
* the JSDOM-rendered panel table places a ``<tr>`` whose fourth
  cell (``cantidad``) textContent is ``"6"`` after the same
  payload is applied to ``updateOrderLines``.
"""
from __future__ import annotations

import base64
import json
import subprocess
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

import backend.dependencies as dependencies_module
from backend.config import settings as settings_module
from backend.config.settings import Settings
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
TestingSessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False
)


def _override_session():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


_MISSING_OVERRIDE = object()


CONFIGURED_TOKEN = "pilot-panel-token-for-sequential-route-test"


def _settings_with_admin_token() -> Settings:
    base = settings_module.load_settings()
    return Settings(
        **{**base.__dict__, "order_management_admin_token": CONFIGURED_TOKEN}
    )


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    raw = f"{username}:{password}".encode()
    encoded = base64.b64encode(raw).decode("ascii")
    return {"Authorization": f"Basic {encoded}"}


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _estado_id_activo() -> int:
    with engine.connect() as c:
        row = c.execute(
            select(EstadoComercio.id).where(EstadoComercio.estado == "ACTIVO")
        ).first()
        if row is None:
            raise RuntimeError(
                "estado ACTIVO not seeded in supernova_test"
            )
        return int(row[0])


class _DeterministicClassifier:
    """Stand-in for the LLM classifier used only to keep the
    dispatcher deterministic.

    The class is a structural replacement for
    :class:`backend.llm.intent_classifier.IntentClassifier`; it
    always returns a single ``agregar_producto`` fragment for the
    raw message text. The orchestrator, processor, resolver,
    handler, seam, repository and response mapper run unchanged
    on top of this stub.
    """

    constructor_calls: ClassVar[list] = []
    query_calls: ClassVar[list] = []

    def __init__(self, *args, **kwargs):
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


def _seed_target() -> dict:
    """Seed one comercio with a single priced
    ``ProductoPresentacion``, one ``Cliente``, one active ``Session``
    linked to one ``BORRADOR`` ``Pedido``. No pending context, no
    queued intents, no other presentations of the same product.
    """
    s = _suffix()
    estado_id = _estado_id_activo()
    with TestingSessionLocal() as db, db.begin():
        comercio = Comercio(
            nombre_fantasia=f"SeqR {s}",
            nombre_corto=f"SR {s}",
            razon_social=f"SeqR SRL {s}",
            cuit=f"30-{s[:8]}-{s[8]}",
            whatsapp=f"+54961{s[:8]}",
            calle="Av. SeqR",
            numero="1",
            piso_departamento=None,
            localidad="CABA",
            provincia="BA",
            codigo_postal="C1000",
            slug=f"seqr-{s}",
            estado_id=estado_id,
        )
        db.add(comercio)
        db.flush()

        cliente = Cliente(
            whatsapp=f"+54961{int(s, 16) % 100000000:08d}",
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
            descripcion=f"Napolitanas {s}",
            activo=True,
            orden=0,
        )
        db.add(categoria)
        db.flush()

        producto = Producto(
            id_categoria_producto=categoria.id,
            nombre=f"Napolitana {s}",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        db.add(producto)
        db.flush()

        presentacion = Presentacion(
            id_comercio=comercio.id,
            codigo=f"GRANDE_{s[:6]}",
            descripcion="Grande",
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
            Precio(
                id_producto_presentacion=assoc.id,
                precio=Decimal("1500.00"),
            )
        )
        db.flush()

        return {
            "comercio_id": int(comercio.id),
            "cliente_id": int(cliente.id),
            "session_id": int(session_row.id),
            "pedido_id": int(pedido.id),
            "pp_id": int(assoc.id),
            "producto_nombre": str(producto.nombre),
            "producto_id": int(producto.id),
            "categoria_id": int(categoria.id),
            "presentacion_id": int(presentacion.id),
        }


def _cleanup_target(ids: dict) -> None:
    with TestingSessionLocal() as db, db.begin():
        sess_row = db.get(SessionModel, ids["session_id"])
        if sess_row is not None:
            sess_row.id_pedido = None
            db.flush()
        db.execute(delete(Precio).where(Precio.id_producto_presentacion == ids["pp_id"]))
        db.execute(delete(PedidoProducto).where(PedidoProducto.id_pedido == ids["pedido_id"]))
        db.execute(delete(ProductoPresentacion).where(ProductoPresentacion.id == ids["pp_id"]))
        db.execute(delete(Producto).where(Producto.id == ids["producto_id"]))
        db.execute(delete(CategoriaProducto).where(CategoriaProducto.id == ids["categoria_id"]))
        db.execute(delete(Presentacion).where(Presentacion.id == ids["presentacion_id"]))
        db.execute(delete(Pedido).where(Pedido.id == ids["pedido_id"]))
        db.execute(delete(SessionModel).where(SessionModel.id == ids["session_id"]))
        db.execute(delete(Cliente).where(Cliente.id == ids["cliente_id"]))
        db.execute(delete(Comercio).where(Comercio.id == ids["comercio_id"]))


@contextmanager
def _patched_recognizer(message_to_cantidad: dict[str, int], pp_id: int):
    """Patch ``detectar_productos`` for the duration of the test.

    Each input message maps to a single ready candidate with the
    requested positive ``cantidad`` and the pre-seeded ``pp_id``.
    No quantity in the original text is reused: ``cantidad`` is
    passed explicitly so that the recognizer-side quantity parser
    stays out of the test scope (per the user instruction not to
    touch plural-recognition).
    """
    from backend.intents.orchestration import (
        agregar_producto_orchestrator as agregar_module,
    )

    def _fake_detectar_productos(text, catalog, *, intent_metadata=None):
        cantidad = int(message_to_cantidad[text])
        return {
            "encontrados": [
                {
                    "producto_presentacion_id": int(pp_id),
                    "cantidad": cantidad,
                }
            ],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }

    patcher = patch.object(
        agregar_module, "detectar_productos", side_effect=_fake_detectar_productos
    )
    patcher.start()
    try:
        yield
    finally:
        patcher.stop()


@contextmanager
def _patched_classifier():
    """Patch ``IntentClassifier`` so each turn resolves to a single
    ``agregar_producto`` fragment with the raw message as ``mensaje``.
    """
    from backend.intents.orchestration import (
        initial_intent_dispatcher as dispatcher,
    )

    _DeterministicClassifier.constructor_calls = []
    _DeterministicClassifier.query_calls = []
    patcher = patch.object(
        dispatcher, "IntentClassifier", _DeterministicClassifier
    )
    patcher.start()
    try:
        yield
    finally:
        patcher.stop()


def _run_one_local_test_post(
    client: TestClient, pedido_id: int, message: str
) -> dict:
    headers = _basic_auth_header("ignored", CONFIGURED_TOKEN)
    headers["X-Local-Test-Origin"] = "same-origin"
    response = client.post(
        f"/admin/pilot/orders/{pedido_id}/local-test",
        json={"message": message},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


_RESOLVE_JSDOM_PATH = (
    Path("/tmp/jsdom-test/node_modules/jsdom")
)


def _jsdom_available() -> bool:
    return _RESOLVE_JSDOM_PATH.exists() and (
        _RESOLVE_JSDOM_PATH / "package.json"
    ).exists()


def _render_order_lines_in_jsdom(
    payload,
    *,
    initial_lines: list[dict] | None = None,
    empty_hidden: bool = True,
) -> dict:
    """Apply ``__panelDebugLines.updateOrderLines(payload)`` inside a
    real JSDOM-backed ``base.html`` and return the rendered table
    rows.

    The helper probes the same fixture path used by the existing
    panel JSDOM runner and intentionally captures the cell
    ``textContent`` for every ``<tr>`` cell. The ``base.html``
    template is the same one the dashboard ships in production.
    """
    if not _jsdom_available():
        raise unittest.SkipTest(
            "jsdom not available; install via `npm install jsdom` "
            "and ensure /tmp/jsdom-test/node_modules/jsdom exists."
        )
    template_path = (
        Path(__file__).resolve().parents[1]
        / "templates"
        / "admin_pilot_orders"
        / "base.html"
    )
    template_html = template_path.read_text(encoding="utf-8")
    start = template_html.find("<script>")
    end = template_html.find("</script>")
    script = template_html[start + len("<script>"):end]

    rows_html = ""
    initial = initial_lines or []
    for row in initial:
        rows_html += "<tr><td>#" + str(int(row["id"])) + "</td></tr>"

    jsdom_path_literal = json.dumps(str(_RESOLVE_JSDOM_PATH))
    payload_literal = json.dumps(payload)
    js_source = (
        "const {JSDOM} = require(" + jsdom_path_literal + ");\n"
        "const dom = new JSDOM("
        "`<!DOCTYPE html><html><body>"
        "<table><tbody data-debug-lines-tbody>"
        + rows_html.replace("`", "\\`")
        + "</tbody></table>"
        "<div class=\"empty\" data-debug-lines-empty"
        + (" hidden" if empty_hidden else "")
        + ">El pedido no tiene líneas registradas.</div>"
        "<script>"
        + script.replace("`", "\\`")
        + "</script>"
        "</body></html>`, {runScripts: 'dangerously'});\n"
        "const w = dom.window;\n"
        "const tbody = w.document.querySelector('[data-debug-lines-tbody]');\n"
        "const empty = w.document.querySelector('[data-debug-lines-empty]');\n"
        "const before = {\n"
        "  rows: tbody.children.length,\n"
        "  hidden: empty.hidden\n"
        "};\n"
        "const payload = " + payload_literal + ";\n"
        "const result = w.__panelDebugLines\n"
        "  ? w.__panelDebugLines.updateOrderLines(payload)\n"
        "  : null;\n"
        "const after = {\n"
        "  rows: tbody.children.length,\n"
        "  hidden: empty.hidden\n"
        "};\n"
        "const rows = Array.from(tbody.children).map(function (tr) {\n"
        "  return Array.from(tr.children).map(function (td) {\n"
        "    return td.textContent;\n"
        "  });\n"
        "});\n"
        "console.log(JSON.stringify({"
        "before: before, after: after, result: result, rows: rows}));"
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".js", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(js_source)
        script_path = handle.name
    try:
        completed = subprocess.run(
            ["node", script_path],
            check=True,
            capture_output=True,
            timeout=30,
        )
    finally:
        Path(script_path).unlink(missing_ok=True)
    output = completed.stdout.decode("utf-8").strip()
    if not output:
        raise AssertionError(
            "node produced no stdout; stderr: "
            + completed.stderr.decode("utf-8")
        )
    return json.loads(output.splitlines()[-1])


class _LocalTestRouteHarness(unittest.TestCase):
    """Shared isolation base for every local-test route regression.

    The harness installs ``app.dependency_overrides[get_session]``
    only for the lifetime of a single test and restores the exact
    previous state via ``addCleanup`` (so the restoration runs even
    when the test body raises). The goal is two-fold:

    * keep the FastAPI app pointed at ``TestingSessionLocal`` so
      every ``POST /admin/pilot/orders/{id}/local-test`` reaches the
      seeded ``supernova_test`` catalog;
    * leave the global ``app.dependency_overrides`` dictionary byte
      identical on exit — entries that existed before ``setUp`` are
      preserved, missing keys stay missing.

    Subclasses describe the regression scenario; this class never
    asserts anything itself.
    """

    def setUp(self) -> None:
        self._previous_get_session_override = app.dependency_overrides.get(
            get_session, _MISSING_OVERRIDE
        )
        app.dependency_overrides[get_session] = _override_session
        self.addCleanup(self._restore_get_session_override)

    def _restore_get_session_override(self) -> None:
        previous = self._previous_get_session_override
        self._previous_get_session_override = _MISSING_OVERRIDE
        if previous is _MISSING_OVERRIDE:
            app.dependency_overrides.pop(get_session, None)
        else:
            # ``dependency_overrides`` declares its value type as a
            # callable; ``previous`` is statically narrowed to either
            # the documented callable or the sentinel above so the
            # assignment is safe at runtime.
            app.dependency_overrides[get_session] = previous  # type: ignore[assignment]

    def _client(self) -> TestClient:
        return TestClient(app, raise_server_exceptions=False)


class PilotLocalTestSequentialCumulativeRegressionTest(_LocalTestRouteHarness):
    """Three sequential ``POST /admin/pilot/orders/{id}/local-test``
    turns with quantities ``1``, ``2``, ``3`` must produce one
    executed ``CustomerResponse`` per turn carrying the durable
    final total, exactly one ``order_lines`` entry per turn with
    ``cantidad`` ``1``, ``3``, ``6``, and a durable DB row of ``6``
    after the third turn.
    """

    TURN_MESSAGES: tuple[tuple[int, str], ...] = (
        (1, "agregar 1 napolitana grande"),
        (2, "agregar 2 napolitanas grandes"),
        (3, "agregar 3 napolitanas grandes"),
    )
    EXPECTED_TOTALS: tuple[int, ...] = (1, 3, 6)

    def setUp(self) -> None:
        super().setUp()
        self.ids = _seed_target()
        self.message_to_cantidad = {
            message: cantidad
            for cantidad, message in self.TURN_MESSAGES
        }
        self.addCleanup(_cleanup_target, self.ids)
        self._settings_patcher = patch.object(
            dependencies_module,
            "load_settings",
            return_value=_settings_with_admin_token(),
        )
        self._settings_patcher.start()
        self.addCleanup(self._settings_patcher.stop)

    def _client(self) -> TestClient:
        return TestClient(app, raise_server_exceptions=False)

    def test_three_sequential_turns_produce_cumulative_totals(self) -> None:
        with _patched_classifier(), _patched_recognizer(
            self.message_to_cantidad, self.ids["pp_id"]
        ):
            client = self._client()
            responses_recorded: list[dict] = []
            order_lines_recorded: list[list[dict]] = []
            for cantidad, message in self.TURN_MESSAGES:
                body = _run_one_local_test_post(
                    client, self.ids["pedido_id"], message
                )
                responses_recorded.append(body["responses"])
                order_lines_recorded.append(body["order_lines"])

        for index, (cantidad, _message) in enumerate(self.TURN_MESSAGES):
            expected_total = self.EXPECTED_TOTALS[index]
            responses = responses_recorded[index]
            order_lines = order_lines_recorded[index]
            # `cantidad` is the requested delta for this turn; kept for
            # clarity inside the loop body but not asserted because the
            # regression contract is ``cantidad_final = expected_total``.
            _ = cantidad

        for index, expected_total in enumerate(self.EXPECTED_TOTALS):
            responses = responses_recorded[index]
            order_lines = order_lines_recorded[index]
            self.assertEqual(
                len(responses),
                1,
                f"turn {index + 1}: expected exactly one response; "
                f"got {len(responses)}: {responses!r}",
            )
            entry = responses[0]
            self.assertEqual(
                entry["status"],
                "executed",
                f"turn {index + 1}: expected executed; "
                f"got {entry.get('status')!r}: {entry!r}",
            )
            self.assertEqual(
                entry["intent"],
                "agregar_producto",
            )
            expected_phrase = (
                f"agregué {expected_total}"
                if expected_total == 1
                else f"se agregaron {expected_total}"
            )
            self.assertIn(
                expected_phrase,
                entry["message"],
                f"turn {index + 1}: CustomerResponse.message must include "
                f"the durable final quantity phrase {expected_phrase!r} "
                f"(never the requested delta); got {entry['message']!r}",
            )

            self.assertEqual(
                len(order_lines),
                1,
                f"turn {index + 1}: expected exactly one order line; "
                f"got {len(order_lines)}: {order_lines!r}",
            )
            line = order_lines[0]
            self.assertEqual(
                int(line["cantidad"]),
                expected_total,
                f"turn {index + 1}: order_lines[0].cantidad must equal "
                f"{expected_total}; got {line['cantidad']!r}",
            )
            self.assertIsInstance(
                int(line["id"]),
                int,
            )
            self.assertGreater(
                int(line["id"]),
                0,
                f"turn {index + 1}: order_lines[0].id must be a positive "
                f"PedidoProducto PK; got {line['id']!r}",
            )
            self.assertEqual(
                line["producto_nombre"],
                self.ids["producto_nombre"],
                f"turn {index + 1}: product name mismatch: {line!r}",
            )
            self.assertEqual(
                line["presentacion_descripcion"],
                "Grande",
            )
            self.assertEqual(
                line["precio_unitario_display"],
                "1500.00",
                "price display must be the stored Decimal as JSON-safe str",
            )

        with TestingSessionLocal() as db:
            row = db.execute(
                select(PedidoProducto.cantidad).where(
                    PedidoProducto.id_pedido == self.ids["pedido_id"],
                    PedidoProducto.id_producto_presentacion == self.ids["pp_id"],
                )
            ).scalar_one()
            self.assertEqual(
                int(row),
                6,
                f"after the third turn the durable PedidoProducto.cantidad "
                f"must equal 6; got {row!r}",
            )
            lines = db.execute(
                select(PedidoProducto.id).where(
                    PedidoProducto.id_pedido == self.ids["pedido_id"]
                )
            ).scalars().all()
            self.assertEqual(
                len(lines),
                1,
                f"after three sequential adds the pedido must hold exactly "
                f"one PedidoProducto row; got {len(lines)}",
            )


class PilotLocalTestJsdomDurableRenderTest(_LocalTestRouteHarness):
    """After three sequential turns, the post-turn ``order_lines``
    payload carrying the durable ``6`` must leave the panel
    ``<tbody>`` with a single row whose quantity cell textContent
    is the integer ``"6"`` — never a browser-side sum, never the
    requested delta, never a cached payload from a prior turn.

    The test reuses the same ``base.html`` debug script that runs
    in production (``updateOrderLines`` via
    ``window.__panelDebugLines``) and inspects the rendered cells
    directly.
    """

    def setUp(self) -> None:
        super().setUp()
        self.ids = _seed_target()
        self.message_to_cantidad = {
            message: cantidad
            for cantidad, message in (
                (1, "agregar 1 napolitana grande"),
                (2, "agregar 2 napolitanas grandes"),
                (3, "agregar 3 napolitanas grandes"),
            )
        }
        self.addCleanup(_cleanup_target, self.ids)
        self._settings_patcher = patch.object(
            dependencies_module,
            "load_settings",
            return_value=_settings_with_admin_token(),
        )
        self._settings_patcher.start()
        self.addCleanup(self._settings_patcher.stop)

    def _client(self) -> TestClient:
        return TestClient(app, raise_server_exceptions=False)

    def test_jsdom_table_renders_durable_six_after_third_turn(self) -> None:
        with _patched_classifier(), _patched_recognizer(
            self.message_to_cantidad, self.ids["pp_id"]
        ):
            client = self._client()
            _run_one_local_test_post(
                client, self.ids["pedido_id"], "agregar 1 napolitana grande"
            )
            _run_one_local_test_post(
                client, self.ids["pedido_id"], "agregar 2 napolitanas grandes"
            )
            body = _run_one_local_test_post(
                client, self.ids["pedido_id"], "agregar 3 napolitanas grandes"
            )

        order_lines_payload = body["order_lines"]
        self.assertEqual(len(order_lines_payload), 1)
        self.assertEqual(int(order_lines_payload[0]["cantidad"]), 6)

        rendered = _render_order_lines_in_jsdom(
            order_lines_payload,
            initial_lines=[],
            empty_hidden=True,
        )
        self.assertTrue(
            rendered["result"],
            f"updateOrderLines must accept the post-turn payload; "
            f"got result={rendered['result']!r}",
        )
        self.assertEqual(
            rendered["before"],
            {"rows": 0, "hidden": True},
        )
        self.assertEqual(
            rendered["after"],
            {"rows": 1, "hidden": True},
        )
        rows = rendered["rows"]
        self.assertEqual(
            len(rows),
            1,
            f"rendered tbody must hold exactly one row; got {rows!r}",
        )
        cells = rows[0]
        self.assertGreaterEqual(
            len(cells),
            4,
            f"each line row carries id/nombre/presentacion/cantidad/"
            f"precio/observaciones; got {cells!r}",
        )
        self.assertEqual(
            cells[3],
            "6",
            f"fourth cell (cantidad) must render the durable integer 6; "
            f"got cells={cells!r}",
        )


if __name__ == "__main__":
    unittest.main()
