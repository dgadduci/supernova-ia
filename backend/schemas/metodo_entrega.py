from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MetodoEntregaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codigo: str = Field(min_length=1, max_length=50)
    descripcion: str = Field(min_length=1, max_length=100)
    orden: int = Field(ge=0)
    activo: bool = True


class MetodoEntregaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    descripcion: str
    orden: int
    activo: bool
    fecha_alta: datetime
    fecha_ultima_modificacion: datetime
