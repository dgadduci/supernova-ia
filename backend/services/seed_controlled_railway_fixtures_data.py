"""Static, deterministic fixture dataset for an empty Railway database.

This module is the single source of truth for the controlled fixture
catalog used by the ``seed_controlled_railway_fixtures`` CLI. The
dataset is intentionally static application data: the CLI never reads,
exports, cleans or compares against a local development database, and
these dataclasses are intentionally frozen so no caller can mutate the
catalog at runtime.

The shape is locked by the
``openspec/changes/seed-controlled-railway-fixtures`` change. The
catalog covers exactly:

* three active, synthetic commerces
* four categories per commerce
* seven presentations per commerce
* thirty products per commerce (8 pizzas, 8 empanadas, 7 beverages,
  7 desserts)
* fifty-nine ``ProductoPresentacion`` rows per commerce (16 pizzas +
  8 empanadas + 21 beverages + 14 desserts)
* fifty-nine fixed prices per commerce

The ``PRESENTATIONS_BY_CATEGORY`` table drives the product-presentation
associations. Prices are keyed by ``(category_slug, product_nombre,
presentation_codigo)`` so the same catalog yields identical numbers
for every commerce.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

COMMERCE_ESTADO_CODIGO: Final[str] = "ACTIVO"
COMMERCE_ESTADO_MODO: Final[str] = "habilitado"


@dataclass(frozen=True)
class CommerceFixture:
    slug: str
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


@dataclass(frozen=True)
class CategoryFixture:
    slug: str
    descripcion: str
    orden: int


@dataclass(frozen=True)
class PresentationFixture:
    codigo: str
    descripcion: str
    orden: int


@dataclass(frozen=True)
class ProductFixture:
    category_slug: str
    nombre: str
    descripcion: str | None


@dataclass(frozen=True)
class FixtureCounts:
    comercios: int
    categorias: int
    presentaciones: int
    productos: int
    producto_presentaciones: int
    precios: int


COMMERCE_FIXTURES: Final[tuple[CommerceFixture, ...]] = (
    CommerceFixture(
        slug="piloto-whatsapp-dedicado",
        nombre_fantasia="Piloto WhatsApp Dedicado",
        nombre_corto="Piloto Dedicado",
        razon_social="Piloto WhatsApp Dedicado SRL",
        cuit="30-77000001-1",
        whatsapp="FIXTURE:DEDICADO",
        calle="Av. Piloto Dedicado",
        numero="100",
        piso_departamento=None,
        localidad="CABA",
        provincia="Buenos Aires",
        codigo_postal="C1000",
    ),
    CommerceFixture(
        slug="piloto-whatsapp-compartido-uno",
        nombre_fantasia="Piloto WhatsApp Compartido Uno",
        nombre_corto="Piloto Compartido Uno",
        razon_social="Piloto WhatsApp Compartido Uno SRL",
        cuit="30-77000002-2",
        whatsapp="FIXTURE:COMPARTIDO-UNO",
        calle="Av. Piloto Compartido Uno",
        numero="200",
        piso_departamento=None,
        localidad="CABA",
        provincia="Buenos Aires",
        codigo_postal="C1001",
    ),
    CommerceFixture(
        slug="piloto-whatsapp-compartido-dos",
        nombre_fantasia="Piloto WhatsApp Compartido Dos",
        nombre_corto="Piloto Compartido Dos",
        razon_social="Piloto WhatsApp Compartido Dos SRL",
        cuit="30-77000003-3",
        whatsapp="FIXTURE:COMPARTIDO-DOS",
        calle="Av. Piloto Compartido Dos",
        numero="300",
        piso_departamento=None,
        localidad="CABA",
        provincia="Buenos Aires",
        codigo_postal="C1002",
    ),
)


CATEGORY_FIXTURES: Final[tuple[CategoryFixture, ...]] = (
    CategoryFixture(slug="pizzas", descripcion="Pizzas", orden=10),
    CategoryFixture(slug="empanadas", descripcion="Empanadas", orden=20),
    CategoryFixture(slug="bebidas", descripcion="Bebidas", orden=30),
    CategoryFixture(slug="postres", descripcion="Postres", orden=40),
)


PRESENTATION_FIXTURES: Final[tuple[PresentationFixture, ...]] = (
    PresentationFixture(codigo="grande", descripcion="Grande", orden=10),
    PresentationFixture(codigo="chica", descripcion="Chica", orden=20),
    PresentationFixture(codigo="unidad", descripcion="Unidad", orden=30),
    PresentationFixture(codigo="lata", descripcion="Lata", orden=40),
    PresentationFixture(codigo="litro", descripcion="Litro", orden=50),
    PresentationFixture(codigo="2-litros", descripcion="2 Litros", orden=60),
    PresentationFixture(codigo="kilo", descripcion="Kilo", orden=70),
)


PRESENTATIONS_BY_CATEGORY: Final[Mapping[str, tuple[str, ...]]] = {
    "pizzas": ("grande", "chica"),
    "empanadas": ("unidad",),
    "bebidas": ("lata", "litro", "2-litros"),
    "postres": ("unidad", "kilo"),
}


PRODUCT_FIXTURES: Final[tuple[ProductFixture, ...]] = (
    ProductFixture(category_slug="pizzas", nombre="Mozzarella", descripcion=None),
    ProductFixture(category_slug="pizzas", nombre="Napolitana", descripcion=None),
    ProductFixture(category_slug="pizzas", nombre="Fugazzeta", descripcion=None),
    ProductFixture(category_slug="pizzas", nombre="Calabresa", descripcion=None),
    ProductFixture(
        category_slug="pizzas",
        nombre="Jamón y morrones",
        descripcion=None,
    ),
    ProductFixture(
        category_slug="pizzas",
        nombre="Cuatro quesos",
        descripcion=None,
    ),
    ProductFixture(
        category_slug="pizzas",
        nombre="Rúcula y crudo",
        descripcion=None,
    ),
    ProductFixture(
        category_slug="pizzas",
        nombre="Vegetariana",
        descripcion=None,
    ),
    ProductFixture(
        category_slug="empanadas",
        nombre="Carne suave",
        descripcion=None,
    ),
    ProductFixture(
        category_slug="empanadas",
        nombre="Carne picante",
        descripcion=None,
    ),
    ProductFixture(category_slug="empanadas", nombre="Pollo", descripcion=None),
    ProductFixture(
        category_slug="empanadas",
        nombre="Jamón y queso",
        descripcion=None,
    ),
    ProductFixture(category_slug="empanadas", nombre="Humita", descripcion=None),
    ProductFixture(category_slug="empanadas", nombre="Verdura", descripcion=None),
    ProductFixture(
        category_slug="empanadas",
        nombre="Cebolla y queso",
        descripcion=None,
    ),
    ProductFixture(category_slug="empanadas", nombre="Caprese", descripcion=None),
    ProductFixture(
        category_slug="bebidas",
        nombre="Cola clásica",
        descripcion=None,
    ),
    ProductFixture(
        category_slug="bebidas",
        nombre="Cola sin azúcar",
        descripcion=None,
    ),
    ProductFixture(
        category_slug="bebidas",
        nombre="Lima-limón",
        descripcion=None,
    ),
    ProductFixture(category_slug="bebidas", nombre="Naranja", descripcion=None),
    ProductFixture(
        category_slug="bebidas",
        nombre="Agua sin gas",
        descripcion=None,
    ),
    ProductFixture(
        category_slug="bebidas",
        nombre="Agua con gas",
        descripcion=None,
    ),
    ProductFixture(
        category_slug="bebidas",
        nombre="Cerveza rubia",
        descripcion=None,
    ),
    ProductFixture(
        category_slug="postres",
        nombre="Helado chocolate",
        descripcion=None,
    ),
    ProductFixture(
        category_slug="postres",
        nombre="Helado vainilla",
        descripcion=None,
    ),
    ProductFixture(
        category_slug="postres",
        nombre="Helado dulce de leche",
        descripcion=None,
    ),
    ProductFixture(
        category_slug="postres",
        nombre="Flan casero",
        descripcion=None,
    ),
    ProductFixture(category_slug="postres", nombre="Tiramisú", descripcion=None),
    ProductFixture(category_slug="postres", nombre="Brownie", descripcion=None),
    ProductFixture(
        category_slug="postres",
        nombre="Ensalada de frutas",
        descripcion=None,
    ),
)


PRICE_FIXTURES: Final[Mapping[tuple[str, str, str], Decimal]] = {
    ("pizzas", "Mozzarella", "grande"): Decimal("8500.00"),
    ("pizzas", "Mozzarella", "chica"): Decimal("5800.00"),
    ("pizzas", "Napolitana", "grande"): Decimal("8800.00"),
    ("pizzas", "Napolitana", "chica"): Decimal("6000.00"),
    ("pizzas", "Fugazzeta", "grande"): Decimal("9200.00"),
    ("pizzas", "Fugazzeta", "chica"): Decimal("6300.00"),
    ("pizzas", "Calabresa", "grande"): Decimal("9000.00"),
    ("pizzas", "Calabresa", "chica"): Decimal("6100.00"),
    ("pizzas", "Jamón y morrones", "grande"): Decimal("9100.00"),
    ("pizzas", "Jamón y morrones", "chica"): Decimal("6200.00"),
    ("pizzas", "Cuatro quesos", "grande"): Decimal("9500.00"),
    ("pizzas", "Cuatro quesos", "chica"): Decimal("6500.00"),
    ("pizzas", "Rúcula y crudo", "grande"): Decimal("9700.00"),
    ("pizzas", "Rúcula y crudo", "chica"): Decimal("6600.00"),
    ("pizzas", "Vegetariana", "grande"): Decimal("8900.00"),
    ("pizzas", "Vegetariana", "chica"): Decimal("6050.00"),
    ("empanadas", "Carne suave", "unidad"): Decimal("900.00"),
    ("empanadas", "Carne picante", "unidad"): Decimal("900.00"),
    ("empanadas", "Pollo", "unidad"): Decimal("900.00"),
    ("empanadas", "Jamón y queso", "unidad"): Decimal("900.00"),
    ("empanadas", "Humita", "unidad"): Decimal("900.00"),
    ("empanadas", "Verdura", "unidad"): Decimal("900.00"),
    ("empanadas", "Cebolla y queso", "unidad"): Decimal("900.00"),
    ("empanadas", "Caprese", "unidad"): Decimal("950.00"),
    ("bebidas", "Cola clásica", "lata"): Decimal("1200.00"),
    ("bebidas", "Cola clásica", "litro"): Decimal("2200.00"),
    ("bebidas", "Cola clásica", "2-litros"): Decimal("3600.00"),
    ("bebidas", "Cola sin azúcar", "lata"): Decimal("1200.00"),
    ("bebidas", "Cola sin azúcar", "litro"): Decimal("2200.00"),
    ("bebidas", "Cola sin azúcar", "2-litros"): Decimal("3600.00"),
    ("bebidas", "Lima-limón", "lata"): Decimal("1200.00"),
    ("bebidas", "Lima-limón", "litro"): Decimal("2200.00"),
    ("bebidas", "Lima-limón", "2-litros"): Decimal("3600.00"),
    ("bebidas", "Naranja", "lata"): Decimal("1200.00"),
    ("bebidas", "Naranja", "litro"): Decimal("2200.00"),
    ("bebidas", "Naranja", "2-litros"): Decimal("3600.00"),
    ("bebidas", "Agua sin gas", "lata"): Decimal("900.00"),
    ("bebidas", "Agua sin gas", "litro"): Decimal("1700.00"),
    ("bebidas", "Agua sin gas", "2-litros"): Decimal("2800.00"),
    ("bebidas", "Agua con gas", "lata"): Decimal("900.00"),
    ("bebidas", "Agua con gas", "litro"): Decimal("1700.00"),
    ("bebidas", "Agua con gas", "2-litros"): Decimal("2800.00"),
    ("bebidas", "Cerveza rubia", "lata"): Decimal("1800.00"),
    ("bebidas", "Cerveza rubia", "litro"): Decimal("3200.00"),
    ("bebidas", "Cerveza rubia", "2-litros"): Decimal("5400.00"),
    ("postres", "Helado chocolate", "unidad"): Decimal("2200.00"),
    ("postres", "Helado chocolate", "kilo"): Decimal("9800.00"),
    ("postres", "Helado vainilla", "unidad"): Decimal("2200.00"),
    ("postres", "Helado vainilla", "kilo"): Decimal("9800.00"),
    ("postres", "Helado dulce de leche", "unidad"): Decimal("2300.00"),
    ("postres", "Helado dulce de leche", "kilo"): Decimal("10100.00"),
    ("postres", "Flan casero", "unidad"): Decimal("1900.00"),
    ("postres", "Flan casero", "kilo"): Decimal("8200.00"),
    ("postres", "Tiramisú", "unidad"): Decimal("2400.00"),
    ("postres", "Tiramisú", "kilo"): Decimal("10800.00"),
    ("postres", "Brownie", "unidad"): Decimal("1600.00"),
    ("postres", "Brownie", "kilo"): Decimal("7200.00"),
    ("postres", "Ensalada de frutas", "unidad"): Decimal("1700.00"),
    ("postres", "Ensalada de frutas", "kilo"): Decimal("7500.00"),
}


def expected_fixture_counts() -> FixtureCounts:
    """Return the locked counts the apply/verify contract checks.

    The counts are derived from the static definitions above so any
    accidental change to the catalog shape raises an obvious mismatch
    during tests. The CLI/service use the same numbers for both
    verification and apply.
    """
    asociaciones = 0
    for product in PRODUCT_FIXTURES:
        asociaciones += len(PRESENTATIONS_BY_CATEGORY[product.category_slug])
    return FixtureCounts(
        comercios=len(COMMERCE_FIXTURES),
        categorias=len(CATEGORY_FIXTURES),
        presentaciones=len(PRESENTATION_FIXTURES),
        productos=len(PRODUCT_FIXTURES),
        producto_presentaciones=asociaciones,
        precios=asociaciones,
    )


__all__ = [
    "CATEGORY_FIXTURES",
    "COMMERCE_ESTADO_CODIGO",
    "COMMERCE_FIXTURES",
    "PRESENTATIONS_BY_CATEGORY",
    "PRESENTATION_FIXTURES",
    "PRICE_FIXTURES",
    "PRODUCT_FIXTURES",
    "CategoryFixture",
    "CommerceFixture",
    "FixtureCounts",
    "PresentationFixture",
    "ProductFixture",
    "expected_fixture_counts",
]
