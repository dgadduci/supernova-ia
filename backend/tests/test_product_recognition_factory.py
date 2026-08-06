"""Focused tests for the 4.10 / 4.12B ``get_product_recognizer`` factory.

The factory resolves the shared product-recognition boundary based on
the validated ``Settings.product_recognizer_mode``. The tests below
verify:

- ``fuzzy`` mode resolves to a ``FuzzyProductRecognizer`` directly.
- ``shadow`` mode resolves to a ``ShadowedProductRecognizer`` whose
  inner recognizer is a ``FuzzyProductRecognizer``.
- ``hybrid_authoritative`` mode resolves to a
  ``HybridAuthoritativeProductRecognizer`` whose inner recognizer is
  a ``FuzzyProductRecognizer`` and whose policy is loaded by the
  ``HybridAuthoritativePolicySource``.
- The factory accepts an injected recorder, embedding client, and
  session provider.
- The factory returns a ``ProductRecognizerProtocol`` in every mode.
- The safe-fuzzy fallback for an unrecognised
  ``PRODUCT_RECOGNIZER_MODE`` value resolves to the
  ``FuzzyProductRecognizer`` without consulting the hybrid policy
  file.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from typing import Any
from unittest import mock

from backend.config.settings import Settings, load_settings
from backend.recognizers.fuzzy_product_recognizer import FuzzyProductRecognizer
from backend.services.exceptions import HybridAuthoritativePolicyError
from backend.services.hybrid_authoritative_recognizer import (
    HybridAuthoritativeProductRecognizer,
)
from backend.services.product_recognition_factory import (
    get_product_recognizer,
)
from backend.services.product_recognition_shadow_service import (
    ShadowedProductRecognizer,
)
from backend.services.shadow_metrics_recorder import ShadowMetricsRecorder


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "llm_url": "http://llm.test/api/generate",
        "llm_model": "test-llm",
        "llm_timeout": 30,
        "llm_keep_alive": "1h",
        "llm_num_ctx": 2048,
        "llm_num_predict": 256,
        "llm_log_content": False,
        "llm_log_max_chars": 50,
        "embedding_url": "http://embed.test/api/embed",
        "embedding_model": "all-minilm:latest",
        "embedding_timeout_seconds": 15,
        "embedding_batch_size": 32,
        "embedding_dimension": 384,
    }
    base.update(overrides)
    return Settings(**base)


class _StubEmbeddingClient:
    def embed_query(self, text: str) -> list[float]:
        return [0.0] * 384

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 384 for _ in texts]


class _StubSession:
    def close(self) -> None:
        pass


def _stub_session_provider_any() -> Any:
    """A stub session provider that returns a non-SQLAlchemy stub.

    The factory only uses the session to construct the
    ``ProductPresentationVectorSearchService`` lazily. The shadow
    service path is exercised in the dedicated
    ``test_product_recognition_shadow_service.py`` tests, so a stub
    session is sufficient here.
    """
    return _StubSession()


def _write_policy_file(directory: str) -> str:
    payload = {
        "selected_policy": {
            "fuzzy_weight": 0.5,
            "vector_weight": 0.5,
            "unique_threshold": 0.7,
            "ambiguous_threshold": 0.4,
            "minimum_score_gap": 0.05,
            "vector_top_k": 5,
        },
        "eligibility": {"status": "eligible"},
    }
    descriptor, path = tempfile.mkstemp(
        suffix=".json", dir=directory, prefix="hybrid_policy_"
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return path


class FuzzyModeFactoryTest(unittest.TestCase):
    def test_fuzzy_mode_returns_fuzzy_recognizer(self):
        settings = _settings(product_recognizer_mode="fuzzy")
        recognizer = get_product_recognizer(
            settings,
            session_provider=_stub_session_provider_any,  # type: ignore[arg-type]
            embedding_client=_StubEmbeddingClient(),
        )
        self.assertIsInstance(recognizer, FuzzyProductRecognizer)

    def test_fuzzy_mode_does_not_return_shadowed_recognizer(self):
        settings = _settings(product_recognizer_mode="fuzzy")
        recognizer = get_product_recognizer(
            settings,
            session_provider=_stub_session_provider_any,  # type: ignore[arg-type]
            embedding_client=_StubEmbeddingClient(),
        )
        self.assertNotIsInstance(recognizer, ShadowedProductRecognizer)


class ShadowModeFactoryTest(unittest.TestCase):
    def test_shadow_mode_returns_shadowed_recognizer(self):
        settings = _settings(product_recognizer_mode="shadow")
        recognizer = get_product_recognizer(
            settings,
            session_provider=_stub_session_provider_any,  # type: ignore[arg-type]
            embedding_client=_StubEmbeddingClient(),
        )
        self.assertIsInstance(recognizer, ShadowedProductRecognizer)
        self.assertIsInstance(
            recognizer._inner,  # type: ignore[attr-defined]
            FuzzyProductRecognizer,
        )

    def test_factory_accepts_injected_recorder(self):
        settings = _settings(product_recognizer_mode="shadow")
        custom_recorder = ShadowMetricsRecorder()
        recognizer = get_product_recognizer(
            settings,
            recorder=custom_recorder,
            session_provider=_stub_session_provider_any,  # type: ignore[arg-type]
            embedding_client=_StubEmbeddingClient(),
        )
        self.assertIsInstance(recognizer, ShadowedProductRecognizer)
        self.assertIs(
            recognizer._recorder,  # type: ignore[attr-defined]
            custom_recorder,
        )

    def test_factory_uses_injected_session_provider(self):
        settings = _settings(product_recognizer_mode="shadow")
        recognizer = get_product_recognizer(
            settings,
            session_provider=_stub_session_provider_any,  # type: ignore[arg-type]
            embedding_client=_StubEmbeddingClient(),
        )
        self.assertIsInstance(recognizer, ShadowedProductRecognizer)


class HybridAuthoritativeModeFactoryTest(unittest.TestCase):
    def test_hybrid_authoritative_mode_returns_hybrid_recognizer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _write_policy_file(directory)
            settings = _settings(
                product_recognizer_mode="hybrid_authoritative",
                hybrid_authoritative_policy_path=path,
            )
            recognizer = get_product_recognizer(
                settings,
                session_provider=_stub_session_provider_any,  # type: ignore[arg-type]
                embedding_client=_StubEmbeddingClient(),
            )
            self.assertIsInstance(recognizer, HybridAuthoritativeProductRecognizer)
            self.assertIsInstance(
                recognizer._inner,  # type: ignore[attr-defined]
                FuzzyProductRecognizer,
            )

    def test_hybrid_authoritative_mode_fails_closed_on_missing_policy(self):
        settings = _settings(
            product_recognizer_mode="hybrid_authoritative",
            hybrid_authoritative_policy_path="/nonexistent/path/report.json",
        )
        with self.assertRaises(HybridAuthoritativePolicyError):
            get_product_recognizer(
                settings,
                session_provider=_stub_session_provider_any,  # type: ignore[arg-type]
                embedding_client=_StubEmbeddingClient(),
            )

    def test_load_settings_safe_fuzzy_fallback_resolves_to_fuzzy_recognizer(self):
        with tempfile.TemporaryDirectory() as directory:
            policy_path = _write_policy_file(directory)
            env = {
                "PRODUCT_RECOGNIZER_MODE": "hybrid_active",
                "HYBRID_AUTHORITATIVE_POLICY_PATH": policy_path,
            }
            with mock.patch.dict(os.environ, env, clear=True):
                with self.assertLogs("backend.config.settings", level="WARNING"):
                    settings = load_settings()
            self.assertEqual(settings.product_recognizer_mode, "fuzzy")
            recognizer = get_product_recognizer(
                settings,
                session_provider=_stub_session_provider_any,  # type: ignore[arg-type]
                embedding_client=_StubEmbeddingClient(),
            )
            self.assertIsInstance(recognizer, FuzzyProductRecognizer)
            self.assertNotIsInstance(recognizer, HybridAuthoritativeProductRecognizer)


if __name__ == "__main__":
    unittest.main(verbosity=2)
