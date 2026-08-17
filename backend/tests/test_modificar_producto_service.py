import unittest
import uuid
from contextlib import contextmanager
from decimal import Decimal

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

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
from backend.models.pedido_producto import PedidoProducto as PedidoProductoModel
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

        prod_orig = Producto(
            id_categoria_producto=categoria.id,
            nombre=f"Pizza Orig {suffix}",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        db.add(prod_orig)
        db.flush()

        prod_dest = Producto(
            id_categoria_producto=categoria.id,
            nombre=f"Pizza Dest {suffix}",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        db.add(prod_dest)
        db.flush()

        pres_orig_chica = Presentacion(
            id_comercio=comercio.id,
            codigo=f"orig-chica-{suffix}",
            descripcion=f"orig-chica-{suffix}",
            activo=True,
            orden=0,
        )
        db.add(pres_orig_chica)
        db.flush()

        pres_dest_grande = Presentacion(
            id_comercio=comercio.id,
            codigo=f"dest-grande-{suffix}",
            descripcion=f"dest-grande-{suffix}",
            activo=True,
            orden=0,
        )
        db.add(pres_dest_grande)
        db.flush()

        pp_orig = ProductoPresentacion(
            id_producto=prod_orig.id,
            id_presentacion=pres_orig_chica.id,
            activo=True,
            orden=0,
        )
        db.add(pp_orig)
        db.flush()

        pp_dest = ProductoPresentacion(
            id_producto=prod_dest.id,
            id_presentacion=pres_dest_grande.id,
            activo=True,
            orden=0,
        )
        db.add(pp_dest)
        db.flush()

        db.add(Precio(id_producto_presentacion=pp_orig.id, precio=Decimal("100.00")))
        db.add(Precio(id_producto_presentacion=pp_dest.id, precio=Decimal("250.00")))
        db.flush()

        return {
            "comercio_id": comercio.id,
            "cliente_id": cliente.id,
            "session_id": session_row.id,
            "pedido_id": pedido.id,
            "categoria_id": categoria.id,
            "producto_ids": [prod_orig.id, prod_dest.id],
            "pp_orig": pp_orig.id,
            "pp_dest": pp_dest.id,
            "pp_dest_id": pp_dest.id,
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
            db.flush()
        db.execute(delete(PedidoProducto).where(PedidoProducto.id_pedido == base["pedido_id"]))
        db.execute(
            delete(Precio).where(Precio.id_producto_presentacion.in_([base["pp_orig"], base["pp_dest"]]))
        )
        db.execute(
            delete(ProductoPresentacion).where(
                ProductoPresentacion.id.in_([base["pp_orig"], base["pp_dest"]])
            )
        )
        db.execute(delete(Producto).where(Producto.id.in_(base["producto_ids"])))
        db.execute(delete(CategoriaProducto).where(CategoriaProducto.id == base["categoria_id"]))
        db.execute(delete(Pedido).where(Pedido.id == base["pedido_id"]))
        db.execute(delete(SessionModel).where(SessionModel.id == base["session_id"]))
        db.execute(delete(Cliente).where(Cliente.id == base["cliente_id"]))
        db.execute(delete(Comercio).where(Comercio.id == base["comercio_id"]))


class ModifyProductFullSwapTest(unittest.TestCase):
    def test_full_swap_with_omitted_cantidad(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_orig"], 3)

            with TestingSessionLocal() as db, db.begin():
                result = PedidoProductoService(db).modify_product(
                    base["pedido_id"],
                    source_line_id,
                    base["pp_dest"],
                    None,
                )

            self.assertEqual(result.status, "executed")
            self.assertEqual(result.cantidad_modificada, 3)
            self.assertEqual(result.cantidad_origen_restante, 0)
            self.assertEqual(result.cantidad_destino_final, 3)
            self.assertTrue(result.origen_eliminado)
            self.assertTrue(result.destino_creado)

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertIsNone(source)
                dest_line = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == base["pedido_id"],
                        PedidoProducto.id_producto_presentacion == base["pp_dest"],
                    )
                ).scalar_one()
                self.assertEqual(dest_line.cantidad, 3)
                self.assertEqual(dest_line.precio_unitario, Decimal("250.00"))
        finally:
            _cleanup(base)

    def test_partial_modification_decrements_source_creates_destination(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_orig"], 5)

            with TestingSessionLocal() as db, db.begin():
                result = PedidoProductoService(db).modify_product(
                    base["pedido_id"],
                    source_line_id,
                    base["pp_dest"],
                    2,
                )

            self.assertEqual(result.status, "executed")
            self.assertEqual(result.cantidad_modificada, 2)
            self.assertEqual(result.cantidad_origen_restante, 3)
            self.assertEqual(result.cantidad_destino_final, 2)
            self.assertFalse(result.origen_eliminado)
            self.assertTrue(result.destino_creado)

            with TestingSessionLocal() as db:
                source = db.get(PedidoProducto, source_line_id)
                self.assertEqual(source.cantidad, 3)
                dest_line = db.execute(
                    select(PedidoProducto).where(
                        PedidoProducto.id_pedido == base["pedido_id"],
                        PedidoProducto.id_producto_presentacion == base["pp_dest"],
                    )
                ).scalar_one()
                self.assertEqual(dest_line.cantidad, 2)
        finally:
            _cleanup(base)

    def test_consolidated_destination_increments_existing(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_orig"], 2)
            existing_dest_id = _seed_line(base, base["pp_dest"], 5)

            with TestingSessionLocal() as db, db.begin():
                result = PedidoProductoService(db).modify_product(
                    base["pedido_id"],
                    source_line_id,
                    base["pp_dest"],
                    None,
                )

            self.assertEqual(result.status, "executed")
            self.assertEqual(result.cantidad_modificada, 2)
            self.assertEqual(result.cantidad_destino_final, 7)
            self.assertFalse(result.destino_creado)

            with TestingSessionLocal() as db:
                dest_line = db.get(PedidoProducto, existing_dest_id)
                self.assertEqual(dest_line.cantidad, 7)
                source = db.get(PedidoProducto, source_line_id)
                self.assertIsNone(source)
        finally:
            _cleanup(base)


class ModifyProductValidationTest(unittest.TestCase):
    def test_quantity_exceeds_source_returns_rejected(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_orig"], 2)

            with TestingSessionLocal() as db, db.begin():
                result = PedidoProductoService(db).modify_product(
                    base["pedido_id"],
                    source_line_id,
                    base["pp_dest"],
                    5,
                )

            self.assertEqual(result.status, "rejected")
            self.assertEqual(result.reason, "quantity_exceeds_source")
            self.assertEqual(result.cantidad_actual, 2)
        finally:
            _cleanup(base)

    def test_invalid_quantity_returns_rejected(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_orig"], 2)

            with TestingSessionLocal() as db, db.begin():
                result = PedidoProductoService(db).modify_product(
                    base["pedido_id"],
                    source_line_id,
                    base["pp_dest"],
                    0,
                )

            self.assertEqual(result.status, "rejected")
            self.assertEqual(result.reason, "invalid_quantity")
        finally:
            _cleanup(base)

    def test_source_not_in_pedido_returns_rejected(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            with TestingSessionLocal() as db, db.begin():
                result = PedidoProductoService(db).modify_product(
                    base["pedido_id"],
                    99999,
                    base["pp_dest"],
                    1,
                )

            self.assertEqual(result.status, "rejected")
            self.assertEqual(result.reason, "source_not_in_pedido")
        finally:
            _cleanup(base)

    def test_equivalent_modification_returns_rejected(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_orig"], 2)

            with TestingSessionLocal() as db, db.begin():
                result = PedidoProductoService(db).modify_product(
                    base["pedido_id"],
                    source_line_id,
                    base["pp_orig"],
                    1,
                )

            self.assertEqual(result.status, "rejected")
            self.assertEqual(result.reason, "equivalent_modification")
        finally:
            _cleanup(base)

    def test_destination_unavailable_returns_rejected(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            source_line_id = _seed_line(base, base["pp_orig"], 2)

            with TestingSessionLocal() as db, db.begin():
                result = PedidoProductoService(db).modify_product(
                    base["pedido_id"],
                    source_line_id,
                    99999,
                    1,
                )

            self.assertEqual(result.status, "rejected")
            self.assertEqual(result.reason, "destination_unavailable")
        finally:
            _cleanup(base)


if __name__ == "__main__":
    unittest.main()
