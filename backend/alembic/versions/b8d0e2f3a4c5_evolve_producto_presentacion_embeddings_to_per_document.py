"""Evolve producto_presentacion_embeddings to per-document rows.

Subphase 4.6 rewrites the persistence boundary from one aggregate row per
``(id_producto_presentacion, modelo)`` to one row per semantic document
(``canonical`` / ``description`` / ``alias`` / ``combined``). The migration
is hand-written in a single transaction with one explicit strategy for
the placeholder rows from Subphase 4.3: ``TRUNCATE TABLE
producto_presentacion_embeddings RESTART IDENTITY``. There is NO pointless
backfill-then-truncate cycle.

The placeholder rows have no ``source_type``, no ``source_text``, no
``content_hash`` and cannot be reconciled into per-document rows; they are
dev/test-only and the truncation is documented accordingly. This matches
the Subphase 2.13 precedent for dev/test fixture rows.

New columns added (initially nullable, then NOT NULL applied after the
truncate and the partition of the legacy uniqueness rule):

- ``source_type String(32)`` — closed set ``canonical|description|alias|combined``
- ``source_record_id Integer`` — nullable; non-null for ``alias`` rows
- ``source_text Text`` — non-empty after trimming
- ``normalized_text Text`` — non-empty after trimming
- ``content_hash String(64)`` — lowercase 64-character hex SHA-256
- ``embedding_status String(32)`` — closed set
  ``pending|ready|failed|stale|inactive``; default ``'pending'``
- ``activo Boolean`` — default ``True``, server default ``"true"``
- ``last_error Text`` — nullable

The legacy ``(id_producto_presentacion, modelo)`` aggregate unique
constraint is dropped. Two PostgreSQL partial unique indexes replace it:

- ``uq_embedding_doc_null_source`` covers ``canonical`` / ``description``
  / ``combined`` (one slot each per presentation per model).
- ``uq_embedding_doc_alias`` covers ``alias`` rows (one slot per alias
  per presentation per model).

Seven table-level ``CHECK`` constraints enforce the closed value sets
and the inter-column invariants:

- ``source_type_chk``
- ``source_record_id_alias_chk``
- ``ready_vector_chk``
- ``content_hash_chk``
- ``source_text_nonempty_chk``
- ``normalized_text_nonempty_chk``
- ``embedding_status_chk``

``vector`` becomes ``nullable=True`` because non-ready states may not
have a vector; the ``ready_vector_chk`` enforces the ``ready → vector
not null`` invariant.

``downgrade()`` is deterministic and runs in this exact order: FIRST
``TRUNCATE TABLE producto_presentacion_embeddings RESTART IDENTITY``
(so the table is empty before any legacy-shape rule is restored),
THEN drop the two partial indexes, drop the seven ``CHECK`` constraints,
drop the new columns, restore the legacy ``(id_producto_presentacion,
modelo)`` ``UniqueConstraint``, and restore ``vector`` to
``nullable=False``. The truncate MUST run BEFORE restoring the legacy
uniqueness rule and BEFORE restoring ``vector NOT NULL``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8d0e2f3a4c5"
down_revision: str | Sequence[str] | None = "a7c9e1f2b3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1.2 Add new columns nullable initially.
    op.add_column(
        "producto_presentacion_embeddings",
        sa.Column("source_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "producto_presentacion_embeddings",
        sa.Column("source_record_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "producto_presentacion_embeddings",
        sa.Column("source_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "producto_presentacion_embeddings",
        sa.Column("normalized_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "producto_presentacion_embeddings",
        sa.Column("content_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "producto_presentacion_embeddings",
        sa.Column(
            "embedding_status",
            sa.String(length=32),
            nullable=True,
            server_default=sa.text("'pending'"),
        ),
    )
    op.add_column(
        "producto_presentacion_embeddings",
        sa.Column(
            "activo",
            sa.Boolean(),
            nullable=True,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "producto_presentacion_embeddings",
        sa.Column("last_error", sa.Text(), nullable=True),
    )

    # 1.3 Single explicit strategy for placeholder dev/test rows from
    # Subphase 4.3. They have no source_type, no source_text, no
    # content_hash and cannot be reconciled into per-document rows.
    op.execute("TRUNCATE TABLE producto_presentacion_embeddings RESTART IDENTITY")

    # 1.4 Drop the legacy aggregate uniqueness rule.
    op.drop_constraint(
        "producto_presentacion_embedding_unico",
        "producto_presentacion_embeddings",
        type_="unique",
    )

    # 1.5 Make vector nullable. non-ready states may not have a vector.
    op.alter_column(
        "producto_presentacion_embeddings",
        "vector",
        existing_type=sa.String(),
        nullable=True,
    )

    # 1.6 Add seven table-level CHECK constraints.
    op.create_check_constraint(
        "source_type_chk",
        "producto_presentacion_embeddings",
        "source_type IN ('canonical','description','alias','combined')",
    )
    op.create_check_constraint(
        "source_record_id_alias_chk",
        "producto_presentacion_embeddings",
        (
            "(source_type = 'alias' AND source_record_id IS NOT NULL) "
            "OR (source_type <> 'alias' AND source_record_id IS NULL)"
        ),
    )
    op.create_check_constraint(
        "ready_vector_chk",
        "producto_presentacion_embeddings",
        "embedding_status <> 'ready' OR vector IS NOT NULL",
    )
    op.create_check_constraint(
        "content_hash_chk",
        "producto_presentacion_embeddings",
        "content_hash ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "source_text_nonempty_chk",
        "producto_presentacion_embeddings",
        "length(btrim(source_text)) > 0",
    )
    op.create_check_constraint(
        "normalized_text_nonempty_chk",
        "producto_presentacion_embeddings",
        "length(btrim(normalized_text)) > 0",
    )
    op.create_check_constraint(
        "embedding_status_chk",
        "producto_presentacion_embeddings",
        "embedding_status IN ('pending','ready','failed','stale','inactive')",
    )

    # 1.7 Partial unique index for canonical / description / combined
    # (one slot each per presentation per model).
    op.create_index(
        "uq_embedding_doc_null_source",
        "producto_presentacion_embeddings",
        ["id_producto_presentacion", "modelo", "source_type"],
        unique=True,
        postgresql_where=sa.text("source_record_id IS NULL"),
    )

    # 1.8 Partial unique index for alias rows (one slot per alias per
    # presentation per model).
    op.create_index(
        "uq_embedding_doc_alias",
        "producto_presentacion_embeddings",
        ["id_producto_presentacion", "modelo", "source_type", "source_record_id"],
        unique=True,
        postgresql_where=sa.text("source_record_id IS NOT NULL"),
    )

    # 1.9 Set NOT NULL on the columns that must be non-null after the
    # data shape is enforced. embedding_status / activo use the existing
    # server defaults so the NOT NULL rewrite does not require explicit
    # populating.
    op.alter_column(
        "producto_presentacion_embeddings",
        "source_type",
        existing_type=sa.String(length=32),
        nullable=False,
    )
    op.alter_column(
        "producto_presentacion_embeddings",
        "source_text",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.alter_column(
        "producto_presentacion_embeddings",
        "normalized_text",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.alter_column(
        "producto_presentacion_embeddings",
        "content_hash",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.alter_column(
        "producto_presentacion_embeddings",
        "embedding_status",
        existing_type=sa.String(length=32),
        nullable=False,
    )
    op.alter_column(
        "producto_presentacion_embeddings",
        "activo",
        existing_type=sa.Boolean(),
        nullable=False,
    )

    # 1.10 Re-introduce the legacy single-column indexes that the new
    # shape still benefits from (kept after the column rename and the
    # legacy UNIQUE drop).
    # No-op: indexes ix_producto_presentacion_embeddings_id_producto_presentacion
    # and ix_producto_presentacion_embeddings_modelo already exist.


def downgrade() -> None:
    # Truncate FIRST so the table is empty before any legacy-shape rule
    # is restored. This MUST run BEFORE restoring the legacy uniqueness
    # rule and BEFORE restoring vector NOT NULL.
    op.execute("TRUNCATE TABLE producto_presentacion_embeddings RESTART IDENTITY")

    # Drop the partial unique indexes.
    op.drop_index(
        "uq_embedding_doc_alias",
        table_name="producto_presentacion_embeddings",
    )
    op.drop_index(
        "uq_embedding_doc_null_source",
        table_name="producto_presentacion_embeddings",
    )

    # Drop the CHECK constraints.
    op.drop_constraint(
        "embedding_status_chk",
        "producto_presentacion_embeddings",
        type_="check",
    )
    op.drop_constraint(
        "normalized_text_nonempty_chk",
        "producto_presentacion_embeddings",
        type_="check",
    )
    op.drop_constraint(
        "source_text_nonempty_chk",
        "producto_presentacion_embeddings",
        type_="check",
    )
    op.drop_constraint(
        "content_hash_chk",
        "producto_presentacion_embeddings",
        type_="check",
    )
    op.drop_constraint(
        "ready_vector_chk",
        "producto_presentacion_embeddings",
        type_="check",
    )
    op.drop_constraint(
        "source_record_id_alias_chk",
        "producto_presentacion_embeddings",
        type_="check",
    )
    op.drop_constraint(
        "source_type_chk",
        "producto_presentacion_embeddings",
        type_="check",
    )

    # Restore vector NOT NULL. The truncate above guarantees the table is
    # empty so the NOT NULL rewrite is safe.
    op.alter_column(
        "producto_presentacion_embeddings",
        "vector",
        existing_type=sa.String(),
        nullable=False,
    )

    # Drop the new columns.
    op.drop_column("producto_presentacion_embeddings", "last_error")
    op.drop_column("producto_presentacion_embeddings", "activo")
    op.drop_column("producto_presentacion_embeddings", "embedding_status")
    op.drop_column("producto_presentacion_embeddings", "content_hash")
    op.drop_column("producto_presentacion_embeddings", "normalized_text")
    op.drop_column("producto_presentacion_embeddings", "source_text")
    op.drop_column("producto_presentacion_embeddings", "source_record_id")
    op.drop_column("producto_presentacion_embeddings", "source_type")

    # Restore the legacy aggregate uniqueness rule. truncate-first
    # guarantees there is no existing row to violate the new constraint.
    op.create_unique_constraint(
        "producto_presentacion_embedding_unico",
        "producto_presentacion_embeddings",
        ["id_producto_presentacion", "modelo"],
    )
