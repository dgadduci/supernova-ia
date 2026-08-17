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
            select(EstadoComercio.id).where(EstadoComercio.codigo == "ACTIVO")
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

    def test_zero_destination_quantity_rejected_no_pending_no_mutation(self):
        """Blocker 1: `cambiar 2 ... por 0 ...` MUST be rejected at the
        orchestrator before any pending state, candidate resolution or
        PedidoProducto mutation. The legacy `2 -> 2` fallback cannot fire.
        """
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_a_chica"], 4)
            with _patched_classifier(_ModificarClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None
                    result = process_incoming_message(
                        db,
                        session_row,
                        "cambiar 2 muzzarella por 0 napolitana",
                    )
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "rejected")
                    self.assertEqual(
                        result[0].resolved_data["reason"],
                        "invalid_destination_quantity",
                    )
                    self.assertIsNone(session_row.context_type)
                    pending = session_row.pending_intents or {}
                    self.assertIsNone(pending.get("active"))
                    db.commit()

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertEqual(source.cantidad, 4)
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

    def test_only_destination_quantity_removes_full_source_and_increments_destination(
        self,
    ):
        """Contract: a request with the only explicit quantity on the
        destination side MUST remove the full source line and create or
        increment the destination by that explicit amount. The legacy
        equal-quantity fallback must NOT be used.
        """
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_a_chica"], 4)
            with _patched_classifier(_ModificarClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None
                    result = process_incoming_message(
                        db,
                        session_row,
                        "cambiar la muzzarella por 2 napolitanas",
                    )
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "executed")
                    self.assertIsNone(
                        result[0].resolved_data.get("cantidad")
                    )
                    self.assertEqual(
                        result[0].resolved_data["cantidad_destino"], 2
                    )
                    db.commit()

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertIsNone(source)
                dest_line = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == base["pedido_id"],
                        PedidoProducto.id_producto_presentacion
                        == base["pp_b_grande"],
                    )
                ).scalar_one()
                self.assertEqual(dest_line.cantidad, 2)
        finally:
            _cleanup(base)

    def test_paired_words_distinct_quantities_execute_2_to_1(self):
        """Contract case 1: `cambiar dos napolitanas por una mozzarella`
        must decrement source by 2 and create/increment destination by 1.
        """
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_a_chica"], 5)
            with _patched_classifier(_ModificarClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None
                    result = process_incoming_message(
                        db,
                        session_row,
                        "cambiar dos muzzarella por una napolitana",
                    )
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "executed")
                    self.assertEqual(
                        result[0].resolved_data["cantidad"], 2
                    )
                    self.assertEqual(
                        result[0].resolved_data["cantidad_destino"], 1
                    )
                    db.commit()

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertEqual(source.cantidad, 3)
                dest_line = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == base["pedido_id"],
                        PedidoProducto.id_producto_presentacion
                        == base["pp_b_grande"],
                    )
                ).scalar_one()
                self.assertEqual(dest_line.cantidad, 1)
        finally:
            _cleanup(base)

    def test_decimal_dot_destination_quantity_rejected_no_mutation(self):
        """Blocker: `cambiar 2 ... por 1.5 ...` MUST be rejected before
        any pending, candidate resolution or PedidoProducto mutation.
        The legacy equal-quantity fallback (`2 -> 1`) cannot fire.
        """
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_a_chica"], 4)
            with _patched_classifier(_ModificarClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None
                    result = process_incoming_message(
                        db,
                        session_row,
                        "cambiar 2 muzzarella por 1.5 napolitana",
                    )
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "rejected")
                    self.assertEqual(
                        result[0].resolved_data["reason"],
                        "invalid_destination_quantity",
                    )
                    self.assertIsNone(session_row.context_type)
                    pending = session_row.pending_intents or {}
                    self.assertIsNone(pending.get("active"))
                    db.commit()

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertEqual(source.cantidad, 4)
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

    def test_decimal_comma_destination_quantity_rejected_no_mutation(self):
        """Spanish form `1,5` MUST behave the same as `1.5`: rejected,
        Pedido intact, no pending, no mutation.
        """
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_a_chica"], 4)
            with _patched_classifier(_ModificarClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None
                    result = process_incoming_message(
                        db,
                        session_row,
                        "cambiar 2 muzzarella por 1,5 napolitana",
                    )
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "rejected")
                    self.assertEqual(
                        result[0].resolved_data["reason"],
                        "invalid_destination_quantity",
                    )
                    self.assertIsNone(session_row.context_type)
                    pending = session_row.pending_intents or {}
                    self.assertIsNone(pending.get("active"))
                    db.commit()

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertEqual(source.cantidad, 4)
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

    def test_decimal_with_colon_after_por_rejected_no_mutation(self):
        """`por:` with a decimal destination quantity MUST be rejected
        because the raw `por` boundary must be semantically compatible
        with `_split_on_por()`. Without the regex fix the decimal
        would collapse into ``1 5`` and trigger a wrong ``2 -> 1``.
        """
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_a_chica"], 4)
            with _patched_classifier(_ModificarClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None
                    result = process_incoming_message(
                        db,
                        session_row,
                        "cambiar 2 muzzarella por: 1.5 napolitana",
                    )
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "rejected")
                    self.assertEqual(
                        result[0].resolved_data["reason"],
                        "invalid_destination_quantity",
                    )
                    self.assertIsNone(session_row.context_type)
                    pending = session_row.pending_intents or {}
                    self.assertIsNone(pending.get("active"))
                    db.commit()

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertEqual(source.cantidad, 4)
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

    def test_negative_with_comma_after_por_rejected_no_mutation(self):
        """`por,` with a negative destination quantity MUST be rejected.
        The raw `por` boundary must be semantically compatible with
        `_split_on_por()` so the ``-1`` token is recognised before
        normalization strips the minus sign.
        """
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_a_chica"], 4)
            with _patched_classifier(_ModificarClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None
                    result = process_incoming_message(
                        db,
                        session_row,
                        "cambiar 2 muzzarella por, -1 napolitana",
                    )
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0].status, "rejected")
                    self.assertEqual(
                        result[0].resolved_data["reason"],
                        "invalid_destination_quantity",
                    )
                    self.assertIsNone(session_row.context_type)
                    pending = session_row.pending_intents or {}
                    self.assertIsNone(pending.get("active"))
                    db.commit()

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertEqual(source.cantidad, 4)
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


if __name__ == "__main__":
    unittest.main()


def _seed_napolitanas_y_mozzarella(suffix: str) -> dict:
    """Seed a draft Pedido with one ``Pizza Napolitana grande`` line plus
    both ``Pizza Mozzarella`` presentations so the initial modification
    message resolves to a ``destination_selection`` pending state.

    The catalog contains exactly one ``Mozzarella`` product so the
    initial destination recognizer returns two ProductoPresentacion
    rows (grande/chica) for the bare destination message. The source
    Pedido carries a single ``Pizza Napolitana grande`` line so the
    source candidate is unique from the first turn.
    """

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
            descripcion=f"Pizzas-{suffix}",
            activo=True,
            orden=0,
        )
        db.add(categoria)
        db.flush()

        producto_napo = Producto(
            id_categoria_producto=categoria.id,
            nombre=f"Pizza Napolitana {suffix}",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        db.add(producto_napo)
        db.flush()

        producto_mozza = Producto(
            id_categoria_producto=categoria.id,
            nombre=f"Pizza Mozzarella {suffix}",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=1,
        )
        db.add(producto_mozza)
        db.flush()

        pres_grande = Presentacion(
            id_comercio=comercio.id,
            codigo="grande",
            descripcion=f"grande-{suffix}",
            activo=True,
            orden=0,
        )
        db.add(pres_grande)
        db.flush()

        pres_chica = Presentacion(
            id_comercio=comercio.id,
            codigo="chica",
            descripcion=f"chica-{suffix}",
            activo=True,
            orden=0,
        )
        db.add(pres_chica)
        db.flush()

        pp_napo_grande = ProductoPresentacion(
            id_producto=producto_napo.id,
            id_presentacion=pres_grande.id,
            activo=True,
            orden=0,
        )
        db.add(pp_napo_grande)
        db.flush()

        pp_mozza_grande = ProductoPresentacion(
            id_producto=producto_mozza.id,
            id_presentacion=pres_grande.id,
            activo=True,
            orden=0,
        )
        db.add(pp_mozza_grande)
        db.flush()

        pp_mozza_chica = ProductoPresentacion(
            id_producto=producto_mozza.id,
            id_presentacion=pres_chica.id,
            activo=True,
            orden=0,
        )
        db.add(pp_mozza_chica)
        db.flush()

        db.add(
            Precio(
                id_producto_presentacion=pp_napo_grande.id,
                precio=Decimal("150.00"),
            )
        )
        db.add(
            Precio(
                id_producto_presentacion=pp_mozza_grande.id,
                precio=Decimal("140.00"),
            )
        )
        db.add(
            Precio(
                id_producto_presentacion=pp_mozza_chica.id,
                precio=Decimal("100.00"),
            )
        )
        db.flush()

        return {
            "comercio_id": comercio.id,
            "cliente_id": cliente.id,
            "session_id": session_row.id,
            "pedido_id": pedido.id,
            "categoria_id": categoria.id,
            "producto_napo_id": producto_napo.id,
            "producto_mozza_id": producto_mozza.id,
            "pp_napo_grande": pp_napo_grande.id,
            "pp_mozza_grande": pp_mozza_grande.id,
            "pp_mozza_chica": pp_mozza_chica.id,
        }


def _cleanup_napolitanas_y_mozzarella(base: dict) -> None:
    with TestingSessionLocal() as db, db.begin():
        sess_row = db.get(SessionModel, base["session_id"])
        if sess_row is not None:
            sess_row.id_pedido = None
            sess_row.context_type = None
            sess_row.pending_intents = {}
            db.flush()
        db.execute(
            delete(PedidoProducto).where(
                PedidoProducto.id_pedido == base["pedido_id"]
            )
        )
        pp_ids = [
            base["pp_napo_grande"],
            base["pp_mozza_grande"],
            base["pp_mozza_chica"],
        ]
        db.execute(
            delete(Precio).where(Precio.id_producto_presentacion.in_(pp_ids))
        )
        db.execute(
            delete(ProductoPresentacion).where(
                ProductoPresentacion.id.in_(pp_ids)
            )
        )
        db.execute(
            delete(Producto).where(
                Producto.id.in_(
                    [base["producto_napo_id"], base["producto_mozza_id"]]
                )
            )
        )
        db.execute(
            delete(CategoriaProducto).where(
                CategoriaProducto.id == base["categoria_id"]
            )
        )
        db.execute(delete(Pedido).where(Pedido.id == base["pedido_id"]))
        db.execute(
            delete(SessionModel).where(SessionModel.id == base["session_id"])
        )
        db.execute(
            delete(Cliente).where(Cliente.id == base["cliente_id"])
        )
        db.execute(
            delete(Comercio).where(Comercio.id == base["comercio_id"])
        )


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


def _seed_napolitanas(suffix: str) -> dict:
    """Seed a draft Pedido with one `Pizza Napolitana grande` line and
    the catalog entries the integration test needs: a `Pizza Napolitana
    chica` presentation that does not yet belong to the pedido. The
    presentation codes use the alias tokens verbatim so the runtime
    fuzzy presentation filter keeps both presentations distinct under
    the test message.
    """
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
            descripcion=f"Pizzas-{suffix}",
            activo=True,
            orden=0,
        )
        db.add(categoria)
        db.flush()

        producto = Producto(
            id_categoria_producto=categoria.id,
            nombre=f"Pizza Napolitana {suffix}",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        db.add(producto)
        db.flush()

        pres_grande = Presentacion(
            id_comercio=comercio.id,
            codigo="grande",
            descripcion=f"grande-{suffix}",
            activo=True,
            orden=0,
        )
        db.add(pres_grande)
        db.flush()

        pres_chica = Presentacion(
            id_comercio=comercio.id,
            codigo="chica",
            descripcion=f"chica-{suffix}",
            activo=True,
            orden=0,
        )
        db.add(pres_chica)
        db.flush()

        pp_grande = ProductoPresentacion(
            id_producto=producto.id,
            id_presentacion=pres_grande.id,
            activo=True,
            orden=0,
        )
        db.add(pp_grande)
        db.flush()

        pp_chica = ProductoPresentacion(
            id_producto=producto.id,
            id_presentacion=pres_chica.id,
            activo=True,
            orden=0,
        )
        db.add(pp_chica)
        db.flush()

        db.add(
            Precio(id_producto_presentacion=pp_grande.id, precio=Decimal("150.00"))
        )
        db.add(
            Precio(id_producto_presentacion=pp_chica.id, precio=Decimal("100.00"))
        )
        db.flush()

        return {
            "comercio_id": comercio.id,
            "cliente_id": cliente.id,
            "session_id": session_row.id,
            "pedido_id": pedido.id,
            "categoria_id": categoria.id,
            "producto_id": producto.id,
            "pp_grande": pp_grande.id,
            "pp_chica": pp_chica.id,
        }


def _cleanup_napolitanas(base: dict) -> None:
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
                    [base["pp_grande"], base["pp_chica"]]
                )
            )
        )
        db.execute(
            delete(ProductoPresentacion).where(
                ProductoPresentacion.id.in_([base["pp_grande"], base["pp_chica"]])
            )
        )
        db.execute(delete(Producto).where(Producto.id == base["producto_id"]))
        db.execute(
            delete(CategoriaProducto).where(
                CategoriaProducto.id == base["categoria_id"]
            )
        )
        db.execute(delete(Pedido).where(Pedido.id == base["pedido_id"]))
        db.execute(delete(SessionModel).where(SessionModel.id == base["session_id"]))
        db.execute(delete(Cliente).where(Cliente.id == base["cliente_id"]))
        db.execute(delete(Comercio).where(Comercio.id == base["comercio_id"]))


class _StubHybridEmbeddingClient:
    """Deterministic embedding client for the hybrid integration test.

    Returns a fixed all-ones vector of the configured dimension so the
    recognizer's ``embed_query`` call is exercised without any HTTP
    transport or live LLM.
    """

    def __init__(self, dimension: int = 384) -> None:
        self._vector = [1.0] * dimension
        self.dimension = dimension

    def embed_query(self, text: str) -> list[float]:
        return list(self._vector)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [list(self._vector) for _ in texts]


class _StubHybridVectorMatch:
    def __init__(self, id_producto_presentacion: int, score: float) -> None:
        self.id_producto_presentacion = id_producto_presentacion
        self.score = score


class _StubHybridVectorSearchService:
    """Deterministic per-call vector search service for the integration
    test. Returns an empty match list so the 4.11.7 guard fires for the
    fuzzy-unique decision and the fuzzy result becomes the authoritative
    hybrid translation.
    """

    def __init__(self) -> None:
        self.call_count = 0

    def search_similar(
        self,
        *,
        id_comercio: int,
        query_embedding,
        top_k: int,
        candidate_producto_presentacion_ids,
    ):
        self.call_count += 1
        return []


class _StubHybridRecorder:
    def __init__(self) -> None:
        self.call_count = 0

    def record(self, *args, **kwargs) -> None:
        self.call_count += 1


def _build_hybrid_recognizer():
    """Build a real ``HybridAuthoritativeProductRecognizer`` with
    deterministic embedding + vector + recorder collaborators.

    The factory uses the calibrated ``HybridDecisionPolicy`` defaults
    so the recognizer falls back to the fuzzy-unique decision when the
    filtered vector side is empty (the 4.11.7 guard).
    """
    from backend.recognizers.fuzzy_product_recognizer import (
        FuzzyProductRecognizer,
    )
    from backend.services.hybrid_authoritative_recognizer import (
        HybridAuthoritativeProductRecognizer,
    )
    from backend.services.product_recognition_calibration_policy import (
        HybridDecisionPolicy,
    )

    policy = HybridDecisionPolicy(
        fuzzy_weight=0.5,
        vector_weight=0.5,
        unique_threshold=0.7,
        ambiguous_threshold=0.4,
        minimum_score_gap=0.05,
        vector_top_k=5,
    )
    return HybridAuthoritativeProductRecognizer(
        inner=FuzzyProductRecognizer(),
        policy=policy,
        embedding_client=_StubHybridEmbeddingClient(),
        vector_search_service=lambda: _StubHybridVectorSearchService(),
        recorder=_StubHybridRecorder(),
        configured_mode="hybrid_authoritative",
        effective_mode="hybrid_authoritative",
    )


class ModificarProductoHybridEndToEndTest(unittest.TestCase):
    """Smallest real-hybrid modification integration proof.

    Wires the real ``HybridAuthoritativeProductRecognizer`` into the
    ``modificar_producto_recognizer`` module via its module-level
    factory binding, then runs the existing orchestration path against
    the real PostgreSQL test database. The handler, service,
    repository and resolver remain untouched (no mocks); only the
    classifier and the deterministic embedding/vector collaborators
    are stubbed.
    """

    def test_cambiar_2_napolitanas_grandes_por_2_chicas_executes(
        self,
    ) -> None:
        from backend.intents.recognizers import (
            modificar_producto_recognizer as modificar_recognizer_module,
        )

        suffix = _suffix()
        base = _seed_napolitanas(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_grande"], 5)
            hybrid_recognizer = _build_hybrid_recognizer()
            original_recognizer = (
                modificar_recognizer_module._product_recognizer  # type: ignore[attr-defined]
            )
            modificar_recognizer_module._product_recognizer = (  # type: ignore[attr-defined]
                hybrid_recognizer
            )
            try:
                with _patched_classifier(_ModificarClassifier):
                    with TestingSessionLocal() as db:
                        session_row = db.get(
                            SessionModel, base["session_id"]
                        )
                        assert session_row is not None
                        result = process_incoming_message(
                            db,
                            session_row,
                            "cambiar 2 napolitanas grandes por 2 napolitanas chicas",
                        )
                        self.assertEqual(len(result), 1)
                        self.assertEqual(result[0].status, "executed")
                        self.assertEqual(
                            result[0].resolved_data[
                                "pedido_producto_origen_id"
                            ],
                            source_line_id,
                        )
                        self.assertEqual(
                            result[0].resolved_data[
                                "producto_presentacion_destino_id"
                            ],
                            base["pp_chica"],
                        )
                        self.assertEqual(
                            result[0].resolved_data["cantidad"], 2
                        )
                        db.commit()
            finally:
                modificar_recognizer_module._product_recognizer = (  # type: ignore[attr-defined]
                    original_recognizer
                )

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertEqual(source.cantidad, 3)
                dest_line = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == base["pedido_id"],
                        PedidoProducto.id_producto_presentacion
                        == base["pp_chica"],
                    )
                ).scalar_one()
                self.assertEqual(dest_line.cantidad, 2)
                session_row = db.get(SessionModel, base["session_id"])
                self.assertIsNone(session_row.context_type)
                self.assertEqual(session_row.pending_intents, {})
        finally:
            _cleanup_napolitanas(base)


class ModificarProductoBareDestinationExecutionTest(unittest.TestCase):
    """Smallest pending destination-selection execution proof.

    The first turn triggers a real pending state via the existing
    orchestration path; the second turn is the bare ``chica`` reply
    that the deterministic pre-check must resolve without invoking
    the generic recognizer. The handler, service and repository are
    untouched (no mocks); only the classifier is stubbed.
    """

    def test_chica_after_destination_clarification_transfers_two_and_clears(
        self,
    ) -> None:
        from backend.intents.orchestration.incoming_message_orchestrator import (
            process_incoming_message,
        )

        suffix = _suffix()
        base = _seed_napolitanas_y_mozzarella(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_napo_grande"], 5)
            with _patched_classifier(_ModificarClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None
                    initial = process_incoming_message(
                        db,
                        session_row,
                        "cambiar 2 napolitanas grandes por una pizza de mozzarella",
                    )
                    self.assertEqual(len(initial), 1)
                    self.assertEqual(initial[0].status, "pending_resolution")
                    self.assertEqual(
                        initial[0].stage, "destination_selection"
                    )
                    self.assertEqual(
                        sorted(
                            initial[0].resolved_data[
                                "destination_candidate_ids"
                            ]
                        ),
                        sorted(
                            [
                                base["pp_mozza_grande"],
                                base["pp_mozza_chica"],
                            ]
                        ),
                    )
                    db.commit()

            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, base["session_id"])
                assert session_row is not None
                self.assertIsNotNone(session_row.context_type)
                pending = session_row.pending_intents or {}
                active = pending.get("active") or {}
                self.assertEqual(active.get("intent"), "modificar_producto")
                self.assertEqual(
                    active.get("stage"), "destination_selection"
                )

            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, base["session_id"])
                assert session_row is not None
                follow_up = process_incoming_message(
                    db, session_row, "chica"
                )
                self.assertEqual(len(follow_up), 1)
                self.assertEqual(follow_up[0].status, "executed")
                self.assertEqual(
                    follow_up[0].resolved_data[
                        "pedido_producto_origen_id"
                    ],
                    source_line_id,
                )
                self.assertEqual(
                    follow_up[0].resolved_data[
                        "producto_presentacion_destino_id"
                    ],
                    base["pp_mozza_chica"],
                )
                self.assertEqual(
                    follow_up[0].resolved_data["cantidad"], 2
                )
                self.assertEqual(
                    follow_up[0].resolved_data["cantidad_destino"], 1
                )
                self.assertEqual(
                    follow_up[0].resolved_data[
                        "cantidad_destino_modificada"
                    ],
                    1,
                )
                db.commit()

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertEqual(source.cantidad, 3)
                dest_line = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == base["pedido_id"],
                        PedidoProducto.id_producto_presentacion
                        == base["pp_mozza_chica"],
                    )
                ).scalar_one()
                self.assertEqual(dest_line.cantidad, 1)
                session_row = db.get(SessionModel, base["session_id"])
                self.assertIsNone(session_row.context_type)
                cleared_pending = session_row.pending_intents or {}
                self.assertIsNone(cleared_pending.get("active"))
                self.assertEqual(cleared_pending.get("queue", []), [])
        finally:
            _cleanup_napolitanas_y_mozzarella(base)

    def test_grande_after_destination_only_pilot_removes_full_source_and_creates_two(
        self,
    ) -> None:
        """Pilot gate: ``cambia la napolitana grande por dos mozzarella grande``
        with source quantity 1 must leave the source removed, create the
        ``Mozzarella grande`` destination at quantity 2, and preserve the
        destination-only semantics through the recognizer.
        """
        from backend.intents.orchestration.incoming_message_orchestrator import (
            process_incoming_message,
        )

        suffix = _suffix()
        base = _seed_napolitanas_y_mozzarella(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_napo_grande"], 1)
            with _patched_classifier(_ModificarClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None
                    initial = process_incoming_message(
                        db,
                        session_row,
                        "cambia la napolitana grande por dos mozzarella grande",
                    )
                    self.assertEqual(len(initial), 1)
                    self.assertEqual(initial[0].status, "executed")
                    self.assertEqual(
                        initial[0].resolved_data[
                            "pedido_producto_origen_id"
                        ],
                        source_line_id,
                    )
                    self.assertEqual(
                        initial[0].resolved_data[
                            "producto_presentacion_destino_id"
                        ],
                        base["pp_mozza_grande"],
                    )
                    self.assertIsNone(
                        initial[0].resolved_data.get("cantidad")
                    )
                    self.assertEqual(
                        initial[0].resolved_data["cantidad_destino"], 2
                    )
                    self.assertEqual(
                        initial[0].resolved_data[
                            "cantidad_destino_modificada"
                        ],
                        2,
                    )
                    db.commit()

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertIsNone(source)
                dest_line = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == base["pedido_id"],
                        PedidoProducto.id_producto_presentacion
                        == base["pp_mozza_grande"],
                    )
                ).scalar_one()
                self.assertEqual(dest_line.cantidad, 2)
                session_row = db.get(SessionModel, base["session_id"])
                self.assertIsNone(session_row.context_type)
                cleared_pending = session_row.pending_intents or {}
                self.assertIsNone(cleared_pending.get("active"))
                self.assertEqual(cleared_pending.get("queue", []), [])
        finally:
            _cleanup_napolitanas_y_mozzarella(base)

    def test_destination_only_without_qualifier_preserves_pending_and_full_source(
        self,
    ) -> None:
        """When the destination-only message leaves the presentation
        ambiguous (e.g. ``dos mozzarellas`` without a ``grande/chica``
        qualifier), the pending state MUST carry
        ``cantidad=None, cantidad_destino=2`` and the follow-up
        ``grande`` clarification MUST execute a full source removal
        plus a destination of exactly 2.
        """
        from backend.intents.orchestration.incoming_message_orchestrator import (
            process_incoming_message,
        )

        suffix = _suffix()
        base = _seed_napolitanas_y_mozzarella(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_napo_grande"], 1)
            with _patched_classifier(_ModificarClassifier):
                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None
                    initial = process_incoming_message(
                        db,
                        session_row,
                        "cambia la napolitana grande por dos mozzarellas",
                    )
                    self.assertEqual(len(initial), 1)
                    self.assertEqual(initial[0].status, "pending_resolution")
                    self.assertEqual(
                        initial[0].stage, "destination_selection"
                    )
                    self.assertIsNone(
                        initial[0].resolved_data.get("cantidad")
                    )
                    self.assertEqual(
                        initial[0].resolved_data["cantidad_destino"], 2
                    )
                    self.assertEqual(
                        sorted(
                            initial[0].resolved_data[
                                "destination_candidate_ids"
                            ]
                        ),
                        sorted(
                            [
                                base["pp_mozza_grande"],
                                base["pp_mozza_chica"],
                            ]
                        ),
                    )
                    db.commit()

            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, base["session_id"])
                assert session_row is not None
                self.assertIsNotNone(session_row.context_type)
                pending = session_row.pending_intents or {}
                active = pending.get("active") or {}
                self.assertEqual(active.get("intent"), "modificar_producto")
                self.assertEqual(
                    active.get("stage"), "destination_selection"
                )
                self.assertIsNone(
                    active.get("resolved_data", {}).get("cantidad")
                )
                self.assertEqual(
                    active.get("resolved_data", {}).get("cantidad_destino"),
                    2,
                )

            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, base["session_id"])
                assert session_row is not None
                follow_up = process_incoming_message(
                    db, session_row, "grande"
                )
                self.assertEqual(len(follow_up), 1)
                self.assertEqual(follow_up[0].status, "executed")
                self.assertEqual(
                    follow_up[0].resolved_data[
                        "pedido_producto_origen_id"
                    ],
                    source_line_id,
                )
                self.assertEqual(
                    follow_up[0].resolved_data[
                        "producto_presentacion_destino_id"
                    ],
                    base["pp_mozza_grande"],
                )
                self.assertIsNone(
                    follow_up[0].resolved_data.get("cantidad")
                )
                self.assertEqual(
                    follow_up[0].resolved_data["cantidad_destino"], 2
                )
                self.assertEqual(
                    follow_up[0].resolved_data[
                        "cantidad_destino_modificada"
                    ],
                    2,
                )
                db.commit()

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertIsNone(source)
                dest_line = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == base["pedido_id"],
                        PedidoProducto.id_producto_presentacion
                        == base["pp_mozza_grande"],
                    )
                ).scalar_one()
                self.assertEqual(dest_line.cantidad, 2)
                session_row = db.get(SessionModel, base["session_id"])
                self.assertIsNone(session_row.context_type)
                cleared_pending = session_row.pending_intents or {}
                self.assertIsNone(cleared_pending.get("active"))
                self.assertEqual(cleared_pending.get("queue", []), [])
        finally:
            _cleanup_napolitanas_y_mozzarella(base)
