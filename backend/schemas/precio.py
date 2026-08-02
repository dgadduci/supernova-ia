from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PrecioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    precio: Decimal = Field(ge=Decimal("0"), max_digits=12, decimal_places=2)


class PrecioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    id_producto_presentacion: int
    precio: Decimal
    fecha_alta: datetime
