"""Phase-7.4 deferred provider inbound processing work item.

A ``ProcesamientoMensajeProveedor`` is the durable, lease-protected
work item that records the deferred business processing of one
provider-message receipt. The webhook acceptance path inserts exactly
one pending row alongside the receipt; the bounded operator CLI then
leases, processes and finalizes it through the existing
``process_incoming_message`` pipeline and outbox mapper.

The work item is keyed one-to-one by the unique foreign key
``recepcion_mensaje_proveedor_id``: a second ``INSERT`` for an
existing receipt is blocked by the database so the deferred work can
never duplicate. The row carries a transient ``mensaje`` body that is
populated only while the work is ``pending``, ``leased`` or
``retryable``; the deferred processor clears the body on successful
processing or terminal exhaustion so the row retains only safe state,
timestamps and failure metadata.

The work item never stores the customer destination (E.164) nor any
provider payload, signature or credential. The deferred processor
derives the destination outbound address from the still-authoritative
``cliente`` row referenced by the linked receipt; copying the address
onto the work item would let a stale work item target a number that no
longer belongs to this conversation.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class ProcesamientoMensajeProveedorEstado(str, enum.Enum):
    """Typed state machine for the deferred inbound work item.

    The state value is the single source of truth for branching. The
    bounded CLI and the deferred processor branch on ``estado`` and
    MUST NOT mutate ``intentos``, ``proximo_intento_en``, lease,
    ``categoria_ultimo_fallo``, ``codigo_ultimo_fallo`` or the
    transient ``mensaje`` body except through the documented
    transitions:

    * ``pending`` is the initial state after webhook acceptance.
    * ``leased`` is set when the operator CLI claims a due row.
    * ``retryable`` is set on transport / transient technical
      failures while the attempt budget remains.
    * ``processed`` is set after the deferred processor commits
      session/pedido/pipeline/outbox effects; the transient body is
      cleared in the same commit.
    * ``failed_terminal`` is set on exhausted retries or terminal
      processor failures; the transient body is cleared.

    ``processed`` and ``failed_terminal`` are terminal: they MUST NOT
    transition to any other state.
    """

    PENDING = "pending"
    LEASED = "leased"
    RETRYABLE = "retryable"
    PROCESSED = "processed"
    FAILED_TERMINAL = "failed_terminal"


class ProcesamientoMensajeProveedorFailureCategory(str, enum.Enum):
    """Safe technical-failure classification.

    The category is the only durable identifier of a transient or
    terminal processing failure. Raw exception text, provider signature
    bytes and inbound text never reach this row. ``PIPELINE_ERROR``
    and ``DATABASE_ERROR`` cover the documented bounded retry
    outcomes; ``BUDGET_EXHAUSTED`` is terminal and is set by the
    processor when the configured maximum attempt count is reached
    without success; ``TERMINAL_PROCESSOR_ERROR`` is terminal and is
    set for unrecoverable processor exceptions.
    """

    PIPELINE_ERROR = "pipeline_error"
    DATABASE_ERROR = "database_error"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TERMINAL_PROCESSOR_ERROR = "terminal_processor_error"


class ProcesamientoMensajeProveedorLLMOutcome(str, enum.Enum):
    """Closed, safe classification of one LLM call attempt.

    The outcome is the only durable identifier of how the existing
    ``QueryLlm`` call finished for the provider-path work item. The
    enum intentionally omits prompt text, response body, customer
    text, exception messages and provider payloads. ``COMPLETED``
    means the upstream returned a parseable response; ``TIMEOUT``
    means the existing configured timeout elapsed before any
    response arrived; ``ERROR`` covers every other bounded failure
    (HTTP error, connection error, response error).
    """

    COMPLETED = "completed"
    TIMEOUT = "timeout"
    ERROR = "error"


class ProcesamientoMensajeProveedor(Base):
    __tablename__ = "procesamientos_mensajes_proveedor"

    __table_args__ = (
        UniqueConstraint(
            "recepcion_mensaje_proveedor_id",
            name=(
                "procesamientos_mensajes_proveedor_recepcion_unico"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    recepcion_mensaje_proveedor_id: Mapped[int] = mapped_column(
        ForeignKey(
            "recepciones_mensajes_proveedor.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    estado: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ProcesamientoMensajeProveedorEstado.PENDING.value,
        server_default=ProcesamientoMensajeProveedorEstado.PENDING.value,
    )

    intentos: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    proximo_intento_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    token_lease: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    lease_expira_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    categoria_ultimo_fallo: Mapped[str | None] = mapped_column(
        String(48),
        nullable=True,
    )

    codigo_ultimo_fallo: Mapped[str | None] = mapped_column(
        String(48),
        nullable=True,
    )

    mensaje: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    fecha_finalizacion: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    llm_solicitado_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    llm_finalizado_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    llm_resultado: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )


__all__ = [
    "ProcesamientoMensajeProveedor",
    "ProcesamientoMensajeProveedorEstado",
    "ProcesamientoMensajeProveedorFailureCategory",
    "ProcesamientoMensajeProveedorLLMOutcome",
]