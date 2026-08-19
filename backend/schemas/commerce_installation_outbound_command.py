"""Canonical Pydantic contracts for the outbound command of the
commerce-isolated Twilio edge.

The contracts in this module are the mirror of the inbound event
contract declared in
:mod:`backend.schemas.commerce_installation_event`. They are split
into a dedicated module so the bounded CLI, the helper service and
the T-C adapter can import the outbound contract without dragging
the inbound contract into their own modules.

The contracts:

* pin the installation identity to the opaque ``instalacion_id``;
* re-declare the comercio id as an untrusted hint (re-resolved on
  the receiving side);
* use ``extra="forbid"`` so any operator field can never reach the
  T-C adapter by accident;
* never carry raw Twilio field names;
* the response contract is closed: ``status`` is restricted to the
  documented set ``{"sent", "retryable", "terminal"}`` and a
  ``"sent"`` response MUST carry a non-empty ``message_sid``. An
  invalid response is treated as an ambiguous result by the helper.

The Pydantic models are independent of SQLAlchemy. The bounded
``OutboundCommandDispatcher`` helper serializes the command with
``model_dump_json`` so the HMAC signature is computed over the exact
bytes the T-C adapter receives.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CanonicalOutboundCommand(BaseModel):
    """Canonical outbound command sent by NovaOrders to the T-C adapter.

    The T-C adapter performs exactly one ``Client.messages.create``
    call when the command is accepted; the bounded CLI already wrote
    the durable ``MensajeProveedorSaliente`` row before this command
    is built. ``idempotency_key`` is unique per outbox row so a
    duplicate command from a parallel dispatcher cannot trigger a
    second send.

    ``status_callback_url`` is optional: when the operator does not
    configure ``TWILIO_CALLBACK_STATUS_URL`` the helper forwards
    ``None`` and the T-C adapter omits the kwarg from
    ``messages.create`` so the canonical contract never carries a
    placeholder URL.
    """

    model_config = ConfigDict(extra="forbid")

    instalacion_id: str = Field(
        min_length=24,
        max_length=24,
        pattern=r"^[a-z0-9]{24}$",
    )
    comercio_id: int = Field(gt=0)
    idempotency_key: str = Field(min_length=1, max_length=128)
    destinatario_e164: str = Field(min_length=1, max_length=32)
    cuerpo: str = Field(min_length=1)
    status_callback_url: str | None = Field(
        default=None,
        max_length=512,
    )
    proveedor: str = Field(min_length=1, max_length=32)


class CanonicalOutboundResponse(BaseModel):
    """Typed response sent back by the T-C adapter to NovaOrders.

    The contract is closed and documented:

    * ``status`` is restricted to the documented set
      ``{"sent", "retryable", "terminal"}``;
    * ``message_sid`` MUST be a non-empty string whenever
      ``status == "sent"`` and MUST be ``None`` otherwise;
    * any extra field is rejected by the ``extra="forbid"`` policy.

    An invalid response — unknown ``status``, missing
    ``message_sid`` on ``"sent"``, extra fields, malformed body —
    is treated as an ambiguous result by the bounded helper. The
    helper raises :class:`OutboundCommandAmbiguous` so the bounded
    CLI finalizes the central outbox row as ``retryable`` while the
    durable claim row stays ``in_progress`` for recovery. The helper
    NEVER finalizes the durable claim with an invalid state and
    NEVER fires a second ``messages.create`` call after an invalid
    response.

    The bounded CLI reads ``status`` and updates the existing outbox
    row through the existing repository. ``message_sid`` is the SID
    returned by the merchant Twilio API; the bounded CLI persists it
    on the ``MensajeProveedorSaliente.identificador_proveedor``
    column exactly like the central dispatcher does today.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["sent", "retryable", "terminal"]
    message_sid: str | None = Field(default=None, max_length=128)
    code: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def _validate_sent_requires_message_sid(self) -> CanonicalOutboundResponse:
        """Ensure ``"sent"`` responses carry a non-empty ``message_sid``.

        The validator rejects ``"sent"`` with a ``None`` /
        empty ``message_sid`` so the bounded helper can raise
        :class:`OutboundCommandAmbiguous` on the receiving side. Any
        other ``status`` value MUST carry a ``None`` ``message_sid``
        so the durable claim row never carries a stale SID on a
        ``retryable`` / ``terminal`` outcome.
        """
        if self.status == "sent":
            sid = self.message_sid
            if not isinstance(sid, str) or not sid.strip():
                raise ValueError(
                    "CanonicalOutboundResponse.status='sent' requires "
                    "a non-empty message_sid"
                )
            self.message_sid = sid.strip()
        else:
            self.message_sid = None
        return self


__all__ = [
    "CanonicalOutboundCommand",
    "CanonicalOutboundResponse",
]
