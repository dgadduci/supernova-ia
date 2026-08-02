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
from backend.intents.schemas.processed_intent import ProcessedIntent
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


def _estado_id() -> int:
    with engine.connect() as conn:
        row = conn.execute(
            select(EstadoComercio.id).where(EstadoComercio.estado == "ACTIVO")
        ).first()
        if row is None:
            raise RuntimeError("estado ACTIVO not seeded")
        return row[0]


class _ModificarClassifier:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def query(self, message):
        return IntentClassificationResult(
            intents=[
                ClassifiedIntent(
                    intent=IntentName.MODIFICAR_PRODUCTO,
                    mensaje=message,
                )
            ],
            mensaje=message,
        )


class _AgregarClassifier:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def query(self, message):
        return IntentClassificationResult(
            intents=[
                ClassifiedIntent(
                    intent=IntentName.AGREGAR_PRODUCTO,
                    mensaje=message,
                )
            ],
            mensaje=message,
        )


class _QuitarClassifier:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def query(self, message):
        return IntentClassificationResult(
            intents=[
                ClassifiedIntent(
                    intent=IntentName.QUITAR_PRODUCTO,
                    mensaje=message,
                )
            ],
            mensaje=message,
        )


def _seed(suffix: str) -> dict:
    estado_id = _estado_id()
    with TestingSessionLocal() as db, db.begin():
        comercio = Comercio(
            nombre_fantasia=f"T-{suffix}",
            nombre_corto=f"TC-{suffix}",
            razon_social=f"R-{suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+5499{suffix[:8]}",
            calle="X",
            numero="1",
            piso_departamento=None,
            localidad="CABA",
            provincia="BA",
            codigo_postal="C1000",
            slug=f"slug-{suffix}",
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
            descripcion=f"Cat-{suffix}",
            activo=True,
            orden=0,
        )
        db.add(categoria)
        db.flush()

        prod_a = Producto(
            id_categoria_producto=categoria.id,
            nombre=f"Pizza Mozzarella {suffix}",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        db.add(prod_a)
        db.flush()

        prod_b = Producto(
            id_categoria_producto=categoria.id,
            nombre=f"Pizza Napolitana {suffix}",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        db.add(prod_b)
        db.flush()

        pres_a_chica = Presentacion(
            id_comercio=comercio.id,
            codigo=f"a-chica-{suffix}",
            descripcion=f"a-chica-{suffix}",
            activo=True,
            orden=0,
        )
        db.add(pres_a_chica)
        db.flush()

        pres_a_grande = Presentacion(
            id_comercio=comercio.id,
            codigo=f"a-grande-{suffix}",
            descripcion=f"a-grande-{suffix}",
            activo=True,
            orden=0,
        )
        db.add(pres_a_grande)
        db.flush()

        pres_b_grande = Presentacion(
            id_comercio=comercio.id,
            codigo=f"b-grande-{suffix}",
            descripcion=f"b-grande-{suffix}",
            activo=True,
            orden=0,
        )
        db.add(pres_b_grande)
        db.flush()

        pp_a_chica = ProductoPresentacion(
            id_producto=prod_a.id,
            id_presentacion=pres_a_chica.id,
            activo=True,
            orden=0,
        )
        db.add(pp_a_chica)
        db.flush()

        pp_a_grande = ProductoPresentacion(
            id_producto=prod_a.id,
            id_presentacion=pres_a_grande.id,
            activo=True,
            orden=0,
        )
        db.add(pp_a_grande)
        db.flush()

        pp_b_grande = ProductoPresentacion(
            id_producto=prod_b.id,
            id_presentacion=pres_b_grande.id,
            activo=True,
            orden=0,
        )
        db.add(pp_b_grande)
        db.flush()

        db.add(Precio(id_producto_presentacion=pp_a_chica.id, precio=Decimal("100.00")))
        db.add(Precio(id_producto_presentacion=pp_a_grande.id, precio=Decimal("150.00")))
        db.add(Precio(id_producto_presentacion=pp_b_grande.id, precio=Decimal("200.00")))
        db.flush()

        return {
            "comercio_id": comercio.id,
            "cliente_id": cliente.id,
            "session_id": session_row.id,
            "pedido_id": pedido.id,
            "categoria_id": categoria.id,
            "producto_ids": [prod_a.id, prod_b.id],
            "pp_a_chica": pp_a_chica.id,
            "pp_a_grande": pp_a_grande.id,
            "pp_b_grande": pp_b_grande.id,
        }


def _seed_line(base: dict, pp_id: int, cantidad: int) -> int:
    with TestingSessionLocal() as db, db.begin():
        line = PedidoProducto(
            id_pedido=base["pedido_id"],
            id_producto_presentacion=pp_id,
            cantidad=cantidad,
            precio_unitario=Decimal("100.00"),
        )
        db.add(line)
        db.flush()
        return line.id


def _cleanup(base: dict) -> None:
    with TestingSessionLocal() as db, db.begin():
        sess_row = db.get(SessionModel, base["session_id"])
        if sess_row is not None:
            sess_row.id_pedido = None
            sess_row.context_type = None
            sess_row.pending_intents = {}
            db.flush()
        db.execute(
            delete(PedidoProducto).where(PedidoProducto.id_pedido == base["pedido_id"])
        )
        db.execute(
            delete(Precio).where(
                Precio.id_producto_presentacion.in_(
                    [base["pp_a_chica"], base["pp_a_grande"], base["pp_b_grande"]]
                )
            )
        )
        db.execute(
            delete(ProductoPresentacion).where(
                ProductoPresentacion.id.in_(
                    [base["pp_a_chica"], base["pp_a_grande"], base["pp_b_grande"]]
                )
            )
        )
        db.execute(delete(Producto).where(Producto.id.in_(base["producto_ids"])))
        db.execute(delete(CategoriaProducto).where(CategoriaProducto.id == base["categoria_id"]))
        db.execute(delete(Pedido).where(Pedido.id == base["pedido_id"]))
        db.execute(delete(SessionModel).where(SessionModel.id == base["session_id"]))
        db.execute(delete(Cliente).where(Cliente.id == base["cliente_id"]))
        db.execute(delete(Comercio).where(Comercio.id == base["comercio_id"]))


@contextmanager
def _patched_classifier(classifier_cls):
    from backend.intents.orchestration import initial_intent_dispatcher as _dispatcher

    patcher = patch.object(_dispatcher, "IntentClassifier", classifier_cls)
    patcher.start()
    try:
        yield
    finally:
        patcher.stop()


class ModificarProductoEndToEndTest(unittest.TestCase):
    def test_full_line_swap_executes_in_single_turn(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_a_chica"], 3)
            with _patched_classifier(_ModificarClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None
                    result = process_incoming_message(
                        db, session_row, "cambiá la muzzarella por napolitana"
                    )
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "executed")
                    self.assertEqual(
                        result[0].resolved_data["pedido_producto_origen_id"],
                        source_line_id,
                    )
                    self.assertEqual(
                        result[0].resolved_data["producto_presentacion_destino_id"],
                        base["pp_b_grande"],
                    )
                    db.commit()

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertIsNone(source)
                dest_line = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == base["pedido_id"],
                        PedidoProducto.id_producto_presentacion == base["pp_b_grande"],
                    )
                ).scalar_one()
                self.assertEqual(dest_line.cantidad, 3)
                session_row = db.get(SessionModel, base["session_id"])
                self.assertIsNone(session_row.context_type)
        finally:
            _cleanup(base)

    def test_partial_modification_with_explicit_cantidad(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_a_chica"], 5)
            with _patched_classifier(_ModificarClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None
                    result = process_incoming_message(
                        db, session_row, "cambiá 2 muzzarella por 2 napolitana"
                    )
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "executed")
                    self.assertEqual(result[0].resolved_data["cantidad"], 2)
                    db.commit()

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertEqual(source.cantidad, 3)
                dest_line = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == base["pedido_id"],
                        PedidoProducto.id_producto_presentacion == base["pp_b_grande"],
                    )
                ).scalar_one()
                self.assertEqual(dest_line.cantidad, 2)
        finally:
            _cleanup(base)

    def test_excess_quantity_rejected(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_a_chica"], 2)
            with _patched_classifier(_ModificarClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None
                    result = process_incoming_message(
                        db, session_row, "cambiá 5 muzzarella por napolitana"
                    )
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "rejected")
                    self.assertEqual(
                        result[0].resolved_data["reason"],
                        "quantity_exceeds_source",
                    )
                    db.commit()

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertEqual(source.cantidad, 2)
                dest = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == base["pedido_id"],
                        PedidoProducto.id_producto_presentacion == base["pp_b_grande"],
                    )
                ).first()
                self.assertIsNone(dest)
        finally:
            _cleanup(base)

    def test_consolidated_destination_increments(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_a_chica"], 2)
            existing_dest_id = _seed_line(base, base["pp_b_grande"], 5)

            with _patched_classifier(_ModificarClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None
                    result = process_incoming_message(
                        db, session_row, "cambiá la muzzarella por napolitana"
                    )
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "executed")
                    db.commit()

            with TestingSessionLocal() as db:
                dest_line = db.get(PedidoProducto, existing_dest_id)
                self.assertEqual(dest_line.cantidad, 7)
                source = db.get(PedidoProducto, source_line_id)
                self.assertIsNone(source)
        finally:
            _cleanup(base)

    def test_destination_unavailable_rejected_at_orchestrator(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_a_chica"], 2)

            with _patched_classifier(_ModificarClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None
                    result = process_incoming_message(
                        db, session_row,
                        "cambiá la muzzarella por algo inexistente xyzqwerty",
                    )
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "rejected")
        finally:
            _cleanup(base)


if __name__ == "__main__":
    unittest.main()


class ModificarProductoEndToEndAtomicityTest(unittest.TestCase):
    """End-to-end matrix covering the section-7 atomic-quantity scenarios."""

    def test_omitted_quantity_transfers_full_source_quantity(self) -> None:
        """7.1: Source x4 + omitted quantity → source removed, destination x4."""
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_a_chica"], 4)
            with _patched_classifier(_ModificarClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None
                    result = process_incoming_message(
                        db, session_row,
                        "cambiá la muzzarella por la napolitana",
                    )
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "executed")
                    self.assertEqual(
                        result[0].resolved_data["cantidad_modificada"], 4
                    )
                    db.commit()

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertIsNone(source)
                dest = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == base["pedido_id"],
                        PedidoProducto.id_producto_presentacion
                        == base["pp_b_grande"],
                    )
                ).scalar_one()
                self.assertEqual(dest.cantidad, 4)
        finally:
            _cleanup(base)

    def test_explicit_partial_quantity_decrements_source_creates_destination(self) -> None:
        """7.2: Source x4 + explicit 2 → source x2, destination x2."""
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_a_chica"], 4)
            with _patched_classifier(_ModificarClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None
                    result = process_incoming_message(
                        db, session_row, "cambiá 2 muzzarella por 2 napolitana"
                    )
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "executed")
                    self.assertEqual(result[0].resolved_data["cantidad"], 2)
                    db.commit()

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertEqual(source.cantidad, 2)
                dest = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == base["pedido_id"],
                        PedidoProducto.id_producto_presentacion
                        == base["pp_b_grande"],
                    )
                ).scalar_one()
                self.assertEqual(dest.cantidad, 2)
        finally:
            _cleanup(base)

    def test_destination_already_exists_increments_in_place(self) -> None:
        """7.9: source x4 + dest x2 already present → source removed, dest x6."""
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_a_chica"], 4)
            existing_dest_id = _seed_line(base, base["pp_b_grande"], 2)
            with _patched_classifier(_ModificarClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None
                    result = process_incoming_message(
                        db, session_row,
                        "cambiá la muzzarella por la napolitana",
                    )
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "executed")
                    db.commit()

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertIsNone(source)
                dest = db.get(PedidoProducto, existing_dest_id)
                self.assertEqual(dest.cantidad, 6)
        finally:
            _cleanup(base)

    def test_destination_equals_source_rejected_at_service(self) -> None:
        """7.10: same producto_presentacion as source → service rejects,
        source unchanged. Tested at the service level (the end-to-end path
        depends on the recognizer to disambiguate single-presentation
        source/destination messages, which can split into multiple
        candidates and produce a `pending_resolution` outcome).
        """
        from backend.services.pedido_producto_service import PedidoProductoService

        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_a_chica"], 3)
            with TestingSessionLocal() as db, db.begin():
                result = PedidoProductoService(db).modify_product(
                    base["pedido_id"],
                    source_line_id,
                    base["pp_a_chica"],
                    1,
                )
            self.assertEqual(result.status, "rejected")
            self.assertEqual(result.reason, "equivalent_modification")

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertEqual(source.cantidad, 3)
        finally:
            _cleanup(base)

    def test_unknown_destination_preserves_pedido(self) -> None:
        """7.4: source x5 + unknown destination → rejected, source remains x5."""
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_a_chica"], 5)
            with _patched_classifier(_ModificarClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None
                    result = process_incoming_message(
                        db, session_row,
                        "cambiá la muzzarella por algo inexistente xyzqwerty",
                    )
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "rejected")
                    self.assertEqual(
                        result[0].resolved_data.get("reason"),
                        "no_destination_candidates",
                    )

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertIsNotNone(source)
                self.assertEqual(source.cantidad, 5)
                dest_lines = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == base["pedido_id"],
                        PedidoProducto.id_producto_presentacion
                        == base["pp_b_grande"],
                    )
                ).all()
                self.assertEqual(len(dest_lines), 0)
        finally:
            _cleanup(base)

    def test_single_processed_intent_invariant(self) -> None:
        """7.15: process_incoming_message returns one ProcessedIntent per modify."""
        suffix = _suffix()
        base = _seed(suffix)
        try:
            _seed_line(base, base["pp_a_chica"], 4)
            with _patched_classifier(_ModificarClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None
                    result = process_incoming_message(
                        db, session_row,
                        "cambiá la muzzarella por la napolitana",
                    )
                    self.assertEqual(len(result), 1)
                    self.assertEqual(
                        result[0].intent, "modificar_producto"
                    )
        finally:
            _cleanup(base)
