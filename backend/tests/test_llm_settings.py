import os
import unittest
from dataclasses import FrozenInstanceError
from unittest import mock

from backend.config.settings import Settings, load_settings
from backend.services.exceptions import (
    InvalidTwilioWebhookAuthToken,
    InvalidTwilioWebhookBaseUrl,
)


class LoadSettingsDefaultsTest(unittest.TestCase):
    def test_default_values_when_no_overrides(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = load_settings()
        self.assertEqual(
            settings,
            Settings(
                llm_url="http://localhost:11434/api/generate",
                llm_model="qwen2.5-coder:7b-ctx8192",
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
            "EMBEDDING_MODEL": "test-embedding-model",
            "EMBEDDING_TIMEOUT_SECONDS": "45",
            "EMBEDDING_BATCH_SIZE": "16",
            "EMBEDDING_DIMENSION": "768",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.embedding_url, "http://embed-host:9000/api/embed")
        self.assertEqual(settings.embedding_model, "test-embedding-model")
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


class LoadOllamaProxySettingsTest(unittest.TestCase):
    def test_proxy_is_none_when_unset(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(load_settings().ollama_proxy_url)

    def test_valid_loopback_socks_proxy_is_accepted(self):
        with mock.patch.dict(
            os.environ,
            {"OLLAMA_PROXY_URL": " socks5h://127.0.0.1:1055 "},
            clear=True,
        ):
            self.assertEqual(
                load_settings().ollama_proxy_url,
                "socks5h://127.0.0.1:1055",
            )

    def test_invalid_proxy_is_rejected(self):
        for value in (
            "",
            "   ",
            "/relative",
            "https://proxy.test",
            "http://127.0.0.1:1055",
        ):
            with self.subTest(value=value), mock.patch.dict(
                os.environ,
                {"OLLAMA_PROXY_URL": value},
                clear=True,
            ):
                with self.assertRaisesRegex(ValueError, "OLLAMA_PROXY_URL"):
                    load_settings()


class LoadTwilioIngressSettingsTest(unittest.TestCase):
    def test_default_twilio_settings_are_none(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = load_settings()
        self.assertIsNone(settings.twilio_auth_token)
        self.assertIsNone(settings.twilio_webhook_base_url)

    def test_twilio_auth_token_override_is_accepted(self):
        env = {"TWILIO_AUTH_TOKEN": "  test-token  "}
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.twilio_auth_token, "test-token")

    def test_twilio_base_url_override_is_accepted(self):
        env = {"TWILIO_WEBHOOK_BASE_URL": "https://example.test/"}
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(
            settings.twilio_webhook_base_url, "https://example.test/"
        )

    def test_empty_twilio_auth_token_rejected(self):
        env = {"TWILIO_AUTH_TOKEN": "   "}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(InvalidTwilioWebhookAuthToken):
                load_settings()

    def test_non_https_base_url_rejected(self):
        env = {"TWILIO_WEBHOOK_BASE_URL": "http://example.test"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(InvalidTwilioWebhookBaseUrl):
                load_settings()

    def test_relative_base_url_rejected(self):
        env = {"TWILIO_WEBHOOK_BASE_URL": "/no/host"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(InvalidTwilioWebhookBaseUrl):
                load_settings()

    def test_base_url_with_query_string_rejected(self):
        env = {
            "TWILIO_WEBHOOK_BASE_URL": "https://example.test/?hub=1"
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(InvalidTwilioWebhookBaseUrl):
                load_settings()

    def test_base_url_with_fragment_rejected(self):
        env = {
            "TWILIO_WEBHOOK_BASE_URL": "https://example.test/#frag"
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(InvalidTwilioWebhookBaseUrl):
                load_settings()

    def test_empty_base_url_rejected(self):
        env = {"TWILIO_WEBHOOK_BASE_URL": "   "}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(InvalidTwilioWebhookBaseUrl):
                load_settings()

    def test_twilio_settings_are_frozen(self):
        env = {
            "TWILIO_AUTH_TOKEN": "test-token",
            "TWILIO_WEBHOOK_BASE_URL": "https://example.test",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        with self.assertRaises(FrozenInstanceError):
            settings.twilio_auth_token = "other"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            settings.twilio_webhook_base_url = "other"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
