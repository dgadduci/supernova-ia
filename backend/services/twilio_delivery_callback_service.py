"""Phase-5.6 Twilio delivery callback service.

The service is the only component in Phase 5.6 that maps a signed
Twilio status callback onto a monotonic outbox-row transition. It
performs three responsibilities:

1. ``apply_callback`` — locates the outbox row by
   ``(proveedor, identificador_proveedor)`` and applies the
   documented monotonic transition in a single narrow transaction.
2. The transition only advances forward from ``accepted`` to
   ``delivered`` or to ``failed_terminal``; any other state, or a
   regressive callback for an already-delivered row, is a no-op.
3. The service returns a typed ``OutboundCallbackResult`` so the
   router can observe each callback and focused tests can branch on
   a single attribute.

The service never imports HTTP, FastAPI, the Twilio SDK, the
coordinator, the resolver, the response orchestrator, the
dispatcher or the inbound webhook. It talks only to the outbox
repository.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session as SqlSession

from backend.models.mensaje_proveedor_saliente import (
    OutboundProviderMessageState,
)
from backend.repositories.mensaje_proveedor_saliente_repository import (
    MensajeProveedorSalienteRepository,
)
from backend.services.outbound_callback_types import (
    OutboundCallbackOutcome,
    OutboundCallbackResult,
)

_PROVIDER_TO_STATE: dict[str, str] = {
    "delivered": OutboundProviderMessageState.DELIVERED.value,
    "sent": OutboundProviderMessageState.DELIVERED.value,
    "failed": OutboundProviderMessageState.FAILED_TERMINAL.value,
    "undelivered": OutboundProviderMessageState.FAILED_TERMINAL.value,
}


class TwilioDeliveryCallbackService:
    """Single-owner Phase-5.6 callback service."""

    def __init__(
        self,
        session: SqlSession,
        *,
        outbox_repo: MensajeProveedorSalienteRepository | None = None,
        now: datetime | None = None,
    ) -> None:
        self._session = session
        self._outbox_repo = outbox_repo or MensajeProveedorSalienteRepository(
            session
        )
        self._now = now

    def _now_or(self) -> datetime:
        if self._now is not None:
            return self._now
        return datetime.now(tz=timezone.utc)

    def apply_callback(
        self,
        *,
        proveedor: str,
        identificador_proveedor: str,
        message_status: str,
    ) -> OutboundCallbackResult:
        """Apply one monotonic callback transition.

        Returns ``applied`` only when the supplied callback moves
        the row forward. ``duplicate`` covers a callback for a row
        already in the target state, ``regression`` covers a
        regressive callback for an already-terminal row, and
        ``unknown`` covers a callback for an unknown SID.

        Transaction ownership is explicit: the service opens and
        closes its own narrow transaction per call. The transition
        is committed only when the row was actually mutated;
        ``unknown``, ``duplicate`` and ``regression`` outcomes do
        not produce a commit because they do not mutate state. A
        technical failure inside the narrow transaction is rolled
        back and propagated so the caller (the router) can surface
        it as a 5xx.
        """
        target = _PROVIDER_TO_STATE.get(message_status)
        if target is None:
            return OutboundCallbackResult(
                outcome=OutboundCallbackOutcome.UNKNOWN,
                mensaje_id=None,
                estado_anterior=None,
                estado_nuevo=None,
            )

        try:
            row = self._outbox_repo.find_by_provider_sid(
                proveedor=proveedor,
                identificador_proveedor=identificador_proveedor,
            )
            if row is None:
                self._session.rollback()
                return OutboundCallbackResult(
                    outcome=OutboundCallbackOutcome.UNKNOWN,
                    mensaje_id=None,
                    estado_anterior=None,
                    estado_nuevo=None,
                )

            if target == OutboundProviderMessageState.DELIVERED.value:
                if row.estado == OutboundProviderMessageState.DELIVERED.value:
                    self._session.rollback()
                    return _duplicate(row.id, row.estado, target)
                if row.estado == OutboundProviderMessageState.FAILED_TERMINAL.value:
                    self._session.rollback()
                    return _regression(row.id, row.estado, target)
                applied = self._outbox_repo.record_provider_status(
                    mensaje_id=int(row.id),
                    estado_proveedor=message_status,
                    estado_proveedor_en=self._now_or(),
                    estado_final=target,
                )
                if not applied:
                    self._session.rollback()
                    return _duplicate(row.id, row.estado, target)
                self._session.commit()
                return _applied(row.id, row.estado, target)

            if target == OutboundProviderMessageState.FAILED_TERMINAL.value:
                if row.estado == OutboundProviderMessageState.FAILED_TERMINAL.value:
                    self._session.rollback()
                    return _duplicate(row.id, row.estado, target)
                if row.estado == OutboundProviderMessageState.DELIVERED.value:
                    self._session.rollback()
                    return _regression(row.id, row.estado, target)
                applied = self._outbox_repo.record_provider_status(
                    mensaje_id=int(row.id),
                    estado_proveedor=message_status,
                    estado_proveedor_en=self._now_or(),
                    estado_final=target,
                )
                if not applied:
                    self._session.rollback()
                    return _duplicate(row.id, row.estado, target)
                self._session.commit()
                return _applied(row.id, row.estado, target)

            self._session.rollback()
            return OutboundCallbackResult(
                outcome=OutboundCallbackOutcome.UNKNOWN,
                mensaje_id=int(row.id),
                estado_anterior=str(row.estado),
                estado_nuevo=None,
            )
        except Exception:
            self._session.rollback()
            raise


def _applied(
    outbox_id: int | None,
    estado_anterior: str | None,
    estado_nuevo: str,
) -> OutboundCallbackResult:
    return OutboundCallbackResult(
        outcome=OutboundCallbackOutcome.APPLIED,
        mensaje_id=outbox_id,
        estado_anterior=estado_anterior,
        estado_nuevo=estado_nuevo,
    )


def _duplicate(
    outbox_id: int | None,
    estado_anterior: str | None,
    estado_nuevo: str,
) -> OutboundCallbackResult:
    return OutboundCallbackResult(
        outcome=OutboundCallbackOutcome.DUPLICATE,
        mensaje_id=outbox_id,
        estado_anterior=estado_anterior,
        estado_nuevo=estado_nuevo,
    )


def _regression(
    outbox_id: int | None,
    estado_anterior: str | None,
    estado_nuevo: str,
) -> OutboundCallbackResult:
    return OutboundCallbackResult(
        outcome=OutboundCallbackOutcome.REGRESSION,
        mensaje_id=outbox_id,
        estado_anterior=estado_anterior,
        estado_nuevo=estado_nuevo,
    )


__all__ = ["TwilioDeliveryCallbackService"]