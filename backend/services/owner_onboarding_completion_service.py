"""Phase 4A owner self-service onboarding completion service.

This module is the single boundary that consumes a private,
account-scoped :class:`BorradorOnboardingComercio` row and
atomically stages the matching ``Comercio``,
``ComercioUsuario`` and terminal draft transition in one
caller-owned transaction.

The service is intentionally narrow and deterministic:

* :func:`complete_onboarding` — the only entry point. It:
  1. resolves the authenticated :class:`CuentaUsuario` for the
     Phase 2 principal through a non-committing lookup (the
     router is responsible for invoking
     :func:`owner_onboarding_service.resolve_or_create_cuenta`
     *before* opening ``session.begin()`` so the completion
     transaction never observes a nested commit). The helper
     refuses to act on an inactive account and raises
     :class:`OwnerAccountInactive` for soft-deactivated rows;
  2. acquires a row-level ``SELECT ... FOR UPDATE`` lock on the
     single draft for that account so a concurrent save /
     completion request cannot land two terminal transitions;
  3. returns idempotently when the draft is already terminal
     (after verifying the OWNER membership is present and points
     back to the same account — a missing membership is the
     "terminal draft inconsistent" signal documented in the
     OpenSpec Phase 4A change);
  4. recomputes ``completo`` server-side from the persisted
     basic-field set (including ``slug``) — the completion
     transaction is the ultimate authority and refuses to
     rely solely on the derived ``draft.completo`` flag;
  5. delegates the commerce staging to the shared non-committing
     :meth:`backend.services.ComercioService.stage_create` seam
     so the commerce and its `OWNER` membership share the same
     validation surface as the Admin create flow. A flush-time
     ``IntegrityError`` (a duplicate slug / whatsapp race that
     escaped the pre-flight duplicate lookup) is translated to
     :class:`OwnerOnboardingUnicityRace` so the caller can
     roll back through the ``with session.begin():`` context
     manager and render a bounded service-unavailable view;
  6. stages the closed ``OWNER`` membership via the
     stage-only :class:`ComercioUsuarioRepository`;
  7. records the terminal ``comercio_id`` / ``completado_en``
     transition on the draft via the stage-only
     :meth:`BorradorOnboardingComercioRepository.mark_terminal`
     helper.

The helper never calls ``commit`` or ``rollback``. The caller
(the owner-onboarding router) owns the surrounding
``session.begin()`` unit-of-work so any staged row is rolled
back together on a persistence failure. The helper also refuses
to call :meth:`ComercioService.create`; the Admin-facing
commit-bound seam remains the single boundary for Admin-driven
``Comercio`` inserts.

The service does not touch payments, deliveries, channels,
catalogue, trials or any readiness surface.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.auth.principal import AuthenticatedPrincipal
from backend.models import EstadoComercio
from backend.models.borrador_onboarding_comercio import (
    BorradorOnboardingComercio,
)
from backend.models.comercio_usuario import ComercioUsuario
from backend.models.cuenta_usuario import CuentaUsuario
from backend.models.estado_comercio import EstadoComercioModoOperacion
from backend.repositories.borrador_onboarding_comercio_repository import (
    REQUIRED_BASIC_FIELDS,
    BorradorOnboardingComercioRepository,
    DraftConcurrencyError,
)
from backend.repositories.comercio_usuario_repository import (
    ComercioUsuarioRepository,
)
from backend.services.comercio_service import ComercioService
from backend.services.owner_onboarding_service import (
    OwnerAccountInactive,
    OwnerOnboardingError,
)

_INACTIVO_CODIGO = "INACTIVO"


@dataclass(frozen=True)
class CompletionOutcome:
    """Typed success signal returned by the completion service.

    The outcome is intentionally typed so the route can render
    the bounded completed view without reaching into the
    database session. The fields carry the exact identifiers
    the OpenSpec Phase 4A change requires the wizard to surface
    to the owner.

    * ``cuenta_id`` — the resolved application-owned account.
    * ``draft_id`` — the draft row that consumed the commerce.
    * ``comercio_id`` — the staged ``Comercio`` id (or the
      existing one for a retry on a terminal draft).
    * ``completado_en`` — the terminal ``completado_en``
      timestamp (or the existing one for a retry).
    """

    cuenta_id: int
    draft_id: int
    comercio_id: int
    completado_en: datetime


class OwnerOnboardingCompletionError(OwnerOnboardingError):
    """Base error raised by the Phase 4A completion service."""


class OwnerOnboardingNoDraft(OwnerOnboardingCompletionError):
    """Raised when the account has no draft row to complete.

    The completion service refuses to manufacture a draft on the
    fly; the wizard's create-or-load boundary is the only seam
    that ever inserts a :class:`BorradorOnboardingComercio`.
    """


class OwnerOnboardingIncomplete(OwnerOnboardingCompletionError):
    """Raised when the draft's server-derived ``completo`` is False.

    The completion service relies on the repository's server-side
    completeness derivation (which now includes ``slug``). A draft
    that fails the closed-set validation never reaches the
    commerce staging seam.
    """


class OwnerOnboardingTerminalInconsistent(
    OwnerOnboardingCompletionError
):
    """Raised when a terminal draft is missing or mismatched.

    The OpenSpec Phase 4A change requires the owner route to fail
    closed — never auto-repair or silently create a second
    commerce — when the terminal draft's ``comercio_id``
    references a ``Comercio`` whose OWNER membership is missing
    or does not match the account.
    """


class OwnerOnboardingInactivoMissing(OwnerOnboardingCompletionError):
    """Raised when the canonical ``INACTIVO`` lifecycle row is absent.

    Phase 4A stages commerces in ``INACTIVO`` exclusively. A
    misconfigured ``estado_comercio`` table is a hard configuration
    error and must surface as a typed failure rather than fall
    back to another state.
    """


class OwnerOnboardingUnicityRace(OwnerOnboardingCompletionError):
    """Raised when ``stage_create`` collides with an existing row.

    The helper translates a flush-time ``IntegrityError`` (a
    duplicate ``slug`` / ``whatsapp`` race that escaped the
    pre-flight duplicate lookup) into a typed completion error
    so the caller can roll the staged commerce, membership and
    terminal draft transition back through the ``with
    session.begin():`` context manager and return a bounded
    service-unavailable view instead of an unclassified 500.
    """


def _resolve_cuenta(
    session: Session, principal: AuthenticatedPrincipal
) -> CuentaUsuario:
    """Resolve the account row without committing.

    Stage-only seam: the helper performs a single non-committing
    ``SELECT`` against ``cuentas_usuario``. The router is
    responsible for calling
    :func:`owner_onboarding_service.resolve_or_create_cuenta`
    *before* opening the completion transaction so the legacy
    commit boundary is honoured and a brand-new ``CuentaUsuario``
    row reaches durable storage before the completion transaction
    starts. This helper therefore refuses to insert a fresh row
    and raises :class:`OwnerOnboardingError` when the account is
    missing — the documented fail-closed signal for an
    inconsistent onboarding state.
    """
    if not isinstance(principal, AuthenticatedPrincipal):
        raise TypeError("principal must be an AuthenticatedPrincipal")
    subject = principal.subject.strip()
    if not subject:
        raise OwnerOnboardingError(
            "validated principal must carry a non-empty subject"
        )
    stmt = select(CuentaUsuario).where(
        CuentaUsuario.supabase_subject == subject
    )
    cuenta = session.execute(stmt).scalar_one_or_none()
    if cuenta is None:
        raise OwnerOnboardingError(
            f"CuentaUsuario for subject {subject!r} must be "
            "resolved before opening the completion transaction"
        )
    if not cuenta.activo:
        raise OwnerAccountInactive(
            f"CuentaUsuario {cuenta.id} is inactive"
        )
    return cuenta


def _inactivo_estado_id(session: Session) -> int:
    """Return the canonical ``INACTIVO`` ``estado_comercio.id``.

    Phase 4A only ever stages commerces in the canonical
    ``INACTIVO`` state, and only when the row is configured
    for onboarding: the row must carry
    ``modo_operacion == BLOQUEADO`` and be marked
    ``seleccionable``. A missing row, an inactive
    ``modo_operacion`` value, or a non-selectable row is a hard
    configuration error surfaced as a typed exception; the helper
    never falls back to ``ACTIVO``, ``PRUEBA`` or any other
    state. The strict check is the documented "fail closed —
    do not silently repurpose another lifecycle row" invariant.
    """
    stmt = select(EstadoComercio).where(
        EstadoComercio.codigo == _INACTIVO_CODIGO
    )
    row = session.execute(stmt).scalar_one_or_none()
    if row is None:
        raise OwnerOnboardingInactivoMissing(
            f"estado_comercio row with codigo='{_INACTIVO_CODIGO}' "
            "is required for owner onboarding completion"
        )
    if not bool(getattr(row, "seleccionable", False)):
        raise OwnerOnboardingInactivoMissing(
            f"estado_comercio row with codigo='{_INACTIVO_CODIGO}' "
            "must be marked seleccionable for owner onboarding "
            "completion"
        )
    modo_value = getattr(row, "modo_operacion", None)
    if modo_value is None:
        raise OwnerOnboardingInactivoMissing(
            f"estado_comercio row with codigo='{_INACTIVO_CODIGO}' "
            "has no modo_operacion configured"
        )
    try:
        modo_enum = EstadoComercioModoOperacion(modo_value)
    except ValueError:
        raise OwnerOnboardingInactivoMissing(
            f"estado_comercio row with codigo='{_INACTIVO_CODIGO}' "
            f"has invalid modo_operacion {modo_value!r}"
        ) from None
    if modo_enum is not EstadoComercioModoOperacion.BLOQUEADO:
        raise OwnerOnboardingInactivoMissing(
            f"estado_comercio row with codigo='{_INACTIVO_CODIGO}' "
            f"must be configured with modo_operacion=BLOQUEADO "
            f"(got {modo_enum.value!r})"
        )
    return int(row.id)


def _commerce_payload_from_draft(
    draft: BorradorOnboardingComercio,
    *,
    estado_id: int,
) -> dict:
    """Project the closed draft field set into a staged create payload.

    The helper centralises the field-mapping between the
    private draft and the canonical ``Comercio`` row, mirroring
    :meth:`ComercioService._normalise_lifecycle_payload`'s
    required-key contract (``whatsapp``, ``slug`` included). The
    caller owns the surrounding unit-of-work.
    """
    payload: dict[str, object] = {
        "nombre_fantasia": draft.nombre_fantasia,
        "nombre_corto": draft.nombre_corto,
        "razon_social": draft.razon_social,
        "cuit": draft.cuit,
        "whatsapp": draft.whatsapp,
        "calle": draft.calle,
        "numero": draft.numero,
        "localidad": draft.localidad,
        "provincia": draft.provincia,
        "slug": draft.slug,
        "estado_id": estado_id,
        "zona_horaria": "America/Argentina/Buenos_Aires",
        "moneda": "ARS",
        "idioma": "es-AR",
    }
    if draft.piso_departamento:
        payload["piso_departamento"] = draft.piso_departamento
    if draft.codigo_postal:
        payload["codigo_postal"] = draft.codigo_postal
    return payload


def _verify_idempotent_terminal(
    *,
    cuenta_id: int,
    draft: BorradorOnboardingComercio,
    membership: ComercioUsuario | None,
) -> CompletionOutcome | None:
    """Return the idempotent outcome when the draft is already terminal.

    Returns ``None`` when the draft is not terminal so the caller
    can fall through to the staging path. Raises
    :class:`OwnerOnboardingTerminalInconsistent` when the
    terminal columns point at a commerce whose OWNER membership
    is missing, owned by a different account, or soft-revoked
    (``activo=False``). The "inactive membership is an
    inconsistency, not a success" rule is the documented
    "fail closed, never repair" invariant: the wizard must
    NEVER infer a successful completion from a membership that
    was revoked after the fact, otherwise the owner would see
    a bounded terminal view while the application considers
    the account authorised over a commerce it no longer owns.
    """
    if draft.comercio_id is None or draft.completado_en is None:
        return None
    if (
        membership is None
        or membership.cuenta_usuario_id != cuenta_id
        or not bool(getattr(membership, "activo", False))
    ):
        raise OwnerOnboardingTerminalInconsistent(
            f"draft {draft.id} is terminal but the OWNER membership "
            f"for comercio {draft.comercio_id} is missing, owned "
            f"by a different account, or inactive"
        )
    return CompletionOutcome(
        cuenta_id=cuenta_id,
        draft_id=draft.id,
        comercio_id=int(draft.comercio_id),
        completado_en=draft.completado_en,
    )


def complete_onboarding(
    session: Session,
    principal: AuthenticatedPrincipal,
) -> CompletionOutcome:
    """Atomically stage the completion transaction.

    The helper never calls ``commit`` or ``rollback``. The
    caller (the router) wraps the unit-of-work in a
    ``with session.begin():`` block so any staged commerce,
    membership or draft transition rolls back together on a
    persistence failure.

    The helper raises typed exceptions so the route can render
    bounded feedback without leaking infrastructure details:

    * :class:`OwnerAccountInactive` — account is deactivated.
    * :class:`OwnerOnboardingNoDraft` — account has no draft.
    * :class:`OwnerOnboardingIncomplete` — draft is incomplete
      or the ``slug`` is missing / blank.
    * :class:`OwnerOnboardingTerminalInconsistent` — terminal
      columns point at a stale commerce with no OWNER membership.
    * :class:`OwnerOnboardingInactivoMissing` — the canonical
      ``INACTIVO`` ``estado_comercio`` row is missing or
      misconfigured (wrong mode / not seleccionable).
    * :class:`OwnerOnboardingUnicityRace` — a flush-time
      ``IntegrityError`` fired inside ``stage_create`` so the
      caller must roll back through the ``with session.begin()``
      context manager and render a bounded service-unavailable
      view.
    * :class:`DuplicateSlug` / :class:`DuplicateWhatsapp` — the
      staged draft collides with an already-existing commerce.
    * :class:`DraftConcurrencyError` — the terminal guard
      detected a concurrent completion.
    """
    if not isinstance(principal, AuthenticatedPrincipal):
        raise TypeError("principal must be an AuthenticatedPrincipal")

    cuenta = _resolve_cuenta(session, principal)
    cuenta_id = int(cuenta.id)

    draft_repo = BorradorOnboardingComercioRepository(session)
    membership_repo = ComercioUsuarioRepository(session)

    draft = draft_repo.lock_for_account(cuenta)
    if draft is None:
        raise OwnerOnboardingNoDraft(
            f"CuentaUsuario {cuenta_id} has no onboarding draft"
        )

    if draft.comercio_id is not None or draft.completado_en is not None:
        existing_membership = membership_repo.get_owner_for_comercio(
            int(draft.comercio_id) if draft.comercio_id is not None else 0
        )
        idempotent = _verify_idempotent_terminal(
            cuenta_id=cuenta_id,
            draft=draft,
            membership=existing_membership,
        )
        if idempotent is not None:
            return idempotent
        # The pair is partial or inconsistent — fall through to
        # the consistency check below.

    # Recompute completeness from the persisted field set rather
    # than trusting ``draft.completo``: the flag is a derived
    # server-side value but the completion transaction is the
    # ultimate authority and must defend against any drift
    # between the flag and the actual columns.
    pending: list[str] = []
    for name in REQUIRED_BASIC_FIELDS:
        value = getattr(draft, name, None)
        if not isinstance(value, str) or not value.strip():
            pending.append(name)
    if pending:
        raise OwnerOnboardingIncomplete(
            f"draft {draft.id} is incomplete; pending fields: "
            + ", ".join(pending)
        )

    estado_id = _inactivo_estado_id(session)
    payload = _commerce_payload_from_draft(draft, estado_id=estado_id)

    try:
        comercio = ComercioService(session).stage_create(payload)
    except IntegrityError as exc:
        # The flush-time unique constraint (slug / whatsapp)
        # fired after the pre-flight duplicate lookup. The
        # surrounding ``with session.begin():`` context manager
        # rolls the staged commerce back; the helper re-raises
        # a typed completion error so the route can render a
        # bounded service-unavailable view instead of letting
        # the IntegrityError escape as a 500. The session is
        # discarded by the context manager's rollback.
        raise OwnerOnboardingUnicityRace(
            f"stage_create raised IntegrityError for draft "
            f"{draft.id}: {exc.orig}"
        ) from exc
    comercio_id = int(comercio.id)

    try:
        membership_repo.create_owner(
            cuenta_usuario_id=cuenta_id,
            comercio_id=comercio_id,
        )
    except IntegrityError as exc:
        # The flush-time unique constraint on the membership
        # (``UNIQUE (comercio_id, rol)`` guarantees a single
        # OWNER per commerce; ``UNIQUE (cuenta_usuario_id,
        # comercio_id)`` guarantees a single membership per
        # account-commerce pair) fired. The surrounding ``with
        # session.begin():`` context manager rolls the staged
        # commerce and the staged membership back together; the
        # helper re-raises a typed completion error so the
        # caller can render a bounded service-unavailable view
        # instead of letting the IntegrityError escape as a 500.
        raise OwnerOnboardingUnicityRace(
            f"create_owner raised IntegrityError for comercio "
            f"{comercio_id}: {exc.orig}"
        ) from exc

    completado_en = datetime.now(timezone.utc)
    try:
        draft_repo.mark_terminal(
            draft,
            comercio_id=comercio_id,
            completado_en=completado_en,
        )
    except DraftConcurrencyError as exc:
        raise OwnerOnboardingCompletionError(
            "another completion reached the terminal transition first"
        ) from exc

    return CompletionOutcome(
        cuenta_id=cuenta_id,
        draft_id=int(draft.id),
        comercio_id=comercio_id,
        completado_en=completado_en,
    )


def stage_payload_from_fields(
    fields: Mapping[str, object],
    *,
    estado_id: int,
) -> dict:
    """Expose the draft-to-commerce projection for tests / callers.

    Public helper so tests can assert the exact payload the
    service builds from a draft without bouncing through the
    ORM. Production code MUST go through
    :func:`complete_onboarding` so the lock, idempotency and
    transaction boundary are honoured.
    """
    if not isinstance(estado_id, int) or isinstance(estado_id, bool):
        raise TypeError("estado_id must be a positive integer")
    return dict(fields) | {"estado_id": estado_id}


__all__ = [
    "CompletionOutcome",
    "OwnerAccountInactive",
    "OwnerOnboardingCompletionError",
    "OwnerOnboardingInactivoMissing",
    "OwnerOnboardingIncomplete",
    "OwnerOnboardingNoDraft",
    "OwnerOnboardingTerminalInconsistent",
    "OwnerOnboardingUnicityRace",
    "complete_onboarding",
    "stage_payload_from_fields",
]
