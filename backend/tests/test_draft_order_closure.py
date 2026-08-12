"""Guided draft-order closure focused tests.

Covers summary fidelity, commerce-scoped payment/delivery selection,
non-mutating rejection cases, complete-confirmation transition, and
full-turn rollback after a technical failure. Includes one provider-
path scenario that asserts a single business result produces a single
outbound response row.
"""
from __future__ import annotations

import importlib
import unittest
import uuid
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from backend.intents.orchestration import (
    draft_order_closure as closure_module,
)
from backend.intents.orchestration.draft_order_closure import (
    process_initial_confirmar_pedido,
    process_initial_consultar_resumen_pedido,
    process_initial_set_metodo_de_entrega,
    process_initial_set_metodo_de_pago,
)
from backend.intents.orchestration.incoming_message_response_orchestrator import (
    process_incoming_message_with_responses,
)
from backend.intents.orchestration.initial_intent_dispatcher import (
    dispatch_initial_message,
)
from backend.intents.responses import (
    draft_order_closure as response_module,
)
from backend.intents.schemas.intent_classification import (
    ClassifiedIntent,
    IntentClassificationResult,
    IntentName,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
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


def _seed_base() -> dict:
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

        foreign_medio = MediosPago(
            codigo=f"TR-{suffix}",
            descripcion=f"Tarjeta {suffix}",
            activo=True,
        )
        db.add(foreign_medio)
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
            "cliente_id": session_row.id_cliente,
            "session_id": session_row.id,
            "pedido_id": pedido.id,
            "producto_id": producto.id,
            "categoria_id": categoria.id,
            "pp_id": assoc.id,
            "medio_pago_id": medio.id,
            "medio_pago_codigo": medio.codigo,
            "medio_pago_descripcion": medio.descripcion,
            "metodo_entrega_id": metodo.id,
            "metodo_entrega_codigo": metodo.codigo,
            "metodo_entrega_descripcion": metodo.descripcion,
            "foreign_medio_pago_id": foreign_medio.id,
        }


def _seed_line(*, pedido_id: int, pp_id: int, cantidad: int = 1) -> int:
    with TestingSessionLocal() as db, db.begin():
        line = PedidoProducto(
            id_pedido=pedido_id,
            id_producto_presentacion=pp_id,
            cantidad=cantidad,
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
                ComercioMedioPago.id_medio_pago.in_(
                    [ids["medio_pago_id"], ids["foreign_medio_pago_id"]]
                )
            )
        )
        db.execute(
            delete(ComercioMetodoEntrega).where(
                ComercioMetodoEntrega.id_metodo_entrega == ids["metodo_entrega_id"]
            )
        )
        db.execute(
            delete(MediosPago).where(
                MediosPago.id.in_(
                    [ids["medio_pago_id"], ids["foreign_medio_pago_id"]]
                )
            )
        )
        db.execute(
            delete(MetodosEntrega).where(
                MetodosEntrega.id == ids["metodo_entrega_id"]
            )
        )
        db.execute(
            delete(Precio).where(
                Precio.id_producto_presentacion == ids["pp_id"]
            )
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


class DraftOrderClosureBoundariesTest(unittest.TestCase):
    def test_module_does_not_import_disallowed_side_effects(self) -> None:
        forbidden_response = (
            "from backend.repositories",
            "from backend.routers",
            "from backend.sessions",
            "from backend.intents.handlers",
            "from backend.intents.recognizers",
            "from backend.intents.resolvers",
            "from backend.intents.processor",
            "from backend.intents.contracts",
            "import requests",
            "import fastapi",
            "backend.old_project",
            "from backend.old_project",
        )
        forbidden_orchestrator = (
            "from backend.routers",
            "from backend.sessions",
            "from backend.intents.handlers",
            "from backend.intents.recognizers",
            "from backend.intents.resolvers",
            "from backend.intents.processor",
            "from backend.intents.contracts",
            "import requests",
            "import fastapi",
            "backend.old_project",
            "from backend.old_project",
        )
        for module, forbidden in (
            (response_module, forbidden_response),
            (closure_module, forbidden_orchestrator),
        ):
            with self.subTest(module=module.__name__):
                importlib.reload(module)
                module_path = module.__file__
                assert module_path is not None
                with open(module_path, encoding="utf-8") as fh:
                    source = fh.read()
                for token in forbidden:
                    self.assertNotIn(token, source)

    def test_orchestrator_does_not_call_db_state_methods(self) -> None:
        with self.subTest(module=closure_module.__name__):
            importlib.reload(closure_module)
            module_path = closure_module.__file__
            assert module_path is not None
            with open(module_path, encoding="utf-8") as fh:
                source = fh.read()
            self.assertNotIn(".commit(", source)
            self.assertNotIn(".rollback(", source)
            self.assertNotIn(".flush(", source)
            self.assertNotIn(".refresh(", source)
            self.assertNotIn(".begin(", source)
            self.assertNotIn(".close(", source)
            self.assertNotIn(".expire(", source)

    def test_response_module_public_surface(self) -> None:
        self.assertEqual(
            response_module.__all__,
            [
                "build_confirmar_pedido_response",
                "build_consultar_resumen_pedido_response",
                "build_set_metodo_de_entrega_response",
                "build_set_metodo_de_pago_response",
                "build_set_observacion_pedido_response",
            ],
        )

    def test_orchestrator_public_surface(self) -> None:
        self.assertEqual(
            closure_module.__all__,
            [
                "process_initial_confirmar_pedido",
                "process_initial_consultar_resumen_pedido",
                "process_initial_set_metodo_de_entrega",
                "process_initial_set_metodo_de_pago",
                "process_initial_set_observacion_pedido",
            ],
        )


class DraftOrderClosureSummaryTest(unittest.TestCase):
    def test_summary_describes_persisted_lines_and_choices(self) -> None:
        ids = _seed_base()
        try:
            _seed_line(pedido_id=ids["pedido_id"], pp_id=ids["pp_id"])
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.id_medio_pago = ids["medio_pago_id"]
                pedido.id_metodo_entrega = ids["metodo_entrega_id"]
                db.commit()
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_consultar_resumen_pedido(
                    db, session_row, "ver resumen"
                )
                self.assertEqual(intent.status, "executed")
                self.assertEqual(intent.intent, "consultar_resumen_pedido")
                self.assertTrue(intent.resolved_data.get("tiene_lineas"))
                self.assertEqual(len(intent.resolved_data["lineas"]), 1)
                self.assertEqual(
                    intent.resolved_data["medio_pago"],
                    f"{ids['medio_pago_codigo']} ({ids['medio_pago_descripcion']})",
                )
                self.assertEqual(
                    intent.resolved_data["metodo_entrega"],
                    f"{ids['metodo_entrega_codigo']} ({ids['metodo_entrega_descripcion']})",
                )
        finally:
            _cleanup(ids)

    def test_summary_empty_draft_returns_executed_with_indicator(self) -> None:
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_consultar_resumen_pedido(
                    db, session_row, "ver resumen"
                )
                self.assertEqual(intent.status, "executed")
                self.assertFalse(intent.resolved_data.get("tiene_lineas"))
        finally:
            _cleanup(ids)

    def test_summary_without_draft_returns_rejected(self) -> None:
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                session_row.id_pedido = None
                db.commit()
                intent = process_initial_consultar_resumen_pedido(
                    db, session_row, "ver resumen"
                )
                self.assertEqual(intent.status, "rejected")
                self.assertEqual(intent.resolved_data.get("reason"), "no_draft")
        finally:
            _cleanup(ids)

    def test_summary_does_not_mutate_pedido_or_lines(self) -> None:
        ids = _seed_base()
        try:
            _seed_line(pedido_id=ids["pedido_id"], pp_id=ids["pp_id"])
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                process_initial_consultar_resumen_pedido(
                    db, session_row, "ver resumen"
                )
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertIsNone(pedido.id_medio_pago)
                self.assertIsNone(pedido.id_metodo_entrega)
                self.assertEqual(pedido.estado_pedido, EstadoPedido.BORRADOR)
                lines = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == ids["pedido_id"]
                    )
                ).scalars().all()
                self.assertEqual(len(lines), 1)
        finally:
            _cleanup(ids)


class DraftOrderClosureSetPaymentTest(unittest.TestCase):
    def test_unique_active_choice_persists_payment(self) -> None:
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_set_metodo_de_pago(
                    db, session_row, ids["medio_pago_codigo"]
                )
                self.assertEqual(intent.status, "executed")
                self.assertEqual(
                    intent.resolved_data.get("id_medio_pago"),
                    ids["medio_pago_id"],
                )
                db.commit()
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(pedido.id_medio_pago, ids["medio_pago_id"])
        finally:
            _cleanup(ids)

    def test_description_match_persists_payment(self) -> None:
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_set_metodo_de_pago(
                    db, session_row, ids["medio_pago_descripcion"]
                )
                self.assertEqual(intent.status, "executed")
                db.commit()
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(pedido.id_medio_pago, ids["medio_pago_id"])
        finally:
            _cleanup(ids)

    def test_foreign_payment_choice_does_not_mutate(self) -> None:
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_set_metodo_de_pago(
                    db, session_row, "TR"
                )
                self.assertEqual(intent.status, "rejected")
                self.assertEqual(intent.resolved_data.get("reason"), "not_active")
                self.assertIsNone(intent.resolved_data.get("id_medio_pago"))
                db.commit()
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertIsNone(pedido.id_medio_pago)
        finally:
            _cleanup(ids)

    def test_empty_choice_returns_clarification(self) -> None:
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_set_metodo_de_pago(db, session_row, "  ")
                self.assertEqual(intent.status, "rejected")
                self.assertEqual(intent.resolved_data.get("reason"), "missing")
                self.assertTrue(intent.resolved_data.get("opciones"))
        finally:
            _cleanup(ids)


def _rename_seeded_payment_description(
    *,
    medio_pago_id: int,
    descripcion: str,
) -> None:
    with TestingSessionLocal() as db, db.begin():
        medio = db.get(MediosPago, medio_pago_id)
        assert medio is not None
        medio.descripcion = descripcion


def _rename_seeded_delivery_description(
    *,
    metodo_entrega_id: int,
    descripcion: str,
) -> None:
    with TestingSessionLocal() as db, db.begin():
        metodo = db.get(MetodosEntrega, metodo_entrega_id)
        assert metodo is not None
        metodo.descripcion = descripcion


def _seed_extra_payment(
    *,
    comercio_id: int,
    codigo: str,
    descripcion: str,
    activo: bool = True,
    activo_en_comercio: bool = True,
) -> int:
    with TestingSessionLocal() as db, db.begin():
        medio = MediosPago(
            codigo=codigo,
            descripcion=descripcion,
            activo=activo,
        )
        db.add(medio)
        db.flush()
        if activo_en_comercio:
            db.add(
                ComercioMedioPago(
                    id_comercio=comercio_id,
                    id_medio_pago=medio.id,
                    activo=True,
                )
            )
            db.flush()
        return medio.id


def _delete_extra_payment(medio_pago_id: int) -> None:
    with TestingSessionLocal() as db, db.begin():
        db.execute(
            delete(ComercioMedioPago).where(
                ComercioMedioPago.id_medio_pago == medio_pago_id
            )
        )
        db.execute(delete(MediosPago).where(MediosPago.id == medio_pago_id))


def _seed_extra_delivery(
    *,
    comercio_id: int,
    codigo: str,
    descripcion: str,
    activo: bool = True,
    activo_en_comercio: bool = True,
) -> int:
    with TestingSessionLocal() as db, db.begin():
        metodo = MetodosEntrega(
            codigo=codigo,
            descripcion=descripcion,
            orden=1,
            activo=activo,
        )
        db.add(metodo)
        db.flush()
        if activo_en_comercio:
            db.add(
                ComercioMetodoEntrega(
                    id_comercio=comercio_id,
                    id_metodo_entrega=metodo.id,
                    activo=True,
                    orden=1,
                )
            )
            db.flush()
        return metodo.id


def _delete_extra_delivery(metodo_entrega_id: int) -> None:
    with TestingSessionLocal() as db, db.begin():
        db.execute(
            delete(ComercioMetodoEntrega).where(
                ComercioMetodoEntrega.id_metodo_entrega
                == metodo_entrega_id
            )
        )
        db.execute(
            delete(MetodosEntrega).where(
                MetodosEntrega.id == metodo_entrega_id
            )
        )


class DraftOrderClosureNaturalChoiceTest(unittest.TestCase):
    def test_natural_payment_phrase_matches_unique_active_description(
        self,
    ) -> None:
        ids = _seed_base()
        try:
            _rename_seeded_payment_description(
                medio_pago_id=ids["medio_pago_id"],
                descripcion="Efectivo (prueba cierre)",
            )
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_set_metodo_de_pago(
                    db,
                    session_row,
                    "Pago en Efectivo (prueba cierre)",
                )
                self.assertEqual(intent.status, "executed")
                self.assertEqual(
                    intent.resolved_data.get("id_medio_pago"),
                    ids["medio_pago_id"],
                )
                self.assertEqual(
                    intent.resolved_data.get("descripcion"),
                    "Efectivo (prueba cierre)",
                )
                db.commit()
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(
                    pedido.id_medio_pago, ids["medio_pago_id"]
                )
        finally:
            _cleanup(ids)

    def test_natural_delivery_phrase_matches_unique_active_description(
        self,
    ) -> None:
        ids = _seed_base()
        try:
            _rename_seeded_delivery_description(
                metodo_entrega_id=ids["metodo_entrega_id"],
                descripcion="Retiro local (prueba cierre)",
            )
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_set_metodo_de_entrega(
                    db,
                    session_row,
                    "Entrega en Retiro local (prueba cierre)",
                )
                self.assertEqual(intent.status, "executed")
                self.assertEqual(
                    intent.resolved_data.get("id_metodo_entrega"),
                    ids["metodo_entrega_id"],
                )
                db.commit()
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(
                    pedido.id_metodo_entrega, ids["metodo_entrega_id"]
                )
        finally:
            _cleanup(ids)

    def test_exact_code_and_description_still_match_with_fallback(
        self,
    ) -> None:
        ids = _seed_base()
        suffix = ids["medio_pago_codigo"].rsplit("-", 1)[-1]
        extra_id: int | None = None
        try:
            _rename_seeded_payment_description(
                medio_pago_id=ids["medio_pago_id"],
                descripcion=f"Efectivo {suffix}",
            )
            extra_id = _seed_extra_payment(
                comercio_id=ids["comercio_id"],
                codigo=f"EFDESC-{suffix}",
                descripcion=f"Efectivo prueba {suffix}",
            )
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_set_metodo_de_pago(
                    db, session_row, ids["medio_pago_codigo"]
                )
                self.assertEqual(intent.status, "executed")
                self.assertEqual(
                    intent.resolved_data.get("id_medio_pago"),
                    ids["medio_pago_id"],
                )
                db.commit()
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(
                    pedido.id_medio_pago, ids["medio_pago_id"]
                )
        finally:
            if extra_id is not None:
                _delete_extra_payment(extra_id)
            _cleanup(ids)

    def test_two_descriptions_with_overlapping_tokens_are_ambiguous(
        self,
    ) -> None:
        ids = _seed_base()
        suffix = ids["medio_pago_codigo"].rsplit("-", 1)[-1]
        extra_id: int | None = None
        try:
            _rename_seeded_payment_description(
                medio_pago_id=ids["medio_pago_id"],
                descripcion=f"Efectivo {suffix}",
            )
            extra_id = _seed_extra_payment(
                comercio_id=ids["comercio_id"],
                codigo=f"EFCON-{suffix}",
                descripcion=f"Efectivo con descuento {suffix}",
            )
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_set_metodo_de_pago(
                    db,
                    session_row,
                    f"Pago en Efectivo {suffix} con descuento",
                )
                self.assertEqual(intent.status, "rejected")
                self.assertEqual(
                    intent.resolved_data.get("reason"), "ambiguous"
                )
                self.assertIsNone(
                    intent.resolved_data.get("id_medio_pago")
                )
                db.commit()
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertIsNone(pedido.id_medio_pago)
        finally:
            if extra_id is not None:
                _delete_extra_payment(extra_id)
            _cleanup(ids)

    def test_partial_token_does_not_qualify_through_fallback(self) -> None:
        ids = _seed_base()
        try:
            _rename_seeded_payment_description(
                medio_pago_id=ids["medio_pago_id"],
                descripcion="Efectivo (prueba cierre)",
            )
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_set_metodo_de_pago(
                    db, session_row, "efect prueb"
                )
                self.assertEqual(intent.status, "rejected")
                self.assertEqual(
                    intent.resolved_data.get("reason"), "not_active"
                )
                self.assertIsNone(
                    intent.resolved_data.get("id_medio_pago")
                )
                db.commit()
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertIsNone(pedido.id_medio_pago)
        finally:
            _cleanup(ids)

    def test_commerce_foreign_description_never_qualifies(self) -> None:
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db, db.begin():
                foreign = db.get(
                    MediosPago, ids["foreign_medio_pago_id"]
                )
                assert foreign is not None
                foreign.descripcion = "Efectivo (prueba cierre)"
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_set_metodo_de_pago(
                    db,
                    session_row,
                    "Pago en Efectivo (prueba cierre)",
                )
                self.assertEqual(intent.status, "rejected")
                self.assertEqual(
                    intent.resolved_data.get("reason"), "not_active"
                )
                self.assertIsNone(
                    intent.resolved_data.get("id_medio_pago")
                )
                db.commit()
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertIsNone(pedido.id_medio_pago)
        finally:
            _cleanup(ids)

    def test_globally_inactive_commerce_linked_payment_never_qualifies(
        self,
    ) -> None:
        ids = _seed_base()
        try:
            _rename_seeded_payment_description(
                medio_pago_id=ids["medio_pago_id"],
                descripcion="Efectivo (prueba cierre)",
            )
            with TestingSessionLocal() as db, db.begin():
                medio = db.get(MediosPago, ids["medio_pago_id"])
                assert medio is not None
                medio.activo = False
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_set_metodo_de_pago(
                    db,
                    session_row,
                    "Pago en Efectivo (prueba cierre)",
                )
                self.assertEqual(intent.status, "rejected")
                self.assertEqual(
                    intent.resolved_data.get("reason"), "not_active"
                )
                db.commit()
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertIsNone(pedido.id_medio_pago)
        finally:
            _cleanup(ids)

    def test_existing_payment_preserved_when_natural_phrase_is_ambiguous(
        self,
    ) -> None:
        ids = _seed_base()
        suffix = ids["medio_pago_codigo"].rsplit("-", 1)[-1]
        extra_id: int | None = None
        try:
            _rename_seeded_payment_description(
                medio_pago_id=ids["medio_pago_id"],
                descripcion=f"Efectivo {suffix}",
            )
            extra_id = _seed_extra_payment(
                comercio_id=ids["comercio_id"],
                codigo=f"EFCON-{suffix}",
                descripcion=f"Efectivo con descuento {suffix}",
            )
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.id_medio_pago = ids["medio_pago_id"]
                db.commit()
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_set_metodo_de_pago(
                    db,
                    session_row,
                    f"Pago en Efectivo {suffix} con descuento",
                )
                self.assertEqual(intent.status, "rejected")
                self.assertEqual(
                    intent.resolved_data.get("reason"), "ambiguous"
                )
                db.commit()
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(
                    pedido.id_medio_pago, ids["medio_pago_id"]
                )
        finally:
            if extra_id is not None:
                _delete_extra_payment(extra_id)
            _cleanup(ids)

    def test_existing_payment_and_delivery_preserved_when_no_fallback_match(
        self,
    ) -> None:
        ids = _seed_base()
        try:
            _rename_seeded_payment_description(
                medio_pago_id=ids["medio_pago_id"],
                descripcion="Efectivo (prueba cierre)",
            )
            _rename_seeded_delivery_description(
                metodo_entrega_id=ids["metodo_entrega_id"],
                descripcion="Retiro local (prueba cierre)",
            )
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.id_medio_pago = ids["medio_pago_id"]
                pedido.id_metodo_entrega = ids["metodo_entrega_id"]
                db.commit()
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_set_metodo_de_pago(
                    db, session_row, "no se parece a nada"
                )
                self.assertEqual(intent.status, "rejected")
                self.assertEqual(
                    intent.resolved_data.get("reason"), "not_active"
                )
                db.commit()
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(
                    pedido.id_medio_pago, ids["medio_pago_id"]
                )
                self.assertEqual(
                    pedido.id_metodo_entrega,
                    ids["metodo_entrega_id"],
                )
        finally:
            _cleanup(ids)


class DraftOrderClosureSetDeliveryTest(unittest.TestCase):
    def test_unique_active_choice_persists_delivery(self) -> None:
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_set_metodo_de_entrega(
                    db, session_row, ids["metodo_entrega_codigo"]
                )
                self.assertEqual(intent.status, "executed")
                db.commit()
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(
                    pedido.id_metodo_entrega, ids["metodo_entrega_id"]
                )
        finally:
            _cleanup(ids)

    def test_inactive_for_comercio_does_not_mutate(self) -> None:
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db:
                # Disable the comercio-metodo association.
                link = db.execute(
                    select(ComercioMetodoEntrega).where(
                        ComercioMetodoEntrega.id_comercio == ids["comercio_id"]
                    )
                ).scalar_one()
                link.activo = False
                db.commit()

                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_set_metodo_de_entrega(
                    db, session_row, ids["metodo_entrega_codigo"]
                )
                self.assertEqual(intent.status, "rejected")
                self.assertEqual(intent.resolved_data.get("reason"), "not_active")
                db.commit()
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertIsNone(pedido.id_metodo_entrega)
        finally:
            _cleanup(ids)


class DraftOrderClosureConfirmTest(unittest.TestCase):
    def _stage_complete(
        self,
        *,
        pedido_id: int,
        medio_pago_id: int,
        metodo_entrega_id: int,
    ) -> None:
        with TestingSessionLocal() as db, db.begin():
            pedido = db.get(Pedido, pedido_id)
            assert pedido is not None
            pedido.id_medio_pago = medio_pago_id
            pedido.id_metodo_entrega = metodo_entrega_id

    def test_complete_draft_transitions_once(self) -> None:
        ids = _seed_base()
        try:
            _seed_line(pedido_id=ids["pedido_id"], pp_id=ids["pp_id"])
            self._stage_complete(
                pedido_id=ids["pedido_id"],
                medio_pago_id=ids["medio_pago_id"],
                metodo_entrega_id=ids["metodo_entrega_id"],
            )
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_confirmar_pedido(
                    db, session_row, "confirmar"
                )
                self.assertEqual(intent.status, "executed")
                self.assertEqual(
                    intent.resolved_data.get("pedido_id"), ids["pedido_id"]
                )
                db.commit()
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(pedido.estado_pedido, EstadoPedido.INGRESADO)
        finally:
            _cleanup(ids)

    def test_second_confirmation_is_idempotent_and_rejected(self) -> None:
        ids = _seed_base()
        try:
            _seed_line(pedido_id=ids["pedido_id"], pp_id=ids["pp_id"])
            self._stage_complete(
                pedido_id=ids["pedido_id"],
                medio_pago_id=ids["medio_pago_id"],
                metodo_entrega_id=ids["metodo_entrega_id"],
            )
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                first = process_initial_confirmar_pedido(
                    db, session_row, "confirmar"
                )
                self.assertEqual(first.status, "executed")
                db.commit()
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                # Reload pedido to observe persisted state in a fresh session.
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(pedido.estado_pedido, EstadoPedido.INGRESADO)
                # Simulate a second-turn attempt with a fresh session.
                second = process_initial_confirmar_pedido(
                    db, session_row, "confirmar de nuevo"
                )
                self.assertEqual(second.status, "rejected")
                self.assertEqual(
                    second.resolved_data.get("reason"), "pedido_not_borrador"
                )
                db.commit()
        finally:
            _cleanup(ids)

    def test_empty_draft_returns_guidance(self) -> None:
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_confirmar_pedido(
                    db, session_row, "confirmar"
                )
                self.assertEqual(intent.status, "rejected")
                self.assertEqual(intent.resolved_data.get("reason"), "empty_draft")
        finally:
            _cleanup(ids)

    def test_missing_payment_returns_guidance(self) -> None:
        ids = _seed_base()
        try:
            _seed_line(pedido_id=ids["pedido_id"], pp_id=ids["pp_id"])
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.id_metodo_entrega = ids["metodo_entrega_id"]
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_confirmar_pedido(
                    db, session_row, "confirmar"
                )
                self.assertEqual(intent.status, "rejected")
                self.assertEqual(
                    intent.resolved_data.get("reason"), "missing_payment"
                )
        finally:
            _cleanup(ids)

    def test_missing_delivery_returns_guidance(self) -> None:
        ids = _seed_base()
        try:
            _seed_line(pedido_id=ids["pedido_id"], pp_id=ids["pp_id"])
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.id_medio_pago = ids["medio_pago_id"]
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                intent = process_initial_confirmar_pedido(
                    db, session_row, "confirmar"
                )
                self.assertEqual(intent.status, "rejected")
                self.assertEqual(
                    intent.resolved_data.get("reason"), "missing_delivery"
                )
        finally:
            _cleanup(ids)


class DraftOrderClosureTechnicalFailureRollbackTest(unittest.TestCase):
    def test_technical_failure_after_staging_rolls_back_full_turn(self) -> None:
        ids = _seed_base()
        try:
            _seed_line(pedido_id=ids["pedido_id"], pp_id=ids["pp_id"])
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                with patch.object(
                    closure_module.MediosPagoRepository,
                    "list_active_for_comercio",
                    side_effect=RuntimeError("boom"),
                ):
                    with self.assertRaises(RuntimeError):
                        process_initial_set_metodo_de_pago(
                            db, session_row, ids["medio_pago_codigo"]
                        )
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertIsNone(pedido.id_medio_pago)
                self.assertEqual(pedido.estado_pedido, EstadoPedido.BORRADOR)
        finally:
            _cleanup(ids)

    def test_local_transactional_processor_rolls_back_on_failure(self) -> None:
        ids = _seed_base()
        try:
            _seed_line(pedido_id=ids["pedido_id"], pp_id=ids["pp_id"])
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                with _patched_classifier(IntentName.SET_METODO_DE_PAGO):
                    with patch.object(
                        closure_module.MediosPagoRepository,
                        "list_active_for_comercio",
                        side_effect=RuntimeError("boom"),
                    ):
                        with self.assertRaises(RuntimeError):
                            process_incoming_message_with_responses(
                                db,
                                session_row,
                                ids["medio_pago_codigo"],
                            )
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertIsNone(pedido.id_medio_pago)
                self.assertEqual(pedido.estado_pedido, EstadoPedido.BORRADOR)
        finally:
            _cleanup(ids)


class _ClosureClassifier:
    def __init__(self, *args, **kwargs) -> None:
        self.intent: IntentName | None = None

    def query(self, message: str) -> IntentClassificationResult:
        assert self.intent is not None
        return IntentClassificationResult(
            intents=[
                ClassifiedIntent(intent=self.intent, mensaje=message)
            ],
            mensaje=message,
        )


@contextmanager
def _patched_classifier(intent: IntentName):
    from backend.intents.orchestration import (
        initial_intent_dispatcher as dispatcher,
    )

    classifier = _ClosureClassifier()
    classifier.intent = intent
    patcher = patch.object(dispatcher, "IntentClassifier", lambda *a, **k: classifier)
    patcher.start()
    try:
        yield
    finally:
        patcher.stop()


class DraftOrderClosureLocalResponseTest(unittest.TestCase):
    def test_local_response_pipeline_renders_summary(self) -> None:
        ids = _seed_base()
        try:
            _seed_line(pedido_id=ids["pedido_id"], pp_id=ids["pp_id"])
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.id_medio_pago = ids["medio_pago_id"]
                pedido.id_metodo_entrega = ids["metodo_entrega_id"]
                db.commit()
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                with _patched_classifier(IntentName.CONSULTAR_RESUMEN_PEDIDO):
                    responses = process_incoming_message_with_responses(
                        db, session_row, "ver resumen"
                    )
                self.assertEqual(len(responses), 1)
                response = responses[0]
                self.assertEqual(response.intent, "consultar_resumen_pedido")
                self.assertIn("Tu pedido:", response.message)
                self.assertIn(
                    ids["medio_pago_codigo"], response.message
                )
                self.assertIn(
                    ids["metodo_entrega_codigo"], response.message
                )
        finally:
            _cleanup(ids)

    def test_local_response_pipeline_renders_payment_confirmation(self) -> None:
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                with _patched_classifier(IntentName.SET_METODO_DE_PAGO):
                    responses = process_incoming_message_with_responses(
                        db,
                        session_row,
                        ids["medio_pago_codigo"],
                    )
                self.assertEqual(len(responses), 1)
                response = responses[0]
                self.assertEqual(response.intent, "set_metodo_de_pago")
                self.assertIn("Listo", response.message)
                self.assertIn(ids["medio_pago_codigo"], response.message)
        finally:
            _cleanup(ids)

    def test_local_response_pipeline_rejects_whitespace_message(
        self,
    ) -> None:
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                with _patched_classifier(IntentName.SET_METODO_DE_ENTREGA):
                    with self.assertRaises(ValueError):
                        process_incoming_message_with_responses(
                            db, session_row, "   "
                        )
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertIsNone(pedido.id_medio_pago)
                self.assertIsNone(pedido.id_metodo_entrega)
                self.assertEqual(pedido.estado_pedido, EstadoPedido.BORRADOR)
        finally:
            _cleanup(ids)


class DraftOrderClosureProviderPathTest(unittest.TestCase):
    """Re-exports the provider-path scenario. The full PostgreSQL-backed
    provider path is covered in `test_provider_inbound_processing.py`;
    this class asserts the dispatcher hands the closure intent to the
    closure orchestrator before the provider mapping boundary sees it.
    """

    def test_closure_intent_reaches_orchestrator_before_mapping(self) -> None:
        from backend.intents.orchestration import (
            initial_intent_dispatcher as dispatcher_module,
        )

        sentinel = ProcessedIntent(
            intent="confirmar_pedido",
            source_text="x",
            status="executed",
            recognizer="draft_order_closure",
            handler="confirmar_pedido",
        )
        with patch.object(
            dispatcher_module,
            "process_initial_confirmar_pedido",
            return_value=sentinel,
        ):
            with _patched_classifier(IntentName.CONFIRMAR_PEDIDO):
                result = dispatch_initial_message(
                    MagicMock(), MagicMock(context_type=None), "x"
                )
        self.assertEqual(result, [sentinel])


class DraftOrderClosureDispatcherRoutingTest(unittest.TestCase):
    def test_dispatcher_routes_four_closure_intents(self) -> None:
        from backend.intents.orchestration import (
            initial_intent_dispatcher as dispatcher_module,
        )

        for intent, orchestrator_attr in (
            (
                IntentName.CONSULTAR_RESUMEN_PEDIDO,
                "process_initial_consultar_resumen_pedido",
            ),
            (
                IntentName.SET_METODO_DE_PAGO,
                "process_initial_set_metodo_de_pago",
            ),
            (
                IntentName.SET_METODO_DE_ENTREGA,
                "process_initial_set_metodo_de_entrega",
            ),
            (
                IntentName.CONFIRMAR_PEDIDO,
                "process_initial_confirmar_pedido",
            ),
        ):
            with self.subTest(intent=intent):
                sentinel = ProcessedIntent(
                    intent=intent.value,
                    source_text="x",
                    status="rejected",
                    recognizer="draft_order_closure",
                    handler=intent.value,
                )
                with patch.object(
                    dispatcher_module, orchestrator_attr, return_value=sentinel
                ):
                    with _patched_classifier(intent):
                        result = dispatch_initial_message(
                            MagicMock(), MagicMock(context_type=None), "x"
                        )
                self.assertEqual(result, [sentinel])


if __name__ == "__main__":
    unittest.main()
