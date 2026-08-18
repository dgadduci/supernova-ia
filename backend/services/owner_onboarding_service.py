"""Business logic for the Phase 3 owner onboarding wizard.

The service is the single boundary that bridges the Phase 2
authenticated principal with the Phase 3 ``CuentaUsuario`` /
``BorradorOnboardingComercio`` persistence boundary.

The contract is intentionally narrow and deterministic:

* :func:`resolve_or_create_cuenta` — load or create the local
  account for the validated external subject, reactivating it
  when an operator previously soft-deactivated the row. The helper
  commits its own unit-of-work because the resolution boundary
  MUST reach durable storage before any draft work runs. The
  helper is intentionally separate from the draft flow so a draft
  save can roll back without rolling back the account insert.
* :func:`load_or_create_borrador` — load the single draft for an
  account, creating an empty one when none exists. The helper
  commits its own unit-of-work so a created draft survives
  across requests even if the next save fails.
* :func:`save_borrador` — apply a field patch with the
  optimistic-concurrency ``expected_version``. The helper commits
  on success and rolls back on a concurrency mismatch so the
  caller can re-read the latest persisted values.

The service uses the repositories' stage-only helpers, owns the
transaction, and never reaches into another service. It never
imports ``ComercioService``, ``CommerceAvailabilityService``,
``ComercioMedioPagoService`` or any lifecycle / payment /
catalogue / channel surface.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.auth.principal import AuthenticatedPrincipal
from backend.models.borrador_onboarding_comercio import (
    BorradorOnboardingComercio,
)
from backend.models.cuenta_usuario import CuentaUsuario
from backend.repositories.borrador_onboarding_comercio_repository import (
    BorradorOnboardingComercioRepository,
    DraftConcurrencyError,
)
from backend.repositories.cuenta_usuario_repository import (
    CuentaUsuarioRepository,
)


class OwnerOnboardingError(Exception):
    """Base error for the Phase 3 owner onboarding service."""


class OwnerAccountInactive(OwnerOnboardingError):
    """Raised when the resolved account is soft-deactivated.

    The service refuses to load or save a draft for an inactive
    account: an operator-driven revocation must be reversed
    through a separate admin surface, never through the wizard.
    """


def _subject_from_principal(
    principal: AuthenticatedPrincipal,
) -> str:
    """Return the cleaned external subject from ``principal``.

    The helper centralises the validation and stripping contract so
    every Phase 3 call site sees the same canonical external
    identifier. The principal's ``__post_init__`` already enforces
    the non-empty / stripped invariant, so the local re-check is a
    narrow defence in depth.
    """
    if not isinstance(principal, AuthenticatedPrincipal):
        raise TypeError("principal must be an AuthenticatedPrincipal")
    subject = principal.subject.strip()
    if not subject:
        raise OwnerOnboardingError(
            "validated principal must carry a non-empty subject"
        )
    return subject


def resolve_or_create_cuenta(
    session: Session, principal: AuthenticatedPrincipal
) -> CuentaUsuario:
    """Resolve the local account for ``principal`` (creating if missing).

    The helper enforces the documented Phase 3 contract:

    * The external subject is the only external input; no email,
      profile metadata or other Supabase claim is projected into
      the row.
    * When no row exists the helper stages a brand-new active
      account and commits the unit-of-work. The helper survives a
      concurrent insert (a parallel request creating the same
      subject) by reloading the row that won the race.
    * When the row exists but ``activo`` is ``False`` the helper
      raises :class:`OwnerAccountInactive`; reactivation is an
      operator-driven admin operation, never the wizard.
    * The helper never mutates ``supabase_subject`` on an existing
      row; the field stays immutable.
    """
    subject = _subject_from_principal(principal)
    repo = CuentaUsuarioRepository(session)

    cuenta = repo.get_by_subject(subject)
    if cuenta is None:
        try:
            cuenta = repo.create_active(subject)
            session.commit()
        except IntegrityError:
            session.rollback()
            cuenta = repo.get_by_subject(subject)
            if cuenta is None:
                raise
        else:
            cuenta = repo.get_by_subject(subject)
            if cuenta is None:
                raise OwnerOnboardingError(
                    "CuentaUsuario insert lost the race and cannot "
                    "be reloaded"
                )

    if cuenta is None:
        raise OwnerOnboardingError(
            "CuentaUsuario could not be resolved for the principal"
        )
    if not cuenta.activo:
        raise OwnerAccountInactive(
            f"CuentaUsuario {cuenta.id} is inactive"
        )
    return cuenta


def load_or_create_borrador(
    session: Session, cuenta: CuentaUsuario
) -> BorradorOnboardingComercio:
    """Return the single draft for ``cuenta`` (creating if missing).

    The helper commits after the initial create so the draft
    survives across requests; a later save never deletes the row.
    The helper refuses to act on an inactive account so a
    previously-deactivated account cannot silently resume.
    """
    if not isinstance(cuenta, CuentaUsuario):
        raise TypeError("cuenta must be a CuentaUsuario instance")
    if not cuenta.activo:
        raise OwnerAccountInactive(
            f"CuentaUsuario {cuenta.id} is inactive"
        )

    repo = BorradorOnboardingComercioRepository(session)
    draft = repo.get_for_account(cuenta)
    if draft is None:
        repo.create_for_account(cuenta)
        session.commit()
        draft = repo.get_for_account(cuenta)
        if draft is None:
            raise OwnerOnboardingError(
                "BorradorOnboardingComercio insert lost and cannot "
                "be reloaded"
            )
    return draft


def save_borrador(
    session: Session,
    draft: BorradorOnboardingComercio,
    *,
    expected_version: int,
    fields: Mapping[str, Any],
) -> BorradorOnboardingComercio:
    """Apply ``fields`` with the optimistic-concurrency version.

    The helper delegates the staging to the repository, then owns
    the commit. On :class:`DraftConcurrencyError` the helper rolls
    back the unit-of-work and re-raises so the caller can rebuild
    the form from the freshly loaded draft.
    """
    if not isinstance(draft, BorradorOnboardingComercio):
        raise TypeError(
            "draft must be a BorradorOnboardingComercio instance"
        )

    repo = BorradorOnboardingComercioRepository(session)
    try:
        saved = repo.save_fields(
            draft,
            expected_version=expected_version,
            fields=fields,
        )
    except DraftConcurrencyError:
        session.rollback()
        raise

    session.commit()
    session.refresh(saved)
    return saved


__all__ = [
    "BorradorOnboardingComercio",
    "BorradorOnboardingComercioRepository",
    "CuentaUsuario",
    "CuentaUsuarioRepository",
    "DraftConcurrencyError",
    "OwnerAccountInactive",
    "OwnerOnboardingError",
    "load_or_create_borrador",
    "resolve_or_create_cuenta",
    "save_borrador",
]
