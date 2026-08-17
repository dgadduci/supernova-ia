"""Service for WhatsApp channel registration and shared-membership lifecycle.

Phase 5.1 scope. The service is the only place that:

* normalizes raw destination numbers to canonical E.164 (stripping the
  optional ``whatsapp:`` transport prefix and any whitespace);
* normalizes the closed-set ``provider`` identifier;
* normalizes opaque public routing codes for shared-channel membership;
* enforces the dedicated / shared cross-entity invariants;
* enforces the permanent historical ``(canal_id,
  routing_code_normalizado)`` reservation rule;
* translates IntegrityError into the project's typed exceptions.

The service and its repositories NEVER call ``commit``, ``rollback``,
``begin``, ``flush``, ``close`` or the incoming-message processor.
Transaction ownership and synchronization belong to the caller.

The read-only ``CommerceChannelResolver`` (sibling module) is the
boundary for resolving a destination to a commerce before the business
pipeline runs.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models.canal_whatsapp import CanalWhatsapp, CanalWhatsappMode
from backend.models.comercio_canal_compartido import ComercioCanalCompartido
from backend.repositories.canal_whatsapp_repository import (
    CanalWhatsappRepository,
)
from backend.repositories.comercio_canal_compartido_repository import (
    ComercioCanalCompartidoRepository,
)
from backend.services.commerce_availability_service import (
    CommerceAvailabilityService,
    CommerceAvailabilityStatus,
)
from backend.services.exceptions import (
    CanalWhatsappNotFound,
    DedicatedChannelCannotHaveSharedMembership,
    DuplicateCanalWhatsappDestination,
    DuplicateRoutingCodeReservation,
    InvalidCanalWhatsappDestination,
    InvalidCanalWhatsappProvider,
    InvalidRoutingCode,
    SharedChannelCannotHaveExclusiveComercio,
)

_KNOWN_PROVIDERS = frozenset({"twilio"})

_E164_PATTERN = re.compile(r"^\+[1-9][0-9]{6,14}$")

_ROUTING_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{2,40}$")


def _normalize_provider(raw: str | None) -> str:
    if not isinstance(raw, str):
        raise InvalidCanalWhatsappProvider("provider must be a string")
    cleaned = raw.strip().lower()
    if not cleaned:
        raise InvalidCanalWhatsappProvider("provider must not be empty")
    if cleaned not in _KNOWN_PROVIDERS:
        raise InvalidCanalWhatsappProvider(
            f"provider {cleaned!r} is not supported"
        )
    return cleaned


def normalize_destination(raw: str | None) -> str:
    """Return the canonical E.164 destination number.

    Strips an optional ``whatsapp:`` prefix and whitespace, then
    enforces the E.164 shape: ``+`` followed by 7-15 digits with no
    leading zero after the ``+``. Equivalent supported representations
    (e.g. ``"  whatsapp:+5491155556666  "``) collapse to the same
    canonical value.
    """
    if not isinstance(raw, str):
        raise InvalidCanalWhatsappDestination(
            "destination must be a string"
        )
    cleaned = raw.strip()
    lowered = cleaned.lower()
    if lowered.startswith("whatsapp:"):
        cleaned = lowered[len("whatsapp:") :].strip()
    cleaned = cleaned.replace(" ", "").replace("\t", "").replace("-", "")
    if not cleaned:
        raise InvalidCanalWhatsappDestination(
            "destination must not be empty"
        )
    if not _E164_PATTERN.match(cleaned):
        raise InvalidCanalWhatsappDestination(
            f"destination {cleaned!r} is not a canonical E.164 value"
        )
    return cleaned


def normalize_routing_code(raw: str | None) -> str:
    """Return the canonical opaque public routing code.

    Routing codes are public identifiers (QR slug, short-link suffix).
    They are restricted to a stable, transport-safe character set so
    equivalent URLs / QR payloads map to the same reservation row.
    """
    if not isinstance(raw, str):
        raise InvalidRoutingCode("routing_code must be a string")
    cleaned = raw.strip()
    if not cleaned:
        raise InvalidRoutingCode("routing_code must not be empty")
    if not _ROUTING_CODE_PATTERN.match(cleaned):
        raise InvalidRoutingCode(
            f"routing_code {cleaned!r} is not a valid opaque identifier"
        )
    return cleaned


class CanalWhatsappService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._canal_repo = CanalWhatsappRepository(session)
        self._membresia_repo = ComercioCanalCompartidoRepository(session)

    @staticmethod
    def normalize_destination(raw: str | None) -> str:
        return normalize_destination(raw)

    @staticmethod
    def normalize_provider(raw: str | None) -> str:
        return _normalize_provider(raw)

    @staticmethod
    def normalize_routing_code(raw: str | None) -> str:
        return normalize_routing_code(raw)

    def _ensure_comercio_exists(self, id_comercio: int) -> None:
        from backend.models import Comercio

        if self._session.get(Comercio, id_comercio) is None:
            raise CanalWhatsappNotFound(
                f"comercio {id_comercio} not found"
            )

    def _ensure_comercio_active(self, id_comercio: int) -> None:
        from backend.models import Comercio

        comercio = self._session.get(Comercio, id_comercio)
        if comercio is None:
            raise CanalWhatsappNotFound(
                f"comercio {id_comercio} not found"
            )
        outcome = CommerceAvailabilityService(
            self._session
        ).evaluate(id_comercio)
        if outcome.status is not CommerceAvailabilityStatus.AVAILABLE:
            raise CanalWhatsappNotFound(
                f"comercio {id_comercio} is not active"
            )

    def register_dedicated_channel(
        self,
        provider: str,
        destination: str,
        id_comercio_exclusivo: int,
    ) -> CanalWhatsapp:
        canonical_provider = _normalize_provider(provider)
        canonical_destination = normalize_destination(destination)
        self._ensure_comercio_active(id_comercio_exclusivo)
        if (
            self._canal_repo.find_active_by_provider_destination(
                canonical_provider, canonical_destination
            )
            is not None
        ):
            raise DuplicateCanalWhatsappDestination(
                f"active channel already exists for "
                f"provider={canonical_provider} "
                f"destination={canonical_destination}"
            )
        try:
            return self._canal_repo.create(
                canonical_provider,
                canonical_destination,
                CanalWhatsappMode.DEDICATED,
                id_comercio_exclusivo,
                True,
            )
        except IntegrityError as exc:
            raise DuplicateCanalWhatsappDestination(str(exc.orig)) from exc

    def register_shared_channel(
        self,
        provider: str,
        destination: str,
    ) -> CanalWhatsapp:
        canonical_provider = _normalize_provider(provider)
        canonical_destination = normalize_destination(destination)
        if (
            self._canal_repo.find_active_by_provider_destination(
                canonical_provider, canonical_destination
            )
            is not None
        ):
            raise DuplicateCanalWhatsappDestination(
                f"active channel already exists for "
                f"provider={canonical_provider} "
                f"destination={canonical_destination}"
            )
        try:
            return self._canal_repo.create(
                canonical_provider,
                canonical_destination,
                CanalWhatsappMode.SHARED,
                None,
                True,
            )
        except IntegrityError as exc:
            raise DuplicateCanalWhatsappDestination(str(exc.orig)) from exc

    def deactivate_channel(self, canal_id: int) -> CanalWhatsapp:
        canal = self._canal_repo.find_by_id(canal_id)
        if canal is None:
            raise CanalWhatsappNotFound(
                f"canal_whatsapp {canal_id} not found"
            )
        if not canal.activo:
            return canal
        canal.activo = False
        canal.fecha_baja = datetime.now(timezone.utc)
        return canal

    def register_shared_membership(
        self,
        canal_id: int,
        comercio_id: int,
        routing_code: str,
    ) -> ComercioCanalCompartido:
        canal = self._canal_repo.find_by_id(canal_id)
        if canal is None:
            raise CanalWhatsappNotFound(
                f"canal_whatsapp {canal_id} not found"
            )
        if canal.mode is not CanalWhatsappMode.SHARED:
            raise DedicatedChannelCannotHaveSharedMembership(
                f"canal_whatsapp {canal_id} is not a shared channel"
            )
        self._ensure_comercio_active(comercio_id)
        canonical_code = normalize_routing_code(routing_code)
        if (
            self._membresia_repo.find_any_by_canal_and_code(
                canal_id, canonical_code
            )
            is not None
        ):
            raise DuplicateRoutingCodeReservation(
                f"routing_code {canonical_code!r} is already reserved "
                f"for canal {canal_id}"
            )
        try:
            return self._membresia_repo.create(
                canal_id,
                comercio_id,
                routing_code.strip(),
                canonical_code,
                True,
            )
        except IntegrityError as exc:
            raise DuplicateRoutingCodeReservation(str(exc.orig)) from exc

    def deactivate_shared_membership(
        self,
        canal_id: int,
        routing_code: str,
    ) -> ComercioCanalCompartido:
        canal = self._canal_repo.find_by_id(canal_id)
        if canal is None:
            raise CanalWhatsappNotFound(
                f"canal_whatsapp {canal_id} not found"
            )
        if canal.mode is not CanalWhatsappMode.SHARED:
            raise DedicatedChannelCannotHaveSharedMembership(
                f"canal_whatsapp {canal_id} is not a shared channel"
            )
        canonical_code = normalize_routing_code(routing_code)
        membership = self._membresia_repo.find_any_by_canal_and_code(
            canal_id, canonical_code
        )
        if membership is None:
            raise CanalWhatsappNotFound(
                f"routing_code {canonical_code!r} is not reserved "
                f"for canal {canal_id}"
            )
        if not membership.activo:
            return membership
        membership.activo = False
        return membership

    def assert_can_be_dedicated(self, canal_id: int) -> None:
        canal = self._canal_repo.find_by_id(canal_id)
        if canal is None:
            raise CanalWhatsappNotFound(
                f"canal_whatsapp {canal_id} not found"
            )
        if canal.mode is not CanalWhatsappMode.DEDICATED:
            raise SharedChannelCannotHaveExclusiveComercio(
                f"canal_whatsapp {canal_id} is not a dedicated channel"
            )
        if canal.id_comercio_exclusivo is None:
            raise SharedChannelCannotHaveExclusiveComercio(
                f"canal_whatsapp {canal_id} has no exclusive commerce"
            )


__all__ = [
    "CanalWhatsappService",
    "normalize_destination",
    "normalize_routing_code",
]