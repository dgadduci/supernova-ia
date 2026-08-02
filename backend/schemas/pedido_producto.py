from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PedidoProductoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_producto_presentacion: int
    cantidad: int = Field(ge=1)
    observaciones: str | None = None


class PedidoProductoUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cantidad: int | None = Field(default=None, ge=1)
    observaciones: str | None = None


class PedidoProductoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    id_pedido: int
    id_producto_presentacion: int
    cantidad: int
    precio_unitario: Decimal
    observaciones: str | None
    created_at: datetime
    updated_at: datetime