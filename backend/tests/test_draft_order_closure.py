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
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from backend.intents.orchestration import (
    draft_order_closure as closure_module,
)
from backend.intents.orchestration.draft_order_closure import (
    process_initial_confirmar_pedido,
    process_initial_consultar_resumen_pedido,
    process_initial_set_direccion_entrega,
    process_initial_set_fecha_hora_entrega,
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
                "build_set_direccion_entrega_response",
                "build_set_fecha_hora_entrega_response",
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
                "process_initial_set_direccion_entrega",
                "process_initial_set_fecha_hora_entrega",
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

    def test_local_response_pipeline_renders_fixed_schedule_message(
        self,
    ) -> None:
        ids = _seed_base()
        try:
            timezone = ZoneInfo("America/Argentina/Buenos_Aires")
            scheduled = datetime.now(timezone) + timedelta(days=7)
            source_text = scheduled.strftime("%d/%m/%Y %H:%M")
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                with _patched_classifier(IntentName.SET_FECHA_HORA_ENTREGA):
                    responses = process_incoming_message_with_responses(
                        db, session_row, source_text
                    )
                self.assertEqual(len(responses), 1)
                response = responses[0]
                self.assertEqual(response.intent, "set_fecha_hora_entrega")
                self.assertEqual(response.status, "executed")
                self.assertEqual(
                    response.message,
                    "Listo, guardé la fecha y hora de entrega.",
                )
                self.assertNotIn(source_text.strip(), response.message)
                self.assertNotIn("Buenos Aires", response.message)
                self.assertNotIn(str(ids["pedido_id"]), response.message)
                db.commit()
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

    def test_dispatcher_routes_set_direccion_entrega_intent(self) -> None:
        from backend.intents.orchestration import (
            initial_intent_dispatcher as dispatcher_module,
        )

        sentinel = ProcessedIntent(
            intent="set_direccion_entrega",
            source_text="x",
            status="rejected",
            recognizer="draft_order_closure",
            handler="set_direccion_entrega",
        )
        with patch.object(
            dispatcher_module,
            "process_initial_set_direccion_entrega",
            return_value=sentinel,
        ):
            with _patched_classifier(IntentName.SET_DIRECCION_ENTREGA):
                result = dispatch_initial_message(
                    MagicMock(), MagicMock(context_type=None), "x"
                )
        self.assertEqual(result, [sentinel])

    def test_dispatcher_routes_set_fecha_hora_entrega_intent(self) -> None:
        from backend.intents.orchestration import (
            initial_intent_dispatcher as dispatcher_module,
        )

        sentinel = ProcessedIntent(
            intent="set_fecha_hora_entrega",
            source_text="x",
            status="rejected",
            recognizer="draft_order_closure",
            handler="set_fecha_hora_entrega",
        )
        with patch.object(
            dispatcher_module,
            "process_initial_set_fecha_hora_entrega",
            return_value=sentinel,
        ):
            with _patched_classifier(IntentName.SET_FECHA_HORA_ENTREGA):
                result = dispatch_initial_message(
                    MagicMock(), MagicMock(context_type=None), "x"
                )
        self.assertEqual(result, [sentinel])

    def test_pending_context_short_circuits_schedule_intent(self) -> None:
        from backend.intents.orchestration import (
            initial_intent_dispatcher as dispatcher_module,
        )

        with patch.object(
            dispatcher_module, "IntentClassifier"
        ) as classifier:
            with patch.object(
                dispatcher_module,
                "process_initial_set_fecha_hora_entrega",
            ) as handler:
                result = dispatch_initial_message(
                    MagicMock(),
                    MagicMock(context_type="pending"),
                    "15/08/2026 19:30",
                )
        self.assertEqual(result, [])
        classifier.assert_not_called()
        handler.assert_not_called()


class DraftOrderClosureSourcePreservationTest(unittest.TestCase):
    """Regression coverage for subphase 4: ``classified.mensaje`` may be a
    substring of the original turn, so the dispatcher must hand the
    full original message to the schedule handler while every other
    branch keeps receiving ``classified.mensaje``.
    """

    @staticmethod
    def _make_classifier(
        *,
        intent: IntentName,
        substring: str,
    ):
        """Build a stub classifier that returns one classified intent
        whose ``mensaje`` is a substring (deliberately shorter than the
        original turn), simulating the production regression.
        """

        class _StubClassifier:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def query(self, message, **kwargs):
                return IntentClassificationResult(
                    intents=[
                        ClassifiedIntent(
                            intent=intent, mensaje=substring
                        ),
                    ],
                    mensaje=message,
                )

        return _StubClassifier()

    def test_set_fecha_hora_entrega_handler_receives_original_message(
        self,
    ) -> None:
        from backend.intents.orchestration import (
            initial_intent_dispatcher as dispatcher_module,
        )

        original_message = (
            "Quiero que me lo envíes mañana a las 8 de la noche"
        )
        substring = "a las 8"
        captured: dict[str, str] = {}

        def _capture(db, session, source_text, **kwargs):
            captured["source_text"] = source_text
            return ProcessedIntent(
                intent="set_fecha_hora_entrega",
                source_text=source_text,
                status="executed",
                recognizer="draft_order_closure",
                handler="set_fecha_hora_entrega",
                resolved_data={"accepted_format": "spanish_relative"},
            )

        with patch.object(
            dispatcher_module,
            "IntentClassifier",
            lambda *a, **k: self._make_classifier(
                intent=IntentName.SET_FECHA_HORA_ENTREGA,
                substring=substring,
            ),
        ):
            with patch.object(
                dispatcher_module,
                "process_initial_set_fecha_hora_entrega",
                side_effect=_capture,
            ):
                dispatch_initial_message(
                    MagicMock(),
                    MagicMock(context_type=None),
                    original_message,
                )

        self.assertEqual(captured["source_text"], original_message)

    def test_other_intent_handler_still_receives_classified_substring(
        self,
    ) -> None:
        from backend.intents.orchestration import (
            initial_intent_dispatcher as dispatcher_module,
        )

        original_message = "Por favor consultar el resumen de mi pedido"
        substring = "resumen"
        captured: dict[str, str] = {}

        def _capture(db, session, source_text):
            captured["source_text"] = source_text
            return ProcessedIntent(
                intent="consultar_resumen_pedido",
                source_text=source_text,
                status="executed",
                recognizer="draft_order_closure",
                handler="consultar_resumen_pedido",
                resolved_data={},
            )

        with patch.object(
            dispatcher_module,
            "IntentClassifier",
            lambda *a, **k: self._make_classifier(
                intent=IntentName.CONSULTAR_RESUMEN_PEDIDO,
                substring=substring,
            ),
        ):
            with patch.object(
                dispatcher_module,
                "process_initial_consultar_resumen_pedido",
                side_effect=_capture,
            ):
                dispatch_initial_message(
                    MagicMock(),
                    MagicMock(context_type=None),
                    original_message,
                )

        self.assertEqual(captured["source_text"], substring)
        self.assertNotEqual(captured["source_text"], original_message)

    def test_original_message_with_two_temporal_fragments_does_not_persist(
        self,
    ) -> None:
        from backend.intents.orchestration import (
            initial_intent_dispatcher as dispatcher_module,
        )

        original_message = (
            "Si, hoy a las 9 de la noche, mañana a las 8 de la mañana"
        )
        previous = datetime(
            2026, 8, 13, 10, 0,
            tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"),
        )
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.datetime_entrega_programada = previous

            with patch.object(
                dispatcher_module,
                "IntentClassifier",
                lambda *a, **k: self._make_classifier(
                    intent=IntentName.SET_FECHA_HORA_ENTREGA,
                    substring="hoy a las 9 de la noche",
                ),
            ):
                with patch.object(
                    closure_module, "datetime", wraps=datetime
                ) as mock_dt:
                    mock_dt.now.return_value = datetime(
                        2026, 8, 12, 6, 0,
                        tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"),
                    )
                    with TestingSessionLocal() as db:
                        session_row = db.get(
                            SessionModel, ids["session_id"]
                        )
                        assert session_row is not None
                        result = dispatch_initial_message(
                            db, session_row, original_message
                        )
                        db.commit()

            self.assertEqual(len(result), 1)
            intent = result[0]
            self.assertEqual(intent.intent, "set_fecha_hora_entrega")
            self.assertEqual(intent.status, "rejected")
            self.assertEqual(
                intent.resolved_data.get("reason"), "invalid_format"
            )

            pedido = _load_pedido(ids["pedido_id"])
            assert pedido is not None
            self.assertEqual(
                pedido.datetime_entrega_programada, previous
            )
        finally:
            _cleanup(ids)

    def test_source_preservation_does_not_leak_text_into_resolved_data(
        self,
    ) -> None:
        from backend.intents.orchestration import (
            initial_intent_dispatcher as dispatcher_module,
        )

        original_message = (
            "Quiero que me lo envíes mañana a las 8 de la noche"
        )
        substring = "a las 8"
        ids = _seed_base()
        try:
            with patch.object(
                dispatcher_module,
                "IntentClassifier",
                lambda *a, **k: self._make_classifier(
                    intent=IntentName.SET_FECHA_HORA_ENTREGA,
                    substring=substring,
                ),
            ):
                with patch.object(
                    closure_module, "datetime", wraps=datetime
                ) as mock_dt:
                    mock_dt.now.return_value = datetime(
                        2026, 8, 12, 6, 0,
                        tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"),
                    )
                    with TestingSessionLocal() as db:
                        session_row = db.get(
                            SessionModel, ids["session_id"]
                        )
                        assert session_row is not None
                        result = dispatch_initial_message(
                            db, session_row, original_message
                        )
                        db.commit()

            self.assertEqual(len(result), 1)
            intent = result[0]
            self.assertEqual(intent.status, "executed")
            self.assertEqual(
                intent.source_text, original_message
            )
            self.assertNotIn(substring, str(intent.resolved_data))
            for value in intent.resolved_data.values():
                self.assertNotIn(original_message, repr(value))
                self.assertNotIn("a las 8", repr(value))
            pedido = _load_pedido(ids["pedido_id"])
            assert pedido is not None
            self.assertEqual(
                pedido.datetime_entrega_programada,
                datetime(
                    2026, 8, 13, 20, 0,
                    tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"),
                ),
            )
        finally:
            _cleanup(ids)


class SetFechaHoraEntregaUnitTest(unittest.TestCase):
    @staticmethod
    def _session(
        *,
        session_id: int = 10,
        pedido_id: int | None = 20,
        estado_session=EstadoSession.ACTIVA,
    ) -> MagicMock:
        return MagicMock(
            id=session_id,
            id_pedido=pedido_id,
            estado_session=estado_session,
        )

    @staticmethod
    def _pedido(
        *,
        session_id: int = 10,
        estado_pedido=EstadoPedido.BORRADOR,
        previous_datetime: datetime | None = None,
    ) -> MagicMock:
        return MagicMock(
            id_session=session_id,
            estado_pedido=estado_pedido,
            datetime_entrega_programada=previous_datetime,
            id_medio_pago=30,
            id_metodo_entrega=40,
            observaciones="observación previa",
            direccion_entrega="dirección previa",
        )

    def test_inactive_session_rejects_without_lookup(self) -> None:
        db = MagicMock()
        result = process_initial_set_fecha_hora_entrega(
            db,
            self._session(estado_session=EstadoSession.CERRADA),
            "15/08/2026 19:30",
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(
            result.resolved_data.get("reason"), "session_not_active"
        )
        db.get.assert_not_called()

    def test_no_draft_rejects_without_lookup(self) -> None:
        db = MagicMock()
        result = process_initial_set_fecha_hora_entrega(
            db,
            self._session(pedido_id=None),
            "15/08/2026 19:30",
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.resolved_data.get("reason"), "no_draft")
        db.get.assert_not_called()

    def test_missing_pedido_row_rejects(self) -> None:
        db = MagicMock()
        db.get.return_value = None
        result = process_initial_set_fecha_hora_entrega(
            db, self._session(), "15/08/2026 19:30"
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.resolved_data.get("reason"), "no_draft")

    def test_foreign_session_pedido_rejects_and_preserves(self) -> None:
        previous = datetime(2027, 1, 1, tzinfo=ZoneInfo("UTC"))
        pedido = self._pedido(session_id=99, previous_datetime=previous)
        db = MagicMock()
        db.get.return_value = pedido
        result = process_initial_set_fecha_hora_entrega(
            db, self._session(), "15/08/2026 19:30"
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(
            result.resolved_data.get("reason"), "session_mismatch"
        )
        self.assertIs(pedido.datetime_entrega_programada, previous)

    def test_non_borrador_pedido_rejects_for_each_state(self) -> None:
        for state in (
            EstadoPedido.INGRESADO,
            EstadoPedido.PREPARACION,
            EstadoPedido.TERMINADO,
            EstadoPedido.ENTREGADO,
            EstadoPedido.CANCELADO,
        ):
            with self.subTest(state=state.value):
                previous = datetime(2027, 1, 1, tzinfo=ZoneInfo("UTC"))
                pedido = self._pedido(
                    estado_pedido=state,
                    previous_datetime=previous,
                )
                db = MagicMock()
                db.get.return_value = pedido
                result = process_initial_set_fecha_hora_entrega(
                    db, self._session(), "15/08/2026 19:30"
                )
                self.assertEqual(result.status, "rejected")
                self.assertEqual(
                    result.resolved_data.get("reason"),
                    "pedido_not_borrador",
                )
                self.assertIs(pedido.datetime_entrega_programada, previous)

    def test_only_exact_documented_formats_are_accepted(self) -> None:
        timezone = ZoneInfo("America/Argentina/Buenos_Aires")
        scheduled = datetime.now(timezone) + timedelta(days=30)
        for source_text, expected_format in (
            (
                f"  {scheduled.strftime('%d/%m/%Y %H:%M')}  ",
                "dd/mm/yyyy_hh:mm",
            ),
            (
                f"\t{scheduled.strftime('%Y-%m-%d %H:%M')}\n",
                "yyyy-mm-dd_hh:mm",
            ),
        ):
            with self.subTest(source_text=source_text):
                previous = datetime(2027, 1, 1, tzinfo=timezone)
                pedido = self._pedido(previous_datetime=previous)
                db = MagicMock()
                db.get.return_value = pedido
                result = process_initial_set_fecha_hora_entrega(
                    db, self._session(), source_text
                )
                self.assertEqual(result.status, "executed")
                self.assertEqual(
                    result.resolved_data,
                    {"accepted_format": expected_format},
                )
                self.assertIsNotNone(pedido.datetime_entrega_programada)
                self.assertEqual(
                    pedido.datetime_entrega_programada,
                    scheduled.replace(second=0, microsecond=0),
                )
                self.assertEqual(
                    pedido.datetime_entrega_programada.utcoffset(),
                    scheduled.utcoffset(),
                )
                self.assertEqual(
                    pedido.datetime_entrega_programada.tzinfo.key,
                    "America/Argentina/Buenos_Aires",
                )

    def test_invalid_calendar_values_return_invalid_format(self) -> None:
        for source_text in (
            "31/02/2027 19:30",
            "2027-13-15 19:30",
            "15/12/2027 25:30",
        ):
            with self.subTest(source_text=source_text):
                parsed_datetime, label = (
                    closure_module._parse_fecha_hora_entrega(source_text)
                )
                self.assertIsNone(parsed_datetime)
                self.assertEqual(label, "invalid_format")

    def test_invalid_and_ambiguous_inputs_reject_and_preserve(self) -> None:
        for source_text in (
            "31/02/2027 19:30",
            "2027-13-15 19:30",
            "15/12/2027 25:30",
            "mañana",
            "15/08/2026",
            "19:30",
            "15/8/2026 19:30",
            "2026-8-15 19:30",
            "15/08/26 19:30",
            "15/08/2026 7:30",
            "15/08/2026 19:30 mañana",
            "2026-08-15T19:30",
            "2026-08-15 19:30 -03:00",
            "15-08-2026 19:30",
        ):
            with self.subTest(source_text=source_text):
                previous = datetime(2027, 1, 1, tzinfo=ZoneInfo("UTC"))
                pedido = self._pedido(previous_datetime=previous)
                db = MagicMock()
                db.get.return_value = pedido
                result = process_initial_set_fecha_hora_entrega(
                    db, self._session(), source_text
                )
                self.assertEqual(result.status, "rejected")
                self.assertEqual(
                    result.resolved_data.get("reason"), "invalid_format"
                )
                self.assertIs(pedido.datetime_entrega_programada, previous)

    def test_past_datetime_rejects_and_preserves(self) -> None:
        timezone = ZoneInfo("America/Argentina/Buenos_Aires")
        previous = datetime(2027, 1, 1, tzinfo=timezone)
        pedido = self._pedido(previous_datetime=previous)
        db = MagicMock()
        db.get.return_value = pedido
        past = datetime.now(timezone) - timedelta(days=1)
        result = process_initial_set_fecha_hora_entrega(
            db,
            self._session(),
            past.strftime("%d/%m/%Y %H:%M"),
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(
            result.resolved_data.get("reason"), "past_datetime"
        )
        self.assertIs(pedido.datetime_entrega_programada, previous)

    def test_replacement_only_mutates_delivery_datetime(self) -> None:
        timezone = ZoneInfo("America/Argentina/Buenos_Aires")
        previous = datetime(2027, 1, 1, tzinfo=timezone)
        pedido = self._pedido(previous_datetime=previous)
        db = MagicMock()
        db.get.return_value = pedido
        scheduled = datetime.now(timezone) + timedelta(days=7)
        result = process_initial_set_fecha_hora_entrega(
            db,
            self._session(),
            scheduled.strftime("%d/%m/%Y %H:%M"),
        )
        self.assertEqual(result.status, "executed")
        self.assertEqual(
            pedido.datetime_entrega_programada,
            scheduled.replace(second=0, microsecond=0),
        )
        self.assertEqual(pedido.id_medio_pago, 30)
        self.assertEqual(pedido.id_metodo_entrega, 40)
        self.assertEqual(pedido.observaciones, "observación previa")
        self.assertEqual(pedido.direccion_entrega, "dirección previa")
        self.assertEqual(pedido.estado_pedido, EstadoPedido.BORRADOR)

    def test_no_transaction_control_methods_called(self) -> None:
        timezone = ZoneInfo("America/Argentina/Buenos_Aires")
        scheduled = datetime.now(timezone) + timedelta(days=7)
        db = MagicMock()
        db.get.return_value = self._pedido()
        result = process_initial_set_fecha_hora_entrega(
            db,
            self._session(),
            scheduled.strftime("%d/%m/%Y %H:%M"),
        )
        self.assertEqual(result.status, "executed")
        for method in (
            "commit",
            "rollback",
            "begin",
            "flush",
            "refresh",
            "expire",
            "close",
        ):
            getattr(db, method).assert_not_called()

    def test_resolved_data_contains_only_safe_format_indicator(self) -> None:
        timezone = ZoneInfo("America/Argentina/Buenos_Aires")
        scheduled = datetime.now(timezone) + timedelta(days=7)
        db = MagicMock()
        db.get.return_value = self._pedido()
        result = process_initial_set_fecha_hora_entrega(
            db,
            self._session(),
            scheduled.strftime("%d/%m/%Y %H:%M"),
        )
        datetime_text = scheduled.isoformat()
        for value in result.resolved_data.values():
            self.assertNotIn(datetime_text, repr(value))


class ParseSpanishExpressionTest(unittest.TestCase):
    """Pure parser tests for the Spanish temporal-expression extension."""

    @staticmethod
    def _now() -> datetime:
        return datetime(2026, 8, 12, 6, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))

    def _assert_success(
        self,
        source_text: str,
        expected: datetime,
    ) -> None:
        parsed, label = closure_module._parse_fecha_hora_entrega(
            source_text, now=self._now()
        )
        self.assertEqual(parsed, expected)
        self.assertEqual(label, "spanish_relative")

    def _assert_rejected(
        self,
        source_text: str,
        reason: str,
    ) -> None:
        parsed, label = closure_module._parse_fecha_hora_entrega(
            source_text, now=self._now()
        )
        self.assertIsNone(parsed)
        self.assertEqual(label, reason)

    def test_hoy_a_las_22_horas_persists_today_22(self) -> None:
        self._assert_success(
            "hoy a las 22 horas",
            datetime(2026, 8, 12, 22, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
        )

    def test_hoy_a_las_22_sin_horas_persists_today_22(self) -> None:
        self._assert_success(
            "hoy a las 22",
            datetime(2026, 8, 12, 22, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
        )

    def test_hoy_a_las_8_uses_24_hour_zero_padded(self) -> None:
        self._assert_success(
            "hoy a las 8",
            datetime(2026, 8, 12, 8, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
        )

    def test_hoy_a_las_8_30_persists_minutes(self) -> None:
        self._assert_success(
            "hoy a las 8:30",
            datetime(2026, 8, 12, 8, 30, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
        )

    def test_wrapped_hoy_a_las_22_horas_persists_when_contiguous(self) -> None:
        self._assert_success(
            "Quiero que me lo envíes hoy a las 22 horas",
            datetime(2026, 8, 12, 22, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
        )

    def test_manana_a_las_6_tarde_translates_to_18(self) -> None:
        self._assert_success(
            "mañana a las 6 de la tarde",
            datetime(2026, 8, 13, 18, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
        )

    def test_manana_a_las_9_manana_keeps_hour(self) -> None:
        self._assert_success(
            "mañana a las 9 de la mañana",
            datetime(2026, 8, 13, 9, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
        )

    def test_manana_a_las_11_noche_translates_to_23(self) -> None:
        self._assert_success(
            "mañana a las 11 de la noche",
            datetime(2026, 8, 13, 23, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
        )

    def test_manana_a_las_12_tarde_keeps_noon(self) -> None:
        self._assert_success(
            "mañana a las 12 de la tarde",
            datetime(2026, 8, 13, 12, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
        )

    def test_manana_a_las_12_manana_is_ambiguous_invalid(self) -> None:
        self._assert_rejected(
            "hoy a las 12 de la mañana",
            "invalid_format",
        )

    def test_manana_a_las_12_noche_is_ambiguous_invalid(self) -> None:
        self._assert_rejected(
            "hoy a las 12 de la noche",
            "invalid_format",
        )

    def test_manana_a_las_13_con_manana_is_out_of_range(self) -> None:
        self._assert_rejected(
            "mañana a las 13 de la mañana",
            "invalid_format",
        )

    def test_hoy_a_las_24_is_out_of_range(self) -> None:
        self._assert_rejected(
            "hoy a las 24",
            "invalid_format",
        )

    def test_el_viernes_a_las_20_resolves_to_next_friday(self) -> None:
        self._assert_success(
            "el viernes a las 20",
            datetime(2026, 8, 14, 20, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
        )

    def test_viernes_a_las_20_without_el_resolves_to_next_friday(self) -> None:
        self._assert_success(
            "viernes a las 20",
            datetime(2026, 8, 14, 20, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
        )

    def test_el_sabado_a_las_10_with_accents_normalizes(self) -> None:
        self._assert_success(
            "el sábado a las 10",
            datetime(2026, 8, 15, 10, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")),
        )

    def test_a_las_11_noche_without_date_is_needs_date(self) -> None:
        self._assert_rejected(
            "a las 11 de la noche",
            "needs_date",
        )

    def test_a_las_8_without_date_and_without_qualifier_is_invalid(self) -> None:
        self._assert_rejected(
            "A las 8",
            "invalid_format",
        )

    def test_a_las_20_without_date_without_qualifier_is_needs_date(self) -> None:
        self._assert_rejected(
            "a las 20",
            "needs_date",
        )

    def test_two_temporal_fragments_is_invalid(self) -> None:
        self._assert_rejected(
            "hoy a las 8 y mañana a las 9",
            "invalid_format",
        )

    def test_en_dos_horas_is_invalid(self) -> None:
        self._assert_rejected("En dos horas", "invalid_format")

    def test_entre_19_y_20_is_invalid(self) -> None:
        self._assert_rejected("Entre 19 y 20", "invalid_format")

    def test_al_mediodia_is_invalid(self) -> None:
        self._assert_rejected("Al mediodía", "invalid_format")

    def test_manana_temprano_is_invalid(self) -> None:
        self._assert_rejected("Mañana temprano", "invalid_format")

    def test_tipo_8_is_invalid(self) -> None:
        self._assert_rejected("Tipo 8", "invalid_format")

    def test_hoy_a_las_22_after_22_is_past_not_rolled_over(self) -> None:
        late_now = datetime(
            2026, 8, 12, 23, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")
        )
        parsed, label = closure_module._parse_fecha_hora_entrega(
            "hoy a las 22", now=late_now
        )
        self.assertIsNone(parsed)
        self.assertEqual(label, "past_datetime")

    def test_past_hoy_does_not_advance_to_manana(self) -> None:
        late_now = datetime(
            2026, 8, 12, 23, 30, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")
        )
        with TestingSessionLocal() as db:
            pedido_row = self._seed_pedido_with_datetime(
                datetime(
                    2026, 8, 13, 10, 0,
                    tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"),
                )
            )
            try:
                session_row = db.get(SessionModel, pedido_row["session_id"])
                assert session_row is not None
                with patch.object(
                    closure_module, "datetime", wraps=datetime
                ) as mock_dt:
                    mock_dt.now.return_value = late_now
                    result = process_initial_set_fecha_hora_entrega(
                        db, session_row, "hoy a las 22"
                    )
                self.assertEqual(result.status, "rejected")
                self.assertEqual(
                    result.resolved_data.get("reason"), "past_datetime"
                )
                with TestingSessionLocal() as verify_db:
                    pedido = verify_db.get(Pedido, pedido_row["pedido_id"])
                    assert pedido is not None
                    self.assertEqual(
                        pedido.datetime_entrega_programada,
                        datetime(
                            2026, 8, 13, 10, 0,
                            tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"),
                        ),
                    )
            finally:
                _cleanup_pedido(pedido_row)

    @staticmethod
    def _seed_pedido_with_datetime(
        previous: datetime,
    ) -> dict:
        ids = _seed_base()
        with TestingSessionLocal() as db, db.begin():
            pedido = db.get(Pedido, ids["pedido_id"])
            assert pedido is not None
            pedido.datetime_entrega_programada = previous
        return ids


def _cleanup_pedido(ids: dict) -> None:
    _cleanup(ids)


class TimeOnlyFragmentValidationTest(unittest.TestCase):
    """Hour validation for time-only Spanish fragments (no date token).

    A time-only hour is unambiguous (returns ``needs_date``) when:

    - the hour is in 13-23 with no qualifier (24-hour interpretation);
    - the hour is in 1-11 with ``de la mañana``, ``de la tarde`` or
      ``de la noche``;
    - the hour is 12 with ``de la tarde`` (interpreted as 12:xx).

    All other hours (``A las 8``, out-of-range, ambiguous noon with
    ``de la mañana`` or ``de la noche``) return ``invalid_format``.
    """

    @staticmethod
    def _now() -> datetime:
        return datetime(
            2026, 8, 12, 6, 0,
            tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"),
        )

    def _assert(self, source_text: str, expected_reason: str) -> None:
        parsed, label = closure_module._parse_fecha_hora_entrega(
            source_text, now=self._now()
        )
        self.assertIsNone(parsed)
        self.assertEqual(label, expected_reason)

    def test_a_las_20_returns_needs_date(self) -> None:
        self._assert("a las 20", "needs_date")

    def test_a_las_22_horas_returns_needs_date(self) -> None:
        self._assert("a las 22 horas", "needs_date")

    def test_a_las_11_noche_returns_needs_date(self) -> None:
        self._assert("a las 11 de la noche", "needs_date")

    def test_a_las_6_tarde_returns_needs_date(self) -> None:
        self._assert("a las 6 de la tarde", "needs_date")

    def test_a_las_9_manana_returns_needs_date(self) -> None:
        self._assert("a las 9 de la mañana", "needs_date")

    def test_a_las_12_tarde_returns_needs_date(self) -> None:
        self._assert("a las 12 de la tarde", "needs_date")

    def test_a_las_8_sin_calificador_returns_invalid_format(self) -> None:
        self._assert("A las 8", "invalid_format")

    def test_a_las_25_returns_invalid_format(self) -> None:
        self._assert("a las 25", "invalid_format")

    def test_a_las_99_tarde_returns_invalid_format(self) -> None:
        self._assert("a las 99 de la tarde", "invalid_format")

    def test_a_las_12_manana_returns_invalid_format(self) -> None:
        self._assert("a las 12 de la mañana", "invalid_format")

    def test_a_las_12_noche_returns_invalid_format(self) -> None:
        self._assert("a las 12 de la noche", "invalid_format")

    def test_a_las_13_manana_returns_invalid_format(self) -> None:
        self._assert("a las 13 de la mañana", "invalid_format")

    def test_two_a_las_clauses_returns_invalid_format(self) -> None:
        self._assert(
            "lo envío a las 20 y lo entregamos a las 21",
            "invalid_format",
        )


class SingleClockInjectionTest(unittest.TestCase):
    """The orchestrator must capture ``datetime.now(tz)`` at most once
    per invocation and pass the same reference to the parser and the
    future-check, so microscale clock drift cannot race the boundary
    comparison.
    """

    @staticmethod
    def _now() -> datetime:
        return datetime(
            2026, 8, 12, 6, 0,
            tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"),
        )

    def _stub_db(self) -> MagicMock:
        db = MagicMock()
        db.get.return_value = MagicMock(
            id_session=10,
            estado_pedido=EstadoPedido.BORRADOR,
        )
        return db

    def test_orchestrator_captures_datetime_now_exactly_once(self) -> None:
        captured_now = self._now()
        call_counter = {"n": 0}

        def _counting_now(tz=None):
            call_counter["n"] += 1
            return captured_now

        with patch.object(
            closure_module, "datetime", wraps=datetime
        ) as mock_dt:
            mock_dt.now.side_effect = _counting_now
            result = process_initial_set_fecha_hora_entrega(
                self._stub_db(),
                MagicMock(
                    id=10,
                    id_pedido=20,
                    estado_session=EstadoSession.ACTIVA,
                ),
                "hoy a las 22 horas",
            )

        self.assertEqual(result.status, "executed")
        self.assertEqual(
            result.resolved_data, {"accepted_format": "spanish_relative"}
        )
        self.assertEqual(call_counter["n"], 1)

    def test_orchestrator_with_explicit_now_does_not_capture(self) -> None:
        explicit_now = self._now()
        call_counter = {"n": 0}

        def _counting_now(tz=None):
            call_counter["n"] += 1
            return explicit_now

        with patch.object(
            closure_module, "datetime", wraps=datetime
        ) as mock_dt:
            mock_dt.now.side_effect = _counting_now
            result = process_initial_set_fecha_hora_entrega(
                self._stub_db(),
                MagicMock(
                    id=10,
                    id_pedido=20,
                    estado_session=EstadoSession.ACTIVA,
                ),
                "hoy a las 22 horas",
                now=explicit_now,
            )

        self.assertEqual(result.status, "executed")
        self.assertEqual(call_counter["n"], 0)


class SetFechaHoraEntregaSpanishExpressionTest(unittest.TestCase):
    """Orchestrator-level coverage of the Spanish-expression extension."""

    @staticmethod
    def _now() -> datetime:
        return datetime(2026, 8, 12, 6, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))

    def _build_pedido(
        self,
        *,
        previous: datetime | None = None,
        estado=EstadoPedido.BORRADOR,
    ) -> dict:
        ids = _seed_base()
        if previous is not None:
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.datetime_entrega_programada = previous
        return ids

    def test_hoy_a_las_22_horas_persists_via_orchestrator(self) -> None:
        ids = self._build_pedido()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                with patch.object(
                    closure_module, "datetime", wraps=datetime
                ) as mock_dt:
                    mock_dt.now.return_value = self._now()
                    result = process_initial_set_fecha_hora_entrega(
                        db,
                        session_row,
                        "Quiero que me lo envíes hoy a las 22 horas",
                    )
                self.assertEqual(result.status, "executed")
                self.assertEqual(
                    result.resolved_data,
                    {"accepted_format": "spanish_relative"},
                )
                db.commit()
            pedido = _load_pedido(ids["pedido_id"])
            assert pedido is not None
            self.assertIsNotNone(pedido.datetime_entrega_programada)
            self.assertEqual(
                pedido.datetime_entrega_programada,
                datetime(
                    2026, 8, 12, 22, 0,
                    tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"),
                ),
            )
        finally:
            _cleanup(ids)

    def test_manana_a_las_6_tarde_persists_via_orchestrator(self) -> None:
        ids = self._build_pedido()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                with patch.object(
                    closure_module, "datetime", wraps=datetime
                ) as mock_dt:
                    mock_dt.now.return_value = self._now()
                    result = process_initial_set_fecha_hora_entrega(
                        db, session_row, "mañana a las 6 de la tarde"
                    )
                self.assertEqual(result.status, "executed")
                db.commit()
            pedido = _load_pedido(ids["pedido_id"])
            assert pedido is not None
            self.assertEqual(
                pedido.datetime_entrega_programada,
                datetime(
                    2026, 8, 13, 18, 0,
                    tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"),
                ),
            )
        finally:
            _cleanup(ids)

    def test_a_las_11_noche_returns_needs_date(self) -> None:
        ids = self._build_pedido()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                result = process_initial_set_fecha_hora_entrega(
                    db, session_row, "a las 11 de la noche"
                )
                self.assertEqual(result.status, "rejected")
                self.assertEqual(
                    result.resolved_data.get("reason"), "needs_date"
                )
                self.assertNotIn("a las 11 de la noche", str(
                    result.resolved_data
                ))
            pedido = _load_pedido(ids["pedido_id"])
            assert pedido is not None
            self.assertIsNone(pedido.datetime_entrega_programada)
        finally:
            _cleanup(ids)

    def test_hoy_past_datetime_returns_past_datetime_and_preserves(self) -> None:
        previous = datetime(
            2026, 8, 13, 10, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")
        )
        ids = self._build_pedido(previous=previous)
        try:
            late_now = datetime(
                2026, 8, 12, 23, 0,
                tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"),
            )
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                with patch.object(
                    closure_module, "datetime", wraps=datetime
                ) as mock_dt:
                    mock_dt.now.return_value = late_now
                    result = process_initial_set_fecha_hora_entrega(
                        db, session_row, "hoy a las 22"
                    )
                self.assertEqual(result.status, "rejected")
                self.assertEqual(
                    result.resolved_data.get("reason"), "past_datetime"
                )
                db.commit()
            pedido = _load_pedido(ids["pedido_id"])
            assert pedido is not None
            self.assertEqual(pedido.datetime_entrega_programada, previous)
        finally:
            _cleanup(ids)

    def test_invalid_format_does_not_mutate(self) -> None:
        previous = datetime(
            2026, 8, 13, 10, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires")
        )
        ids = self._build_pedido(previous=previous)
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                for source_text in (
                    "En dos horas",
                    "Entre 19 y 20",
                    "Tipo 8",
                    "Mañana temprano",
                    "Al mediodía",
                    "hoy a las 8 y mañana a las 9",
                ):
                    result = process_initial_set_fecha_hora_entrega(
                        db, session_row, source_text
                    )
                    self.assertEqual(
                        result.status, "rejected",
                        msg=f"unexpected status for {source_text!r}",
                    )
                    self.assertEqual(
                        result.resolved_data.get("reason"),
                        "invalid_format",
                        msg=f"unexpected reason for {source_text!r}",
                    )
                db.commit()
            pedido = _load_pedido(ids["pedido_id"])
            assert pedido is not None
            self.assertEqual(pedido.datetime_entrega_programada, previous)
        finally:
            _cleanup(ids)

    def test_spanish_success_changes_only_datetime(self) -> None:
        ids = self._build_pedido()
        try:
            _seed_line(pedido_id=ids["pedido_id"], pp_id=ids["pp_id"])
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.id_medio_pago = ids["medio_pago_id"]
                pedido.id_metodo_entrega = ids["metodo_entrega_id"]
                pedido.observaciones = "observación previa"
                pedido.direccion_entrega = "dirección previa"
                pedido_id_session = pedido.id_session

            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                with patch.object(
                    closure_module, "datetime", wraps=datetime
                ) as mock_dt:
                    mock_dt.now.return_value = self._now()
                    result = process_initial_set_fecha_hora_entrega(
                        db, session_row, "mañana a las 9 de la mañana"
                    )
                self.assertEqual(result.status, "executed")
                db.commit()

            pedido = _load_pedido(ids["pedido_id"])
            assert pedido is not None
            self.assertEqual(
                pedido.datetime_entrega_programada,
                datetime(
                    2026, 8, 13, 9, 0,
                    tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"),
                ),
            )
            self.assertEqual(pedido.id_session, pedido_id_session)
            self.assertEqual(pedido.id_medio_pago, ids["medio_pago_id"])
            self.assertEqual(
                pedido.id_metodo_entrega, ids["metodo_entrega_id"]
            )
            self.assertEqual(pedido.observaciones, "observación previa")
            self.assertEqual(pedido.direccion_entrega, "dirección previa")
            self.assertEqual(pedido.estado_pedido, EstadoPedido.BORRADOR)
        finally:
            _cleanup(ids)

    def test_spanish_does_not_call_transaction_control_methods(self) -> None:
        timezone = ZoneInfo("America/Argentina/Buenos_Aires")
        ids = _seed_base()
        try:
            db_mock = MagicMock()
            db_mock.get.return_value = MagicMock(
                id_session=ids["session_id"],
                estado_pedido=EstadoPedido.BORRADOR,
            )
            with patch.object(
                closure_module, "datetime", wraps=datetime
            ) as mock_dt:
                mock_dt.now.return_value = datetime(2026, 8, 12, 6, 0, tzinfo=timezone)
                result = process_initial_set_fecha_hora_entrega(
                    db_mock,
                    MagicMock(
                        id=ids["session_id"],
                        id_pedido=ids["pedido_id"],
                        estado_session=EstadoSession.ACTIVA,
                    ),
                    "hoy a las 22 horas",
                )
            self.assertEqual(result.status, "executed")
            for method in (
                "commit",
                "rollback",
                "begin",
                "flush",
                "refresh",
                "expire",
                "close",
            ):
                getattr(db_mock, method).assert_not_called()
        finally:
            _cleanup(ids)

    def test_spanish_resolved_data_does_not_leak_datetime_or_text(self) -> None:
        ids = self._build_pedido()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                with patch.object(
                    closure_module, "datetime", wraps=datetime
                ) as mock_dt:
                    mock_dt.now.return_value = self._now()
                    result = process_initial_set_fecha_hora_entrega(
                        db,
                        session_row,
                        "Quiero que me lo envíes hoy a las 22 horas",
                    )
                self.assertEqual(result.status, "executed")
                for value in result.resolved_data.values():
                    self.assertNotIn("22", repr(value))
                    self.assertNotIn("horas", repr(value))
                    self.assertNotIn("hoy", repr(value))
        finally:
            _cleanup(ids)


class SetFechaHoraEntregaLocalPipelineSpanishTest(unittest.TestCase):
    """Integration: end-to-end local pipeline renders the fixed
    private messages for the Spanish-expression extension.
    """

    @staticmethod
    def _now() -> datetime:
        return datetime(2026, 8, 12, 6, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))

    def test_success_renders_fixed_confirmation_without_leak(self) -> None:
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                with _patched_classifier(IntentName.SET_FECHA_HORA_ENTREGA):
                    with patch.object(
                        closure_module, "datetime", wraps=datetime
                    ) as mock_dt:
                        mock_dt.now.return_value = self._now()
                        responses = process_incoming_message_with_responses(
                            db,
                            session_row,
                            "Quiero que me lo envíes hoy a las 22 horas",
                        )
                self.assertEqual(len(responses), 1)
                response = responses[0]
                self.assertEqual(response.intent, "set_fecha_hora_entrega")
                self.assertEqual(response.status, "executed")
                self.assertEqual(
                    response.message,
                    "Listo, guardé la fecha y hora de entrega.",
                )
                self.assertNotIn("hoy", response.message)
                self.assertNotIn("22", response.message)
                self.assertNotIn("horas", response.message)
                self.assertNotIn(str(ids["pedido_id"]), response.message)
                db.commit()
        finally:
            _cleanup(ids)

    def test_needs_date_renders_distinct_message(self) -> None:
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                with _patched_classifier(IntentName.SET_FECHA_HORA_ENTREGA):
                    responses = process_incoming_message_with_responses(
                        db, session_row, "a las 11 de la noche"
                    )
                self.assertEqual(len(responses), 1)
                response = responses[0]
                self.assertEqual(response.intent, "set_fecha_hora_entrega")
                self.assertEqual(response.status, "rejected")
                self.assertIn("Necesito", response.message)
                self.assertNotIn(
                    "a las 11 de la noche", response.message
                )
                self.assertNotIn("pedido", str(response.intent))
                db.commit()
        finally:
            _cleanup(ids)

    def test_past_datetime_renders_distinct_message(self) -> None:
        ids = _seed_base()
        try:
            late_now = datetime(
                2026, 8, 12, 23, 0,
                tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"),
            )
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                with _patched_classifier(IntentName.SET_FECHA_HORA_ENTREGA):
                    with patch.object(
                        closure_module, "datetime", wraps=datetime
                    ) as mock_dt:
                        mock_dt.now.return_value = late_now
                        responses = process_incoming_message_with_responses(
                            db, session_row, "hoy a las 22"
                        )
                self.assertEqual(len(responses), 1)
                response = responses[0]
                self.assertEqual(response.intent, "set_fecha_hora_entrega")
                self.assertEqual(response.status, "rejected")
                self.assertIn("ya pasó", response.message)
                self.assertNotIn("hoy a las 22", response.message)
                db.commit()
        finally:
            _cleanup(ids)

    def test_invalid_format_renders_distinct_message(self) -> None:
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                with _patched_classifier(IntentName.SET_FECHA_HORA_ENTREGA):
                    responses = process_incoming_message_with_responses(
                        db, session_row, "En dos horas"
                    )
                self.assertEqual(len(responses), 1)
                response = responses[0]
                self.assertEqual(response.intent, "set_fecha_hora_entrega")
                self.assertEqual(response.status, "rejected")
                self.assertIn("'hoy'", response.message)
                self.assertNotIn("En dos horas", response.message)
                db.commit()
        finally:
            _cleanup(ids)


class SetDireccionEntregaUnitTest(unittest.TestCase):
    """Pure unit tests for ``process_initial_set_direccion_entrega``."""

    def _session(
        self,
        *,
        session_id: int = 10,
        pedido_id: int | None = 20,
        estado_session=EstadoSession.ACTIVA,
    ):
        session = MagicMock(
            id=session_id,
            id_pedido=pedido_id,
            estado_session=estado_session,
        )
        return session

    def test_no_pedido_associated_rejects_without_lookup(self) -> None:
        db = MagicMock()
        result = process_initial_set_direccion_entrega(
            db, self._session(pedido_id=None), "Tilcara 2020"
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.resolved_data.get("reason"), "no_draft")
        db.get.assert_not_called()

    def test_closed_session_rejects_without_reading_pedido(self) -> None:
        db = MagicMock()
        result = process_initial_set_direccion_entrega(
            db,
            self._session(estado_session=EstadoSession.CERRADA),
            "Tilcara 2020",
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(
            result.resolved_data.get("reason"), "session_not_active"
        )
        db.get.assert_not_called()

    def test_missing_pedido_row_rejects(self) -> None:
        db = MagicMock()
        db.get.return_value = None
        result = process_initial_set_direccion_entrega(
            db, self._session(), "Tilcara 2020"
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.resolved_data.get("reason"), "no_draft")

    def test_foreign_session_pedido_rejects(self) -> None:
        db = MagicMock()
        pedido = MagicMock(
            id_session=99,
            estado_pedido=EstadoPedido.BORRADOR,
        )
        db.get.return_value = pedido
        result = process_initial_set_direccion_entrega(
            db, self._session(), "Tilcara 2020"
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.resolved_data.get("reason"), "session_mismatch")
        pedido.direccion_entrega.assert_not_called()

    def test_non_borrador_pedido_rejects_for_each_state(self) -> None:
        for state in (
            EstadoPedido.INGRESADO,
            EstadoPedido.PREPARACION,
            EstadoPedido.TERMINADO,
            EstadoPedido.ENTREGADO,
            EstadoPedido.CANCELADO,
        ):
            with self.subTest(state=state.value):
                db = MagicMock()
                pedido = MagicMock(
                    id_session=10,
                    estado_pedido=state,
                )
                db.get.return_value = pedido
                result = process_initial_set_direccion_entrega(
                    db, self._session(), "Tilcara 2020"
                )
                self.assertEqual(result.status, "rejected")
                self.assertEqual(
                    result.resolved_data.get("reason"),
                    "pedido_not_borrador",
                )
                pedido.direccion_entrega.assert_not_called()

    def test_empty_text_rejects_and_preserves(self) -> None:
        pedido = MagicMock(
            id_session=10,
            estado_pedido=EstadoPedido.BORRADOR,
        )
        db = MagicMock()
        db.get.return_value = pedido
        for empty in ("", "   ", "\t\n", "\u00a0\u202f\u3000"):
            with self.subTest(raw=empty):
                result = process_initial_set_direccion_entrega(
                    db, self._session(), empty
                )
                self.assertEqual(result.status, "rejected")
                self.assertEqual(
                    result.resolved_data.get("reason"), "text_empty"
                )
        pedido.direccion_entrega.assert_not_called()

    def test_too_long_text_rejects_and_preserves(self) -> None:
        pedido = MagicMock(
            id_session=10,
            estado_pedido=EstadoPedido.BORRADOR,
        )
        db = MagicMock()
        db.get.return_value = pedido
        too_long = "x" * 501
        result = process_initial_set_direccion_entrega(
            db, self._session(), too_long
        )
        self.assertEqual(result.status, "rejected")
        self.assertEqual(
            result.resolved_data.get("reason"), "text_too_long"
        )
        pedido.direccion_entrega.assert_not_called()

    def test_unicode_whitespace_collapses_before_length_check(self) -> None:
        pedido = MagicMock(
            id_session=10,
            estado_pedido=EstadoPedido.BORRADOR,
        )
        db = MagicMock()
        db.get.return_value = pedido
        weird = (
            "\u00a0\u00a0Tilcara\u202f2020\u3000Piso\t2\n"
        )
        result = process_initial_set_direccion_entrega(
            db, self._session(), weird
        )
        self.assertEqual(result.status, "executed")
        self.assertEqual(
            pedido.direccion_entrega, "Tilcara 2020 Piso 2"
        )
        self.assertEqual(
            result.resolved_data.get("accepted_length"),
            len("Tilcara 2020 Piso 2"),
        )

    def test_accepted_length_one_is_accepted(self) -> None:
        pedido = MagicMock(
            id_session=10,
            estado_pedido=EstadoPedido.BORRADOR,
        )
        db = MagicMock()
        db.get.return_value = pedido
        result = process_initial_set_direccion_entrega(
            db, self._session(), "x"
        )
        self.assertEqual(result.status, "executed")
        self.assertEqual(pedido.direccion_entrega, "x")
        self.assertEqual(result.resolved_data.get("accepted_length"), 1)

    def test_accepted_length_500_is_accepted(self) -> None:
        pedido = MagicMock(
            id_session=10,
            estado_pedido=EstadoPedido.BORRADOR,
        )
        db = MagicMock()
        db.get.return_value = pedido
        text = "a" * 500
        result = process_initial_set_direccion_entrega(
            db, self._session(), text
        )
        self.assertEqual(result.status, "executed")
        self.assertEqual(pedido.direccion_entrega, text)
        self.assertEqual(result.resolved_data.get("accepted_length"), 500)

    def test_replacement_overwrites_previous_value(self) -> None:
        pedido = MagicMock(
            id_session=10,
            estado_pedido=EstadoPedido.BORRADOR,
        )
        db = MagicMock()
        db.get.return_value = pedido
        result = process_initial_set_direccion_entrega(
            db, self._session(), "Nueva 123"
        )
        self.assertEqual(result.status, "executed")
        self.assertEqual(pedido.direccion_entrega, "Nueva 123")

    def test_does_not_mutate_observaciones(self) -> None:
        pedido = MagicMock(
            id_session=10,
            estado_pedido=EstadoPedido.BORRADOR,
        )
        db = MagicMock()
        db.get.return_value = pedido
        result = process_initial_set_direccion_entrega(
            db, self._session(), "Tilcara 2020"
        )
        self.assertEqual(result.status, "executed")
        pedido.observaciones.assert_not_called()

    def test_no_transaction_control_methods_called(self) -> None:
        db = MagicMock()
        db.get.return_value = MagicMock(
            id_session=10,
            estado_pedido=EstadoPedido.BORRADOR,
        )
        process_initial_set_direccion_entrega(db, self._session(), "ok")
        for method in (
            "commit",
            "rollback",
            "begin",
            "flush",
            "refresh",
            "expire",
            "close",
        ):
            getattr(db, method).assert_not_called()

    def test_does_not_leak_raw_text_into_resolved_data(self) -> None:
        pedido = MagicMock(
            id_session=10,
            estado_pedido=EstadoPedido.BORRADOR,
        )
        db = MagicMock()
        db.get.return_value = pedido
        secret = "secret-direccion-payload-aaa"
        result = process_initial_set_direccion_entrega(
            db, self._session(), secret
        )
        self.assertNotIn(secret, result.resolved_data.values())
        for value in result.resolved_data.values():
            self.assertNotIn(secret, repr(value))


class SetDireccionEntregaIntegrationTest(unittest.TestCase):
    """PostgreSQL-backed tests for the full orchestrator + mapper chain."""

    def test_successful_replacement_of_null_address_persists(self) -> None:
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                result = process_initial_set_direccion_entrega(
                    db,
                    session_row,
                    "  Tilcara  2020  Piso 2 ",
                )
                self.assertEqual(result.status, "executed")
                self.assertEqual(
                    result.resolved_data.get("accepted_length"),
                    len("Tilcara 2020 Piso 2"),
                )
                db.commit()

            pedido = _load_pedido(ids["pedido_id"])
            assert pedido is not None
            self.assertEqual(pedido.direccion_entrega, "Tilcara 2020 Piso 2")
            self.assertEqual(pedido.estado_pedido, EstadoPedido.BORRADOR)
        finally:
            _cleanup(ids)

    def test_successful_replacement_of_existing_address(self) -> None:
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.direccion_entrega = "valor previo"

            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                result = process_initial_set_direccion_entrega(
                    db, session_row, "  nuevo valor "
                )
                self.assertEqual(result.status, "executed")
                db.commit()

            pedido = _load_pedido(ids["pedido_id"])
            assert pedido is not None
            self.assertEqual(pedido.direccion_entrega, "nuevo valor")
            self.assertEqual(pedido.estado_pedido, EstadoPedido.BORRADOR)
        finally:
            _cleanup(ids)

    def test_too_long_text_does_not_overwrite_existing(self) -> None:
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.direccion_entrega = "valor previo"

            text = "x" * 501
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                result = process_initial_set_direccion_entrega(
                    db, session_row, text
                )
                self.assertEqual(result.status, "rejected")
                self.assertEqual(
                    result.resolved_data.get("reason"), "text_too_long"
                )
                db.commit()

            pedido = _load_pedido(ids["pedido_id"])
            assert pedido is not None
            self.assertEqual(pedido.direccion_entrega, "valor previo")
        finally:
            _cleanup(ids)

    def test_empty_text_does_not_overwrite_existing(self) -> None:
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.direccion_entrega = "valor previo"

            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                result = process_initial_set_direccion_entrega(
                    db, session_row, "   \u00a0  "
                )
                self.assertEqual(result.status, "rejected")
                self.assertEqual(
                    result.resolved_data.get("reason"), "text_empty"
                )
                db.commit()

            pedido = _load_pedido(ids["pedido_id"])
            assert pedido is not None
            self.assertEqual(pedido.direccion_entrega, "valor previo")
        finally:
            _cleanup(ids)

    def test_successful_turn_does_not_alter_payment_or_method(self) -> None:
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.id_medio_pago = ids["medio_pago_id"]
                pedido.id_metodo_entrega = ids["metodo_entrega_id"]
                pedido.observaciones = "observacion previa"

            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                process_initial_set_direccion_entrega(
                    db, session_row, "Tilcara 2020"
                )
                db.commit()

            pedido = _load_pedido(ids["pedido_id"])
            assert pedido is not None
            self.assertEqual(
                pedido.id_medio_pago, ids["medio_pago_id"]
            )
            self.assertEqual(
                pedido.id_metodo_entrega, ids["metodo_entrega_id"]
            )
            self.assertEqual(pedido.observaciones, "observacion previa")
            self.assertEqual(pedido.direccion_entrega, "Tilcara 2020")
            self.assertEqual(pedido.estado_pedido, EstadoPedido.BORRADOR)
        finally:
            _cleanup(ids)

    def test_successful_turn_does_not_change_lines(self) -> None:
        ids = _seed_base()
        try:
            line_id = _seed_line(
                pedido_id=ids["pedido_id"], pp_id=ids["pp_id"]
            )
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                process_initial_set_direccion_entrega(
                    db, session_row, "Tilcara 2020"
                )
                db.commit()
            with TestingSessionLocal() as db:
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                self.assertEqual(pedido.direccion_entrega, "Tilcara 2020")
                lines = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == ids["pedido_id"]
                    )
                ).scalars().all()
                self.assertEqual([line.id for line in lines], [line_id])
                self.assertEqual(lines[0].cantidad, 1)
        finally:
            _cleanup(ids)

    def test_successful_turn_does_not_alter_pending_state(self) -> None:
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db, db.begin():
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                session_row.pending_intents = {
                    "active": {
                        "intent": "vaciar_pedido",
                        "status": "pending_resolution",
                        "source_text": "vaciar",
                        "recognizer": "vaciar_pedido",
                        "handler": "vaciar_pedido",
                        "resolved_data": {"pedido_id": ids["pedido_id"]},
                        "requirements": [
                            {
                                "name": "confirmacion",
                                "status": "pending",
                                "value": None,
                            }
                        ],
                        "candidate_ids": [],
                    },
                    "queue": [],
                }
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                process_initial_set_direccion_entrega(
                    db, session_row, "Tilcara 2020"
                )
                db.commit()
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                self.assertIsNotNone(session_row.pending_intents)
                self.assertEqual(
                    session_row.pending_intents["active"]["intent"],
                    "vaciar_pedido",
                )
        finally:
            _cleanup(ids)

    def test_technical_failure_after_staging_rolls_back_entire_turn(
        self,
    ) -> None:
        ids = _seed_base()
        try:
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.direccion_entrega = "valor previo"

            class _BoomOnCommit(Exception):
                pass

            class _ExplodingSession:
                def __init__(self, real) -> None:
                    self._real = real

                def get(self, *args, **kwargs):
                    return self._real.get(*args, **kwargs)

                def commit(self):
                    raise _BoomOnCommit("simulated technical failure")

                def rollback(self):
                    self._real.rollback()

            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                wrapped = _ExplodingSession(db)
                process_initial_set_direccion_entrega(
                    wrapped, session_row, "Tilcara 2020"
                )
                with self.assertRaises(_BoomOnCommit):
                    wrapped.commit()
                wrapped.rollback()

            pedido = _load_pedido(ids["pedido_id"])
            assert pedido is not None
            self.assertEqual(pedido.direccion_entrega, "valor previo")
        finally:
            _cleanup(ids)


class SetFechaHoraEntregaIntegrationTest(unittest.TestCase):
    def test_success_persists_authoritative_timezone(self) -> None:
        ids = _seed_base()
        try:
            timezone = ZoneInfo("America/Argentina/Buenos_Aires")
            scheduled = datetime.now(timezone) + timedelta(days=7)
            source_text = scheduled.strftime("%d/%m/%Y %H:%M")
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                result = process_initial_set_fecha_hora_entrega(
                    db, session_row, source_text
                )
                self.assertEqual(result.status, "executed")
                self.assertEqual(
                    result.resolved_data,
                    {"accepted_format": "dd/mm/yyyy_hh:mm"},
                )
                db.commit()

            pedido = _load_pedido(ids["pedido_id"])
            assert pedido is not None
            self.assertIsNotNone(pedido.datetime_entrega_programada)
            self.assertEqual(
                pedido.datetime_entrega_programada,
                scheduled.replace(second=0, microsecond=0),
            )
            self.assertEqual(
                pedido.datetime_entrega_programada.tzinfo.key,
                "America/Argentina/Buenos_Aires",
            )
        finally:
            _cleanup(ids)

    def test_success_replaces_existing_schedule(self) -> None:
        ids = _seed_base()
        try:
            timezone = ZoneInfo("America/Argentina/Buenos_Aires")
            previous = datetime.now(timezone) + timedelta(days=1)
            replacement = previous + timedelta(days=1)
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.datetime_entrega_programada = previous

            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                result = process_initial_set_fecha_hora_entrega(
                    db,
                    session_row,
                    replacement.strftime("%Y-%m-%d %H:%M"),
                )
                self.assertEqual(result.status, "executed")
                self.assertEqual(
                    result.resolved_data,
                    {"accepted_format": "yyyy-mm-dd_hh:mm"},
                )
                db.commit()

            pedido = _load_pedido(ids["pedido_id"])
            assert pedido is not None
            self.assertEqual(
                pedido.datetime_entrega_programada,
                replacement.replace(second=0, microsecond=0),
            )
        finally:
            _cleanup(ids)

    def test_invalid_and_past_inputs_preserve_existing_schedule(self) -> None:
        ids = _seed_base()
        try:
            timezone = ZoneInfo("America/Argentina/Buenos_Aires")
            previous = datetime.now(timezone) + timedelta(days=1)
            past = datetime.now(timezone) - timedelta(days=1)
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.datetime_entrega_programada = previous

            for source_text, expected_reason in (
                ("15/08/2026", "invalid_format"),
                (past.strftime("%d/%m/%Y %H:%M"), "past_datetime"),
            ):
                with self.subTest(source_text=source_text):
                    with TestingSessionLocal() as db:
                        session_row = db.get(SessionModel, ids["session_id"])
                        assert session_row is not None
                        result = process_initial_set_fecha_hora_entrega(
                            db, session_row, source_text
                        )
                        self.assertEqual(result.status, "rejected")
                        self.assertEqual(
                            result.resolved_data.get("reason"),
                            expected_reason,
                        )
                        db.commit()

                    pedido = _load_pedido(ids["pedido_id"])
                    assert pedido is not None
                    self.assertEqual(
                        pedido.datetime_entrega_programada,
                        previous,
                    )
        finally:
            _cleanup(ids)

    def test_success_changes_only_delivery_schedule(self) -> None:
        ids = _seed_base()
        try:
            line_id = _seed_line(pedido_id=ids["pedido_id"], pp_id=ids["pp_id"])
            pending_intents = {"active": "vaciar_pedido", "queue": []}
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.id_medio_pago = ids["medio_pago_id"]
                pedido.id_metodo_entrega = ids["metodo_entrega_id"]
                pedido.observaciones = "observación previa"
                pedido.direccion_entrega = "dirección previa"
                pedido_id_session = pedido.id_session
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                session_row.pending_intents = pending_intents
                session_before = {
                    "id_pedido": session_row.id_pedido,
                    "context_type": session_row.context_type,
                }

            timezone = ZoneInfo("America/Argentina/Buenos_Aires")
            scheduled = datetime.now(timezone) + timedelta(days=7)
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                result = process_initial_set_fecha_hora_entrega(
                    db,
                    session_row,
                    scheduled.strftime("%d/%m/%Y %H:%M"),
                )
                self.assertEqual(result.status, "executed")
                db.commit()

            pedido = _load_pedido(ids["pedido_id"])
            assert pedido is not None
            self.assertEqual(
                pedido.datetime_entrega_programada,
                scheduled.replace(second=0, microsecond=0),
            )
            self.assertEqual(pedido.id_session, pedido_id_session)
            self.assertEqual(pedido.id_medio_pago, ids["medio_pago_id"])
            self.assertEqual(
                pedido.id_metodo_entrega,
                ids["metodo_entrega_id"],
            )
            self.assertEqual(pedido.observaciones, "observación previa")
            self.assertEqual(pedido.direccion_entrega, "dirección previa")
            self.assertEqual(pedido.estado_pedido, EstadoPedido.BORRADOR)
            lines = _load_lines(ids["pedido_id"])
            self.assertEqual([line.id for line in lines], [line_id])
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                self.assertEqual(
                    session_row.id_pedido,
                    session_before["id_pedido"],
                )
                self.assertEqual(
                    session_row.context_type,
                    session_before["context_type"],
                )
                self.assertEqual(session_row.pending_intents, pending_intents)
        finally:
            _cleanup(ids)

    def test_outer_rollback_restores_prior_schedule(self) -> None:
        ids = _seed_base()
        try:
            timezone = ZoneInfo("America/Argentina/Buenos_Aires")
            previous = datetime.now(timezone) + timedelta(days=1)
            with TestingSessionLocal() as db, db.begin():
                pedido = db.get(Pedido, ids["pedido_id"])
                assert pedido is not None
                pedido.datetime_entrega_programada = previous

            class _BoomOnCommit(Exception):
                pass

            class _ExplodingSession:
                def __init__(self, real) -> None:
                    self._real = real

                def get(self, *args, **kwargs):
                    return self._real.get(*args, **kwargs)

                def commit(self):
                    raise _BoomOnCommit("simulated technical failure")

                def rollback(self):
                    self._real.rollback()

            timezone = ZoneInfo("America/Argentina/Buenos_Aires")
            scheduled = datetime.now(timezone) + timedelta(days=7)
            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, ids["session_id"])
                assert session_row is not None
                wrapped = _ExplodingSession(db)
                result = process_initial_set_fecha_hora_entrega(
                    wrapped,
                    session_row,
                    scheduled.strftime("%d/%m/%Y %H:%M"),
                )
                self.assertEqual(result.status, "executed")
                with self.assertRaises(_BoomOnCommit):
                    wrapped.commit()
                wrapped.rollback()

            pedido = _load_pedido(ids["pedido_id"])
            assert pedido is not None
            self.assertEqual(pedido.datetime_entrega_programada, previous)
        finally:
            _cleanup(ids)


def _load_lines(pedido_id: int) -> list[PedidoProducto]:
    with TestingSessionLocal() as db:
        return list(
            db.execute(
                select(PedidoProducto).where(
                    PedidoProducto.id_pedido == pedido_id
                )
            ).scalars()
        )


def _load_pedido(pedido_id: int) -> Pedido | None:
    with TestingSessionLocal() as db:
        return db.get(Pedido, pedido_id)


if __name__ == "__main__":
    unittest.main()
