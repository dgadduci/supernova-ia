import os
import unittest
from unittest import mock

from backend.config.settings import Settings, load_settings


class LoadSettingsDefaultsTest(unittest.TestCase):
    def test_default_values_when_no_overrides(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = load_settings()
        self.assertEqual(
            settings,
            Settings(
                llm_url="http://localhost:11434/api/generate",
                llm_model="qwen-27b-coding:latest",
                llm_timeout=180,
                llm_keep_alive="2h",
                llm_num_ctx=8192,
                llm_num_predict=1500,
                llm_log_content=False,
                llm_log_max_chars=1000,
            ),
        )

    def test_settings_is_frozen(self):
        settings = load_settings()
        with self.assertRaises(Exception):
            settings.llm_model = "other"  # type: ignore[misc]

    def test_embedding_defaults_are_independent_from_llm(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = load_settings()
        self.assertEqual(settings.embedding_url, "http://localhost:11434/api/embed")
        self.assertEqual(settings.embedding_model, "all-minilm:latest")
        self.assertEqual(settings.embedding_timeout_seconds, 30)
        self.assertEqual(settings.embedding_batch_size, 32)
        self.assertEqual(settings.embedding_dimension, 384)


class LoadSettingsOverridesTest(unittest.TestCase):
    def test_string_overrides(self):
        env = {
            "LLM_URL": "https://example/llm",
            "LLM_MODEL": "custom-model",
            "LLM_KEEP_ALIVE": "30m",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.llm_url, "https://example/llm")
        self.assertEqual(settings.llm_model, "custom-model")
        self.assertEqual(settings.llm_keep_alive, "30m")

    def test_int_overrides(self):
        env = {
            "LLM_TIMEOUT": "42",
            "LLM_NUM_CTX": "4096",
            "LLM_NUM_PREDICT": "512",
            "LLM_LOG_MAX_CHARS": "250",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.llm_timeout, 42)
        self.assertEqual(settings.llm_num_ctx, 4096)
        self.assertEqual(settings.llm_num_predict, 512)
        self.assertEqual(settings.llm_log_max_chars, 250)

    def test_bool_overrides_truthy_and_falsy(self):
        for raw, expected in [("1", True), ("true", True), ("YES", True), ("On", True),
                              ("0", False), ("false", False), ("no", False), ("OFF", False)]:
            with mock.patch.dict(os.environ, {"LLM_LOG_CONTENT": raw}, clear=True):
                self.assertEqual(load_settings().llm_log_content, expected, msg=raw)

    def test_int_override_rejects_non_integer(self):
        with mock.patch.dict(os.environ, {"LLM_TIMEOUT": "fast"}, clear=True):
            with self.assertRaises(ValueError):
                load_settings()

    def test_bool_override_rejects_unknown(self):
        with mock.patch.dict(os.environ, {"LLM_LOG_CONTENT": "maybe"}, clear=True):
            with self.assertRaises(ValueError):
                load_settings()


class LoadEmbeddingSettingsTest(unittest.TestCase):
    def test_embedding_overrides_apply(self):
        env = {
            "EMBEDDING_URL": "http://embed-host:9000/api/embed",
            "EMBEDDING_MODEL": "nomic-embed-text",
            "EMBEDDING_TIMEOUT_SECONDS": "45",
            "EMBEDDING_BATCH_SIZE": "16",
            "EMBEDDING_DIMENSION": "768",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.embedding_url, "http://embed-host:9000/api/embed")
        self.assertEqual(settings.embedding_model, "nomic-embed-text")
        self.assertEqual(settings.embedding_timeout_seconds, 45)
        self.assertEqual(settings.embedding_batch_size, 16)
        self.assertEqual(settings.embedding_dimension, 768)

    def test_embedding_settings_are_independent_from_llm_settings(self):
        env = {
            "LLM_URL": "http://llm-host:11434/api/generate",
            "LLM_MODEL": "different-llm-model",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertNotEqual(settings.embedding_url, settings.llm_url)
        self.assertNotEqual(settings.embedding_model, settings.llm_model)
        self.assertEqual(
            settings.embedding_url,
            "http://localhost:11434/api/embed",
        )
        self.assertEqual(settings.embedding_model, "all-minilm:latest")

    def test_embedding_settings_are_frozen(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = load_settings()
        with self.assertRaises(Exception):
            settings.embedding_model = "other"  # type: ignore[misc]
        with self.assertRaises(Exception):
            settings.embedding_batch_size = 1  # type: ignore[misc]

    def test_embedding_positive_int_overrides_reject_non_positive_values(self):
        for var in ("EMBEDDING_TIMEOUT_SECONDS", "EMBEDDING_BATCH_SIZE", "EMBEDDING_DIMENSION"):
            for raw in ("0", "-3", "abc"):
                with mock.patch.dict(os.environ, {var: raw}, clear=True):
                    with self.assertRaises(ValueError, msg=f"{var}={raw}"):
                        load_settings()


if __name__ == "__main__":
    unittest.main()
