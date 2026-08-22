"""Phase-7.4 provider-neutral inbound-message boundary.

The coordinator is the sole transaction owner for the provider-message
receipt + deferred work boundary. It performs three narrow
responsibilities:

1. ``accept`` — webhook acceptance path. Validates the same active
   client/channel/commerce authority as the previous Phase-5.4
   coordinator, conflict-safe claims the receipt via PostgreSQL
   ``INSERT ... ON CONFLICT DO NOTHING RETURNING``, stages exactly one
   pending deferred work item containing the inbound body, and commits
   once. A duplicate committed receipt returns ``already_processed``
   and never re-stages a work item; an invalid context returns
   ``invalid_context`` and never persists anything. The acceptance
   path MUST NOT import or invoke the classifier, recognizer, session
   staging, message pipeline, response mapper or outbound mapper.
2. ``claim_due_processing`` — operator CLI claim path. Selects one
   due work row with ``FOR UPDATE SKIP LOCKED``, emits a fresh lease
   token and commits the claim so the lease is durable before any
   business work begins.
3. ``process_lease`` — operator CLI processing path. Loads the leased
   work item, reuses the existing receipt's authoritative
   commerce/cliente/channel ids, runs the existing
   ``process_incoming_message`` pipeline on the stored body, stages
   outbound rows referencing the existing receipt and commits
   session/pedido/pipeline/outbox effects together with the terminal
   work finalization. A technical failure rolls back the business
   effects and finalizes the work as ``retryable`` or
   ``failed_terminal`` according to the bounded attempt budget.

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
"""
from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session as SqlSession

from backend.intents.orchestration.incoming_message_orchestrator import (
    process_incoming_message,
)
from backend.llm.query_llm import (
    WorkItemLLMTimingRecorder,
    install_llm_timing_recorder,
)
from backend.models import CanalWhatsappMode
from backend.models.cliente import Cliente
from backend.models.procesamiento_mensaje_proveedor import (
    ProcesamientoMensajeProveedor,
    ProcesamientoMensajeProveedorFailureCategory,
)
from backend.repositories.canal_whatsapp_repository import (
    CanalWhatsappRepository,
)
from backend.repositories.cliente_repository import ClienteRepository
from backend.repositories.comercio_canal_compartido_repository import (
    ComercioCanalCompartidoRepository,
)
from backend.repositories.contexto_cliente_canal_whatsapp_repository import (
    ContextoClienteCanalWhatsappRepository,
)
from backend.repositories.mensaje_proveedor_saliente_repository import (
    MensajeProveedorSalienteRepository,
)
from backend.repositories.pedido_repository import PedidoRepository
from backend.repositories.procesamiento_mensaje_proveedor_repository import (
    ProcesamientoMensajeProveedorRepository,
)
from backend.repositories.recepcion_mensaje_proveedor_repository import (
    RecepcionMensajeProveedorRepository,
)
from backend.repositories.session_repository import SessionRepository
from backend.services.commerce_availability_service import (
    CommerceAvailabilityService,
    CommerceAvailabilityStatus,
)
from backend.services.exceptions import (
    InvalidProviderInboundMessageCommand,
)
from backend.services.outbound_response_mapper import (
    stage_outbound_rows,
)

logger = logging.getLogger(__name__)


class ProviderInboundMessageStatus(str, enum.Enum):
    """Typed outcomes returned by the acceptance boundary.

    Every value maps to a single non-resolved or resolved state. The
    coordinator never raises a business-outcome signal; callers
    branch on ``outcome.status`` after a single ``accept`` call.
    """

    ACCEPTED = "accepted"
    ALREADY_PROCESSED = "already_processed"
    INVALID_CONTEXT = "invalid_context"


class ProviderInboundProcessingOutcome(str, enum.Enum):
    """Typed outcomes returned by ``process_lease``.

    Every value maps to a single non-resolved or resolved state. The
    coordinator never raises a business-outcome signal; callers
    branch on ``outcome`` after a single ``process_lease`` call.
    """

    PROCESSED = "processed"
    RETRY_SCHEDULED = "retry_scheduled"
    FAILED_TERMINAL = "failed_terminal"


DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_INITIAL_BACKOFF_SECONDS = 30
DEFAULT_MAX_BACKOFF_SECONDS = 300
DEFAULT_LEASE_SECONDS = 60


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
class ProviderInboundAcceptanceOutcome:
    """Immutable Phase-7.4 acceptance outcome.

    ``status`` is the single source of truth for branching. Every
    other field is only meaningful for the matching successful
    outcome; non-success outcomes leave id-bearing fields as
    ``None``. Raw inbound text is never copied onto the outcome so
    observability surfaces cannot leak provider payload bytes.
    """

    status: ProviderInboundMessageStatus
    canal_id: int
    cliente_id: int
    comercio_id: int
    proveedor: str
    identificador_recepcion: str
    receipt_id: int | None
    procesamiento_id: int | None
    resolution_source: str


@dataclass(frozen=True)
class ProviderInboundProcessingResult:
    """Immutable Phase-7.4 processing outcome.

    ``outcome`` is the single source of truth for branching. The
    transient ``mensaje`` body is never copied onto the result so
    observability surfaces cannot leak provider payload bytes.
    """

    outcome: ProviderInboundProcessingOutcome
    procesamiento_id: int | None
    receipt_id: int | None
    intentos: int | None
    categoria: ProcesamientoMensajeProveedorFailureCategory | None
    codigo: str | None
    detalle: str | None


class ProviderInboundMessageCoordinator:
    """Sole Phase-7.4 transaction owner for provider-message acceptance
    and deferred processing.
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
        procesamiento_repo: (
            ProcesamientoMensajeProveedorRepository | None
        ) = None,
        session_repo: SessionRepository | None = None,
        pedido_repo: PedidoRepository | None = None,
        outbox_repo: MensajeProveedorSalienteRepository | None = None,
        *,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        initial_backoff_seconds: int = DEFAULT_INITIAL_BACKOFF_SECONDS,
        max_backoff_seconds: int = DEFAULT_MAX_BACKOFF_SECONDS,
        now: datetime | None = None,
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
        self._procesamiento_repo = (
            procesamiento_repo
            or ProcesamientoMensajeProveedorRepository(session)
        )
        self._session_repo = session_repo or SessionRepository(session)
        self._pedido_repo = pedido_repo or PedidoRepository(session)
        self._outbox_repo = (
            outbox_repo or MensajeProveedorSalienteRepository(session)
        )
        self._lease_seconds = int(lease_seconds)
        self._max_attempts = int(max_attempts)
        self._initial_backoff_seconds = int(initial_backoff_seconds)
        self._max_backoff_seconds = int(max_backoff_seconds)
        self._now = now

    def accept(
        self, command: ProviderInboundMessageCommand
    ) -> ProviderInboundAcceptanceOutcome:
        """Validate the routing decision, claim the receipt and stage
        exactly one pending work item. Commits once.

        Acceptance owns the unique short transaction that proves the
        webhook acknowledgement: it never invokes the classifier,
        recognizer, session/pedido staging, message pipeline, response
        mapper or outbound mapper. A duplicate committed receipt
        rolls back the still-open coordinator transaction and returns
        ``already_processed`` without staging a second work item.
        """
        try:
            return self._accept_locked(command)
        except InvalidProviderInboundMessageCommand:
            raise
        except Exception:
            self._session.rollback()
            raise

    def claim_due_processing(
        self, *, now: datetime | None = None
    ) -> ProcesamientoMensajeProveedor | None:
        """Claim exactly one due work item and commit the lease.

        The caller is responsible for invoking ``process_lease`` on
        the leased row before the lease expires; the bounded attempt
        budget and deterministic backoff guarantee the row can be
        re-claimed after the lease window without manual repair.
        """
        when = now or self._now_or()
        try:
            claimed = self._procesamiento_repo.claim_due(
                now=when, lease_seconds=self._lease_seconds
            )
            self._session.commit()
            return claimed
        except Exception:
            self._session.rollback()
            raise

    def process_lease(
        self,
        leased: ProcesamientoMensajeProveedor,
    ) -> ProviderInboundProcessingResult:
        """Process one leased work item end-to-end and commit once.

        The function loads the receipt + work item, reuses the
        authoritative commerce/cliente/channel ids, runs the
        existing pipeline, stages the outbound rows referencing the
        existing receipt, and finalizes the work in a single commit.
        A technical failure rolls the business effects back and
        finalizes the work as ``retryable`` (when the attempt budget
        remains) or ``failed_terminal`` (when the budget is
        exhausted). The transient body is preserved on retry and
        cleared on terminal exhaustion.
        """
        try:
            return self._process_locked(leased)
        except Exception:
            try:
                self._session.rollback()
            except Exception:
                logger.exception(
                    "twilio_inbound_processor_rollback_failed",
                    extra={"procesamiento_id": int(leased.id)},
                )
            raise

    def _accept_locked(
        self, command: ProviderInboundMessageCommand
    ) -> ProviderInboundAcceptanceOutcome:
        if not self._is_cliente_activo(command.cliente_id):
            return self._invalid(command, "client_lookup")

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
                return self._invalid(command, "pending_only_target")
            if int(selected) != command.comercio_id:
                return self._invalid(command, "selected_authority_mismatch")
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

        receipt_id = self._recepcion_repo.claim(
            command.proveedor,
            command.identificador_recepcion,
            command.canal_id,
            command.cliente_id,
            command.comercio_id,
        )
        if receipt_id is None:
            self._session.rollback()
            return self._already_processed(command, "duplicate_receipt")

        work_row = self._procesamiento_repo.stage(
            recepcion_mensaje_proveedor_id=receipt_id,
            mensaje=command.mensaje,
        )
        self._session.flush()

        self._session.commit()

        return ProviderInboundAcceptanceOutcome(
            status=ProviderInboundMessageStatus.ACCEPTED,
            canal_id=command.canal_id,
            cliente_id=command.cliente_id,
            comercio_id=command.comercio_id,
            proveedor=command.proveedor,
            identificador_recepcion=command.identificador_recepcion,
            receipt_id=receipt_id,
            procesamiento_id=int(work_row.id or 0) or None,
            resolution_source="first_processing",
        )

    def _process_locked(
        self,
        leased: ProcesamientoMensajeProveedor,
    ) -> ProviderInboundProcessingResult:
        lease_token = str(leased.token_lease or "")
        if not lease_token:
            raise RuntimeError(
                "process_lease requires a leased work item"
            )
        procesamiento_id = int(leased.id)
        attempts = int(leased.intentos)
        body = leased.mensaje
        if body is None:
            raise RuntimeError(
                "process_lease requires a work item with the transient body"
            )

        receipt = self._recepcion_repo.find_by_id(
            int(leased.recepcion_mensaje_proveedor_id)
        )
        if receipt is None:
            self._finalize_terminal(
                leased=leased,
                categoria=ProcesamientoMensajeProveedorFailureCategory.DATABASE_ERROR,
                codigo="receipt_missing",
            )
            return ProviderInboundProcessingResult(
                outcome=ProviderInboundProcessingOutcome.FAILED_TERMINAL,
                procesamiento_id=procesamiento_id,
                receipt_id=None,
                intentos=attempts,
                categoria=ProcesamientoMensajeProveedorFailureCategory.DATABASE_ERROR,
                codigo="receipt_missing",
                detalle="receipt_missing",
            )

        cliente_id = int(receipt.cliente_id)
        comercio_id = int(receipt.comercio_id)
        proveedor = str(receipt.proveedor)
        destinatario_e164 = self._destinatario_from_receipt(receipt)

        try:
            availability = CommerceAvailabilityService(
                self._session
            ).evaluate(comercio_id)
        except Exception as exc:  # noqa: BLE001 - coordinator owns the rollback
            try:
                self._session.rollback()
            except Exception:
                logger.exception(
                    "twilio_inbound_processor_availability_rollback_failed",
                    extra={"procesamiento_id": procesamiento_id},
                )
            return self._finalize_failure(
                leased=leased,
                attempts=attempts,
                exc=exc,
            )

        if availability.status is not CommerceAvailabilityStatus.AVAILABLE:
            reason = (
                availability.reason.value
                if availability.reason is not None
                else "blocked_state"
            )
            codigo = f"unavailable_{reason}"
            self._finalize_terminal(
                leased=leased,
                categoria=ProcesamientoMensajeProveedorFailureCategory.TERMINAL_PROCESSOR_ERROR,
                codigo=codigo,
            )
            return ProviderInboundProcessingResult(
                outcome=ProviderInboundProcessingOutcome.FAILED_TERMINAL,
                procesamiento_id=procesamiento_id,
                receipt_id=int(receipt.id),
                intentos=attempts,
                categoria=ProcesamientoMensajeProveedorFailureCategory.TERMINAL_PROCESSOR_ERROR,
                codigo=codigo,
                detalle=codigo,
            )

        # Install the safe LLM timing recorder around the existing
        # ``process_incoming_message`` call so the provider-path work
        # item captures the moment the worker reaches the
        # ``QueryLlm`` boundary and the moment the call finishes,
        # without introducing a side transaction and without
        # changing the LLM behaviour. The recorder is cleared in
        # every exit branch (success, retryable, terminal and any
        # unexpected exception) so other concurrent coordinators
        # never inherit the hook through the worker threads. The
        # existing safe correlation field — the receipt's
        # ``identificador_recepcion`` — is attached to every
        # ``llm_request`` event emitted from the same thread so the
        # provider-path observability can be linked back to the
        # exact synthetic inbound identifier without leaking
        # prompts, responses, PII or secrets.
        timing_recorder = WorkItemLLMTimingRecorder()
        install_llm_timing_recorder(
            timing_recorder,
            correlation_id=str(receipt.identificador_recepcion or ""),
        )
        try:
            session_row = self._session_repo.stage_active(
                comercio_id, cliente_id
            )
            if session_row.id_pedido is None:
                if session_row.id is None:
                    self._session.flush()
                pedido_row = self._pedido_repo.stage_draft_for_session(
                    int(session_row.id)
                )
                self._session.flush()
                session_row.id_pedido = int(pedido_row.id)
            self._session.flush()

            intents = process_incoming_message(
                self._session, session_row, body
            )

            stage_outbound_rows(
                self._session,
                session_row,
                proveedor=proveedor,
                recepcion_mensaje_proveedor_id=int(receipt.id),
                destinatario_e164=destinatario_e164,
                intents=tuple(intents),
                outbox_repo=self._outbox_repo,
            )
            self._session.flush()
        except Exception as exc:  # noqa: BLE001 - coordinator owns the rollback
            install_llm_timing_recorder(None)
            try:
                self._session.rollback()
            except Exception:
                logger.exception(
                    "twilio_inbound_processor_business_rollback_failed",
                    extra={"procesamiento_id": procesamiento_id},
                )
            return self._finalize_failure(
                leased=leased,
                attempts=attempts,
                exc=exc,
                llm_solicitado_en=timing_recorder.solicitado_en,
                llm_finalizado_en=timing_recorder.finalizado_en,
                llm_resultado=timing_recorder.resultado,
            )
        install_llm_timing_recorder(None)

        finalized = self._procesamiento_repo.finalize_processed(
            procesamiento_id=procesamiento_id,
            lease_token=lease_token,
            fecha_finalizacion=self._now_or(),
            llm_solicitado_en=timing_recorder.solicitado_en,
            llm_finalizado_en=timing_recorder.finalizado_en,
            llm_resultado=timing_recorder.resultado,
        )
        if not finalized:
            self._session.rollback()
            return ProviderInboundProcessingResult(
                outcome=ProviderInboundProcessingOutcome.RETRY_SCHEDULED,
                procesamiento_id=procesamiento_id,
                receipt_id=int(receipt.id),
                intentos=attempts,
                categoria=None,
                codigo=None,
                detalle="lease_lost",
            )
        self._session.commit()
        return ProviderInboundProcessingResult(
            outcome=ProviderInboundProcessingOutcome.PROCESSED,
            procesamiento_id=procesamiento_id,
            receipt_id=int(receipt.id),
            intentos=attempts,
            categoria=None,
            codigo=None,
            detalle=None,
        )

    def _finalize_failure(
        self,
        *,
        leased: ProcesamientoMensajeProveedor,
        attempts: int,
        exc: BaseException,
        llm_solicitado_en: datetime | None = None,
        llm_finalizado_en: datetime | None = None,
        llm_resultado: str | None = None,
    ) -> ProviderInboundProcessingResult:
        categoria, codigo = _classify_failure(exc)
        lease_token = str(leased.token_lease or "")
        procesamiento_id = int(leased.id)
        fecha_finalizacion = self._now_or()

        if attempts >= self._max_attempts:
            finalized = self._procesamiento_repo.finalize_terminal(
                procesamiento_id=procesamiento_id,
                lease_token=lease_token,
                categoria=categoria.value,
                codigo=codigo,
                fecha_finalizacion=fecha_finalizacion,
                llm_solicitado_en=llm_solicitado_en,
                llm_finalizado_en=llm_finalizado_en,
                llm_resultado=llm_resultado,
            )
            if not finalized:
                self._session.rollback()
                return ProviderInboundProcessingResult(
                    outcome=ProviderInboundProcessingOutcome.RETRY_SCHEDULED,
                    procesamiento_id=procesamiento_id,
                    receipt_id=int(
                        leased.recepcion_mensaje_proveedor_id
                    ),
                    intentos=attempts,
                    categoria=categoria,
                    codigo=codigo,
                    detalle="lease_lost",
                )
            self._session.commit()
            return ProviderInboundProcessingResult(
                outcome=ProviderInboundProcessingOutcome.FAILED_TERMINAL,
                procesamiento_id=procesamiento_id,
                receipt_id=int(
                    leased.recepcion_mensaje_proveedor_id
                ),
                intentos=attempts,
                categoria=categoria,
                codigo=codigo,
                detalle="budget_exhausted",
            )

        proximo_intento_en = _compute_next_attempt_at(
            now=fecha_finalizacion,
            attempts=attempts,
            initial_seconds=self._initial_backoff_seconds,
            max_seconds=self._max_backoff_seconds,
        )
        finalized = self._procesamiento_repo.finalize_retryable(
            procesamiento_id=procesamiento_id,
            lease_token=lease_token,
            categoria=categoria.value,
            codigo=codigo,
            proximo_intento_en=proximo_intento_en,
            llm_solicitado_en=llm_solicitado_en,
            llm_finalizado_en=llm_finalizado_en,
            llm_resultado=llm_resultado,
        )
        if not finalized:
            self._session.rollback()
            return ProviderInboundProcessingResult(
                outcome=ProviderInboundProcessingOutcome.RETRY_SCHEDULED,
                procesamiento_id=procesamiento_id,
                receipt_id=int(
                    leased.recepcion_mensaje_proveedor_id
                ),
                intentos=attempts,
                categoria=categoria,
                codigo=codigo,
                detalle="lease_lost",
            )
        self._session.commit()
        return ProviderInboundProcessingResult(
            outcome=ProviderInboundProcessingOutcome.RETRY_SCHEDULED,
            procesamiento_id=procesamiento_id,
            receipt_id=int(leased.recepcion_mensaje_proveedor_id),
            intentos=attempts,
            categoria=categoria,
            codigo=codigo,
            detalle=None,
        )

    def _finalize_terminal(
        self,
        *,
        leased: ProcesamientoMensajeProveedor,
        categoria: ProcesamientoMensajeProveedorFailureCategory,
        codigo: str,
        llm_solicitado_en: datetime | None = None,
        llm_finalizado_en: datetime | None = None,
        llm_resultado: str | None = None,
    ) -> bool:
        finalized = self._procesamiento_repo.finalize_terminal(
            procesamiento_id=int(leased.id),
            lease_token=str(leased.token_lease or ""),
            categoria=categoria.value,
            codigo=codigo,
            fecha_finalizacion=self._now_or(),
            llm_solicitado_en=llm_solicitado_en,
            llm_finalizado_en=llm_finalizado_en,
            llm_resultado=llm_resultado,
        )
        if finalized:
            self._session.commit()
            return True
        self._session.rollback()
        return False

    def _destinatario_from_receipt(self, receipt: Any) -> str:
        cliente = self._session.get(Cliente, int(receipt.cliente_id))
        if cliente is None:
            return self._destinatario_fallback(receipt)
        return self._canonicalize_destinatario(cliente.whatsapp)

    def _destinatario_fallback(self, receipt: Any) -> str:
        cliente = ClienteRepository(self._session).get_by_id(
            int(receipt.cliente_id)
        )
        if cliente is None:
            raise RuntimeError(
                "cliente missing for receipt during inbound processing"
            )
        return self._canonicalize_destinatario(cliente.whatsapp)

    @staticmethod
    def _canonicalize_destinatario(raw: str) -> str:
        from backend.services.cliente_service import InvalidWhatsApp, normalize_whatsapp

        try:
            return normalize_whatsapp(str(raw))
        except InvalidWhatsApp:
            return str(raw).strip()

    def _is_cliente_activo(self, cliente_id: int) -> bool:
        cliente = self._session.get(Cliente, cliente_id)
        if cliente is None:
            return False
        return bool(cliente.activo)

    def _is_comercio_activo(self, comercio_id: int) -> bool:
        outcome = CommerceAvailabilityService(
            self._session
        ).evaluate(comercio_id)
        return outcome.status is CommerceAvailabilityStatus.AVAILABLE

    def _invalid(
        self,
        command: ProviderInboundMessageCommand,
        source: str,
    ) -> ProviderInboundAcceptanceOutcome:
        return ProviderInboundAcceptanceOutcome(
            status=ProviderInboundMessageStatus.INVALID_CONTEXT,
            canal_id=command.canal_id,
            cliente_id=command.cliente_id,
            comercio_id=command.comercio_id,
            proveedor=command.proveedor,
            identificador_recepcion=command.identificador_recepcion,
            receipt_id=None,
            procesamiento_id=None,
            resolution_source=source,
        )

    def _already_processed(
        self,
        command: ProviderInboundMessageCommand,
        source: str,
    ) -> ProviderInboundAcceptanceOutcome:
        return ProviderInboundAcceptanceOutcome(
            status=ProviderInboundMessageStatus.ALREADY_PROCESSED,
            canal_id=command.canal_id,
            cliente_id=command.cliente_id,
            comercio_id=command.comercio_id,
            proveedor=command.proveedor,
            identificador_recepcion=command.identificador_recepcion,
            receipt_id=None,
            procesamiento_id=None,
            resolution_source=source,
        )

    def _now_or(self) -> datetime:
        if self._now is not None:
            return self._now
        return datetime.now(tz=_utc())


def _utc():
    from datetime import timezone

    return timezone.utc


def _classify_failure(
    exc: BaseException,
) -> tuple[ProcesamientoMensajeProveedorFailureCategory, str]:
    """Translate a processing exception into a safe category/code.

    The transient body, raw exception message, provider signature and
    inbound text NEVER appear in the stored category/code. The
    classification is intentionally coarse so the row remains safe to
    log.
    """
    name = type(exc).__name__
    if isinstance(exc, RuntimeError) and name == "RuntimeError":
        return (
            ProcesamientoMensajeProveedorFailureCategory.PIPELINE_ERROR,
            "pipeline_error",
        )
    return (
        ProcesamientoMensajeProveedorFailureCategory.DATABASE_ERROR,
        "processor_error",
    )


def _compute_next_attempt_at(
    *,
    now: datetime,
    attempts: int,
    initial_seconds: int,
    max_seconds: int,
) -> datetime:
    safe_initial = max(1, int(initial_seconds))
    safe_max = max(safe_initial, int(max_seconds))
    delay = safe_initial * max(1, int(attempts))
    delay = min(delay, safe_max)
    from datetime import timedelta

    return now + timedelta(seconds=int(delay))


__all__ = [
    "DEFAULT_INITIAL_BACKOFF_SECONDS",
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_MAX_BACKOFF_SECONDS",
    "ProviderInboundAcceptanceOutcome",
    "ProviderInboundMessageCommand",
    "ProviderInboundMessageCoordinator",
    "ProviderInboundMessageStatus",
    "ProviderInboundProcessingOutcome",
    "ProviderInboundProcessingResult",
]