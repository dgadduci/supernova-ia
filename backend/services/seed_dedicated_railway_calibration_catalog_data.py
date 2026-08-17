"""Static, deterministic calibration catalog for the dedicated Railway database.

This module is the single source of truth for the dedicated Railway
calibration catalog consumed by the
``backend.cli.seed_dedicated_railway_calibration_catalog`` CLI. The
catalog is intentionally static application data: the CLI never
reads, exports, cleans or compares against a local development
database; the dataclasses are intentionally frozen so no caller can
mutate the catalog at runtime.

The catalog is **isolated** from the WhatsApp pilot fixture
(``backend.services.seed_controlled_railway_fixtures_data``): the
commerce slug, fixtures and category mapping are all different so
the controlled Railway pilot fixture and the dedicated calibration
catalog cannot share an owned-table state.

The catalog is **aligned** with the controlled Railway calibration
identity manifest
(``backend.services.controlled_railway_calibration_identity``). Every
identity declared by the manifest — across pizzas, empanadas,
bebidas and postres — is present exactly once in the catalog with its
literal category slug, product name and presentation code. No
alias, no closest-match, no semantic substitution, no category
crossing is performed: the manifest identities are matched
literally and exclusively.

The catalog owns the same fixture-owned tables as the pilot
fixture: ``estado_comercio``, ``comercios``, ``categorias_productos``,
``presentaciones``, ``productos``, ``producto_presentaciones`` and
``producto_precios``. The catalog creates the single ``ACTIVO``
``estado_comercio`` row it needs. The CLI is the sole owner of one
setup transaction; helpers never call ``commit``, ``rollback``,
``begin`` or ``flush``.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from backend.services.controlled_railway_calibration_identity import (
    get_logical_identity,
    manifest_token_count,
)

COMMERCE_ESTADO_CODIGO: Final[str] = "ACTIVO"
COMMERCE_ESTADO_MODO: Final[str] = "habilitado"


# Marker the dedicated Railway target MUST expose. The CLI reads the
# environment variable exactly as the operator confirms it on the
# deployment. The CLI never compares URLs, hosts, credentials or
# other sensitive values; the marker is a non-secret sentinel that
# proves the destination is the dedicated calibration Railway.
DEDICATED_TARGET_MARKER: Final[str] = "dedicated"
DEDICATED_TARGET_ENV_VAR: Final[str] = "RAILWAY_CALIBRATION_CATALOG_TARGET"


# Dedicated commerce slug. Matches the manifest's
# ``FIXTURE_COMMERCE_SLUG`` so the controlled Railway calibration
# identity resolver (``backend.services.controlled_railway_calibration_identity.resolve_manifest``)
# can resolve every manifest identity against the dedicated
# catalog. Isolation from the WhatsApp pilot fixture is guaranteed
# at the database / marker boundary, not by the slug: the dedicated
# catalog lives on a different dedicated Railway database and the
# CLI refuses to mutate any destination that already carries pilot
# fixture rows.
DEDICATED_COMMERCE_SLUG: Final[str] = "piloto-whatsapp-dedicado"


# Static version identifier. Bumped only when the catalog shape
# changes (new identity, new presentation policy, new price). The
# audit evidence echoes this version so the operator can localise
# drift between the deployed catalog and the one the audit was
# authored against.
CATALOG_FIXTURE_VERSION: Final[str] = "1.0.0"


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
        slug=DEDICATED_COMMERCE_SLUG,
        nombre_fantasia="Calibración Dedicada",
        nombre_corto="Calibración Dedicada",
        razon_social="Calibración Dedicada SRL",
        cuit="30-77009999-9",
        whatsapp="FIXTURE:CALIBRACION-DEDICADA",
        calle="Av. Calibración Dedicada",
        numero="1000",
        piso_departamento=None,
        localidad="CABA",
        provincia="Buenos Aires",
        codigo_postal="C1000",
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
    "postres": ("kilo",),
}


# Product fixtures cover every identity declared by the controlled
# Railway calibration identity manifest. The list is the unique set
# of ``(category_slug, product_nombre)`` pairs the manifest references
# — every manifest token resolves to one of these products.
PRODUCT_FIXTURES: Final[tuple[ProductFixture, ...]] = (
    # Pizzas
    ProductFixture(category_slug="pizzas", nombre="Mozzarella", descripcion=None),
    ProductFixture(category_slug="pizzas", nombre="Napolitana", descripcion=None),
    ProductFixture(category_slug="pizzas", nombre="Margherita", descripcion=None),
    ProductFixture(category_slug="pizzas", nombre="Fugazzeta", descripcion=None),
    ProductFixture(category_slug="pizzas", nombre="Fugazza", descripcion=None),
    ProductFixture(category_slug="pizzas", nombre="Calabresa", descripcion=None),
    ProductFixture(
        category_slug="pizzas",
        nombre="Cuatro quesos",
        descripcion=None,
    ),
    ProductFixture(category_slug="pizzas", nombre="Roquefort", descripcion=None),
    ProductFixture(category_slug="pizzas", nombre="Hawaiana", descripcion=None),
    ProductFixture(
        category_slug="pizzas",
        nombre="Especial de la Casa",
        descripcion=None,
    ),
    # Empanadas
    ProductFixture(
        category_slug="empanadas",
        nombre="Carne suave",
        descripcion=None,
    ),
    ProductFixture(
        category_slug="empanadas",
        nombre="Jamón y queso",
        descripcion=None,
    ),
    ProductFixture(category_slug="empanadas", nombre="Pollo", descripcion=None),
    ProductFixture(
        category_slug="empanadas",
        nombre="Verdura",
        descripcion=None,
    ),
    # Bebidas
    ProductFixture(category_slug="bebidas", nombre="Coca-Cola", descripcion=None),
    ProductFixture(category_slug="bebidas", nombre="Sprite", descripcion=None),
    ProductFixture(
        category_slug="bebidas",
        nombre="Vino tinto Malbec",
        descripcion=None,
    ),
    # Postres
    ProductFixture(
        category_slug="postres",
        nombre="Flan casero",
        descripcion=None,
    ),
    ProductFixture(category_slug="postres", nombre="Tiramisú", descripcion=None),
    ProductFixture(category_slug="postres", nombre="Helado", descripcion=None),
    ProductFixture(category_slug="postres", nombre="Brownie", descripcion=None),
)


# Prices are keyed by ``(category_slug, product_nombre,
# presentation_codigo)``. They are stable, reproducible and do not
# reflect any historical or production value. The fixture audit
# cross-checks the catalog's prices against this exact mapping.
PRICE_FIXTURES: Final[Mapping[tuple[str, str, str], Decimal]] = {
    # Pizzas
    ("pizzas", "Mozzarella", "grande"): Decimal("8500.00"),
    ("pizzas", "Mozzarella", "chica"): Decimal("5800.00"),
    ("pizzas", "Napolitana", "grande"): Decimal("8800.00"),
    ("pizzas", "Napolitana", "chica"): Decimal("6000.00"),
    ("pizzas", "Margherita", "grande"): Decimal("8600.00"),
    ("pizzas", "Margherita", "chica"): Decimal("5900.00"),
    ("pizzas", "Fugazzeta", "grande"): Decimal("9200.00"),
    ("pizzas", "Fugazzeta", "chica"): Decimal("6300.00"),
    ("pizzas", "Fugazza", "grande"): Decimal("9100.00"),
    ("pizzas", "Fugazza", "chica"): Decimal("6200.00"),
    ("pizzas", "Calabresa", "grande"): Decimal("9000.00"),
    ("pizzas", "Calabresa", "chica"): Decimal("6100.00"),
    ("pizzas", "Cuatro quesos", "grande"): Decimal("9500.00"),
    ("pizzas", "Cuatro quesos", "chica"): Decimal("6500.00"),
    ("pizzas", "Roquefort", "grande"): Decimal("9700.00"),
    ("pizzas", "Roquefort", "chica"): Decimal("6600.00"),
    ("pizzas", "Hawaiana", "grande"): Decimal("8900.00"),
    ("pizzas", "Hawaiana", "chica"): Decimal("6050.00"),
    ("pizzas", "Especial de la Casa", "grande"): Decimal("9900.00"),
    ("pizzas", "Especial de la Casa", "chica"): Decimal("6800.00"),
    # Empanadas
    ("empanadas", "Carne suave", "unidad"): Decimal("900.00"),
    ("empanadas", "Jamón y queso", "unidad"): Decimal("900.00"),
    ("empanadas", "Pollo", "unidad"): Decimal("900.00"),
    ("empanadas", "Verdura", "unidad"): Decimal("900.00"),
    # Bebidas
    ("bebidas", "Coca-Cola", "lata"): Decimal("1200.00"),
    ("bebidas", "Coca-Cola", "litro"): Decimal("2200.00"),
    ("bebidas", "Coca-Cola", "2-litros"): Decimal("3600.00"),
    ("bebidas", "Sprite", "lata"): Decimal("1200.00"),
    ("bebidas", "Sprite", "litro"): Decimal("2200.00"),
    ("bebidas", "Sprite", "2-litros"): Decimal("3600.00"),
    ("bebidas", "Vino tinto Malbec", "lata"): Decimal("1800.00"),
    ("bebidas", "Vino tinto Malbec", "litro"): Decimal("3200.00"),
    ("bebidas", "Vino tinto Malbec", "2-litros"): Decimal("5400.00"),
    # Postres
    ("postres", "Flan casero", "kilo"): Decimal("8200.00"),
    ("postres", "Tiramisú", "kilo"): Decimal("10800.00"),
    ("postres", "Helado", "kilo"): Decimal("9800.00"),
    ("postres", "Brownie", "kilo"): Decimal("7200.00"),
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


def get_dedicated_target_marker() -> str:
    """Return the dedicated-target marker the CLI must validate against."""
    return DEDICATED_TARGET_MARKER


def get_dedicated_target_env_var() -> str:
    """Return the dedicated-target environment variable name."""
    return DEDICATED_TARGET_ENV_VAR


def get_dedicated_commerce_slug() -> str:
    """Return the dedicated commerce slug the catalog provisions."""
    return DEDICATED_COMMERCE_SLUG


def get_catalog_fixture_version() -> str:
    """Return the static catalog version identifier."""
    return CATALOG_FIXTURE_VERSION


def audit_manifest_coverage() -> dict[str, int]:
    """Audit the catalog coverage of the manifest identities.

    Returns a dict with the following keys:

    * ``manifest_tokens`` — total number of distinct tokens the
      manifest declares.
    * ``covered_tokens`` — subset of manifest tokens whose
      ``(category_slug, product_nombre, presentation_codigo)`` tuple
      is present in the catalog exactly once.
    * ``missing_tokens`` — manifest tokens with no catalog row.
    * ``ambiguous_tokens`` — manifest tokens whose tuple resolves to
      more than one catalog row.

    The audit is fail-closed: the audit always counts every manifest
    token. The fixture CLI re-runs the audit after its single flush
    to confirm the staged catalog matches the static audit.
    """
    from backend.services.controlled_railway_calibration_identity import (
        _LOGICAL_IDENTITIES,
    )

    indexed: dict[tuple[str, str, str], int] = {}
    for product in PRODUCT_FIXTURES:
        for presentation_codigo in PRESENTATIONS_BY_CATEGORY[
            product.category_slug
        ]:
            key = (
                product.category_slug,
                product.nombre,
                presentation_codigo,
            )
            indexed[key] = indexed.get(key, 0) + 1

    total = 0
    covered = 0
    missing = 0
    ambiguous = 0
    for token in _LOGICAL_IDENTITIES:
        total += 1
        logical = get_logical_identity(token)
        key = (
            logical.category_slug,
            logical.product_nombre,
            logical.presentation_codigo,
        )
        count = indexed.get(key, 0)
        if count == 0:
            missing += 1
        elif count > 1:
            ambiguous += 1
        else:
            covered += 1
    return {
        "manifest_tokens": total,
        "covered_tokens": covered,
        "missing_tokens": missing,
        "ambiguous_tokens": ambiguous,
    }


def manifest_is_fully_covered() -> bool:
    """Return ``True`` when the static catalog covers the manifest exactly.

    The audit covers every manifest token exactly once and has zero
    missing/ambiguous rows.
    """
    audit = audit_manifest_coverage()
    return (
        audit["covered_tokens"] == audit["manifest_tokens"]
        and audit["missing_tokens"] == 0
        and audit["ambiguous_tokens"] == 0
        and audit["manifest_tokens"] == manifest_token_count()
    )


__all__ = [
    "CATALOG_FIXTURE_VERSION",
    "CATEGORY_FIXTURES",
    "COMMERCE_ESTADO_CODIGO",
    "COMMERCE_FIXTURES",
    "DEDICATED_COMMERCE_SLUG",
    "DEDICATED_TARGET_ENV_VAR",
    "DEDICATED_TARGET_MARKER",
    "PRESENTATIONS_BY_CATEGORY",
    "PRESENTATION_FIXTURES",
    "PRICE_FIXTURES",
    "PRODUCT_FIXTURES",
    "CategoryFixture",
    "CommerceFixture",
    "FixtureCounts",
    "PresentationFixture",
    "ProductFixture",
    "audit_manifest_coverage",
    "expected_fixture_counts",
    "get_catalog_fixture_version",
    "get_dedicated_commerce_slug",
    "get_dedicated_target_env_var",
    "get_dedicated_target_marker",
    "manifest_is_fully_covered",
]
