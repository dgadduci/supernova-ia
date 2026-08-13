"""Result type for ``PedidoProductoService.stage_add_or_increment_for_session``.

``ProductAddResult`` is the structured return value of the modern
``agregar_producto`` seam used only by the provider flow. The seam
never commits, rolls back, flushes, refreshes, expires, or begins a
new transaction — the caller owns the full-turn transactional
boundary. The result captures both successful executions (with a
boolean ``linea_creada`` flag, the final ``cantidad`` and the
snapshotted ``precio_unitario``) and every documented business
rejection (with a deterministic ``reason`` drawn from the closed
allowlist in the proposal).

The seam never raises a ``PrecioNotFound`` or other legacy sentinel
for ambiguous prices: an exact-zero or exact-many price set is a
deterministic ``rejected_price_unavailable`` business outcome that
the handler translates to the same generic customer response as
every other business rejection. Only unexpected technical failures
are propagated so the provider coordinator can roll back.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

STATUS_EXECUTED = "executed"
STATUS_REJECTED = "rejected"
STATUS_FAILED = "failed"

REJECTED_INVALID_INPUT = "rejected_invalid_input"
REJECTED_SESSION_OR_PEDIDO = "rejected_session_or_pedido"
REJECTED_NOT_EDITABLE = "rejected_not_editable"
REJECTED_MISSING_PRESENTATION = "rejected_missing_presentation"
REJECTED_PRICE_UNAVAILABLE = "rejected_price_unavailable"


@dataclass(frozen=True)
class ProductAddResult:
    status: str
    reason: str | None = None
    linea_creada: bool | None = None
    cantidad_final: int | None = None
    precio_unitario: Decimal | None = None


__all__ = [
    "REJECTED_INVALID_INPUT",
    "REJECTED_MISSING_PRESENTATION",
    "REJECTED_NOT_EDITABLE",
    "REJECTED_PRICE_UNAVAILABLE",
    "REJECTED_SESSION_OR_PEDIDO",
    "STATUS_EXECUTED",
    "STATUS_FAILED",
    "STATUS_REJECTED",
    "ProductAddResult",
]