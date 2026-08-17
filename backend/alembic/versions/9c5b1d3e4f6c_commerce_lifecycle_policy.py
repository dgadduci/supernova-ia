"""commerce lifecycle policy

Revision ID: 9c5b1d3e4f6c
Revises: f1g2h3i4j5k6
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9c5b1d3e4f6c"
down_revision: Union[str, Sequence[str], None] = "f1g2h3i4j5k6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add typed EstadoComercio mode/selectable fields and Comercio trial fields."""
    op.execute(
        "CREATE TYPE estado_comercio_modo_operacion AS ENUM "
        "('habilitado', 'bloqueado', 'prueba')"
    )

    op.add_column(
        "estado_comercio",
        sa.Column(
            "codigo",
            sa.String(length=50),
            nullable=False,
            server_default="__legacy__",
        ),
    )
    op.add_column(
        "estado_comercio",
        sa.Column(
            "descripcion",
            sa.String(length=150),
            nullable=False,
            server_default="__legacy__",
        ),
    )
    op.add_column(
        "estado_comercio",
        sa.Column(
            "modo_operacion",
            sa.Enum(
                "habilitado",
                "bloqueado",
                "prueba",
                name="estado_comercio_modo_operacion",
                create_type=False,
            ),
            nullable=False,
            server_default="bloqueado",
        ),
    )
    op.add_column(
        "estado_comercio",
        sa.Column(
            "seleccionable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.execute(
        "UPDATE estado_comercio SET "
        "codigo = estado, "
        "descripcion = estado, "
        "modo_operacion = CASE "
        "  WHEN estado = 'ACTIVO' THEN 'habilitado'::estado_comercio_modo_operacion "
        "  WHEN estado = 'PRUEBA' THEN 'prueba'::estado_comercio_modo_operacion "
        "  ELSE 'bloqueado'::estado_comercio_modo_operacion "
        "END, "
        "seleccionable = (estado IN ('ACTIVO', 'INACTIVO', 'PRUEBA'))"
    )

    op.alter_column("estado_comercio", "codigo", server_default=None)
    op.alter_column("estado_comercio", "descripcion", server_default=None)
    op.alter_column(
        "estado_comercio", "modo_operacion", server_default=None
    )
    op.create_unique_constraint(
        "uq_estado_comercio_codigo", "estado_comercio", ["codigo"]
    )

    op.drop_column("estado_comercio", "estado")

    op.add_column(
        "comercios",
        sa.Column(
            "prueba_hasta",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "comercios",
        sa.Column(
            "prueba_max_pedidos",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "comercios",
        sa.Column(
            "prueba_pedidos_consumidos",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint(
        "comercios_prueba_max_pedidos_positivo",
        "comercios",
        "prueba_max_pedidos IS NULL OR prueba_max_pedidos > 0",
    )
    op.create_check_constraint(
        "comercios_prueba_pedidos_consumidos_no_negativo",
        "comercios",
        "prueba_pedidos_consumidos >= 0",
    )
    op.alter_column(
        "comercios", "prueba_pedidos_consumidos", server_default=None
    )


def downgrade() -> None:
    """Revert trial columns and EstadoComercio typed fields."""
    op.drop_constraint(
        "comercios_prueba_pedidos_consumidos_no_negativo",
        "comercios",
        type_="check",
    )
    op.drop_constraint(
        "comercios_prueba_max_pedidos_positivo",
        "comercios",
        type_="check",
    )
    op.drop_column("comercios", "prueba_pedidos_consumidos")
    op.drop_column("comercios", "prueba_max_pedidos")
    op.drop_column("comercios", "prueba_hasta")

    op.add_column(
        "estado_comercio",
        sa.Column("estado", sa.String(), nullable=False, server_default=""),
    )
    op.execute(
        "UPDATE estado_comercio SET estado = COALESCE(codigo, descripcion)"
    )
    op.alter_column("estado_comercio", "estado", server_default=None)
    op.drop_constraint("uq_estado_comercio_codigo", "estado_comercio")
    op.drop_column("estado_comercio", "seleccionable")
    op.drop_column("estado_comercio", "modo_operacion")
    op.drop_column("estado_comercio", "descripcion")
    op.drop_column("estado_comercio", "codigo")
    op.execute("DROP TYPE estado_comercio_modo_operacion")