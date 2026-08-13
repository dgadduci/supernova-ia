"""End-to-end conversation integration tests for the pending-product-ambiguity resolver.

Reproduces the Coca-Cola Common Lata vs Coca-Cola Zero Lata clarification
conversation through the full pending-context dispatch pipeline against
the real ``supernova_test`` PostgreSQL database, plus a parallel scenario
with Pizza Muzzarella Tradicional vs Pizza Muzzarella Especial to prove
the resolver is generic across product families.

The initial ambiguous message is sent through
:func:`process_incoming_message` (the same entry point the HTTP layer
uses); the customer reply is then routed through
:func:`dispatch_pending_context` exactly as the spec requires. The
IntentClassifier LLM dependency is replaced with a deterministic stub.
"""
from __future__ import annotations

import unittest
import uuid
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, ClassVar
from unittest.mock import patch

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from backend.intents.orchestration.incoming_message_orchestrator import (
    process_incoming_message,
)
from backend.intents.orchestration.pending_context_dispatcher import (
    dispatch_pending_context,
    emit_event,
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
from backend.observability.events import EVENT_PENDING_CONTEXT_TRANSITION

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


def _seed_two_product_comercio(
    *,
    nombre_a: str,
    nombre_b: str,
    codigo_a: str,
    codigo_b: str,
    descripcion_presentacion: str,
    precio_a: Decimal,
    precio_b: Decimal,
) -> dict[str, Any]:
    """Seed one comercio with two products on a shared category.

    Returns the created ids plus the resolution ids of the two
    ProductoPresentacion rows. Each product carries an explicit
    distinguishing token in its ``nombre`` (``nombre_a`` and ``nombre_b``
    differ on at least one word) so Layer 5 can distinguish them.
    """
    s = _suffix()
    estado_id = _estado_id_activo()

    with TestingSessionLocal() as db, db.begin():
        comercio = Comercio(
            nombre_fantasia=f"Amb {s}",
            nombre_corto=f"Amb {s}",
            razon_social=f"Amb SRL {s}",
            cuit=f"30-{s[:8]}-{s[8]}",
            whatsapp=f"+5492{s[:8]}",
            calle="Av. Amb",
            numero="1",
            piso_departamento=None,
            localidad="CABA",
            provincia="BA",
            codigo_postal="C1000",
            slug=f"amb-{s}",
            estado_id=estado_id,
        )
        db.add(comercio)
        db.flush()

        cliente = Cliente(
            whatsapp=f"+5492{int(s, 16) % 100000000:08d}",
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
            descripcion=f"Cat {s}",
            activo=True,
            orden=0,
        )
        db.add(categoria)
        db.flush()

        producto_a = Producto(
            id_categoria_producto=categoria.id,
            nombre=nombre_a,
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        db.add(producto_a)
        db.flush()

        producto_b = Producto(
            id_categoria_producto=categoria.id,
            nombre=nombre_b,
            descripcion=None,
            activo=True,
            disponible=True,
            orden=1,
        )
        db.add(producto_b)
        db.flush()

        presentacion = Presentacion(
            id_comercio=comercio.id,
            codigo=f"AMB{s[:4]}",
            descripcion=descripcion_presentacion,
            activo=True,
            orden=0,
        )
        db.add(presentacion)
        db.flush()

        assoc_a = ProductoPresentacion(
            id_producto=producto_a.id,
            id_presentacion=presentacion.id,
            activo=True,
            orden=0,
        )
        db.add(assoc_a)
        db.flush()

        assoc_b = ProductoPresentacion(
            id_producto=producto_b.id,
            id_presentacion=presentacion.id,
            activo=True,
            orden=1,
        )
        db.add(assoc_b)
        db.flush()

        db.add(Precio(id_producto_presentacion=assoc_a.id, precio=precio_a))
        db.flush()
        db.add(Precio(id_producto_presentacion=assoc_b.id, precio=precio_b))
        db.flush()

        ids: dict[str, Any] = {
            "comercio_id": comercio.id,
            "cliente_id": cliente.id,
            "session_id": session_row.id,
            "pedido_id": pedido.id,
            "producto_a_id": producto_a.id,
            "producto_b_id": producto_b.id,
            "presentacion_id": presentacion.id,
            "pp_a_id": assoc_a.id,
            "pp_b_id": assoc_b.id,
            "producto_ids": [producto_a.id, producto_b.id],
            "presentacion_ids": [presentacion.id],
            "categoria_id": categoria.id,
        }
    return ids


def _cleanup(ids: dict[str, Any]) -> None:
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
        db.execute(
            delete(Precio).where(
                Precio.id_producto_presentacion.in_(
                    select(ProductoPresentacion.id).where(
                        ProductoPresentacion.id_producto.in_(ids["producto_ids"])
                    )
                )
            )
        )
        db.execute(
            delete(ProductoPresentacion).where(
                ProductoPresentacion.id_producto.in_(ids["producto_ids"])
            )
        )
        db.execute(delete(Producto).where(Producto.id.in_(ids["producto_ids"])))
        db.execute(delete(CategoriaProducto).where(CategoriaProducto.id == ids["categoria_id"]))
        db.execute(delete(Presentacion).where(Presentacion.id.in_(ids["presentacion_ids"])))
        db.execute(delete(Pedido).where(Pedido.id == ids["pedido_id"]))
        db.execute(delete(SessionModel).where(SessionModel.id == ids["session_id"]))
        db.execute(delete(Cliente).where(Cliente.id == ids["cliente_id"]))
        db.execute(delete(Comercio).where(Comercio.id == ids["comercio_id"]))


class _PatchedClassifier:
    """Stub IntentClassifier that always returns an agregar_producto intent.

    Mirrors the helper in ``test_incoming_message_integration``.
    """

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
    from backend.intents.orchestration import initial_intent_dispatcher as _dispatcher

    _PatchedClassifier.constructor_calls = []
    _PatchedClassifier.query_calls = []

    patcher = patch.object(_dispatcher, "IntentClassifier", _PatchedClassifier)
    patcher.start()
    try:
        yield _PatchedClassifier
    finally:
        patcher.stop()


def _assert_executed_for_pp(
    *,
    session_id: int,
    pedido_id: int,
    expected_pp_id: int,
    expected_cantidad: int = 1,
) -> None:
    with TestingSessionLocal() as db:
        session_row = db.get(SessionModel, session_id)
        assert session_row is not None
        assert session_row.context_type is None, (
            f"context_type should be cleared; got {session_row.context_type!r}"
        )
        pending = session_row.pending_intents or {}
        assert pending.get("active") is None, (
            f"active intent should be cleared; got {pending.get('active')!r}"
        )
        assert pending.get("queue") == [], (
            f"queue should be empty; got {pending.get('queue')!r}"
        )

        lines = (
            db.execute(
                select(PedidoProducto).where(
                    PedidoProducto.id_pedido == pedido_id
                )
            )
            .scalars()
            .all()
        )
        assert len(lines) == 1, (
            f"expected exactly 1 PedidoProducto; got {len(lines)}"
        )
        line = lines[0]
        assert line.id_producto_presentacion == expected_pp_id, (
            f"expected pp_id={expected_pp_id}; got {line.id_producto_presentacion}"
        )
        assert line.cantidad == expected_cantidad, (
            f"expected cantidad={expected_cantidad}; got {line.cantidad}"
        )


def _assert_pending_preserved(
    *,
    session_id: int,
    pedido_id: int,
    expected_candidate_ids: list[int],
) -> None:
    with TestingSessionLocal() as db:
        session_row = db.get(SessionModel, session_id)
        assert session_row is not None
        assert session_row.context_type == "product_selection", (
            f"context_type should be preserved; got {session_row.context_type!r}"
        )
        pending = session_row.pending_intents or {}
        active = pending.get("active")
        assert active is not None
        assert active.get("status") == "pending_resolution"
        assert active.get("candidate_ids") == expected_candidate_ids, (
            f"expected candidate_ids={expected_candidate_ids}; "
            f"got {active.get('candidate_ids')!r}"
        )

        lines = (
            db.execute(
                select(PedidoProducto).where(
                    PedidoProducto.id_pedido == pedido_id
                )
            )
            .scalars()
            .all()
        )
        assert len(lines) == 0, (
            f"expected 0 PedidoProducto rows; got {len(lines)}"
        )





class CocaColaCommonVsZeroEndToEndTest(unittest.TestCase):
    """Layer 1 / 2 / 4 / 6 / 7 reply shapes all converge on
    Common Lata through the real ``dispatch_pending_context`` entry
    point. The initial ambiguous ``una coca`` message establishes a
    pending context that lists both candidates.

    Only replies that are NOT pre-empted by the existing fragment
    path's recognizer are exercised here — those replies (``zero``,
    ``coca zero``, ``la que no es zero``, ``no quiero la zero``,
    ``no la zero``) are covered by
    :class:`CocaColaZeroSelectionEndToEndTest` instead because the
    existing path already resolves them to the Zero Lata candidate.

    Replies that spell out the Zero Lata full name (``coca cola zero
    lata``, ``Coca-Cola Zero Lata``) are exercised by
    :class:`CocaColaZeroSelectionEndToEndTest` because they converge
    on Zero Lata, not Common Lata.
    """

    def test_coca_cola_common_vs_zero_full_conversation(self) -> None:
        for reply in (
            "1",
            "primera",
            "coca cola en lata",
            "común",
            "normal",
            "regular",
            "original",
            "sin zero",
            "la otra",
        ):
            self._assert_common_via_dispatch(reply)

    def _assert_common_via_dispatch(self, reply: str) -> None:
        ids = _seed_two_product_comercio(
            nombre_a="Coca-Cola",
            nombre_b="Coca-Cola Zero",
            codigo_a="COMUN",
            codigo_b="ZERO",
            descripcion_presentacion="Lata",
            precio_a=Decimal("1000.00"),
            precio_b=Decimal("1100.00"),
        )
        try:
            with _patched_classifier("una coca"):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    initial = process_incoming_message(
                        db, session_row, "una coca"
                    )
                    assert len(initial) == 1
                    assert initial[0].status == "pending_resolution"
                    db.commit()

            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                outcomes = dispatch_pending_context(db, session_row, reply)
                assert len(outcomes) >= 1
                assert outcomes[0].status == "executed"
                db.commit()

            _assert_executed_for_pp(
                session_id=ids["session_id"],
                pedido_id=ids["pedido_id"],
                expected_pp_id=ids["pp_a_id"],
                expected_cantidad=1,
            )
        finally:
            _cleanup(ids)


class CocaColaZeroSelectionEndToEndTest(unittest.TestCase):
    """Layer 1 / 2 / 5 reply shapes all converge on Zero Lata."""

    def test_coca_cola_zero_selection_via_differentiating_token(self) -> None:
        for reply in (
            "zero",
            "2",
            "segunda",
            "coca zero",
            "la zero",
            "coca cola zero lata",
            "Coca-Cola Zero Lata",
        ):
            self._assert_zero_via_dispatch(reply)

    def _assert_zero_via_dispatch(self, reply: str) -> None:
        ids = _seed_two_product_comercio(
            nombre_a="Coca-Cola",
            nombre_b="Coca-Cola Zero",
            codigo_a="COMUN",
            codigo_b="ZERO",
            descripcion_presentacion="Lata",
            precio_a=Decimal("1000.00"),
            precio_b=Decimal("1100.00"),
        )
        try:
            with _patched_classifier("una coca"):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    process_incoming_message(db, session_row, "una coca")
                    db.commit()

            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                outcomes = dispatch_pending_context(db, session_row, reply)
                assert len(outcomes) >= 1
                assert outcomes[0].status == "executed"
                db.commit()

            _assert_executed_for_pp(
                session_id=ids["session_id"],
                pedido_id=ids["pedido_id"],
                expected_pp_id=ids["pp_b_id"],
            )
        finally:
            _cleanup(ids)


class PizzaTradicionalVsEspecialEndToEndTest(unittest.TestCase):
    """A second generic family — Pizza Muzzarella Tradicional vs Pizza
    Muzzarella Especial — exercises the resolver against a different
    naming shape and ensures that no Coca-Cola-specific logic exists.

    Some replies (``tradicional``, ``la tradicional``) go through the
    existing fragment path (where ``tradicional`` is a documented
    ``PRESENTACION_ALIAS``); others (``1``, ``primera``) reach the new
    resolver because the existing fragment path has no discriminating
    alias for them. Both must converge on Tradicional.
    """

    def test_second_generic_family_pizza_tradicional_vs_especial(self) -> None:
        for reply in (
            "1",
            "primera",
            "tradicional",
            "la tradicional",
            "pizza muzarrela tradicional",
        ):
            self._assert_tradicional_via_dispatch(reply)

    def _assert_tradicional_via_dispatch(self, reply: str) -> None:
        ids = _seed_two_product_comercio(
            nombre_a="Pizza Muzzarella Tradicional",
            nombre_b="Pizza Muzzarella Especial",
            codigo_a="TRADICIONAL",
            codigo_b="ESPECIAL",
            descripcion_presentacion="Unidad",
            precio_a=Decimal("1500.00"),
            precio_b=Decimal("1700.00"),
        )
        try:
            with _patched_classifier("quiero una pizza de muzzarella"):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    result = process_incoming_message(
                        db, session_row, "quiero una pizza de muzzarella"
                    )
                    assert len(result) == 1
                    assert result[0].status == "pending_resolution"
                    db.commit()

            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                outcomes = dispatch_pending_context(db, session_row, reply)
                assert len(outcomes) >= 1
                assert outcomes[0].status == "executed"
                db.commit()

            _assert_executed_for_pp(
                session_id=ids["session_id"],
                pedido_id=ids["pedido_id"],
                expected_pp_id=ids["pp_a_id"],
            )
        finally:
            _cleanup(ids)


class VagueAnswerAmbiguousEndToEndTest(unittest.TestCase):
    """A vague ``no sé`` reply must keep the pending context intact."""

    def test_vague_answer_remains_ambiguous_through_dispatch(self) -> None:
        ids = _seed_two_product_comercio(
            nombre_a="Coca-Cola",
            nombre_b="Coca-Cola Zero",
            codigo_a="COMUN",
            codigo_b="ZERO",
            descripcion_presentacion="Lata",
            precio_a=Decimal("1000.00"),
            precio_b=Decimal("1100.00"),
        )
        try:
            with _patched_classifier("una coca"):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    process_incoming_message(db, session_row, "una coca")
                    db.commit()

            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                outcomes = dispatch_pending_context(db, session_row, "no sé")
                assert len(outcomes) == 1
                assert outcomes[0].status == "pending_resolution"
                db.commit()

            _assert_pending_preserved(
                session_id=ids["session_id"],
                pedido_id=ids["pedido_id"],
                expected_candidate_ids=[ids["pp_a_id"], ids["pp_b_id"]],
            )
        finally:
            _cleanup(ids)


class MozzarellaGrandeEndToEndTest(unittest.TestCase):
    """Reproduces the WhatsApp sequence from the proposal:

    1. ``Quiero una pizza de mozzarella`` opens a pending context with
       the two persisted candidates (Mozzarella Grande and Mozzarella
       Chica).
    2. The customer replies ``Grande`` which the resolver narrows to a
       single ready candidate through the existing restricted
       ``Mozzarella Grande`` candidate set.
    3. The existing ready-execution path adds the product and clears
       ``session.context_type`` and the pending state.
    4. The dispatcher emits a ``pending_context_transition`` event
       carrying ``status_after="executed"`` and ``context_cleared=True``.

    The test pins the exact expected candidates and proves no
    candidate widening or catalog-only lookup occurs during the
    clarification turn.
    """

    def test_mozzarella_grande_conversation(self) -> None:
        ids = _seed_two_presentation_comercio(
            nombre="Pizza Mozzarella",
            codigo_a="GRANDE",
            codigo_b="CHICA",
        )
        try:
            with _patched_classifier("quiero una pizza de mozzarella"):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    initial = process_incoming_message(
                        db, session_row, "quiero una pizza de mozzarella"
                    )
                    assert len(initial) == 1
                    assert initial[0].status == "pending_resolution"
                    assert sorted(initial[0].candidate_ids) == sorted(
                        [ids["pp_a_id"], ids["pp_b_id"]]
                    )
                    assert session_row.context_type == "product_selection"
                    db.commit()

            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                outcomes = dispatch_pending_context(db, session_row, "Grande")
                assert len(outcomes) >= 1
                assert outcomes[0].status == "executed"
                assert outcomes[0].resolved_data.get("producto_presentacion_id") == ids["pp_a_id"]
                db.commit()

            _assert_executed_for_pp(
                session_id=ids["session_id"],
                pedido_id=ids["pedido_id"],
                expected_pp_id=ids["pp_a_id"],
                expected_cantidad=1,
            )
        finally:
            _cleanup_two_presentation(ids)

    def test_mozzarella_grande_trace_records_executed_and_context_cleared(
        self,
    ) -> None:
        ids = _seed_two_presentation_comercio(
            nombre="Pizza Mozzarella",
            codigo_a="GRANDE",
            codigo_b="CHICA",
        )
        try:
            with _patched_classifier("quiero una pizza de mozzarella"):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    process_incoming_message(
                        db, session_row, "quiero una pizza de mozzarella"
                    )
                    db.commit()

            captured: list[dict] = []

            def _capture(**kwargs):
                captured.append(kwargs)
                return True

            with patch(
                "backend.intents.orchestration.pending_context_dispatcher.emit_event",
                side_effect=_capture,
            ):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    outcomes = dispatch_pending_context(db, session_row, "Grande")
                    assert outcomes[0].status == "executed"
                    db.commit()

            transition = next(
                kwargs
                for kwargs in captured
                if kwargs.get("event") == EVENT_PENDING_CONTEXT_TRANSITION
            )
            self.assertEqual(transition["outcome"], "ready_executed")
            self.assertEqual(transition["context_kind"], "product_selection")
            self.assertEqual(transition["status_before"], "pending_resolution")
            self.assertEqual(transition["status_after"], "executed")
            self.assertTrue(transition["context_cleared"])
            self.assertEqual(transition["candidate_count_before"], 2)
            self.assertEqual(transition["candidate_count_after"], 0)
        finally:
            _cleanup_two_presentation(ids)


class StatusInterruptionPreservesMozzarellaEndToEndTest(unittest.TestCase):
    """The closed deterministic status predicate must interrupt the
    pending Mozzarella Grande context without mutating the active
    candidate set, queue, or context type."""

    def test_status_query_during_pending_mozzarella_preserves_context(self) -> None:
        ids = _seed_two_presentation_comercio(
            nombre="Pizza Mozzarella",
            codigo_a="GRANDE",
            codigo_b="CHICA",
        )
        try:
            with _patched_classifier("quiero una pizza de mozzarella"):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, ids["session_id"])
                    assert session_row is not None
                    process_incoming_message(
                        db, session_row, "quiero una pizza de mozzarella"
                    )
                    db.commit()

            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                outcomes = dispatch_pending_context(
                    db, session_row, "Cuál es el estado de mi pedido"
                )
                assert len(outcomes) == 1
                assert outcomes[0].intent == "consultar_estado_pedido"
                db.commit()

            _assert_pending_preserved(
                session_id=ids["session_id"],
                pedido_id=ids["pedido_id"],
                expected_candidate_ids=sorted(
                    [ids["pp_a_id"], ids["pp_b_id"]]
                ),
            )
        finally:
            _cleanup_two_presentation(ids)


def _seed_two_presentation_comercio(
    *,
    nombre: str,
    codigo_a: str,
    codigo_b: str,
) -> dict[str, Any]:
    """Seed one comercio with one product exposed through two
    presentations (``codigo_a`` / ``codigo_b``). Returns the same id
    map shape as ``_seed_two_product_comercio`` so the existing helpers
    can run unchanged."""
    s = _suffix()
    estado_id = _estado_id_activo()

    with TestingSessionLocal() as db, db.begin():
        comercio = Comercio(
            nombre_fantasia=f"Moz {s}",
            nombre_corto=f"Moz {s}",
            razon_social=f"Moz SRL {s}",
            cuit=f"30-{s[:8]}-{s[8]}",
            whatsapp=f"+5493{s[:8]}",
            calle="Av. Moz",
            numero="1",
            piso_departamento=None,
            localidad="CABA",
            provincia="BA",
            codigo_postal="C1000",
            slug=f"moz-{s}",
            estado_id=estado_id,
        )
        db.add(comercio)
        db.flush()

        cliente = Cliente(
            whatsapp=f"+5493{int(s, 16) % 100000000:08d}",
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
            descripcion=f"Moz Cat {s}",
            activo=True,
            orden=0,
        )
        db.add(categoria)
        db.flush()

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

        presentacion_a = Presentacion(
            id_comercio=comercio.id,
            codigo=f"{codigo_a}_{s[:4]}",
            descripcion=f"Grande {s}",
            activo=True,
            orden=0,
        )
        db.add(presentacion_a)
        db.flush()

        presentacion_b = Presentacion(
            id_comercio=comercio.id,
            codigo=f"{codigo_b}_{s[:4]}",
            descripcion=f"Chica {s}",
            activo=True,
            orden=1,
        )
        db.add(presentacion_b)
        db.flush()

        assoc_a = ProductoPresentacion(
            id_producto=producto.id,
            id_presentacion=presentacion_a.id,
            activo=True,
            orden=0,
        )
        db.add(assoc_a)
        db.flush()

        assoc_b = ProductoPresentacion(
            id_producto=producto.id,
            id_presentacion=presentacion_b.id,
            activo=True,
            orden=1,
        )
        db.add(assoc_b)
        db.flush()

        db.add(Precio(id_producto_presentacion=assoc_a.id, precio=Decimal("12500.00")))
        db.add(Precio(id_producto_presentacion=assoc_b.id, precio=Decimal("8500.00")))
        db.flush()

        return {
            "comercio_id": comercio.id,
            "cliente_id": cliente.id,
            "session_id": session_row.id,
            "pedido_id": pedido.id,
            "producto_id": producto.id,
            "presentacion_a_id": presentacion_a.id,
            "presentacion_b_id": presentacion_b.id,
            "pp_a_id": assoc_a.id,
            "pp_b_id": assoc_b.id,
            "producto_ids": [producto.id],
            "presentacion_ids": [presentacion_a.id, presentacion_b.id],
            "categoria_id": categoria.id,
        }


def _cleanup_two_presentation(ids: dict[str, Any]) -> None:
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
        db.execute(
            delete(Precio).where(
                Precio.id_producto_presentacion.in_(
                    select(ProductoPresentacion.id).where(
                        ProductoPresentacion.id_producto.in_(ids["producto_ids"])
                    )
                )
            )
        )
        db.execute(
            delete(ProductoPresentacion).where(
                ProductoPresentacion.id_producto.in_(ids["producto_ids"])
            )
        )
        db.execute(delete(Producto).where(Producto.id.in_(ids["producto_ids"])))
        db.execute(delete(CategoriaProducto).where(CategoriaProducto.id == ids["categoria_id"]))
        db.execute(delete(Presentacion).where(Presentacion.id.in_(ids["presentacion_ids"])))
        db.execute(delete(Pedido).where(Pedido.id == ids["pedido_id"]))
        db.execute(delete(SessionModel).where(SessionModel.id == ids["session_id"]))
        db.execute(delete(Cliente).where(Cliente.id == ids["cliente_id"]))
        db.execute(delete(Comercio).where(Comercio.id == ids["comercio_id"]))


if __name__ == "__main__":
    unittest.main()
