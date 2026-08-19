"""Phase 4B owner-self-service read-only readiness projection.

This module is the single non-mutating boundary that powers the
post-completion owner dashboard. It computes a typed
``OwnerOnboardingReadinessProjection`` from authoritative sources
only:

* the validated Supabase principal (validated immutable subject)
  resolves to its :class:`CuentaUsuario`;
* the account's :class:`BorradorOnboardingComercio` row, when
  terminal, exposes the exact :class:`Comercio` it created;
* an active ``OWNER`` :class:`ComercioUsuario` membership for
  the resolved account-commerce pair is the documented
  authorization gate;
* the canonical :class:`Comercio` row supplies the basic
  profile fields surfaced on the dashboard;
* :class:`CommerceAvailabilityService` reports the lifecycle
  evaluation (Phase 4B keeps the commerce in ``INACTIVO`` so
  this is expected to read ``UNAVAILABLE``);
* the existing
  :meth:`MediosPagoRepository.list_active_for_comercio` /
  :meth:`MetodoEntregaRepository.list_active_for_comercio`
  helpers enumerate the eligible active payment / delivery
  associations, joining both the commerce bridge ``activo``
  flag and the global catalog ``activo`` flag so a globally
  inactive catalog row cannot count as eligible;
* a dedicated channel is reported when an active
  :class:`CanalWhatsapp` references the exact ``comercio_id``
  through ``id_comercio_exclusivo``; a shared membership is
  reported when an active :class:`ComercioCanalCompartido`
  for the commerce points at an active shared
  :class:`CanalWhatsapp`. An absent or inactive channel is
  reported as pending; the resolver never infers readiness.

The service is read-only by construction:

* it never calls ``session.add``, ``session.flush``,
  ``session.commit`` or ``session.rollback``;
* it never calls
  :meth:`CommerceAvailabilityService.reserve_confirmed_order`
  so the trial counter can never be incremented;
* it never invokes the existing payment/delivery configuration
  service (the Admin mutation boundary) or any catalog /
  channel / trial mutation seam;
* it never accepts a ``comercio_id`` from the caller. The
  exact ``Comercio`` is derived from the validated principal
  and the account-owned terminal draft.

The service raises typed exceptions so the route can render
bounded feedback without leaking infrastructure details:

* :class:`OwnerReadinessAccountMissing` — the principal does
  not resolve to an active ``CuentaUsuario``;
* :class:`OwnerReadinessDraftMissing` — the account has no
  draft row to derive the commerce from;
* :class:`OwnerReadinessDraftNotTerminal` — the draft exists
  but the completion transaction has not yet staged the
  commerce, so the dashboard must NOT expose any commerce
  fact and the wizard must be used instead;
* :class:`OwnerReadinessMembershipMissing` — the terminal
  draft points at a comercio without an active ``OWNER``
  membership, or the membership belongs to another account;
* :class:`OwnerReadinessComercioMissing` — the terminal draft
  points at a ``comercio_id`` whose ``Comercio`` row has been
  removed (the documented fail-closed signal: never fall back
  to another commerce, draft or state).

The service does NOT catch ``SQLAlchemyError`` or any other
infrastructure error — the surrounding ``try/except`` in the
route is the only place where a generic ``503`` is rendered.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.auth.principal import AuthenticatedPrincipal
from backend.models import (
    BorradorOnboardingComercio,
    CanalWhatsapp,
    CanalWhatsappMode,
    Comercio,
    ComercioCanalCompartido,
    CuentaUsuario,
    EstadoComercio,
)
from backend.models.estado_comercio import EstadoComercioModoOperacion
from backend.repositories.comercio_usuario_repository import (
    ComercioUsuarioRepository,
)
from backend.repositories.medios_pago_repository import MediosPagoRepository
from backend.repositories.metodo_entrega_repository import (
    MetodoEntregaRepository,
)
from backend.services.commerce_availability_service import (
    CommerceAvailabilityOutcome,
    CommerceAvailabilityService,
    CommerceAvailabilityStatus,
)
from backend.services.owner_onboarding_service import OwnerOnboardingError


@dataclass(frozen=True)
class CommerceProfile:
    """Read-only basic commerce profile facts surfaced on the dashboard.

    The dataclass is intentionally narrow: only the canonical
    fields the dashboard needs to render the identity card.
    Fields are stripped of leading / trailing whitespace when
    possible; ``None`` is reserved for genuinely absent values.
    """

    comercio_id: int
    nombre_fantasia: str
    nombre_corto: str
    razon_social: str
    cuit: str
    slug: str
    whatsapp: str
    estado_codigo: str
    estado_modo_operacion: EstadoComercioModoOperacion | None
    fecha_alta: datetime
    fecha_ultima_modificacion: datetime


@dataclass(frozen=True)
class EligiblePaymentReadiness:
    """Derived payment readiness row.

    ``has_eligible_payment`` is ``True`` only when at least one
    :class:`ComercioMedioPago` row is active AND its referenced
    :class:`MediosPago` row is active. A globally inactive
    catalog row can NEVER produce a positive readiness signal.
    The helper counts how many rows qualified so the dashboard
    can render a meaningful next-action hint.
    """

    has_eligible_payment: bool
    eligible_count: int
    eligible_codigos: tuple[str, ...]


@dataclass(frozen=True)
class EligibleDeliveryReadiness:
    """Derived delivery readiness row.

    Mirror of :class:`EligiblePaymentReadiness` for the
    :class:`ComercioMetodoEntrega` / :class:`MetodosEntrega`
    pair.
    """

    has_eligible_delivery: bool
    eligible_count: int
    eligible_codigos: tuple[str, ...]


@dataclass(frozen=True)
class ChannelReadiness:
    """Derived channel readiness row.

    ``has_dedicated_channel`` reports an active dedicated
    :class:`CanalWhatsapp` for the exact ``comercio_id``.
    ``has_shared_membership`` reports an active shared
    membership for the commerce on an active shared channel.
    Both are populated independently so the dashboard can
    distinguish the two operational states.
    """

    has_dedicated_channel: bool
    has_shared_membership: bool
    dedicated_channel_id: int | None
    shared_membership_id: int | None


@dataclass(frozen=True)
class LifecycleReadiness:
    """Read-only lifecycle evaluation.

    Mirrors the typed outcome of
    :class:`CommerceAvailabilityService` but the dashboard
    does NOT mutate or rely on availability — a complete
    checklist never authorises ``PRUEBA`` or ``ACTIVO``.
    """

    status: CommerceAvailabilityStatus
    reason: Any
    modo_operacion: EstadoComercioModoOperacion | None
    prueba_hasta: datetime | None
    prueba_max_pedidos: int | None
    prueba_pedidos_consumidos: int


@dataclass(frozen=True)
class OwnerOnboardingReadinessProjection:
    """Typed projection returned by :func:`build_owner_readiness`.

    The dataclass is the single contract between the
    read-only service and the dashboard template. The router
    never inspects the underlying ORM rows once the projection
    is built so the template renders derived facts only.
    """

    cuenta_id: int
    draft_id: int
    profile: CommerceProfile
    lifecycle: LifecycleReadiness
    payments: EligiblePaymentReadiness
    deliveries: EligibleDeliveryReadiness
    channel: ChannelReadiness
    completed_at: datetime
    subject: str


@dataclass(frozen=True)
class PendingReadinessHint:
    """Bounded next-action hint for the dashboard.

    Each entry describes one ``pending`` requirement so the
    template can render plain language instead of raw state
    codes. The contract is intentionally closed: every
    rendered hint MUST map to a single boolean flag on the
    projection.
    """

    key: str
    message: str


class OwnerReadinessError(OwnerOnboardingError):
    """Base error raised by the Phase 4B readiness service."""


class OwnerReadinessAccountMissing(OwnerReadinessError):
    """Raised when the principal does not resolve to a CuentaUsuario.

    The dashboard must NOT fall back to another commerce or
    another draft: a missing account means the owner has
    never completed the onboarding transaction and there is
    no authoritative commerce to project. The router renders
    the bounded service-unavailable view in this case.
    """


class OwnerReadinessDraftMissing(OwnerReadinessError):
    """Raised when the account has no draft row at all."""


class OwnerReadinessDraftNotTerminal(OwnerReadinessError):
    """Raised when the account's draft is not yet terminal.

    The dashboard must NOT render commerce facts while the
    completion transaction is still pending. The router
    converts this signal into the bounded service-unavailable
    view so the owner falls back to the wizard.
    """


class OwnerReadinessMembershipMissing(OwnerReadinessError):
    """Raised when no active ``OWNER`` membership links the
    account to the terminal draft's commerce.

    The router treats this as a hard failure: the dashboard
    must NOT render commerce facts when the membership is
    missing or owned by a different account. The router
    refuses to fall back to another commerce or another
    draft, exactly like the Phase 4A terminal-inconsistency
    invariant.
    """


class OwnerReadinessComercioMissing(OwnerReadinessError):
    """Raised when the terminal draft points at a missing Comercio.

    The signal is the documented "never repair" invariant:
    a terminal draft whose commerce has been removed must NOT
    silently re-create the commerce, must NOT fall back to
    another commerce, and must NOT expose any projection fact
    on the dashboard.
    """


def _resolve_cuenta(
    session: Session, principal: AuthenticatedPrincipal
) -> CuentaUsuario:
    """Return the active ``CuentaUsuario`` for ``principal``.

    The helper is intentionally non-creating: the readiness
    service never inserts an account row, never commits and
    never falls back to another account / draft / commerce.
    A missing or inactive account is the documented
    fail-closed signal for the dashboard.
    """
    if not isinstance(principal, AuthenticatedPrincipal):
        raise TypeError("principal must be an AuthenticatedPrincipal")
    subject = principal.subject.strip()
    if not subject:
        raise OwnerReadinessAccountMissing(
            "validated principal must carry a non-empty subject"
        )
    stmt = select(CuentaUsuario).where(
        CuentaUsuario.supabase_subject == subject
    )
    cuenta = session.execute(stmt).scalar_one_or_none()
    if cuenta is None:
        raise OwnerReadinessAccountMissing(
            f"CuentaUsuario for subject {subject!r} does not exist"
        )
    if not bool(getattr(cuenta, "activo", False)):
        raise OwnerReadinessAccountMissing(
            f"CuentaUsuario {cuenta.id} is inactive"
        )
    return cuenta


def _resolve_terminal_draft(
    session: Session, cuenta: CuentaUsuario
) -> BorradorOnboardingComercio:
    """Return the account's terminal draft or raise a typed failure.

    A non-terminal draft is the documented "wizard not yet
    completed" signal: the dashboard has no authoritative
    commerce to project and the router must redirect the
    owner back to the wizard. The helper refuses to fall
    back to any other draft or any other account.
    """
    stmt = (
        select(BorradorOnboardingComercio)
        .where(
            BorradorOnboardingComercio.cuenta_usuario_id == int(cuenta.id)
        )
    )
    draft = session.execute(stmt).scalar_one_or_none()
    if draft is None:
        raise OwnerReadinessDraftMissing(
            f"CuentaUsuario {cuenta.id} has no onboarding draft"
        )
    if (
        draft.comercio_id is None
        or draft.completado_en is None
    ):
        raise OwnerReadinessDraftNotTerminal(
            f"draft {draft.id} is not terminal; "
            "the wizard must complete onboarding first"
        )
    return draft


def _resolve_comercio(
    session: Session, draft: BorradorOnboardingComercio
) -> tuple[Comercio, EstadoComercio]:
    """Return the canonical ``Comercio`` + ``EstadoComercio`` pair.

    The helper fails closed when the terminal draft points at
    a commerce that has been removed from the database: the
    dashboard must NEVER fall back to another commerce, must
    NEVER auto-repair the terminal draft, and must NEVER
    expose any projection fact.
    """
    comercio_id = int(draft.comercio_id) if draft.comercio_id is not None else 0
    comercio = session.get(Comercio, comercio_id)
    if comercio is None:
        raise OwnerReadinessComercioMissing(
            f"terminal draft {draft.id} points at the missing "
            f"comercio {comercio_id}"
        )
    estado = session.get(EstadoComercio, int(comercio.estado_id))
    if estado is None:
        # The comercio has lost its lifecycle row; this is a
        # configuration error and the dashboard refuses to
        # render anything rather than guess a default state.
        raise OwnerReadinessComercioMissing(
            f"comercio {comercio_id} has no EstadoComercio row"
        )
    return comercio, estado


def _verify_owner_membership(
    session: Session,
    *,
    cuenta_id: int,
    comercio_id: int,
) -> None:
    """Raise :class:`OwnerReadinessMembershipMissing` on a bad gate.

    The helper is the documented authorization boundary: a
    dashboard read MUST require an active ``OWNER`` membership
    for the exact account-commerce pair. A missing,
    inactive, or account-mismatched membership is the
    documented fail-closed signal.
    """
    membership = ComercioUsuarioRepository(
        session
    ).get_owner_membership(
        cuenta_usuario_id=cuenta_id,
        comercio_id=comercio_id,
    )
    if (
        membership is None
        or not bool(getattr(membership, "activo", False))
    ):
        raise OwnerReadinessMembershipMissing(
            f"no active OWNER membership for account "
            f"{cuenta_id} and comercio {comercio_id}"
        )


def _evaluate_lifecycle(
    session: Session, comercio_id: int
) -> LifecycleReadiness:
    """Return the typed availability evaluation.

    The helper delegates to
    :class:`CommerceAvailabilityService.evaluate` so the
    dashboard reads the same single source of truth as every
    other availability boundary. The helper never calls
    :meth:`CommerceAvailabilityService.reserve_confirmed_order`,
    so the trial counter can never be incremented from a
    dashboard GET.
    """
    outcome: CommerceAvailabilityOutcome = CommerceAvailabilityService(
        session
    ).evaluate(comercio_id)
    return LifecycleReadiness(
        status=outcome.status,
        reason=outcome.reason,
        modo_operacion=outcome.modo_operacion,
        prueba_hasta=outcome.prueba_hasta,
        prueba_max_pedidos=outcome.prueba_max_pedidos,
        prueba_pedidos_consumidos=int(outcome.prueba_pedidos_consumidos),
    )


def _evaluate_payments(
    session: Session, comercio_id: int
) -> EligiblePaymentReadiness:
    """Return the eligible-payment readiness row.

    An eligible payment is a :class:`ComercioMedioPago` row
    whose ``activo`` flag is ``True`` AND whose referenced
    :class:`MediosPago` row is also ``activo``. The existing
    :meth:`MediosPagoRepository.list_active_for_comercio`
    helper enforces both predicates in a single SQL join so
    the helper cannot silently accept a globally inactive
    catalog row.
    """
    medios = MediosPagoRepository(session).list_active_for_comercio(
        comercio_id
    )
    codigos = tuple(
        str(getattr(medio_pago, "codigo", "") or "")
        for medio_pago in medios
    )
    return EligiblePaymentReadiness(
        has_eligible_payment=bool(medios),
        eligible_count=len(medios),
        eligible_codigos=codigos,
    )


def _evaluate_deliveries(
    session: Session, comercio_id: int
) -> EligibleDeliveryReadiness:
    """Return the eligible-delivery readiness row.

    Mirror of :func:`_evaluate_payments` for the delivery
    bridge.
    """
    metodos = MetodoEntregaRepository(session).list_active_for_comercio(
        comercio_id
    )
    codigos = tuple(
        str(getattr(metodo_entrega, "codigo", "") or "")
        for metodo_entrega in metodos
    )
    return EligibleDeliveryReadiness(
        has_eligible_delivery=bool(metodos),
        eligible_count=len(metodos),
        eligible_codigos=codigos,
    )


def _evaluate_channel(
    session: Session, comercio_id: int
) -> ChannelReadiness:
    """Return the typed channel readiness row.

    The helper is the single source of truth for the
    dashboard's "channel ready" indicator:

    * an active dedicated :class:`CanalWhatsapp` with
      ``id_comercio_exclusivo == comercio_id`` reports
      ``has_dedicated_channel = True``;
    * an active :class:`ComercioCanalCompartido` whose
      ``comercio_id`` matches and whose owning
      :class:`CanalWhatsapp` is active and ``shared``
      reports ``has_shared_membership = True``;
    * absent / inactive rows report the corresponding
      ``False`` so the dashboard renders a ``pending`` hint.

    The helper never inserts, never deletes, never commits.
    """
    dedicated_stmt = select(CanalWhatsapp).where(
        CanalWhatsapp.id_comercio_exclusivo == comercio_id,
        CanalWhatsapp.activo.is_(True),
        CanalWhatsapp.mode == CanalWhatsappMode.DEDICATED,
    )
    dedicated = session.execute(dedicated_stmt).scalar_one_or_none()

    shared_stmt = select(ComercioCanalCompartido).where(
        ComercioCanalCompartido.comercio_id == comercio_id,
        ComercioCanalCompartido.activo.is_(True),
        CanalWhatsapp.id == ComercioCanalCompartido.canal_id,
        CanalWhatsapp.activo.is_(True),
        CanalWhatsapp.mode == CanalWhatsappMode.SHARED,
    )
    shared_membership = session.execute(shared_stmt).scalar_one_or_none()

    return ChannelReadiness(
        has_dedicated_channel=dedicated is not None,
        has_shared_membership=shared_membership is not None,
        dedicated_channel_id=(
            int(dedicated.id) if dedicated is not None else None
        ),
        shared_membership_id=(
            int(shared_membership.id)
            if shared_membership is not None
            else None
        ),
    )


def _build_profile(
    comercio: Comercio,
    estado: EstadoComercio,
) -> CommerceProfile:
    """Project the canonical commerce fields onto the dashboard."""
    modo_value = getattr(estado, "modo_operacion", None)
    modo_enum: EstadoComercioModoOperacion | None
    if modo_value is None:
        modo_enum = None
    else:
        try:
            modo_enum = EstadoComercioModoOperacion(modo_value)
        except ValueError:
            modo_enum = None
    return CommerceProfile(
        comercio_id=int(comercio.id),
        nombre_fantasia=str(comercio.nombre_fantasia or ""),
        nombre_corto=str(comercio.nombre_corto or ""),
        razon_social=str(comercio.razon_social or ""),
        cuit=str(comercio.cuit or ""),
        slug=str(comercio.slug or ""),
        whatsapp=str(comercio.whatsapp or ""),
        estado_codigo=str(estado.codigo or ""),
        estado_modo_operacion=modo_enum,
        fecha_alta=comercio.fecha_alta,
        fecha_ultima_modificacion=comercio.fecha_ultima_modificacion,
    )


def build_owner_readiness(
    session: Session,
    principal: AuthenticatedPrincipal,
) -> OwnerOnboardingReadinessProjection:
    """Return the typed projection for the dashboard.

    The helper is read-only: it never calls ``session.add``,
    ``flush``, ``commit`` or ``rollback``; it never calls
    :meth:`CommerceAvailabilityService.reserve_confirmed_order`
    and never accepts a ``comercio_id`` from the caller.
    The exact ``Comercio`` is derived from the validated
    Supabase principal through the ``CuentaUsuario`` /
    terminal draft / active ``OWNER`` membership chain.
    """
    if not isinstance(principal, AuthenticatedPrincipal):
        raise TypeError("principal must be an AuthenticatedPrincipal")

    cuenta = _resolve_cuenta(session, principal)
    draft = _resolve_terminal_draft(session, cuenta)
    comercio, estado = _resolve_comercio(session, draft)
    _verify_owner_membership(
        session,
        cuenta_id=int(cuenta.id),
        comercio_id=int(comercio.id),
    )

    profile = _build_profile(comercio, estado)
    lifecycle = _evaluate_lifecycle(session, int(comercio.id))
    payments = _evaluate_payments(session, int(comercio.id))
    deliveries = _evaluate_deliveries(session, int(comercio.id))
    channel = _evaluate_channel(session, int(comercio.id))

    return OwnerOnboardingReadinessProjection(
        cuenta_id=int(cuenta.id),
        draft_id=int(draft.id),
        profile=profile,
        lifecycle=lifecycle,
        payments=payments,
        deliveries=deliveries,
        channel=channel,
        completed_at=(
            draft.completado_en
            if draft.completado_en is not None
            else datetime.now(tz=timezone.utc)
        ),
        subject=principal.subject,
    )


__all__ = [
    "ChannelReadiness",
    "CommerceProfile",
    "EligibleDeliveryReadiness",
    "EligiblePaymentReadiness",
    "LifecycleReadiness",
    "OwnerOnboardingReadinessProjection",
    "OwnerReadinessAccountMissing",
    "OwnerReadinessComercioMissing",
    "OwnerReadinessDraftMissing",
    "OwnerReadinessDraftNotTerminal",
    "OwnerReadinessError",
    "OwnerReadinessMembershipMissing",
    "PendingReadinessHint",
    "build_owner_readiness",
]