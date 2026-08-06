"""Focused tests for Subphase 4.10/4.12B product-recognition settings.

These tests cover the ``Settings`` fields:

- ``product_recognizer_mode``: literal ``"fuzzy"``, ``"shadow"``, or
  ``"hybrid_authoritative"`` (default ``"fuzzy"``). Subphase 4.12B
  replaced the "raise on invalid literal" surface with a safe-fuzzy
  fallback that logs a structured warning so an operator typo can
  never prevent application startup.
- ``shadow_vector_top_k`` (positive integer, default ``5``).
- ``shadow_hybrid_min_score_gap`` (float in ``[0.0, 1.0]``, default
  ``0.05``; provisional and non-authoritative).
- ``hybrid_authoritative_policy_path`` (
  ``str | None``, default ``None``), validated ONLY when the
  effective mode is ``"hybrid_authoritative"``.

The tests use ``unittest.mock.patch.dict(os.environ, ..., clear=True)``
to isolate the env var surface and assert that ``Settings.load()``
honours the safe-fuzzy fallback, the scoped validator, and the
existing shadow validators.
"""
from __future__ import annotations

import logging
import math
import os
import unittest
from unittest import mock

from backend.config.settings import (
    DEFAULT_HYBRID_AUTHORITATIVE_POLICY_PATH,
    DEFAULT_PRODUCT_RECOGNIZER_MODE,
    DEFAULT_SHADOW_HYBRID_MIN_SCORE_GAP,
    DEFAULT_SHADOW_VECTOR_TOP_K,
    Settings,
    load_settings,
)
from backend.services.exceptions import (
    InvalidHybridAuthoritativePolicyPath,
    InvalidProductRecognizerMode,
    InvalidShadowHybridMinScoreGap,
    InvalidShadowVectorTopK,
)


class ProductRecognizerModeDefaultsTest(unittest.TestCase):
    def test_default_mode_is_fuzzy(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = load_settings()
        self.assertEqual(settings.product_recognizer_mode, "fuzzy")
        self.assertEqual(
            DEFAULT_PRODUCT_RECOGNIZER_MODE,
            "fuzzy",
            "default product recognizer mode must be 'fuzzy'",
        )

    def test_shadow_mode_override_is_accepted(self):
        env = {"PRODUCT_RECOGNIZER_MODE": "shadow"}
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.product_recognizer_mode, "shadow")

    def test_hybrid_authoritative_mode_override_is_accepted(self):
        env = {
            "PRODUCT_RECOGNIZER_MODE": "hybrid_authoritative",
            "HYBRID_AUTHORITATIVE_POLICY_PATH": "/tmp/report.json",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.product_recognizer_mode, "hybrid_authoritative")

    def test_invalid_literal_falls_back_to_fuzzy_with_warning(self):
        env = {"PRODUCT_RECOGNIZER_MODE": "hybrid_active"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertLogs("backend.config.settings", level="WARNING") as captured:
                settings = load_settings()
        self.assertEqual(settings.product_recognizer_mode, "fuzzy")
        self.assertEqual(len(captured.records), 1)
        record = captured.records[0]
        self.assertEqual(getattr(record, "configured_mode", None), "hybrid_active")
        self.assertEqual(getattr(record, "effective_mode", None), "fuzzy")
        self.assertEqual(getattr(record, "reason", None), "invalid_mode")

    def test_capitalised_typo_falls_back_to_fuzzy_with_warning(self):
        env = {"PRODUCT_RECOGNIZER_MODE": "HybridAuthoritative"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertLogs("backend.config.settings", level="WARNING") as captured:
                settings = load_settings()
        self.assertEqual(settings.product_recognizer_mode, "fuzzy")
        self.assertEqual(
            getattr(captured.records[0], "configured_mode", None),
            "HybridAuthoritative",
        )
        self.assertEqual(getattr(captured.records[0], "effective_mode", None), "fuzzy")
        self.assertEqual(getattr(captured.records[0], "reason", None), "invalid_mode")

    def test_empty_string_falls_back_to_fuzzy_with_warning(self):
        env = {"PRODUCT_RECOGNIZER_MODE": ""}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertLogs("backend.config.settings", level="WARNING") as captured:
                settings = load_settings()
        self.assertEqual(settings.product_recognizer_mode, "fuzzy")
        self.assertEqual(len(captured.records), 1)
        self.assertEqual(getattr(captured.records[0], "reason", None), "invalid_mode")

    def test_invalid_literal_does_not_raise_invalid_mode_marker(self):
        env = {"PRODUCT_RECOGNIZER_MODE": "hybrid_active"}
        with mock.patch.dict(os.environ, env, clear=True):
            try:
                load_settings()
            except InvalidProductRecognizerMode as exc:
                self.fail(
                    "safe-fuzzy fallback must not raise InvalidProductRecognizerMode "
                    f"(got {exc!r})"
                )

    def test_warning_record_carries_no_raw_exception_text(self):
        env = {"PRODUCT_RECOGNIZER_MODE": "hybrid_active"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertLogs("backend.config.settings", level="WARNING") as captured:
                load_settings()
        record = captured.records[0]
        for field in ("message", "msg"):
            value = getattr(record, field, "")
            if isinstance(value, str):
                for forbidden in ("Traceback", "Error", "Exception"):
                    self.assertNotIn(forbidden, value)

    def test_default_mode_emits_no_warning(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            logger = logging.getLogger("backend.config.settings")
            previous_level = logger.level
            logger.setLevel(logging.WARNING)
            try:
                with mock.patch.object(logger, "warning") as warning_method:
                    load_settings()
            finally:
                logger.setLevel(previous_level)
        warning_method.assert_not_called()


class HybridAuthoritativePolicyPathTest(unittest.TestCase):
    def test_default_policy_path_is_none(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = load_settings()
        self.assertIsNone(settings.hybrid_authoritative_policy_path)
        self.assertIsNone(DEFAULT_HYBRID_AUTHORITATIVE_POLICY_PATH)

    def test_explicit_path_override_is_accepted_in_hybrid_mode(self):
        env = {
            "PRODUCT_RECOGNIZER_MODE": "hybrid_authoritative",
            "HYBRID_AUTHORITATIVE_POLICY_PATH": "/tmp/report.json",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.hybrid_authoritative_policy_path, "/tmp/report.json")

    def test_empty_path_override_is_rejected_in_hybrid_mode(self):
        env = {
            "PRODUCT_RECOGNIZER_MODE": "hybrid_authoritative",
            "HYBRID_AUTHORITATIVE_POLICY_PATH": "",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(InvalidHybridAuthoritativePolicyPath):
                load_settings()

    def test_path_override_is_ignored_in_fuzzy_mode(self):
        env = {
            "PRODUCT_RECOGNIZER_MODE": "fuzzy",
            "HYBRID_AUTHORITATIVE_POLICY_PATH": "/tmp/report.json",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.hybrid_authoritative_policy_path, "/tmp/report.json")

    def test_path_override_is_ignored_in_shadow_mode(self):
        env = {
            "PRODUCT_RECOGNIZER_MODE": "shadow",
            "HYBRID_AUTHORITATIVE_POLICY_PATH": "/tmp/report.json",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.hybrid_authoritative_policy_path, "/tmp/report.json")

    def test_path_override_is_ignored_after_safe_fuzzy_fallback(self):
        env = {
            "PRODUCT_RECOGNIZER_MODE": "hybrid_active",
            "HYBRID_AUTHORITATIVE_POLICY_PATH": "/tmp/report.json",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertLogs("backend.config.settings", level="WARNING"):
                settings = load_settings()
        self.assertEqual(settings.product_recognizer_mode, "fuzzy")
        self.assertEqual(settings.hybrid_authoritative_policy_path, "/tmp/report.json")


class ShadowVectorTopKDefaultsTest(unittest.TestCase):
    def test_default_top_k_is_five(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = load_settings()
        self.assertEqual(settings.shadow_vector_top_k, 5)
        self.assertEqual(
            DEFAULT_SHADOW_VECTOR_TOP_K,
            5,
            "default shadow vector top_k must be 5",
        )

    def test_positive_top_k_override_is_accepted(self):
        env = {"SHADOW_VECTOR_TOP_K": "10"}
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.shadow_vector_top_k, 10)

    def test_zero_top_k_is_rejected_at_load_time(self):
        env = {"SHADOW_VECTOR_TOP_K": "0"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(InvalidShadowVectorTopK):
                load_settings()

    def test_negative_top_k_is_rejected_at_load_time(self):
        env = {"SHADOW_VECTOR_TOP_K": "-1"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(InvalidShadowVectorTopK):
                load_settings()

    def test_non_integer_top_k_is_rejected_at_load_time(self):
        env = {"SHADOW_VECTOR_TOP_K": "abc"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ValueError):
                load_settings()


class ShadowHybridMinScoreGapDefaultsTest(unittest.TestCase):
    def test_default_min_score_gap_is_zero_point_zero_five(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = load_settings()
        self.assertEqual(settings.shadow_hybrid_min_score_gap, 0.05)
        self.assertEqual(
            DEFAULT_SHADOW_HYBRID_MIN_SCORE_GAP,
            0.05,
            "default shadow hybrid min_score_gap must be 0.05",
        )

    def test_zero_min_score_gap_is_accepted(self):
        env = {"SHADOW_HYBRID_MIN_SCORE_GAP": "0.0"}
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.shadow_hybrid_min_score_gap, 0.0)

    def test_one_min_score_gap_is_accepted(self):
        env = {"SHADOW_HYBRID_MIN_SCORE_GAP": "1.0"}
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.shadow_hybrid_min_score_gap, 1.0)

    def test_midpoint_min_score_gap_override_is_accepted(self):
        env = {"SHADOW_HYBRID_MIN_SCORE_GAP": "0.1"}
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.shadow_hybrid_min_score_gap, 0.1)

    def test_negative_min_score_gap_is_rejected_at_load_time(self):
        env = {"SHADOW_HYBRID_MIN_SCORE_GAP": "-0.01"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(InvalidShadowHybridMinScoreGap):
                load_settings()

    def test_above_one_min_score_gap_is_rejected_at_load_time(self):
        env = {"SHADOW_HYBRID_MIN_SCORE_GAP": "1.01"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(InvalidShadowHybridMinScoreGap):
                load_settings()

    def test_nan_min_score_gap_is_rejected_at_load_time(self):
        env = {"SHADOW_HYBRID_MIN_SCORE_GAP": "NaN"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(InvalidShadowHybridMinScoreGap):
                load_settings()

    def test_non_numeric_min_score_gap_is_rejected_at_load_time(self):
        env = {"SHADOW_HYBRID_MIN_SCORE_GAP": "abc"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ValueError):
                load_settings()


class SettingsIsFrozenTest(unittest.TestCase):
    def test_settings_is_frozen(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = load_settings()
        with self.assertRaises((Exception,)):
            settings.product_recognizer_mode = "shadow"  # type: ignore[misc]
        with self.assertRaises((Exception,)):
            settings.shadow_vector_top_k = 1  # type: ignore[misc]
        with self.assertRaises((Exception,)):
            settings.shadow_hybrid_min_score_gap = 0.5  # type: ignore[misc]
        with self.assertRaises((Exception,)):
            settings.hybrid_authoritative_policy_path = "/tmp/x.json"  # type: ignore[misc]

    def test_dataclass_contains_expected_fields(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = load_settings()
        self.assertIsInstance(settings, Settings)
        self.assertIn("product_recognizer_mode", settings.__dataclass_fields__)
        self.assertIn("shadow_vector_top_k", settings.__dataclass_fields__)
        self.assertIn(
            "shadow_hybrid_min_score_gap", settings.__dataclass_fields__
        )
        self.assertIn(
            "hybrid_authoritative_policy_path", settings.__dataclass_fields__
        )

    def test_non_authoritative_field_default_is_float(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = load_settings()
        self.assertIsInstance(settings.shadow_hybrid_min_score_gap, float)
        self.assertFalse(
            math.isnan(settings.shadow_hybrid_min_score_gap),
            "default min_score_gap must be a finite float, not NaN",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
