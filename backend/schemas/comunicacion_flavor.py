"""Safe response schemas for the global communication flavor catalog.

The OpenSpec contract exposes only the safe metadata
(``id``, ``codigo``, ``nombre``, ``descripcion``, ``version``,
``activo``) through every API and configuration read. The internal
``instruccion_llm`` text is never published: it is reserved for the
future response-embellishment phase and must not leak through any
diagnostic, log message or exception detail.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FlavorComunicacionResponse(BaseModel):
    """Safe public view of a single global flavor row."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str = Field(min_length=1, max_length=50)
    nombre: str = Field(min_length=1, max_length=120)
    descripcion: str = Field(min_length=1, max_length=255)
    version: int = Field(ge=1)
    activo: bool


class FlavorComunicacionSummary(BaseModel):
    """Embedding of the selected flavor on a commerce read.

    The Commerce and ComercioConfiguracion responses include this
    nested block so administrators can audit the current selection
    without re-querying the catalog. ``instruccion_llm`` is
    intentionally absent.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str = Field(min_length=1, max_length=50)
    nombre: str = Field(min_length=1, max_length=120)
    descripcion: str = Field(min_length=1, max_length=255)
    version: int = Field(ge=1)
    activo: bool


class ComercioFlavorAssignRequest(BaseModel):
    """Payload for the focused ``PUT /comercios/{id}/flavor-comunicacion``
    operation.

    Only the global flavor ID is accepted. The endpoint refuses any
    payload that tries to mutate ``descripcion`` or ``instruccion_llm``
    because the catalog is system-managed global seed data.
    """

    model_config = ConfigDict(extra="forbid")

    flavor_comunicacion_id: int = Field(ge=1)


__all__ = [
    "ComercioFlavorAssignRequest",
    "FlavorComunicacionResponse",
    "FlavorComunicacionSummary",
]
