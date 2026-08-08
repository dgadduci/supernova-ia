import json
import logging
import os
import unittest
from unittest import mock

import requests

from backend.config.settings import Settings, load_settings
from backend.llm.query_llm import (
    QueryLlm,
    QueryLlmConnectionError,
    QueryLlmError,
    QueryLlmHttpError,
    QueryLlmResponseError,
    QueryLlmTimeoutError,
)


def _settings(**overrides) -> Settings:
    base = dict(
        llm_url="http://llm.test/api/generate",
        llm_model="test-model",
        llm_timeout=30,
        llm_keep_alive="1h",
        llm_num_ctx=2048,
        llm_num_predict=256,
        llm_log_content=False,
        llm_log_max_chars=50,
    )
    base.update(overrides)
    return Settings(**base)


class _FakeResponse:
    def __init__(self, body: str, status_code: int = 200):
        self._body = body
        self.status_code = status_code
        self.text = body

    def json(self):
        return {"response": self._body}

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.exceptions.HTTPError(f"{self.status_code} error")
            err.response = self
            raise err


class QueryLlmPayloadTest(unittest.TestCase):
    def test_payload_contains_all_required_fields(self):
        captured = {}

        def transport(url, **kwargs):
            captured["url"] = url
            captured["payload"] = kwargs.get("json")
            captured["timeout"] = kwargs.get("timeout")
            return _FakeResponse(json.dumps({"ok": True}))

        settings = _settings()
        client = QueryLlm(settings=settings, transport=transport)
        result = client.request("hola")

        self.assertEqual(captured["url"], settings.llm_url)
        self.assertEqual(captured["timeout"], settings.llm_timeout)
        payload = captured["payload"]
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["prompt"], "hola")
        self.assertEqual(payload["stream"], False)
        self.assertEqual(payload["think"], False)
        self.assertEqual(payload["format"], "json")
        self.assertEqual(payload["keep_alive"], "1h")
        self.assertEqual(payload["options"]["temperature"], 0)
        self.assertEqual(payload["options"]["num_predict"], 256)
        self.assertEqual(payload["options"]["num_ctx"], 2048)
        self.assertEqual(result, {"ok": True})

    def test_real_transport_uses_configured_proxy(self):
        response = _FakeResponse(json.dumps({"ok": True}))
        settings = _settings(ollama_proxy_url="socks5h://127.0.0.1:1055")
        with mock.patch("backend.llm.query_llm.requests.post", return_value=response) as post:
            QueryLlm(settings=settings).request("hola")
        self.assertEqual(
            post.call_args.kwargs["proxies"],
            {"http": "socks5h://127.0.0.1:1055", "https": "socks5h://127.0.0.1:1055"},
        )

    def test_real_transport_has_no_proxy_when_unset(self):
        response = _FakeResponse(json.dumps({"ok": True}))
        with mock.patch("backend.llm.query_llm.requests.post", return_value=response) as post:
            QueryLlm(settings=_settings()).request("hola")
        self.assertNotIn("proxies", post.call_args.kwargs)

    def test_injected_transport_does_not_receive_proxy_keyword(self):
        transport = mock.Mock(return_value=_FakeResponse(json.dumps({"ok": True})))
        QueryLlm(
            settings=_settings(ollama_proxy_url="socks5h://127.0.0.1:1055"),
            transport=transport,
        ).request("hola")
        self.assertNotIn("proxies", transport.call_args.kwargs)

    def test_request_does_not_mutate_settings(self):
        settings = _settings()
        transport = mock.Mock(return_value=_FakeResponse(json.dumps({"ok": True})))
        client = QueryLlm(settings=settings, transport=transport)
        before = settings.llm_model
        client.request("uno")
        client.request("dos")
        self.assertEqual(settings.llm_model, before)
        self.assertEqual(transport.call_count, 2)
        first_payload = transport.call_args_list[0].kwargs["json"]
        second_payload = transport.call_args_list[1].kwargs["json"]
        self.assertIsNot(first_payload, second_payload)


class QueryLlmDefaultContractTest(unittest.TestCase):
    """Locked-in defaults for the non-semantic QueryLlm path."""

    def test_load_settings_default_model_and_context(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = load_settings()
        self.assertEqual(settings.llm_model, "qwen2.5-coder:7b-ctx8192")
        self.assertEqual(settings.llm_num_ctx, 8192)

    def test_query_llm_payload_emits_default_model_and_context(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            settings = load_settings()

        captured = {}

        def transport(url, **kwargs):
            captured["url"] = url
            captured["payload"] = kwargs.get("json")
            return _FakeResponse(json.dumps({"ok": True}))

        QueryLlm(settings=settings, transport=transport).request("hola")

        payload = captured["payload"]
        self.assertEqual(payload["model"], "qwen2.5-coder:7b-ctx8192")
        self.assertEqual(payload["options"]["num_ctx"], 8192)
        self.assertEqual(payload["stream"], False)
        self.assertEqual(payload["think"], False)
        self.assertEqual(payload["format"], "json")
        self.assertEqual(payload["options"]["temperature"], 0)

    def test_env_overrides_take_precedence_over_default(self):
        env = {
            "LLM_MODEL": "custom-7b-override",
            "LLM_NUM_CTX": "4096",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            settings = load_settings()

        captured = {}

        def transport(url, **kwargs):
            captured["payload"] = kwargs.get("json")
            return _FakeResponse(json.dumps({"ok": True}))

        QueryLlm(settings=settings, transport=transport).request("hola")

        payload = captured["payload"]
        self.assertEqual(payload["model"], "custom-7b-override")
        self.assertEqual(payload["options"]["num_ctx"], 4096)


class QueryLlmParsingTest(unittest.TestCase):
    def test_clean_json_is_parsed(self):
        transport = mock.Mock(return_value=_FakeResponse(json.dumps({"a": 1, "b": [2, 3]})))
        client = QueryLlm(settings=_settings(), transport=transport)
        self.assertEqual(client.request("p"), {"a": 1, "b": [2, 3]})

    def test_json_extracted_from_surrounding_text(self):
        body = 'texto { "intents": [] } más'
        transport = mock.Mock(return_value=_FakeResponse(body))
        client = QueryLlm(settings=_settings(), transport=transport)
        self.assertEqual(client.request("p"), {"intents": []})

    def test_empty_body_raises_response_error(self):
        transport = mock.Mock(return_value=_FakeResponse(""))
        client = QueryLlm(settings=_settings(), transport=transport)
        with self.assertRaises(QueryLlmResponseError):
            client.request("p")

    def test_whitespace_only_body_raises_response_error(self):
        transport = mock.Mock(return_value=_FakeResponse("   \n\t  "))
        client = QueryLlm(settings=_settings(), transport=transport)
        with self.assertRaises(QueryLlmResponseError):
            client.request("p")

    def test_invalid_json_without_braces_raises_response_error(self):
        transport = mock.Mock(return_value=_FakeResponse("not-json"))
        client = QueryLlm(settings=_settings(), transport=transport)
        with self.assertRaises(QueryLlmResponseError):
            client.request("p")

    def test_invalid_json_with_unmatched_braces_raises_response_error(self):
        transport = mock.Mock(return_value=_FakeResponse("{ broken "))
        client = QueryLlm(settings=_settings(), transport=transport)
        with self.assertRaises(QueryLlmResponseError):
            client.request("p")


class QueryLlmErrorsTest(unittest.TestCase):
    def test_timeout_raises_timeout_error(self):
        def transport(url, json=None, timeout=None):
            raise requests.exceptions.Timeout("slow")

        client = QueryLlm(settings=_settings(), transport=transport)
        with self.assertRaises(QueryLlmTimeoutError):
            client.request("p")

    def test_connection_error_raises_connection_error(self):
        def transport(url, json=None, timeout=None):
            raise requests.exceptions.ConnectionError("nope")

        client = QueryLlm(settings=_settings(), transport=transport)
        with self.assertRaises(QueryLlmConnectionError):
            client.request("p")

    def test_http_error_raises_http_error_with_status(self):
        transport = mock.Mock(return_value=_FakeResponse("boom", status_code=503))
        client = QueryLlm(settings=_settings(), transport=transport)
        with self.assertRaises(QueryLlmHttpError) as ctx:
            client.request("p")
        self.assertEqual(ctx.exception.status_code, 503)

    def test_timeout_error_is_subclass_of_base(self):
        self.assertTrue(issubclass(QueryLlmTimeoutError, QueryLlmError))
        self.assertTrue(issubclass(QueryLlmConnectionError, QueryLlmError))
        self.assertTrue(issubclass(QueryLlmHttpError, QueryLlmError))
        self.assertTrue(issubclass(QueryLlmResponseError, QueryLlmError))

    def test_request_never_returns_none(self):
        transport = mock.Mock(return_value=_FakeResponse(json.dumps({"ok": True})))
        client = QueryLlm(settings=_settings(), transport=transport)
        self.assertIsNotNone(client.request("p"))


class QueryLlmInputValidationTest(unittest.TestCase):
    def test_empty_prompt_raises_value_error_without_calling_transport(self):
        transport = mock.Mock()
        client = QueryLlm(settings=_settings(), transport=transport)
        with self.assertRaises(ValueError):
            client.request("")
        transport.assert_not_called()

    def test_whitespace_only_prompt_raises_value_error(self):
        transport = mock.Mock()
        client = QueryLlm(settings=_settings(), transport=transport)
        with self.assertRaises(ValueError):
            client.request("   \n")
        transport.assert_not_called()

    def test_non_string_prompt_raises_value_error(self):
        transport = mock.Mock()
        client = QueryLlm(settings=_settings(), transport=transport)
        with self.assertRaises(ValueError):
            client.request(None)  # type: ignore[arg-type]
        transport.assert_not_called()


class QueryLlmLoggingTest(unittest.TestCase):
    def _make_client(self, **setting_overrides):
        settings = _settings(**setting_overrides)
        return QueryLlm(settings=settings, transport=mock.Mock(return_value=_FakeResponse(json.dumps({"ok": True}))))

    def test_info_logs_carry_metadata_without_content(self):
        client = self._make_client()
        with self.assertLogs("backend.llm.query_llm", level="INFO") as captured:
            client.request("super-secret-prompt")
        joined = "\n".join(captured.output)
        self.assertIn("llm request start", joined)
        self.assertIn("test-model", joined)
        self.assertIn("llm request success", joined)
        self.assertNotIn("super-secret-prompt", joined)

    def test_debug_content_logs_only_when_enabled(self):
        client = self._make_client(llm_log_content=True)
        with self.assertLogs("backend.llm.query_llm", level="DEBUG") as captured:
            client.request("super-secret-prompt")
        joined = "\n".join(captured.output)
        self.assertIn("super-secret-prompt", joined)

        client_disabled = self._make_client(llm_log_content=False)
        with self.assertLogs("backend.llm.query_llm", level="DEBUG") as captured_disabled:
            client_disabled.request("super-secret-prompt")
        joined_disabled = "\n".join(captured_disabled.output)
        self.assertNotIn("super-secret-prompt", joined_disabled)

    def test_content_logs_are_truncated(self):
        long_prompt = "x" * 500
        client = self._make_client(llm_log_content=True, llm_log_max_chars=10)
        with self.assertLogs("backend.llm.query_llm", level="DEBUG") as captured:
            client.request(long_prompt)
        joined = "\n".join(captured.output)
        self.assertIn("…", joined)
        self.assertNotIn("x" * 100, joined)

    def test_module_does_not_configure_global_logging(self):
        root_handlers_before = list(logging.getLogger().handlers)
        # Importing should not register new root handlers.
        from backend.llm import query_llm as _reimport  # noqa: F401

        root_handlers_after = list(logging.getLogger().handlers)
        self.assertEqual(root_handlers_before, root_handlers_after)


if __name__ == "__main__":
    unittest.main()
