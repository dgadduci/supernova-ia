"""Result type for `PedidoProductoService.modify_product`.

`ModificationResult` is the structured return value of the atomic mutation. The
service never commits, rolls back, flushes, refreshes, expires, or begins a
new transaction — the caller owns the transactional boundary. The result
captures both successful executions (with display names, quantities, and
consolidation flags) and rejected outcomes (with a deterministic `reason`
that the handler and response builder translate into Spanish messages).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModificationResult:
    status: str
    reason: str | None = None
    producto_origen_nombre: str | None = None
    presentacion_origen: str | None = None
    producto_destino_nombre: str | None = None
    presentacion_destino: str | None = None
    cantidad_modificada: int | None = None
    cantidad_origen_restante: int | None = None
    cantidad_destino_final: int | None = None
    origen_eliminado: bool | None = None
    destino_creado: bool | None = None
    cantidad_actual: int | None = None
    cantidad_destino_modificada: int | None = None


__all__ = ["ModificationResult"]
