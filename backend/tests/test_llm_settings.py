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


if __name__ == "__main__":
    unittest.main()
