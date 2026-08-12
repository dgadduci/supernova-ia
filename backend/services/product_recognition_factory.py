"""Settings-driven factory for the shared product-recognition boundary.

The factory resolves the shared ``ProductRecognizerProtocol.recognize(...)``
boundary based on the validated ``Settings.product_recognizer_mode``. The
three documented branches are:

- ``"fuzzy"`` (default): an ``ObservedFuzzyProductRecognizer`` wrapping
  a ``FuzzyProductRecognizer`` is returned. The wrapper delegates to
  the inner fuzzy recognizer and emits one observability record per
  call through the existing ``ShadowMetricsRecorder`` so every fuzzy
  request is observable without invoking embedding or vector search.
- ``"shadow"``: a ``ShadowedProductRecognizer`` is returned; the
  inner recognizer is the ``FuzzyProductRecognizer`` and the
  parallel pipeline records the comparison through the
  ``ShadowMetricsRecorder``.
- ``"hybrid_authoritative"``: a
  ``HybridAuthoritativeProductRecognizer`` is returned; the inner
  recognizer is the ``FuzzyProductRecognizer`` and the hybrid
  pipeline reads the calibrated ``HybridDecisionPolicy`` the
  ``HybridAuthoritativePolicySource.load`` produces.

When ``PRODUCT_RECOGNIZER_MODE`` carries an unrecognised literal,
``Settings.load()`` already resolves the effective mode to
``"fuzzy"`` and emits a single sanitized structured warning. The
factory then returns the ``ObservedFuzzyProductRecognizer`` wrapper
configured with ``fallback_category="invalid_mode"`` so the per-
request observability reflects the configured raw literal, the
effective ``fuzzy`` mode, the fuzzy authoritative strategy, and the
sanitized ``invalid_mode`` category without invoking any hybrid
pipeline.

The factory is invoked once at orchestrator module import time with
``load_settings()``; the resulting recognizer is bound to the
module-level ``_product_recognizer`` symbol and re-exported as
``detectar_productos = _product_recognizer.recognize`` (rewritten as
a thin wrapper that accepts and forwards ``intent_metadata``).

The factory is responsible for constructing the embedding client, the
shadow service, and the hybrid authoritative recognizer. The shadow
service and the hybrid authoritative recognizer need a per-request
database session for the 4.9 vector search service, so the factory
accepts a ``session_provider`` callable that returns a fresh
SQLAlchemy ``Session`` on each call. The default ``session_provider``
is the ``SessionLocal`` factory exposed by ``backend.dependencies``;
tests can inject a stub.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from backend.llm.embedding_client import OllamaEmbeddingClient
from backend.recognizers.fuzzy_product_recognizer import FuzzyProductRecognizer
from backend.recognizers.product_recognizer_contract import (
    ProductRecognizerProtocol,
    ProductRecognizerResult,
    RecognizeContext,
)
from backend.services.hybrid_authoritative_policy_source import (
    HybridAuthoritativePolicySource,
)
from backend.services.hybrid_authoritative_recognizer import (
    HybridAuthoritativeProductRecognizer,
)
from backend.services.product_recognition_shadow_comparison import (
    ProductRecognitionHybridObservation,
    ProductRecognitionShadowComparison,
)
from backend.services.product_recognition_shadow_service import (
    ProductRecognitionShadowService,
    ShadowedProductRecognizer,
)
from backend.services.shadow_metrics_recorder import ShadowMetricsRecorder

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from backend.config.settings import Settings
    from backend.llm.embedding_client import EmbeddingClientProtocol
    from backend.services.product_presentation_vector_search_service import (
        ProductPresentationVectorSearchService,
    )


def _default_session_provider() -> Session:
    """Acquire a database session via the project's session factory.

    Imported lazily so the factory module can be imported without
    configuring the database engine (e.g. in test environments that
    inject a fake session provider).
    """
    from backend.dependencies import get_session

    return next(get_session())


def _build_vector_search_service_factory(
    *,
    session_provider: Callable[[], Session],
    settings: Settings,
) -> Callable[[], ProductPresentationVectorSearchService]:
    """Build a factory that returns a fresh
    ``ProductPresentationVectorSearchService`` per call.
    """
    from backend.services.product_presentation_vector_search_service import (
        ProductPresentationVectorSearchService,
    )

    def _factory() -> ProductPresentationVectorSearchService:
        session = session_provider()
        return ProductPresentationVectorSearchService(session, settings)

    return _factory


def _collect_fuzzy_candidates(
    fuzzy_result: ProductRecognizerResult,
) -> tuple[tuple[int, ...], tuple[float, ...]]:
    """Mirror the shadow/hybrid candidate collector for the
    ``ObservedFuzzyProductRecognizer`` decorator.

    The top entry is ``1.0`` and subsequent entries are non-increasing
    confidence proxies aligned with the encounter order. The tuple
    is empty when the fuzzy side produced no candidates. Category-
    level ``encontrados_posibles`` groups (``kind: "category"``)
    contribute zero ids.
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


class ObservedFuzzyProductRecognizer(FuzzyProductRecognizer):
    """Subclass of ``FuzzyProductRecognizer`` that emits one
    ``ShadowMetricsRecorder`` record per ``recognize(...)`` call.

    The decorator is used in fuzzy mode and when an unrecognised
    ``PRODUCT_RECOGNIZER_MODE`` resolves to fuzzy via the safe-fuzzy
    fallback. Every call records:

    - ``configured_mode``: the raw env value (or the default when
      the env var is unset);
    - ``effective_mode``: the mode the runtime actually applied
      (``"fuzzy"`` in this branch);
    - ``authoritative_strategy``: ``"fuzzy"``;
    - the fuzzy decision (``"unique"`` / ``"ambiguous"`` /
      ``"unknown"``);
    - ``hybrid_decision`` is not evaluated (``"not_evaluated"``);
    - ``fallback=False`` in the regular fuzzy path, or
      ``fallback=True`` plus ``fallback_category="invalid_mode"``
      when the configured literal fell outside the documented set.

    The decorator subclasses ``FuzzyProductRecognizer`` so the
    ``isinstance(recognizer, FuzzyProductRecognizer)`` contract
    that the existing focused tests rely on keeps holding without
    modification. The decorator never invokes embedding, the
    vector-search service, or any database session; it only
    forwards the four-key ``ProductRecognizerResult`` returned by
    the inner fuzzy recognizer to the caller unchanged.
    """

    def __init__(
        self,
        *,
        recorder: ShadowMetricsRecorder,
        configured_mode: str,
        effective_mode: str,
        fallback_category: str | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        self._recorder = recorder
        self._configured_mode = configured_mode
        self._effective_mode = effective_mode
        self._fallback_category = fallback_category
        self._clock = clock

    def recognize(
        self,
        text: str,
        catalog: list[dict],
        *,
        intent_metadata: RecognizeContext | None = None,
    ) -> ProductRecognizerResult:
        started = self._clock()
        result = super().recognize(
            text,
            catalog,
            intent_metadata=intent_metadata,
        )
        latency_ms = max(0.0, (self._clock() - started) * 1000.0)

        fuzzy_candidate_ids, fuzzy_candidate_scores = _collect_fuzzy_candidates(
            result
        )

        hybrid_observation = ProductRecognitionHybridObservation(
            hybrid_candidate_ranking=(),
            hybrid_combined_scores=(),
            hybrid_top1_top2_gap=0.0,
            exact_canonical_match=False,
            exact_alias_match=False,
            decision="not_evaluated",
            fuzzy_weight=0.0,
            vector_weight=0.0,
            unique_threshold=0.0,
            ambiguous_threshold=0.0,
            min_score_gap=0.0,
            non_authoritative=True,
        )

        comparison = ProductRecognitionShadowComparison(
            fuzzy_best_id=(
                fuzzy_candidate_ids[0] if fuzzy_candidate_ids else None
            ),
            vector_best_id=None,
            fuzzy_candidate_ids=fuzzy_candidate_ids,
            vector_candidate_ids=(),
            fuzzy_candidate_scores=fuzzy_candidate_scores,
            vector_candidate_scores=(),
            agreement="fuzzy_only",
            fuzzy_latency_ms=float(latency_ms),
            embedding_latency_ms=0.0,
            vector_latency_ms=0.0,
            vector_available=False,
            failure_category=None,
            fallback=self._fallback_category is not None,
        )

        self._recorder.record(
            comparison,
            hybrid_observation=hybrid_observation,
            id_comercio=0,
            intent=None,
            correlation_id="",
            configured_mode=self._configured_mode,
            effective_mode=self._effective_mode,
            authoritative_strategy="fuzzy",
            fallback_category=self._fallback_category,
            mode="fuzzy",
        )

        return result


def get_product_recognizer(
    settings: Settings,
    *,
    recorder: ShadowMetricsRecorder | None = None,
    session_provider: Callable[[], Session] | None = None,
    embedding_client: EmbeddingClientProtocol | None = None,
    commerce_id_resolver: Callable[[list[dict]], int | None] | None = None,
) -> ProductRecognizerProtocol:
    """Return the shared product-recognition recognizer bound to ``settings``.

    Parameters
    ----------
    settings:
        Loaded ``Settings`` carrying the validated configuration
        (``product_recognizer_mode``, ``shadow_vector_top_k``,
        ``shadow_hybrid_min_score_gap``, and
        ``hybrid_authoritative_policy_path``).
    recorder:
        Optional recorder override. Tests use this to inject a fake
        recorder so no log record is emitted. Production callers omit
        the argument and accept the default ``ShadowMetricsRecorder()``.
    session_provider:
        Optional session factory override. The default acquires a
        session via ``backend.dependencies.get_session``. Tests can
        inject a stub that returns a pre-configured session.
    embedding_client:
        Optional embedding client override. The default constructs
        ``OllamaEmbeddingClient(settings)``. Tests can inject a stub.
    commerce_id_resolver:
        Optional ``catalog -> id_comercio | None`` callable. The
        default is ``None``; the hybrid authoritative recognizer
        then runs the hybrid pipeline only when ``intent_metadata``
        carries ``commerce_id``. The OpenSpec contract forbids using
        a missing ``commerce_id`` as a fallback reason; the hybrid
        authoritative recognizer raises
        :class:`HybridAuthoritativeCommerceIdMissing` if neither the
        metadata nor the resolver provides one.
    """
    fuzzy = FuzzyProductRecognizer()
    configured_mode = getattr(
        settings,
        "product_recognizer_configured_mode",
        settings.product_recognizer_mode,
    )
    effective_mode = settings.product_recognizer_mode

    if effective_mode == "fuzzy":
        chosen_recorder = (
            recorder if recorder is not None else ShadowMetricsRecorder()
        )
        invalid_mode = (
            "invalid_mode"
            if configured_mode != "fuzzy"
            and configured_mode != effective_mode
            else None
        )
        return ObservedFuzzyProductRecognizer(
            recorder=chosen_recorder,
            configured_mode=configured_mode,
            effective_mode=effective_mode,
            fallback_category=invalid_mode,
        )

    if effective_mode not in {"shadow", "hybrid_authoritative"}:
        # ``Settings.load()`` already reduced the effective mode to
        # ``"fuzzy"`` for an unrecognised env literal; this branch is
        # unreachable for the documented modes but it is kept as a
        # defensive safety net so the factory never returns a bare
        # ``FuzzyProductRecognizer`` without observability.
        chosen_recorder = (
            recorder if recorder is not None else ShadowMetricsRecorder()
        )
        return ObservedFuzzyProductRecognizer(
            recorder=chosen_recorder,
            configured_mode=configured_mode,
            effective_mode="fuzzy",
            fallback_category="invalid_mode",
        )

    chosen_recorder = recorder if recorder is not None else ShadowMetricsRecorder()
    chosen_session_provider = (
        session_provider if session_provider is not None else _default_session_provider
    )
    chosen_embedding_client = (
        embedding_client
        if embedding_client is not None
        else OllamaEmbeddingClient(settings)
    )

    vector_search_service_factory = _build_vector_search_service_factory(
        session_provider=chosen_session_provider,
        settings=settings,
    )

    if effective_mode == "hybrid_authoritative":
        policy = HybridAuthoritativePolicySource.load(settings)
        return HybridAuthoritativeProductRecognizer(
            inner=fuzzy,
            policy=policy,
            embedding_client=chosen_embedding_client,
            vector_search_service=vector_search_service_factory,
            recorder=chosen_recorder,
            commerce_id_resolver=commerce_id_resolver,
            configured_mode=configured_mode,
            effective_mode=effective_mode,
        )

    if effective_mode == "shadow":
        shadow_service = ProductRecognitionShadowService(
            embedding_client=chosen_embedding_client,
            vector_search_service=vector_search_service_factory,
            settings=settings,
        )
        return ShadowedProductRecognizer(
            inner=fuzzy,
            shadow=shadow_service,
            recorder=chosen_recorder,
            commerce_id_resolver=commerce_id_resolver,  # type: ignore[arg-type]
            configured_mode=configured_mode,
            effective_mode=effective_mode,
        )

    return fuzzy


__all__ = ["ObservedFuzzyProductRecognizer", "get_product_recognizer"]
