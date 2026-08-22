"""add nullable LLM timing fields to procesamientos_mensajes_proveedor

Revision ID: a8e2f4c6d5b7
Revises: 7c4d5e6f7a8b
Create Date: 2026-08-21 18:00:00.000000

The Admin/Pilot Emulator timing observability change extends the
existing provider-path work item with three nullable columns that
record the moment the worker requested the LLM and the moment the
LLM finished normally or with a timeout/error. The columns are
additive, nullable, reversible and never hold prompts, responses,
customer text or exception detail.

The migration is intentionally additive:

* ``llm_solicitado_en`` (``TIMESTAMP WITH TIME ZONE``) is set
  before the worker invokes the existing ``QueryLlm`` boundary.
* ``llm_finalizado_en`` (``TIMESTAMP WITH TIME ZONE``) is set when
  the call returns normally, fails or reaches the configured
  timeout.
* ``llm_resultado`` (``VARCHAR(16)``) holds a closed
  ``completed``/``timeout``/``error`` token mirroring the bounded
  ``ProcesamientoMensajeProveedorLLMOutcome`` enum.

``downgrade()`` drops only the three new columns; it does not
rewrite any existing receipt, work item or outbox row and is safe
to roll back when the operator disables the timing feature.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8e2f4c6d5b7"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "procesamientos_mensajes_proveedor",
        sa.Column(
            "llm_solicitado_en",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "procesamientos_mensajes_proveedor",
        sa.Column(
            "llm_finalizado_en",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "procesamientos_mensajes_proveedor",
        sa.Column(
            "llm_resultado",
            sa.String(length=16),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "procesamientos_mensajes_proveedor",
        "llm_resultado",
    )
    op.drop_column(
        "procesamientos_mensajes_proveedor",
        "llm_finalizado_en",
    )
    op.drop_column(
        "procesamientos_mensajes_proveedor",
        "llm_solicitado_en",
    )
