"""Phase-5.2 / 5.3 shared-channel routing service.

Phase 5.2 persisted the durable pre-commerce state of an existing
client activating a shared-channel membership. Phase 5.3 adds the
manual commerce-selection and explicit commerce-switching surface on
top of that durable state without invoking the business pipeline.

The service:

* validates the caller-supplied ``canal_id``, ``cliente_id`` and raw
  ``mensaje_original_pendiente`` (only the 5.2 ``activate`` entry
  point receives the original message);
* normalizes the routing-code envelope (5.2 only);
* resolves an exact active ``ComercioCanalCompartido`` membership of
  the supplied active shared channel;
* persists the selection only from that membership's commerce so
  commerce isolation is preserved;
* preserves ``mensaje_original_pendiente`` byte-for-byte on every
  outcome so a later phase can route it through the business pipeline;
* exposes manual-selection options as channel-scoped active memberships
  and accepts an active membership id (not an arbitrary commerce id)
  for the first selection;
* stages a pending switch target through explicit request, replace,
  confirm and cancel transitions; the existing selection is the only
  selection the rest of the system can observe until confirmation;
* never widens the candidate set, never invokes the local endpoint,
  classifier, recognizer, handler, catalog or session / order / client
  creation code, and never commits, rolls back, begins, flushes or
  closes. The caller owns the transaction and the eventual
  Phase-5.4 single-transaction orchestration.

Every business scenario collapses into one of the documented typed
outcomes. No outcome silently falls back to a different commerce, a
global client-only context or the existing local pipeline. The
service never raises a business-outcome signal; contract violations
(non-positive ids, non-string empty ``mensaje_original_pendiente``,
non-positive ``membership_id``) are the only cases that raise
:class:`InvalidSharedRoutingContext` (5.2) or
:class:`InvalidSharedChannelMembershipSelection` (5.3).
"""
from __future__ import annotations

import enum
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.models.canal_whatsapp import CanalWhatsappMode
from backend.models.contexto_cliente_canal_whatsapp import (
    ContextoClienteCanalWhatsapp,
)
from backend.repositories.canal_whatsapp_repository import (
    CanalWhatsappRepository,
)
from backend.repositories.comercio_canal_compartido_repository import (
    ComercioCanalCompartidoRepository,
)
from backend.repositories.contexto_cliente_canal_whatsapp_repository import (
    ContextoClienteCanalWhatsappRepository,
)
from backend.services.commerce_availability_service import (
    CommerceAvailabilityService,
    CommerceAvailabilityStatus,
)
from backend.services.exceptions import (
    InvalidSharedChannelMembershipSelection,
    InvalidSharedRoutingContext,
)


class ContextActivationStatus(str, enum.Enum):
    """Typed outcomes returned by ``SharedChannelRoutingService.activate``.

    Every value maps to a single non-resolved or resolved state. The
    service never raises a business-outcome signal; callers branch on
    ``outcome.status`` after a single ``activate`` call.
    """

    ACTIVATED = "activated"
    ALREADY_SELECTED = "already_selected"
    REQUIRES_EXPLICIT_SWITCH = "requires_explicit_switch"
    INVALID_ROUTING_CODE = "invalid_routing_code"
    UNKNOWN_OR_REVOKED_CODE = "unknown_or_revoked_code"
    INACTIVE_CHANNEL = "inactive_channel"
    UNAVAILABLE_COMMERCE = "unavailable_commerce"
    INVALID_CONTEXT = "invalid_context"


@enum.unique
class ManualSelectionStatus(str, enum.Enum):
    """Typed outcomes returned by Phase-5.3 service entry points.

    Every value maps to a single non-resolved or resolved state. The
    service never raises a business-outcome signal; callers branch on
    ``outcome.status`` after a single service call.
    """

    OPTIONS_AVAILABLE = "options_available"
    SELECTED = "selected"
    ALREADY_SELECTED = "already_selected"
    SWITCH_REQUESTED = "switch_requested"
    SWITCH_CONFIRMED = "switch_confirmed"
    SWITCH_CANCELLED = "switch_cancelled"
    NO_PENDING_SWITCH = "no_pending_switch"
    INVALID_CONTEXT = "invalid_context"
    INACTIVE_CHANNEL = "inactive_channel"
    INVALID_CHANNEL_MODE = "invalid_channel_mode"
    UNKNOWN_OR_INACTIVE_MEMBERSHIP = "unknown_or_inactive_membership"
    UNAVAILABLE_COMMERCE = "unavailable_commerce"


@dataclass(frozen=True)
class ManualSelectionOption:
    """Public projection of a manual-selection option.

    The caller selects by ``membership_id``; the commerce id is exposed
    only as informational metadata so the future webhook boundary can
    log the decision without exposing the commerce id as a selection
    authority.
    """

    membership_id: int
    comercio_id: int


@dataclass(frozen=True)
class ManualSelectionOutcome:
    """Immutable Phase-5.3 outcome.

    ``status`` is the single source of truth for branching. Every
    other field is only meaningful for the matching successful
    outcome; non-success outcomes leave id-bearing fields as ``None``
    (or echo the failed lookup ids).
    """

    status: ManualSelectionStatus
    canal_id: int
    cliente_id: int
    membership_id: int | None
    comercio_id_seleccionado: int | None
    comercio_id_cambio_pendiente: int | None
    mensaje_original_pendiente: str | None
    options: tuple[ManualSelectionOption, ...]
    resolution_source: str


@dataclass(frozen=True)
class ContextActivationOutcome:
    """Immutable activation outcome."""

    status: ContextActivationStatus
    canal_id: int
    cliente_id: int
    comercio_id: int | None
    routing_code_normalizado: str | None
    mensaje_original_pendiente: str | None
    resolution_source: str


def _validate_arguments(
    canal_id: object,
    cliente_id: object,
    mensaje_original_pendiente: object,
) -> tuple[int, int, str]:
    if not isinstance(canal_id, int) or isinstance(canal_id, bool) or canal_id <= 0:
        raise InvalidSharedRoutingContext(
            "canal_id must be a positive integer"
        )
    if (
        not isinstance(cliente_id, int)
        or isinstance(cliente_id, bool)
        or cliente_id <= 0
    ):
        raise InvalidSharedRoutingContext(
            "cliente_id must be a positive integer"
        )
    if not isinstance(mensaje_original_pendiente, str) or not mensaje_original_pendiente:
        raise InvalidSharedRoutingContext(
            "mensaje_original_pendiente must be a non-empty string"
        )
    return int(canal_id), int(cliente_id), mensaje_original_pendiente


def _validate_canal_cliente(
    canal_id: object,
    cliente_id: object,
) -> tuple[int, int]:
    if (
        not isinstance(canal_id, int)
        or isinstance(canal_id, bool)
        or canal_id <= 0
    ):
        raise InvalidSharedChannelMembershipSelection(
            "canal_id must be a positive integer"
        )
    if (
        not isinstance(cliente_id, int)
        or isinstance(cliente_id, bool)
        or cliente_id <= 0
    ):
        raise InvalidSharedChannelMembershipSelection(
            "cliente_id must be a positive integer"
        )
    return int(canal_id), int(cliente_id)


def _validate_membership_id(membership_id: object) -> int:
    if (
        not isinstance(membership_id, int)
        or isinstance(membership_id, bool)
        or membership_id <= 0
    ):
        raise InvalidSharedChannelMembershipSelection(
            "membership_id must be a positive integer"
        )
    return int(membership_id)


class SharedChannelRoutingService:
    """Phase-5.2 / 5.3 shared-channel routing service.

    The service holds a SQLAlchemy ``Session`` and three repositories
    (canal, shared membership, customer-channel context) and exposes
    Phase-5.2 ``activate`` and Phase-5.3 ``list_manual_options``,
    ``select_manual``, ``request_switch``, ``confirm_switch`` and
    ``cancel_switch``. It MUST NOT touch any pipeline component (no
    classifier / recognizer / handler / catalog / session / order /
    client creation call) and MUST NOT call ``commit``, ``rollback``,
    ``begin``, ``flush`` or ``close``.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._canal_repo = CanalWhatsappRepository(session)
        self._membresia_repo = ComercioCanalCompartidoRepository(session)
        self._contexto_repo = ContextoClienteCanalWhatsappRepository(session)

    @staticmethod
    def normalize_routing_code(raw: str) -> str:
        from backend.services.canal_whatsapp_service import normalize_routing_code

        return normalize_routing_code(raw)

    def activate(
        self,
        canal_id: int,
        cliente_id: int,
        routing_code: str,
        mensaje_original_pendiente: str,
    ) -> ContextActivationOutcome:
        canal_id, cliente_id, mensaje_original = _validate_arguments(
            canal_id, cliente_id, mensaje_original_pendiente
        )

        from backend.models import Cliente

        cliente = self._session.get(Cliente, cliente_id)
        if cliente is None or not cliente.activo:
            return ContextActivationOutcome(
                status=ContextActivationStatus.INVALID_CONTEXT,
                canal_id=canal_id,
                cliente_id=cliente_id,
                comercio_id=None,
                routing_code_normalizado=None,
                mensaje_original_pendiente=None,
                resolution_source="client_lookup",
            )

        from backend.services.exceptions import InvalidRoutingCode

        try:
            normalized = self.normalize_routing_code(routing_code)
        except InvalidRoutingCode:
            return ContextActivationOutcome(
                status=ContextActivationStatus.INVALID_ROUTING_CODE,
                canal_id=canal_id,
                cliente_id=cliente_id,
                comercio_id=None,
                routing_code_normalizado=None,
                mensaje_original_pendiente=None,
                resolution_source="routing_code_normalization",
            )

        canal = self._canal_repo.find_by_id(canal_id)
        if canal is None or not canal.activo:
            return ContextActivationOutcome(
                status=ContextActivationStatus.INACTIVE_CHANNEL,
                canal_id=canal_id,
                cliente_id=cliente_id,
                comercio_id=None,
                routing_code_normalizado=None,
                mensaje_original_pendiente=None,
                resolution_source="channel_lookup",
            )

        if canal.mode is not CanalWhatsappMode.SHARED:
            return ContextActivationOutcome(
                status=ContextActivationStatus.INVALID_CONTEXT,
                canal_id=canal_id,
                cliente_id=cliente_id,
                comercio_id=None,
                routing_code_normalizado=None,
                mensaje_original_pendiente=None,
                resolution_source="channel_mode",
            )

        membership = self._membresia_repo.find_active_by_canal_and_code(
            canal_id, normalized
        )
        if membership is None:
            return ContextActivationOutcome(
                status=ContextActivationStatus.UNKNOWN_OR_REVOKED_CODE,
                canal_id=canal_id,
                cliente_id=cliente_id,
                comercio_id=None,
                routing_code_normalizado=normalized,
                mensaje_original_pendiente=None,
                resolution_source="membership_lookup",
            )

        if not self._is_comercio_activo(int(membership.comercio_id)):
            return ContextActivationOutcome(
                status=ContextActivationStatus.UNAVAILABLE_COMMERCE,
                canal_id=canal_id,
                cliente_id=cliente_id,
                comercio_id=int(membership.comercio_id),
                routing_code_normalizado=normalized,
                mensaje_original_pendiente=None,
                resolution_source="membership_commerce",
            )

        existing = self._contexto_repo.find_by_canal_and_cliente(
            canal_id, cliente_id
        )
        if existing is not None and existing.comercio_id_seleccionado is not None:
            if int(existing.comercio_id_seleccionado) == int(membership.comercio_id):
                return ContextActivationOutcome(
                    status=ContextActivationStatus.ALREADY_SELECTED,
                    canal_id=canal_id,
                    cliente_id=cliente_id,
                    comercio_id=int(membership.comercio_id),
                    routing_code_normalizado=normalized,
                    mensaje_original_pendiente=existing.mensaje_original_pendiente,
                    resolution_source="same_membership_commerce",
                )
            return ContextActivationOutcome(
                status=ContextActivationStatus.REQUIRES_EXPLICIT_SWITCH,
                canal_id=canal_id,
                cliente_id=cliente_id,
                comercio_id=int(membership.comercio_id),
                routing_code_normalizado=normalized,
                mensaje_original_pendiente=existing.mensaje_original_pendiente,
                resolution_source="conflicting_membership_commerce",
            )

        self._contexto_repo.create(
            canal_id=canal_id,
            cliente_id=cliente_id,
            comercio_id_seleccionado=int(membership.comercio_id),
            mensaje_original_pendiente=mensaje_original,
        )

        return ContextActivationOutcome(
            status=ContextActivationStatus.ACTIVATED,
            canal_id=canal_id,
            cliente_id=cliente_id,
            comercio_id=int(membership.comercio_id),
            routing_code_normalizado=normalized,
            mensaje_original_pendiente=mensaje_original,
            resolution_source="first_activation",
        )

    def list_manual_options(
        self,
        canal_id: int,
        cliente_id: int,
    ) -> ManualSelectionOutcome:
        canal_id, cliente_id = _validate_canal_cliente(canal_id, cliente_id)

        pre = self._resolve_preconditions(
            canal_id, cliente_id, require_context=False
        )
        if pre is not None:
            return pre

        canal = self._canal_repo.find_by_id(canal_id)
        assert canal is not None
        if canal.mode is not CanalWhatsappMode.SHARED:
            existing = self._contexto_repo.find_by_canal_and_cliente(
                canal_id, cliente_id
            )
            return ManualSelectionOutcome(
                status=ManualSelectionStatus.INVALID_CHANNEL_MODE,
                canal_id=canal_id,
                cliente_id=cliente_id,
                membership_id=None,
                comercio_id_seleccionado=_safe_selected(existing),
                comercio_id_cambio_pendiente=_safe_pending(existing),
                mensaje_original_pendiente=_safe_message(existing),
                options=(),
                resolution_source="channel_mode",
            )

        memberships = self._membresia_repo.list_active_by_canal(canal_id)
        options: list[ManualSelectionOption] = []
        for membership in memberships:
            if not self._is_comercio_activo(int(membership.comercio_id)):
                continue
            options.append(
                ManualSelectionOption(
                    membership_id=int(membership.id),
                    comercio_id=int(membership.comercio_id),
                )
            )

        existing = self._contexto_repo.find_by_canal_and_cliente(
            canal_id, cliente_id
        )
        return ManualSelectionOutcome(
            status=ManualSelectionStatus.OPTIONS_AVAILABLE,
            canal_id=canal_id,
            cliente_id=cliente_id,
            membership_id=None,
            comercio_id_seleccionado=_safe_selected(existing),
            comercio_id_cambio_pendiente=_safe_pending(existing),
            mensaje_original_pendiente=_safe_message(existing),
            options=tuple(options),
            resolution_source="channel_scoped_active_memberships",
        )

    def select_manual(
        self,
        canal_id: int,
        cliente_id: int,
        membership_id: int,
    ) -> ManualSelectionOutcome:
        canal_id, cliente_id = _validate_canal_cliente(canal_id, cliente_id)
        membership_id = _validate_membership_id(membership_id)

        pre = self._resolve_preconditions(
            canal_id, cliente_id, require_context=True
        )
        if pre is not None:
            return _with_membership(pre, membership_id)

        canal = self._canal_repo.find_by_id(canal_id)
        assert canal is not None
        if canal.mode is not CanalWhatsappMode.SHARED:
            existing = self._contexto_repo.find_by_canal_and_cliente(
                canal_id, cliente_id
            )
            return ManualSelectionOutcome(
                status=ManualSelectionStatus.INVALID_CHANNEL_MODE,
                canal_id=canal_id,
                cliente_id=cliente_id,
                membership_id=membership_id,
                comercio_id_seleccionado=_safe_selected(existing),
                comercio_id_cambio_pendiente=_safe_pending(existing),
                mensaje_original_pendiente=_safe_message(existing),
                options=(),
                resolution_source="channel_mode",
            )

        membership = self._membresia_repo.find_active_by_canal_and_id(
            canal_id, membership_id
        )
        if membership is None:
            existing = self._contexto_repo.find_by_canal_and_cliente(
                canal_id, cliente_id
            )
            return ManualSelectionOutcome(
                status=ManualSelectionStatus.UNKNOWN_OR_INACTIVE_MEMBERSHIP,
                canal_id=canal_id,
                cliente_id=cliente_id,
                membership_id=membership_id,
                comercio_id_seleccionado=_safe_selected(existing),
                comercio_id_cambio_pendiente=_safe_pending(existing),
                mensaje_original_pendiente=_safe_message(existing),
                options=(),
                resolution_source="membership_lookup",
            )

        if not self._is_comercio_activo(int(membership.comercio_id)):
            existing = self._contexto_repo.find_by_canal_and_cliente(
                canal_id, cliente_id
            )
            return ManualSelectionOutcome(
                status=ManualSelectionStatus.UNAVAILABLE_COMMERCE,
                canal_id=canal_id,
                cliente_id=cliente_id,
                membership_id=membership_id,
                comercio_id_seleccionado=_safe_selected(existing),
                comercio_id_cambio_pendiente=_safe_pending(existing),
                mensaje_original_pendiente=_safe_message(existing),
                options=(),
                resolution_source="membership_commerce",
            )

        existing = self._contexto_repo.find_by_canal_and_cliente(
            canal_id, cliente_id
        )
        assert existing is not None

        if existing.comercio_id_seleccionado is not None:
            if int(existing.comercio_id_seleccionado) == int(
                membership.comercio_id
            ):
                return ManualSelectionOutcome(
                    status=ManualSelectionStatus.ALREADY_SELECTED,
                    canal_id=canal_id,
                    cliente_id=cliente_id,
                    membership_id=membership_id,
                    comercio_id_seleccionado=int(
                        existing.comercio_id_seleccionado
                    ),
                    comercio_id_cambio_pendiente=_safe_pending(existing),
                    mensaje_original_pendiente=existing.mensaje_original_pendiente,
                    options=(),
                    resolution_source="same_selection_idempotent",
                )
            return ManualSelectionOutcome(
                status=ManualSelectionStatus.UNKNOWN_OR_INACTIVE_MEMBERSHIP,
                canal_id=canal_id,
                cliente_id=cliente_id,
                membership_id=membership_id,
                comercio_id_seleccionado=int(
                    existing.comercio_id_seleccionado
                ),
                comercio_id_cambio_pendiente=_safe_pending(existing),
                mensaje_original_pendiente=existing.mensaje_original_pendiente,
                options=(),
                resolution_source="requires_explicit_switch",
            )

        target_comercio_id = int(membership.comercio_id)
        self._contexto_repo.set_selected_comercio(
            existing, target_comercio_id
        )
        self._contexto_repo.clear_pending_target(existing)
        return ManualSelectionOutcome(
            status=ManualSelectionStatus.SELECTED,
            canal_id=canal_id,
            cliente_id=cliente_id,
            membership_id=membership_id,
            comercio_id_seleccionado=target_comercio_id,
            comercio_id_cambio_pendiente=None,
            mensaje_original_pendiente=existing.mensaje_original_pendiente,
            options=(),
            resolution_source="first_manual_selection",
        )

    def request_switch(
        self,
        canal_id: int,
        cliente_id: int,
        membership_id: int,
    ) -> ManualSelectionOutcome:
        canal_id, cliente_id = _validate_canal_cliente(canal_id, cliente_id)
        membership_id = _validate_membership_id(membership_id)

        pre = self._resolve_preconditions(
            canal_id, cliente_id, require_context=True
        )
        if pre is not None:
            return _with_membership(pre, membership_id)

        canal = self._canal_repo.find_by_id(canal_id)
        assert canal is not None
        if canal.mode is not CanalWhatsappMode.SHARED:
            existing = self._contexto_repo.find_by_canal_and_cliente(
                canal_id, cliente_id
            )
            return ManualSelectionOutcome(
                status=ManualSelectionStatus.INVALID_CHANNEL_MODE,
                canal_id=canal_id,
                cliente_id=cliente_id,
                membership_id=membership_id,
                comercio_id_seleccionado=_safe_selected(existing),
                comercio_id_cambio_pendiente=_safe_pending(existing),
                mensaje_original_pendiente=_safe_message(existing),
                options=(),
                resolution_source="channel_mode",
            )

        membership = self._membresia_repo.find_active_by_canal_and_id(
            canal_id, membership_id
        )
        if membership is None:
            existing = self._contexto_repo.find_by_canal_and_cliente(
                canal_id, cliente_id
            )
            return ManualSelectionOutcome(
                status=ManualSelectionStatus.UNKNOWN_OR_INACTIVE_MEMBERSHIP,
                canal_id=canal_id,
                cliente_id=cliente_id,
                membership_id=membership_id,
                comercio_id_seleccionado=_safe_selected(existing),
                comercio_id_cambio_pendiente=_safe_pending(existing),
                mensaje_original_pendiente=_safe_message(existing),
                options=(),
                resolution_source="membership_lookup",
            )

        existing = self._contexto_repo.find_by_canal_and_cliente(
            canal_id, cliente_id
        )
        assert existing is not None

        if existing.comercio_id_seleccionado is None:
            return ManualSelectionOutcome(
                status=ManualSelectionStatus.INVALID_CONTEXT,
                canal_id=canal_id,
                cliente_id=cliente_id,
                membership_id=membership_id,
                comercio_id_seleccionado=None,
                comercio_id_cambio_pendiente=_safe_pending(existing),
                mensaje_original_pendiente=existing.mensaje_original_pendiente,
                options=(),
                resolution_source="no_selection_to_switch",
            )

        if not self._is_comercio_activo(int(membership.comercio_id)):
            return ManualSelectionOutcome(
                status=ManualSelectionStatus.UNAVAILABLE_COMMERCE,
                canal_id=canal_id,
                cliente_id=cliente_id,
                membership_id=membership_id,
                comercio_id_seleccionado=int(existing.comercio_id_seleccionado),
                comercio_id_cambio_pendiente=_safe_pending(existing),
                mensaje_original_pendiente=existing.mensaje_original_pendiente,
                options=(),
                resolution_source="membership_commerce",
            )

        selected_comercio = int(existing.comercio_id_seleccionado)
        target_comercio = int(membership.comercio_id)
        if target_comercio == selected_comercio:
            return ManualSelectionOutcome(
                status=ManualSelectionStatus.SWITCH_REQUESTED,
                canal_id=canal_id,
                cliente_id=cliente_id,
                membership_id=membership_id,
                comercio_id_seleccionado=selected_comercio,
                comercio_id_cambio_pendiente=_safe_pending(existing),
                mensaje_original_pendiente=existing.mensaje_original_pendiente,
                options=(),
                resolution_source="same_commerce_no_pending_switch",
            )

        self._contexto_repo.stage_pending_target(existing, target_comercio)
        staged_pending = existing.comercio_id_cambio_pendiente
        if staged_pending is None:
            staged_pending = target_comercio
        return ManualSelectionOutcome(
            status=ManualSelectionStatus.SWITCH_REQUESTED,
            canal_id=canal_id,
            cliente_id=cliente_id,
            membership_id=membership_id,
            comercio_id_seleccionado=selected_comercio,
            comercio_id_cambio_pendiente=int(staged_pending),
            mensaje_original_pendiente=existing.mensaje_original_pendiente,
            options=(),
            resolution_source="switch_target_staged",
        )

    def confirm_switch(
        self,
        canal_id: int,
        cliente_id: int,
    ) -> ManualSelectionOutcome:
        canal_id, cliente_id = _validate_canal_cliente(canal_id, cliente_id)

        pre = self._resolve_preconditions(
            canal_id, cliente_id, require_context=True
        )
        if pre is not None:
            return pre

        canal = self._canal_repo.find_by_id(canal_id)
        assert canal is not None
        if canal.mode is not CanalWhatsappMode.SHARED:
            existing = self._contexto_repo.find_by_canal_and_cliente(
                canal_id, cliente_id
            )
            return ManualSelectionOutcome(
                status=ManualSelectionStatus.INVALID_CHANNEL_MODE,
                canal_id=canal_id,
                cliente_id=cliente_id,
                membership_id=None,
                comercio_id_seleccionado=_safe_selected(existing),
                comercio_id_cambio_pendiente=_safe_pending(existing),
                mensaje_original_pendiente=_safe_message(existing),
                options=(),
                resolution_source="channel_mode",
            )

        existing = self._contexto_repo.find_by_canal_and_cliente(
            canal_id, cliente_id
        )
        assert existing is not None

        if existing.comercio_id_cambio_pendiente is None:
            return ManualSelectionOutcome(
                status=ManualSelectionStatus.NO_PENDING_SWITCH,
                canal_id=canal_id,
                cliente_id=cliente_id,
                membership_id=None,
                comercio_id_seleccionado=_safe_selected(existing),
                comercio_id_cambio_pendiente=None,
                mensaje_original_pendiente=existing.mensaje_original_pendiente,
                options=(),
                resolution_source="no_pending_target",
            )

        pending_target = int(existing.comercio_id_cambio_pendiente)
        membership = self._membresia_repo.find_active_by_canal_and_comercio(
            canal_id, pending_target
        )
        if membership is None or not self._is_comercio_activo(
            int(membership.comercio_id)
        ):
            return ManualSelectionOutcome(
                status=ManualSelectionStatus.UNKNOWN_OR_INACTIVE_MEMBERSHIP,
                canal_id=canal_id,
                cliente_id=cliente_id,
                membership_id=None,
                comercio_id_seleccionado=_safe_selected(existing),
                comercio_id_cambio_pendiente=pending_target,
                mensaje_original_pendiente=existing.mensaje_original_pendiente,
                options=(),
                resolution_source="stale_pending_target",
            )

        self._contexto_repo.commit_pending_target_to_selection(existing)
        committed_comercio_id = existing.comercio_id_seleccionado
        if committed_comercio_id is None:
            committed_comercio_id = pending_target
        return ManualSelectionOutcome(
            status=ManualSelectionStatus.SWITCH_CONFIRMED,
            canal_id=canal_id,
            cliente_id=cliente_id,
            membership_id=int(membership.id),
            comercio_id_seleccionado=int(committed_comercio_id),
            comercio_id_cambio_pendiente=None,
            mensaje_original_pendiente=existing.mensaje_original_pendiente,
            options=(),
            resolution_source="pending_target_committed",
        )

    def cancel_switch(
        self,
        canal_id: int,
        cliente_id: int,
    ) -> ManualSelectionOutcome:
        canal_id, cliente_id = _validate_canal_cliente(canal_id, cliente_id)

        pre = self._resolve_preconditions(
            canal_id, cliente_id, require_context=True
        )
        if pre is not None:
            return pre

        canal = self._canal_repo.find_by_id(canal_id)
        assert canal is not None
        if canal.mode is not CanalWhatsappMode.SHARED:
            existing = self._contexto_repo.find_by_canal_and_cliente(
                canal_id, cliente_id
            )
            return ManualSelectionOutcome(
                status=ManualSelectionStatus.INVALID_CHANNEL_MODE,
                canal_id=canal_id,
                cliente_id=cliente_id,
                membership_id=None,
                comercio_id_seleccionado=_safe_selected(existing),
                comercio_id_cambio_pendiente=_safe_pending(existing),
                mensaje_original_pendiente=_safe_message(existing),
                options=(),
                resolution_source="channel_mode",
            )

        existing = self._contexto_repo.find_by_canal_and_cliente(
            canal_id, cliente_id
        )
        assert existing is not None

        if existing.comercio_id_cambio_pendiente is None:
            return ManualSelectionOutcome(
                status=ManualSelectionStatus.NO_PENDING_SWITCH,
                canal_id=canal_id,
                cliente_id=cliente_id,
                membership_id=None,
                comercio_id_seleccionado=_safe_selected(existing),
                comercio_id_cambio_pendiente=None,
                mensaje_original_pendiente=existing.mensaje_original_pendiente,
                options=(),
                resolution_source="no_pending_target",
            )

        self._contexto_repo.clear_pending_target(existing)
        return ManualSelectionOutcome(
            status=ManualSelectionStatus.SWITCH_CANCELLED,
            canal_id=canal_id,
            cliente_id=cliente_id,
            membership_id=None,
            comercio_id_seleccionado=_safe_selected(existing),
            comercio_id_cambio_pendiente=None,
            mensaje_original_pendiente=existing.mensaje_original_pendiente,
            options=(),
            resolution_source="pending_target_cleared",
        )

    def _is_comercio_activo(self, comercio_id: int) -> bool:
        outcome = CommerceAvailabilityService(
            self._session
        ).evaluate(comercio_id)
        return outcome.status is CommerceAvailabilityStatus.AVAILABLE

    def _resolve_preconditions(
        self,
        canal_id: int,
        cliente_id: int,
        require_context: bool,
    ) -> ManualSelectionOutcome | None:
        from backend.models import Cliente

        cliente = self._session.get(Cliente, cliente_id)
        if cliente is None or not cliente.activo:
            return ManualSelectionOutcome(
                status=ManualSelectionStatus.INVALID_CONTEXT,
                canal_id=canal_id,
                cliente_id=cliente_id,
                membership_id=None,
                comercio_id_seleccionado=None,
                comercio_id_cambio_pendiente=None,
                mensaje_original_pendiente=None,
                options=(),
                resolution_source="client_lookup",
            )

        canal = self._canal_repo.find_by_id(canal_id)
        if canal is None or not canal.activo:
            return ManualSelectionOutcome(
                status=ManualSelectionStatus.INACTIVE_CHANNEL,
                canal_id=canal_id,
                cliente_id=cliente_id,
                membership_id=None,
                comercio_id_seleccionado=None,
                comercio_id_cambio_pendiente=None,
                mensaje_original_pendiente=None,
                options=(),
                resolution_source="channel_lookup",
            )

        existing = self._contexto_repo.find_by_canal_and_cliente(
            canal_id, cliente_id
        )
        if require_context and existing is None:
            return ManualSelectionOutcome(
                status=ManualSelectionStatus.INVALID_CONTEXT,
                canal_id=canal_id,
                cliente_id=cliente_id,
                membership_id=None,
                comercio_id_seleccionado=None,
                comercio_id_cambio_pendiente=None,
                mensaje_original_pendiente=None,
                options=(),
                resolution_source="missing_context",
            )
        return None


def _safe_selected(
    existing: ContextoClienteCanalWhatsapp | None,
) -> int | None:
    if existing is None:
        return None
    if existing.comercio_id_seleccionado is None:
        return None
    return int(existing.comercio_id_seleccionado)


def _safe_pending(
    existing: ContextoClienteCanalWhatsapp | None,
) -> int | None:
    if existing is None:
        return None
    if existing.comercio_id_cambio_pendiente is None:
        return None
    return int(existing.comercio_id_cambio_pendiente)


def _safe_message(
    existing: ContextoClienteCanalWhatsapp | None,
) -> str | None:
    if existing is None:
        return None
    return existing.mensaje_original_pendiente


def _with_membership(
    outcome: ManualSelectionOutcome,
    membership_id: int,
) -> ManualSelectionOutcome:
    return ManualSelectionOutcome(
        status=outcome.status,
        canal_id=outcome.canal_id,
        cliente_id=outcome.cliente_id,
        membership_id=membership_id,
        comercio_id_seleccionado=outcome.comercio_id_seleccionado,
        comercio_id_cambio_pendiente=outcome.comercio_id_cambio_pendiente,
        mensaje_original_pendiente=outcome.mensaje_original_pendiente,
        options=(),
        resolution_source=outcome.resolution_source,
    )


__all__ = [
    "ContextActivationOutcome",
    "ContextActivationStatus",
    "ManualSelectionOption",
    "ManualSelectionOutcome",
    "ManualSelectionStatus",
    "SharedChannelRoutingService",
]
