"""Structured-log metrics recorder for the 4.10 shadow mode and the
4.12B hybrid authoritative mode.

The recorder is a thin wrapper over the standard ``logging``
mechanism. It emits one structured log record per call carrying the
documented safe operational fields, plus a ``mode`` field that
distinguishes the shadow and the hybrid authoritative paths.

The recorder does NOT import FastAPI, HTTP, the embedding client,
the vector search service, the sync service, the admin router, or any
persistence model. It does NOT call ``commit``, ``rollback``,
``close``, or ``begin`` on any database session.

Failure categories are sanitized strings (``"embedding_failure"``,
``"vector_failure"``, ``"unknown"``). The recorder never logs the
customer message, the raw ``query_embedding``, the embedding prompt,
the source document text, the database credentials, a Python stack
trace, or the raw text of any infrastructure exception.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from backend.services.product_recognition_shadow_comparison import (
        ProductRecognitionHybridObservation,
        ProductRecognitionShadowComparison,
)


logger = logging.getLogger(__name__)

RecorderMode = Literal["shadow", "hybrid_authoritative"]


class ShadowMetricsRecorder:
    """Emit exactly one structured log record per shadow-mode call.

    The recorder is a plain class with no database / FastAPI / HTTP
    dependencies. Construct once and reuse it for the lifetime of the
    process. The ``record`` method never raises; failures are swallowed
    by the standard ``logging`` machinery.
    """

    def record(
        self,
        comparison: ProductRecognitionShadowComparison,
        *,
        hybrid_observation: ProductRecognitionHybridObservation,
        id_comercio: int,
        intent: str | None,
        correlation_id: str,
        mode: RecorderMode = "shadow",
    ) -> None:
        if (
            comparison.vector_available is False
            and comparison.failure_category is None
        ):
            failure_category: str | None = "unknown"
        else:
            failure_category = comparison.failure_category

        if mode == "hybrid_authoritative":
            hybrid_non_authoritative = False
        else:
            hybrid_non_authoritative = hybrid_observation.non_authoritative

        logger.info(
            "shadow_product_recognition",
            extra={
                "shadow_metric": "product_recognition_comparison",
                "mode": mode,
                "id_comercio": id_comercio,
                "intent": intent,
                "correlation_id": correlation_id,
                "fuzzy_best_id": comparison.fuzzy_best_id,
                "vector_best_id": comparison.vector_best_id,
                "fuzzy_candidate_count": len(comparison.fuzzy_candidate_ids),
                "vector_candidate_count": len(comparison.vector_candidate_ids),
                "fuzzy_candidate_scores": comparison.fuzzy_candidate_scores,
                "vector_candidate_scores": comparison.vector_candidate_scores,
                "agreement": comparison.agreement,
                "fuzzy_latency_ms": comparison.fuzzy_latency_ms,
                "embedding_latency_ms": comparison.embedding_latency_ms,
                "vector_latency_ms": comparison.vector_latency_ms,
                "vector_available": comparison.vector_available,
                "failure_category": failure_category,
                "hybrid_candidate_ranking": (
                    hybrid_observation.hybrid_candidate_ranking
                ),
                "hybrid_combined_scores": (
                    hybrid_observation.hybrid_combined_scores
                ),
                "hybrid_top1_top2_gap": (
                    hybrid_observation.hybrid_top1_top2_gap
                ),
                "exact_canonical_match": hybrid_observation.exact_canonical_match,
                "exact_alias_match": hybrid_observation.exact_alias_match,
                "hybrid_decision": hybrid_observation.decision,
                "hybrid_fuzzy_weight": hybrid_observation.fuzzy_weight,
                "hybrid_vector_weight": hybrid_observation.vector_weight,
                "hybrid_unique_threshold": (
                    hybrid_observation.unique_threshold
                ),
                "hybrid_ambiguous_threshold": (
                    hybrid_observation.ambiguous_threshold
                ),
                "hybrid_min_score_gap": hybrid_observation.min_score_gap,
                "hybrid_non_authoritative": hybrid_non_authoritative,
            },
        )


__all__ = ["RecorderMode", "ShadowMetricsRecorder"]
