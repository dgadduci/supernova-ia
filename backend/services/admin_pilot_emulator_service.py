"""Admin/pilot Twilio emulator driver service.

The service is the only component that the admin/pilot route
invokes to submit a single bounded test message through the twilio
emulator. The service performs five bounded responsibilities:

1. validate the exact selected active Session, Pedido, Cliente,
   Comercio and dedicated channel identity;
2. validate the active T-C installation and the emulator-enabled
   configuration;
3. ask the emulator inbound control surface to deliver the inbound
   through the configured T-C webhook;
4. project the synthetic inbound identifier so the browser can poll
   for the existing provider receipt/outbox state;
5. emit the bounded safe observability event.

The service never calls the coordinator, worker, dispatcher or T-C
directly: the inbound control surface is the single entry point that
funnels the test message into the existing pipeline. The service
never commits, rolls back, flushes, refreshes, begins or closes the
session: the request-level dependency remains the transaction owner.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session as SqlSession

from backend.models import (
    CanalWhatsapp,
    CanalWhatsappMode,
    Cliente,
    EstadoPedido,
    EstadoSession,
    InstalacionTwilioComercio,
    Pedido,
)
from backend.models import (
    Session as SessionModel,
)
from backend.observability import (
    COMPONENT_ADMIN_PILOT_EMULATOR,
    COMPONENT_TWILIO_EMULATOR,
    EVENT_ADMIN_PILOT_EMULATOR_OUTCOME,
    EVENT_TWILIO_EMULATOR_OUTBOUND_OUTCOME,
    emit_event,
)
from backend.services.commerce_availability_service import (
    CommerceAvailabilityService,
    CommerceAvailabilityStatus,
)

logger = logging.getLogger(__name__)


class AdminPilotEmulatorError(Exception):
    """Bounded error raised by the admin/pilot emulator driver.

    The exception type is opaque to the route: the helper translates
    every branch into a generic bounded outcome so the operator
    cannot probe the failure class from the response payload.
    """


@dataclass(frozen=True)
class EmulatorTestTarget:
    """Bounded selection for the exact active pedido/session."""

    pedido_id: int
    session_id: int
    cliente_id: int
    comercio_id: int
    canal_id: int
    canal_destination_e164: str


@dataclass(frozen=True)
class EmulatorTestResult:
    """Bounded outcome of one emulator test submission."""

    synthetic_inbound_id: str
    target: EmulatorTestTarget


def load_active_emulator_target(
    db: SqlSession, pedido_id: int
) -> EmulatorTestTarget | None:
    """Return the exact active pedido/session for the emulator path.

    The loader mirrors the same identity contract as
    :func:`admin_pilot_orders._load_local_test_session` but accepts
    pedidos in any non-``BORRADOR`` state so the panel can drive a
    test message through the documented pipeline after the operator
    confirmed the order. It returns ``None`` for every shape the
    admin must reject without leaking which invariant failed.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    stmt = (
        select(Pedido)
        .where(Pedido.id == pedido_id)
        .options(
            joinedload(Pedido.session).joinedload(SessionModel.cliente),
            joinedload(Pedido.session).joinedload(SessionModel.comercio),
        )
    )
    pedido = db.execute(stmt).unique().scalar_one_or_none()
    if pedido is None:
        return None
    if pedido.estado_pedido == EstadoPedido.BORRADOR:
        return None
    session = getattr(pedido, "session", None)
    if session is None:
        return None
    if session.id_pedido != pedido.id:
        return None
    if session.estado_session != EstadoSession.ACTIVA:
        return None
    if session.id_comercio != pedido.session.comercio.id:
        return None
    if session.id_cliente != pedido.session.cliente.id:
        return None
    canal = _load_dedicated_canal(
        db=db, comercio_id=int(session.id_comercio)
    )
    if canal is None:
        return None
    return EmulatorTestTarget(
        pedido_id=int(pedido.id),
        session_id=int(session.id),
        cliente_id=int(session.id_cliente),
        comercio_id=int(session.id_comercio),
        canal_id=int(canal.id),
        canal_destination_e164=str(canal.destination_e164),
    )


def _load_dedicated_canal(
    *, db: SqlSession, comercio_id: int
) -> CanalWhatsapp | None:
    from sqlalchemy import select

    stmt = (
        select(CanalWhatsapp)
        .where(CanalWhatsapp.id_comercio_exclusivo == comercio_id)
        .where(CanalWhatsapp.activo.is_(True))
        .where(CanalWhatsapp.mode == CanalWhatsappMode.DEDICATED)
        .where(CanalWhatsapp.provider == "twilio")
    )
    return db.execute(stmt).unique().scalar_one_or_none()


def commerce_availability_status(
    db: SqlSession, *, comercio_id: int
) -> CommerceAvailabilityStatus:
    """Return the bounded commerce availability outcome for the test.

    The helper reuses the existing policy so the emulator path can
    never bypass the documented availability guard. The caller
    treats any non-``AVAILABLE`` value as a generic rejection.
    """
    if comercio_id <= 0:
        return CommerceAvailabilityStatus.UNAVAILABLE
    outcome = CommerceAvailabilityService(db).evaluate(comercio_id)
    return outcome.status


def load_active_installation(
    db: SqlSession, *, comercio_id: int
) -> InstalacionTwilioComercio | None:
    """Return the active T-C installation for the commerce, if any.

    The helper exists so the admin route can reject an emulator
    submission before the operator surfaces a misleading error.
    """
    from sqlalchemy import select

    stmt = select(InstalacionTwilioComercio).where(
        InstalacionTwilioComercio.id_comercio == comercio_id
    )
    rows = list(db.execute(stmt).unique().scalars())
    for row in rows:
        if bool(getattr(row, "activo", False)):
            return row
    return None


def resolve_cliente_e164(db: SqlSession, *, cliente_id: int) -> str | None:
    """Return the canonical E.164 for the exact selected cliente."""
    from sqlalchemy import select

    stmt = select(Cliente).where(Cliente.id == cliente_id)
    cliente = db.execute(stmt).unique().scalar_one_or_none()
    if cliente is None:
        return None
    whatsapp = getattr(cliente, "whatsapp", None)
    if not isinstance(whatsapp, str) or not whatsapp.strip():
        return None
    return _normalize_e164(whatsapp.strip())


def _normalize_e164(value: str) -> str | None:
    cleaned = value.strip()
    cleaned = cleaned.removeprefix("whatsapp:")
    if not cleaned.startswith("+"):
        return None
    digits = cleaned[1:]
    if not digits.isdigit() or not digits:
        return None
    if len(digits) > 15:
        return None
    return cleaned


def normalize_destination_e164(value: str) -> str | None:
    """Public helper for tests; same logic as :func:`_normalize_e164`."""
    return _normalize_e164(value)


def emit_admin_emulator_event(
    *,
    outcome: str,
    reason: str | None = None,
) -> None:
    """Emit the bounded admin emulator outcome event.

    The helper is the single sink for the admin emulator events. It
    never emits raw addresses, bodies, signatures, URLs, exception
    text, provider payloads or arbitrary operator input.
    """
    emit_event(
        event=EVENT_ADMIN_PILOT_EMULATOR_OUTCOME,
        component=COMPONENT_ADMIN_PILOT_EMULATOR,
        outcome=outcome,
        reason=reason,
    )


def emit_emulator_outbound_event(
    *,
    outcome: str,
    reason: str | None = None,
) -> None:
    """Emit the bounded emulator outbound outcome event."""
    emit_event(
        event=EVENT_TWILIO_EMULATOR_OUTBOUND_OUTCOME,
        component=COMPONENT_TWILIO_EMULATOR,
        outcome=outcome,
        reason=reason,
    )


__all__ = [
    "AdminPilotEmulatorError",
    "EmulatorTestResult",
    "EmulatorTestTarget",
    "commerce_availability_status",
    "emit_admin_emulator_event",
    "emit_emulator_outbound_event",
    "load_active_emulator_target",
    "load_active_installation",
    "normalize_destination_e164",
    "resolve_cliente_e164",
]