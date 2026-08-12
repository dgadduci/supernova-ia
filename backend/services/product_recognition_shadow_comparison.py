"""Frozen comparison and hybrid-observation dataclasses for Subphase 4.10.

Subphase 4.10 introduces an opt-in shadow mode that runs the fuzzy
and semantic/vector product recognizers in parallel and records the
comparison payload for later calibration. The two dataclasses here
are the typed contract between the
:class:`ProductRecognitionShadowService` and the
:class:`ShadowMetricsRecorder`:

- :class:`ProductRecognitionShadowComparison` carries the twelve
  documented fields that summarise one shadow-mode call.
- :class:`ProductRecognitionHybridObservation` carries the strictly
  observational hybrid ranking payload produced by the same call.

Both dataclasses are frozen ``@dataclass`` instances. They are
intentionally minimal: they MUST NOT carry the input text, the
customer message, the raw vectors, the embedding prompt, the source
documents, the correlation identifier, the database credentials, or
any internal exception trace. The two dataclasses are the only
public shape the shadow service returns to the recorder.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Agreement = Literal[
    "same_top1",
    "same_candidate_set",
    "different",
    "fuzzy_only",
    "vector_only",
    "no_result",
]


HybridDecision = Literal["unique", "ambiguous", "unknown", "not_evaluated"]


@dataclass(frozen=True)
class ProductRecognitionShadowComparison:
    """Frozen comparison payload for one shadow-mode recognizer call.

    Fields:

    - ``fuzzy_best_id``: the first ``producto_presentacion_id`` in
      ``fuzzy_result["encontrados"]`` (``None`` when the list is empty).
    - ``vector_best_id``: the first
      ``ProductPresentationVectorMatch.id_producto_presentacion``
      (``None`` when the vector pipeline is unavailable or returns no
      matches).
    - ``fuzzy_candidate_ids``: every ``producto_presentacion_id``
      from ``encontrados`` and every ``producto_presentacion_id``
      inside each ``encontrados_posibles[*]["productos"]`` group, in
      encounter order.
    - ``vector_candidate_ids``: every
      ``ProductPresentationVectorMatch.id_producto_presentacion`` in
      match order.
    - ``fuzzy_candidate_scores``: normalized fuzzy scores in
      ``[0.0, 1.0]`` aligned with ``fuzzy_candidate_ids`` in
      encounter order. The top entry is ``1.0`` and subsequent entries
      are non-increasing; the tuple is empty when the fuzzy side
      produced no candidates.
    - ``vector_candidate_scores``: cosine similarity scores in
      ``[0.0, 1.0]`` aligned with ``vector_candidate_ids`` in match
      order; populated from ``ProductPresentationVectorMatch.score``.
    - ``agreement``: one of the documented :data:`Agreement` literals.
    - ``fuzzy_latency_ms``: the fuzzy latency measured by the
      ``ShadowedProductRecognizer`` decorator (caller-supplied).
    - ``embedding_latency_ms``: the elapsed time of the embedding
      query (``0.0`` when the embedding pipeline is unavailable).
    - ``vector_latency_ms``: the elapsed time of the vector search
      (``0.0`` when the vector pipeline is unavailable).
    - ``vector_available``: ``True`` when the embedding client and
      the vector search service both completed successfully.
    - ``failure_category``: sanitized shadow-pipeline failure category
      (``"embedding_failure"``, ``"vector_failure"``, or ``None``
      when both pipelines succeeded). The recorder applies the
      ``"unknown"`` fallback on its own; the comparison itself never
      carries ``"unknown"``.
    - ``fallback``: explicit ``True`` when the recognizer returned
      the fuzzy result instead of the hybrid (or shadow) decision
      for an approved technical reason. ``False`` when the hybrid
      (or shadow) decision was authoritative. Semantic hybrid
      outcomes (``unknown`` / ``ambiguous`` / filtered-empty
      vector) never set this flag.

    The dataclass is a plain ``frozen=True`` :func:`dataclasses.dataclass`;
    it is NOT a Pydantic model, a SQLAlchemy ORM model, or a class
    with side effects in ``__post_init__``. The ``failure_category``
    field is supplied through the constructor and SHALL NOT be
    attached as a hidden attribute.
    """

    fuzzy_best_id: int | None
    vector_best_id: int | None
    fuzzy_candidate_ids: tuple[int, ...]
    vector_candidate_ids: tuple[int, ...]
    fuzzy_candidate_scores: tuple[float, ...]
    vector_candidate_scores: tuple[float, ...]
    agreement: str
    fuzzy_latency_ms: float
    embedding_latency_ms: float
    vector_latency_ms: float
    vector_available: bool
    failure_category: str | None
    fallback: bool = False


@dataclass(frozen=True)
class ProductRecognitionHybridObservation:
    """Frozen observational hybrid-ranking payload for one shadow-mode call.

    Fields:

    - ``hybrid_candidate_ranking``: ``producto_presentacion_id`` in
      descending observational combined score; ties broken by
      ascending encounter order across the union of fuzzy and vector
      candidates.
    - ``hybrid_combined_scores``: observational combined score aligned
      with ``hybrid_candidate_ranking``.
    - ``hybrid_top1_top2_gap``: difference between the top-1 and top-2
      combined scores (``0.0`` when fewer than two-ranked candidates).
    - ``exact_canonical_match``: ``True`` when the normalized input
      text equals a catalog ``producto_nombre`` for a candidate in
      the hybrid ranking.
    - ``exact_alias_match``: ``True`` when the normalized input text
      equals any applicable alias for a candidate in the hybrid
      ranking.
    - ``decision``: one of :data:`HybridDecision` determined by the
      fixed decision order described in the spec.
    - ``fuzzy_weight`` / ``vector_weight``: the **provisional**,
      non-authoritative weights used to compute the combined score.
    - ``unique_threshold`` / ``ambiguous_threshold``: the **provisional**,
      non-authoritative thresholds used to compute the decision.
    - ``min_score_gap``: the **provisional**, non-authoritative
      ``shadow_hybrid_min_score_gap`` value used to gate the
      ``unique`` decision on the top-1/top-2 gap.
    - ``non_authoritative``: literal ``True`` marking the weights,
      thresholds, and ``min_score_gap`` as provisional so Subphase
      4.11 calibration can replace them without changing the
      observation surface.

    The dataclass is a plain ``frozen=True`` :func:`dataclasses.dataclass`;
    it is NOT a Pydantic model, a SQLAlchemy ORM model, or a class
    with side effects in ``__post_init__``.
    """

    hybrid_candidate_ranking: tuple[int, ...]
    hybrid_combined_scores: tuple[float, ...]
    hybrid_top1_top2_gap: float
    exact_canonical_match: bool
    exact_alias_match: bool
    decision: str
    fuzzy_weight: float
    vector_weight: float
    unique_threshold: float
    ambiguous_threshold: float
    min_score_gap: float
    non_authoritative: bool


__all__ = [
    "Agreement",
    "HybridDecision",
    "ProductRecognitionHybridObservation",
    "ProductRecognitionShadowComparison",
]
