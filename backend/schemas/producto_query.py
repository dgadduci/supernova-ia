from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from backend.schemas.categoria_producto import CategoriaProductoResponse
from backend.schemas.precio import PrecioResponse
from backend.schemas.presentacion import PresentacionResponse


class ProductoPresentacionDetalleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    id_producto: int
    id_presentacion: int
    activo: bool
    orden: int
    fecha_alta: datetime
    fecha_ultima_modificacion: datetime
    presentacion: PresentacionResponse
    precios: list = []


ProductoPresentacionDetalleResponse.model_rebuild()


class ProductoDetalleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    id_categoria_producto: int
    nombre: str
    descripcion: str | None
    activo: bool
    disponible: bool
    orden: int
    fecha_alta: datetime
    fecha_ultima_modificacion: datetime
    categoria: CategoriaProductoResponse
    id_comercio: int = 0
    presentaciones: list = []


ProductoDetalleResponse.model_rebuild()


class ProductoPrecioResumenResponse(BaseModel):
    id_producto_presentacion: int
    id_presentacion: int
    id_producto: int
    presentacion_id: int
    presentacion_codigo: str
    presentacion_descripcion: str
    precio: Decimal
    fecha_alta: datetime


class ProductoCategoriaResumenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    id_comercio: int
    descripcion: str
    activo: bool
    orden: int
    fecha_alta: datetime
    fecha_ultima_modificacion: datetime
    productos: list = []


ProductoCategoriaResumenResponse.model_rebuild()


class ProductoComercioCatalogoResponse(BaseModel):
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
    categorias: list["ProductoCategoriaResumenResponse"] = []


class ProductoIncompletoResponse(BaseModel):
    id_producto: int
    nombre: str
    id_categoria_producto: int
    problemas: list[str]
