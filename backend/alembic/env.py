import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from backend.models import Base
from backend.models.canal_whatsapp import CanalWhatsapp
from backend.models.categorias_productos import CategoriaProducto
from backend.models.cliente import Cliente
from backend.models.comercio import Comercio
from backend.models.comercio_canal_compartido import ComercioCanalCompartido
from backend.models.comercio_medios_pago import ComercioMedioPago
from backend.models.comercio_metodos_entrega import ComercioMetodoEntrega
from backend.models.contexto_cliente_canal_whatsapp import (
    ContextoClienteCanalWhatsapp,
)
from backend.models.estado_comercio import EstadoComercio
from backend.models.medios_pago import MediosPago
from backend.models.mensaje_proveedor_saliente import (
    MensajeProveedorSaliente,
)
from backend.models.metodos_entrega import MetodosEntrega
from backend.models.pedido import Pedido
from backend.models.pedido_producto import PedidoProducto
from backend.models.precio import Precio
from backend.models.presentaciones import Presentacion
from backend.models.producto import Producto
from backend.models.producto_alias import ProductoAlias
from backend.models.producto_presentacion import ProductoPresentacion
from backend.models.producto_presentacion_embedding import ProductoPresentacionEmbedding
from backend.models.session import Session

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

if os.environ.get("SUPERNOVA_DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", os.environ["SUPERNOVA_DATABASE_URL"])

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
