from datetime import datetime

from pydantic import BaseModel, ConfigDict

from backend.schemas.comunicacion_flavor import FlavorComunicacionSummary


class EstadoComercioDetalleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    estado: str


class MedioPagoDetalleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    descripcion: str
    activo: bool
    fecha_alta: datetime
    fecha_ultima_modificacion: datetime


class ComercioMedioPagoDetalleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    id_comercio: int
    id_medio_pago: int
    activo: bool
    titular: str | None
    alias: str | None
    fecha_alta: datetime
    fecha_ultima_modificacion: datetime
    medio_pago: MedioPagoDetalleResponse


class MetodoEntregaDetalleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    descripcion: str
    orden: int
    activo: bool
    fecha_alta: datetime
    fecha_ultima_modificacion: datetime


class ComercioMetodoEntregaDetalleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    id_comercio: int
    id_metodo_entrega: int
    activo: bool
    orden: int
    fecha_alta: datetime
    fecha_ultima_modificacion: datetime
    metodo_entrega: MetodoEntregaDetalleResponse


class ComercioConfiguracionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre_fantasia: str
    nombre_corto: str
    razon_social: str
    cuit: str
    whatsapp: str
    calle: str
    numero: str
    piso_departamento: str | None
    localidad: str
    provincia: str
    codigo_postal: str | None
    slug: str
    estado_id: int
    zona_horaria: str
    moneda: str
    idioma: str
    fecha_alta: datetime
    fecha_ultima_modificacion: datetime
    fecha_baja: datetime | None
    estado: EstadoComercioDetalleResponse
    medios_pago: list[ComercioMedioPagoDetalleResponse]
    metodos_entrega: list[ComercioMetodoEntregaDetalleResponse]
    flavor_comunicacion: FlavorComunicacionSummary | None
