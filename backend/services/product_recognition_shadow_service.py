"""Subphase 4.10 shadow service and ``ShadowedProductRecognizer`` decorator.

The shadow service runs the fuzzy and semantic/vector product recognizers
in parallel in opt-in shadow mode and records the comparison payload for
later calibration (Subphase 4.11). The fuzzy recognizer remains the sole
authoritative recognizer; the shadow service never alters the fuzzy result
returned to the caller.

Architecture:

- The fuzzy recognizer is invoked **exactly once** per shadow-mode call.
  The :class:`ShadowedProductRecognizer` decorator runs the inner fuzzy
  recognizer, measures its latency, and forwards the already-computed
  result and latency to the shadow service. The shadow service does NOT
  accept a fuzzy recognizer as a collaborator and does NOT invoke any
  fuzzy recognizer.
- The shadow service depends on the embedding client through the existing
  :class:`backend.llm.embedding_client.EmbeddingClientProtocol`; it does
  NOT import ``OllamaEmbeddingClient`` directly.
- The shadow service depends on the 4.9
  :class:`ProductPresentationVectorSearchService` for the vector search.
- The shadow service trusts ``Settings``. Validators run at
  ``Settings.load()`` time; the shadow service does not re-validate.

Module boundaries:

- The module does NOT import FastAPI, HTTP, the fuzzy recognizer module,
  the document builder, the seeder, the indexer, the sync service, the
  admin router, or any persistence model.
- The module does NOT depend on the concrete ``OllamaEmbeddingClient``;
  the embedding client dependency is the abstract protocol only.
- The module does NOT call ``session.commit``, ``session.rollback``,
  ``session.close``, or ``session.begin``, and it does NOT hold a
  database session.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from backend.recognizers import product_recognizer as _recognizer_module
from backend.recognizers.product_recognizer_contract import (
    ProductRecognizerProtocol,
    ProductRecognizerResult,
    RecognizeContext,
)
from backend.services.product_recognition_shadow_comparison import (
    ProductRecognitionHybridObservation,
    ProductRecognitionShadowComparison,
)
from backend.services.shadow_metrics_recorder import ShadowMetricsRecorder

if TYPE_CHECKING:
    from backend.config.settings import Settings
    from backend.llm.embedding_client import EmbeddingClientProtocol
    from backend.services.product_presentation_vector_search_service import (
        ProductPresentationVectorSearchService,
    )


class ShoppingCartResolver(Protocol):
    """Callable signature for the commerce-id resolver.

    The :class:`ShadowedProductRecognizer` decorator accepts an
    optional ``commerce_id_resolver`` callable. When the resolver is
    ``None`` or returns ``None``, the shadow comparison is skipped and
    the fuzzy result is returned unchanged.
    """

    def __call__(self, catalog: list[dict]) -> int | None: ...


class ProductRecognitionShadowService:
    """Run fuzzy and semantic/vector recognition in parallel and record
    the comparison payload.

    The service is constructed once per process and configured with
    the embedding client, a vector-search-service factory, the loaded
    settings, and the provisional hybrid weights and thresholds. The
    fuzzy recognizer is **not** a collaborator; the service consumes
    the fuzzy result and the measured fuzzy latency the decorator
    already produced.

    The :class:`vector_search_service` parameter is a callable
    ``() -> ProductPresentationVectorSearchService`` so the factory
    can construct the shadow service at orchestrator-import time
    without acquiring a database session. The session-bound
    :class:`ProductPresentationVectorSearchService` is built per call
    by the factory callable; the shadow service does not own a
    session.

    The :meth:`compare` method wraps the embedding and vector steps in
    a broad ``try``/``except``: any exception is translated to a
    sanitized failure category, ``vector_available=False``, and an
    empty vector candidate list. The fuzzy result is returned unchanged
    in both modes.
    """

    def __init__(
        self,
        *,
        embedding_client: EmbeddingClientProtocol,
        vector_search_service: Callable[[], ProductPresentationVectorSearchService],
        settings: Settings,
        fuzzy_weight: float = 0.5,
        vector_weight: float = 0.5,
        unique_threshold: float = 0.7,
        ambiguous_threshold: float = 0.4,
        min_score_gap: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._embedding_client = embedding_client
        self._vector_search_service_factory = vector_search_service
        self._settings = settings
        self._fuzzy_weight = fuzzy_weight
        self._vector_weight = vector_weight
        self._unique_threshold = unique_threshold
        self._ambiguous_threshold = ambiguous_threshold
        self._clock = clock
        self._min_score_gap = (
            min_score_gap
            if min_score_gap is not None
            else settings.shadow_hybrid_min_score_gap
        )

    def compare(
        self,
        text: str,
        catalog: list[dict],
        fuzzy_result: ProductRecognizerResult,
        fuzzy_latency_ms: float,
        id_comercio: int,
    ) -> tuple[ProductRecognitionShadowComparison, ProductRecognitionHybridObservation]:
        """Compare the already-computed fuzzy result against a parallel
        vector search and return the comparison and the observational
        hybrid observation.

        The fuzzy recognizer is NOT invoked. The caller-supplied
        ``fuzzy_result`` and ``fuzzy_latency_ms`` are consumed directly.
        """
        fuzzy_candidate_ids, fuzzy_candidate_scores = _collect_fuzzy_candidates(
            fuzzy_result
        )
        fuzzy_best_id = fuzzy_candidate_ids[0] if fuzzy_candidate_ids else None

        failure_category: str | None = None
        embedding_latency_ms: float = 0.0
        vector_latency_ms: float = 0.0
        vector_candidate_ids: tuple[int, ...] = ()
        vector_candidate_scores: tuple[float, ...] = ()
        vector_best_id: int | None = None
        vector_available = False
        query_embedding: list[float] = []

        embedding_started = self._clock()
        try:
            normalized_text = _recognizer_module._normalizar_texto(text)
        except Exception:  # noqa: BLE001 - intentional broad catch
            embedding_latency_ms = max(
                0.0, (self._clock() - embedding_started) * 1000.0
            )
            failure_category = "embedding_failure"
            normalized_text = text

        if failure_category is None:
            try:
                query_embedding = self._embedding_client.embed_query(
                    normalized_text
                )
                embedding_latency_ms = max(
                    0.0, (self._clock() - embedding_started) * 1000.0
                )
            except Exception:  # noqa: BLE001 - intentional broad catch
                embedding_latency_ms = max(
                    0.0, (self._clock() - embedding_started) * 1000.0
                )
                failure_category = "embedding_failure"

        if failure_category is None:
            vector_started = self._clock()
            try:
                vector_search_service = self._vector_search_service_factory()
                matches = vector_search_service.search_similar(
                    id_comercio=id_comercio,
                    query_embedding=query_embedding,
                    top_k=self._settings.shadow_vector_top_k,
                    candidate_producto_presentacion_ids=None,
                )
            except Exception:  # noqa: BLE001 - intentional broad catch
                vector_latency_ms = max(
                    0.0, (self._clock() - vector_started) * 1000.0
                )
                failure_category = "vector_failure"
            else:
                vector_latency_ms = max(
                    0.0, (self._clock() - vector_started) * 1000.0
                )
                vector_available = True
                vector_candidate_ids = tuple(
                    int(match.id_producto_presentacion) for match in matches
                )
                vector_candidate_scores = tuple(
                    float(match.score) for match in matches
                )
                vector_best_id = (
                    vector_candidate_ids[0] if vector_candidate_ids else None
                )

        agreement = _classify_agreement(
            fuzzy_candidate_ids=fuzzy_candidate_ids,
            vector_candidate_ids=vector_candidate_ids,
            fuzzy_best_id=fuzzy_best_id,
            vector_best_id=vector_best_id,
        )

        comparison = ProductRecognitionShadowComparison(
            fuzzy_best_id=fuzzy_best_id,
            vector_best_id=vector_best_id,
            fuzzy_candidate_ids=fuzzy_candidate_ids,
            vector_candidate_ids=vector_candidate_ids,
            fuzzy_candidate_scores=fuzzy_candidate_scores,
            vector_candidate_scores=vector_candidate_scores,
            agreement=agreement,
            fuzzy_latency_ms=float(fuzzy_latency_ms),
            embedding_latency_ms=float(embedding_latency_ms),
            vector_latency_ms=float(vector_latency_ms),
            vector_available=vector_available,
            failure_category=failure_category,
        )

        hybrid_observation = _build_hybrid_observation(
            text=text,
            catalog=catalog,
            fuzzy_candidate_ids=fuzzy_candidate_ids,
            fuzzy_candidate_scores=fuzzy_candidate_scores,
            vector_candidate_ids=vector_candidate_ids,
            vector_candidate_scores=vector_candidate_scores,
            fuzzy_weight=self._fuzzy_weight,
            vector_weight=self._vector_weight,
            unique_threshold=self._unique_threshold,
            ambiguous_threshold=self._ambiguous_threshold,
            min_score_gap=self._min_score_gap,
        )

        return comparison, hybrid_observation


class ShadowedProductRecognizer:
    """Decorator that wraps an inner product recognizer and records the
    shadow-mode comparison.

    The decorator's ``recognize`` method:

    1. Invokes the inner recognizer exactly once, measures its latency.
    2. Resolves the commerce id through the injected
       ``commerce_id_resolver`` (skipping shadow work when the resolver
       is ``None`` or returns ``None``).
    3. Delegates to ``ProductRecognitionShadowService.compare(text,
       catalog, fuzzy_result, fuzzy_latency_ms, id_comercio)`` and
       forwards the comparison and the hybrid observation to the
       recorder.
    4. Returns the inner recognizer result byte-for-byte unchanged.
    """

    def __init__(
        self,
        *,
        inner: ProductRecognizerProtocol,
        shadow: ProductRecognitionShadowService,
        recorder: ShadowMetricsRecorder,
        commerce_id_resolver: ShoppingCartResolver | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._shadow = shadow
        self._recorder = recorder
        self._commerce_id_resolver = commerce_id_resolver
        self._clock = clock

    def recognize(
        self,
        text: str,
        catalog: list[dict],
        *,
        intent_metadata: RecognizeContext | None = None,
    ) -> ProductRecognizerResult:
        started = self._clock()
        fuzzy_result = self._inner.recognize(text, catalog)
        fuzzy_latency_ms = max(0.0, (self._clock() - started) * 1000.0)

        if self._commerce_id_resolver is None:
            return fuzzy_result
        id_comercio = self._commerce_id_resolver(catalog)
        if id_comercio is None:
            return fuzzy_result

        comparison, hybrid_observation = self._shadow.compare(
            text=text,
            catalog=catalog,
            fuzzy_result=fuzzy_result,
            fuzzy_latency_ms=fuzzy_latency_ms,
            id_comercio=id_comercio,
        )
        self._recorder.record(
            comparison,
            hybrid_observation=hybrid_observation,
            id_comercio=id_comercio,
            intent=None,
            correlation_id="",
        )
        return fuzzy_result


def _collect_fuzzy_candidates(
    fuzzy_result: ProductRecognizerResult,
) -> tuple[tuple[int, ...], tuple[float, ...]]:
    """Collect every ``producto_presentacion_id`` from the fuzzy result
    in encounter order and produce the aligned normalized score tuple.

    The top entry is ``1.0`` and subsequent entries are non-increasing
    confidence proxies aligned with the encounter order. The tuple is
    empty when the fuzzy side produced no candidates. Category-level
    ``encontrados_posibles`` groups (``kind: "category"``) contribute
    zero ids — the category signal carries no product ids and the
    shadow comparison records it via the empty
    ``fuzzy_candidate_ids`` tuple.
    """
    encontrados = fuzzy_result.get("encontrados", []) or []
    encontrados_posibles = fuzzy_result.get("encontrados_posibles", []) or []

    ids: list[int] = []
    for entry in encontrados:
        pid = entry.get("producto_presentacion_id")
        if pid is not None and pid not in ids:
            ids.append(int(pid))
    for group in encontrados_posibles:
        if group.get("kind") == "category":
            continue
        productos_raw = group.get("productos")
        productos = productos_raw if isinstance(productos_raw, list) else []
        for entry in productos:
            pid = entry.get("producto_presentacion_id")
            if pid is not None and pid not in ids:
                ids.append(int(pid))

    if not ids:
        return (), ()

    scores: list[float] = []
    if len(ids) == 1:
        scores = [1.0]
    else:
        scores = [1.0]
        for index in range(1, len(ids)):
            decay = max(0.0, 1.0 - (index * (1.0 / max(len(ids), 1))))
            scores.append(decay)
    return tuple(ids), tuple(scores)


def _classify_agreement(
    *,
    fuzzy_candidate_ids: tuple[int, ...],
    vector_candidate_ids: tuple[int, ...],
    fuzzy_best_id: int | None,
    vector_best_id: int | None,
) -> str:
    """Return the agreement literal in the documented order."""
    if not fuzzy_candidate_ids and not vector_candidate_ids:
        return "no_result"
    if (
        fuzzy_best_id is not None
        and vector_best_id is not None
        and fuzzy_best_id == vector_best_id
    ):
        return "same_top1"
    if (
        fuzzy_candidate_ids
        and vector_candidate_ids
        and set(fuzzy_candidate_ids) == set(vector_candidate_ids)
        and fuzzy_best_id != vector_best_id
    ):
        return "same_candidate_set"
    if fuzzy_candidate_ids and vector_candidate_ids:
        return "different"
    if fuzzy_candidate_ids:
        return "fuzzy_only"
    if vector_candidate_ids:
        return "vector_only"
    return "no_result"


def _build_hybrid_observation(
    *,
    text: str,
    catalog: list[dict],
    fuzzy_candidate_ids: tuple[int, ...],
    fuzzy_candidate_scores: tuple[float, ...],
    vector_candidate_ids: tuple[int, ...],
    vector_candidate_scores: tuple[float, ...],
    fuzzy_weight: float,
    vector_weight: float,
    unique_threshold: float,
    ambiguous_threshold: float,
    min_score_gap: float,
) -> ProductRecognitionHybridObservation:
    """Compute the strictly observational hybrid ranking payload.

    The decision order is fixed:

    1. exact canonical match → ``unique``
    2. exact alias match → ``unique``
    3. vector signal → ``unique`` when the top-1 combined score is
       ``>= unique_threshold`` and the ranked candidate set either
       has exactly one candidate or the top-1/top-2 gap is
       ``>= min_score_gap``
    4. fuzzy complementary signal → ``ambiguous`` when the ranking
       has more than one candidate and the top-1 combined score is
       ``>= ambiguous_threshold``
    5. otherwise ``unknown``.

    The function is purely data: it never mutates the fuzzy result,
    the visible candidates, the pending context, the handlers, the
    responses, or any persistence. The provisional weights and
    thresholds are recorded as ``non_authoritative=True``.
    """
    normalized_text = _recognizer_module._normalizar_texto(text)
    catalog_index = _build_catalog_index(catalog)

    encounter_order: list[int] = []
    seen: set[int] = set()
    for pid in fuzzy_candidate_ids:
        if pid not in seen:
            encounter_order.append(pid)
            seen.add(pid)
    for pid in vector_candidate_ids:
        if pid not in seen:
            encounter_order.append(pid)
            seen.add(pid)

    fuzzy_score_map = dict(zip(fuzzy_candidate_ids, fuzzy_candidate_scores))
    vector_score_map = dict(zip(vector_candidate_ids, vector_candidate_scores))

    combined: list[tuple[int, float, int]] = []
    for index, pid in enumerate(encounter_order):
        f_score = fuzzy_score_map.get(pid, 0.0)
        v_score = vector_score_map.get(pid, 0.0)
        score = fuzzy_weight * f_score + vector_weight * v_score
        combined.append((pid, score, index))

    combined.sort(key=lambda item: (-item[1], item[2]))

    hybrid_candidate_ranking = tuple(pid for pid, _, _ in combined)
    hybrid_combined_scores = tuple(float(score) for _, score, _ in combined)

    if len(hybrid_combined_scores) >= 2:
        hybrid_top1_top2_gap = max(
            0.0, hybrid_combined_scores[0] - hybrid_combined_scores[1]
        )
    else:
        hybrid_top1_top2_gap = 0.0

    exact_canonical_match, exact_alias_match = _detect_exact_matches(
        normalized_text=normalized_text,
        catalog_index=catalog_index,
        candidate_ids=hybrid_candidate_ranking,
    )

    decision = _compute_hybrid_decision(
        exact_canonical_match=exact_canonical_match,
        exact_alias_match=exact_alias_match,
        hybrid_candidate_ranking=hybrid_candidate_ranking,
        hybrid_combined_scores=hybrid_combined_scores,
        hybrid_top1_top2_gap=hybrid_top1_top2_gap,
        unique_threshold=unique_threshold,
        ambiguous_threshold=ambiguous_threshold,
        min_score_gap=min_score_gap,
    )

    return ProductRecognitionHybridObservation(
        hybrid_candidate_ranking=hybrid_candidate_ranking,
        hybrid_combined_scores=hybrid_combined_scores,
        hybrid_top1_top2_gap=hybrid_top1_top2_gap,
        exact_canonical_match=exact_canonical_match,
        exact_alias_match=exact_alias_match,
        decision=decision,
        fuzzy_weight=float(fuzzy_weight),
        vector_weight=float(vector_weight),
        unique_threshold=float(unique_threshold),
        ambiguous_threshold=float(ambiguous_threshold),
        min_score_gap=float(min_score_gap),
        non_authoritative=True,
    )


def _build_catalog_index(catalog: list[dict]) -> dict[int, dict]:
    """Build a ``producto_presentacion_id`` -> ``catalog row`` map.

    The catalog list is the caller-supplied projection (it carries
    ``producto_nombre`` and ``aliases`` for each row). No database
    access is performed.
    """
    index: dict[int, dict] = {}
    for row in catalog:
        pid = row.get("producto_presentacion_id")
        if pid is None:
            continue
        index[int(pid)] = row
    return index


def _detect_exact_matches(
    *,
    normalized_text: str,
    catalog_index: dict[int, dict],
    candidate_ids: tuple[int, ...],
) -> tuple[bool, bool]:
    """Return ``(exact_canonical_match, exact_alias_match)`` for the
    candidates in the hybrid ranking.

    An exact canonical match is ``True`` when the normalized input
    text equals a catalog ``producto_nombre`` for at least one of the
    candidates. An exact alias match is ``True`` when the normalized
    input text equals any applicable alias (general or specific) for
    at least one of the candidates.
    """
    if not normalized_text or not candidate_ids:
        return False, False

    canonical_match = False
    alias_match = False
    for pid in candidate_ids:
        row = catalog_index.get(pid)
        if not row:
            continue
        nombre = row.get("producto_nombre")
        if isinstance(nombre, str) and _recognizer_module._normalizar_texto(
            nombre
        ) == normalized_text:
            canonical_match = True
        aliases = row.get("aliases") or {}
        for key in ("general_aliases", "specific_aliases"):
            values = aliases.get(key) if isinstance(aliases, dict) else None
            if not values:
                continue
            for alias in values:
                if not isinstance(alias, str):
                    continue
                if (
                    _recognizer_module._normalizar_texto(alias)
                    == normalized_text
                ):
                    alias_match = True
                    break
            if alias_match:
                break
    return canonical_match, alias_match


def _compute_hybrid_decision(
    *,
    exact_canonical_match: bool,
    exact_alias_match: bool,
    hybrid_candidate_ranking: tuple[int, ...],
    hybrid_combined_scores: tuple[float, ...],
    hybrid_top1_top2_gap: float,
    unique_threshold: float,
    ambiguous_threshold: float,
    min_score_gap: float,
) -> str:
    """Return the hybrid decision literal in the documented order."""
    if exact_canonical_match and hybrid_candidate_ranking:
        return "unique"
    if exact_alias_match and hybrid_candidate_ranking:
        return "unique"
    if not hybrid_candidate_ranking or not hybrid_combined_scores:
        return "unknown"
    top_score = hybrid_combined_scores[0]
    if (
        top_score >= unique_threshold
        and (
            len(hybrid_candidate_ranking) == 1
            or hybrid_top1_top2_gap >= min_score_gap
        )
    ):
        return "unique"
    if (
        len(hybrid_candidate_ranking) > 1
        and top_score >= ambiguous_threshold
    ):
        return "ambiguous"
    return "unknown"


__all__ = [
    "ProductRecognitionShadowService",
    "ShadowedProductRecognizer",
    "ShoppingCartResolver",
]
