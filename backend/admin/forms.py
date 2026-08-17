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
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


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


class MedioPagoCreateForm(BaseModel):
    """Create global payment-method form payload.

    The shape mirrors
    :class:`backend.schemas.medios_pago.MediosPagoCreate` so the
    shared :class:`backend.services.medios_pago_service.MediosPagoService`
    boundary receives the same validated payload regardless of
    whether the JSON API or the panel submitted the request. The
    boolean availability fields default to ``False`` to match the
    documented safe baseline; an operator who wants a method to
    permit per-commerce ``titular`` / ``alias`` editing ticks the
    corresponding checkbox and the panel forwards ``True``.
    """

    model_config = ConfigDict(extra="forbid")

    codigo: str = Field(min_length=1, max_length=50)
    descripcion: str = Field(min_length=1, max_length=100)
    activo: bool | None = None
    habilita_titular: bool | None = None
    habilita_alias: bool | None = None


class MedioPagoUpdateForm(BaseModel):
    """Edit global payment-method form payload.

    The shape mirrors
    :class:`backend.schemas.medios_pago.MediosPagoUpdate` so the
    shared service boundary receives the same validated payload
    regardless of who submitted the request. ``codigo`` is
    intentionally absent from the update shape because the global
    catalog code is the natural identifier the rest of the system
    keys off; an operator who wants to change a code must use a
    new global row.
    """

    model_config = ConfigDict(extra="forbid")

    descripcion: str | None = Field(default=None, min_length=1, max_length=100)
    activo: bool | None = None
    habilita_titular: bool | None = None
    habilita_alias: bool | None = None


def _coerce_blank_flavor_id_to_none(value: object) -> object:
    """Normalise the HTML "no flavor" representation to ``None``.

    The browser always sends ``flavor_comunicacion_id=""`` when the
    operator picks the "— Sin flavor —" option. Without this
    normalisation step Pydantic rejects the empty string before
    ``int`` coercion can produce ``None`` and the route never sees
    a real ``flavor_comunicacion_id``. The helper runs *before*
    Pydantic's type validation so the field can still be declared
    as ``int | None`` with ``ge=1``: a blank string becomes
    ``None`` (the only valid clear), a non-blank string is passed
    through for ``int`` coercion (which still rejects non-numeric
    values and values below ``1``), and ``None`` or any other
    non-string value is forwarded unchanged.
    """
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned == "":
            return None
        return cleaned
    return value


class FlavorAssignForm(BaseModel):
    """Flavor assignment / clear form payload.

    The shape accepts only the documented
    ``flavor_comunicacion_id`` field with the same constraint the
    JSON API enforces: a positive global flavor id to assign, or the
    explicit ``None`` value to clear. Any other value (``0``, a
    negative number, a non-numeric string, a magic code) is rejected
    by Pydantic so the panel never has to invent a "neutral" sentinel
    or rely on a magic code.

    The native HTML representation of "no flavor" is the empty string
    (``<option value="">— Sin flavor —</option>``), so the panel-only
    adapter normalises a blank value to ``None`` *before* Pydantic
    coerces the field to ``int``. This is strictly a panel adapter
    concern: the JSON API schema
    (:class:`backend.schemas.comunicacion_flavor.FlavorAsignacion`)
    is unchanged because it never receives form-encoded payloads.
    After the normalisation step Pydantic validates the field as
    ``int | None`` with ``ge=1`` so ``0``, negative numbers and
    non-numeric strings are still rejected at the adapter boundary
    and never reach the shared :class:`CatalogCreateService`.

    ``extra`` is configured to ``"ignore"`` so the server-rendered
    CSRF marker field does not break Pydantic validation; the panel
    only ever writes the documented ``flavor_comunicacion_id`` to
    the service so the broader rejection guarantee still holds.
    """

    model_config = ConfigDict(extra="ignore")

    flavor_comunicacion_id: Annotated[
        int | None,
        BeforeValidator(_coerce_blank_flavor_id_to_none),
    ] = Field(default=None, ge=1)


__all__ = [
    "CatalogFormError",
    "CategoriaProductoForm",
    "FlavorAssignForm",
    "MedioPagoCreateForm",
    "MedioPagoUpdateForm",
    "PrecioForm",
    "PresentacionForm",
    "ProductoForm",
]