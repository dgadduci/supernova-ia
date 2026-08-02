from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProductoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(min_length=1, max_length=150)
    descripcion: str | None = None
    activo: bool | None = None
    disponible: bool | None = None
    orden: int | None = Field(default=None, ge=0)


class ProductoResponse(BaseModel):
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
