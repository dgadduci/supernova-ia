from __future__ import annotations

from typing import Literal, Protocol, Required, TypedDict


class AliasProjection(TypedDict, total=False):
    """Recognition-ready alias data attached to one catalog row.

    ``general_aliases`` apply to every presentation of the product.
    ``specific_aliases`` apply only to the exact
    ``producto_presentacion_id`` that carries them. Both collections use
    the recognizer-compatible normalized form so callers can pass them
    straight into the fuzzy pipeline without further transformation.
    """

    general_aliases: list[str]
    specific_aliases: list[str]


class ProductCatalogEntry(TypedDict, total=False):
    producto_presentacion_id: Required[int]
    producto_id: int
    presentacion_id: int
    categoria_id: int
    producto_nombre: Required[str]
    categoria_nombre: str
    presentacion_codigo: str
    presentacion_descripcion: str
    producto_activo: bool
    presentacion_activo: bool
    activo: bool
    disponible: bool
    aliases: AliasProjection


class RecognizedProduct(TypedDict, total=False):
    producto_presentacion_id: Required[int]
    producto_id: int
    presentacion_id: int
    categoria_id: int
    producto_nombre: Required[str]
    categoria_nombre: str
    presentacion_codigo: str
    presentacion_descripcion: str
    producto_activo: bool
    presentacion_activo: bool
    activo: bool
    disponible: bool
    aliases: AliasProjection
    cantidad: Required[int]
    texto_origen: Required[str]


class PossibleMatchGroup(TypedDict):
    texto_origen: str
    productos: list[RecognizedProduct]


class CategoryAmbiguityGroup(TypedDict, total=True):
    kind: Literal["category"]
    categoria_nombre: str
    texto_origen: str


PossibleAmbiguityGroup = PossibleMatchGroup | CategoryAmbiguityGroup


class UnmatchedFragment(TypedDict):
    texto_origen: str


class ProductRecognizerResult(TypedDict):
    encontrados: list[RecognizedProduct]
    encontrados_posibles: list[PossibleAmbiguityGroup]
    encontrados_no_disponibles: list[RecognizedProduct]
    no_encontrados: list[UnmatchedFragment]


class RecognizeContext(TypedDict, total=True):
    """Backward-compatible shared context for the recognition boundary.

    The Subphase 4.12B hybrid authoritative recognizer reads the
    ``catalog_scope`` field to fire the 4.11.5 restricted-scope guard
    verbatim at runtime. Every call site that omits the new
    ``intent_metadata`` keyword argument on
    :meth:`ProductRecognizerProtocol.recognize` continues to work
    without modification; the keyword argument is keyword-only and
    optional.

    The ``catalog_scope`` literal carries the documented scope of the
    catalog the caller is passing to ``recognize(...)``:

    - ``"pending_product_selection_restricted"`` — the catalog is the
      in-memory restricted candidate projection the 4.12A resolver
      narrowed for the active pending intent. The 4.11.5 guard fires
      when the fuzzy decision is ``"ambiguous"``.
    - ``"commerce_dynamic_database"`` — the catalog is the active
      commerce dynamic database. The 4.11.5 guard is short-circuited.
    """

    catalog_scope: Literal[
        "pending_product_selection_restricted",
        "commerce_dynamic_database",
    ]


class ProductRecognizerProtocol(Protocol):
    def recognize(
        self,
        text: str,
        catalog: list[dict],
        *,
        intent_metadata: RecognizeContext | None = None,
    ) -> ProductRecognizerResult:
        ...


CatalogEntry = ProductCatalogEntry
PossibleProducts = PossibleMatchGroup
UnmatchedProductFragment = UnmatchedFragment


__all__ = [
    "AliasProjection",
    "CatalogEntry",
    "CategoryAmbiguityGroup",
    "PossibleAmbiguityGroup",
    "PossibleMatchGroup",
    "PossibleProducts",
    "ProductCatalogEntry",
    "ProductRecognizerProtocol",
    "ProductRecognizerResult",
    "RecognizeContext",
    "RecognizedProduct",
    "UnmatchedFragment",
    "UnmatchedProductFragment",
]
