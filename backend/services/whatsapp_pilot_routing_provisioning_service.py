"""Controlled-WhatsApp pilot routing provisioning service.

The service is the only place that stages the pilot client and
dedicated-channel rows needed for a single
``CommerceChannelResolver.resolve_dedicated("twilio", sender)``
success. It exists so the CLI never imports
``ClienteRepository`` / ``CanalWhatsappService`` directly and so the
service can own the read-mostly inspection contract while the CLI
remains the sole owner of the single setup transaction.

The service is intentionally narrow:

* it accepts already-canonical E.164 destinations for the client and
  the configured sender (canonicalization is the CLI's job — it
  rejects raw user input there);
* it accepts the already-validated positive ``comercio_id``;
* it stages ORM state via the no-flush helpers in
  :class:`backend.repositories.cliente_repository.ClienteRepository`
  and the existing ``CanalWhatsappService.register_dedicated_channel``;
* it never calls ``commit``, ``rollback``, ``begin`` or ``flush``;
* it never invokes the inbound coordinator, the outbox dispatcher,
  the delivery callback adapter, the recognizer, the catalog or the
  shared-channel activation surface;
* it never logs, prints or returns the E.164 address, the sender,
  message bodies, credentials, signatures or database URLs.

The service exposes two narrow operations:

* :meth:`WhatsappPilotRoutingProvisioningService.verify` — read-only
  inspection that never mutates any row and reports the exact
  ``CommerceChannelResolver`` outcome alongside the active /
  inactive / missing flags for the required client.
* :meth:`WhatsappPilotRoutingProvisioningService.apply` — staging
  only: it stages the missing active client, stages the missing
  dedicated channel, reactivates an inactive client only when the
  CLI forwards an explicit acknowledgement and returns the typed
  result so the CLI can run the final resolver check, commit once
  or roll back on every failure.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from backend.models import Comercio
from backend.models.canal_whatsapp import CanalWhatsappMode
from backend.repositories.canal_whatsapp_repository import (
    CanalWhatsappRepository,
)
from backend.repositories.cliente_repository import ClienteRepository
from backend.services.canal_whatsapp_service import (
    CanalWhatsappService,
    normalize_destination,
)
from backend.services.commerce_availability_service import (
    CommerceAvailabilityService,
    CommerceAvailabilityStatus,
)
from backend.services.commerce_channel_resolver import (
    CommerceChannelResolver,
    DedicatedResolution,
    ResolutionStatus,
)
from backend.services.exceptions import (
    InvalidWhatsappPilotProvisioningInput,
    WhatsappPilotProvisioningCommerceUnavailable,
)

_PROVIDER_TWILIO = "twilio"


class ProvisioningMode(str, enum.Enum):
    """CLI mode echoed in every result for evidence auditing."""

    VERIFY = "verify"
    APPLY = "apply"


class ProvisioningStatus(str, enum.Enum):
    """Single source of truth for the CLI / log / evidence surface.

    Every value is a safe identifier; no value exposes an address,
    body, credential or DB URL.
    """

    READY = "ready"
    PROVISIONED = "provisioned"
    NOT_READY = "not_ready"
    INACTIVE_CLIENT_REQUIRES_ACKNOWLEDGEMENT = (
        "inactive_client_requires_acknowledgement"
    )
    CONFIGURATION_FAILURE = "configuration_failure"
    INPUT_INVALID = "input_invalid"
    COMMERCE_UNAVAILABLE = "commerce_unavailable"
    DUPLICATE_CONFLICT = "duplicate_conflict"
    TECHNICAL_FAILURE = "technical_failure"


@dataclass(frozen=True)
class ProvisioningResult:
    """Immutable, sanitized pilot-routing provisioning outcome.

    Every value is safe to log, print and persist in pilot evidence.
    ``cliente_id`` / ``canal_id`` are numeric internal IDs only;
    ``cliente_e164`` / ``sender_e164`` are NEVER stored on this
    dataclass — callers must keep the raw addresses in caller-owned
    state and redacted before any logging or evidence step.
    """

    mode: ProvisioningMode
    status: ProvisioningStatus
    comercio_id: int
    cliente_id: int | None
    canal_id: int | None
    resolver_status: ResolutionStatus | None
    client_created: bool = False
    client_reactivated: bool = False
    channel_created: bool = False
    detalle: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _ResolverOutcome:
    """Internal carrier for the resolver-driven outcome grouping.

    The service resolves the existing channel state once via
    :class:`CommerceChannelResolver` and groups the result so the
    CLI can branch on a single attribute without re-reading the
    channel table.
    """

    resolution: DedicatedResolution
    existing_canal: Any | None
    existing_cliente: Any | None


class WhatsappPilotRoutingProvisioningService:
    """Staging-only service for the controlled WhatsApp pilot.

    The service is intentionally narrow. It only knows how to:

    * load the canonical client row (or absence) by the normalized
      ``cliente_e164``;
    * load the canonical channel row (or absence) by the normalized
      ``sender_e164`` for provider ``twilio``;
    * read the active ``Commerce`` referenced by ``comercio_id``;
    * stage a new active ``Cliente`` via the no-flush
      :meth:`ClienteRepository.stage_create` helper;
    * stage a reactivation of an inactive ``Cliente`` via the
      no-flush :meth:`ClienteRepository.stage_set_activo` helper;
    * stage a new dedicated ``CanalWhatsapp`` via
      :meth:`CanalWhatsappService.register_dedicated_channel`
      (which already does not flush);
    * return a typed, sanitized :class:`ProvisioningResult`.

    Transaction ownership is NEVER claimed here; the service stages
    ORM state and the CLI runs the single ``flush`` (after staging
    both records) followed by the single ``commit`` or
    ``rollback``.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._cliente_repo = ClienteRepository(session)
        self._canal_repo = CanalWhatsappRepository(session)
        self._canal_service = CanalWhatsappService(session)
        self._resolver = CommerceChannelResolver(session)

    def resolve_for_canonical_sender(
        self, sender_e164_canonical: str
    ) -> DedicatedResolution:
        """Run the resolver against the live (possibly flushed) session.

        The CLI is the sole owner of the single setup transaction. The
        staging service deliberately never flushes so the staged client
        and channel rows remain invisible to the resolver until the CLI
        flushes once. After the CLI flushes, this helper exposes the
        resolver outcome against the staged state so the CLI can decide
        whether to commit or roll back.
        """
        return self._resolver.resolve_dedicated(
            _PROVIDER_TWILIO, sender_e164_canonical
        )

    def find_canal_id_by_destination(
        self, sender_e164_canonical: str
    ) -> int | None:
        """Return the canal ``id`` for the canonical sender.

        Used by the CLI after the staging flush so the final
        :class:`ProvisioningResult` echoes the persisted, canonical
        numeric ID instead of the in-memory pre-flush surrogate.
        """
        canal = self._canal_repo.find_by_provider_destination_any(
            _PROVIDER_TWILIO, sender_e164_canonical
        )
        return None if canal is None else int(canal.id)

    def find_cliente_id_by_whatsapp(
        self, cliente_e164_canonical: str
    ) -> int | None:
        """Return the cliente ``id`` for the canonical WhatsApp address.

        Used by the CLI after the staging flush so the final
        :class:`ProvisioningResult` echoes the persisted, canonical
        numeric ID instead of the in-memory pre-flush surrogate.
        """
        cliente = self._cliente_repo.get_by_whatsapp(
            cliente_e164_canonical
        )
        return None if cliente is None else int(cliente.id)

    def verify(
        self,
        *,
        cliente_e164_canonical: str,
        comercio_id: int,
        sender_e164_canonical: str,
    ) -> ProvisioningResult:
        """Return the read-only sanitized readiness outcome.

        The call NEVER mutates and NEVER flushes; the resolver runs
        against the live, committed rows. The CLI translates the
        result into ``ready`` / ``not_ready`` /
        ``inactive_client_requires_acknowledgement`` /
        ``configuration_failure`` without any further I/O.
        """
        self._assert_commerce_activo(comercio_id)
        outcome = self._inspect(
            cliente_e164_canonical=cliente_e164_canonical,
            comercio_id=comercio_id,
            sender_e164_canonical=sender_e164_canonical,
        )
        return self._compose_verify_result(
            outcome=outcome, comercio_id=comercio_id
        )

    def apply(
        self,
        *,
        cliente_e164_canonical: str,
        comercio_id: int,
        sender_e164_canonical: str,
        reactivate_client_acknowledgement: bool,
    ) -> ProvisioningResult:
        """Stage the missing pilot records without committing.

        The call stages ORM state through the no-flush repository
        helpers. It does NOT call ``flush``, ``commit``,
        ``rollback`` or ``begin``. The CLI performs the single
        flush that exposes the staged state to the final resolver
        check and then commits once or rolls back on every failure.

        A missing / inactive commerce raises
        :class:`WhatsappPilotProvisioningCommerceUnavailable` BEFORE
        any staging so the CLI can roll back a fresh, empty
        transaction. A duplicate race condition raises
        :class:`DuplicateCanalWhatsappDestination` /
        :class:`DuplicateWhatsapp` so the CLI rolls back and
        translates it to the typed ``duplicate_conflict`` status.
        """
        self._assert_commerce_activo(comercio_id)
        outcome = self._inspect(
            cliente_e164_canonical=cliente_e164_canonical,
            comercio_id=comercio_id,
            sender_e164_canonical=sender_e164_canonical,
        )

        canal = outcome.existing_canal
        if canal is not None:
            detalle = self._detail_for_existing_canal(canal, comercio_id)
            if detalle == "channel_history_exists":
                canal_id = int(canal.id)
                cliente = outcome.existing_cliente
                client_created = False
                client_reactivated = False
                if cliente is None:
                    cliente = self._cliente_repo.stage_create(
                        whatsapp=cliente_e164_canonical,
                        nombre=None,
                        domicilio=None,
                        activo=True,
                    )
                    client_created = True
                elif not cliente.activo:
                    if not reactivate_client_acknowledgement:
                        return ProvisioningResult(
                            mode=ProvisioningMode.APPLY,
                            status=ProvisioningStatus.INACTIVE_CLIENT_REQUIRES_ACKNOWLEDGEMENT,
                            comercio_id=comercio_id,
                            cliente_id=self._safe_id(cliente),
                            canal_id=canal_id,
                            resolver_status=outcome.resolution.status,
                        )
                    self._cliente_repo.stage_set_activo(cliente, True)
                    client_reactivated = True
                if client_created or client_reactivated:
                    return ProvisioningResult(
                        mode=ProvisioningMode.APPLY,
                        status=ProvisioningStatus.NOT_READY,
                        comercio_id=comercio_id,
                        cliente_id=self._safe_id(cliente),
                        canal_id=canal_id,
                        resolver_status=outcome.resolution.status,
                        client_created=client_created,
                        client_reactivated=client_reactivated,
                        channel_created=False,
                        detalle="staged",
                    )
                return ProvisioningResult(
                    mode=ProvisioningMode.APPLY,
                    status=ProvisioningStatus.READY,
                    comercio_id=comercio_id,
                    cliente_id=self._safe_id(cliente),
                    canal_id=canal_id,
                    resolver_status=outcome.resolution.status,
                    detalle="channel_history_exists",
                )
            return ProvisioningResult(
                mode=ProvisioningMode.APPLY,
                status=ProvisioningStatus.CONFIGURATION_FAILURE,
                comercio_id=comercio_id,
                cliente_id=self._safe_id(outcome.existing_cliente),
                canal_id=int(canal.id),
                resolver_status=outcome.resolution.status,
                detalle=detalle,
            )

        cliente = outcome.existing_cliente
        client_created = False
        client_reactivated = False
        if cliente is None:
            cliente = self._cliente_repo.stage_create(
                whatsapp=cliente_e164_canonical,
                nombre=None,
                domicilio=None,
                activo=True,
            )
            client_created = True
        elif not cliente.activo:
            if not reactivate_client_acknowledgement:
                return ProvisioningResult(
                    mode=ProvisioningMode.APPLY,
                    status=ProvisioningStatus.INACTIVE_CLIENT_REQUIRES_ACKNOWLEDGEMENT,
                    comercio_id=comercio_id,
                    cliente_id=self._safe_id(cliente),
                    canal_id=None,
                    resolver_status=outcome.resolution.status,
                )
            self._cliente_repo.stage_set_activo(cliente, True)
            client_reactivated = True

        canal = self._canal_service.register_dedicated_channel(
            provider=_PROVIDER_TWILIO,
            destination=sender_e164_canonical,
            id_comercio_exclusivo=comercio_id,
        )

        return ProvisioningResult(
            mode=ProvisioningMode.APPLY,
            status=ProvisioningStatus.NOT_READY,
            comercio_id=comercio_id,
            cliente_id=self._safe_id(cliente),
            canal_id=self._safe_id(canal),
            resolver_status=outcome.resolution.status,
            client_created=client_created,
            client_reactivated=client_reactivated,
            channel_created=True,
            detalle="staged",
        )

    def _inspect(
        self,
        *,
        cliente_e164_canonical: str,
        comercio_id: int,
        sender_e164_canonical: str,
    ) -> _ResolverOutcome:
        existing_cliente = self._cliente_repo.get_by_whatsapp(
            cliente_e164_canonical
        )
        resolution = self._resolver.resolve_dedicated(
            _PROVIDER_TWILIO, sender_e164_canonical
        )
        canal = self._canal_repo.find_by_provider_destination_any(
            _PROVIDER_TWILIO, sender_e164_canonical
        )
        return _ResolverOutcome(
            resolution=resolution,
            existing_canal=canal,
            existing_cliente=existing_cliente,
        )

    def _compose_verify_result(
        self,
        *,
        outcome: _ResolverOutcome,
        comercio_id: int,
    ) -> ProvisioningResult:
        resolution = outcome.resolution
        cliente = outcome.existing_cliente
        canal = outcome.existing_canal

        canal_id: int | None = resolution.channel_id
        if canal_id is None and canal is not None:
            canal_id = int(canal.id)

        if resolution.status is ResolutionStatus.RESOLVED:
            if resolution.comercio_id == comercio_id:
                if cliente is None:
                    return ProvisioningResult(
                        mode=ProvisioningMode.VERIFY,
                        status=ProvisioningStatus.NOT_READY,
                        comercio_id=comercio_id,
                        cliente_id=None,
                        canal_id=canal_id,
                        resolver_status=resolution.status,
                        detalle="client_missing",
                    )
                if not cliente.activo:
                    return ProvisioningResult(
                        mode=ProvisioningMode.VERIFY,
                        status=ProvisioningStatus.INACTIVE_CLIENT_REQUIRES_ACKNOWLEDGEMENT,
                        comercio_id=comercio_id,
                        cliente_id=self._safe_id(cliente),
                        canal_id=canal_id,
                        resolver_status=resolution.status,
                    )
                return ProvisioningResult(
                    mode=ProvisioningMode.VERIFY,
                    status=ProvisioningStatus.READY,
                    comercio_id=comercio_id,
                    cliente_id=int(cliente.id),
                    canal_id=canal_id,
                    resolver_status=resolution.status,
                )
            return ProvisioningResult(
                mode=ProvisioningMode.VERIFY,
                status=ProvisioningStatus.CONFIGURATION_FAILURE,
                comercio_id=comercio_id,
                cliente_id=self._safe_id(cliente),
                canal_id=canal_id,
                resolver_status=resolution.status,
                detalle="channel_commerce_mismatch",
            )

        if resolution.status is ResolutionStatus.INACTIVE_CHANNEL:
            return ProvisioningResult(
                mode=ProvisioningMode.VERIFY,
                status=ProvisioningStatus.CONFIGURATION_FAILURE,
                comercio_id=comercio_id,
                cliente_id=self._safe_id(cliente),
                canal_id=canal_id,
                resolver_status=resolution.status,
                detalle="channel_inactive",
            )

        if resolution.status is ResolutionStatus.REQUIRES_SHARED_ROUTING:
            return ProvisioningResult(
                mode=ProvisioningMode.VERIFY,
                status=ProvisioningStatus.CONFIGURATION_FAILURE,
                comercio_id=comercio_id,
                cliente_id=self._safe_id(cliente),
                canal_id=canal_id,
                resolver_status=resolution.status,
                detalle="channel_mode_mismatch",
            )

        if resolution.status is ResolutionStatus.UNAVAILABLE_COMMERCE:
            return ProvisioningResult(
                mode=ProvisioningMode.VERIFY,
                status=ProvisioningStatus.CONFIGURATION_FAILURE,
                comercio_id=comercio_id,
                cliente_id=self._safe_id(cliente),
                canal_id=canal_id,
                resolver_status=resolution.status,
                detalle="channel_commerce_unavailable",
            )

        if resolution.status is ResolutionStatus.INVALID_DESTINATION:
            return ProvisioningResult(
                mode=ProvisioningMode.VERIFY,
                status=ProvisioningStatus.INPUT_INVALID,
                comercio_id=comercio_id,
                cliente_id=self._safe_id(cliente),
                canal_id=None,
                resolver_status=resolution.status,
                detalle="sender_destination_invalid",
            )

        if resolution.status is ResolutionStatus.UNKNOWN_CHANNEL:
            if cliente is None:
                return ProvisioningResult(
                    mode=ProvisioningMode.VERIFY,
                    status=ProvisioningStatus.NOT_READY,
                    comercio_id=comercio_id,
                    cliente_id=None,
                    canal_id=None,
                    resolver_status=resolution.status,
                    detalle="client_and_channel_missing",
                )
            if not cliente.activo:
                return ProvisioningResult(
                    mode=ProvisioningMode.VERIFY,
                    status=ProvisioningStatus.INACTIVE_CLIENT_REQUIRES_ACKNOWLEDGEMENT,
                    comercio_id=comercio_id,
                    cliente_id=int(cliente.id),
                    canal_id=None,
                    resolver_status=resolution.status,
                )
            return ProvisioningResult(
                mode=ProvisioningMode.VERIFY,
                status=ProvisioningStatus.NOT_READY,
                comercio_id=comercio_id,
                cliente_id=int(cliente.id),
                canal_id=None,
                resolver_status=resolution.status,
                detalle="channel_missing",
            )

        return ProvisioningResult(
            mode=ProvisioningMode.VERIFY,
            status=ProvisioningStatus.TECHNICAL_FAILURE,
            comercio_id=comercio_id,
            cliente_id=self._safe_id(cliente),
            canal_id=canal_id,
            resolver_status=resolution.status,
            detalle="unhandled_resolver_status",
        )

    def _detail_for_existing_canal(
        self, canal: Any, comercio_id: int
    ) -> str:
        if not canal.activo:
            return "channel_inactive"
        if canal.mode is not CanalWhatsappMode.DEDICATED:
            return "channel_mode_mismatch"
        if canal.id_comercio_exclusivo != comercio_id:
            return "channel_commerce_mismatch"
        return "channel_history_exists"

    def _assert_commerce_activo(self, comercio_id: int) -> None:
        if not isinstance(comercio_id, int) or comercio_id <= 0:
            raise InvalidWhatsappPilotProvisioningInput(
                "comercio_id must be a positive integer"
            )
        comercio = self._session.get(Comercio, comercio_id)
        if comercio is None:
            raise WhatsappPilotProvisioningCommerceUnavailable(
                f"comercio {comercio_id} not found"
            )
        outcome = CommerceAvailabilityService(
            self._session
        ).evaluate(comercio_id)
        if outcome.status is not CommerceAvailabilityStatus.AVAILABLE:
            raise WhatsappPilotProvisioningCommerceUnavailable(
                f"comercio {comercio_id} is not active"
            )

    @staticmethod
    def _safe_id(row: Any) -> int | None:
        if row is None:
            return None
        row_id = getattr(row, "id", None)
        if row_id is None:
            return None
        return int(row_id)

    def _refresh_canal(self, canal: Any) -> Any:
        canal_id = int(canal.id)
        refreshed = self._canal_repo.find_by_id(canal_id)
        return refreshed if refreshed is not None else canal


def normalize_cliente_e164(raw: str | None) -> str:
    """Re-export the canonical E.164 normalization for the CLI.

    The CLI must call this exactly once before invoking the service.
    The service assumes the supplied values are already canonical so
    it can avoid mixing business validation with normalization.
    """
    return normalize_destination(raw)


__all__ = [
    "InvalidWhatsappPilotProvisioningInput",
    "ProvisioningMode",
    "ProvisioningResult",
    "ProvisioningStatus",
    "WhatsappPilotProvisioningCommerceUnavailable",
    "WhatsappPilotRoutingProvisioningService",
    "normalize_cliente_e164",
]
