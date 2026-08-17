"""Pydantic form shapes for the administrative catalog panel.

Every form mirrors the corresponding JSON API request schema so the
shared :class:`CatalogCreateService` boundary receives the exact
same validated payload regardless of who submitted the request. The
forms use ``form_data``-style assignment with ``extra='forbid'`` so
the panel cannot smuggle unknown fields into the existing
services.

The panel never writes directly to repositories or models — the
forms are a pure adapter that produces typed input for the shared
service. The shared service then owns validation, transaction
ownership and the post-create embedding synchronization exactly as
the JSON API router does.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CatalogFormError(BaseModel):
    """Bounded, escaped form-level error rendered by the panel.

    The panel surfaces the same human-readable messages the JSON API
    uses (``str(exc)``) so an operator who reads both surfaces sees
    consistent feedback. The field name (``field_name``) is optional
    and is rendered only when the form has a single offending input;
    the message itself is the same generic string the JSON API
    emits so no internal identifier leaks.
    """

    model_config = ConfigDict(extra="forbid")

    field_name: str | None = None
    message: str = Field(min_length=1, max_length=400)


class CategoriaProductoForm(BaseModel):
    """Create-category form payload.

    The shape mirrors :class:`backend.schemas.categoria_producto.CategoriaProductoCreate`
    exactly so the panel forwards the same validated data into
    :meth:`CatalogCreateService.create_categoria_producto`.
    """

    model_config = ConfigDict(extra="forbid")

    descripcion: str = Field(min_length=1, max_length=100)
    activo: bool | None = None
    orden: int | None = Field(default=None, ge=0)


class ProductoForm(BaseModel):
    """Create-product form payload.

    The shape mirrors :class:`backend.schemas.producto.ProductoCreate`.
    """

    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(min_length=1, max_length=150)
    descripcion: str | None = Field(default=None, max_length=2000)
    activo: bool | None = None
    disponible: bool | None = None
    orden: int | None = Field(default=None, ge=0)


class PresentacionForm(BaseModel):
    """Create-presentation form payload.

    The shape mirrors :class:`backend.schemas.presentacion.PresentacionCreate`.
    """

    model_config = ConfigDict(extra="forbid")

    codigo: str = Field(min_length=1, max_length=50)
    descripcion: str = Field(min_length=1, max_length=100)
    activo: bool | None = None
    orden: int | None = Field(default=None, ge=0)


class PrecioForm(BaseModel):
    """Create-price form payload.

    The shape mirrors :class:`backend.schemas.precio.PrecioCreate`.
    """

    model_config = ConfigDict(extra="forbid")

    precio: Decimal = Field(ge=Decimal(0), max_digits=12, decimal_places=2)


class FlavorAssignForm(BaseModel):
    """Flavor assignment / clear form payload.

    The shape accepts only the documented
    ``flavor_comunicacion_id`` field with the same constraint the
    JSON API enforces: a positive global flavor id to assign, or the
    explicit ``None`` value to clear. Any other value (an empty
    string, ``0``, a negative number, a sentinel) is rejected by
    Pydantic so the panel never has to invent a "neutral" sentinel
    or rely on a magic code. The closed validator guarantees that
    the only way to clear the flavor is to omit the value entirely
    in the form (which Pydantic translates into ``None``).

    ``extra`` is configured to ``"ignore"`` so the server-rendered
    CSRF marker field does not break Pydantic validation; the panel
    only ever writes the documented ``flavor_comunicacion_id`` to
    the service so the broader rejection guarantee still holds.
    """

    model_config = ConfigDict(extra="ignore")

    flavor_comunicacion_id: int | None = Field(default=None, ge=1)


__all__ = [
    "CatalogFormError",
    "CategoriaProductoForm",
    "FlavorAssignForm",
    "PrecioForm",
    "PresentacionForm",
    "ProductoForm",
]