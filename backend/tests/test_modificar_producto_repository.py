import unittest
import uuid
from contextlib import contextmanager
from decimal import Decimal

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from backend.models import (
    CategoriaProducto,
    EstadoComercio,
    Precio,
    Presentacion,
    Producto,
    ProductoPresentacion,
)
from backend.models import Session as SessionModel
from backend.models.pedido_producto import PedidoProducto
from backend.models.session import EstadoSession
from backend.models.pedido import EstadoPedido, Pedido
from backend.models.cliente import Cliente
from backend.models.comercio import Comercio
from backend.repositories.pedido_producto_repository import (
    PedidoProductoRepository,
)

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _seed(suffix: str) -> dict:
    """Seed comercio, cliente, session, pedido, presentacion, pp, precio."""
    with engine.connect() as conn:
        estado_id = conn.execute(
            select(EstadoComercio.id).where(EstadoComercio.codigo == "ACTIVO")
        ).first()
        if estado_id is None:
            raise RuntimeError("estado ACTIVO not seeded")
        estado_id = estado_id[0]

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

        producto = Producto(
            id_categoria_producto=categoria.id,
            nombre=f"P-{suffix}",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        db.add(producto)
        db.flush()

        presentacion = Presentacion(
            id_comercio=comercio.id,
            codigo=f"g-{suffix}",
            descripcion=f"g-{suffix}",
            activo=True,
            orden=0,
        )
        db.add(presentacion)
        db.flush()

        pp = ProductoPresentacion(
            id_producto=producto.id,
            id_presentacion=presentacion.id,
            activo=True,
            orden=0,
        )
        db.add(pp)
        db.flush()

        precio = Precio(
            id_producto_presentacion=pp.id, precio=Decimal("100.00")
        )
        db.add(precio)
        db.flush()

        return {
            "comercio_id": comercio.id,
            "cliente_id": cliente.id,
            "session_id": session_row.id,
            "pedido_id": pedido.id,
            "categoria_id": categoria.id,
            "producto_id": producto.id,
            "presentacion_id": presentacion.id,
            "pp_id": pp.id,
        }


def _cleanup(base: dict) -> None:
    with TestingSessionLocal() as db, db.begin():
        sess_row = db.get(SessionModel, base["session_id"])
        if sess_row is not None:
            sess_row.id_pedido = None
            db.flush()
        db.execute(
            delete(PedidoProducto).where(PedidoProducto.id_pedido == base["pedido_id"])
        )
        db.execute(
            delete(Precio).where(Precio.id_producto_presentacion == base["pp_id"])
        )
        db.execute(
            delete(ProductoPresentacion).where(
                ProductoPresentacion.id == base["pp_id"]
            )
        )
        db.execute(delete(Presentacion).where(Presentacion.id == base["presentacion_id"]))
        db.execute(delete(Producto).where(Producto.id == base["producto_id"]))
        db.execute(delete(CategoriaProducto).where(CategoriaProducto.id == base["categoria_id"]))
        db.execute(delete(Pedido).where(Pedido.id == base["pedido_id"]))
        db.execute(delete(SessionModel).where(SessionModel.id == base["session_id"]))
        db.execute(delete(Cliente).where(Cliente.id == base["cliente_id"]))
        db.execute(delete(Comercio).where(Comercio.id == base["comercio_id"]))


class PedidoProductoRepositoryNewMethodsTest(unittest.TestCase):
    def test_get_for_pedido_returns_line_for_matching_pedido(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            with TestingSessionLocal() as db, db.begin():
                line = PedidoProducto(
                    id_pedido=base["pedido_id"],
                    id_producto_presentacion=base["pp_id"],
                    cantidad=3,
                    precio_unitario=Decimal("100.00"),
                )
                db.add(line)
                db.flush()
                line_id = line.id

            with TestingSessionLocal() as db:
                repo = PedidoProductoRepository(db)
                result = repo.get_for_pedido(base["pedido_id"], line_id)
                self.assertIsNotNone(result)
                self.assertEqual(result.id, line_id)

            with TestingSessionLocal() as db:
                repo = PedidoProductoRepository(db)
                result = repo.get_for_pedido(base["pedido_id"] + 999, line_id)
                self.assertIsNone(result)
        finally:
            _cleanup(base)

    def test_increment_increases_quantity(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            with TestingSessionLocal() as db, db.begin():
                line = PedidoProducto(
                    id_pedido=base["pedido_id"],
                    id_producto_presentacion=base["pp_id"],
                    cantidad=2,
                    precio_unitario=Decimal("100.00"),
                )
                db.add(line)
                db.flush()
                line_id = line.id

            with TestingSessionLocal() as db:
                repo = PedidoProductoRepository(db)
                updated = repo.increment(line_id, 3)
                self.assertEqual(updated.cantidad, 5)
        finally:
            _cleanup(base)

    def test_decrement_decreases_quantity(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            with TestingSessionLocal() as db, db.begin():
                line = PedidoProducto(
                    id_pedido=base["pedido_id"],
                    id_producto_presentacion=base["pp_id"],
                    cantidad=5,
                    precio_unitario=Decimal("100.00"),
                )
                db.add(line)
                db.flush()
                line_id = line.id

            with TestingSessionLocal() as db:
                repo = PedidoProductoRepository(db)
                updated = repo.decrement(line_id, 2)
                self.assertEqual(updated.cantidad, 3)
        finally:
            _cleanup(base)

    def test_create_with_price_snapshot_creates_row(self):
        suffix = _suffix()
        base = _seed(suffix)
        try:
            with TestingSessionLocal() as db:
                repo = PedidoProductoRepository(db)
                with db.begin():
                    row = repo.create_with_price_snapshot(
                        base["pedido_id"],
                        base["pp_id"],
                        4,
                        Decimal("250.00"),
                    )
                    self.assertEqual(row.cantidad, 4)
                    self.assertEqual(row.precio_unitario, Decimal("250.00"))
                    self.assertEqual(row.id_pedido, base["pedido_id"])
                    self.assertEqual(
                        row.id_producto_presentacion, base["pp_id"]
                    )
                    new_id = row.id

            with TestingSessionLocal() as db:
                fetched = db.get(PedidoProducto, new_id)
                self.assertIsNotNone(fetched)
                self.assertEqual(fetched.cantidad, 4)
        finally:
            _cleanup(base)


if __name__ == "__main__":
    unittest.main()
