"""Settings-driven factory for the shared product-recognition boundary.

The factory resolves the shared ``ProductRecognizerProtocol.recognize(...)``
boundary based on the validated ``Settings.product_recognizer_mode``. The
three documented branches are:

- ``"fuzzy"`` (default): a ``FuzzyProductRecognizer`` is returned
  unchanged. The shadow service, the recorder, and the embedding
  client are NOT invoked.
- ``"shadow"``: a ``ShadowedProductRecognizer`` is returned; the
  inner recognizer is the ``FuzzyProductRecognizer`` and the
  parallel pipeline records the comparison through the
  ``ShadowMetricsRecorder``.
- ``"hybrid_authoritative"``: a
  ``HybridAuthoritativeProductRecognizer`` is returned; the inner
  recognizer is the ``FuzzyProductRecognizer`` and the hybrid
  pipeline reads the calibrated ``HybridDecisionPolicy`` the
  ``HybridAuthoritativePolicySource.load`` produces.

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

from collections.abc import Callable
from typing import TYPE_CHECKING

from backend.llm.embedding_client import OllamaEmbeddingClient
from backend.recognizers.fuzzy_product_recognizer import FuzzyProductRecognizer
from backend.recognizers.product_recognizer_contract import (
    ProductRecognizerProtocol,
)
from backend.services.hybrid_authoritative_policy_source import (
    HybridAuthoritativePolicySource,
)
from backend.services.hybrid_authoritative_recognizer import (
    HybridAuthoritativeProductRecognizer,
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
        then skips the embedding and vector pipeline when no
        resolver is supplied.
    """
    fuzzy = FuzzyProductRecognizer()
    if settings.product_recognizer_mode == "fuzzy":
        return fuzzy

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

    if settings.product_recognizer_mode == "hybrid_authoritative":
        policy = HybridAuthoritativePolicySource.load(settings)
        return HybridAuthoritativeProductRecognizer(
            inner=fuzzy,
            policy=policy,
            embedding_client=chosen_embedding_client,
            vector_search_service=vector_search_service_factory,
            recorder=chosen_recorder,
            commerce_id_resolver=commerce_id_resolver,
        )

    if settings.product_recognizer_mode == "shadow":
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
        )

    return fuzzy


__all__ = ["get_product_recognizer"]
