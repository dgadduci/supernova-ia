"""Durable outbound idempotency registry for the T-C adapter.

The table is the single source of truth that prevents a second
``messages.create`` from being issued for the same
``(instalacion_id, idempotency_key)`` pair. The bounded
``OutboundCommandDispatcher`` claims a row before the network call;
the claim transaction owns the in-flight decision, so concurrent
dispatchers serialise through the database instead of trusting a
process-local cache.

The table is intentionally small and operational only. It is not a
business table: it carries no pedido, no cliente, no canal and no
catalog state. The bounded CLI never deletes rows in this phase:
deleting a row would let the bounded CLI re-issue a
``messages.create`` for a previously-sent key, which would break the
documented duplicate-send guarantee. Operations that need to drop
historical rows belong to a future operator-only change that is
explicitly out of scope.

The four documented states are the durable state machine for the
bounded retry contract:

* ``in_progress`` — the bounded dispatcher has claimed the slot
  and has not yet seen a typed response from the T-C adapter. The
  same key returned to a second caller short-circuits with
  ``already_claimed`` so no second ``messages.create`` runs. The
  state is also the durable marker for an ambiguous network
  result (timeout, connection drop, malformed body): the helper
  raises :class:`OutboundCommandAmbiguous` so the bounded CLI can
  finalize the outbox row as ``retryable`` while the durable
  claim remains ``in_progress`` for recovery. Concurrent claims
  on the same key serialise through the unique index and the
  atomic ``retryable -> in_progress`` transition;
* ``sent`` — the T-C adapter returned a SID. The claim is
  permanent in this phase; the same key returned to a second
  caller short-circuits with the known SID and never fires a
  second ``messages.create``. The bounded CLI never deletes the
  row;
* ``retryable`` — the T-C adapter or the bounded CLI drove a
  bounded retryable failure. The claim is the explicit marker
  for "the next dispatch must perform a new HTTP call". The
  next dispatch atomically transitions the row back to
  ``in_progress`` through a single ``UPDATE ... WHERE estado =
  'retryable'`` statement, then performs the new HTTP call. Two
  concurrent callers on the same ``retryable`` row serialise
  through the predicate: only one wins and runs the new send;
  the other returns the durable state without calling T-C. The
  bounded CLI keeps the same ``idempotency_key`` and never
  deletes the row;
* ``terminal`` — the T-C adapter reported a 4xx-class terminal
  failure. The claim is permanent in this phase; the same key
  returned to a second caller short-circuits with the known
  terminal failure and never fires a second
  ``messages.create``. The bounded CLI never deletes the row.

A row never carries the outbound body, the destination phone, the
auth token, the signature or the raw exception text. The bounded CLI
uses the row only to derive the next-attempt timestamp and the SID
to persist on ``MensajeProveedorSaliente.identificador_proveedor``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


IdempotencyStatus = Literal["in_progress", "sent", "retryable", "terminal"]


class InstalacionTwilioComercioIdempotencia(Base):
    """Durable claim of one outbound ``messages.create`` invocation."""

    __tablename__ = "instalaciones_twilio_comercio_idempotencia"

    __table_args__ = (
        UniqueConstraint(
            "instalacion_id",
            "idempotency_key",
            name=(
                "uq_instalacion_twilio_idempotencia_installation_key"
            ),
        ),
        Index(
            "ix_instalaciones_twilio_idempotencia_installation",
            "instalacion_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    instalacion_id: Mapped[str] = mapped_column(
        ForeignKey(
            "instalaciones_twilio_comercio.instalacion_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    idempotency_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    estado: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="in_progress",
        server_default="in_progress",
    )

    message_sid: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    codigo: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    http_status: Mapped[int | None] = mapped_column(
        nullable=True,
    )

    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    fecha_ultima_modificacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


__all__ = [
    "IdempotencyStatus",
    "InstalacionTwilioComercioIdempotencia",
]