import os
import unittest
from dataclasses import FrozenInstanceError
from unittest import mock

from backend.config.settings import (
    DEFAULT_LLM_HTTP_CLIENT,
    Settings,
    load_settings,
)
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

    def test_valid_socks5_scheme_is_accepted(self):
        with mock.patch.dict(
            os.environ,
            {"OLLAMA_PROXY_URL": "socks5://127.0.0.1:1055"},
            clear=True,
        ):
            self.assertEqual(
                load_settings().ollama_proxy_url,
                "socks5://127.0.0.1:1055",
            )

    def test_valid_loopback_http_proxy_is_accepted(self):
        with mock.patch.dict(
            os.environ,
            {"OLLAMA_PROXY_URL": "http://127.0.0.1:1056"},
            clear=True,
        ):
            self.assertEqual(
                load_settings().ollama_proxy_url,
                "http://127.0.0.1:1056",
            )

    def test_http_proxy_strips_surrounding_whitespace(self):
        with mock.patch.dict(
            os.environ,
            {"OLLAMA_PROXY_URL": "  http://127.0.0.1:1056  "},
            clear=True,
        ):
            self.assertEqual(
                load_settings().ollama_proxy_url,
                "http://127.0.0.1:1056",
            )

    def test_invalid_proxy_is_rejected(self):
        for value in (
            "",
            "   ",
            "/relative",
            "https://proxy.test",
            "ftp://127.0.0.1:1055",
            "HTTP_PROXY=http://127.0.0.1:1056",
        ):
            with self.subTest(value=value), mock.patch.dict(
                os.environ,
                {"OLLAMA_PROXY_URL": value},
                clear=True,
            ):
                with self.assertRaisesRegex(ValueError, "OLLAMA_PROXY_URL"):
                    load_settings()

    def test_proxy_with_credentials_is_rejected(self):
        with mock.patch.dict(
            os.environ,
            {"OLLAMA_PROXY_URL": "http://user:pass@127.0.0.1:1056"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "OLLAMA_PROXY_URL"):
                load_settings()

    def test_proxy_with_path_query_or_fragment_is_rejected(self):
        for value in (
            "http://127.0.0.1:1056/api",
            "http://127.0.0.1:1056?hub=1",
            "http://127.0.0.1:1056#frag",
        ):
            with self.subTest(value=value), mock.patch.dict(
                os.environ,
                {"OLLAMA_PROXY_URL": value},
                clear=True,
            ):
                with self.assertRaisesRegex(ValueError, "OLLAMA_PROXY_URL"):
                    load_settings()

    def test_proxy_without_host_is_rejected(self):
        with mock.patch.dict(
            os.environ,
            {"OLLAMA_PROXY_URL": "http://"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "OLLAMA_PROXY_URL"):
                load_settings()

    def test_http_proxy_requires_loopback_host(self):
        """The Railway HTTP Tailscale listener is local-only on
        ``127.0.0.1:1056``. A remote HTTP proxy host would defeat the
        loopback boundary and is therefore rejected before the
        Ollama clients ever see the value.
        """
        for value in (
            "http://proxy.example:8080",
            "http://100.113.65.40:1056",
            "http://localhost:1056",
            "http://[::1]:1056",
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


class LoadLlmHttpClientSettingsTest(unittest.TestCase):
    """Closed vocabulary for the QueryLlm transport selection.

    The setting exists to drive an opt-in, reversible Test-only
    HTTPX experiment behind ``LLM_HTTP_CLIENT=httpx``; the
    Requests transport remains the production default. The value
    is never treated as an endpoint, proxy, header, credential or
    customer input and is rejected explicitly so a
    misconfiguration never reaches an HTTP request.
    """

    def test_default_is_requests_when_absent(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = load_settings()
        self.assertEqual(settings.llm_http_client, "requests")
        self.assertEqual(settings.llm_http_client, DEFAULT_LLM_HTTP_CLIENT)
        self.assertEqual(DEFAULT_LLM_HTTP_CLIENT, "requests")

    def test_blank_value_resolves_to_requests(self):
        for raw in ("", "   "):
            with self.subTest(raw=raw), mock.patch.dict(
                os.environ, {"LLM_HTTP_CLIENT": raw}, clear=True
            ):
                settings = load_settings()
            self.assertEqual(settings.llm_http_client, "requests")

    def test_explicit_requests_value_is_accepted(self):
        with mock.patch.dict(
            os.environ, {"LLM_HTTP_CLIENT": "requests"}, clear=True
        ):
            settings = load_settings()
        self.assertEqual(settings.llm_http_client, "requests")

    def test_explicit_httpx_value_is_accepted(self):
        with mock.patch.dict(
            os.environ, {"LLM_HTTP_CLIENT": "httpx"}, clear=True
        ):
            settings = load_settings()
        self.assertEqual(settings.llm_http_client, "httpx")

    def test_value_is_normalised_lowercase_and_stripped(self):
        for raw, expected in (
            ("  httpx  ", "httpx"),
            ("HTTPX", "httpx"),
            ("\trequests\n", "requests"),
            ("Requests", "requests"),
        ):
            with self.subTest(raw=raw), mock.patch.dict(
                os.environ, {"LLM_HTTP_CLIENT": raw}, clear=True
            ):
                settings = load_settings()
            self.assertEqual(settings.llm_http_client, expected)

    def test_invalid_value_is_rejected_before_request(self):
        for raw in (
            "curl",
            "urllib",
            "aiohttp",
            "http",
            "requests2",
            "requests,httpx",
        ):
            with self.subTest(raw=raw), mock.patch.dict(
                os.environ, {"LLM_HTTP_CLIENT": raw}, clear=True
            ):
                with self.assertRaisesRegex(
                    ValueError, "LLM_HTTP_CLIENT"
                ) as ctx:
                    load_settings()
                rendered = str(ctx.exception).lower()
                self.assertNotIn("://", rendered)
                self.assertNotIn("socks5", rendered)
                self.assertNotIn("proxy=", rendered)
                self.assertNotIn("bearer", rendered)
                self.assertNotIn("authorization", rendered)

    def test_invalid_value_message_does_not_leak_secret_markers(self):
        """The error MUST surface the closed vocabulary clearly without
        echoing secret-shaped input verbatim. Echoing the raw
        ``LLM_HTTP_CLIENT`` value is allowed because the field is
        a transport selector and not a credential, but the helper
        MUST avoid secret-marker leakage that the operator could
        mistake for a credential echo.
        """
        with mock.patch.dict(
            os.environ,
            {"LLM_HTTP_CLIENT": "bearer-token-should-not-echo-as-credential"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "LLM_HTTP_CLIENT") as ctx:
                load_settings()
        rendered = str(ctx.exception)
        self.assertNotIn("Authorization", rendered)
        self.assertNotIn("Bearer bearer-token", rendered)
        self.assertNotIn("secret=", rendered)
        self.assertNotIn("password=", rendered)

    def test_settings_is_frozen_for_llm_http_client(self):
        with mock.patch.dict(
            os.environ, {"LLM_HTTP_CLIENT": "httpx"}, clear=True
        ):
            settings = load_settings()
        with self.assertRaises(FrozenInstanceError):
            settings.llm_http_client = "requests"  # type: ignore[misc]

    def test_settings_field_coexists_with_existing_fields(self):
        with mock.patch.dict(
            os.environ, {"LLM_HTTP_CLIENT": "httpx"}, clear=True
        ):
            settings = load_settings()
        self.assertEqual(settings.llm_http_client, "httpx")
        self.assertEqual(settings.llm_url, "http://localhost:11434/api/generate")
        self.assertEqual(settings.llm_model, "qwen2.5-coder:7b-ctx8192")
        self.assertEqual(settings.llm_timeout, 180)
        self.assertIsNone(settings.ollama_proxy_url)


if __name__ == "__main__":
    unittest.main()
