from pydantic import BaseModel, ConfigDict, Field


class EstadoComercioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    estado: str = Field(min_length=1)


class EstadoComercioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    estado: str
