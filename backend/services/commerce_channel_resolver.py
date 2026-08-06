"""Read-only commerce-channel resolver.

Phase 5.1 boundary. The resolver accepts a provider + destination
input, normalizes the destination, and returns one of the documented
typed outcomes. It never mutates, never commits, never rolls back and
never invokes the local incoming-message endpoint, classifier,
recognizer, catalog or handler code.

The 5.1 success path is the active dedicated channel case: a single
exclusive commerce is identified from the provider-scoped destination.
All other cases return a typed non-resolved outcome and never select a
commerce; the future shared-code activation path is reserved through
``requires_shared_routing`` so callers can hand control to Phase 5.2.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.models.canal_whatsapp import CanalWhatsappMode
from backend.repositories.canal_whatsapp_repository import (
    CanalWhatsappRepository,
)
from backend.services.canal_whatsapp_service import (
    InvalidCanalWhatsappDestination,
    normalize_destination,
)


class ResolutionStatus(str, enum.Enum):
    """Typed outcomes returned by ``CommerceChannelResolver``.

    Every value MUST map to a single non-resolved or resolved state.
    The resolver never raises a non-resolved exception to its caller:
    malformed inputs collapse into ``INVALID_DESTINATION`` so the
    caller can branch on a single attribute.
    """

    RESOLVED = "resolved"
    INVALID_DESTINATION = "invalid_destination"
    UNKNOWN_CHANNEL = "unknown_channel"
    INACTIVE_CHANNEL = "inactive_channel"
    UNAVAILABLE_COMMERCE = "unavailable_commerce"
    REQUIRES_SHARED_ROUTING = "requires_shared_routing"


@dataclass(frozen=True)
class DedicatedResolution:
    """Immutable resolver outcome.

    ``status`` is the single source of truth for branching; every other
    field is only meaningful for ``RESOLVED`` outcomes. ``channel_id``
    and ``comercio_id`` are populated for resolved dedicated channels;
    ``routing_mode`` echoes the channel mode so callers can branch on
    it without re-loading the row.
    """

    status: ResolutionStatus
    channel_id: int | None
    routing_mode: CanalWhatsappMode | None
    comercio_id: int | None
    resolution_source: str

    @property
    def is_resolved(self) -> bool:
        return self.status is ResolutionStatus.RESOLVED


class CommerceChannelResolver:
    """Read-only dedicated-channel resolver.

    The resolver holds a SQLAlchemy ``Session`` and a single repository
    and exposes one entry point: ``resolve_dedicated``. It MUST NOT
    touch any pipeline component: no sender inspection, no message
    text inspection, no client/session creation, no classifier,
    recognizer, handler or catalog call.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._canal_repo = CanalWhatsappRepository(session)

    def resolve_dedicated(
        self,
        provider: str,
        destination: str,
    ) -> DedicatedResolution:
        try:
            canonical_destination = normalize_destination(destination)
        except InvalidCanalWhatsappDestination:
            return DedicatedResolution(
                status=ResolutionStatus.INVALID_DESTINATION,
                channel_id=None,
                routing_mode=None,
                comercio_id=None,
                resolution_source="destination_normalization",
            )

        canal = self._canal_repo.find_active_by_provider_destination(
            provider, canonical_destination
        )
        if canal is None:
            any_canal = self._canal_repo.find_by_provider_destination_any(
                provider, canonical_destination
            )
            if any_canal is not None and not any_canal.activo:
                return DedicatedResolution(
                    status=ResolutionStatus.INACTIVE_CHANNEL,
                    channel_id=int(any_canal.id),
                    routing_mode=any_canal.mode,
                    comercio_id=None,
                    resolution_source="inactive_channel",
                )
            return DedicatedResolution(
                status=ResolutionStatus.UNKNOWN_CHANNEL,
                channel_id=None,
                routing_mode=None,
                comercio_id=None,
                resolution_source="no_active_channel",
            )

        if canal.mode is CanalWhatsappMode.SHARED:
            return DedicatedResolution(
                status=ResolutionStatus.REQUIRES_SHARED_ROUTING,
                channel_id=int(canal.id),
                routing_mode=CanalWhatsappMode.SHARED,
                comercio_id=None,
                resolution_source="shared_channel",
            )

        comercio_id = canal.id_comercio_exclusivo
        if comercio_id is None:
            return DedicatedResolution(
                status=ResolutionStatus.UNAVAILABLE_COMMERCE,
                channel_id=int(canal.id),
                routing_mode=CanalWhatsappMode.DEDICATED,
                comercio_id=None,
                resolution_source="no_exclusive_commerce",
            )

        if not self._is_comercio_activo(comercio_id):
            return DedicatedResolution(
                status=ResolutionStatus.UNAVAILABLE_COMMERCE,
                channel_id=int(canal.id),
                routing_mode=CanalWhatsappMode.DEDICATED,
                comercio_id=comercio_id,
                resolution_source="inactive_commerce",
            )

        return DedicatedResolution(
            status=ResolutionStatus.RESOLVED,
            channel_id=int(canal.id),
            routing_mode=CanalWhatsappMode.DEDICATED,
            comercio_id=int(comercio_id),
            resolution_source="destination_number",
        )

    def _is_comercio_activo(self, comercio_id: int) -> bool:
        from backend.models import Comercio, EstadoComercio

        comercio = self._session.get(Comercio, comercio_id)
        if comercio is None:
            return False
        estado = self._session.get(EstadoComercio, comercio.estado_id)
        if estado is None:
            return False
        return estado.estado == "ACTIVO"


__all__ = [
    "CommerceChannelResolver",
    "DedicatedResolution",
    "ResolutionStatus",
]