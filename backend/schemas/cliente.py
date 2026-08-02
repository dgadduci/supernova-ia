from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ClienteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    whatsapp: str = Field(min_length=1, max_length=20)
    nombre: str | None = Field(default=None, max_length=150)
    domicilio: str | None = Field(default=None, max_length=255)


class ClienteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre: str | None = Field(default=None, max_length=150)
    domicilio: str | None = Field(default=None, max_length=255)
    activo: bool | None = None


class ClienteActivoUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activo: bool


class ClienteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str | None
    whatsapp: str
    domicilio: str | None
    activo: bool
    created_at: datetime
    updated_at: datetime