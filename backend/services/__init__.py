"""Service-layer re-exports for the product-presentation vector search.

The 4.9 search surface is a sibling of the 4.7 admin service and the
4.8 catalog-embedding synchronization service. The package re-exports
``ProductPresentationVectorMatch`` so callers can import the typed
result through ``backend.services`` instead of reaching into the
module file directly.

Subphase 4.10 adds the shadow-mode re-exports: the frozen comparison
and hybrid-observation dataclasses, the shadow service, the
shadowed recognizer decorator, and the (re-used) embedding client
protocol. These re-exports keep the public surface narrow and
prevent callers from reaching into the module files directly.
"""
from __future__ import annotations

from backend.llm.embedding_client import EmbeddingClientProtocol
from backend.services.product_presentation_vector_match import (
    ProductPresentationVectorMatch,
)
from backend.services.product_recognition_factory import get_product_recognizer
from backend.services.product_recognition_shadow_comparison import (
    ProductRecognitionHybridObservation,
    ProductRecognitionShadowComparison,
)
from backend.services.product_recognition_shadow_service import (
    ProductRecognitionShadowService,
    ShadowedProductRecognizer,
)
from backend.services.shadow_metrics_recorder import ShadowMetricsRecorder


__all__ = [
    "EmbeddingClientProtocol",
    "ProductPresentationHybridObservation",
    "ProductPresentationShadowComparison",
    "ProductPresentationVectorMatch",
    "ProductRecognitionHybridObservation",
    "ProductRecognitionShadowComparison",
    "ProductRecognitionShadowService",
    "ShadowMetricsRecorder",
    "ShadowedProductRecognizer",
    "get_product_recognizer",
]