"""Phase-5.4 provider-neutral inbound-message coordinator.

The coordinator owns the sole provider-message receipt transaction
boundary. It accepts a validated active routing decision
(``ProviderInboundMessageCommand``), validates it against the existing
client, active channel and channel-scoped commerce authority,
conflict-safe claims one provider receipt via PostgreSQL
``INSERT ... ON CONFLICT DO NOTHING RETURNING``, stages a compatible
active conversation session for the supplied commerce/client pair,
invokes the existing non-transactional message pipeline and commits
the staged state once. A duplicate committed receipt rolls back the
still-open coordinator transaction and returns
``already_processed`` without re-invoking the pipeline or creating a
new session.

The coordinator does NOT:

* parse provider payloads, validate Twilio signatures or build TwiML
  (Phase 5.5);
* deliver outbound messages, track callback state or schedule
  retries (Phase 5.6);
* expose an HTTP, FastAPI, Twilio SDK or response-delivery boundary;
* widen the candidate set of provider receipts, channel-scoped
  commerce decisions, active sessions or processed messages;
* touch transaction-control methods outside this class: no
  ``commit``, ``rollback``, ``begin``, ``flush``, ``close``,
  ``expire`` or ``refresh`` is called from any repository, routing
  service, session staging helper or reusable pipeline primitive
  that participates in the coordinator's transaction.

The existing ``process_incoming_message_transactional`` wrapper
remains the local-endpoint transaction owner; it now shares the
same non-transactional ``process_incoming_message`` primitive the
coordinator uses.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass

from sqlalchemy.orm import Session as SqlSession

from backend.intents.orchestration.incoming_message_orchestrator import (
    process_incoming_message,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models import CanalWhatsappMode
from backend.repositories.canal_whatsapp_repository import (
    CanalWhatsappRepository,
)
from backend.repositories.comercio_canal_compartido_repository import (
    ComercioCanalCompartidoRepository,
)
from backend.repositories.contexto_cliente_canal_whatsapp_repository import (
    ContextoClienteCanalWhatsappRepository,
)
from backend.repositories.mensaje_proveedor_saliente_repository import (
    MensajeProveedorSalienteRepository,
)
from backend.repositories.recepcion_mensaje_proveedor_repository import (
    RecepcionMensajeProveedorRepository,
)
from backend.repositories.session_repository import SessionRepository
from backend.services.exceptions import (
    InvalidProviderInboundMessageCommand,
)
from backend.services.outbound_response_mapper import (
    stage_outbound_rows,
)


class ProviderInboundMessageStatus(str, enum.Enum):
    """Typed outcomes returned by ``ProviderInboundMessageCoordinator.process``.

    Every value maps to a single non-resolved or resolved state. The
    coordinator never raises a business-outcome signal; callers
    branch on ``outcome.status`` after a single ``process`` call.
    """

    PROCESSED = "processed"
    ALREADY_PROCESSED = "already_processed"
    INVALID_CONTEXT = "invalid_context"


@dataclass(frozen=True)
class ProviderInboundMessageCommand:
    """Validated active routing decision for one provider delivery.

    Every field is required. The caller is responsible for producing
    a routing decision that is already authoritative for the
    supplied channel and client; the coordinator does not infer,
    widen or silently switch the commerce.
    """

    proveedor: str
    identificador_recepcion: str
    canal_id: int
    cliente_id: int
    comercio_id: int
    mensaje: str
    destinatario_e164: str

    def __post_init__(self) -> None:
        if not isinstance(self.proveedor, str) or not self.proveedor:
            raise InvalidProviderInboundMessageCommand(
                "proveedor must be a non-empty string"
            )
        if (
            not isinstance(self.identificador_recepcion, str)
            or not self.identificador_recepcion
        ):
            raise InvalidProviderInboundMessageCommand(
                "identificador_recepcion must be a non-empty string"
            )
        if (
            not isinstance(self.canal_id, int)
            or isinstance(self.canal_id, bool)
            or self.canal_id <= 0
        ):
            raise InvalidProviderInboundMessageCommand(
                "canal_id must be a positive integer"
            )
        if (
            not isinstance(self.cliente_id, int)
            or isinstance(self.cliente_id, bool)
            or self.cliente_id <= 0
        ):
            raise InvalidProviderInboundMessageCommand(
                "cliente_id must be a positive integer"
            )
        if (
            not isinstance(self.comercio_id, int)
            or isinstance(self.comercio_id, bool)
            or self.comercio_id <= 0
        ):
            raise InvalidProviderInboundMessageCommand(
                "comercio_id must be a positive integer"
            )
        if not isinstance(self.mensaje, str) or not self.mensaje.strip():
            raise InvalidProviderInboundMessageCommand(
                "mensaje must be a non-empty, non-whitespace string"
            )
        if (
            not isinstance(self.destinatario_e164, str)
            or not self.destinatario_e164.strip()
        ):
            raise InvalidProviderInboundMessageCommand(
                "destinatario_e164 must be a non-empty, non-whitespace string"
            )


@dataclass(frozen=True)
class ProviderInboundMessageOutcome:
    """Immutable Phase-5.4 outcome.

    ``status`` is the single source of truth for branching. Every
    other field is only meaningful for the matching successful
    outcome; non-success outcomes leave id-bearing fields as ``None``
    and ``processed_intents`` as an empty tuple. Raw inbound text is
    never copied onto the outcome so observability surfaces cannot
    leak provider payload bytes.
    """

    status: ProviderInboundMessageStatus
    canal_id: int
    cliente_id: int
    comercio_id: int
    proveedor: str
    identificador_recepcion: str
    receipt_id: int | None
    session_id: int | None
    processed_intents: tuple[ProcessedIntent, ...]
    resolution_source: str


class ProviderInboundMessageCoordinator:
    """Sole Phase-5.4 transaction owner for provider-message processing.

    The coordinator is the ONLY component in Phase 5.4 allowed to
    call ``commit`` or ``rollback`` on the SQLAlchemy session. No
    repository, routing service, session staging helper or reusable
    pipeline primitive participates in transaction control.
    """

    def __init__(
        self,
        session: SqlSession,
        canal_repo: CanalWhatsappRepository | None = None,
        contexto_repo: ContextoClienteCanalWhatsappRepository | None = None,
        membresia_repo: (
            ComercioCanalCompartidoRepository | None
        ) = None,
        recepcion_repo: RecepcionMensajeProveedorRepository | None = None,
        session_repo: SessionRepository | None = None,
        outbox_repo: MensajeProveedorSalienteRepository | None = None,
    ) -> None:
        self._session = session
        self._canal_repo = canal_repo or CanalWhatsappRepository(session)
        self._contexto_repo = (
            contexto_repo
            or ContextoClienteCanalWhatsappRepository(session)
        )
        self._membresia_repo = (
            membresia_repo
            or ComercioCanalCompartidoRepository(session)
        )
        self._recepcion_repo = (
            recepcion_repo or RecepcionMensajeProveedorRepository(session)
        )
        self._session_repo = session_repo or SessionRepository(session)
        self._outbox_repo = (
            outbox_repo or MensajeProveedorSalienteRepository(session)
        )

    def process(
        self, command: ProviderInboundMessageCommand
    ) -> ProviderInboundMessageOutcome:
        try:
            return self._process_locked(command)
        except InvalidProviderInboundMessageCommand:
            # Contract violation: surface to the caller untouched.
            raise
        except Exception:
            # Any technical failure rolls back the entire
            # coordinator transaction and propagates unchanged.
            self._session.rollback()
            raise

    def _process_locked(
        self, command: ProviderInboundMessageCommand
    ) -> ProviderInboundMessageOutcome:
        # 1. Existing active client.
        if not self._is_cliente_activo(command.cliente_id):
            return self._invalid(command, "client_lookup")

        # 2. Active channel and channel-scoped authority.
        canal = self._canal_repo.find_by_id(command.canal_id)
        if canal is None or not canal.activo:
            return self._invalid(command, "channel_lookup")
        if canal.mode is CanalWhatsappMode.DEDICATED:
            if (
                canal.id_comercio_exclusivo is None
                or int(canal.id_comercio_exclusivo) != command.comercio_id
            ):
                return self._invalid(command, "dedicated_authority")
        elif canal.mode is CanalWhatsappMode.SHARED:
            existing_context = self._contexto_repo.find_by_canal_and_cliente(
                command.canal_id, command.cliente_id
            )
            if existing_context is None:
                return self._invalid(command, "missing_shared_context")
            selected = existing_context.comercio_id_seleccionado
            if selected is None:
                # A pending target with no committed selection is
                # never processing authority.
                return self._invalid(command, "pending_only_target")
            if int(selected) != command.comercio_id:
                return self._invalid(command, "selected_authority_mismatch")
            # The selected commerce MUST also be an active member of
            # this shared channel right now. A stale context can still
            # reference a commerce whose membership has been revoked
            # (or never existed); processing authority requires a
            # live ``ComercioCanalCompartido`` for the same
            # ``(canal_id, comercio_id)`` pair.
            membership = (
                self._membresia_repo.find_active_by_canal_and_comercio(
                    command.canal_id, command.comercio_id
                )
            )
            if membership is None:
                return self._invalid(
                    command, "revoked_shared_membership"
                )
        else:
            return self._invalid(command, "unknown_channel_mode")

        if not self._is_comercio_activo(command.comercio_id):
            return self._invalid(command, "unavailable_commerce")

        # 3. Receipt claim (PG ON CONFLICT DO NOTHING RETURNING).
        receipt_id = self._recepcion_repo.claim(
            command.proveedor,
            command.identificador_recepcion,
            command.canal_id,
            command.cliente_id,
            command.comercio_id,
        )
        if receipt_id is None:
            # A committed receipt for the same pair already exists;
            # the winner's transaction holds it. Roll back our own
            # still-open transaction and return ``already_processed``.
            self._session.rollback()
            return self._already_processed(command, "duplicate_receipt")

        # 4. Active conversation session acquisition or staged
        # creation; staged without flush so the partial unique index
        # is checked only at the surrounding commit.
        session_row = self._session_repo.stage_active(
            command.comercio_id, command.cliente_id
        )

        # 5. Existing non-transactional message pipeline. Failures
        # propagate to the outer ``except`` which rolls back the
        # entire transaction (including the receipt claim).
        intents = process_incoming_message(
            self._session, session_row, command.mensaje
        )

        # 6. Stage durable outbound rows inside the same transaction
        # so the receipt, session, pipeline effects and the
        # provider-message outbox are atomic. The mapper is the only
        # place that renders the customer responses; the coordinator
        # never inspects the rendered text or the row payloads.
        stage_outbound_rows(
            self._session,
            session_row,
            proveedor=command.proveedor,
            recepcion_mensaje_proveedor_id=receipt_id,
            destinatario_e164=command.destinatario_e164,
            intents=tuple(intents),
            outbox_repo=self._outbox_repo,
        )

        # 7. Single commit, only after every staging succeeded.
        self._session.commit()

        receipt_row = self._recepcion_repo.find_by_proveedor_y_recepcion(
            command.proveedor, command.identificador_recepcion
        )
        receipt_id: int | None = (
            int(receipt_row.id) if receipt_row is not None else None
        )
        session_id: int | None = (
            int(getattr(session_row, "id", 0)) or None
        )

        return ProviderInboundMessageOutcome(
            status=ProviderInboundMessageStatus.PROCESSED,
            canal_id=command.canal_id,
            cliente_id=command.cliente_id,
            comercio_id=command.comercio_id,
            proveedor=command.proveedor,
            identificador_recepcion=command.identificador_recepcion,
            receipt_id=receipt_id,
            session_id=session_id,
            processed_intents=tuple(intents),
            resolution_source="first_processing",
        )

    def _is_cliente_activo(self, cliente_id: int) -> bool:
        from backend.models import Cliente

        cliente = self._session.get(Cliente, cliente_id)
        if cliente is None:
            return False
        return bool(cliente.activo)

    def _is_comercio_activo(self, comercio_id: int) -> bool:
        from backend.models import Comercio, EstadoComercio

        comercio = self._session.get(Comercio, comercio_id)
        if comercio is None:
            return False
        estado = self._session.get(EstadoComercio, comercio.estado_id)
        if estado is None:
            return False
        return bool(estado.estado == "ACTIVO")

    def _invalid(
        self,
        command: ProviderInboundMessageCommand,
        source: str,
    ) -> ProviderInboundMessageOutcome:
        return ProviderInboundMessageOutcome(
            status=ProviderInboundMessageStatus.INVALID_CONTEXT,
            canal_id=command.canal_id,
            cliente_id=command.cliente_id,
            comercio_id=command.comercio_id,
            proveedor=command.proveedor,
            identificador_recepcion=command.identificador_recepcion,
            receipt_id=None,
            session_id=None,
            processed_intents=(),
            resolution_source=source,
        )

    def _already_processed(
        self,
        command: ProviderInboundMessageCommand,
        source: str,
    ) -> ProviderInboundMessageOutcome:
        return ProviderInboundMessageOutcome(
            status=ProviderInboundMessageStatus.ALREADY_PROCESSED,
            canal_id=command.canal_id,
            cliente_id=command.cliente_id,
            comercio_id=command.comercio_id,
            proveedor=command.proveedor,
            identificador_recepcion=command.identificador_recepcion,
            receipt_id=None,
            session_id=None,
            processed_intents=(),
            resolution_source=source,
        )


__all__ = [
    "ProviderInboundMessageCommand",
    "ProviderInboundMessageCoordinator",
    "ProviderInboundMessageOutcome",
    "ProviderInboundMessageStatus",
]
