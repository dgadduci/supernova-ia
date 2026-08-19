"""Canonical Pydantic contracts for the commerce-isolated Twilio edge.

The two contracts are the single source of truth for the bridge between
the T-C adapter and NovaOrders:

* ``CanonicalInboundEvent`` — sent by the T-C adapter to
  ``POST /internal/commerce-installation/{instalacion_id}/accept-event``.
* ``CanonicalOutboundCommand`` — sent by NovaOrders to the T-C adapter
  ``POST /internal/commands/send-message``.

The outbound contract lives in
:mod:`backend.schemas.commerce_installation_outbound_command` so the
inbound module stays focused on the single Twilio-side contract.

Both contracts:

* use ``extra="forbid"`` so any Twilio-only field can never reach
  NovaOrders by accident and so any extra operator field can never
  reach the T-C adapter by accident;
* pin the installation identity to the opaque ``instalacion_id``;
* re-declare the comercio id as an untrusted hint (re-resolved on the
  receiving side);
* never carry raw Twilio field names beyond the canonical
  ``message_sid`` (formerly ``MessageSid``) and the four normalized
  fields.

The Pydantic models are independent of SQLAlchemy. The bounded
internal ingress dependency accepts raw JSON bytes so it can verify
the HMAC signature over the exact bytes Twilio's adapter signed.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CanonicalInboundEvent(BaseModel):
    """Canonical inbound event forwarded by the T-C adapter.

    The four required Twilio fields are mapped to the canonical names
    used by the NovaOrders core. Optional bounded metadata is allowed
    but its keys are explicitly enumerated so the contract shape is
    stable.
    """

    model_config = ConfigDict(extra="forbid")

    instalacion_id: str = Field(
        min_length=24,
        max_length=24,
        pattern=r"^[a-z0-9]{24}$",
    )
    comercio_id: int = Field(gt=0)
    proveedor: str = Field(min_length=1, max_length=32)
    message_sid: str = Field(min_length=1, max_length=128)
    from_e164: str = Field(min_length=1, max_length=32)
    to_e164: str = Field(min_length=1, max_length=32)
    cuerpo: str = Field(min_length=1)
    profile_name_hash: str | None = Field(
        default=None,
        max_length=64,
    )
    num_media: int = Field(default=0, ge=0)
    metadata: dict[str, Any] | None = None


class CanonicalInboundAcceptResponse(BaseModel):
    """Typed response sent back to the T-C adapter.

    The adapter branches on ``status`` and returns the empty TwiML only
    when ``status`` is ``"accepted"`` or ``"duplicate"``. A
    ``"rejected"`` response also yields the empty TwiML because the
    event was durably classified as a no-op for that commerce.
    """

    model_config = ConfigDict(extra="forbid")

    status: str = Field(min_length=1, max_length=32)
    receipt_id: int | None = None
    reason: str | None = Field(default=None, max_length=64)


__all__ = [
    "CanonicalInboundAcceptResponse",
    "CanonicalInboundEvent",
]
