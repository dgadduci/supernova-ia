"""Read-only typed view models for the administrative catalog panel.

The panel templates rely on these dataclasses so they can render
data without ever inspecting SQLAlchemy ORM state. Each view model
captures only the documented closed fields; ``instruccion_llm`` is
intentionally absent everywhere; identifiers stay numeric so
``autoescape`` keeps the rendered HTML safe.

The view models are intentionally minimal: a ``CommerceSummary``
just carries what the list needs, the full ``CommerceDetailView``
carries the configuration the detail page requires, and the
catalog views mirror the existing JSON schemas without exposing
operational internals (no embeddings payloads, no provider data,
no diagnostic data, no exception detail).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from backend.models import EstadoComercio


@dataclass(frozen=True)
class CommerceSummary:
    """Bounded commerce projection for the administrative list view."""

    id: int
    nombre_fantasia: str
    nombre_corto: str
    estado: str
    flavor_codigo: str | None
    flavor_nombre: str | None
    tiene_flavor: bool


@dataclass(frozen=True)
class FlavorOption:
    """One selectable flavor row in the assignment form.

    The panel never displays ``instruccion_llm`` so the option is
    limited to the operator-facing metadata. The dataclass is the
    sole surface the panel uses to enumerate flavors.
    """

    id: int
    codigo: str
    nombre: str
    descripcion: str
    version: int


@dataclass(frozen=True)
class FlavorSummaryView:
    """Closed summary used inside the commerce detail view."""

    id: int
    codigo: str
    nombre: str
    descripcion: str
    version: int
    activo: bool


@dataclass(frozen=True)
class PaymentMethodDetailView:
    """One commerce-level payment-method row in the detail view."""

    id: int
    codigo: str
    descripcion: str
    activo: bool
    titular: str | None
    alias: str | None


@dataclass(frozen=True)
class GlobalMedioPagoRow:
    """One global payment-method row in the catalog administration view.

    The view model carries only the documented closed fields the
    panel renders. The per-commerce ``titular`` / ``alias`` values
    remain exclusively on ``ComercioMedioPago``; the global catalog
    stores the boolean availability flags that govern whether a
    commerce form may edit those per-commerce values.
    """

    id: int
    codigo: str
    descripcion: str
    activo: bool
    habilita_titular: bool
    habilita_alias: bool


@dataclass(frozen=True)
class DeliveryMethodDetailView:
    """One commerce-level delivery-method row in the detail view."""

    id: int
    codigo: str
    descripcion: str
    activo: bool
    orden: int


@dataclass(frozen=True)
class CommerceDetailView:
    """Exact commerce configuration used by the detail view."""

    id: int
    nombre_fantasia: str
    nombre_corto: str
    razon_social: str
    cuit: str
    whatsapp: str
    calle: str
    numero: str
    piso_departamento: str | None
    localidad: str
    provincia: str
    codigo_postal: str | None
    slug: str
    estado: str
    zona_horaria: str
    moneda: str
    idioma: str
    medios_pago: list[PaymentMethodDetailView] = field(default_factory=list)
    metodos_entrega: list[DeliveryMethodDetailView] = field(default_factory=list)
    flavor: FlavorSummaryView | None = None


@dataclass(frozen=True)
class CatalogCategoriaRow:
    """One category row inside the commerce-scoped catalog view."""

    id: int
    descripcion: str
    activo: bool
    orden: int


@dataclass(frozen=True)
class CatalogProductoRow:
    """One product row inside the category-scoped catalog view."""

    id: int
    nombre: str
    descripcion: str | None
    activo: bool
    disponible: bool
    orden: int


@dataclass(frozen=True)
class CatalogPresentacionRow:
    """One presentation row inside the commerce-scoped catalog view."""

    id: int
    codigo: str
    descripcion: str
    activo: bool
    orden: int


@dataclass(frozen=True)
class CatalogProductoPresentacionRow:
    """One product/presentation pair inside the product-scoped view.

    The pair only carries the parent identifiers and a display
    string for the presentation description. The price-availability
    flag follows the exact same convention used by the pilot
    panel: ``True`` only when there is exactly one ``Precio`` row.
    """

    id: int
    id_producto: int
    id_presentacion: int
    presentacion_descripcion: str
    precio_disponible: bool


@dataclass(frozen=True)
class CatalogCategoriaDetailView:
    """Category-scoped view used by the panel."""

    id: int
    id_comercio: int
    descripcion: str
    activo: bool
    orden: int
    productos: list[CatalogProductoRow] = field(default_factory=list)


@dataclass(frozen=True)
class CatalogProductoDetailView:
    """Product-scoped view used by the panel.

    The view includes the parent category id and the list of
    product-presentation pairs so the price-creation form can
    display the available parent presentations.
    """

    id: int
    id_categoria_producto: int
    nombre: str
    descripcion: str | None
    activo: bool
    disponible: bool
    orden: int
    presentaciones: list[CatalogProductoPresentacionRow] = field(default_factory=list)


@dataclass(frozen=True)
class CommerceCatalogNavigationView:
    """Commerce-scoped catalog navigation view.

    The dataclass surfaces every nested row the panel needs without
    ever broadening the query beyond the selected comercio. Each
    child list carries exactly the rows that belong to the
    selected commerce; no cross-commerce lookup is performed.
    """

    comercio_id: int
    categorias: list[CatalogCategoriaRow] = field(default_factory=list)
    presentaciones: list[CatalogPresentacionRow] = field(default_factory=list)


@dataclass(frozen=True)
class InvalidComercioIdError:
    """Sentinel raised when the path commerce id is not a positive integer."""

    raw_value: str


@dataclass(frozen=True)
class InvalidNestedIdError:
    """Sentinel raised when a nested catalog id is not a positive integer."""

    raw_value: str


@dataclass(frozen=True)
class PanelFormStatus:
    """Status envelope rendered after a successful or failed form submission.

    The dataclass carries only the information the panel needs to
    display the result: an ``outcome`` token (``"success"`` or
    ``"error"``), a localized status text suitable for screen
    readers (always non-empty, no colour-only signal), the
    optional field name that produced the validation error and an
    optional resource identifier to link to. The dataclass never
    carries the raw exception, the row data, the diagnostics or the
    session payload.
    """

    outcome: str
    message: str
    field_name: str | None = None
    resource_id: int | None = None
    resource_label: str | None = None


def parse_positive_int(raw_value: str, *, field_name: str) -> int:
    """Validate and return a positive integer for a path parameter.

    The helper centralises the panel's strict integer parsing so
    every nested identifier goes through the same gate. It raises
    :class:`ValueError` for non-positive or non-integer values; the
    caller translates the failure into a safe ``400`` HTML page.
    """
    if not isinstance(raw_value, str):
        raise TypeError(f"{field_name} must be a string")
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive integer") from exc
    if parsed < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return parsed


def to_estado_label(estado: Any) -> str:
    """Return a stable, closed label for an :class:`EstadoComercio` row.

    The label is always a non-empty ``str`` so the template can
    always render it; unknown values fall back to ``"DESCONOCIDO"``
    so the panel never leaks an ORM enum or an SQL identifier.
    """
    if isinstance(estado, EstadoComercio):
        return str(estado.estado)
    if hasattr(estado, "estado"):
        return str(estado.estado)
    if isinstance(estado, str) and estado:
        return estado
    return "DESCONOCIDO"


def format_precio_display(value: Decimal) -> str:
    """Render a stored :class:`decimal.Decimal` price for display.

    The helper preserves the trailing zeros so a stored
    ``Decimal('150.00')`` renders as ``"150.00"`` in the panel.
    The helper never inspects the configuration and is pure.
    """
    return str(value)


__all__ = [
    "CatalogCategoriaDetailView",
    "CatalogCategoriaRow",
    "CatalogPresentacionRow",
    "CatalogProductoDetailView",
    "CatalogProductoPresentacionRow",
    "CatalogProductoRow",
    "CommerceCatalogNavigationView",
    "CommerceDetailView",
    "CommerceSummary",
    "DeliveryMethodDetailView",
    "FlavorOption",
    "FlavorSummaryView",
    "GlobalMedioPagoRow",
    "InvalidComercioIdError",
    "InvalidNestedIdError",
    "PanelFormStatus",
    "PaymentMethodDetailView",
    "format_precio_display",
    "parse_positive_int",
    "to_estado_label",
]