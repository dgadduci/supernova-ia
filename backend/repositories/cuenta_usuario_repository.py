"""Persistence boundary for the ``CuentaUsuario`` row.

Phase 3 introduces the application-owned account identity that
resolves a Supabase magic-link subject into a durable internal
row. The repository is the single boundary that loads, creates
and re-activates those rows from a database session.

The repository only stages / flushes — it NEVER calls
``commit`` or ``rollback``. The caller (the owner-onboarding
service) owns the surrounding transaction so a wider operation
that touches the draft row can roll back together with the account
mutation when needed. The repository never opens its own session.

The repository contract is intentionally narrow:

* :func:`get_by_subject` — load the active account for an external
  Supabase subject. Returns ``None`` when no account exists so the
  service can decide whether to create one.
* :func:`create_active` — stage a new active account row for an
  external subject that has never been seen. The repository stamps
  the active flag and the audit timestamps; it never sets
  ``fecha_baja`` because the row is brand new.
* :func:`reactivate` — recover an account that was previously
  deactivated. The helper clears the ``fecha_baja`` column and
  flips ``activo`` back to ``True`` so the wizard can resume a
  previously abandoned onboarding. External identity remains
  immutable.
* :func:`deactivate` — soft-deactivate the account by setting
  ``fecha_baja`` and ``activo = False``. The repository never
  deletes an account; revocation is reversible by an operator
  through :func:`reactivate`.

The repository never stores email, provider metadata or any
profile mirror — the external subject is the only identity input.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.cuenta_usuario import CuentaUsuario


class CuentaUsuarioRepository:
    """Stage-only persistence boundary for :class:`CuentaUsuario`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_subject(self, supabase_subject: str) -> CuentaUsuario | None:
        """Return the account row for ``supabase_subject`` or ``None``.

        The helper loads the row irrespective of the ``activo`` flag
        so the caller can decide whether to reactivate, return the
        already-active row, or reject the request. The repository
        never filters on ``activo`` because the service is the only
        decision-maker for the resolution boundary.
        """
        if not isinstance(supabase_subject, str) or not supabase_subject.strip():
            raise ValueError("supabase_subject must be a non-empty string")
        cleaned_subject = supabase_subject.strip()
        stmt = select(CuentaUsuario).where(
            CuentaUsuario.supabase_subject == cleaned_subject
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def create_active(self, supabase_subject: str) -> CuentaUsuario:
        """Stage a brand-new active account for ``supabase_subject``.

        The helper does not call ``commit``; it stages the row and
        flushes so the resulting ``id`` and ``fecha_alta`` are
        deterministic for the rest of the unit-of-work. The caller
        owns the surrounding transaction.
        """
        if not isinstance(supabase_subject, str) or not supabase_subject.strip():
            raise ValueError("supabase_subject must be a non-empty string")
        cleaned_subject = supabase_subject.strip()
        cuenta = CuentaUsuario(
            supabase_subject=cleaned_subject,
            activo=True,
        )
        self._session.add(cuenta)
        self._session.flush()
        return cuenta

    def reactivate(self, cuenta: CuentaUsuario) -> None:
        """Clear ``fecha_baja`` and flip ``activo`` back to ``True``.

        The repository mutates the staged instance in place; the
        surrounding transaction decides whether to commit. The
        external subject is intentionally never rewritten so the
        identity contract stays immutable.
        """
        cuenta.activo = True
        cuenta.fecha_baja = None
        self._session.flush()

    def deactivate(self, cuenta: CuentaUsuario) -> None:
        """Soft-deactivate ``cuenta`` with a UTC ``fecha_baja`` stamp.

        The repository never deletes an account; the row is
        preserved so historical references and audit trails stay
        intact.
        """
        cuenta.activo = False
        cuenta.fecha_baja = datetime.now(timezone.utc)
        self._session.flush()


__all__ = ["CuentaUsuarioRepository"]
