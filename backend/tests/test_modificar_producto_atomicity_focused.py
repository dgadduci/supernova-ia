"""Focused tests for the atomic quantity-preserving modify_product flow.

These tests cover the section-6 scenarios of the
`fix-modificar-producto-atomicity-quantity` change:
- validation-before-mutation (6.1)
- destination_unavailable for unknown destination (6.2)
- destination_price_missing rejection (6.3)
- authoritative quantity derivation (6.4, 6.5)
- price-snapshot ordering (6.6)
- execute_modificar_producto re-reads source quantity (6.7)
- handler forbids composition with quitar_producto/agregar_producto (6.8)
- handler returns exactly one ProcessedIntent (6.9)
- process_initial_modificar_producto preserves None cantidad (6.10)
- resolve_product_modification preserves None cantidad across stages (6.11)
"""
import unittest
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from backend.intents.context.product_modification_resolver import (
    resolve_product_modification,
)
from backend.intents.handlers import (
    modificar_producto_handler as handler_module,
)
from backend.intents.handlers.modificar_producto_handler import (
    execute_modificar_producto,
)
from backend.intents.orchestration.initial_intent_dispatcher import (
    dispatch_initial_message,
)
from backend.intents.orchestration.modificar_producto_initial import (
    process_initial_modificar_producto,
)
from backend.intents.recognizers.modificar_producto_recognizer import (
    recognize_modificar_producto,
)
from backend.intents.schemas.intent_classification import (
    ClassifiedIntent,
    IntentClassificationResult,
    IntentName,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
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

        return {
            "comercio_id": comercio.id,
            "cliente_id": cliente.id,
            "session_id": session_row.id,
            "pedido_id": pedido.id,
            "categoria_id": categoria.id,
        }


def _seed_product(
    base: dict,
    suffix: str,
    *,
    nombre: str,
    codigo_presentacion: str,
    with_price: bool = True,
    presentacion_activo: bool = True,
    producto_activo: bool = True,
    producto_disponible: bool = True,
    pp_activo: bool = True,
) -> dict:
    """Seed a product + presentation + association + price.

    Returns a dict with `producto_id`, `presentacion_id`, `pp_id`, and `pedido_producto_id`
    if `seed_pedido_line=True`.
    """
    with TestingSessionLocal() as db, db.begin():
        producto = Producto(
            id_categoria_producto=base["categoria_id"],
            nombre=nombre,
            descripcion=None,
            activo=producto_activo,
            disponible=producto_disponible,
            orden=0,
        )
        db.add(producto)
        db.flush()

        presentacion = Presentacion(
            id_comercio=base["comercio_id"],
            codigo=codigo_presentacion,
            descripcion=codigo_presentacion,
            activo=presentacion_activo,
            orden=0,
        )
        db.add(presentacion)
        db.flush()

        pp = ProductoPresentacion(
            id_producto=producto.id,
            id_presentacion=presentacion.id,
            activo=pp_activo,
            orden=0,
        )
        db.add(pp)
        db.flush()

        if with_price:
            db.add(Precio(id_producto_presentacion=pp.id, precio=Decimal("100.00")))
            db.flush()

        return {
            "producto_id": producto.id,
            "presentacion_id": presentacion.id,
            "pp_id": pp.id,
            "producto_nombre": producto.nombre,
            "presentacion_codigo": presentacion.codigo,
        }


def _seed_pedido_line(base: dict, pp_id: int, cantidad: int) -> int:
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
            delete(PedidoProducto).where(
                PedidoProducto.id_pedido == base["pedido_id"]
            )
        )

        producto_ids = [
            row[0]
            for row in db.execute(
                select(Producto.id).where(
                    Producto.id_categoria_producto == base["categoria_id"]
                )
            ).all()
        ]
        if producto_ids:
            pp_ids = [
                row[0]
                for row in db.execute(
                    select(ProductoPresentacion.id).where(
                        ProductoPresentacion.id_producto.in_(producto_ids)
                    )
                ).all()
            ]
            if pp_ids:
                db.execute(
                    delete(Precio).where(
                        Precio.id_producto_presentacion.in_(pp_ids)
                    )
                )
            db.execute(
                delete(ProductoPresentacion).where(
                    ProductoPresentacion.id_producto.in_(producto_ids)
                )
            )
            db.execute(delete(Producto).where(Producto.id.in_(producto_ids)))
        db.execute(
            delete(CategoriaProducto).where(
                CategoriaProducto.id == base["categoria_id"]
            )
        )
        db.execute(delete(Pedido).where(Pedido.id == base["pedido_id"]))
        db.execute(
            delete(SessionModel).where(SessionModel.id == base["session_id"])
        )
        db.execute(delete(Cliente).where(Cliente.id == base["cliente_id"]))
        db.execute(delete(Comercio).where(Comercio.id == base["comercio_id"]))


class ModifyProductValidationBeforeMutationTest(unittest.TestCase):
    """Section 6.1, 6.2, 6.3 - destination validation before source mutation."""

    def test_destination_unavailable_does_not_mutate_source(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            orig = _seed_product(
                base,
                suffix,
                nombre=f"Origen {suffix}",
                codigo_presentacion=f"orig-{suffix}",
            )
            source_line_id = _seed_pedido_line(base, orig["pp_id"], 4)

            with TestingSessionLocal() as db, db.begin():
                result = PedidoProductoService(db).modify_product(
                    base["pedido_id"],
                    source_line_id,
                    99999,
                    None,
                )

            self.assertEqual(result.status, "rejected")
            self.assertEqual(result.reason, "destination_unavailable")

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertIsNotNone(source)
                self.assertEqual(source.cantidad, 4)
        finally:
            _cleanup(base)

    def test_destination_price_missing_does_not_mutate_source(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            orig = _seed_product(
                base,
                suffix,
                nombre=f"Origen {suffix}",
                codigo_presentacion=f"orig-{suffix}",
            )
            dest = _seed_product(
                base,
                suffix,
                nombre=f"Dest {suffix}",
                codigo_presentacion=f"dest-{suffix}",
                with_price=False,
            )
            source_line_id = _seed_pedido_line(base, orig["pp_id"], 4)

            with TestingSessionLocal() as db, db.begin():
                result = PedidoProductoService(db).modify_product(
                    base["pedido_id"],
                    source_line_id,
                    dest["pp_id"],
                    None,
                )

            self.assertEqual(result.status, "rejected")
            self.assertEqual(result.reason, "destination_price_missing")

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertIsNotNone(source)
                self.assertEqual(source.cantidad, 4)
        finally:
            _cleanup(base)


class ModifyProductAuthoritativeQuantityTest(unittest.TestCase):
    """Section 6.4, 6.5 - quantity derivation must use source.quantity."""

    def test_omitted_quantity_uses_full_source_quantity(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            orig = _seed_product(
                base,
                suffix,
                nombre=f"Origen {suffix}",
                codigo_presentacion=f"orig-{suffix}",
            )
            dest = _seed_product(
                base,
                suffix,
                nombre=f"Dest {suffix}",
                codigo_presentacion=f"dest-{suffix}",
            )
            source_line_id = _seed_pedido_line(base, orig["pp_id"], 4)

            with TestingSessionLocal() as db, db.begin():
                result = PedidoProductoService(db).modify_product(
                    base["pedido_id"],
                    source_line_id,
                    dest["pp_id"],
                    None,
                )

            self.assertEqual(result.status, "executed")
            self.assertEqual(result.cantidad_modificada, 4)
            self.assertEqual(result.cantidad_destino_final, 4)

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertIsNone(source)
                dest_line = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == base["pedido_id"],
                        PedidoProducto.id_producto_presentacion == dest["pp_id"],
                    )
                ).scalar_one()
                self.assertEqual(dest_line.cantidad, 4)
        finally:
            _cleanup(base)

    def test_resolve_cantidad_a_modificar_never_substitutes_one(self):
        from backend.services.pedido_producto_service import PedidoProductoService

        # None → source quantity
        self.assertEqual(
            PedidoProductoService._resolve_cantidad_a_modificar(None, 4), 4
        )
        self.assertEqual(
            PedidoProductoService._resolve_cantidad_a_modificar(None, 99), 99
        )
        # explicit positive → explicit
        self.assertEqual(
            PedidoProductoService._resolve_cantidad_a_modificar(2, 5), 2
        )
        # invalid types → None
        self.assertIsNone(
            PedidoProductoService._resolve_cantidad_a_modificar(0, 5)
        )
        self.assertIsNone(
            PedidoProductoService._resolve_cantidad_a_modificar(-1, 5)
        )
        self.assertIsNone(
            PedidoProductoService._resolve_cantidad_a_modificar(True, 5)
        )
        self.assertIsNone(
            PedidoProductoService._resolve_cantidad_a_modificar("1", 5)
        )


class ModifyProductDistinctDestinationQuantityTest(unittest.TestCase):
    """Section 7 - paired `2 -> 1` modification atomic mutation."""

    def test_distinct_quantity_decrements_source_creates_destination(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            orig = _seed_product(
                base,
                suffix,
                nombre=f"Origen {suffix}",
                codigo_presentacion=f"orig-{suffix}",
            )
            dest = _seed_product(
                base,
                suffix,
                nombre=f"Dest {suffix}",
                codigo_presentacion=f"dest-{suffix}",
            )
            source_line_id = _seed_pedido_line(base, orig["pp_id"], 7)

            with TestingSessionLocal() as db, db.begin():
                result = PedidoProductoService(db).modify_product(
                    base["pedido_id"],
                    source_line_id,
                    dest["pp_id"],
                    2,
                    1,
                )

            self.assertEqual(result.status, "executed")
            self.assertEqual(result.cantidad_modificada, 2)
            self.assertEqual(result.cantidad_destino_modificada, 1)
            self.assertEqual(result.cantidad_origen_restante, 5)
            self.assertEqual(result.cantidad_destino_final, 1)

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertIsNotNone(source)
                self.assertEqual(source.cantidad, 5)
                dest_line = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == base["pedido_id"],
                        PedidoProducto.id_producto_presentacion == dest["pp_id"],
                    )
                ).scalar_one()
                self.assertEqual(dest_line.cantidad, 1)
        finally:
            _cleanup(base)

    def test_absent_destination_quantity_mirrors_source(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            orig = _seed_product(
                base,
                suffix,
                nombre=f"Origen {suffix}",
                codigo_presentacion=f"orig-{suffix}",
            )
            dest = _seed_product(
                base,
                suffix,
                nombre=f"Dest {suffix}",
                codigo_presentacion=f"dest-{suffix}",
            )
            source_line_id = _seed_pedido_line(base, orig["pp_id"], 4)

            with TestingSessionLocal() as db, db.begin():
                result = PedidoProductoService(db).modify_product(
                    base["pedido_id"],
                    source_line_id,
                    dest["pp_id"],
                    2,
                    None,
                )

            self.assertEqual(result.status, "executed")
            self.assertEqual(result.cantidad_modificada, 2)
            self.assertEqual(result.cantidad_destino_modificada, 2)
            self.assertEqual(result.cantidad_destino_final, 2)
        finally:
            _cleanup(base)

    def test_zero_destination_quantity_rejected(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            orig = _seed_product(
                base,
                suffix,
                nombre=f"Origen {suffix}",
                codigo_presentacion=f"orig-{suffix}",
            )
            dest = _seed_product(
                base,
                suffix,
                nombre=f"Dest {suffix}",
                codigo_presentacion=f"dest-{suffix}",
            )
            source_line_id = _seed_pedido_line(base, orig["pp_id"], 4)

            with TestingSessionLocal() as db, db.begin():
                result = PedidoProductoService(db).modify_product(
                    base["pedido_id"],
                    source_line_id,
                    dest["pp_id"],
                    2,
                    0,
                )

            self.assertEqual(result.status, "rejected")
            self.assertEqual(result.reason, "invalid_quantity")

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertIsNotNone(source)
                self.assertEqual(source.cantidad, 4)
        finally:
            _cleanup(base)

    def test_consolidated_destination_uses_destination_quantity(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            orig = _seed_product(
                base,
                suffix,
                nombre=f"Origen {suffix}",
                codigo_presentacion=f"orig-{suffix}",
            )
            dest = _seed_product(
                base,
                suffix,
                nombre=f"Dest {suffix}",
                codigo_presentacion=f"dest-{suffix}",
            )
            source_line_id = _seed_pedido_line(base, orig["pp_id"], 5)
            existing_dest_id = _seed_pedido_line(base, dest["pp_id"], 2)

            with TestingSessionLocal() as db, db.begin():
                result = PedidoProductoService(db).modify_product(
                    base["pedido_id"],
                    source_line_id,
                    dest["pp_id"],
                    2,
                    1,
                )

            self.assertEqual(result.status, "executed")
            self.assertEqual(result.cantidad_destino_modificada, 1)
            self.assertEqual(result.cantidad_destino_final, 3)
            self.assertFalse(result.destino_creado)

            with TestingSessionLocal() as db:
                existing_dest = db.get(PedidoProducto, existing_dest_id)
                self.assertEqual(existing_dest.cantidad, 3)
        finally:
            _cleanup(base)


class ModifyProductPriceSnapshotOrderingTest(unittest.TestCase):
    """Section 6.6 - current_precio is read before any source mutation."""

    def test_current_precio_read_before_source_mutation(self):
        """Ensure the service reads `current_precio` strictly before the source mutation.

        We patch `PedidoProductoRepository.decrement` to record its access
        order; `current_precio` must complete before `decrement` runs.
        """
        suffix = _suffix()
        base = _seed(suffix)
        try:
            orig = _seed_product(
                base,
                suffix,
                nombre=f"Origen {suffix}",
                codigo_presentacion=f"orig-{suffix}",
            )
            dest = _seed_product(
                base,
                suffix,
                nombre=f"Dest {suffix}",
                codigo_presentacion=f"dest-{suffix}",
            )
            source_line_id = _seed_pedido_line(base, orig["pp_id"], 5)

            call_order: list[str] = []

            real_repo = PedidoProductoService
            real_modify = real_repo.modify_product

            def _wrap_delete(self, item):
                call_order.append("delete_source")
                return self._session.delete(item)

            def _wrap_current_precio(self, pp_id):
                call_order.append("current_precio")
                return self._session.execute(
                    select(Precio).where(Precio.id_producto_presentacion == pp_id)
                ).scalar_one_or_none()

            with patch(
                "backend.repositories.pedido_producto_repository.PedidoProductoRepository.delete",
                _wrap_delete,
            ), patch(
                "backend.repositories.pedido_producto_repository.PedidoProductoRepository.current_precio",
                _wrap_current_precio,
            ):
                with TestingSessionLocal() as db, db.begin():
                    real_modify(
                        PedidoProductoService(db),
                        base["pedido_id"],
                        source_line_id,
                        dest["pp_id"],
                        None,
                    )

            self.assertIn("current_precio", call_order)
            self.assertIn("delete_source", call_order)
            self.assertLess(
                call_order.index("current_precio"),
                call_order.index("delete_source"),
            )
        finally:
            _cleanup(base)


class HandlerReReadSourceCantidadTest(unittest.TestCase):
    """Section 6.7 - handler re-reads source quantity when omitted."""

    def test_handler_re_reads_cantidad_when_omitted(self):
        """When the resolved intent carries `cantidad is None`, the handler
        re-reads the current `PedidoProducto.cantidad` and passes that value
        to `PedidoProductoService.modify_product`.
        """
        suffix = _suffix()
        base = _seed(suffix)
        try:
            orig = _seed_product(
                base,
                suffix,
                nombre=f"Origen {suffix}",
                codigo_presentacion=f"orig-{suffix}",
            )
            dest = _seed_product(
                base,
                suffix,
                nombre=f"Dest {suffix}",
                codigo_presentacion=f"dest-{suffix}",
            )
            source_line_id = _seed_pedido_line(base, orig["pp_id"], 4)

            from backend.services.exceptions import ModificationFailed
            from backend.services.modification_result import ModificationResult

            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, base["session_id"])
                assert session_row is not None
                intent = ProcessedIntent(
                    intent="modificar_producto",
                    source_text="cambia",
                    status="ready",
                    recognizer="modificar_producto_recognizer",
                    handler="modificar_producto",
                    resolved_data={
                        "pedido_producto_origen_id": source_line_id,
                        "producto_presentacion_destino_id": dest["pp_id"],
                        "cantidad": None,
                    },
                )
                with patch.object(
                    handler_module, "PedidoProductoService"
                ) as service_cls:
                    service = MagicMock()
                    service.modify_product.return_value = ModificationResult(
                        status="executed",
                        producto_origen_nombre=orig["producto_nombre"],
                        presentacion_origen=orig["presentacion_codigo"],
                        producto_destino_nombre=dest["producto_nombre"],
                        presentacion_destino=dest["presentacion_codigo"],
                        cantidad_modificada=4,
                        cantidad_origen_restante=0,
                        cantidad_destino_final=4,
                        origen_eliminado=True,
                        destino_creado=True,
                    )
                    service_cls.return_value = service

                    result = execute_modificar_producto(db, session_row, intent)

            self.assertEqual(result.status, "executed")
            self.assertEqual(result.resolved_data["cantidad_modificada"], 4)
            # The handler must have passed `4` (the re-read) instead of `None`.
            called_with = service.modify_product.call_args
            self.assertEqual(called_with.args[3], 4)
        finally:
            _cleanup(base)


class HandlerForbidsCompositionTest(unittest.TestCase):
    """Section 6.8 - handler must not import quitar or agregar handlers."""

    def test_handler_does_not_import_quitar_or_agregar_handlers(self):
        from backend.intents.handlers import (
            agregar_producto_handler,
            quitar_producto_handler,
        )

        self.assertNotIn(
            "execute_quitar_producto",
            dir(handler_module),
        )
        self.assertNotIn(
            "execute_agregar_producto",
            dir(handler_module),
        )
        # Cross-check that the handlers exist elsewhere, otherwise our test
        # would be vacuously true.
        self.assertTrue(callable(quitar_producto_handler.execute_quitar_producto))
        self.assertTrue(callable(agregar_producto_handler.execute_agregar_producto))

    def test_handler_returns_one_processed_intent(self):
        from backend.services.modification_result import ModificationResult

        with patch.object(handler_module, "PedidoProductoService") as service_cls:
            service = MagicMock()
            service.modify_product.return_value = ModificationResult(
                status="executed",
                producto_origen_nombre="A",
                presentacion_origen="a",
                producto_destino_nombre="B",
                presentacion_destino="b",
                cantidad_modificada=1,
                cantidad_origen_restante=0,
                cantidad_destino_final=1,
                origen_eliminado=True,
                destino_creado=True,
            )
            service_cls.return_value = service
            db = MagicMock()
            db.get.return_value = None
            session = MagicMock()
            session.id_pedido = 7
            intent = ProcessedIntent(
                intent="modificar_producto",
                source_text="x",
                status="ready",
                recognizer="modificar_producto_recognizer",
                handler="modificar_producto",
                resolved_data={
                    "pedido_producto_origen_id": 1,
                    "producto_presentacion_destino_id": 2,
                    "cantidad": 1,
                },
            )
            result = execute_modificar_producto(db, session, intent)

            # Section 6.9: returns exactly one ProcessedIntent
            self.assertIsInstance(result, ProcessedIntent)
            # The service was called exactly once
            service.modify_product.assert_called_once()


class InitialOrchestrationPreservesOmittedQuantityTest(unittest.TestCase):
    """Section 6.10 - process_initial_modificar_producto must persist None."""

    def test_recognizer_returns_none_cantidad_when_message_omits_quantity(self):
        """When the user's message omits the explicit quantity, the
        recognizer returns `cantidad is None` instead of substituting `1`.
        """
        suffix = _suffix()
        base = _seed(suffix)
        try:
            orig = _seed_product(
                base,
                suffix,
                nombre=f"Empanada Orig {suffix}",
                codigo_presentacion=f"orig-{suffix}",
            )
            dest = _seed_product(
                base,
                suffix,
                nombre=f"Empanada Dest {suffix}",
                codigo_presentacion=f"dest-{suffix}",
            )
            _seed_pedido_line(base, orig["pp_id"], 4)

            with TestingSessionLocal() as db:
                session_row = db.get(SessionModel, base["session_id"])
                assert session_row is not None

                recognized = recognize_modificar_producto(
                    db,
                    session_row,
                    "cambia la orig por dest",
                )

            self.assertIsNone(recognized["cantidad"])
            self.assertEqual(
                len(recognized["source_candidate_ids"]), 1,
                f"Expected 1 source candidate but got {recognized['source_candidate_ids']}",
            )
            self.assertEqual(
                len(recognized["destination_candidate_ids"]), 1,
                f"Expected 1 destination candidate but got {recognized['destination_candidate_ids']}",
            )
        finally:
            _cleanup(base)

    def test_initial_orchestrator_persists_none_cantidad_through_to_handler(self):
        """When the recognizer returns `cantidad is None`, the orchestrator
        forwards `None` to the handler and the destination receives the
        re-read source quantity. The destination quantity SHALL NEVER be `1`.
        """
        suffix = _suffix()
        base = _seed(suffix)
        try:
            orig = _seed_product(
                base,
                suffix,
                nombre=f"Empanada Orig {suffix}",
                codigo_presentacion=f"orig-{suffix}",
            )
            dest = _seed_product(
                base,
                suffix,
                nombre=f"Empanada Dest {suffix}",
                codigo_presentacion=f"dest-{suffix}",
            )
            _seed_pedido_line(base, orig["pp_id"], 4)

            from backend.services.exceptions import ModificationFailed
            from backend.services.modification_result import ModificationResult

            with patch.object(handler_module, "PedidoProductoService") as svc_cls:
                service = MagicMock()
                service.modify_product.return_value = ModificationResult(
                    status="executed",
                    producto_origen_nombre=orig["producto_nombre"],
                    presentacion_origen=orig["presentacion_codigo"],
                    producto_destino_nombre=dest["producto_nombre"],
                    presentacion_destino=dest["presentacion_codigo"],
                    cantidad_modificada=4,
                    cantidad_origen_restante=0,
                    cantidad_destino_final=4,
                    origen_eliminado=True,
                    destino_creado=True,
                )
                svc_cls.return_value = service

                with TestingSessionLocal() as db:
                    session_row = db.get(SessionModel, base["session_id"])
                    assert session_row is not None
                    intent = process_initial_modificar_producto(
                        db,
                        session_row,
                        "cambia la orig por dest",
                    )

                # The orchestrator should forward None to the handler;
                # the handler will then re-read and pass 4 to the service.
                self.assertEqual(intent.status, "executed")
                # The handler must have been called with 4 (the re-read value).
                service.modify_product.assert_called_once()
                args = service.modify_product.call_args.args
                self.assertEqual(args[3], 4)
        finally:
            _cleanup(base)


class ResolverPreservesOmittedQuantityAcrossStagesTest(unittest.TestCase):
    """Section 6.11 - resolve_product_modification must persist None."""

    def test_resolver_preserves_none_cantidad_across_destination_selection(self):
        """When the resolver advances from `source_selection` to
        `destination_selection`, the persisted `cantidad` remains `None`.
        """
        active_intent = ProcessedIntent(
            intent="modificar_producto",
            source_text="cambia",
            status="pending_resolution",
            recognizer="modificar_producto_recognizer",
            handler="modificar_producto",
            stage="destination_selection",
            resolved_data={
                "source_candidate_ids": [1],
                "destination_candidate_ids": [10, 11],
                "cantidad": None,
            },
            requirements=[],
            candidate_ids=[],
        )
        with patch(
            "backend.intents.context.product_modification_resolver.ProductoQueryService"
        ) as pq_cls:
            pq_cls.return_value.list_presentaciones_by_ids.return_value = [
                {"producto_presentacion_id": 10, "producto_nombre": "Dest10"},
                {"producto_presentacion_id": 11, "producto_nombre": "Dest11"},
            ]
            with patch(
                "backend.intents.context.product_modification_resolver.detectar_productos"
            ) as detectar:
                detectar.return_value = {
                    "encontrados": [
                        {"producto_presentacion_id": 10, "producto_nombre": "X"},
                    ],
                    "encontrados_posibles": [],
                }
                db = MagicMock()
                session = MagicMock()
                session.id_pedido = 1
                session.id_comercio = 1
                result = resolve_product_modification(
                    db, session, "el primero", active_intent
                )

        self.assertEqual(result.status, "ready")
        self.assertIsNone(result.resolved_data.get("cantidad"))


if __name__ == "__main__":
    unittest.main()
