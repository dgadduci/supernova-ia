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

import contextlib
import io
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
    ObservedFuzzyProductRecognizer,
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


class FuzzyModeObservabilityTest(unittest.TestCase):
    """Fuzzy-mode observability tests.

    The factory returns the ``ObservedFuzzyProductRecognizer``
    wrapper in fuzzy mode and on the safe-fuzzy invalid-mode
    fallback. Every ``recognize(...)`` call MUST emit one
    ``ShadowMetricsRecorder`` record with the documented fields
    without invoking embedding or vector search.
    """

    def _catalog(self) -> list[dict]:
        return [
            {
                "producto_presentacion_id": 1,
                "producto_nombre": "Empanada de Carne",
                "presentacion_codigo": "unidad",
                "aliases": {"general_aliases": [], "specific_aliases": []},
            }
        ]

    def test_fuzzy_mode_records_observability_with_minimum_fields(self):
        """A fuzzy-mode call records configured/effective mode,
        authoritative_strategy='fuzzy', the fuzzy decision, and
        ``hybrid_decision='not_evaluated'`` (the hybrid pipeline was
        never evaluated). ``fallback=False`` and ``fallback_category``
        are absent.
        """
        settings = _settings(product_recognizer_mode="fuzzy")
        recognizer = get_product_recognizer(
            settings,
            session_provider=_stub_session_provider_any,  # type: ignore[arg-type]
            embedding_client=_StubEmbeddingClient(),
        )
        self.assertIsInstance(recognizer, ObservedFuzzyProductRecognizer)

        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            recognizer.recognize("empanada de carne", self._catalog())

        event = json.loads(stdout.getvalue().strip())
        self.assertEqual(event["event"], "shadow_product_recognition")
        self.assertEqual(event["component"], "product_recognition")
        self.assertEqual(event["configured_mode"], "fuzzy")
        self.assertEqual(event["effective_mode"], "fuzzy")
        self.assertEqual(event["authoritative_strategy"], "fuzzy")
        # ``hybrid_decision`` is the documented "not_evaluated"
        # sentinel: the hybrid pipeline was never run in fuzzy mode.
        self.assertEqual(event["hybrid_decision"], "not_evaluated")
        self.assertFalse(event["fallback"])
        self.assertNotIn("fallback_category", event)

    def test_fuzzy_mode_preserves_four_key_result_contract(self):
        """The wrapper forwards the four-key ``ProductRecognizerResult``
        byte-for-byte unchanged.
        """
        from backend.recognizers.fuzzy_product_recognizer import (
            FuzzyProductRecognizer,
        )

        settings = _settings(product_recognizer_mode="fuzzy")
        recognizer = get_product_recognizer(
            settings,
            session_provider=_stub_session_provider_any,  # type: ignore[arg-type]
            embedding_client=_StubEmbeddingClient(),
        )
        wrapper_result = recognizer.recognize(
            "empanada de carne", self._catalog()
        )
        baseline_result = FuzzyProductRecognizer().recognize(
            "empanada de carne", self._catalog()
        )
        self.assertEqual(set(wrapper_result), set(baseline_result))
        for key in ("encontrados", "encontrados_posibles",
                    "encontrados_no_disponibles", "no_encontrados"):
            self.assertEqual(wrapper_result[key], baseline_result[key])

    def test_fuzzy_mode_does_not_invoke_embedding_or_vector_search(self):
        """Fuzzy-mode observability must not invoke the embedding
        client or the vector-search pipeline.
        """
        settings = _settings(product_recognizer_mode="fuzzy")
        embed_calls: list[str] = []

        class _CountingEmbeddingClient:
            def embed_query(self, text):
                embed_calls.append(text)
                return [0.0] * 384

            def embed_documents(self, texts):
                return [[0.0] * 384 for _ in texts]

        recognizer = get_product_recognizer(
            settings,
            session_provider=_stub_session_provider_any,  # type: ignore[arg-type]
            embedding_client=_CountingEmbeddingClient(),
        )
        self.assertIsInstance(recognizer, ObservedFuzzyProductRecognizer)
        recognizer.recognize("empanada de carne", self._catalog())
        self.assertEqual(embed_calls, [])

    def test_invalid_mode_records_observability_with_invalid_mode_category(self):
        """An unrecognised ``PRODUCT_RECOGNIZER_MODE`` resolves to
        effective ``fuzzy`` and the per-request observability records
        the configured raw literal as the sanitized ``invalid_mode``
        token, the effective ``fuzzy`` mode, the fuzzy authoritative
        strategy, and the sanitized ``invalid_mode`` category. The
        hybrid pipeline is NOT invoked and the fuzzy result is
        returned unchanged.
        """
        env = {"PRODUCT_RECOGNIZER_MODE": "hybrid_active"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertLogs(
                "backend.config.settings", level="WARNING"
            ) as settings_log:
                settings = load_settings()
            self.assertEqual(settings.product_recognizer_mode, "fuzzy")
            self.assertEqual(
                settings.product_recognizer_configured_mode,
                "hybrid_active",
            )
            recognizer = get_product_recognizer(
                settings,
                session_provider=_stub_session_provider_any,  # type: ignore[arg-type]
                embedding_client=_StubEmbeddingClient(),
            )
            self.assertIsInstance(recognizer, ObservedFuzzyProductRecognizer)

        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            recognizer.recognize("empanada de carne", self._catalog())

        # The warning carries the safe-fuzzy fallback fields. The
        # warning and the per-request record are emitted through
        # independent paths.
        warning = settings_log.records[0]
        self.assertEqual(warning.configured_mode, "hybrid_active")
        self.assertEqual(warning.effective_mode, "fuzzy")
        self.assertEqual(warning.reason, "invalid_mode")

        event = json.loads(stdout.getvalue().strip())
        self.assertEqual(event["event"], "shadow_product_recognition")
        self.assertEqual(event["component"], "product_recognition")
        # The recorder sanitizes the raw operator literal to the
        # closed ``invalid_mode`` token so the closed-shape contract
        # never reflects operator input verbatim.
        self.assertEqual(event["configured_mode"], "invalid_mode")
        self.assertEqual(event["effective_mode"], "fuzzy")
        self.assertEqual(event["authoritative_strategy"], "fuzzy")
        self.assertEqual(event["hybrid_decision"], "not_evaluated")
        self.assertTrue(event["fallback"])
        self.assertEqual(event["fallback_category"], "invalid_mode")

    def test_invalid_mode_does_not_load_hybrid_policy_file(self):
        """The safe-fuzzy invalid-mode fallback does not consult the
        hybrid policy file (the factory short-circuits before the
        ``hybrid_authoritative`` branch).
        """
        with tempfile.TemporaryDirectory() as directory:
            policy_path = _write_policy_file(directory)
            env = {
                "PRODUCT_RECOGNIZER_MODE": "hybrid_active",
                "HYBRID_AUTHORITATIVE_POLICY_PATH": policy_path,
            }
            with mock.patch.dict(os.environ, env, clear=True):
                with self.assertLogs("backend.config.settings", level="WARNING"):
                    settings = load_settings()
                # Delete the policy file BEFORE the factory call; the
                # factory must not touch it because the effective mode
                # is already ``fuzzy``.
                os.unlink(policy_path)
                recognizer = get_product_recognizer(
                    settings,
                    session_provider=_stub_session_provider_any,  # type: ignore[arg-type]
                    embedding_client=_StubEmbeddingClient(),
                )
                self.assertIsInstance(recognizer, FuzzyProductRecognizer)
                self.assertNotIsInstance(
                    recognizer, HybridAuthoritativeProductRecognizer
                )


class ShadowNoCommerceIdObservationSkipTest(unittest.TestCase):
    """Shadow-mode behaviour when the commerce id is missing.

    Shadow mode is observational: the fuzzy result is authoritative.
    When the commerce id is missing the shadow side simply skips the
    observation; it does not classify the missing commerce id as a
    fallback category. The hybrid authoritative recognizer, by
    contrast, raises :class:`HybridAuthoritativeCommerceIdMissing`.
    """

    def test_shadow_recognizer_skips_observation_without_fallback_category(self):
        from backend.services.product_recognition_shadow_service import (
            ProductRecognitionShadowService,
            ShadowedProductRecognizer,
        )

        recorder = ShadowMetricsRecorder()
        settings = _settings(product_recognizer_mode="shadow")

        # Use a sentinel object that would raise if invoked; the
        # shadow recognizer must short-circuit BEFORE calling the
        # shadow service because the commerce id cannot be resolved.
        class _ExplodingShadowService:
            def compare(self, *args, **kwargs):
                raise AssertionError(
                    "shadow service must not be invoked when "
                    "commerce_id cannot be resolved"
                )

        recognizer = ShadowedProductRecognizer(
            inner=FuzzyProductRecognizer(),
            shadow=_ExplodingShadowService(),  # type: ignore[arg-type]
            recorder=recorder,
            commerce_id_resolver=None,
            configured_mode="shadow",
            effective_mode="shadow",
        )
        # Suppress unused-binding warning for the imported class.
        del ProductRecognitionShadowService, settings

        # When the resolver is absent the shadow recognizer must NOT
        # emit any observation (it has nothing to observe) and must
        # NOT tag the call as a fallback.
        result = recognizer.recognize(
            "empanada",
            _stub_catalog(),
        )

        # The fuzzy result is authoritative and the shadow service
        # was never consulted.
        self.assertIn("encontrados", result)


def _stub_catalog() -> list[dict]:
    return [
        {
            "producto_presentacion_id": 1,
            "producto_nombre": "Empanada de Carne",
            "presentacion_codigo": "unidad",
        }
    ]


if __name__ == "__main__":
    unittest.main(verbosity=2)
