from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_comercio: int
    id_cliente: int
    id_pedido: int | None = None


class SessionPedidoUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_pedido: int


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    id_comercio: int
    id_cliente: int
    id_pedido: int | None
    datetime_inicio: datetime
    datetime_ultimo_movimiento: datetime
    estado_session: str