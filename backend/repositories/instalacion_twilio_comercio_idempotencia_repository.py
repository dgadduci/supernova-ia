"""SQLAlchemy queries for ``instalaciones_twilio_comercio_idempotencia``.

The repository owns the unique
``(instalacion_id, idempotency_key)`` claim lifecycle and the
durable state machine that prevents the bounded CLI from sending a
second ``messages.create`` for the same key:

* ``claim_in_progress`` — try to ``INSERT`` a fresh row in
  ``in_progress`` state through the unique database constraint. The
  function returns ``(row, already_claimed)``: ``False`` when the
  call successfully staged a new ``in_progress`` row and ``True``
  when the row already existed. The repository NEVER raises the
  unique-constraint violation as a technical error — the losing
  caller receives the existing row so the helper can branch on the
  durable state;
* ``transition_retryable_to_in_progress`` — atomically transition
  an existing ``retryable`` claim back to ``in_progress`` so the
  bounded CLI can perform a new ``messages.create`` call. The
  ``UPDATE`` carries a ``WHERE estado = 'retryable'`` predicate so
  only one concurrent caller wins; the loser's update affects zero
  rows. The bounded CLI keeps the same ``idempotency_key`` and never
  deletes the row, so the duplicate-send protection is preserved
  across retries;
* ``find`` — return the existing row when the helper needs to
  translate an external outcome back to the durable result;
* ``finalize`` — write the typed Twilio outcome (``sent`` /
  ``retryable`` / ``terminal``) on the already-claimed row so a
  second caller with the same key short-circuits to the documented
  durable state.

The durable state machine is the single source of truth that
prevents a second ``messages.create`` per key:

* ``in_progress`` — the bounded helper has staged the claim and
  has not yet seen a typed response. Two concurrent claims
  serialise through the unique index and the atomic transition
  below; the loser returns the durable state without calling
  T-C. After an ambiguous result (timeout, malformed body) the
  row stays ``in_progress`` so a subsequent retry short-circuits
  to the durable state without firing a second send;
* ``sent`` — the T-C adapter returned a SID. The claim is
  permanent; a second caller returns the SID without firing a
  second ``messages.create``;
* ``retryable`` — the T-C adapter or the bounded CLI drove a
  bounded retryable failure. The next dispatch atomically
  transitions the row back to ``in_progress`` before performing a
  new HTTP call. Two concurrent callers on the same ``retryable``
  row serialise through the ``WHERE estado = 'retryable'``
  predicate: only one wins and runs the new send; the other
  returns the durable state without calling T-C;
* ``terminal`` — the T-C adapter returned a 4xx-class terminal
  failure. The claim is permanent; a second caller returns the
  durable state without firing a second ``messages.create``.

The repository never commits, never flushes and never rolls back from
its own perspective: callers own the surrounding transaction so the
bounded CLI stays the single source of truth for the lease / commit /
rollback discipline used by the rest of the outbox.

The ``claim_in_progress`` implementation rolls back the session on the
unique-constraint violation. The helper guarantees the session is
fresh and carries no other pending mutations so the rollback is always
scoped to the failed ``INSERT``. The losing caller then receives the
existing row through the same return tuple.

The ``transition_retryable_to_in_progress`` implementation uses a
single ``UPDATE`` with a ``WHERE estado = 'retryable'`` predicate.
The database is the serialisation point; no process-local lock, no
in-memory dictionary and no second transaction is needed. The
function returns the number of rows updated so the helper can branch
on ``True`` (we won the transition) or ``False`` (the row was in
some other state during the update). The bounded CLI clears the
``message_sid``, ``codigo`` and ``http_status`` columns on the
transition so the in-progress row carries no stale typed outcome.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models.instalacion_twilio_comercio_idempotencia import (
    InstalacionTwilioComercioIdempotencia,
)


class InstalacionTwilioComercioIdempotenciaRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find(
        self, *, instalacion_id: str, idempotency_key: str
    ) -> InstalacionTwilioComercioIdempotencia | None:
        return self._session.execute(
            select(InstalacionTwilioComercioIdempotencia).where(
                InstalacionTwilioComercioIdempotencia.instalacion_id
                == str(instalacion_id),
                InstalacionTwilioComercioIdempotencia.idempotency_key
                == str(idempotency_key),
            )
        ).scalar_one_or_none()

    def claim_in_progress(
        self, *, instalacion_id: str, idempotency_key: str
    ) -> tuple[InstalacionTwilioComercioIdempotencia, bool]:
        """Try to claim the slot for the supplied key.

        Returns ``(row, already_claimed)``. ``already_claimed=True``
        means the row existed before the call — the unique constraint
        rejected the ``INSERT`` and the function recovered the durable
        state. ``False`` means the call successfully staged a new
        ``in_progress`` row.

        The repository relies on the database-level unique
        ``(instalacion_id, idempotency_key)`` constraint to refuse
        concurrent duplicates. The function does NOT raise the
        ``IntegrityError`` to the caller — losing callers must receive
        the existing row so the helper can branch on the typed
        outcome. The session is rolled back on the conflict so the
        losing caller never carries the rejected flush forward.
        """
        try:
            row = InstalacionTwilioComercioIdempotencia(
                instalacion_id=str(instalacion_id),
                idempotency_key=str(idempotency_key),
                estado="in_progress",
                message_sid=None,
                codigo=None,
                http_status=None,
            )
            self._session.add(row)
            self._session.flush()
            return row, False
        except IntegrityError:
            self._session.rollback()
            existing = self.find(
                instalacion_id=str(instalacion_id),
                idempotency_key=str(idempotency_key),
            )
            if existing is None:
                raise
            return existing, True

    def transition_retryable_to_in_progress(
        self, *, instalacion_id: str, idempotency_key: str
    ) -> bool:
        """Atomically transition ``retryable`` → ``in_progress``.

        Returns ``True`` when exactly one row was updated (the caller
        won the race and may perform a new ``messages.create`` call).
        Returns ``False`` when zero rows were updated (the row was in
        another state or another caller already won the transition).

        The ``UPDATE`` carries a ``WHERE estado = 'retryable'``
        predicate so the database is the serialisation point. No
        process-local lock, no in-memory dictionary and no second
        transaction is needed. The function clears the
        ``message_sid``, ``codigo`` and ``http_status`` columns so
        the in-progress row carries no stale typed outcome from the
        previous attempt.
        """
        result = self._session.execute(
            update(InstalacionTwilioComercioIdempotencia)
            .where(
                InstalacionTwilioComercioIdempotencia.instalacion_id
                == str(instalacion_id),
                InstalacionTwilioComercioIdempotencia.idempotency_key
                == str(idempotency_key),
                InstalacionTwilioComercioIdempotencia.estado
                == "retryable",
            )
            .values(
                estado="in_progress",
                message_sid=None,
                codigo=None,
                http_status=None,
            )
        )
        return bool(int(getattr(result, "rowcount", 0) or 0) == 1)

    def finalize(
        self,
        *,
        instalacion_id: str,
        idempotency_key: str,
        estado: str,
        message_sid: str | None,
        codigo: str | None,
        http_status: int | None,
    ) -> InstalacionTwilioComercioIdempotencia | None:
        """Write the typed outcome on the existing claim.

        The repository locates the claim by the unique pair and
        updates it in-place. The function returns the updated row
        so the bounded CLI can persist the SID on the outbox row
        in the same caller-owned transaction. A missing claim is
        treated as a no-op (returns ``None``) — the helper must
        claim before it can finalize.
        """
        row = self.find(
            instalacion_id=str(instalacion_id),
            idempotency_key=str(idempotency_key),
        )
        if row is None:
            return None
        row.estado = str(estado)
        row.message_sid = (
            str(message_sid) if message_sid is not None else None
        )
        row.codigo = str(codigo) if codigo is not None else None
        if http_status is None:
            row.http_status = None
        else:
            row.http_status = int(http_status)
        return row


__all__ = [
    "InstalacionTwilioComercioIdempotenciaRepository",
]