from backend.models.estado_comercio import EstadoComercioModoOperacion
from pydantic import BaseModel, ConfigDict, Field


class EstadoComercioCreate(BaseModel):
    """Reserved input shape for the legacy creation endpoint.

    The arbitrary creation surface is retired by the
    ``add-commerce-lifecycle-policy`` change so no caller can submit
    an unbounded ``estado`` label that would silently become part of
    the operational availability vocabulary. The schema remains in the
    module as a typing aid for downstream consumers; the router
    exposes only list and get endpoints and does NOT import this
    model.
    """

    model_config = ConfigDict(extra="forbid")

    codigo: str = Field(min_length=1, max_length=50)
    descripcion: str = Field(min_length=1, max_length=150)
    modo_operacion: EstadoComercioModoOperacion
    seleccionable: bool = False


class EstadoComercioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    descripcion: str
    modo_operacion: EstadoComercioModoOperacion
    seleccionable: bool


__all__ = ["EstadoComercioCreate", "EstadoComercioResponse"]