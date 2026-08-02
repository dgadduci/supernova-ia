from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MediosPagoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codigo: str = Field(min_length=1, max_length=50)
    descripcion: str = Field(min_length=1, max_length=100)
    activo: bool = True


class MediosPagoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    descripcion: str
    activo: bool
    fecha_alta: datetime
    fecha_ultima_modificacion: datetime
