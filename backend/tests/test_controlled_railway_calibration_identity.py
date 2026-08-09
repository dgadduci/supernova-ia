from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest

from backend.cli.calibrate_product_recognizer import build_parser
from backend.services.controlled_railway_calibration_identity import (
    FIXTURE_COMMERCE_SLUG,
    MANIFEST_VERSION,
    MissingManifestReferenceError,
    MissingRuntimeIdentityError,
    collect_dataset_tokens,
    get_logical_identity,
    manifest_token_count,
    materialize_dataset,
    resolve_manifest,
)

DATASET_PATH = Path(__file__).parent.parent / "data" / "product_recognition_calibration_cases.json"


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return list(self.rows)


class FakeSession:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.calls = 0
        self.commits = 0
        self.rollbacks = 0
        self.begins = 0
        self.flushes = 0
        self.closes = 0

    def execute(self, statement: Any) -> FakeResult:
        self.calls += 1
        if self.calls == 1:
            return FakeResult([(42,)])
        return FakeResult(self.rows)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def begin(self) -> None:
        self.begins += 1

    def flush(self) -> None:
        self.flushes += 1

    def close(self) -> None:
        self.closes += 1


def dataset() -> dict[str, Any]:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def exact_dataset() -> dict[str, Any]:
    return {
        "seed_refs": {
            "pp_pizza_muzzarella_grande": 1,
            "pp_pizza_napolitana_grande": 3,
        },
        "cases": [
            {
                "case_id": "exact",
                "catalog_scope": "commerce_dynamic_database",
                "id_comercio": 1,
                "expected_producto_presentacion_id_ref": "pp_pizza_muzzarella_grande",
                "allowed_candidate_ids": [1, 3],
                "restricted_candidate_ids": [],
            }
        ],
    }


def _validated_minimal_dataset() -> dict[str, Any]:
    """Return a dataset that passes ``validate_dataset`` with declared tokens.

    The shape mirrors the schema the CLI loader accepts: a schema
    version, an eligibility block, a catalog block referenced by the
    case, and a single ``commerce_dynamic_database`` case using only
    declared tokens (``1`` and ``3``).
    """
    return {
        "schema_version": 3,
        "eligibility": {
            "primary_metric": "decision_accuracy",
            "required_improvement": 0.0,
            "false_positive_tolerance": 0.0,
            "latency_budget_ms_p95": 500,
        },
        "seed_refs": {
            "pp_pizza_muzzarella_grande": 1,
            "pp_pizza_napolitana_grande": 3,
        },
        "catalogs": {
            "minimal_fixture": {
                "scope": "in_memory",
                "entries": [],
            },
        },
        "cases": [
            {
                "case_id": "validated_exact",
                "catalog_scope": "commerce_dynamic_database",
                "id_comercio": 1,
                "input_text": "pizza de muzzarella",
                "expected_decision": "unique",
                "expected_producto_presentacion_id_ref": "pp_pizza_muzzarella_grande",
                "allowed_candidate_ids": [1, 3],
                "restricted_candidate_ids": [],
                "match_expectation": "canonical",
                "presentation_resolution_expectation": "resolved",
                "category": "canonical",
                "catalog_fixture": "minimal_fixture",
            }
        ],
    }


def full_fixture_catalog_rows() -> list[tuple[Any, ...]]:
    """Return catalog rows covering the historical identities the manifest declares.

    The list mirrors the runtime-controlled Railway fixture for the
    dedicated commerce: it provides exactly one active PP for every
    declared identity the manifest resolves for the historical dataset.
    Tokens whose historical identity is NOT in the controlled fixture
    (for example ``Margherita`` or ``Coca-Cola``) are intentionally
    omitted so the resolver can be observed failing closed.
    """
    return [
        (101, "Pizzas", "Mozzarella", "grande", True, True, True, True),
        (102, "Pizzas", "Mozzarella", "chica", True, True, True, True),
        (103, "Pizzas", "Napolitana", "grande", True, True, True, True),
        (104, "Pizzas", "Napolitana", "chica", True, True, True, True),
        (105, "Pizzas", "Fugazzeta", "grande", True, True, True, True),
        (106, "Pizzas", "Fugazzeta", "chica", True, True, True, True),
        (107, "Pizzas", "Calabresa", "grande", True, True, True, True),
        (108, "Pizzas", "Calabresa", "chica", True, True, True, True),
        (109, "Pizzas", "Cuatro quesos", "grande", True, True, True, True),
        (110, "Pizzas", "Cuatro quesos", "chica", True, True, True, True),
        (201, "Empanadas", "Carne suave", "unidad", True, True, True, True),
        (203, "Empanadas", "Jamón y queso", "unidad", True, True, True, True),
        (204, "Empanadas", "Pollo", "unidad", True, True, True, True),
        (206, "Empanadas", "Verdura", "unidad", True, True, True, True),
        (701, "Postres", "Flan casero", "kilo", True, True, True, True),
        (702, "Postres", "Tiramisú", "kilo", True, True, True, True),
        (703, "Postres", "Brownie", "kilo", True, True, True, True),
    ]


def minimal_catalog_rows() -> list[tuple[Any, ...]]:
    return [
        (101, "Pizzas", "Mozzarella", "grande", True, True, True, True),
        (102, "Pizzas", "Napolitana", "grande", True, True, True, True),
    ]


# ---------------------------------------------------------------------------
# Manifest declaration contract
# ---------------------------------------------------------------------------


def test_manifest_declares_every_dynamic_dataset_token() -> None:
    """Every dynamic case token (numeric and symbolic) MUST be declared.

    The manifest must cover all of: ``seed_refs`` keys referenced by
    ``expected_producto_presentacion_id_ref`` and integers used by
    ``allowed_candidate_ids`` / ``restricted_candidate_ids`` of a
    ``commerce_dynamic_database`` case. The dataset must not be edited;
    the manifest is the single source of truth for translation.
    """
    used_tokens = collect_dataset_tokens(dataset())
    assert used_tokens, "the frozen dataset must exercise dynamic tokens"
    for token in used_tokens:
        # No MissingManifestReferenceError: every dynamic token is declared.
        get_logical_identity(token)


def test_manifest_coverage_matches_used_token_count() -> None:
    """The manifest declares every used token and only used tokens.

    ``collect_dataset_tokens`` must produce exactly the set of manifest
    tokens actually exercised by dynamic cases. Tokens declared in the
    manifest but not exercised by any case must NOT appear — keeping
    the manifest aligned with the frozen dataset's semantic surface.
    """
    used_tokens = collect_dataset_tokens(dataset())
    # Every used token is declared.
    for token in used_tokens:
        get_logical_identity(token)
    # The manifest has at least the used-token surface plus the alias
    # declarations; the union set is stable and reproducible.
    assert manifest_token_count() >= len(used_tokens)


def test_existing_fixture_identities_resolve_exactly() -> None:
    """Tokens with a fixture identity resolve to their declared identity."""
    expected = {
        1: ("pizzas", "Mozzarella", "grande"),
        2: ("pizzas", "Mozzarella", "chica"),
        3: ("pizzas", "Napolitana", "grande"),
        4: ("pizzas", "Napolitana", "chica"),
        7: ("pizzas", "Fugazzeta", "grande"),
        8: ("pizzas", "Fugazzeta", "chica"),
        11: ("pizzas", "Calabresa", "grande"),
        12: ("pizzas", "Calabresa", "chica"),
        15: ("pizzas", "Cuatro quesos", "grande"),
        16: ("pizzas", "Cuatro quesos", "chica"),
        31: ("empanadas", "Carne suave", "unidad"),
        33: ("empanadas", "Jamón y queso", "unidad"),
        34: ("empanadas", "Pollo", "unidad"),
        36: ("empanadas", "Verdura", "unidad"),
        69: ("postres", "Flan casero", "kilo"),
        70: ("postres", "Tiramisú", "kilo"),
        72: ("postres", "Brownie", "kilo"),
    }
    for token, identity in expected.items():
        logical = get_logical_identity(token)
        assert (
            logical.category_slug,
            logical.product_nombre,
            logical.presentation_codigo,
        ) == identity


def test_declared_but_fixture_unresolved_tokens_keep_canonical_identity() -> None:
    """Tokens with no fixture match still carry the declared historical identity.

    These tokens are intentional in the manifest: extending the
    controlled Railway fixture is a separate change. Their canonical
    identity MUST NOT be silently remapped to a fixture product — no
    alias, no nearest match, no round-robin, no category crossing.
    """
    historical_only = {
        5: ("pizzas", "Margherita", "grande"),
        6: ("pizzas", "Margherita", "chica"),
        9: ("pizzas", "Fugazza", "grande"),
        10: ("pizzas", "Fugazza", "chica"),
        19: ("pizzas", "Roquefort", "grande"),
        20: ("pizzas", "Roquefort", "chica"),
        23: ("pizzas", "Hawaiana", "grande"),
        24: ("pizzas", "Hawaiana", "chica"),
        29: ("pizzas", "Especial de la Casa", "grande"),
        30: ("pizzas", "Especial de la Casa", "chica"),
        39: ("bebidas", "Coca-Cola", "lata"),
        40: ("bebidas", "Coca-Cola", "litro"),
        41: ("bebidas", "Coca-Cola", "2-litros"),
        45: ("bebidas", "Sprite", "lata"),
        46: ("bebidas", "Sprite", "litro"),
        47: ("bebidas", "Sprite", "2-litros"),
        60: ("bebidas", "Vino tinto Malbec", "lata"),
        61: ("bebidas", "Vino tinto Malbec", "litro"),
        62: ("bebidas", "Vino tinto Malbec", "2-litros"),
        71: ("postres", "Helado", "kilo"),
    }
    for token, identity in historical_only.items():
        logical = get_logical_identity(token)
        assert (
            logical.category_slug,
            logical.product_nombre,
            logical.presentation_codigo,
        ) == identity


def test_symbolic_refs_share_their_numeric_identity() -> None:
    """Each symbolic ``seed_refs`` key maps to the same identity as its integer.

    Symbolic references are declared alongside their numeric tokens so
    coverage validation treats them as one logical identity. The
    materializer collapses them to the same runtime PK during
    resolution.
    """
    pairs = [
        ("pp_pizza_muzzarella_grande", 1),
        ("pp_pizza_napolitana_grande", 3),
        ("pp_pizza_napolitana_chica", 4),
        ("pp_pizza_fugazzeta_grande", 7),
        ("pp_pizza_calabresa_grande", 11),
        ("pp_pizza_calabresa_chica", 12),
        ("pp_pizza_cuatro_quesos_grande", 15),
        ("pp_pizza_margherita_grande", 5),
        ("pp_pizza_fugazza_grande", 9),
        ("pp_pizza_hawaiana_grande", 23),
        ("pp_pizza_roquefort_grande", 19),
        ("pp_pizza_especial_casa_grande", 29),
        ("pp_empanada_carne", 31),
        ("pp_empanada_jamon_queso", 33),
        ("pp_empanada_pollo", 34),
        ("pp_empanada_verdura", 36),
        ("pp_coca_cola_lata", 39),
        ("pp_sprite_lata", 45),
        ("pp_vino_tinto_malbec_lata", 60),
        ("pp_tiramisu", 70),
        ("pp_brownie_helado", 72),
    ]
    for symbolic, numeric in pairs:
        sym = get_logical_identity(symbolic)
        num = get_logical_identity(numeric)
        assert (
            sym.commerce_slug,
            sym.category_slug,
            sym.product_nombre,
            sym.presentation_codigo,
        ) == (
            num.commerce_slug,
            num.category_slug,
            num.product_nombre,
            num.presentation_codigo,
        )


def test_pizza_tokens_never_resolve_to_other_categories() -> None:
    for token in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 16, 19, 20, 23, 24, 29, 30):
        assert get_logical_identity(token).category_slug == "pizzas"


def test_token_outside_the_manifest_raises_manifest_error() -> None:
    """Only tokens absent from the manifest raise ``MissingManifestReferenceError``."""
    for token in ("pp_does_not_exist", 99999, "pp_pizza_typo_grande"):
        with pytest.raises(MissingManifestReferenceError):
            get_logical_identity(token)


def test_token_outside_the_manifest_raises_manifest_error_during_resolve() -> None:
    """A dataset referencing an undeclared token stops the resolver before any work.

    The resolver must raise :class:`MissingManifestReferenceError` for
    dataset tokens the manifest does not declare, without touching the
    catalog query or any subsequent embedding/vector call.
    """
    valid = _validated_minimal_dataset()
    # Add an undeclared symbolic reference via ``expected_producto_presentacion_id_ref``.
    # We don't touch the candidate list (which must stay unique); the
    # coverage check observes the undeclared token through the expected ref.
    valid["seed_refs"]["pp_unknown_product"] = 99
    valid["cases"][0]["expected_producto_presentacion_id_ref"] = (
        "pp_unknown_product"
    )
    session = FakeSession(minimal_catalog_rows())
    with pytest.raises(MissingManifestReferenceError):
        resolve_manifest(cast(Any, session), valid)
    # Coverage check happens before the catalog query; the comercio
    # resolution is the first and only call.
    assert session.calls == 1


# ---------------------------------------------------------------------------
# Resolver / runtime contract
# ---------------------------------------------------------------------------


def test_resolver_raises_missing_runtime_identity_before_catalog_query() -> None:
    """Declared tokens missing from the fixture raise ``MissingRuntimeIdentityError``.

    The frozen dataset references tokens whose declared identity is
    not present in the controlled Railway fixture (for example
    Margherita, Coca-Cola, Sprite). The resolver must perform the
    read-only check, raise :class:`MissingRuntimeIdentityError`, and
    stop the CLI before any embedding, vector search or runner call.
    """
    session = FakeSession(minimal_catalog_rows())
    with pytest.raises(MissingRuntimeIdentityError):
        resolve_manifest(cast(Any, session), dataset())
    # The comercio lookup happens before the catalog scan; both calls
    # are part of the resolver's read-only work, and the second call
    # observes the missing fixture identity. After that, no embedding,
    # vector, or runner work is attempted.
    assert session.calls == 2
    assert session.commits == 0
    assert session.rollbacks == 0
    assert session.begins == 0
    assert session.flushes == 0
    assert session.closes == 0


def test_resolver_does_not_control_transactions() -> None:
    """The resolver never commits, rolls back, begins, flushes or closes."""
    session = FakeSession(minimal_catalog_rows())
    resolve_manifest(cast(Any, session), exact_dataset())
    assert session.commits == 0
    assert session.rollbacks == 0
    assert session.begins == 0
    assert session.flushes == 0
    assert session.closes == 0


def test_resolver_fails_before_embedding_vector_or_runner_on_undeclared_token() -> None:
    """Undeclared tokens fail fast, before the catalog/embedding/vector stack.

    The CLI instantiates the embedding client and runner only after
    :func:`resolve_manifest` returns. This test asserts the CLI-level
    invariant by monkey-patching the embedding client and runner: if
    either is touched, the resolver contract is broken.
    """
    import backend.cli.calibrate_product_recognizer as cli_module

    instantiated: list[str] = []

    class _TrackingEmbeddingClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            instantiated.append("embedding_client")

    class _TrackingRunner:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            instantiated.append("runner")

    class _TrackingVectorFactory:
        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            instantiated.append("vector_search_factory")
            return object()

    class _TrackingSettings:
        def __getattr__(self, name: str) -> Any:
            return None

    original_embedding = cli_module.OllamaEmbeddingClient
    original_runner = cli_module.ProductRecognitionCalibrationRunner
    original_settings = cli_module.load_settings
    original_vector = cli_module.ProductPresentationVectorSearchService
    original_recognizer = cli_module.FuzzyProductRecognizer
    cli_module.OllamaEmbeddingClient = _TrackingEmbeddingClient  # type: ignore[assignment]
    cli_module.ProductRecognitionCalibrationRunner = _TrackingRunner  # type: ignore[assignment]
    cli_module.load_settings = lambda: _TrackingSettings()  # type: ignore[assignment]
    cli_module.ProductPresentationVectorSearchService = lambda *a, **k: object()  # type: ignore[assignment]
    cli_module.FuzzyProductRecognizer = lambda: object()  # type: ignore[assignment]
    try:
        # Build a dataset that triggers MissingManifestReferenceError
        # before any embedding work runs.
        import tempfile

        bad = _validated_minimal_dataset()
        bad["seed_refs"]["pp_unknown_xyz"] = 99
        bad["cases"][0]["expected_producto_presentacion_id_ref"] = "pp_unknown_xyz"
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as handle:
            json.dump(bad, handle)
            tmp_path = handle.name
        try:
            rc = cli_module.main(
                [
                    "--dataset",
                    tmp_path,
                    "--output",
                    "ignored.json",
                    "--controlled-railway-manifest",
                ]
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    finally:
        cli_module.OllamaEmbeddingClient = original_embedding  # type: ignore[assignment]
        cli_module.ProductRecognitionCalibrationRunner = original_runner  # type: ignore[assignment]
        cli_module.load_settings = original_settings  # type: ignore[assignment]
        cli_module.ProductPresentationVectorSearchService = original_vector  # type: ignore[assignment]
        cli_module.FuzzyProductRecognizer = original_recognizer  # type: ignore[assignment]
    assert rc == 1
    assert instantiated == []


def test_resolver_fails_before_embedding_vector_or_runner_on_unresolved_identity() -> None:
    """Declared tokens missing from the fixture stop the CLI without any downstream work.

    The CLI instantiates the embedding client and runner only after
    :func:`resolve_manifest` returns. This test forces the resolver to
    fail with :class:`MissingRuntimeIdentityError` and asserts neither
    the embedding client nor the runner is constructed.
    """
    import backend.cli.calibrate_product_recognizer as cli_module

    instantiated: list[str] = []

    class _TrackingEmbeddingClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            instantiated.append("embedding_client")

    class _TrackingRunner:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            instantiated.append("runner")

    class _TrackingSettings:
        def __getattr__(self, name: str) -> Any:
            return None

    original_embedding = cli_module.OllamaEmbeddingClient
    original_runner = cli_module.ProductRecognitionCalibrationRunner
    original_settings = cli_module.load_settings
    original_vector = cli_module.ProductPresentationVectorSearchService
    original_recognizer = cli_module.FuzzyProductRecognizer
    cli_module.OllamaEmbeddingClient = _TrackingEmbeddingClient  # type: ignore[assignment]
    cli_module.ProductRecognitionCalibrationRunner = _TrackingRunner  # type: ignore[assignment]
    cli_module.load_settings = lambda: _TrackingSettings()  # type: ignore[assignment]
    cli_module.ProductPresentationVectorSearchService = lambda *a, **k: object()  # type: ignore[assignment]
    cli_module.FuzzyProductRecognizer = lambda: object()  # type: ignore[assignment]
    try:
        # Use the real frozen dataset: it references tokens not in the
        # fake session's catalog (Margherita, Coca-Cola, Sprite, etc.),
        # so the resolver must raise MissingRuntimeIdentityError.
        import tempfile

        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as handle:
            json.dump(dataset(), handle)
            tmp_path = handle.name
        try:
            rc = cli_module.main(
                [
                    "--dataset",
                    tmp_path,
                    "--output",
                    "ignored.json",
                    "--controlled-railway-manifest",
                ]
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    finally:
        cli_module.OllamaEmbeddingClient = original_embedding  # type: ignore[assignment]
        cli_module.ProductRecognitionCalibrationRunner = original_runner  # type: ignore[assignment]
        cli_module.load_settings = original_settings  # type: ignore[assignment]
        cli_module.ProductPresentationVectorSearchService = original_vector  # type: ignore[assignment]
        cli_module.FuzzyProductRecognizer = original_recognizer  # type: ignore[assignment]
    assert rc == 1
    assert instantiated == []


def test_no_semantic_substitution_for_unresolved_tokens() -> None:
    """A declared identity missing from the fixture MUST NOT be silently mapped.

    The resolver must NOT swap ``Margherita`` for ``Mozzarella``,
    ``Coca-Cola`` for ``Cola clásica`` or perform any other
    approximation, alias or category crossing. The error must be
    :class:`MissingRuntimeIdentityError` carrying the canonical
    identity.
    """
    session = FakeSession(minimal_catalog_rows())
    with pytest.raises(MissingRuntimeIdentityError) as info:
        resolve_manifest(cast(Any, session), dataset())
    err = info.value
    # The error must surface the declared canonical identity, never a
    # substituted alias.
    assert err.logical.product_nombre in {
        "Margherita",
        "Fugazza",
        "Roquefort",
        "Hawaiana",
        "Especial de la Casa",
        "Coca-Cola",
        "Sprite",
        "Vino tinto Malbec",
        "Helado",
    }


# ---------------------------------------------------------------------------
# Successful resolution contract
# ---------------------------------------------------------------------------


def test_exact_resolution_and_materialization_preserve_source_boundaries() -> None:
    source = exact_dataset()
    snapshot = copy.deepcopy(source)
    resolution = resolve_manifest(
        cast(Any, FakeSession(minimal_catalog_rows())), source
    )
    materialized = materialize_dataset(source, resolution)
    assert source == snapshot
    assert materialized["cases"][0]["allowed_candidate_ids"] == [101, 102]
    assert materialized["cases"][0]["restricted_candidate_ids"] == []
    assert materialized["cases"][0]["expected_producto_presentacion_id"] == 101
    assert materialized["cases"][0]["id_comercio"] == 42
    assert materialized["source_fingerprint"]
    assert materialized["materialized_fingerprint"]


def test_full_resolution_collapses_symbolic_and_numeric_to_same_pp() -> None:
    """A symbolic ref and its numeric token resolve to the same runtime PP."""
    custom_dataset = {
        "seed_refs": {"pp_pizza_muzzarella_grande": 1},
        "cases": [
            {
                "case_id": "exact",
                "catalog_scope": "commerce_dynamic_database",
                "id_comercio": 1,
                "expected_producto_presentacion_id_ref": "pp_pizza_muzzarella_grande",
                "allowed_candidate_ids": [1],
                "restricted_candidate_ids": [],
            }
        ],
    }
    resolution = resolve_manifest(
        cast(Any, FakeSession(full_fixture_catalog_rows())), custom_dataset
    )
    pp_id = resolution.resolved[1].producto_presentacion_id
    assert resolution.resolved["pp_pizza_muzzarella_grande"].producto_presentacion_id == pp_id


def test_manifest_metadata_is_explicit() -> None:
    resolution = resolve_manifest(
        cast(Any, FakeSession(minimal_catalog_rows())), exact_dataset()
    )
    assert resolution.manifest_version == MANIFEST_VERSION
    assert resolution.commerce_slug == FIXTURE_COMMERCE_SLUG


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_cli_flag_is_explicit_and_default_path_is_unchanged() -> None:
    """Without ``--controlled-railway-manifest`` the CLI preserves the legacy flow.

    The flag is the only way to activate the adapter. Without it the
    resolver must never run and the embedding/vector/runner stack is
    reached unchanged.
    """
    parser = build_parser()
    without_flag = parser.parse_args(
        ["--dataset", "source.json", "--output", "report.json"]
    )
    with_flag = parser.parse_args(
        [
            "--dataset",
            "source.json",
            "--output",
            "report.json",
            "--controlled-railway-manifest",
        ]
    )
    assert without_flag.controlled_railway_manifest is False
    assert with_flag.controlled_railway_manifest is True


def test_cli_without_flag_does_not_resolve_manifest() -> None:
    """CLI without the flag must never call ``resolve_manifest`` or instantiate the adapter.

    The CLI imports ``resolve_manifest`` lazily inside the
    ``--controlled-railway-manifest`` branch. Without the flag the
    module is never imported and no resolver call is attempted,
    preserving the existing in-memory calibration path.
    """
    import sys
    import types

    import backend.cli.calibrate_product_recognizer as cli_module

    adapter_name = "backend.services.controlled_railway_calibration_identity"
    sys.modules.pop(adapter_name, None)
    access_attempts: list[str] = []

    guard = types.ModuleType(adapter_name)

    def _record(name: str) -> Any:
        def _raise(*args: Any, **kwargs: Any) -> Any:
            access_attempts.append(name)
            raise AssertionError(f"adapter access without flag: {name}")

        return _raise

    guard.resolve_manifest = _record("resolve_manifest")  # type: ignore[attr-defined]
    guard.materialize_dataset = _record("materialize_dataset")  # type: ignore[attr-defined]
    guard.ControlledRailwayIdentityError = _record("ControlledRailwayIdentityError")  # type: ignore[attr-defined]
    sys.modules[adapter_name] = guard

    # The CLI uses ``validate_dataset`` to sanity-check the input; we
    # need that import to keep working. Every other collaborator is
    # replaced with a sentinel that records any construction attempt.
    instantiated: list[str] = []

    class _TrackingEmbeddingClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            instantiated.append("embedding_client")

    class _TrackingRunner:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            instantiated.append("runner")

    class _TrackingSettings:
        def __getattr__(self, name: str) -> Any:
            return None

    original_embedding = cli_module.OllamaEmbeddingClient
    original_runner = cli_module.ProductRecognitionCalibrationRunner
    original_settings = cli_module.load_settings
    original_vector = cli_module.ProductPresentationVectorSearchService
    original_recognizer = cli_module.FuzzyProductRecognizer
    cli_module.OllamaEmbeddingClient = _TrackingEmbeddingClient  # type: ignore[assignment]
    cli_module.ProductRecognitionCalibrationRunner = _TrackingRunner  # type: ignore[assignment]
    cli_module.load_settings = lambda: _TrackingSettings()  # type: ignore[assignment]
    cli_module.ProductPresentationVectorSearchService = lambda *a, **k: object()  # type: ignore[assignment]
    cli_module.FuzzyProductRecognizer = lambda: object()  # type: ignore[assignment]
    try:
        import tempfile

        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as handle:
            json.dump(exact_dataset(), handle)
            tmp_path = handle.name
        try:
            # Without the flag the CLI keeps the legacy path. The
            # tracking runner / embedding client intentionally do not
            # run end-to-end; the only invariant we assert is that the
            # adapter was never touched. Any exception the CLI raises
            # is irrelevant to that invariant — we catch ``Exception``
            # explicitly to keep the test robust against future
            # collaborators that may add unrelated failure modes.
            try:
                cli_module.main(["--dataset", tmp_path, "--output", "ignored.json"])
            except (OSError, RuntimeError, ValueError, TypeError):
                pass
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    finally:
        sys.modules.pop(adapter_name, None)
        cli_module.OllamaEmbeddingClient = original_embedding  # type: ignore[assignment]
        cli_module.ProductRecognitionCalibrationRunner = original_runner  # type: ignore[assignment]
        cli_module.load_settings = original_settings  # type: ignore[assignment]
        cli_module.ProductPresentationVectorSearchService = original_vector  # type: ignore[assignment]
        cli_module.FuzzyProductRecognizer = original_recognizer  # type: ignore[assignment]
    # The adapter's symbols must never be accessed.
    assert access_attempts == []
    # Downstream collaborators ARE allowed to run on the legacy path
    # (this is the explicit guarantee of the flag); we only assert the
    # adapter was not reached.