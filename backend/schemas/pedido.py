from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PedidoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_session: int
    id_medio_pago: int | None = None
    id_metodo_entrega: int | None = None
    datetime_entrega_programada: datetime | None = None


class PedidoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    id_session: int
    id_medio_pago: int | None
    id_metodo_entrega: int | None
    datetime_entrega_programada: datetime | None
    estado_pedido: str
    fecha_alta: datetime
    fecha_ultima_modificacion: datetime


class PedidoDetalleLinea(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    cantidad: int
    producto_nombre: str
    presentacion_descripcion: str


class PedidoDetalleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    id_session: int
    id_medio_pago: int | None
    id_metodo_entrega: int | None
    datetime_entrega_programada: datetime | None
    estado_pedido: str
    fecha_alta: datetime
    fecha_ultima_modificacion: datetime
    lineas: list[PedidoDetalleLinea]


class PedidoMedioPagoUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_medio_pago: int | None = None


class PedidoMetodoEntregaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_metodo_entrega: int | None = None


class PedidoFechaEntregaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    datetime_entrega_programada: datetime | None = None


class PedidoEstadoUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    estado_pedido: str