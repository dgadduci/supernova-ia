"""Persistence boundary for ``ComercioUsuario``.

Phase 4A introduces the closed ``OWNER`` membership row the
owner-self-service completion transaction stages in the same
caller-owned unit-of-work as the ``Comercio`` and the terminal
``BorradorOnboardingComercio`` transition. The repository is the
single boundary that stages and reads those rows from a database
session.

The repository only stages / flushes — it NEVER calls
``commit`` or ``rollback``. The caller (the owner-onboarding
completion service) owns the surrounding transaction so the
commerce, the membership and the draft terminal transition can
all roll back together on any persistence failure. The
repository never opens its own session.

The repository contract is intentionally narrow:

* :func:`get_owner_for_comercio` — load the single ``OWNER``
  membership row for a ``comercio_id``. The helper is the only
  source of truth for the "is this terminal draft consistent?"
  audit; returning ``None`` for an ostensibly terminal draft is
  the canonical "fail closed — do not repair" signal called
  out by the Phase 4A OpenSpec change.
* :func:`get_owner_membership` — load the membership row for
  the exact ``CuentaUsuario``-``Comercio`` pair. The helper is
  the lookup the wizard / completion service uses when an
  authorised owner navigates the post-completion surface.
* :func:`create_owner` — stage the single ``OWNER`` membership
  row for a freshly created commerce. The helper stamps the
  audit timestamps and an active flag; it never accepts a
  caller-provided ``fecha_baja`` because the row is brand new.

The repository never deletes or soft-deactivates a membership:
``OWNER`` revocation is out of scope for the current
implementation.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.comercio_usuario import ComercioUsuario

_OWNER_ROL = "OWNER"


class ComercioUsuarioMembershipError(Exception):
    """Base error raised by the membership persistence boundary."""


class DuplicateComercioOwnerError(ComercioUsuarioMembershipError):
    """Raised when the helper would violate the unique ``OWNER`` invariant.

    The helper surfaces the typed signal so the completion service
    can roll the transaction back without surfacing an opaque
    ``IntegrityError``. The Phase 4A ``UNIQUE (comercio_id, rol)``
    index guarantees the database itself rejects the second insert;
    this exception exists so the service can distinguish the
    duplicate case from any other persistence failure.
    """


class ComercioUsuarioRepository:
    """Stage-only persistence boundary for :class:`ComercioUsuario`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_owner_for_comercio(
        self, comercio_id: int
    ) -> ComercioUsuario | None:
        """Return the single ``OWNER`` membership for ``comercio_id``.

        The helper enforces the closed ``OWNER`` set in the query
        itself so a future additional ``rol`` cannot silently
        broaden the lookup. Returns ``None`` when no row exists so
        the completion service can treat the missing row as the
        terminal-draft inconsistency documented in the Phase 4A
        OpenSpec change.
        """
        if (
            not isinstance(comercio_id, int)
            or isinstance(comercio_id, bool)
        ):
            raise TypeError("comercio_id must be a positive integer")
        stmt = select(ComercioUsuario).where(
            ComercioUsuario.comercio_id == comercio_id,
            ComercioUsuario.rol == _OWNER_ROL,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_owner_membership(
        self,
        *,
        cuenta_usuario_id: int,
        comercio_id: int,
    ) -> ComercioUsuario | None:
        """Return the membership row for the exact account-commerce pair."""
        if (
            not isinstance(cuenta_usuario_id, int)
            or isinstance(cuenta_usuario_id, bool)
        ):
            raise TypeError("cuenta_usuario_id must be a positive integer")
        if (
            not isinstance(comercio_id, int)
            or isinstance(comercio_id, bool)
        ):
            raise TypeError("comercio_id must be a positive integer")
        stmt = select(ComercioUsuario).where(
            ComercioUsuario.cuenta_usuario_id == cuenta_usuario_id,
            ComercioUsuario.comercio_id == comercio_id,
            ComercioUsuario.rol == _OWNER_ROL,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def create_owner(
        self,
        *,
        cuenta_usuario_id: int,
        comercio_id: int,
    ) -> ComercioUsuario:
        """Stage a single ``OWNER`` membership row.

        The helper refuses to write any other ``rol`` value so the
        closed ``OWNER`` set remains a property of the repository,
        not just the database check. The row is staged with the
        active flag and the audit timestamps; the caller owns the
        surrounding transaction.
        """
        if (
            not isinstance(cuenta_usuario_id, int)
            or isinstance(cuenta_usuario_id, bool)
        ):
            raise TypeError("cuenta_usuario_id must be a positive integer")
        if (
            not isinstance(comercio_id, int)
            or isinstance(comercio_id, bool)
        ):
            raise TypeError("comercio_id must be a positive integer")

        membership = ComercioUsuario(
            cuenta_usuario_id=cuenta_usuario_id,
            comercio_id=comercio_id,
            rol=_OWNER_ROL,
            activo=True,
        )
        self._session.add(membership)
        self._session.flush()
        return membership


__all__ = [
    "ComercioUsuarioMembershipError",
    "ComercioUsuarioRepository",
    "DuplicateComercioOwnerError",
]
