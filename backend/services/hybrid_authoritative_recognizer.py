"""Subphase 4.12B hybrid authoritative product recognizer.

The recognizer is the opt-in third mode of the shared
``ProductRecognizerProtocol.recognize(...)`` boundary. It runs the
Subphase 4.10 fuzzy + vector pipeline as the Subphase 4.11 calibration
runner specifies, applies the 4.11.5 and 4.11.7 guards verbatim with
the 4.11.5 guard reading ``catalog_scope`` from the new
``intent_metadata`` keyword argument, and returns the hybrid decision
as the four-key ``ProductRecognizerResult`` consumed by the
orchestrators.

Failure modes:

- The commerce-id resolver is ``None`` or returns ``None`` → the
  recognizer returns the fuzzy result byte-for-byte and skips the
  recorder.
- The embedding client or the vector search service raises any
  exception → the recognizer returns the fuzzy result byte-for-byte
  and records the sanitized failure category.
- The filtered vector side is empty after the catalog-scope filter
  is applied → the recognizer continues with the filtered empty
  vector side (this is a valid semantic outcome, not a technical
  failure) and the 4.11.7 guard fires verbatim when the fuzzy
  decision is ``"unique"``.

The recognizer depends only on:

- the injected inner fuzzy recognizer (one-shot per call);
- the injected embedding client (``embed_query`` only);
- the injected per-call vector-search-service factory;
- the calibrated :class:`HybridDecisionPolicy` the loader returned
  to the factory;
- the existing four-key ``ProductRecognizerResult`` contract;
- the catalog argument the caller passes to ``recognize(...)`` — the
  recognizer MUST NOT query or reload the full commerce catalog to
  expand the candidate set.

The recognizer does NOT import FastAPI, the recognizer factory, the
shadow service, the shadowed recognizer, the calibration runner, the
calibration policy module, the seeder, the indexer, the document
builder, the sync service, the admin router, any persistence model,
any intent-specific module, any handler, or any response builder.
It does NOT call ``session.commit`` / ``rollback`` / ``close`` /
``begin`` and does not hold a database session.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from backend.recognizers import product_recognizer as _recognizer_module
from backend.recognizers.product_recognizer_contract import (
    PossibleMatchGroup,
    ProductRecognizerProtocol,
    ProductRecognizerResult,
    RecognizeContext,
    RecognizedProduct,
    UnmatchedFragment,
)
from backend.services.exceptions import HybridAuthoritativeCommerceIdMissing
from backend.services.product_recognition_shadow_comparison import (
    ProductRecognitionHybridObservation,
    ProductRecognitionShadowComparison,
)
from backend.services.shadow_metrics_recorder import ShadowMetricsRecorder

if TYPE_CHECKING:
    from backend.llm.embedding_client import EmbeddingClientProtocol
    from backend.services.product_presentation_vector_search_service import (
        ProductPresentationVectorSearchService,
    )
    from backend.services.product_recognition_calibration_policy import (
        HybridDecisionPolicy,
    )


_RESTRICTED_CATALOG_SCOPE = "pending_product_selection_restricted"


class HybridAuthoritativeProductRecognizer:
    """Authoritative hybrid (fuzzy + vector) recognizer.

    The recognizer is constructed once at factory call time and reused
    for the lifetime of the process. It does NOT reload the policy,
    the embedding client, or the vector-search-service factory on
    every call.
    """

    def __init__(
        self,
        *,
        inner: ProductRecognizerProtocol,
        policy: HybridDecisionPolicy,
        embedding_client: EmbeddingClientProtocol,
        vector_search_service: Callable[[], ProductPresentationVectorSearchService],
        recorder: ShadowMetricsRecorder,
        commerce_id_resolver: Callable[[list[dict]], int | None] | None = None,
        configured_mode: str | None = None,
        effective_mode: str | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._policy = policy
        self._embedding_client = embedding_client
        self._vector_search_service_factory = vector_search_service
        self._recorder = recorder
        self._commerce_id_resolver = commerce_id_resolver
        self._configured_mode = (
            configured_mode
            if configured_mode is not None
            else "hybrid_authoritative"
        )
        self._effective_mode = (
            effective_mode
            if effective_mode is not None
            else "hybrid_authoritative"
        )
        self._clock = clock

    def recognize(
        self,
        text: str,
        catalog: list[dict],
        *,
        intent_metadata: RecognizeContext | None = None,
    ) -> ProductRecognizerResult:
        fuzzy_started = self._clock()
        fuzzy_result = self._inner.recognize(text, catalog)
        fuzzy_latency_ms = max(0.0, (self._clock() - fuzzy_started) * 1000.0)

        fuzzy_candidate_ids, fuzzy_candidate_scores = _collect_fuzzy_candidates(
            fuzzy_result
        )
        fuzzy_decision = _fuzzy_decision(fuzzy_result, fuzzy_candidate_ids)

        allowed_candidate_ids = _build_allowed_candidate_ids(catalog)

        id_comercio = _resolve_id_comercio(
            catalog=catalog,
            intent_metadata=intent_metadata,
            commerce_id_resolver=self._commerce_id_resolver,
        )
        if id_comercio is None:
            raise HybridAuthoritativeCommerceIdMissing(
                "HybridAuthoritativeProductRecognizer requires an "
                "id_comercio from intent_metadata['commerce_id'] or the "
                "injected commerce_id_resolver; the production entry "
                "points (agregar/quitar/modificar/pending selection/"
                "pending modification) thread the commerce_id "
                "explicitly via RecognizeContext.commerce_id."
            )

        (
            raw_vector_ids,
            raw_vector_scores,
            vector_available,
            failure_category,
            embedding_latency_ms,
            vector_latency_ms,
            normalized_text,
        ) = _run_vector_pipeline(
            text=text,
            id_comercio=id_comercio,
            embedding_client=self._embedding_client,
            vector_search_service_factory=self._vector_search_service_factory,
            vector_top_k=self._policy.vector_top_k,
            clock=self._clock,
        )

        if not vector_available:
            observation = _build_hybrid_observation(
                catalog=catalog,
                fuzzy_candidate_ids=fuzzy_candidate_ids,
                fuzzy_candidate_scores=fuzzy_candidate_scores,
                vector_candidate_ids=(),
                vector_candidate_scores=(),
                policy=self._policy,
                fuzzy_decision=fuzzy_decision,
                normalized_text=normalized_text,
            )
            comparison = _build_comparison(
                fuzzy_candidate_ids=fuzzy_candidate_ids,
                fuzzy_candidate_scores=fuzzy_candidate_scores,
                filtered_vector_ids=(),
                filtered_vector_scores=(),
                fuzzy_latency_ms=fuzzy_latency_ms,
                embedding_latency_ms=embedding_latency_ms,
                vector_latency_ms=vector_latency_ms,
                vector_available=False,
                failure_category=failure_category,
                fallback=True,
            )
            self._recorder.record(
                comparison,
                hybrid_observation=observation,
                id_comercio=id_comercio,
                intent=None,
                correlation_id="",
                configured_mode=self._configured_mode,
                effective_mode=self._effective_mode,
                authoritative_strategy="hybrid",
                fallback_category=failure_category,
                mode="hybrid_authoritative",
            )
            return fuzzy_result

        (
            filtered_vector_ids,
            filtered_vector_scores,
        ) = _filter_vector_results_by_allowed_candidates(
            raw_vector_ids=raw_vector_ids,
            raw_vector_scores=raw_vector_scores,
            allowed_candidate_ids=allowed_candidate_ids,
        )

        decision = _decide_hybrid(
            fuzzy_decision=fuzzy_decision,
            intent_metadata=intent_metadata,
            fuzzy_candidate_ids=fuzzy_candidate_ids,
            fuzzy_candidate_scores=fuzzy_candidate_scores,
            filtered_vector_ids=filtered_vector_ids,
            filtered_vector_scores=filtered_vector_scores,
            policy=self._policy,
        )

        ranking, ranking_scores = _build_hybrid_ranking(
            fuzzy_candidate_ids=fuzzy_candidate_ids,
            fuzzy_candidate_scores=fuzzy_candidate_scores,
            filtered_vector_ids=filtered_vector_ids,
            filtered_vector_scores=filtered_vector_scores,
            policy=self._policy,
        )

        result = _translate_hybrid_decision(
            decision=decision,
            ranking=ranking,
            ranking_scores=ranking_scores,
            normalized_text=normalized_text,
            catalog=catalog,
        )

        observation = _build_hybrid_observation(
            catalog=catalog,
            fuzzy_candidate_ids=fuzzy_candidate_ids,
            fuzzy_candidate_scores=fuzzy_candidate_scores,
            vector_candidate_ids=filtered_vector_ids,
            vector_candidate_scores=filtered_vector_scores,
            policy=self._policy,
            fuzzy_decision=fuzzy_decision,
            normalized_text=normalized_text,
        )
        comparison = _build_comparison(
            fuzzy_candidate_ids=fuzzy_candidate_ids,
            fuzzy_candidate_scores=fuzzy_candidate_scores,
            filtered_vector_ids=filtered_vector_ids,
            filtered_vector_scores=filtered_vector_scores,
            fuzzy_latency_ms=fuzzy_latency_ms,
            embedding_latency_ms=embedding_latency_ms,
            vector_latency_ms=vector_latency_ms,
            vector_available=True,
            failure_category=None,
            fallback=False,
        )
        self._recorder.record(
            comparison,
            hybrid_observation=observation,
            id_comercio=id_comercio,
            intent=None,
            correlation_id="",
            configured_mode=self._configured_mode,
            effective_mode=self._effective_mode,
            authoritative_strategy="hybrid",
            mode="hybrid_authoritative",
        )

        return result


def _run_vector_pipeline(
    *,
    text: str,
    id_comercio: int,
    embedding_client: EmbeddingClientProtocol,
    vector_search_service_factory: Callable[[], ProductPresentationVectorSearchService],
    vector_top_k: int,
    clock: Callable[[], float],
) -> tuple[
    tuple[int, ...],
    tuple[float, ...],
    bool,
    str | None,
    float,
    float,
    str,
]:
    """Run the embedding + vector pipeline.

    Returns a 7-tuple of
    ``(vector_ids, vector_scores, vector_available, failure_category,
    embedding_latency_ms, vector_latency_ms, normalized_text)``.

    Any exception is translated to a sanitized failure category and
    ``vector_available=False``. The raw ``vector_ids`` and
    ``vector_scores`` returned by the search service are returned
    verbatim so the catalog-scope filter step can apply the
    ``allowed_candidate_ids`` invariant before any guard, scoring,
    ranking, or translation is consumed.
    """
    embedding_started = clock()
    failure_category: str | None = None
    normalized_text = text
    query_embedding: list[float] = []
    # Broad catch is intentional: any unexpected technical failure must fall back to fuzzy.
    try:
        normalized_text = _recognizer_module._normalizar_texto(text)
    except Exception:  # noqa: BLE001
        embedding_latency_ms = max(0.0, (clock() - embedding_started) * 1000.0)
        return (), (), False, "embedding_failure", embedding_latency_ms, 0.0, text

    if failure_category is None:
        # Broad catch is intentional: any unexpected technical failure must fall back to fuzzy.
        try:
            query_embedding = embedding_client.embed_query(normalized_text)
            embedding_latency_ms = max(
                0.0, (clock() - embedding_started) * 1000.0
            )
        except Exception:  # noqa: BLE001
            embedding_latency_ms = max(
                0.0, (clock() - embedding_started) * 1000.0
            )
            return (
                (),
                (),
                False,
                "embedding_failure",
                embedding_latency_ms,
                0.0,
                normalized_text,
            )

    if failure_category is None:
        vector_started = clock()
        # Broad catch is intentional: any unexpected technical failure must fall back to fuzzy.
        try:
            vector_search_service = vector_search_service_factory()
            matches = vector_search_service.search_similar(
                id_comercio=id_comercio,
                query_embedding=query_embedding,
                top_k=vector_top_k,
                candidate_producto_presentacion_ids=None,
            )
        except Exception:  # noqa: BLE001
            vector_latency_ms = max(0.0, (clock() - vector_started) * 1000.0)
            return (
                (),
                (),
                False,
                "vector_failure",
                embedding_latency_ms,
                vector_latency_ms,
                normalized_text,
            )
        vector_latency_ms = max(0.0, (clock() - vector_started) * 1000.0)
        vector_ids = tuple(int(match.id_producto_presentacion) for match in matches)
        vector_scores = tuple(float(match.score) for match in matches)
        return (
            vector_ids,
            vector_scores,
            True,
            None,
            embedding_latency_ms,
            vector_latency_ms,
            normalized_text,
        )

    return (), (), False, failure_category, 0.0, 0.0, normalized_text


def _build_allowed_candidate_ids(catalog: list[dict]) -> frozenset[int]:
    """Build ``allowed_candidate_ids`` exclusively from the passed catalog.

    The set contains every ``producto_presentacion_id`` present in the
    catalog rows (deduplicated). The recognizer does NOT query or
    reload the full commerce catalog to expand this set and does NOT
    reintroduce candidates discarded by the 4.12A narrowing flow.
    The set is built once per call and reused by every filter,
    guard, scoring step, ranking step, and translation step.
    """
    ids: set[int] = set()
    for row in catalog:
        pid = row.get("producto_presentacion_id")
        if pid is None:
            continue
        ids.add(int(pid))
    return frozenset(ids)


def _filter_vector_results_by_allowed_candidates(
    *,
    raw_vector_ids: tuple[int, ...],
    raw_vector_scores: tuple[float, ...],
    allowed_candidate_ids: frozenset[int],
) -> tuple[tuple[int, ...], tuple[float, ...]]:
    """Filter the raw vector results against ``allowed_candidate_ids``.

    The filtered vector side is the ONLY vector side consumed by the
    4.11.5 guard, the 4.11.7 guard, the hybrid scoring, the hybrid
    ranking, the decision translation, and the recorder observation.
    Duplicate vector IDs in the retained results are deduplicated
    AFTER the filter step (the strongest match wins — the first
    occurrence is retained because the search service returns
    matches in descending score order).

    If no raw vector candidate survives the filter, the filtered
    vector side is empty: the 4.11.7 guard consumes the filtered
    empty ``vector_ids`` and activates verbatim when the fuzzy
    decision is ``"unique"``. Filtering every raw vector result out
    does NOT trigger a technical fallback to fuzzy; the recognizer
    continues with the filtered empty vector side and the existing
    fuzzy pipeline.
    """
    filtered_ids: list[int] = []
    filtered_scores: list[float] = []
    seen: set[int] = set()
    for pid, score in zip(raw_vector_ids, raw_vector_scores):
        if pid not in allowed_candidate_ids:
            continue
        if pid in seen:
            continue
        seen.add(pid)
        filtered_ids.append(int(pid))
        filtered_scores.append(float(score))
    return tuple(filtered_ids), tuple(filtered_scores)


def _decide_hybrid(
    *,
    fuzzy_decision: str,
    intent_metadata: RecognizeContext | None,
    fuzzy_candidate_ids: tuple[int, ...],
    fuzzy_candidate_scores: tuple[float, ...],
    filtered_vector_ids: tuple[int, ...],
    filtered_vector_scores: tuple[float, ...],
    policy: HybridDecisionPolicy,
) -> str:
    """Apply the 4.11.5 and 4.11.7 guards verbatim and return the
    decision the rest of the pipeline must translate.

    The 4.11.5 guard reads ``catalog_scope`` exclusively from
    ``intent_metadata.get("catalog_scope")``; when the metadata is
    ``None`` or its ``catalog_scope`` is not the documented
    ``pending_product_selection_restricted`` literal, the guard is
    short-circuited.

    The 4.11.7 guard is scope-independent and consumes the FILTERED
    ``vector_ids``; it fires verbatim when the fuzzy decision is
    ``"unique"`` AND the filtered vector side is empty, regardless
    of whether the raw search returned results that were discarded
    by the catalog-scope filter.
    """
    if (
        fuzzy_decision == "unique"
        and not filtered_vector_ids
    ):
        return "unique"
    if (
        intent_metadata is not None
        and intent_metadata.get("catalog_scope") == _RESTRICTED_CATALOG_SCOPE
        and fuzzy_decision == "ambiguous"
    ):
        return "ambiguous"

    if not fuzzy_candidate_ids:
        return "unknown"

    ranking, ranking_scores = _build_hybrid_ranking(
        fuzzy_candidate_ids=fuzzy_candidate_ids,
        fuzzy_candidate_scores=fuzzy_candidate_scores,
        filtered_vector_ids=filtered_vector_ids,
        filtered_vector_scores=filtered_vector_scores,
        policy=policy,
    )

    if not ranking or not ranking_scores:
        return "unknown"

    top_score = ranking_scores[0]
    gap = max(0.0, top_score - ranking_scores[1]) if len(ranking_scores) > 1 else 0.0
    if (
        top_score >= policy.ambiguous_threshold
        and len(ranking) > 1
    ):
        return "ambiguous"
    if (
        top_score >= policy.unique_threshold
        and (
            len(ranking) == 1
            or gap >= policy.minimum_score_gap
        )
    ):
        return "unique"
    return "unknown"


def _build_hybrid_ranking(
    *,
    fuzzy_candidate_ids: tuple[int, ...],
    fuzzy_candidate_scores: tuple[float, ...],
    filtered_vector_ids: tuple[int, ...],
    filtered_vector_scores: tuple[float, ...],
    policy: HybridDecisionPolicy,
) -> tuple[tuple[int, ...], tuple[float, ...]]:
    """Build the hybrid ranking from the FILTERED candidates only.

    The fuzzy scoring rule mirrors the 4.10 shadow service: the top
    fuzzy score is ``1.0`` and subsequent scores are non-increasing
    in encounter order. The vector scores are clipped to
    ``policy.vector_top_k`` from the FILTERED ``vector_ids`` /
    ``vector_scores``. The hybrid score is
    ``policy.fuzzy_weight * fuzzy_score + policy.vector_weight * vector_score``.
    No candidate outside ``allowed_candidate_ids`` MAY appear in the
    ranking (the filter has already discarded them).
    """
    if not fuzzy_candidate_ids:
        return (), ()

    fuzzy_score_map = dict(zip(fuzzy_candidate_ids, fuzzy_candidate_scores))
    vector_clipped_ids = filtered_vector_ids[: policy.vector_top_k]
    vector_clipped_scores = filtered_vector_scores[: policy.vector_top_k]
    vector_score_map = dict(zip(vector_clipped_ids, vector_clipped_scores))

    encounter: list[int] = []
    seen: set[int] = set()
    for pid in fuzzy_candidate_ids:
        if pid in seen:
            continue
        seen.add(pid)
        encounter.append(int(pid))
    for pid in vector_clipped_ids:
        if pid in seen:
            continue
        seen.add(pid)
        encounter.append(int(pid))

    combined: list[tuple[int, float, int]] = []
    for index, pid in enumerate(encounter):
        f_score = fuzzy_score_map.get(pid, 0.0)
        v_score = vector_score_map.get(pid, 0.0)
        score = policy.fuzzy_weight * f_score + policy.vector_weight * v_score
        combined.append((pid, score, index))

    combined.sort(key=lambda item: (-item[1], item[2]))
    ranking = tuple(item[0] for item in combined)
    ranking_scores = tuple(float(item[1]) for item in combined)
    return ranking, ranking_scores


def _translate_hybrid_decision(
    *,
    decision: str,
    ranking: tuple[int, ...],
    ranking_scores: tuple[float, ...],
    normalized_text: str,
    catalog: list[dict],
) -> ProductRecognizerResult:
    """Translate the hybrid decision into the four-key
    ``ProductRecognizerResult`` contract.

    The translator consumes the FILTERED ranking; no raw, unfiltered,
    or out-of-scope candidate MAY appear in the translated result.
    Invariants:

    - ``"unique"`` → single-entry ``encontrados`` carrying the
      top-ranked candidate with the deterministic positive quantity
      extracted from the input text and ``texto_origen`` set to the
      normalized input text. The product id is the top-ranked
      candidate from the filtered hybrid ranking; quantity parsing
      does NOT select or re-rank candidates.
    - ``"ambiguous"`` → single ``encontrados_posibles`` group whose
      ``productos`` is the filtered ranking in descending combined
      score order.
    - ``"unknown"`` → single-entry ``no_encontrados`` carrying the
      normalized input text.

    The three other collections are always empty lists (never
    ``None``). Duplicate ``producto_presentacion_id``s are
    deduplicated to the strongest match; descending score order is
    preserved.
    """
    catalog_index = _build_catalog_index(catalog)

    if decision == "unique" and ranking:
        top_id = ranking[0]
        row = catalog_index.get(top_id, {})
        entry: RecognizedProduct = {  # type: ignore[typeddict-item]
            "producto_presentacion_id": top_id,
            "producto_nombre": str(row.get("producto_nombre", "")),
            "cantidad": _extract_deterministic_quantity(normalized_text),
            "texto_origen": normalized_text,
        }
        return {
            "encontrados": [entry],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }

    if decision == "ambiguous" and ranking:
        productos: list[RecognizedProduct] = []
        for index, pid in enumerate(ranking):
            row = catalog_index.get(pid, {})
            entry: RecognizedProduct = {  # type: ignore[typeddict-item]
                "producto_presentacion_id": pid,
                "producto_nombre": str(row.get("producto_nombre", "")),
                "texto_origen": normalized_text,
            }
            productos.append(entry)
        group: PossibleMatchGroup = {
            "texto_origen": normalized_text,
            "productos": productos,
        }
        return {
            "encontrados": [],
            "encontrados_posibles": [group],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }

    fragment: UnmatchedFragment = {"texto_origen": normalized_text}
    return {
        "encontrados": [],
        "encontrados_posibles": [],
        "encontrados_no_disponibles": [],
        "no_encontrados": [fragment],
    }


def _extract_deterministic_quantity(text: str) -> int:
    """Return the positive integer quantity for a ``unique`` hybrid
    translation.

    The helper reuses the existing deterministic
    :func:`product_recognizer._extraer_cantidad` helper against the
    input text. The extractor does NOT consult the catalog, the
    hybrid ranking, the embedding client, the vector-search service,
    any LLM or any database; it is a pure text-to-int helper that
    already powers the inner fuzzy recognizer's quantity parsing.

    When the input omits a valid quantity, the extractor returns its
    documented default of ``1``, which matches the pre-change
    hybrid translation default. The helper therefore preserves the
    default-one behaviour and never widens candidates, reorders
    the ranking, alters the hybrid decision, or selects a candidate.
    """
    return int(_recognizer_module._extraer_cantidad(text))


def _build_catalog_index(catalog: list[dict]) -> dict[int, dict]:
    index: dict[int, dict] = {}
    for row in catalog:
        pid = row.get("producto_presentacion_id")
        if pid is None:
            continue
        index[int(pid)] = row
    return index


def _collect_fuzzy_candidates(
    fuzzy_result: ProductRecognizerResult,
) -> tuple[tuple[int, ...], tuple[float, ...]]:
    """Mirror the 4.10 shadow-service candidate collector.

    The top entry is ``1.0`` and subsequent entries are non-increasing
    confidence proxies aligned with the encounter order. The tuple is
    empty when the fuzzy side produced no candidates. Category-level
    ``encontrados_posibles`` groups (``kind: "category"``) contribute
    zero ids.
    """
    encontrados = fuzzy_result.get("encontrados", []) or []
    encontrados_posibles = fuzzy_result.get("encontrados_posibles", []) or []

    ids: list[int] = []
    for entry in encontrados:
        pid = entry.get("producto_presentacion_id")
        if pid is not None and pid not in ids:
            ids.append(int(pid))
    for group in encontrados_posibles:
        if isinstance(group, dict) and group.get("kind") == "category":
            continue
        productos_raw = group.get("productos") if isinstance(group, dict) else None
        productos = productos_raw if isinstance(productos_raw, list) else []
        for entry in productos:
            pid = entry.get("producto_presentacion_id")
            if pid is not None and pid not in ids:
                ids.append(int(pid))

    if not ids:
        return (), ()

    scores: list[float] = [1.0]
    for index in range(1, len(ids)):
        decay = max(0.0, 1.0 - (index * (1.0 / max(len(ids), 1))))
        scores.append(decay)
    return tuple(ids), tuple(scores)


def _fuzzy_decision(
    fuzzy_result: ProductRecognizerResult,
    fuzzy_candidate_ids: tuple[int, ...],
) -> str:
    if any(
        isinstance(group, dict) and group.get("kind") == "category"
        for group in (fuzzy_result.get("encontrados_posibles") or [])
    ):
        return "ambiguous"
    if len(fuzzy_candidate_ids) == 0:
        return "unknown"
    if len(fuzzy_candidate_ids) == 1:
        return "unique"
    return "ambiguous"


def _build_hybrid_observation(
    *,
    catalog: list[dict],
    fuzzy_candidate_ids: tuple[int, ...],
    fuzzy_candidate_scores: tuple[float, ...],
    vector_candidate_ids: tuple[int, ...],
    vector_candidate_scores: tuple[float, ...],
    policy: HybridDecisionPolicy,
    fuzzy_decision: str,
    normalized_text: str,
) -> ProductRecognitionHybridObservation:
    """Build the recorded hybrid observation.

    The recorded payload is the AUTHORITATIVE payload: the
    ``hybrid_candidate_ranking`` and ``hybrid_combined_scores`` are
    derived from the filtered vector side and the fuzzy side. The
    ``non_authoritative`` flag is ``False`` because the hybrid
    decision is the answer the customer sees.
    """
    encounter: list[int] = []
    seen: set[int] = set()
    for pid in fuzzy_candidate_ids:
        if pid in seen:
            continue
        seen.add(pid)
        encounter.append(int(pid))
    for pid in vector_candidate_ids:
        if pid in seen:
            continue
        seen.add(pid)
        encounter.append(int(pid))

    fuzzy_score_map = dict(zip(fuzzy_candidate_ids, fuzzy_candidate_scores))
    vector_score_map = dict(zip(vector_candidate_ids, vector_candidate_scores))

    combined: list[tuple[int, float, int]] = []
    for index, pid in enumerate(encounter):
        f_score = fuzzy_score_map.get(pid, 0.0)
        v_score = vector_score_map.get(pid, 0.0)
        score = policy.fuzzy_weight * f_score + policy.vector_weight * v_score
        combined.append((pid, score, index))

    combined.sort(key=lambda item: (-item[1], item[2]))
    ranking = tuple(pid for pid, _, _ in combined)
    scores = tuple(float(score) for _, score, _ in combined)

    if len(scores) >= 2:
        gap = max(0.0, scores[0] - scores[1])
    else:
        gap = 0.0

    exact_canonical, exact_alias = _detect_exact_matches(
        normalized_text=normalized_text,
        catalog=catalog,
        ranking=ranking,
    )

    if ranking and (exact_canonical or exact_alias):
        decision = "unique"
    elif not ranking:
        decision = "ambiguous" if fuzzy_decision == "ambiguous" else "unknown"
    elif scores and (
        scores[0] >= policy.unique_threshold
        and (len(ranking) == 1 or gap >= policy.minimum_score_gap)
    ):
        decision = "unique"
    elif (
        scores
        and len(ranking) > 1
        and scores[0] >= policy.ambiguous_threshold
    ):
        decision = "ambiguous"
    else:
        decision = "unknown"

    return ProductRecognitionHybridObservation(
        hybrid_candidate_ranking=ranking,
        hybrid_combined_scores=scores,
        hybrid_top1_top2_gap=gap,
        exact_canonical_match=exact_canonical,
        exact_alias_match=exact_alias,
        decision=decision,
        fuzzy_weight=float(policy.fuzzy_weight),
        vector_weight=float(policy.vector_weight),
        unique_threshold=float(policy.unique_threshold),
        ambiguous_threshold=float(policy.ambiguous_threshold),
        min_score_gap=float(policy.minimum_score_gap),
        non_authoritative=False,
    )


def _detect_exact_matches(
    *,
    normalized_text: str,
    catalog: list[dict],
    ranking: tuple[int, ...],
) -> tuple[bool, bool]:
    """Return ``(exact_canonical_match, exact_alias_match)`` for the
    candidates in the hybrid ranking.

    Mirrors the 4.10 shadow-service helper, but uses the recognizer's
    ``_normalizar_texto`` helper directly so the runtime recognizer
    does not import the calibration runner.
    """
    if not normalized_text or not ranking:
        return False, False

    catalog_index = _build_catalog_index(catalog)
    canonical = False
    alias = False
    for pid in ranking:
        row = catalog_index.get(pid)
        if not row:
            continue
        nombre = row.get("producto_nombre")
        if isinstance(nombre, str) and _recognizer_module._normalizar_texto(
            nombre
        ) == normalized_text:
            canonical = True
        aliases = row.get("aliases") or {}
        for key in ("general_aliases", "specific_aliases"):
            values = aliases.get(key) if isinstance(aliases, dict) else None
            if not values:
                continue
            for alias_value in values:
                if not isinstance(alias_value, str):
                    continue
                if (
                    _recognizer_module._normalizar_texto(alias_value)
                    == normalized_text
                ):
                    alias = True
                    break
            if alias:
                break
    return canonical, alias


def _resolve_id_comercio(
    *,
    catalog: list[dict],
    intent_metadata: RecognizeContext | None,
    commerce_id_resolver: Callable[[list[dict]], int | None] | None,
) -> int | None:
    """Resolve the ``id_comercio`` the hybrid authoritative recognizer needs
    to run its vector-search pipeline.

    The runtime boundary prefers the ``commerce_id`` carried in
    ``intent_metadata`` (added in 4.12B to support
    ``quitar_producto``, ``modificar_producto``, and pending-context
    flows whose catalogs are not the full comercio catalog). When
    the metadata does not carry a commerce id, the resolver
    injected at factory call time is consulted; when neither yields
    an ``int`` the caller has violated the documented contract and
    the recognizer raises :class:`HybridAuthoritativeCommerceIdMissing`
    so the integration bug surfaces immediately instead of being
    hidden behind a silent fallback.
    """
    if intent_metadata is not None:
        metadata_commerce_id = intent_metadata.get("commerce_id")
        if isinstance(metadata_commerce_id, int):
            return metadata_commerce_id
    if commerce_id_resolver is None:
        return None
    try:
        resolved = commerce_id_resolver(catalog)
    except Exception:  # noqa: BLE001 - intentional broad catch
        return None
    if isinstance(resolved, int):
        return resolved
    return None


def _build_comparison(
    *,
    fuzzy_candidate_ids: tuple[int, ...],
    fuzzy_candidate_scores: tuple[float, ...],
    filtered_vector_ids: tuple[int, ...],
    filtered_vector_scores: tuple[float, ...],
    fuzzy_latency_ms: float,
    embedding_latency_ms: float,
    vector_latency_ms: float,
    vector_available: bool,
    failure_category: str | None,
    fallback: bool = False,
) -> ProductRecognitionShadowComparison:
    fuzzy_best_id = fuzzy_candidate_ids[0] if fuzzy_candidate_ids else None
    vector_best_id = filtered_vector_ids[0] if filtered_vector_ids else None
    if not filtered_vector_ids and not filtered_vector_scores:
        agreement = (
            "fuzzy_only"
            if fuzzy_candidate_ids
            else "no_result"
        )
    elif fuzzy_best_id == vector_best_id and fuzzy_best_id is not None:
        agreement = "same_top1"
    elif (
        fuzzy_candidate_ids
        and filtered_vector_ids
        and set(fuzzy_candidate_ids) == set(filtered_vector_ids)
        and fuzzy_best_id != vector_best_id
    ):
        agreement = "same_candidate_set"
    elif fuzzy_candidate_ids and filtered_vector_ids:
        agreement = "different"
    elif fuzzy_candidate_ids:
        agreement = "fuzzy_only"
    elif filtered_vector_ids:
        agreement = "vector_only"
    else:
        agreement = "no_result"

    return ProductRecognitionShadowComparison(
        fuzzy_best_id=fuzzy_best_id,
        vector_best_id=vector_best_id,
        fuzzy_candidate_ids=fuzzy_candidate_ids,
        vector_candidate_ids=filtered_vector_ids,
        fuzzy_candidate_scores=fuzzy_candidate_scores,
        vector_candidate_scores=filtered_vector_scores,
        agreement=agreement,
        fuzzy_latency_ms=float(fuzzy_latency_ms),
        embedding_latency_ms=float(embedding_latency_ms),
        vector_latency_ms=float(vector_latency_ms),
        vector_available=vector_available,
        failure_category=failure_category,
        fallback=fallback,
    )


__all__ = ["HybridAuthoritativeProductRecognizer"]
