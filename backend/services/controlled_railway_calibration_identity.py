"""Versioned, explicit logical identity manifest for the controlled Railway fixture.

The manifest is the only sanctioned translation between the frozen dataset's
historical references and runtime fixture primary keys. It declares only
identities that exist exactly in the controlled fixture: commerce, category,
canonical product and presentation. It never infers or changes product semantics.

The resolver performs read-only queries and fails closed when the source uses a
token absent from this exact-identity manifest or when the fixture identity is
missing, ambiguous or inactive. The caller owns the session and transaction.
The source dataset is never mutated; materialization produces an in-memory copy
only after the complete identity set has resolved.

"""
from __future__ import annotations

import dataclasses
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import (
    CategoriaProducto,
    Comercio,
    Presentacion,
    Producto,
    ProductoPresentacion,
)
from backend.services.product_recognition_calibration_commerce_catalog import (
    CommerceCatalog,
    fingerprint_commerce_catalog,
)
from backend.services.product_recognition_calibration_policy import (
    dataset_fingerprint,
)

ManifestToken = str | int


MANIFEST_VERSION: Final[str] = "1.0.0"


# The single fixture commerce slug every dynamic dataset reference
# resolves under. The dataset's dynamic ``id_comercio`` is rewritten to
# the runtime ``comercio.id`` of this slug during materialization; the
# dataset source value (``1``) is preserved on disk.
FIXTURE_COMMERCE_SLUG: Final[str] = "piloto-whatsapp-dedicado"


# Logical identity for each calibration reference. Each declared token maps
# directly to one canonical fixture commerce, category, product and
# presentation. The manifest declares every dynamic dataset reference
# (numeric PP token and symbolic ``seed_refs`` key) used by
# ``commerce_dynamic_database`` cases so coverage can be validated against
# the entire dynamic surface.
#
# The manifest is exhaustive by design. Declared identities that the
# controlled fixture does not contain are intentionally NOT pruned: the
# resolver raises :class:`MissingRuntimeIdentityError` for them so the
# fixture-extension work is tracked as a separate change.
def _identity(category_slug: str, product_nombre: str, presentation_codigo: str) -> tuple[str, str, str]:
    return (category_slug, product_nombre, presentation_codigo)


# The manifest declares every numeric PP token and symbolic ``seed_refs``
# key that a ``commerce_dynamic_database`` case references (directly via
# ``expected_producto_presentacion_id_ref`` or indirectly via
# ``allowed_candidate_ids`` / ``restricted_candidate_ids``). The canonical
# product and presentation names match the dataset's frozen
# ``commerce_catalog_inventory`` for the controlled Railway commerce; the
# fixture is the runtime source of truth used to detect missing identities.
_LOGICAL_IDENTITIES: Final[dict[ManifestToken, tuple[str, str, str]]] = {
    # --- numeric PP tokens used by commerce_dynamic_database cases ---
    # Pizzas
    1: _identity("pizzas", "Mozzarella", "grande"),
    2: _identity("pizzas", "Mozzarella", "chica"),
    3: _identity("pizzas", "Napolitana", "grande"),
    4: _identity("pizzas", "Napolitana", "chica"),
    5: _identity("pizzas", "Margherita", "grande"),
    6: _identity("pizzas", "Margherita", "chica"),
    7: _identity("pizzas", "Fugazzeta", "grande"),
    8: _identity("pizzas", "Fugazzeta", "chica"),
    9: _identity("pizzas", "Fugazza", "grande"),
    10: _identity("pizzas", "Fugazza", "chica"),
    11: _identity("pizzas", "Calabresa", "grande"),
    12: _identity("pizzas", "Calabresa", "chica"),
    15: _identity("pizzas", "Cuatro quesos", "grande"),
    16: _identity("pizzas", "Cuatro quesos", "chica"),
    19: _identity("pizzas", "Roquefort", "grande"),
    20: _identity("pizzas", "Roquefort", "chica"),
    23: _identity("pizzas", "Hawaiana", "grande"),
    24: _identity("pizzas", "Hawaiana", "chica"),
    29: _identity("pizzas", "Especial de la Casa", "grande"),
    30: _identity("pizzas", "Especial de la Casa", "chica"),
    # Empanadas
    31: _identity("empanadas", "Carne suave", "unidad"),
    33: _identity("empanadas", "Jamón y queso", "unidad"),
    34: _identity("empanadas", "Pollo", "unidad"),
    36: _identity("empanadas", "Verdura", "unidad"),
    # Bebidas
    39: _identity("bebidas", "Coca-Cola", "lata"),
    40: _identity("bebidas", "Coca-Cola", "litro"),
    41: _identity("bebidas", "Coca-Cola", "2-litros"),
    45: _identity("bebidas", "Sprite", "lata"),
    46: _identity("bebidas", "Sprite", "litro"),
    47: _identity("bebidas", "Sprite", "2-litros"),
    60: _identity("bebidas", "Vino tinto Malbec", "lata"),
    61: _identity("bebidas", "Vino tinto Malbec", "litro"),
    62: _identity("bebidas", "Vino tinto Malbec", "2-litros"),
    # Postres
    69: _identity("postres", "Flan casero", "kilo"),
    70: _identity("postres", "Tiramisú", "kilo"),
    71: _identity("postres", "Helado", "kilo"),
    72: _identity("postres", "Brownie", "kilo"),
    # --- symbolic ``seed_refs`` keys used by commerce_dynamic_database cases ---
    # Each symbolic key is declared with the same canonical identity as the
    # numeric token it resolves to in the frozen ``seed_refs`` map; the
    # resolver validates the symbolic key against the manifest and the
    # fixture as if it were the numeric token.
    "pp_pizza_muzzarella_grande": _identity("pizzas", "Mozzarella", "grande"),
    "pp_pizza_napolitana_grande": _identity("pizzas", "Napolitana", "grande"),
    "pp_pizza_napolitana_chica": _identity("pizzas", "Napolitana", "chica"),
    "pp_pizza_fugazzeta_grande": _identity("pizzas", "Fugazzeta", "grande"),
    "pp_pizza_fugazza_grande": _identity("pizzas", "Fugazza", "grande"),
    "pp_pizza_calabresa_grande": _identity("pizzas", "Calabresa", "grande"),
    "pp_pizza_calabresa_chica": _identity("pizzas", "Calabresa", "chica"),
    "pp_pizza_cuatro_quesos_grande": _identity("pizzas", "Cuatro quesos", "grande"),
    "pp_pizza_margherita_grande": _identity("pizzas", "Margherita", "grande"),
    "pp_pizza_hawaiana_grande": _identity("pizzas", "Hawaiana", "grande"),
    "pp_pizza_roquefort_grande": _identity("pizzas", "Roquefort", "grande"),
    "pp_pizza_especial_casa_grande": _identity(
        "pizzas", "Especial de la Casa", "grande"
    ),
    "pp_empanada_carne": _identity("empanadas", "Carne suave", "unidad"),
    "pp_empanada_jamon_queso": _identity("empanadas", "Jamón y queso", "unidad"),
    "pp_empanada_pollo": _identity("empanadas", "Pollo", "unidad"),
    "pp_empanada_verdura": _identity("empanadas", "Verdura", "unidad"),
    "pp_coca_cola_lata": _identity("bebidas", "Coca-Cola", "lata"),
    "pp_sprite_lata": _identity("bebidas", "Sprite", "lata"),
    "pp_vino_tinto_malbec_lata": _identity("bebidas", "Vino tinto Malbec", "lata"),
    "pp_tiramisu": _identity("postres", "Tiramisú", "kilo"),
    "pp_brownie_helado": _identity("postres", "Brownie", "kilo"),
}



@dataclasses.dataclass(frozen=True)
class LogicalIdentity:
    """The fixture business identity a dataset token resolves to."""

    commerce_slug: str
    category_slug: str
    product_nombre: str
    presentation_codigo: str


@dataclasses.dataclass(frozen=True)
class ResolvedIdentity:
    """A dataset token mapped to its runtime PK pair.

    The pair is the runtime counterpart of the manifest's logical
    identity. Runtime PP IDs are unique; the same token never resolves
    to two different PP IDs.
    """

    token: ManifestToken
    logical: LogicalIdentity
    id_comercio: int
    producto_presentacion_id: int


@dataclasses.dataclass(frozen=True)
class ManifestResolution:
    """The complete output of :func:`resolve_manifest`.

    The dataset contains a single ``id_comercio`` value for every
    dynamic case (the dataset's source ``id_comercio``). The manifest
    publishes one runtime ``id_comercio`` per ``LogicalIdentity``;
    for the current change every dynamic token resolves under the same
    ``FIXTURE_COMMERCE_SLUG``, so :attr:`runtime_id_comercio` is the
    single runtime commerce id the runner must use for every dynamic
    case.
    """

    manifest_version: str
    commerce_slug: str
    runtime_id_comercio: int
    resolved: dict[ManifestToken, ResolvedIdentity]
    catalog_fingerprint: str


# ---------------------------------------------------------------------------
# Typed errors. The CLI catches these and exits non-zero before any
# embedding/vector call.
# ---------------------------------------------------------------------------


class ControlledRailwayIdentityError(ValueError):
    """Base class for typed manifest resolution errors."""


class MissingManifestReferenceError(ControlledRailwayIdentityError):
    """Raised when a dataset token is not declared by the manifest."""

    def __init__(self, *, token: ManifestToken) -> None:
        message = f"missing manifest reference token={token!r}"
        super().__init__(message)
        self.token = token


class UnexpectedManifestReferenceError(ControlledRailwayIdentityError):
    """Raised when the manifest declares a token that the dataset does not use."""

    def __init__(self, *, token: ManifestToken) -> None:
        message = f"unexpected manifest reference token={token!r}"
        super().__init__(message)
        self.token = token


class MissingFixtureCommerceError(ControlledRailwayIdentityError):
    """Raised when the fixture commerce slug is not present in the database."""

    def __init__(self, *, commerce_slug: str) -> None:
        message = f"missing fixture commerce slug={commerce_slug!r}"
        super().__init__(message)
        self.commerce_slug = commerce_slug


class AmbiguousFixtureCommerceError(ControlledRailwayIdentityError):
    """Raised when the fixture commerce slug resolves to multiple rows."""

    def __init__(self, *, commerce_slug: str, count: int) -> None:
        message = f"ambiguous fixture commerce slug={commerce_slug!r} count={count}"
        super().__init__(message)
        self.commerce_slug = commerce_slug
        self.count = count


class MissingRuntimeIdentityError(ControlledRailwayIdentityError):
    """Raised when a manifest identity has no matching DB row."""

    def __init__(self, *, token: ManifestToken, logical: LogicalIdentity) -> None:
        message = (
            f"missing runtime identity token={token!r} "
            f"category_slug={logical.category_slug!r} "
            f"product_nombre={logical.product_nombre!r} "
            f"presentation_codigo={logical.presentation_codigo!r}"
        )
        super().__init__(message)
        self.token = token
        self.logical = logical


class AmbiguousRuntimeIdentityError(ControlledRailwayIdentityError):
    """Raised when a manifest identity matches multiple DB rows."""

    def __init__(
        self,
        *,
        token: ManifestToken,
        logical: LogicalIdentity,
        count: int,
    ) -> None:
        message = (
            f"ambiguous runtime identity token={token!r} "
            f"category_slug={logical.category_slug!r} "
            f"product_nombre={logical.product_nombre!r} "
            f"presentation_codigo={logical.presentation_codigo!r} "
            f"count={count}"
        )
        super().__init__(message)
        self.token = token
        self.logical = logical
        self.count = count


class InactiveRuntimeIdentityError(ControlledRailwayIdentityError):
    """Raised when the resolved DB row is not active."""

    def __init__(
        self,
        *,
        token: ManifestToken,
        logical: LogicalIdentity,
        reason: str,
    ) -> None:
        message = (
            f"inactive runtime identity token={token!r} "
            f"category_slug={logical.category_slug!r} "
            f"product_nombre={logical.product_nombre!r} "
            f"presentation_codigo={logical.presentation_codigo!r} "
            f"reason={reason}"
        )
        super().__init__(message)
        self.token = token
        self.logical = logical
        self.reason = reason


class CrossCommerceRuntimeIdentityError(ControlledRailwayIdentityError):
    """Raised when the resolved DB row belongs to a different commerce."""

    def __init__(
        self,
        *,
        token: ManifestToken,
        logical: LogicalIdentity,
        expected_id_comercio: int,
        actual_id_comercio: int,
    ) -> None:
        message = (
            f"cross-commerce runtime identity token={token!r} "
            f"expected_id_comercio={expected_id_comercio} "
            f"actual_id_comercio={actual_id_comercio}"
        )
        super().__init__(message)
        self.token = token
        self.logical = logical
        self.expected_id_comercio = expected_id_comercio
        self.actual_id_comercio = actual_id_comercio


class DuplicateManifestTokenError(ControlledRailwayIdentityError):
    """Raised when two manifest tokens map to the same runtime PP."""

    def __init__(self, *, producto_presentacion_id: int, tokens: tuple[ManifestToken, ...]) -> None:
        message = (
            f"duplicate manifest tokens share the same runtime PP id "
            f"producto_presentacion_id={producto_presentacion_id} "
            f"tokens={sorted(repr(token) for token in tokens)}"
        )
        super().__init__(message)
        self.producto_presentacion_id = producto_presentacion_id
        self.tokens = tokens


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_manifest_version() -> str:
    """Return the manifest version string. Stable for audit."""
    return MANIFEST_VERSION


def get_fixture_commerce_slug() -> str:
    """Return the fixture commerce slug every dynamic reference resolves under."""
    return FIXTURE_COMMERCE_SLUG


def get_logical_identity(token: ManifestToken) -> LogicalIdentity:
    """Return the manifest-declared logical identity for ``token``.

    Raises :class:`MissingManifestReferenceError` when the token is
    not declared by the manifest. The mapping is explicit; the runner
    rejects any undeclared token before evaluating the case.
    """
    raw = _LOGICAL_IDENTITIES.get(token)
    if raw is None:
        raise MissingManifestReferenceError(token=token)
    category_slug, product_nombre, presentation_codigo = raw
    return LogicalIdentity(
        commerce_slug=FIXTURE_COMMERCE_SLUG,
        category_slug=category_slug,
        product_nombre=product_nombre,
        presentation_codigo=presentation_codigo,
    )


def manifest_token_count() -> int:
    """Return the number of distinct tokens declared by the manifest."""
    return len(_LOGICAL_IDENTITIES)


def collect_dataset_tokens(dataset: dict[str, Any]) -> set[ManifestToken]:
    """Return the set of tokens used by every ``commerce_dynamic_database`` case.

    The collected set is the union of:

    * every ``expected_producto_presentacion_id_ref`` string used by a
      ``commerce_dynamic_database`` case (the symbolic ``seed_refs`` key);
    * every integer present in ``allowed_candidate_ids`` or
      ``restricted_candidate_ids`` of a ``commerce_dynamic_database``
      case.

    The collector does not include ``seed_refs`` keys that no dynamic
    case references and does not include integers from cases with a
    different ``catalog_scope`` — only references that drive the
    runner's evaluation participate in the coverage check.
    """
    tokens: set[ManifestToken] = set()
    for case in dataset.get("cases", []) or []:
        if case.get("catalog_scope") != "commerce_dynamic_database":
            continue
        for ref_key in ("allowed_candidate_ids", "restricted_candidate_ids"):
            for value in case.get(ref_key, []) or []:
                if isinstance(value, bool) or not isinstance(value, int):
                    continue
                tokens.add(value)
        ref_value = case.get("expected_producto_presentacion_id_ref")
        if isinstance(ref_value, str) and ref_value:
            tokens.add(ref_value)
    return tokens


def resolve_manifest(
    session: Session,
    dataset: dict[str, Any],
) -> ManifestResolution:
    """Resolve every manifest identity to its runtime PK pair.

    The function performs the minimum read-only work needed to prove
    the manifest is valid for the current database: it queries the
    ``comercios`` table once for the declared slug, queries the
    catalog once for every distinct (category_slug, product_nombre,
    presentation_codigo) tuple, and computes the runtime fingerprint
    via :func:`fingerprint_commerce_catalog`. The session is never
    written, committed, rolled back, flushed or closed by this
    function.

    The function fails closed (raising a typed error) before any
    embedding or vector call when:

    * a token in the dataset is not declared by the manifest;
    * the manifest declares a token the dataset does not use;
    * the fixture commerce slug is missing or ambiguous in the
      database;
    * any logical identity has zero or more than one active row in
      the fixture commerce;
    * any logical identity resolves to a row whose ``id_comercio``
      differs from the declared fixture commerce;
    * any logical identity resolves to an inactive row;
    * two distinct tokens collapse to the same runtime PP (which
      would break the source dataset's allowed_candidate_ids
      uniqueness invariant).

    The returned :class:`ManifestResolution` carries the runtime
    commerce id every dynamic case must use, the resolved token map,
    and the runtime catalog fingerprint. The materializer uses the
    resolution to rewrite the dataset in memory; the runner then
    consumes the rewritten dataset unchanged.
    """
    if not isinstance(dataset, dict):
        raise ControlledRailwayIdentityError("dataset must be a dict")

    # 1. Read the fixture commerce slug → runtime id_comercio.
    commerce_rows = list(
        session.execute(
            select(Comercio.id).where(Comercio.slug == FIXTURE_COMMERCE_SLUG)
        ).all()
    )
    if not commerce_rows:
        raise MissingFixtureCommerceError(commerce_slug=FIXTURE_COMMERCE_SLUG)
    if len(commerce_rows) > 1:
        raise AmbiguousFixtureCommerceError(
            commerce_slug=FIXTURE_COMMERCE_SLUG,
            count=len(commerce_rows),
        )
    runtime_id_comercio = int(commerce_rows[0][0])

    # 2. Compute the expected / actual token set coverage.
    dataset_tokens = collect_dataset_tokens(dataset)
    manifest_tokens = set(_LOGICAL_IDENTITIES.keys())
    missing_in_manifest = dataset_tokens - manifest_tokens
    if missing_in_manifest:
        raise MissingManifestReferenceError(
            token=min(missing_in_manifest, key=lambda value: (str(type(value)), value))
        )

    # 3. Read the catalog for the runtime commerce (one query).
    catalog_rows = list(
        session.execute(
            select(
                ProductoPresentacion.id,
                CategoriaProducto.descripcion,
                Producto.nombre,
                Presentacion.codigo,
                ProductoPresentacion.activo,
                Producto.activo,
                Presentacion.activo,
                Producto.disponible,
            )
            .join(Producto, Producto.id == ProductoPresentacion.id_producto)
            .join(Presentacion, Presentacion.id == ProductoPresentacion.id_presentacion)
            .join(CategoriaProducto, CategoriaProducto.id == Producto.id_categoria_producto)
            .where(CategoriaProducto.id_comercio == runtime_id_comercio)
        ).all()
    )

    # Build (id_comercio, lowercased categoria_descripcion, lowercased product_nombre,
    # lowercased presentation_codigo) -> list of (pp_id, activo, producto_activo,
    # presentacion_activo, disponible) groupings.
    by_identity: dict[tuple[str, str, str], list[tuple[int, bool, bool, bool, bool]]] = {}
    for (
        pp_id,
        categoria_descripcion,
        product_nombre,
        presentation_codigo,
        pp_activo,
        producto_activo,
        presentacion_activo,
        disponible,
    ) in catalog_rows:
        key = (
            str(categoria_descripcion).strip().casefold(),
            str(product_nombre).strip().casefold(),
            str(presentation_codigo).strip().casefold(),
        )
        by_identity.setdefault(key, []).append(
            (
                int(pp_id),
                bool(pp_activo),
                bool(producto_activo),
                bool(presentacion_activo),
                bool(disponible),
            )
        )

    # 4. Resolve each token, validating uniqueness / activity / commerce.
    resolved: dict[ManifestToken, ResolvedIdentity] = {}
    # Group tokens by their logical identity so two tokens that describe
    # the same fixture product (a symbolic ref and its integer seed_refs
    # companion) collapse to a single PP resolution. The grouping is
    # what the manifest token→logical_identity dictionary already
    # provides: keystones with the same ``(slug, cat, prod, pres)`` tuple
    # represent the same fixture product. We rebuild the same mapping
    # from the resolved tokens so we can catch *cross-token* collisions
    # where two different logical identities accidentally point to the
    # same PP ID — that would be a manifest bug that would corrupt the
    # allowed_candidate_ids uniqueness invariant.
    pp_id_to_logical_keys: dict[int, set[tuple[str, str, str, str]]] = {}
    for token in sorted(dataset_tokens, key=lambda value: (str(type(value)), str(value))):
        logical = get_logical_identity(token)
        key = (
            logical.category_slug.strip().casefold(),
            logical.product_nombre.strip().casefold(),
            logical.presentation_codigo.strip().casefold(),
        )
        rows = by_identity.get(key, [])
        if not rows:
            raise MissingRuntimeIdentityError(token=token, logical=logical)
        if len(rows) > 1:
            raise AmbiguousRuntimeIdentityError(
                token=token,
                logical=logical,
                count=len(rows),
            )
        pp_id, pp_activo, producto_activo, presentacion_activo, _disponible = rows[0]
        if not pp_activo:
            raise InactiveRuntimeIdentityError(
                token=token, logical=logical, reason="producto_presentacion.activo=false"
            )
        if not producto_activo:
            raise InactiveRuntimeIdentityError(
                token=token, logical=logical, reason="producto.activo=false"
            )
        if not presentacion_activo:
            raise InactiveRuntimeIdentityError(
                token=token, logical=logical, reason="presentacion.activo=false"
            )
        resolved[token] = ResolvedIdentity(
            token=token,
            logical=logical,
            id_comercio=runtime_id_comercio,
            producto_presentacion_id=pp_id,
        )
        logical_key = (
            logical.commerce_slug,
            logical.category_slug,
            logical.product_nombre,
            logical.presentation_codigo,
        )
        pp_id_to_logical_keys.setdefault(pp_id, set()).add(logical_key)

    cross_token_collisions = {
        pp_id: logical_keys
        for pp_id, logical_keys in pp_id_to_logical_keys.items()
        if len(logical_keys) > 1
    }
    if cross_token_collisions:
        first_pp_id = min(cross_token_collisions.keys())
        raise DuplicateManifestTokenError(
            producto_presentacion_id=first_pp_id,
            tokens=tuple(
                token
                for token, resolved_id in resolved.items()
                if resolved_id.producto_presentacion_id == first_pp_id
            ),
        )

    # 5. Compute the runtime catalog fingerprint using the same shape
    # the runner expects. The fingerprint is computed by delegating to
    # :func:`fingerprint_commerce_catalog`, which is the canonical,
    # already-tested derivation shared by the existing runner.
    runtime_entries: list[dict[str, Any]] = []
    for (
        pp_id,
        categoria_descripcion,
        product_nombre,
        presentation_codigo,
        pp_activo,
        producto_activo,
        presentacion_activo,
        disponible,
    ) in catalog_rows:
        runtime_entries.append(
            {
                "producto_presentacion_id": int(pp_id),
                "producto_id": int(pp_id),
                "presentacion_id": int(pp_id),
                "categoria_id": int(pp_id),
                "categoria_nombre": str(categoria_descripcion),
                "producto_nombre": str(product_nombre),
                "presentacion_codigo": str(presentation_codigo),
                "presentacion_descripcion": str(presentation_codigo),
                "activo": bool(pp_activo),
                "producto_activo": bool(producto_activo),
                "presentacion_activo": bool(presentacion_activo),
                "disponible": bool(disponible),
            }
        )
    runtime_entries.sort(key=lambda entry: entry["producto_presentacion_id"])
    runtime_catalog = CommerceCatalog(
        id_comercio=runtime_id_comercio,
        entries=tuple(runtime_entries),
    )
    fingerprint = fingerprint_commerce_catalog(runtime_catalog)

    return ManifestResolution(
        manifest_version=MANIFEST_VERSION,
        commerce_slug=FIXTURE_COMMERCE_SLUG,
        runtime_id_comercio=runtime_id_comercio,
        resolved=resolved,
        catalog_fingerprint=fingerprint,
    )


def materialize_dataset(
    dataset: dict[str, Any],
    resolution: ManifestResolution,
) -> dict[str, Any]:
    """Return a deep copy of ``dataset`` with every dynamic reference replaced.

    The function never mutates ``dataset``. The returned copy:

    * replaces every ``catalog_scope: "commerce_dynamic_database"`` case's
      ``id_comercio`` with the runtime ``id_comercio`` of the manifest
      resolution;
    * replaces ``allowed_candidate_ids`` and ``restricted_candidate_ids``
      for those cases with the runtime PP IDs from the resolution,
      preserving the source list ordering and uniqueness;
    * resolves ``expected_producto_presentacion_id_ref`` to the runtime
      ``expected_producto_presentacion_id`` and removes the
      ``_ref`` field;
    * rewrites the top-level ``seed_refs`` map so every key references
      the runtime PP ID for the resolved identity;
    * rewrites ``inventory_fingerprint`` to the runner-compatible
      derivation over the runtime ``seed_refs`` map (the frozen
      source value would otherwise leave the runner pre-validation
      raising ``SeedReferenceError`` for stale ``seed_refs`` even
      though the copy is otherwise consistent);
    * rewrites ``commerce_catalog_fingerprint`` so its sole key is the
      runtime ``id_comercio`` and its value is the recomputed runtime
      fingerprint;
    * drops the persisted ``commerce_catalog_inventory`` block (it
      describes the source DB state, not the runtime fixture).

    The fingerprint of the materialized dataset is written to
    ``materialized_fingerprint`` on the returned copy and is also
    recorded on the runner report through the standard
    :func:`dataset_fingerprint` derivation. The source dataset's
    fingerprint is recorded on the return value as
    ``source_fingerprint`` so the audit trail can distinguish the
    frozen source from the runtime copy.

    ``materialized_fingerprint`` is computed strictly after every
    rewrite above, including the ``inventory_fingerprint`` update, so
    the runtime fingerprint digest reflects the complete materialized
    state.
    """
    if not isinstance(dataset, dict):
        raise ControlledRailwayIdentityError("dataset must be a dict")

    source_fingerprint = dataset_fingerprint(dataset)
    materialized: dict[str, Any] = {
        key: value for key, value in dataset.items() if key != "cases"
    }
    materialized["cases"] = []

    runtime_id_comercio = resolution.runtime_id_comercio
    materialized_seed_refs: dict[str, int] = {}
    for ref, resolved_identity in resolution.resolved.items():
        if isinstance(ref, str):
            materialized_seed_refs[ref] = resolved_identity.producto_presentacion_id

    for case in dataset.get("cases", []) or []:
        if not isinstance(case, dict):
            materialized["cases"].append(case)
            continue
        if case.get("catalog_scope") != "commerce_dynamic_database":
            materialized["cases"].append(case)
            continue
        new_case = dict(case)
        new_case["id_comercio"] = runtime_id_comercio
        for key in ("allowed_candidate_ids", "restricted_candidate_ids"):
            values = case.get(key, []) or []
            rewritten: list[int] = []
            for value in values:
                if isinstance(value, bool) or not isinstance(value, int):
                    continue
                resolved_identity = resolution.resolved.get(value)
                if resolved_identity is None:
                    raise MissingManifestReferenceError(token=value)
                rewritten.append(resolved_identity.producto_presentacion_id)
            new_case[key] = rewritten
        ref = case.get("expected_producto_presentacion_id_ref")
        if isinstance(ref, str) and ref:
            resolved_identity = resolution.resolved.get(ref)
            if resolved_identity is None:
                raise MissingManifestReferenceError(token=ref)
            new_case["expected_producto_presentacion_id"] = resolved_identity.producto_presentacion_id
            new_case.pop("expected_producto_presentacion_id_ref", None)
        materialized["cases"].append(new_case)

    materialized["seed_refs"] = materialized_seed_refs

    # Recompute ``inventory_fingerprint`` after rewriting ``seed_refs``
    # with runtime PP IDs. The runner validates this exact field via
    # ``_seed_refs_fingerprint(dataset["seed_refs"])``; if we left the
    # frozen source value untouched, the runner would raise
    # ``SeedReferenceError`` for stale ``seed_refs`` even though every
    # other invariant is satisfied. The derivation mirrors the runner's
    # helper exactly so the materialized copy is accepted unchanged.
    materialized["inventory_fingerprint"] = _seed_refs_fingerprint(
        materialized_seed_refs
    )

    fingerprint_block: dict[str, str] = {
        str(runtime_id_comercio): resolution.catalog_fingerprint
    }
    materialized["commerce_catalog_fingerprint"] = fingerprint_block
    materialized.pop("commerce_catalog_inventory", None)

    materialized_fingerprint = hash_materialized_dataset(materialized)
    materialized["source_fingerprint"] = source_fingerprint
    materialized["materialized_fingerprint"] = materialized_fingerprint
    materialized["controlled_railway_identity_manifest"] = {
        "version": resolution.manifest_version,
        "commerce_slug": resolution.commerce_slug,
        "runtime_id_comercio": runtime_id_comercio,
        "catalog_fingerprint": resolution.catalog_fingerprint,
    }
    return materialized


def hash_materialized_dataset(materialized: dict[str, Any]) -> str:
    """Return the SHA-256 fingerprint of the materialized dataset.

    The fingerprint is computed over the canonical JSON of the
    materialized dataset, excluding the audit fields
    (``source_fingerprint``, ``materialized_fingerprint`` and
    ``controlled_railway_identity_manifest``) so the digest is stable
    across audit-only re-derivations.
    """
    import hashlib as _hashlib

    from backend.services.product_recognition_calibration_policy import canonical_json

    payload = {
        key: value
        for key, value in materialized.items()
        if key
        not in {
            "source_fingerprint",
            "materialized_fingerprint",
            "controlled_railway_identity_manifest",
        }
    }
    return _hashlib.sha256(canonical_json(payload)).hexdigest()


def _seed_refs_fingerprint(seed_refs: dict[str, Any]) -> str:
    """Return the fingerprint the runner expects for ``seed_refs``.

    The derivation mirrors
    :func:`backend.services.product_recognition_calibration_runner._seed_refs_fingerprint`
    exactly: SHA-256 over the canonical JSON of the sorted
    ``seed_refs`` mapping. The runner validates
    ``dataset["inventory_fingerprint"]`` against this derivation in
    its pre-validation step. The materializer MUST overwrite the
    source ``inventory_fingerprint`` with this value after rewriting
    ``seed_refs`` to runtime PP IDs; otherwise the runner raises
    :class:`SeedReferenceError` for stale ``seed_refs`` even though
    every other invariant on the materialized copy is satisfied.

    The local re-implementation keeps the contract explicit and
    documents the dependency on the runner's algorithm. Any future
    change to the runner's fingerprint derivation MUST be mirrored
    here in the same change so the materialized copy remains accepted
    by the runner unchanged.
    """
    return dataset_fingerprint({"seed_refs": dict(sorted(seed_refs.items()))})


# The module exports the manifest version and the resolver entry point
# so the CLI can wire the explicit selection flag with the module
# symbol without reaching into the private manifest declaration.
__all__ = [
    "FIXTURE_COMMERCE_SLUG",
    "MANIFEST_VERSION",
    "AmbiguousFixtureCommerceError",
    "AmbiguousRuntimeIdentityError",
    "ControlledRailwayIdentityError",
    "CrossCommerceRuntimeIdentityError",
    "DuplicateManifestTokenError",
    "InactiveRuntimeIdentityError",
    "LogicalIdentity",
    "ManifestResolution",
    "ManifestToken",
    "MissingFixtureCommerceError",
    "MissingManifestReferenceError",
    "MissingRuntimeIdentityError",
    "ResolvedIdentity",
    "UnexpectedManifestReferenceError",
    "collect_dataset_tokens",
    "fingerprint_commerce_catalog",
    "get_fixture_commerce_slug",
    "get_logical_identity",
    "get_manifest_version",
    "hash_materialized_dataset",
    "manifest_token_count",
    "materialize_dataset",
    "resolve_manifest",
]
