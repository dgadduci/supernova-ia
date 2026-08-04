from typing import Protocol, Required, TypedDict


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


class UnmatchedFragment(TypedDict):
    texto_origen: str


class ProductRecognizerResult(TypedDict):
    encontrados: list[RecognizedProduct]
    encontrados_posibles: list[PossibleMatchGroup]
    encontrados_no_disponibles: list[RecognizedProduct]
    no_encontrados: list[UnmatchedFragment]


class ProductRecognizerProtocol(Protocol):
    def recognize(
        self,
        text: str,
        catalog: list[dict],
    ) -> ProductRecognizerResult:
        ...


CatalogEntry = ProductCatalogEntry
PossibleProducts = PossibleMatchGroup
UnmatchedProductFragment = UnmatchedFragment


__all__ = [
    "AliasProjection",
    "CatalogEntry",
    "PossibleMatchGroup",
    "PossibleProducts",
    "ProductCatalogEntry",
    "ProductRecognizerProtocol",
    "ProductRecognizerResult",
    "RecognizedProduct",
    "UnmatchedFragment",
    "UnmatchedProductFragment",
]
