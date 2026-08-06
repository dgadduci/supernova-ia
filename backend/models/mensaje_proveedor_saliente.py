"""Phase-5.6 outbound provider-message outbox.

A ``MensajeProveedorSaliente`` is the durable, provider-neutral work item
that records one rendered customer response produced by a first valid
Phase-5.4 inbound receipt. The row is the sole replayable artifact: it
stores the immutable canonical destination, the rendered response body,
the provider, the inbound receipt foreign key and a zero-based
``sequence`` unique per receipt. It carries dispatch state, lease
token/expiry, attempt count, next-attempt timestamp, the provider SID
when accepted, the last safe failure category/code and the
provider-status timestamp. It never stores Twilio credentials, signature
values or raw provider callback payloads.

The row is committed atomically alongside the inbound receipt, the
compatible session and the existing message pipeline in the same
Phase-5.4 transaction. A duplicate inbound receipt creates no new row.
A rollback leaves no durable outbox state.

Foreign keys are restrictive: an operator cannot delete a receipt
while outbox rows still reference it. The unique constraint enforces
exactly one row per ``(recepcion_mensaje_proveedor_id, sequence)`` pair
so the response ordering is durable and observable.
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


class OutboundProviderMessageState(str, enum.Enum):
    """Typed outbox state machine.

    The state value is the single source of truth for branching. Every
    value maps to a single non-resolved or resolved state. The
    dispatcher and the callback service branch on ``state`` after a
    single ``process`` call and MUST NOT mutate body, destination,
    attempt count, retry eligibility or provider SID except through the
    documented transitions:

    * ``pending`` is set when the inbound transaction commits.
    * ``leased`` is set when the dispatcher claims a due row.
    * ``accepted`` is set when Twilio returns a ``MessageSid``.
    * ``retryable`` is set on transport / HTTP 429 / HTTP 5xx.
    * ``failed_terminal`` is set on definitive 4xx, exhausted retries
      or a signed terminal callback.
    * ``delivered`` is set by a signed monotonic callback.

    ``failed_terminal`` and ``delivered`` are terminal: they MUST NOT
    transition to any other state.
    """

    PENDING = "pending"
    LEASED = "leased"
    ACCEPTED = "accepted"
    RETRYABLE = "retryable"
    DELIVERED = "delivered"
    FAILED_TERMINAL = "failed_terminal"


class OutboundFailureCategory(str, enum.Enum):
    """Safe provider-failure classification.

    The category is the only durable identifier of a transient or
    definitive provider failure. Raw provider payload bytes never reach
    this row. ``RETRYABLE_TIMEOUT``, ``RETRYABLE_429`` and
    ``RETRYABLE_5XX`` are bounded by configuration; ``TERMINAL_4XX``
    stops the row immediately. ``BUDGET_EXHAUSTED`` is terminal and is
    set by the dispatcher when the configured maximum attempt count
    is reached without success.
    """

    RETRYABLE_TIMEOUT = "retryable_timeout"
    RETRYABLE_429 = "retryable_429"
    RETRYABLE_5XX = "retryable_5xx"
    TERMINAL_4XX = "terminal_4xx"
    BUDGET_EXHAUSTED = "budget_exhausted"


class MensajeProveedorSaliente(Base):
    __tablename__ = "mensajes_proveedor_salientes"

    __table_args__ = (
        UniqueConstraint(
            "recepcion_mensaje_proveedor_id",
            "sequence",
            name="mensajes_proveedor_salientes_recepcion_sequence_unico",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    proveedor: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    recepcion_mensaje_proveedor_id: Mapped[int] = mapped_column(
        ForeignKey(
            "recepciones_mensajes_proveedor.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    destinatario_e164: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    cuerpo: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    sequence: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    estado: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=OutboundProviderMessageState.PENDING.value,
        server_default=OutboundProviderMessageState.PENDING.value,
    )

    identificador_proveedor: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
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
        String(32),
        nullable=True,
    )

    codigo_ultimo_fallo: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    estado_proveedor: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    estado_proveedor_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


__all__ = [
    "MensajeProveedorSaliente",
    "OutboundFailureCategory",
    "OutboundProviderMessageState",
]