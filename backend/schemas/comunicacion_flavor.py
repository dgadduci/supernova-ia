"""Response schemas for the global communication flavor catalog.

The OpenSpec contract splits the catalog exposure into two views:

* ``FlavorComunicacionResponse`` is the administrative view returned
  only by the existing authenticated ``GET /flavors-comunicacion``
  endpoint. It exposes the persisted ``instruccion_llm`` so an
  authenticated administrator can read the exact LLM directive used
  by the outbound stylist. The bounded text is limited to the column
  shape defined on the model (non-empty, max 2000 characters).
* ``FlavorComunicacionSummary`` is the commerce-safe view embedded on
  every commerce and commerce-configuration read and on the flavor
  assignment payload. It intentionally omits ``instruccion_llm`` so
  the field never leaks to nested commerce payloads, configuration
  responses, assignment requests, logs, diagnostics or exception
  details.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FlavorComunicacionResponse(BaseModel):
    """Administrative view of a single global flavor row.

    Returned only by the authenticated ``GET /flavors-comunicacion``
    listing. The ``instruccion_llm`` field reflects the exact
    persisted directive used by the outbound LLM styler and is
    bounded by the catalog column (non-empty, max 2000 characters).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str = Field(min_length=1, max_length=50)
    nombre: str = Field(min_length=1, max_length=120)
    descripcion: str = Field(min_length=1, max_length=255)
    instruccion_llm: str = Field(min_length=1, max_length=2000)
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
