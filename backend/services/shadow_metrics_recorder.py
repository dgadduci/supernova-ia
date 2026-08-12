"""Structured-event emitter for the 4.10 shadow mode, the
4.12B hybrid authoritative mode, and the 4.12B fuzzy-mode
``ObservedFuzzyProductRecognizer`` decorator.

The recorder routes every observation through the single
``backend.observability.events`` shared boundary as the
``shadow_product_recognition`` event belonging to the
``product_recognition`` component. The event carries only the
closed allowlisted recognition fields:

* ``configured_mode`` and ``effective_mode`` (``fuzzy`` /
  ``shadow`` / ``hybrid_authoritative`` / sanitized
  ``invalid_mode``);
* ``authoritative_strategy`` (``fuzzy`` / ``hybrid``);
* ``hybrid_decision`` (``unique`` / ``ambiguous`` / ``unknown`` /
  ``not_evaluated``);
* ``fallback`` boolean and ``fallback_category`` (only when
  ``fallback=true``, restricted to the sanitized technical
  categories plus ``invalid_mode``);
* ``fuzzy_latency_ms``, ``embedding_latency_ms`` and
  ``vector_latency_ms`` (bounded non-negative integers when
  available).

The recorder does NOT emit customer text, E.164, ``id_comercio``,
intent, correlation IDs, result IDs, candidate counts / rankings,
scores, exact-match flags, policy values, messages, raw exception
text or tracebacks. The shared catalogue rejects any such field
and the recorder never tries to pass one.

The recorder does NOT import FastAPI, HTTP, the embedding client,
the vector search service, the sync service, the admin router, or
any persistence model. It does NOT call ``commit``, ``rollback``,
``close``, or ``begin`` on any database session.

Emission failure is swallowed by :func:`backend.observability.events.emit_event`
and never affects recognition or customer processing.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from backend.observability.events import (
    COMPONENT_PRODUCT_RECOGNITION,
    EVENT_SHADOW_PRODUCT_RECOGNITION,
    emit_event,
)

if TYPE_CHECKING:
    from backend.services.product_recognition_shadow_comparison import (
        ProductRecognitionHybridObservation,
        ProductRecognitionShadowComparison,
)


RecorderMode = Literal["fuzzy", "shadow", "hybrid_authoritative"]


_SANITIZED_RECOGNITION_MODES: frozenset[str] = frozenset(
    {"fuzzy", "shadow", "hybrid_authoritative"}
)
_SANITIZED_FALLBACK_CATEGORIES: frozenset[str] = frozenset(
    {
        "embedding_failure",
        "vector_failure",
        "malformed_response",
        "unexpected_technical_failure",
        "invalid_mode",
    }
)
_MAX_BOUNDED_LATENCY_MS = 24 * 60 * 60 * 1000


def _bounded_latency_ms(value: float) -> int:
    """Round ``value`` to a bounded non-negative integer millisecond.

    The recorder never trusts upstream floats: negative durations
    collapse to ``0`` and oversize durations are capped at the
    shared catalogue ceiling so the emitter always sees a valid
    bounded integer.
    """
    if value < 0:
        return 0
    rounded = round(value)
    if rounded > _MAX_BOUNDED_LATENCY_MS:
        return _MAX_BOUNDED_LATENCY_MS
    return rounded


def _sanitize_configured_mode(configured_mode: str | None) -> str:
    """Reduce the operator-supplied configured mode to a closed
    sanitized allowlist token.

    The recorder only emits one of ``fuzzy``, ``shadow``,
    ``hybrid_authoritative`` or the sanitized ``invalid_mode``
    marker. Any unrecognised raw value is reported as
    ``invalid_mode`` so the shared event never reflects operator
    input verbatim.
    """
    if configured_mode in _SANITIZED_RECOGNITION_MODES:
        return configured_mode
    return "invalid_mode"


class ShadowMetricsRecorder:
    """Emit exactly one catalogued ``shadow_product_recognition``
    event per shadow-mode call.

    The recorder is a plain class with no database / FastAPI / HTTP
    dependencies. Construct once and reuse it for the lifetime of
    the process. The ``record`` method is non-blocking and never
    raises: validation or emission failures are swallowed by
    :func:`backend.observability.events.emit_event` and the
    surrounding recognition flow keeps its existing behaviour.

    The recorder maps its already-computed values to the event
    without changing recognition work. ``unique``, ``ambiguous`` and
    ``unknown`` are valid business observations whether the mode is
    shadow or hybrid-authoritative. A fallback is true only for the
    existing technical categories; an unavailable vector or
    business ambiguity must not manufacture a fallback. Invalid
    configured mode continues resolving to effective fuzzy,
    recorded with the sanitized ``invalid_mode`` category.
    """

    def __init__(self, *, stream: Any | None = None) -> None:
        self._stream = stream

    def record(
        self,
        comparison: ProductRecognitionShadowComparison,
        *,
        hybrid_observation: ProductRecognitionHybridObservation,
        id_comercio: int,
        intent: str | None,
        correlation_id: str,
        configured_mode: str | None = None,
        effective_mode: str | None = None,
        authoritative_strategy: str = "fuzzy",
        fallback_category: str | None = None,
        mode: RecorderMode = "shadow",
        stream: Any | None = None,
    ) -> None:
        del id_comercio, intent, correlation_id

        if (
            comparison.vector_available is False
            and comparison.failure_category is None
        ):
            failure_category: str | None = "unknown"
        else:
            failure_category = comparison.failure_category

        resolved_fallback = comparison.fallback or fallback_category is not None
        resolved_fallback_category = (
            fallback_category
            if fallback_category is not None
            else (failure_category if comparison.fallback else None)
        )

        if (
            resolved_fallback
            and resolved_fallback_category not in _SANITIZED_FALLBACK_CATEGORIES
        ):
            resolved_fallback = False
            resolved_fallback_category = None

        sanitized_configured_mode = _sanitize_configured_mode(configured_mode)

        if mode == "fuzzy":
            hybrid_decision = "not_evaluated"
        else:
            hybrid_decision = hybrid_observation.decision

        emit_event(
            event=EVENT_SHADOW_PRODUCT_RECOGNITION,
            component=COMPONENT_PRODUCT_RECOGNITION,
            configured_mode=sanitized_configured_mode,
            effective_mode=effective_mode,
            authoritative_strategy=authoritative_strategy,
            hybrid_decision=hybrid_decision,
            fallback=resolved_fallback,
            fallback_category=resolved_fallback_category,
            fuzzy_latency_ms=_bounded_latency_ms(
                float(comparison.fuzzy_latency_ms)
            ),
            embedding_latency_ms=_bounded_latency_ms(
                float(comparison.embedding_latency_ms)
            ),
            vector_latency_ms=_bounded_latency_ms(
                float(comparison.vector_latency_ms)
            ),
            stream=stream if stream is not None else self._stream,
        )


__all__ = ["RecorderMode", "ShadowMetricsRecorder"]
