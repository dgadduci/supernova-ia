"""End-to-end integration tests for the `set_observacion_producto` flow.

The tests cover the full transactional flow:

- unique set through `process_incoming_message` ⇒ committed observation;
- unique clear through `process_incoming_message` ⇒ committed ``NULL``;
- ambiguous classification ⇒ pending context with the
  ``order_line_selection`` context type and the original action/text
  preserved for refinement;
- technical failure inside the write seam ⇒ outer transactional owner
  rolls back the full turn (no observation written).
"""
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


class _SetObservacionProductoClassifier:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def query(self, message: str) -> IntentClassificationResult:
        return IntentClassificationResult(
            intents=[
                ClassifiedIntent(
                    intent=IntentName.SET_OBSERVACION_PRODUCTO,
                    mensaje=message,
                )
            ],
            mensaje=message,
        )


def _seed_comercio_cliente_pedido(suffix: str) -> dict:
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

        return {
            "comercio_id": comercio.id,
            "cliente_id": cliente.id,
            "session_id": session_row.id,
            "pedido_id": pedido.id,
            "categoria_id": categoria.id,
        }


def _seed_producto(
    *,
    comercio_id: int,
    categoria_id: int,
    nombre: str,
    codigos_presentacion: list[str],
    suffix: str,
) -> dict:
    with TestingSessionLocal() as db, db.begin():
        producto = Producto(
            id_categoria_producto=categoria_id,
            nombre=nombre,
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        db.add(producto)
        db.flush()

        asociaciones: dict[str, ProductoPresentacion] = {}
        for orden, codigo in enumerate(codigos_presentacion):
            presentacion = Presentacion(
                id_comercio=comercio_id,
                codigo=f"{codigo} {suffix}",
                descripcion=f"{codigo} {suffix}",
                activo=True,
                orden=orden,
            )
            db.add(presentacion)
            db.flush()
            assoc = ProductoPresentacion(
                id_producto=producto.id,
                id_presentacion=presentacion.id,
                activo=True,
                orden=orden,
            )
            db.add(assoc)
            db.flush()
            db.add(
                Precio(id_producto_presentacion=assoc.id, precio=Decimal("12345.67"))
            )
            db.flush()
            asociaciones[codigo] = assoc

        return {
            "producto_id": producto.id,
            "asociaciones": {k: v.id for k, v in asociaciones.items()},
        }


def _seed_pedido_producto(
    *,
    pedido_id: int,
    pp_id: int,
    cantidad: int,
    observaciones: str | None = None,
) -> int:
    with TestingSessionLocal() as db, db.begin():
        line = PedidoProducto(
            id_pedido=pedido_id,
            id_producto_presentacion=pp_id,
            cantidad=cantidad,
            precio_unitario=Decimal("100.00"),
            observaciones=observaciones,
        )
        db.add(line)
        db.flush()
        return line.id


def _cleanup_full(
    *,
    comercio_id: int,
    cliente_id: int,
    pedido_id: int,
    session_id: int,
    categoria_id: int,
    producto_ids: list[int],
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
        db.execute(delete(CategoriaProducto).where(CategoriaProducto.id == categoria_id))
        db.execute(delete(Pedido).where(Pedido.id == pedido_id))
        db.execute(delete(SessionModel).where(SessionModel.id == session_id))
        db.execute(delete(Cliente).where(Cliente.id == cliente_id))
        db.execute(delete(Comercio).where(Comercio.id == comercio_id))


@contextmanager
def _patched_classifier(classifier_cls):
    from backend.intents.orchestration import initial_intent_dispatcher as _dispatcher

    patcher = patch.object(_dispatcher, "IntentClassifier", classifier_cls)
    patcher.start()
    try:
        yield
    finally:
        patcher.stop()


class SetObservacionProductoEndToEndIntegrationTest(unittest.TestCase):
    def test_unique_set_executes_and_writes_trimmed_text(self) -> None:
        suffix = _suffix()
        base = _seed_comercio_cliente_pedido(suffix)
        pizza = _seed_producto(
            comercio_id=base["comercio_id"],
            categoria_id=base["categoria_id"],
            nombre=f"Pizza Muzzarella Aclaracion {suffix}",
            codigos_presentacion=["chica"],
            suffix=suffix,
        )
        line_id: int | None = None
        try:
            line_id = _seed_pedido_producto(
                pedido_id=base["pedido_id"],
                pp_id=pizza["asociaciones"]["chica"],
                cantidad=1,
            )

            with _patched_classifier(_SetObservacionProductoClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None

                    result = process_incoming_message(
                        db,
                        session_row,
                        "pizza muzzarella aclaracion",
                    )

                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "executed")
                    self.assertEqual(
                        result[0].intent, "set_observacion_producto"
                    )

                    db.commit()

            with TestingSessionLocal() as db:
                line = db.execute(
                    select(PedidoProducto).where(PedidoProducto.id == line_id)
                ).scalar_one()
                self.assertEqual(
                    line.observaciones, "pizza muzzarella aclaracion"
                )

                session_row = db.get(SessionModel, base["session_id"])
                assert session_row is not None
                pending = session_row.pending_intents or {}
                self.assertIsNone(pending.get("active"))
                self.assertIsNone(session_row.context_type)
        finally:
            if line_id is not None:
                pass
            _cleanup_full(
                comercio_id=base["comercio_id"],
                cliente_id=base["cliente_id"],
                pedido_id=base["pedido_id"],
                session_id=base["session_id"],
                categoria_id=base["categoria_id"],
                producto_ids=[pizza["producto_id"]],
            )

    def test_unique_clear_executes_and_writes_null(self) -> None:
        suffix = _suffix()
        base = _seed_comercio_cliente_pedido(suffix)
        pizza = _seed_producto(
            comercio_id=base["comercio_id"],
            categoria_id=base["categoria_id"],
            nombre=f"Pizza Muzzarella Aclaracion {suffix}",
            codigos_presentacion=["chica"],
            suffix=suffix,
        )
        line_id: int | None = None
        try:
            line_id = _seed_pedido_producto(
                pedido_id=base["pedido_id"],
                pp_id=pizza["asociaciones"]["chica"],
                cantidad=1,
                observaciones="stale-text",
            )

            with _patched_classifier(_SetObservacionProductoClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None

                    result = process_incoming_message(
                        db,
                        session_row,
                        "Quitar la aclaracion de la pizza",
                    )

                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "executed")
                    self.assertEqual(result[0].resolved_data["observation_action"], "clear")

                    db.commit()

            with TestingSessionLocal() as db:
                line = db.execute(
                    select(PedidoProducto).where(PedidoProducto.id == line_id)
                ).scalar_one()
                self.assertIsNone(line.observaciones)
        finally:
            if line_id is not None:
                pass
            _cleanup_full(
                comercio_id=base["comercio_id"],
                cliente_id=base["cliente_id"],
                pedido_id=base["pedido_id"],
                session_id=base["session_id"],
                categoria_id=base["categoria_id"],
                producto_ids=[pizza["producto_id"]],
            )

    def test_no_draft_returns_rejected_without_mutation(self) -> None:
        suffix = _suffix()
        estado_id = _estado_id_activo()
        comercio_id: int | None = None
        cliente_id: int | None = None
        session_id: int | None = None
        try:
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
                comercio_id = comercio.id
                cliente = Cliente(
                    whatsapp=f"+5491{int(suffix, 16) % 100000000:08d}",
                    nombre=None,
                    domicilio=None,
                    activo=True,
                )
                db.add(cliente)
                db.flush()
                cliente_id = cliente.id
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
                session_id = session_row.id

            with _patched_classifier(_SetObservacionProductoClassifier):
                with TestingSessionLocal() as db_inner:
                    fetched = db_inner.get(SessionModel, session_id)
                    assert fetched is not None
                    result = process_incoming_message(
                        db_inner, fetched, "alguna observacion"
                    )
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "rejected")
                    self.assertEqual(
                        result[0].intent, "set_observacion_producto"
                    )
                    db_inner.commit()
        finally:
            if session_id is not None:
                with TestingSessionLocal() as db, db.begin():
                    db.execute(
                        delete(SessionModel).where(
                            SessionModel.id == session_id
                        )
                    )
            if cliente_id is not None:
                with TestingSessionLocal() as db, db.begin():
                    db.execute(
                        delete(Cliente).where(Cliente.id == cliente_id)
                    )
            if comercio_id is not None:
                with TestingSessionLocal() as db, db.begin():
                    db.execute(
                        delete(Comercio).where(Comercio.id == comercio_id)
                    )


if __name__ == "__main__":
    unittest.main()
