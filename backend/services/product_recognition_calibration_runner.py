from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.recognizers.product_recognizer_contract import (
    ProductRecognizerProtocol,
    ProductRecognizerResult,
)
from backend.services.product_presentation_vector_match import (
    ProductPresentationVectorMatch,
)
from backend.services.product_recognition_calibration_commerce_catalog import (
    CommerceCatalog,
    StaleCommerceCatalogError,
    fingerprint_commerce_catalog,
    load_commerce_catalog_from_database,
)
from backend.services.product_recognition_calibration_diagnosis import (
    MISMATCH_CATEGORIES,
    classify_mismatch,
    normalize_canonical_id,
)
from backend.services.product_recognition_calibration_policy import (
    HybridDecisionPolicy,
    dataset_fingerprint,
    generate_policy_grid,
    nearest_rank,
    policy_distance,
    validate_dataset,
)


class EmbeddingClient(Protocol):
    def embed_query(self, text: str) -> list[float]: ...


class VectorSearch(Protocol):
    def search_similar(
        self,
        *,
        id_comercio: int,
        query_embedding: Sequence[float],
        top_k: int,
        candidate_producto_presentacion_ids: Sequence[int] | None = None,
    ) -> list[ProductPresentationVectorMatch]: ...


@dataclass
class StageLatency:
    durations_ms: list[float] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0

    def record(self, duration_ms: float, *, succeeded: bool) -> None:
        if math.isfinite(duration_ms):
            self.durations_ms.append(max(0.0, duration_ms))
        if succeeded:
            self.success_count += 1
        else:
            self.failure_count += 1

    def aggregate(self) -> dict[str, int | float | None]:
        return {
            "count": self.success_count + self.failure_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "p50_ms": nearest_rank(self.durations_ms, 0.5),
            "p95_ms": nearest_rank(self.durations_ms, 0.95),
            "max_ms": max(self.durations_ms) if self.durations_ms else None,
        }


@dataclass(frozen=True)
class CaseObservation:
    case_id: str
    fuzzy_ids: tuple[int, ...]
    fuzzy_scores: tuple[float, ...]
    vector_ids: tuple[int, ...]
    vector_scores: tuple[float, ...]
    failure_categories: tuple[str, ...]
    duration_ms: float
    fuzzy_decision: str = ""


@dataclass(frozen=True)
class StrategyPrediction:
    decision: str
    top_id: int | None
    ranking: tuple[int, ...]
    scores: tuple[float, ...]
    canonical: bool
    alias: bool


MISSING_INPUT_REASONS = (
    "missing_primary_metric",
    "missing_required_improvement",
    "missing_false_positive_tolerance",
    "missing_latency_budget",
)


def _fuzzy_ids(result: ProductRecognizerResult) -> tuple[tuple[int, ...], tuple[float, ...]]:
    ids: list[int] = []
    for entry in result.get("encontrados", []) or []:
        try:
            value = normalize_canonical_id(entry)
        except ValueError:
            continue
        if value not in ids:
            ids.append(value)
    for group in result.get("encontrados_posibles", []) or []:
        if group.get("kind") == "category":
            continue
        productos_raw = group.get("productos")
        productos = productos_raw if isinstance(productos_raw, list) else []
        for entry in productos:
            try:
                value = normalize_canonical_id(entry)
            except ValueError:
                continue
            if value not in ids:
                ids.append(value)
    if not ids:
        return (), ()
    return tuple(ids), tuple(
        1.0 if index == 0 else max(0.0, 1.0 - index / len(ids))
        for index in range(len(ids))
    )


def _fuzzy_decision(
    result: ProductRecognizerResult, ids: tuple[int, ...] | None = None,
) -> str:
    """Return the fuzzy decision derived from the typed-union discriminator.

    Returns ``"ambiguous"`` whenever an ``encontrados_posibles`` group
    carries ``kind: "category"``; otherwise falls back to the existing
    id-based logic. Pure function of the recognizer result.
    """
    encontrados_posibles = result.get("encontrados_posibles", []) or []
    for group in encontrados_posibles:
        if group.get("kind") == "category":
            return "ambiguous"
    fuzzy_ids = ids if ids is not None else _fuzzy_ids(result)[0]
    if len(fuzzy_ids) == 0:
        return "unknown"
    if len(fuzzy_ids) == 1:
        return "unique"
    return "ambiguous"


def _exact_flags(case: dict[str, Any], ranking: tuple[int, ...]) -> tuple[bool, bool]:
    normalized = case["input_text"].strip().casefold()
    catalog = case.get("catalog", [])
    canonical = False
    alias = False
    for row in catalog:
        if row.get("producto_presentacion_id") not in ranking:
            continue
        if normalized == str(row.get("producto_nombre", "")).strip().casefold():
            canonical = True
        aliases = row.get("aliases") or {}
        if isinstance(aliases, dict):
            alias_values = [alias for values in aliases.values() for alias in values]
            if normalized in {str(alias).strip().casefold() for alias in alias_values}:
                alias = True
    return canonical, alias


def _decision(
    ranking: tuple[int, ...],
    scores: tuple[float, ...],
    policy: HybridDecisionPolicy,
    canonical: bool,
    alias: bool,
    fuzzy_decision: str = "",
) -> str:
    if ranking and (canonical or alias):
        return "unique"
    if not ranking:
        if fuzzy_decision == "ambiguous":
            return "ambiguous"
        return "unknown"
    top_score = scores[0]
    gap = top_score - scores[1] if len(scores) > 1 else 0.0
    if top_score >= policy.unique_threshold and (
        len(ranking) == 1 or gap >= policy.minimum_score_gap
    ):
        return "unique"
    if len(ranking) > 1 and top_score >= policy.ambiguous_threshold:
        return "ambiguous"
    return "unknown"


def _prediction(
    case: dict[str, Any],
    ids: tuple[int, ...],
    scores: tuple[float, ...],
    policy: HybridDecisionPolicy | None,
    fuzzy_decision: str = "",
) -> StrategyPrediction:
    ranking = ids if policy is None else ids[: policy.vector_top_k]
    ranking_scores = scores if policy is None else scores[: policy.vector_top_k]
    canonical, alias = _exact_flags(case, ranking)
    if policy is None:
        decision = "unique" if len(ranking) == 1 else "ambiguous" if len(ranking) > 1 else "unknown"
    else:
        decision = _decision(ranking, ranking_scores, policy, canonical, alias, fuzzy_decision)
    return StrategyPrediction(
        decision=decision,
        top_id=ranking[0] if ranking else None,
        ranking=ranking,
        scores=ranking_scores,
        canonical=canonical,
        alias=alias,
    )


def _hybrid_prediction(
    case: dict[str, Any], observation: CaseObservation, policy: HybridDecisionPolicy
) -> StrategyPrediction:
    if (
        observation.fuzzy_decision == "unique"
        and not observation.vector_ids
    ):
        canonical, alias = _exact_flags(case, observation.fuzzy_ids)
        return StrategyPrediction(
            decision="unique",
            top_id=observation.fuzzy_ids[0] if observation.fuzzy_ids else None,
            ranking=observation.fuzzy_ids,
            scores=observation.fuzzy_scores,
            canonical=canonical,
            alias=alias,
        )
    if (
        case.get("catalog_scope") == "pending_product_selection_restricted"
        and observation.fuzzy_decision == "ambiguous"
    ):
        canonical, alias = _exact_flags(case, observation.fuzzy_ids)
        return StrategyPrediction(
            decision="ambiguous",
            top_id=observation.fuzzy_ids[0] if observation.fuzzy_ids else None,
            ranking=observation.fuzzy_ids,
            scores=observation.fuzzy_scores,
            canonical=canonical,
            alias=alias,
        )
    encounter: list[int] = []
    for value in observation.fuzzy_ids + observation.vector_ids:
        if value not in encounter:
            encounter.append(value)
    fuzzy = dict(zip(observation.fuzzy_ids, observation.fuzzy_scores))
    vector = dict(
        zip(
            observation.vector_ids[: policy.vector_top_k],
            observation.vector_scores[: policy.vector_top_k],
        )
    )
    values = [
        (
            value,
            policy.fuzzy_weight * fuzzy.get(value, 0.0)
            + policy.vector_weight * vector.get(value, 0.0),
            index,
        )
        for index, value in enumerate(encounter)
    ]
    values.sort(key=lambda item: (-item[1], item[2]))
    ids = tuple(item[0] for item in values)
    scores = tuple(float(item[1]) for item in values)
    return _prediction(case, ids, scores, policy, observation.fuzzy_decision)


def _rate(count: int, denominator: int) -> float | None:
    return count / denominator if denominator else None


def _seed_refs_fingerprint(seed_refs: dict[str, Any]) -> str:
    return dataset_fingerprint({"seed_refs": dict(sorted(seed_refs.items()))})


def _resolved_expected_id(case: dict[str, Any], seed_refs: dict[str, Any]) -> int | None:
    expected = case.get("expected_producto_presentacion_id")
    if expected is not None:
        return normalize_canonical_id(expected)
    reference = case.get("expected_producto_presentacion_id_ref")
    if reference is None:
        return None
    if not isinstance(reference, str) or reference not in seed_refs:
        raise SeedReferenceError(
            case_id=case["case_id"],
            message="missing symbolic reference",
            reference=str(reference),
            expected_commerce=int(case["id_comercio"]),
        )
    return normalize_canonical_id(seed_refs[reference])


def _correct(case: dict[str, Any], prediction: StrategyPrediction) -> bool:
    expected_id = case.get("expected_producto_presentacion_id")
    return prediction.decision == case["expected_decision"] and (
        expected_id is None or prediction.top_id == expected_id
    )


def _strategy_metrics(
    cases: list[dict[str, Any]],
    observations: dict[str, CaseObservation],
    predictions: dict[str, StrategyPrediction],
) -> dict[str, Any]:
    total = len(cases)
    with_id = [case for case in cases if case.get("expected_producto_presentacion_id") is not None]
    presentation = [case for case in cases if case["presentation_resolution_expectation"] != "not_applicable"]
    canonical = [case for case in cases if case["match_expectation"] == "canonical"]
    alias = [case for case in cases if case["match_expectation"] == "alias"]
    restricted = [case for case in cases if case["restricted_candidate_ids"]]
    correct = sum(_correct(case, predictions[case["case_id"]]) for case in cases)
    top_one = sum(
        predictions[case["case_id"]].top_id == case["expected_producto_presentacion_id"]
        for case in with_id
    )
    false_positive = sum(
        prediction.decision == "unique"
        and (
            case["expected_decision"] != "unique"
            or prediction.top_id not in case["allowed_candidate_ids"]
        )
        for case in cases
        for prediction in [predictions[case["case_id"]]]
    )
    non_unknown = [case for case in cases if case["expected_decision"] != "unknown"]
    predicted_unique = [case for case in cases if predictions[case["case_id"]].decision == "unique"]
    expected_ambiguous = [case for case in cases if case["expected_decision"] == "ambiguous"]
    predicted_ambiguous = [case for case in cases if predictions[case["case_id"]].decision == "ambiguous"]
    presentation_correct = sum(
        predictions[case["case_id"]].decision
        == case["presentation_resolution_expectation"]
        or (
            case["presentation_resolution_expectation"] == "resolved"
            and predictions[case["case_id"]].top_id
            == case.get("expected_producto_presentacion_id")
        )
        for case in presentation
    )
    canonical_correct = sum(
        _correct(case, predictions[case["case_id"]])
        and predictions[case["case_id"]].canonical
        for case in canonical
    )
    alias_correct = sum(
        _correct(case, predictions[case["case_id"]])
        and predictions[case["case_id"]].alias
        for case in alias
    )
    restricted_correct = sum(
        set(predictions[case["case_id"]].ranking).issubset(case["allowed_candidate_ids"])
        and not set(predictions[case["case_id"]].ranking).intersection(
            case["restricted_candidate_ids"]
        )
        and _correct(case, predictions[case["case_id"]])
        for case in restricted
    )
    both_top = [
        case
        for case in cases
        if predictions[case["case_id"]].top_id is not None
        and observations[case["case_id"]].vector_ids
    ]
    agreement = sum(
        predictions[case["case_id"]].top_id
        == observations[case["case_id"]].vector_ids[0]
        for case in both_top
    )
    durations = [observations[case["case_id"]].duration_ms for case in cases]
    return {
        "total_cases": total,
        "decision_accuracy": {"count": correct, "denominator": total, "rate": _rate(correct, total)},
        "top_1_accuracy": {"count": top_one, "denominator": len(with_id), "rate": _rate(top_one, len(with_id))},
        "recall_at_top_k": {"count": top_one, "denominator": len(with_id), "rate": _rate(top_one, len(with_id))},
        "false_positives": {"count": false_positive, "denominator": total, "rate": _rate(false_positive, total)},
        "false_unknowns": {
            "count": sum(predictions[case["case_id"]].decision == "unknown" for case in non_unknown),
            "denominator": len(non_unknown),
            "rate": _rate(sum(predictions[case["case_id"]].decision == "unknown" for case in non_unknown), len(non_unknown)),
        },
        "incorrect_unique_decisions": {
            "count": sum(not _correct(case, predictions[case["case_id"]]) for case in predicted_unique),
            "denominator": len(predicted_unique),
            "rate": _rate(sum(not _correct(case, predictions[case["case_id"]]) for case in predicted_unique), len(predicted_unique)),
        },
        "correct_ambiguities": {
            "count": sum(predictions[case["case_id"]].decision == "ambiguous" for case in expected_ambiguous),
            "denominator": len(expected_ambiguous),
            "rate": _rate(sum(predictions[case["case_id"]].decision == "ambiguous" for case in expected_ambiguous), len(expected_ambiguous)),
        },
        "incorrect_ambiguities": {
            "count": sum(case["expected_decision"] != "ambiguous" for case in predicted_ambiguous),
            "denominator": len(predicted_ambiguous),
            "rate": _rate(sum(case["expected_decision"] != "ambiguous" for case in predicted_ambiguous), len(predicted_ambiguous)),
        },
        "presentation_resolution_accuracy": {"count": presentation_correct, "denominator": len(presentation), "rate": _rate(presentation_correct, len(presentation))},
        "canonical_match_accuracy": {"count": canonical_correct, "denominator": len(canonical), "rate": _rate(canonical_correct, len(canonical))},
        "alias_match_accuracy": {"count": alias_correct, "denominator": len(alias), "rate": _rate(alias_correct, len(alias))},
        "restricted_candidate_accuracy": {"count": restricted_correct, "denominator": len(restricted), "rate": _rate(restricted_correct, len(restricted))},
        "top_1_agreement": {"count": agreement, "denominator": len(both_top), "rate": _rate(agreement, len(both_top))},
        "latency_p50": nearest_rank(durations, 0.5),
        "latency_p95": nearest_rank(durations, 0.95),
    }


def _eligibility(
    fuzzy: dict[str, Any],
    hybrid: dict[str, Any],
    eligibility: dict[str, Any] | None,
) -> dict[str, Any]:
    if not eligibility:
        return {"status": "pending", "reasons": list(MISSING_INPUT_REASONS)}
    missing = [key for key in MISSING_INPUT_REASONS if eligibility.get(key.removeprefix("missing_")) is None]
    if missing:
        return {"status": "pending", "reasons": missing}
    reasons: list[str] = []
    primary_metric = eligibility["primary_metric"]
    fuzzy_value = _metric_rate(fuzzy, primary_metric)
    hybrid_value = _metric_rate(hybrid, primary_metric)
    if fuzzy_value is None or hybrid_value is None or hybrid_value - fuzzy_value < eligibility["required_improvement"]:
        reasons.append("primary_metric_improvement_failed")
    if hybrid["false_positives"]["rate"] is not None and hybrid["false_positives"]["rate"] > eligibility["false_positive_tolerance"]:
        reasons.append("false_positive_tolerance_failed")
    if hybrid["restricted_candidate_accuracy"]["rate"] is not None and fuzzy["restricted_candidate_accuracy"]["rate"] is not None and hybrid["restricted_candidate_accuracy"]["rate"] < fuzzy["restricted_candidate_accuracy"]["rate"]:
        reasons.append("restricted_candidate_non_regression_failed")
    for name in ("canonical_match_accuracy", "alias_match_accuracy"):
        if hybrid[name]["rate"] is not None and fuzzy[name]["rate"] is not None and hybrid[name]["rate"] < fuzzy[name]["rate"]:
            reasons.append(f"{name}_failed")
    if hybrid.get("commerce_isolation", {}).get("passed") is False:
        reasons.append("commerce_isolation_failed")
    if hybrid["latency_p95"] is not None and hybrid["latency_p95"] > eligibility["latency_budget"]:
        reasons.append("latency_budget_failed")
    return {"status": "eligible" if not reasons else "not_eligible", "reasons": reasons}


def _metric_rate(metrics: dict[str, Any], name: str) -> float | None:
    value = metrics.get(name)
    return value.get("rate") if isinstance(value, dict) else None


def _difference(left: Any, right: Any) -> float | None:
    left_value = left.get("rate") if isinstance(left, dict) else left
    right_value = right.get("rate") if isinstance(right, dict) else right
    if left_value is None or right_value is None:
        return None
    return abs(float(right_value) - float(left_value))


class SeedReferenceError(ValueError):
    """Raised when a database-backed case declares an invalid seed reference.

    The error message identifies the case, the offending reference or
    candidate, the offending value, and the expected commerce scope so the
    operator can localise the issue without re-reading the dataset.
    """

    def __init__(
        self,
        *,
        case_id: str,
        message: str,
        reference: str | None = None,
        offending_value: Any = None,
        expected_commerce: int | None = None,
    ) -> None:
        prefix = f"{case_id}: {message}"
        if reference is not None:
            prefix += f" reference={reference!r}"
        if offending_value is not None:
            prefix += f" offending_value={offending_value!r}"
        if expected_commerce is not None:
            prefix += f" expected_commerce={expected_commerce}"
        super().__init__(prefix)
        self.case_id = case_id
        self.reference = reference
        self.offending_value = offending_value
        self.expected_commerce = expected_commerce


def _resolve_dataset_eligibility(
    dataset: dict[str, Any], eligibility: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Return the eligibility input consumed by ``_eligibility``.

    Precedence:
      1. Explicit ``eligibility`` argument (always wins).
      2. Optional top-level ``eligibility`` block on the dataset
         (``schema_version >= 3``). The latency budget is read from
         ``latency_budget_ms_p95`` and mapped to ``latency_budget``.
      3. ``None`` (existing ``pending`` fallback).
    """
    if eligibility is not None:
        return eligibility
    block = dataset.get("eligibility")
    if not isinstance(block, dict):
        return None
    return {
        "primary_metric": block["primary_metric"],
        "required_improvement": float(block["required_improvement"]),
        "false_positive_tolerance": float(block["false_positive_tolerance"]),
        "latency_budget": float(block["latency_budget_ms_p95"]),
    }


def _validate_commerce_dynamic_references(
    dataset: dict[str, Any],
    cases: list[dict[str, Any]],
    id_commerce_by_pp_id: dict[int, int],
) -> None:
    """Validate every reference on every ``commerce_dynamic_database`` case.

    Each affected case is checked against its own ``id_comercio`` BEFORE
    the case is evaluated. The check fails fast with a distinct message
    for each failure mode:

    - missing symbolic reference in the dataset ``seed_refs`` map
    - nonexistent resolved ``producto_presentacion_id``
    - cross-commerce ID (the ID belongs to another comercio)
    - ambiguous symbolic resolution (the same key maps to multiple IDs)
    - invalid symbolic reference (non-string, empty, or non-int value)
    - invalid candidate IDs in ``allowed_candidate_ids`` or
      ``restricted_candidate_ids`` (cross-commerce or nonexistent)

    Cases with ``catalog_scope`` other than ``commerce_dynamic_database``
    are not touched: their candidate IDs are not validated against the
    database, their ``id_comercio`` is not forced to ``1``, and their
    fixture IDs are not reinterpreted as production database IDs.
    """
    seed_refs = dataset.get("seed_refs")
    for case in cases:
        if case.get("catalog_scope") != "commerce_dynamic_database":
            continue
        expected_commerce = int(case["id_comercio"])
        ref = case.get("expected_producto_presentacion_id_ref")
        if isinstance(ref, str) and ref and (
            not isinstance(seed_refs, dict) or ref not in seed_refs
        ):
            raise SeedReferenceError(
                case_id=case["case_id"],
                message="missing symbolic reference",
                reference=ref,
                expected_commerce=expected_commerce,
            )
        for key in ("allowed_candidate_ids", "restricted_candidate_ids"):
            for candidate_id in case.get(key, []) or []:
                owner = id_commerce_by_pp_id.get(int(candidate_id))
                if owner is None:
                    raise SeedReferenceError(
                        case_id=case["case_id"],
                        message=f"nonexistent candidate_id in {key}",
                        offending_value=candidate_id,
                        expected_commerce=expected_commerce,
                    )
                if owner != expected_commerce:
                    raise SeedReferenceError(
                        case_id=case["case_id"],
                        message=f"cross-commerce candidate_id in {key}",
                        offending_value=candidate_id,
                        expected_commerce=expected_commerce,
                    )
    if not isinstance(seed_refs, dict):
        return
    for key, value in seed_refs.items():
        if not isinstance(key, str) or not key:
            raise SeedReferenceError(
                case_id="dataset",
                message="invalid seed_refs key",
                reference=key,
                offending_value=value,
            )
        if not isinstance(value, int) or isinstance(value, bool):
            raise SeedReferenceError(
                case_id="dataset",
                message="invalid seed_refs value",
                reference=key,
                offending_value=value,
            )
    seen: dict[str, set[int]] = {}
    for case in cases:
        if case.get("catalog_scope") != "commerce_dynamic_database":
            continue
        ref = case.get("expected_producto_presentacion_id_ref")
        if not (isinstance(ref, str) and ref):
            continue
        if ref not in seed_refs:
            continue
        value = int(seed_refs[ref])
        owner = id_commerce_by_pp_id.get(value)
        if owner is None:
            raise SeedReferenceError(
                case_id=case["case_id"],
                message="nonexistent resolved reference",
                reference=ref,
                offending_value=value,
                expected_commerce=int(case["id_comercio"]),
            )
        if owner != int(case["id_comercio"]):
            raise SeedReferenceError(
                case_id=case["case_id"],
                message="cross-commerce resolved reference",
                reference=ref,
                offending_value=value,
                expected_commerce=int(case["id_comercio"]),
            )
        seen.setdefault(ref, set()).add(value)


def _build_id_commerce_index(
    session: Session | None,
) -> dict[int, int]:
    """Return ``producto_presentacion_id -> id_comercio`` for active rows.

    The lookup is built once per runner call over the existing SQLAlchemy
    session. The runner accepts ``None`` to signal that the database is
    unavailable (e.g. tests with no session); in that case the lookup is
    empty and the runner assumes scopes are already validated by the
    dataset policy.
    """
    if session is None:
        return {}
    from backend.models import (
        CategoriaProducto,
        Presentacion,
        Producto,
        ProductoPresentacion,
    )

    stmt = (
        select(
            ProductoPresentacion.id,
            CategoriaProducto.id_comercio,
        )
        .join(Producto, Producto.id == ProductoPresentacion.id_producto)
        .join(CategoriaProducto, CategoriaProducto.id == Producto.id_categoria_producto)
        .join(Presentacion, Presentacion.id == ProductoPresentacion.id_presentacion)
        .where(Producto.activo.is_(True))
        .where(ProductoPresentacion.activo.is_(True))
        .where(Presentacion.activo.is_(True))
        .where(CategoriaProducto.activo.is_(True))
    )
    return {
        int(pp_id): int(id_comercio)
        for pp_id, id_comercio in session.execute(stmt).all()
    }


class ProductRecognitionCalibrationRunner:
    def __init__(
        self,
        *,
        recognizer: ProductRecognizerProtocol,
        embedding_client: EmbeddingClient,
        vector_search_factory: Callable[[], VectorSearch],
        clock: Callable[[], float] | None = None,
        session: Session | None = None,
    ) -> None:
        import time

        self._recognizer = recognizer
        self._embedding_client = embedding_client
        self._vector_search_factory = vector_search_factory
        self._clock = clock or time.monotonic
        self._session = session
        self._commerce_catalog_cache: dict[int, CommerceCatalog] = {}

    def commerce_catalog_cache_size(self) -> int:
        """Return the number of cached per-commerce catalogs. Test surface."""
        return len(self._commerce_catalog_cache)

    def _resolve_commerce_catalog(
        self,
        dataset: dict[str, Any],
        id_comercio: int,
    ) -> CommerceCatalog:
        """Return the cached fresh DB catalog for ``id_comercio``.

        On first reference, the runner loads the catalog from PostgreSQL
        through :func:`load_commerce_catalog_from_database`, computes
        its fingerprint, and compares it against the persisted
        ``commerce_catalog_fingerprint[str(id_comercio)]``. On mismatch
        — or when the persisted fingerprint is absent — the runner
        raises :class:`StaleCommerceCatalogError` and refuses to start
        the calibration (the CLI converts the refusal into non-zero
        exit and emits no report). On success, the same
        :class:`CommerceCatalog` object is cached on
        ``self._commerce_catalog_cache`` and reused for every subsequent
        case at that commerce.
        """
        cached = self._commerce_catalog_cache.get(id_comercio)
        if cached is not None:
            return cached
        if self._session is None:
            raise StaleCommerceCatalogError(
                id_comercio=id_comercio,
                expected_fingerprint=None,
                actual_fingerprint="unavailable",
            )
        catalog = load_commerce_catalog_from_database(self._session, id_comercio)
        actual_fingerprint = fingerprint_commerce_catalog(catalog)
        fingerprint_block = dataset.get("commerce_catalog_fingerprint")
        expected_fingerprint: str | None = None
        if isinstance(fingerprint_block, dict):
            value = fingerprint_block.get(str(id_comercio))
            if isinstance(value, str):
                expected_fingerprint = value
        if expected_fingerprint is None or expected_fingerprint != actual_fingerprint:
            raise StaleCommerceCatalogError(
                id_comercio=id_comercio,
                expected_fingerprint=expected_fingerprint,
                actual_fingerprint=actual_fingerprint,
            )
        self._commerce_catalog_cache[id_comercio] = catalog
        return catalog

    def _case_catalog(
        self,
        dataset: dict[str, Any],
        case: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Return the catalog the runner hands to the recognizer for ``case``.

        For ``catalog_scope: "commerce_dynamic_database"`` cases the
        runner hands the cached fresh DB catalog — the same
        :class:`CommerceCatalog` object across every case at the
        case's ``id_comercio``. For every other catalog scope the
        embedded ``catalogs[<catalog_fixture>].entries`` is used
        unchanged. The dispatch does NOT consult
        ``allowed_candidate_ids``, ``restricted_candidate_ids``,
        ``expected_decision``, ``expected_producto_presentacion_id``,
        or any other expected-case field.
        """
        if case.get("catalog_scope") == "commerce_dynamic_database":
            catalog = self._resolve_commerce_catalog(dataset, int(case["id_comercio"]))
            return [dict(entry) for entry in catalog.entries]
        return list(dataset["catalogs"][case["catalog_fixture"]].get("entries", []))

    def _flag_fuzzy_boundary_violation(
        self,
        case: dict[str, Any],
        fuzzy_ids: tuple[int, ...],
    ) -> bool:
        """Return ``True`` when the fuzzy recognizer violated the case boundary.

        The check fires when any fuzzy candidate id is in
        ``restricted_candidate_ids`` or — when the case has a non-empty
        ``allowed_candidate_ids`` — when any fuzzy candidate id is
        absent from ``allowed_candidate_ids``. The vector-search
        boundary check at ``runner.py:654-660`` (allowed candidates
        filtered by ``set(case["allowed_candidate_ids"])``) is preserved
        unchanged.
        """
        allowed = set(case.get("allowed_candidate_ids") or [])
        restricted = set(case.get("restricted_candidate_ids") or [])
        for candidate in fuzzy_ids:
            if candidate in restricted:
                return True
            if allowed and candidate not in allowed:
                return True
        return False

    def run(
        self,
        dataset: dict[str, Any],
        *,
        policies: list[HybridDecisionPolicy] | None = None,
        commerce_id: int | None = None,
        limit: int | None = None,
        eligibility: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        validate_dataset(dataset)
        eligibility_input = _resolve_dataset_eligibility(dataset, eligibility)
        id_commerce_by_pp_id = _build_id_commerce_index(self._session)
        selected = [
            case
            for case in dataset["cases"]
            if commerce_id is None or case["id_comercio"] == commerce_id
        ]
        if limit is not None:
            selected = selected[:limit]
        _validate_commerce_dynamic_references(dataset, selected, id_commerce_by_pp_id)
        seed_refs = dataset.get("seed_refs")
        if not isinstance(seed_refs, dict):
            seed_refs = {}
        expected_inventory_fingerprint = dataset.get("inventory_fingerprint")
        current_inventory_fingerprint = _seed_refs_fingerprint(seed_refs)
        if expected_inventory_fingerprint is not None and expected_inventory_fingerprint != current_inventory_fingerprint:
            offending = next(
                (
                    key
                    for key in sorted(seed_refs)
                    if f"{key}={seed_refs[key]}" not in str(expected_inventory_fingerprint)
                ),
                next(iter(seed_refs), "seed_refs"),
            )
            raise SeedReferenceError(
                case_id="dataset",
                message="stale seed_refs relative to inventory fingerprint",
                reference=offending,
                offending_value=expected_inventory_fingerprint,
            )
        selected = [
            {**case, "expected_producto_presentacion_id": _resolved_expected_id(case, seed_refs)}
            for case in selected
        ]
        policies = list(policies or generate_policy_grid())
        observations: dict[str, CaseObservation] = {}
        stage_latencies = {
            name: StageLatency()
            for name in ("fuzzy", "embedding", "vector_search", "evaluation")
        }
        for source_case in selected:
            case = {**source_case, "catalog": self._case_catalog(dataset, source_case)}
            started = self._clock()
            failures: list[str] = []
            fuzzy_decision = ""
            stage_started = self._clock()
            fuzzy_succeeded = True
            try:
                fuzzy_result = self._recognizer.recognize(case["input_text"], case["catalog"])
                fuzzy_ids, fuzzy_scores = _fuzzy_ids(fuzzy_result)
                fuzzy_decision = _fuzzy_decision(fuzzy_result, fuzzy_ids)
            except (RuntimeError, ValueError, TypeError, KeyError, AttributeError):
                fuzzy_ids, fuzzy_scores = (), ()
                failures.append("fuzzy_failure")
                fuzzy_succeeded = False
            stage_latencies["fuzzy"].record(
                (self._clock() - stage_started) * 1000.0,
                succeeded=fuzzy_succeeded,
            )
            vector_ids: tuple[int, ...] = ()
            vector_scores: tuple[float, ...] = ()
            if not failures:
                if self._flag_fuzzy_boundary_violation(case, fuzzy_ids):
                    failures.append("candidate_boundary_violation")
                stage_started = self._clock()
                try:
                    embedding = self._embedding_client.embed_query(case["input_text"])
                except (RuntimeError, ValueError, TypeError, KeyError, AttributeError):
                    failures.append("embedding_failure")
                    stage_latencies["embedding"].record(
                        (self._clock() - stage_started) * 1000.0,
                        succeeded=False,
                    )
                else:
                    stage_latencies["embedding"].record(
                        (self._clock() - stage_started) * 1000.0,
                        succeeded=True,
                    )
                    stage_started = self._clock()
                    vector_succeeded = True
                    try:
                        matches = self._vector_search_factory().search_similar(
                            id_comercio=case["id_comercio"],
                            query_embedding=embedding,
                            top_k=max(policy.vector_top_k for policy in policies),
                            candidate_producto_presentacion_ids=case["allowed_candidate_ids"],
                        )
                        allowed = set(case["allowed_candidate_ids"])
                        if any(match.id_producto_presentacion not in allowed for match in matches):
                            failures.append("candidate_boundary_violation")
                        vector_ids = tuple(match.id_producto_presentacion for match in matches if match.id_producto_presentacion in allowed)
                        vector_scores = tuple(float(match.score) for match in matches if match.id_producto_presentacion in allowed)
                    except (RuntimeError, ValueError, TypeError, KeyError, AttributeError):
                        failures.append("vector_failure")
                        vector_succeeded = False
                    stage_latencies["vector_search"].record(
                        (self._clock() - stage_started) * 1000.0,
                        succeeded=vector_succeeded,
                    )
            observations[case["case_id"]] = CaseObservation(
                case_id=case["case_id"],
                fuzzy_ids=fuzzy_ids,
                fuzzy_scores=fuzzy_scores,
                vector_ids=vector_ids,
                vector_scores=vector_scores,
                failure_categories=tuple(failures),
                duration_ms=max(0.0, (self._clock() - started) * 1000.0),
                fuzzy_decision=fuzzy_decision,
            )
        if not any(not item.failure_categories and item.vector_ids for item in observations.values()):
            raise RuntimeError("no evaluable hybrid cases")
        evaluation_started = self._clock()
        fuzzy_predictions: dict[str, StrategyPrediction] = {}
        policy_reports: list[dict[str, Any]] = []
        cases_with_catalog = {
            case["case_id"]: {**case, "catalog": self._case_catalog(dataset, case)}
            for case in selected
        }
        for case in selected:
            observation = observations[case["case_id"]]
            fuzzy_predictions[case["case_id"]] = _prediction(cases_with_catalog[case["case_id"]], observation.fuzzy_ids, observation.fuzzy_scores, None)
        fuzzy_metrics = _strategy_metrics(selected, observations, fuzzy_predictions)
        for policy in policies:
            predictions = {
                case["case_id"]: _hybrid_prediction(cases_with_catalog[case["case_id"]], observations[case["case_id"]], policy)
                for case in selected
            }
            metrics = _strategy_metrics(selected, observations, predictions)
            policy_reports.append({"policy": policy.__dict__, "metrics": metrics, "distance": policy_distance(policy)})
        best = max(
            enumerate(policy_reports),
            key=lambda item: (
                _metric_rate(item[1]["metrics"], "decision_accuracy") or 0.0,
                -item[1]["metrics"]["false_positives"]["count"],
                -item[1]["metrics"]["incorrect_unique_decisions"]["count"],
                _metric_rate(item[1]["metrics"], "top_1_accuracy") or 0.0,
                -item[1]["metrics"]["false_unknowns"]["count"],
                -item[1]["policy"]["vector_top_k"],
                -item[1]["distance"],
                -item[0],
            ),
        )[1]
        hybrid_metrics = best["metrics"]
        best_policy = HybridDecisionPolicy(**best["policy"])
        selected_predictions = {
            case["case_id"]: _hybrid_prediction(cases_with_catalog[case["case_id"]], observations[case["case_id"]], best_policy)
            for case in selected
        }
        mismatch_counts = {category: 0 for category in MISMATCH_CATEGORIES}
        case_results: list[dict[str, Any]] = []
        for case in selected:
            observation = observations[case["case_id"]]
            fuzzy_prediction = fuzzy_predictions[case["case_id"]]
            hybrid_prediction = selected_predictions[case["case_id"]]
            expected_id = case.get("expected_producto_presentacion_id")
            fuzzy_correct = _correct(case, fuzzy_prediction)
            hybrid_correct = _correct(case, hybrid_prediction)
            result_record: dict[str, Any] = {
                "case_id": case["case_id"],
                "expected_decision": case["expected_decision"],
                "expected_producto_presentacion_id": expected_id,
                "actual_fuzzy_decision": fuzzy_prediction.decision,
                "actual_fuzzy_producto_presentacion_id": fuzzy_prediction.top_id,
                "actual_fuzzy_candidate_ids": list(fuzzy_prediction.ranking),
                "actual_hybrid_decision": hybrid_prediction.decision,
                "actual_hybrid_producto_presentacion_id": hybrid_prediction.top_id,
                "actual_hybrid_candidate_ids": list(hybrid_prediction.ranking),
                "normalized_id_used_by_evaluator": expected_id,
                "presentation_resolution_result": "not_applicable",
                "fuzzy_correct": fuzzy_correct,
                "hybrid_correct": hybrid_correct,
                "id_comercio": case["id_comercio"],
            }
            if hybrid_correct:
                category = "correct"
            else:
                category = classify_mismatch(result_record)
                mismatch_counts[category.value] += 1
            result_record["mismatch_category"] = category
            case_results.append(result_record)
        mismatch_counts["total"] = sum(mismatch_counts.values())
        comparison = [
            {
                "metric": name,
                "fuzzy_baseline": fuzzy_metrics[name]["rate"] if isinstance(fuzzy_metrics.get(name), dict) else fuzzy_metrics.get(name),
                "selected_hybrid_policy": hybrid_metrics[name]["rate"] if isinstance(hybrid_metrics.get(name), dict) else hybrid_metrics.get(name),
                "absolute_difference": _difference(
                    fuzzy_metrics.get(name), hybrid_metrics.get(name)
                ),
            }
            for name in ("decision_accuracy", "top_1_accuracy", "canonical_match_accuracy", "alias_match_accuracy", "restricted_candidate_accuracy")
            if name in fuzzy_metrics
        ]
        diagnostic_records: list[dict[str, Any]] = []
        for case, result in zip(selected, case_results):
            diagnostic_records.append({
                "case_id": case["case_id"],
                "input_text": case["input_text"],
                "category": case["category"],
                "shape": case.get("shape", case["category"]),
                "expected_decision": result["expected_decision"],
                "expected_producto_presentacion_id": result["expected_producto_presentacion_id"],
                "expected_presentacion_id": None,
                "actual_fuzzy_decision": result["actual_fuzzy_decision"],
                "actual_fuzzy_producto_presentacion_id": result["actual_fuzzy_producto_presentacion_id"],
                "actual_fuzzy_presentacion_id": None,
                "actual_fuzzy_candidate_ids": result["actual_fuzzy_candidate_ids"],
                "actual_hybrid_decision": result["actual_hybrid_decision"],
                "actual_hybrid_producto_presentacion_id": result["actual_hybrid_producto_presentacion_id"],
                "actual_hybrid_presentacion_id": None,
                "actual_hybrid_candidate_ids": result["actual_hybrid_candidate_ids"],
                "normalized_id_used_by_evaluator": result["normalized_id_used_by_evaluator"],
                "presentation_resolution_result": result["presentation_resolution_result"],
                "mismatch_category": result["mismatch_category"],
                "evidence": "",
            })
        stage_latencies["evaluation"].record(
            (self._clock() - evaluation_started) * 1000.0,
            succeeded=True,
        )
        failed_case_ids = [case["case_id"] for case in selected if observations[case["case_id"]].failure_categories]
        report = {
            "dataset_version": dataset["schema_version"],
            "dataset_fingerprint": dataset_fingerprint(dataset),
            "case_count": len(selected),
            "policy_count": len(policies),
            "selected_policy": best["policy"],
            "fuzzy_metrics": fuzzy_metrics,
            "hybrid_metrics": hybrid_metrics,
            "vector_metrics": {},
            "mismatch_category_counts": mismatch_counts,
            "case_results": case_results,
            "_diagnostic_records": diagnostic_records,
            "policies": policy_reports,
            "comparison": comparison,
            "infrastructure_failures": len(failed_case_ids),
            "failed_case_ids": failed_case_ids,
            "latency_p50": hybrid_metrics["latency_p50"],
            "latency_p95": hybrid_metrics["latency_p95"],
            "latency_breakdown": {
                name: latency.aggregate()
                for name, latency in stage_latencies.items()
            },
            "eligibility": _eligibility(fuzzy_metrics, hybrid_metrics, eligibility_input),
            "commerce_catalog_cache_size": len(self._commerce_catalog_cache),
        }
        return report


__all__ = [
    "MISSING_INPUT_REASONS",
    "CaseObservation",
    "ProductRecognitionCalibrationRunner",
    "SeedReferenceError",
    "StrategyPrediction",
]
