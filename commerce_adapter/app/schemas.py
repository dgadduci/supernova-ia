"""Pydantic schemas for the T-C adapter contracts.

The two schemas are the local mirror of the NovaOrders canonical
contracts. The adapter validates the inbound event before signing and
forwards exactly the same field names to NovaOrders; it parses the
NovaOrders response into :class:`NovaOrdersIngressResult` so the
routes can branch on the typed outcome.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CanonicalInboundEvent(BaseModel):
    """Local mirror of the NovaOrders canonical inbound event."""

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
    profile_name_hash: str | None = Field(default=None, max_length=64)
    num_media: int = Field(default=0, ge=0)
    metadata: dict[str, Any] | None = None


class CanonicalOutboundCommand(BaseModel):
    """Local mirror of the canonical outbound command.

    ``status_callback_url`` is optional: when ``None`` the adapter
    omits the kwarg from ``messages.create`` so the canonical
    contract never carries a placeholder URL.
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


class NovaOrdersIngressResult:
    """Typed result of the bounded NovaOrders HTTP forward.

    The routes branch on ``status`` after a single forward. The bounded
    CLI never logs body, phone, token or signature.
    """

    __slots__ = ("http_status", "reason", "receipt_id", "status")

    def __init__(
        self,
        *,
        status: str,
        receipt_id: int | None = None,
        reason: str | None = None,
        http_status: int = 0,
    ) -> None:
        self.status = str(status)
        self.receipt_id = receipt_id
        self.reason = reason
        self.http_status = int(http_status)

    @property
    def is_accepted(self) -> bool:
        return self.status in {"accepted", "duplicate"}


__all__ = [
    "CanonicalInboundEvent",
    "CanonicalOutboundCommand",
    "NovaOrdersIngressResult",
]