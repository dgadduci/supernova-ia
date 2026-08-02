from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PresentacionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codigo: str = Field(min_length=1, max_length=50)
    descripcion: str = Field(min_length=1, max_length=100)
    activo: bool | None = None
    orden: int | None = Field(default=None, ge=0)


class PresentacionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    id_comercio: int
    codigo: str
    descripcion: str
    activo: bool
    orden: int
    fecha_alta: datetime
    fecha_ultima_modificacion: datetime
