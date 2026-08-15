"""add global communication flavors catalog and FK

Revision ID: d1d2e3f4a5b6
Revises: c1d2e3f4a5b6
Create Date: 2026-08-15 10:00:00.000000

Phase 1 of the ``add-global-communication-flavors`` change introduces
the global ``flavors_comunicacion`` catalog and a non-null
``Comercio.flavor_comunicacion_id`` foreign key. The migration is
safe for an existing database and is reversible:

1. Create ``flavors_comunicacion`` and insert the six canonical
   global records, including one active row whose code is exactly
   ``neutro``. The default seed is resolved by code, not by assumed
   numeric ID, so the migration remains correct even if the autoincrement
   counter changes.
2. Add ``comercios.flavor_comunicacion_id`` as a nullable column.
3. Backfill every existing commerce by resolving the seeded
   ``neutro`` row by code.
4. Add the foreign key and enforce ``NOT NULL``.

``downgrade()`` reverses the column constraint, drops the FK, drops
the column, and drops the catalog. The downgrade uses the
``flavors_comunicacion`` table name as the canonical reset state
because the application does not expose any flavor CRUD for the
catalog: the catalog is system-managed global seed data only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1d2e3f4a5b6"
down_revision: str | Sequence[str] | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEUTRO_FLAVOR_SEED = (
    "neutro",
    "Neutro",
    "Tono profesional y cordial sin estilo regional.",
    (
        "Mantener un tono profesional, cordial y neutro. No añadir "
        "muletillas, acentos regionales, ni modificar datos del pedido. "
        "Si la política o reglas del sistema no autorizan la respuesta, "
        "responder con la salida determinística existente."
    ),
)

CANONICAL_FLAVORS: list[tuple[str, str, str, str]] = [
    NEUTRO_FLAVOR_SEED,
    (
        "serio",
        "Serio",
        "Tono sobrio y respetuoso, sin informalismos.",
        (
            "Mantener un tono serio, sobrio y respetuoso. Evitar "
            "muletillas, emojis o humor. No alterar datos del pedido. "
            "Si la política o reglas del sistema no autorizan la "
            "respuesta, responder con la salida determinística existente."
        ),
    ),
    (
        "joven",
        "Joven",
        "Tono cordial, cercano y dinámico, sin informalidad excesiva.",
        (
            "Mantener un tono cordial, cercano y dinámico apropiado para "
            "audiencia joven. Evitar jerga agresiva, anglicismos "
            "innecesarios ni diminutivos excesivos. No alterar datos del "
            "pedido. Si la política o reglas del sistema no autorizan la "
            "respuesta, responder con la salida determinística existente."
        ),
    ),
    (
        "elegante",
        "Elegante",
        "Tono distinguido y amable, con vocabulario cuidado.",
        (
            "Mantener un tono elegante, amable y distinguido, con "
            "vocabulario cuidado y preciso. Evitar coloquialismos. No "
            "alterar datos del pedido. Si la política o reglas del "
            "sistema no autorizan la respuesta, responder con la salida "
            "determinística existente."
        ),
    ),
    (
        "mexicano",
        "Cordial contemporáneo (México)",
        "Cordial y respetuoso, con registro mexicano contemporáneo.",
        (
            "Mantener un tono cordial y respetuoso, con un registro "
            "mexicano contemporáneo natural. Tratar al cliente con "
            "respeto y cercanía, sin estereotipos ni imitaciones "
            "caricaturescas. No modificar hechos del negocio, precios, "
            "productos ni datos del pedido. Si la política o reglas del "
            "sistema no autorizan la respuesta, responder con la salida "
            "determinística existente."
        ),
    ),
    (
        "peruano",
        "Cordial contemporáneo (Perú)",
        "Cordial y respetuoso, con registro peruano contemporáneo.",
        (
            "Mantener un tono cordial y respetuoso, con un registro "
            "peruano contemporáneo natural. Tratar al cliente con "
            "respeto y cercanía, sin estereotipos ni imitaciones "
            "caricaturescas. No modificar hechos del negocio, precios, "
            "productos ni datos del pedido. Si la política o reglas del "
            "sistema no autorizan la respuesta, responder con la salida "
            "determinística existente."
        ),
    ),
]


def upgrade() -> None:
    bind = op.get_bind()
    flav_table = sa.table(
        "flavors_comunicacion",
        sa.column("id", sa.Integer),
        sa.column("codigo", sa.String),
        sa.column("nombre", sa.String),
        sa.column("descripcion", sa.String),
        sa.column("instruccion_llm", sa.String),
        sa.column("activo", sa.Boolean),
        sa.column("version", sa.Integer),
    )

    op.create_table(
        "flavors_comunicacion",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("codigo", sa.String(length=50), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("descripcion", sa.String(length=255), nullable=False),
        sa.Column("instruccion_llm", sa.String(length=2000), nullable=False),
        sa.Column(
            "activo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "fecha_alta",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "fecha_ultima_modificacion",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "codigo <> ''",
            name="flavor_comunicacion_codigo_no_vacio",
        ),
        sa.CheckConstraint(
            "nombre <> ''",
            name="flavor_comunicacion_nombre_no_vacio",
        ),
        sa.CheckConstraint(
            "descripcion <> ''",
            name="flavor_comunicacion_descripcion_no_vacia",
        ),
        sa.CheckConstraint(
            "length(instruccion_llm) > 0",
            name="flavor_comunicacion_instruccion_llm_no_vacia",
        ),
        sa.CheckConstraint(
            "version > 0",
            name="flavor_comunicacion_version_positiva",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("codigo", name="flavors_comunicacion_codigo_unico"),
    )
    op.create_index(
        op.f("ix_flavors_comunicacion_activo"),
        "flavors_comunicacion",
        ["activo"],
        unique=False,
    )

    for codigo, nombre, descripcion, instruccion in CANONICAL_FLAVORS:
        bind.execute(
            flav_table.insert().values(
                codigo=codigo,
                nombre=nombre,
                descripcion=descripcion,
                instruccion_llm=instruccion,
                activo=True,
                version=1,
            )
        )

    op.add_column(
        "comercios",
        sa.Column("flavor_comunicacion_id", sa.Integer(), nullable=True),
    )

    neutro_id = bind.execute(
        sa.select(flav_table.c.id).where(flav_table.c.codigo == "neutro")
    ).scalar_one()

    bind.execute(
        sa.text("UPDATE comercios SET flavor_comunicacion_id = :neutro_id"),
        {"neutro_id": neutro_id},
    )

    op.create_foreign_key(
        "comercios_flavor_comunicacion_fk",
        "comercios",
        "flavors_comunicacion",
        ["flavor_comunicacion_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.alter_column(
        "comercios",
        "flavor_comunicacion_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_index(
        op.f("ix_comercios_flavor_comunicacion_id"),
        "comercios",
        ["flavor_comunicacion_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_comercios_flavor_comunicacion_id"),
        table_name="comercios",
    )
    op.drop_constraint(
        "comercios_flavor_comunicacion_fk",
        "comercios",
        type_="foreignkey",
    )
    op.drop_column("comercios", "flavor_comunicacion_id")

    op.drop_index(
        op.f("ix_flavors_comunicacion_activo"),
        table_name="flavors_comunicacion",
    )
    op.drop_table("flavors_comunicacion")
