from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MediosPagoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codigo: str = Field(min_length=1, max_length=50)
    descripcion: str = Field(min_length=1, max_length=100)
    activo: bool = True
    habilita_titular: bool = False
    habilita_alias: bool = False


class MediosPagoUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    descripcion: str | None = Field(default=None, min_length=1, max_length=100)
    activo: bool | None = None
    habilita_titular: bool | None = None
    habilita_alias: bool | None = None


class MediosPagoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    descripcion: str
    activo: bool
    habilita_titular: bool
    habilita_alias: bool
    fecha_alta: datetime
    fecha_ultima_modificacion: datetime