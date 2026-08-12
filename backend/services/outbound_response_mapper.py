"""Phase-5.6 reusable response mapper.

The mapper is the reusable translation boundary between the Phase-5.4
coordinator pipeline and the durable outbound-message outbox. It
performs three narrow responsibilities:

1. ``build_customer_responses`` — translates processed intents into
   rendered ``CustomerResponse`` values using the existing
   ``agregar`` / ``quitar`` / ``modificar`` builders, the four
   guided-closure builders (``consultar_resumen_pedido``,
   ``set_metodo_de_pago``, ``set_metodo_de_entrega``,
   ``confirmar_pedido``), the ``iniciar_pedido`` builder, the
   ``vaciar_pedido`` builder, and the generic fallback message.
2. ``stage_outbound_rows`` — renders the same responses and stages
   one durable outbox row per response inside the caller's
   transaction.
3. ``GENERIC_MESSAGE`` — the constant used by both the local
   endpoint and the outbox when the response builder does not
   recognize the intent.

The mapper is invoked from the Phase-5.4 coordinator only. The
local HTTP endpoint continues to use
``process_incoming_message_with_responses`` directly so its JSON
response payload and ordering remain equivalent. The mapper never
imports HTTP, FastAPI, the Twilio SDK, the coordinator, the resolver
or the dispatch service. The mapper never invokes any SQLAlchemy
transaction-control method directly: the staging path delegates the
actual ``MensajeProveedorSaliente`` row insertion to the repository
so the repository remains the sole database-boundary knowledge.
"""
from __future__ import annotations

from collections.abc import Sequence as SequenceABC
from dataclasses import dataclass

from sqlalchemy.orm import Session as DatabaseSession

from backend.diagnostics.sink import DiagnosticSink
from backend.intents.orchestration.informational_commerce_queries import (
    is_informational_commerce_intent,
)
from backend.intents.responses.agregar_producto_response import (
    build_agregar_producto_response,
)
from backend.intents.responses.consecutive_add_product_coalescer import (
    coalesce_consecutive_add_product_intents,
)
from backend.intents.responses.draft_order_closure import (
    build_confirmar_pedido_response,
    build_consultar_resumen_pedido_response,
    build_set_metodo_de_entrega_response,
    build_set_metodo_de_pago_response,
)
from backend.intents.responses.informational_commerce_queries import (
    build_informational_commerce_response,
)
from backend.intents.responses.modificar_producto_response import (
    build_modificar_producto_response,
)
from backend.intents.responses.new_order_after_confirmation import (
    build_iniciar_pedido_response,
)
from backend.intents.responses.order_status_query import (
    build_order_status_query_response,
)
from backend.intents.responses.quitar_producto_response import (
    build_quitar_producto_response,
)
from backend.intents.responses.social_conversation_response import (
    build_social_conversation_response,
    is_social_conversation_intent,
)
from backend.intents.responses.vaciar_pedido_response import (
    build_vaciar_pedido_response,
)
from backend.intents.schemas.customer_response import CustomerResponse
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession
from backend.repositories.mensaje_proveedor_saliente_repository import (
    MensajeProveedorSalienteRepository,
)
from backend.services.exceptions import InvalidOutboundProviderMessage

GENERIC_MESSAGE = (
    "Disculpá, no pude procesar tu mensaje. ¿Podrías reformularlo?"
)


@dataclass(frozen=True)
class StagedOutboundRow:
    """Immutable staged outbox row preview.

    The coordinator receives one preview per staged row so it can
    observe the durable identity and the rendered text without
    touching the repository again. The preview never exposes the
    raw database row to the coordinator's caller surface.
    """

    mensaje_proveedor_saliente_id: int
    sequence: int
    customer_response: CustomerResponse


def build_customer_responses(
    db: DatabaseSession,
    session: ConversationSession,
    intents: SequenceABC[ProcessedIntent],
    *,
    sink: DiagnosticSink | None = None,
) -> list[CustomerResponse]:
    """Translate processed intents into rendered customer responses.

    The mapper is intentionally pure with respect to the supplied
    arguments. The order of the returned responses matches the
    order of the supplied intents so the local endpoint and the
    outbox both render the same texts in the same order. The
    ``sink`` is reserved for symmetry with the pipeline primitive
    but is unused at this layer.
    """
    del sink
    rendered_intents = coalesce_consecutive_add_product_intents(intents)
    responses: list[CustomerResponse] = []
    for intent in rendered_intents:
        if intent.intent == "agregar_producto":
            responses.append(
                build_agregar_producto_response(db, session, intent)
            )
        elif intent.intent == "quitar_producto":
            responses.append(
                build_quitar_producto_response(db, session, intent)
            )
        elif intent.intent == "modificar_producto":
            responses.append(
                build_modificar_producto_response(db, session, intent)
            )
        elif intent.intent == "consultar_resumen_pedido":
            responses.append(
                build_consultar_resumen_pedido_response(db, session, intent)
            )
        elif intent.intent == "set_metodo_de_pago":
            responses.append(
                build_set_metodo_de_pago_response(db, session, intent)
            )
        elif intent.intent == "set_metodo_de_entrega":
            responses.append(
                build_set_metodo_de_entrega_response(db, session, intent)
            )
        elif intent.intent == "confirmar_pedido":
            responses.append(
                build_confirmar_pedido_response(db, session, intent)
            )
        elif intent.intent == "consultar_estado_pedido":
            responses.append(
                build_order_status_query_response(db, session, intent)
            )
        elif intent.intent == "iniciar_pedido":
            responses.append(
                build_iniciar_pedido_response(db, session, intent)
            )
        elif intent.intent == "vaciar_pedido":
            responses.append(
                build_vaciar_pedido_response(db, session, intent)
            )
        elif is_informational_commerce_intent(intent.intent):
            responses.append(
                build_informational_commerce_response(db, session, intent)
            )
        elif is_social_conversation_intent(intent.intent):
            responses.append(
                build_social_conversation_response(intent)
            )
        else:
            responses.append(
                CustomerResponse(
                    message=GENERIC_MESSAGE,
                    intent=intent.intent,
                    status=intent.status,
                )
            )
    return responses


def stage_outbound_rows(
    db: DatabaseSession,
    session: ConversationSession,
    *,
    proveedor: str,
    recepcion_mensaje_proveedor_id: int,
    destinatario_e164: str,
    intents: SequenceABC[ProcessedIntent],
    outbox_repo: MensajeProveedorSalienteRepository | None = None,
) -> list[StagedOutboundRow]:
    """Render intents and stage one durable outbox row per response.

    The mapper performs the same ``build_customer_responses`` work
    so the rendered text is identical to the local endpoint's
    response payload, then adds one
    ``MensajeProveedorSaliente`` row per non-empty response in the
    caller's transaction. The repository owns the actual ``add``
    call so the mapper does not couple to the session directly.

    Validation rules:

    * ``proveedor`` is a non-empty stripped string.
    * ``destinatario_e164`` is a non-empty stripped string.
    * ``recepcion_mensaje_proveedor_id`` is a positive integer.
    * ``intents`` is an iterable of ``ProcessedIntent`` (possibly
      empty).

    Any violation raises
    :class:`InvalidOutboundProviderMessage` before the first
    database interaction so the coordinator can roll back its
    staged state on a clean error.
    """
    _validate(
        proveedor=proveedor,
        recepcion_mensaje_proveedor_id=recepcion_mensaje_proveedor_id,
        destinatario_e164=destinatario_e164,
    )

    repo = outbox_repo or MensajeProveedorSalienteRepository(db)
    intent_list = list(intents)
    responses = build_customer_responses(db, session, intent_list)

    staged: list[StagedOutboundRow] = []
    for sequence, response in enumerate(responses):
        row = repo.stage(
            proveedor=proveedor,
            recepcion_mensaje_proveedor_id=recepcion_mensaje_proveedor_id,
            destinatario_e164=destinatario_e164,
            cuerpo=response.message,
            sequence=sequence,
        )
        staged.append(
            StagedOutboundRow(
                mensaje_proveedor_saliente_id=int(row.id or 0) or -1,
                sequence=sequence,
                customer_response=response,
            )
        )
    return staged


def _validate(
    *,
    proveedor: str,
    recepcion_mensaje_proveedor_id: int,
    destinatario_e164: str,
) -> None:
    if (
        not isinstance(proveedor, str)
        or not proveedor.strip()
    ):
        raise InvalidOutboundProviderMessage(
            "proveedor must be a non-empty string"
        )
    if (
        not isinstance(destinatario_e164, str)
        or not destinatario_e164.strip()
    ):
        raise InvalidOutboundProviderMessage(
            "destinatario_e164 must be a non-empty string"
        )
    if (
        not isinstance(recepcion_mensaje_proveedor_id, int)
        or isinstance(recepcion_mensaje_proveedor_id, bool)
        or recepcion_mensaje_proveedor_id <= 0
    ):
        raise InvalidOutboundProviderMessage(
            "recepcion_mensaje_proveedor_id must be a positive integer"
        )


__all__ = [
    "GENERIC_MESSAGE",
    "StagedOutboundRow",
    "build_customer_responses",
    "stage_outbound_rows",
]