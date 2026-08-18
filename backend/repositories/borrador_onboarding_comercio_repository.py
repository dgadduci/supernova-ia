"""Persistence boundary for ``BorradorOnboardingComercio``.

Phase 3 introduces the private, per-account draft that an
authenticated owner uses to stage the basic-commerce fields
required by the future Phase 4 completion transaction. The
repository is the single boundary that loads and mutates that
draft from a database session.

The repository only stages / flushes — it NEVER calls
``commit`` or ``rollback``. The caller (the owner-onboarding
service) owns the surrounding transaction so a save flow that
needs to roll back can also roll back the owning
``CuentaUsuario`` row in the same unit-of-work. The repository
never opens its own session.

The contract:

* :func:`get_for_account` — load the single draft for an account,
  returning ``None`` when none exists. The unique FK constraint
  guarantees there is at most one row, so the helper never returns
  more than a single instance.
* :func:`lock_for_account` — acquire a row-level
  ``SELECT ... FOR UPDATE`` lock on the same single draft so the
  completion transaction can serialise with concurrent save flows
  and guarantee the "exactly one commerce per draft" invariant
  documented in the Phase 4A OpenSpec change.
* :func:`create_for_account` — stage a brand-new draft row for an
  account that has never had a draft. The repository stamps
  ``version = 0`` and the audit timestamps; it never accepts a
  caller-provided ``version`` because the optimistic token must be
  monotonic and reproducible from the row itself.
* :func:`save_fields` — apply the basic-commerce fields with an
  atomic, DB-level optimistic-concurrency check. The helper issues
  a single SQL ``UPDATE`` whose ``WHERE`` clause matches both the
  primary key and ``expected_version``; the persistence step never
  reads the in-memory ``draft.version`` to decide whether to
  proceed. When the conditional update affects exactly one row the
  helper refreshes the in-memory instance so the caller sees the
  new version, the server-derived ``completo`` flag and the
  stamped ``fecha_ultima_modificacion``; when it affects zero rows
  the helper raises :class:`DraftConcurrencyError` and does not
  stage any in-memory change, so two sessions that pre-loaded the
  same version can never both confirm a write. The helper refuses
  to save on a terminal draft (one whose ``comercio_id`` /
  ``completado_en`` pair is set) so the OpenSpec Phase 4A "no
  editing of a terminal draft" invariant holds.
* :func:`mark_terminal` — record the terminal transition with an
  atomic, DB-level guard that the paired ``comercio_id`` /
  ``completado_en`` columns were both ``NULL`` when the UPDATE
  fired. The helper is the single stage step the completion
  transaction uses and never calls ``commit`` / ``rollback``.

The repository never touches ``comercios`` or
``comercio_usuarios`` other than to record the terminal
``comercio_id``; creating those rows is the completion
transaction's job, owned by the application caller.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from backend.models.borrador_onboarding_comercio import (
    BorradorOnboardingComercio,
)
from backend.models.cuenta_usuario import CuentaUsuario

REQUIRED_BASIC_FIELDS: tuple[str, ...] = (
    "nombre_fantasia",
    "nombre_corto",
    "razon_social",
    "cuit",
    "whatsapp",
    "calle",
    "numero",
    "localidad",
    "provincia",
    "slug",
)


class DraftConcurrencyError(Exception):
    """Raised when a save's optimistic-concurrency token mismatches.

    The owner router / service translates the signal to a
    re-render of the wizard with the latest persisted values and a
    short message asking the user to retry. The repository never
    stages the patch on a mismatch so no partial overwrite can
    land in the database.
    """


class DraftTerminalError(Exception):
    """Raised when a save is attempted on a terminal draft.

    A draft is terminal when its ``comercio_id`` /
    ``completado_en`` paired columns are set, i.e. the Phase 4A
    completion transaction has already produced the corresponding
    commerce and owner membership. The OpenSpec change forbids any
    further field mutation on a terminal draft; the wizard is
    expected to render the bounded completed view instead.
    """


def _clean_optional_string(value: object) -> str | None:
    """Return ``value`` stripped when non-empty, else ``None``.

    The helper centralises the trimming contract used by every
    basic-commerce field so an empty form input is stored as
    ``NULL`` rather than as an empty string. The wizard then
    derives progress from NULL vs non-empty values.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _is_completo_from_cleaned(cleaned: Mapping[str, object]) -> bool:
    """Return ``True`` iff every required basic field holds a value.

    The helper is computed from the already-cleaned values mapping
    rather than from the ORM instance so the ``completo`` flag can
    be derived before the conditional UPDATE is issued. Reading
    from the instance would couple the decision to the in-memory
    snapshot, which is precisely what the atomic save flow cannot
    rely on.
    """
    for name in REQUIRED_BASIC_FIELDS:
        value = cleaned.get(name)
        if not isinstance(value, str) or not value.strip():
            return False
    return True


class BorradorOnboardingComercioRepository:
    """Stage-only persistence boundary for the owner draft row."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_account(
        self, cuenta: CuentaUsuario
    ) -> BorradorOnboardingComercio | None:
        """Return the single draft row for ``cuenta`` or ``None``."""
        if cuenta is None:
            raise ValueError("cuenta must be a CuentaUsuario instance")
        if not isinstance(cuenta, CuentaUsuario):
            raise TypeError("cuenta must be a CuentaUsuario instance")
        stmt = select(BorradorOnboardingComercio).where(
            BorradorOnboardingComercio.cuenta_usuario_id == cuenta.id
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def lock_for_account(
        self, cuenta: CuentaUsuario
    ) -> BorradorOnboardingComercio | None:
        """Return the single draft row with a row-level lock.

        The helper is the Phase 4A completion transaction's
        concurrency seam: it issues ``SELECT ... FOR UPDATE`` so a
        parallel save / completion call against the same draft
        blocks until the holding transaction commits or rolls
        back. Returns ``None`` when no draft exists so the
        completion service can fail closed instead of mutating a
        stranger's draft.
        """
        if cuenta is None:
            raise ValueError("cuenta must be a CuentaUsuario instance")
        if not isinstance(cuenta, CuentaUsuario):
            raise TypeError("cuenta must be a CuentaUsuario instance")
        stmt = (
            select(BorradorOnboardingComercio)
            .where(
                BorradorOnboardingComercio.cuenta_usuario_id == cuenta.id
            )
            .with_for_update()
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def create_for_account(
        self, cuenta: CuentaUsuario
    ) -> BorradorOnboardingComercio:
        """Stage a brand-new empty draft for ``cuenta``.

        The helper enforces the unique-FK contract by checking that
        no draft exists for the account yet — it raises
        :class:`ValueError` so the service stays fail-closed on a
        programmer error rather than letting the database raise a
        constraint violation.
        """
        if not isinstance(cuenta, CuentaUsuario):
            raise TypeError("cuenta must be a CuentaUsuario instance")
        if self.get_for_account(cuenta) is not None:
            raise ValueError(
                "BorradorOnboardingComercio already exists for account "
                f"{cuenta.id}"
            )
        draft = BorradorOnboardingComercio(
            cuenta_usuario_id=cuenta.id,
            version=0,
            completo=False,
        )
        self._session.add(draft)
        self._session.flush()
        return draft

    def save_fields(
        self,
        draft: BorradorOnboardingComercio,
        *,
        expected_version: int,
        fields: Mapping[str, object],
    ) -> BorradorOnboardingComercio:
        """Apply ``fields`` with an atomic DB-level version check.

        The helper accepts a plain mapping of
        ``field_name -> value`` so the service can pass form
        payload verbatim. Unknown keys are ignored so a future
        column cannot accidentally widen the persisted surface
        without the helper noticing.

        The persistence is a single SQL ``UPDATE`` whose ``WHERE``
        clause matches the primary key, ``expected_version`` and
        the "not terminal" guard. The atomic conditional update is
        the only authority: the helper never reads
        ``draft.version`` from the in-memory snapshot to decide
        whether to proceed, so two sessions that pre-loaded the
        same version cannot both confirm a write. When the
        conditional update affects exactly one row the helper
        refreshes the in-memory instance so the caller sees the
        new version, the server-derived ``completo`` flag and the
        stamped ``fecha_ultima_modificacion``; when it affects zero
        rows the helper raises :class:`DraftConcurrencyError` and
        does not stage any in-memory change.

        The helper refuses to save on a terminal draft (whose
        ``comercio_id`` and ``completado_en`` paired columns are
        set) by raising :class:`DraftTerminalError`. The wizard is
        expected to detect the terminal state and render the
        bounded completed view.
        """
        if not isinstance(draft, BorradorOnboardingComercio):
            raise TypeError(
                "draft must be a BorradorOnboardingComercio instance"
            )
        if not isinstance(expected_version, int):
            raise TypeError("expected_version must be an int")
        if (
            draft.comercio_id is not None
            or draft.completado_en is not None
        ):
            raise DraftTerminalError(
                f"draft {draft.id} is terminal; further saves are "
                "rejected"
            )

        cleaned: dict[str, str | None] = {}
        for name in REQUIRED_BASIC_FIELDS + (
            "piso_departamento",
            "codigo_postal",
        ):
            cleaned[name] = _clean_optional_string(fields.get(name))

        new_completo = _is_completo_from_cleaned(cleaned)
        new_version = expected_version + 1

        stmt = (
            update(BorradorOnboardingComercio)
            .where(
                BorradorOnboardingComercio.id == draft.id,
                BorradorOnboardingComercio.version == expected_version,
                BorradorOnboardingComercio.comercio_id.is_(None),
                BorradorOnboardingComercio.completado_en.is_(None),
            )
            .values(
                **cleaned,
                version=new_version,
                completo=new_completo,
                fecha_ultima_modificacion=func.now(),
            )
            .execution_options(synchronize_session="fetch")
        )
        result = self._session.execute(stmt)
        if result.rowcount != 1:
            raise DraftConcurrencyError(
                f"expected_version={expected_version} "
                f"rowcount={result.rowcount}"
            )

        self._session.refresh(draft)
        return draft

    def mark_terminal(
        self,
        draft: BorradorOnboardingComercio,
        *,
        comercio_id: int,
        completado_en: datetime,
    ) -> BorradorOnboardingComercio:
        """Record the Phase 4A terminal transition atomically.

        The helper stages the ``comercio_id`` / ``completado_en``
        paired update with an explicit ``comercio_id IS NULL AND
        completado_en IS NULL`` guard so a concurrent completion
        request cannot land two terminal transitions on the same
        row. The helper raises :class:`DraftConcurrencyError`
        when the conditional update affects zero rows so the
        caller can fail closed without auto-repair.
        """
        if not isinstance(draft, BorradorOnboardingComercio):
            raise TypeError(
                "draft must be a BorradorOnboardingComercio instance"
            )
        if not isinstance(comercio_id, int) or isinstance(comercio_id, bool):
            raise TypeError("comercio_id must be a positive integer")
        if not isinstance(completado_en, datetime):
            raise TypeError("completado_en must be a datetime")

        stmt = (
            update(BorradorOnboardingComercio)
            .where(
                BorradorOnboardingComercio.id == draft.id,
                BorradorOnboardingComercio.comercio_id.is_(None),
                BorradorOnboardingComercio.completado_en.is_(None),
            )
            .values(
                comercio_id=comercio_id,
                completado_en=completado_en,
                fecha_ultima_modificacion=func.now(),
            )
            .execution_options(synchronize_session="fetch")
        )
        result = self._session.execute(stmt)
        if result.rowcount != 1:
            raise DraftConcurrencyError(
                f"terminal transition guard rowcount={result.rowcount}"
            )

        self._session.refresh(draft)
        return draft


__all__ = [
    "REQUIRED_BASIC_FIELDS",
    "BorradorOnboardingComercioRepository",
    "DraftConcurrencyError",
    "DraftTerminalError",
]
