import io
import json
import logging
import os
import unittest
from unittest import mock

import httpx
import requests

from backend.config.settings import Settings, load_settings
from backend.llm.query_llm import (
    QueryLlm,
    QueryLlmConnectionError,
    QueryLlmError,
    QueryLlmHttpError,
    QueryLlmResponseError,
    QueryLlmTimeoutError,
    current_llm_correlation_id,
    install_llm_timing_recorder,
    reset_llm_timing_recorder,
)
from backend.observability import EventValidationError


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
        self.closed = False

    def json(self):
        return {"response": self._body}

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.exceptions.HTTPError(f"{self.status_code} error")
            err.response = self
            raise err

    def close(self):
        self.closed = True


class _FakeStreamingResponse:
    """Streaming-capable fake response for the ``iter_content`` path.

    The ``inner_body`` constructor argument is the JSON string Ollama
    stores inside the ``response`` envelope field. The wrapper
    serialises that inner string with :func:`json.dumps` so the
    envelope bytes returned through :meth:`iter_content` reconstruct
    exactly the same envelope string the real Ollama ``/api/generate``
    path produces with ``stream: false``. ``close`` records the call
    so success / failure close semantics can be asserted.
    """

    def __init__(
        self,
        inner_body: str,
        *,
        status_code: int = 200,
        chunk_size: int = 4,
    ) -> None:
        self._inner_body = inner_body
        self._envelope = json.dumps({"response": inner_body})
        self.status_code = status_code
        self.text = self._envelope
        self._chunk_size = chunk_size
        self.closed = False
        self.iter_calls = 0

    def iter_content(self, chunk_size: int = 8192):
        self.iter_calls += 1
        data = self._envelope.encode("utf-8")
        size = self._chunk_size if self._chunk_size > 0 else chunk_size
        for i in range(0, len(data), size):
            yield data[i:i + size]

    def json(self):
        return {"response": self._inner_body}

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.exceptions.HTTPError(f"{self.status_code} error")
            err.response = self
            raise err

    def close(self):
        self.closed = True


class _FakeHttpxStreamingResponse:
    """Streaming-capable fake response shaped like :class:`httpx.Response`.

    The class mirrors :class:`_FakeStreamingResponse` but exposes
    :meth:`iter_bytes` instead of :meth:`iter_content` so the
    :class:`_HttpxResponseAdapter` in :mod:`backend.llm.query_llm`
    can consume it. The wrapper also tracks ``close`` and ``iter``
    calls so tests can assert success / failure close semantics.
    """

    def __init__(
        self,
        inner_body: str,
        *,
        status_code: int = 200,
        chunk_size: int = 4,
    ) -> None:
        self._inner_body = inner_body
        self._envelope = json.dumps({"response": inner_body})
        self.status_code = int(status_code)
        self._chunk_size = chunk_size
        self.closed = False
        self.iter_calls = 0

    @property
    def text(self) -> str:
        return self._envelope

    def iter_bytes(self, chunk_size: int = 8192):
        self.iter_calls += 1
        data = self._envelope.encode("utf-8")
        size = self._chunk_size if self._chunk_size > 0 else chunk_size
        for i in range(0, len(data), size):
            yield data[i:i + size]

    def json(self):
        return {"response": self._inner_body}

    def close(self):
        self.closed = True


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

    def test_real_transport_uses_configured_non_socks_proxy(self):
        """Non-SOCKS proxies continue to be forwarded verbatim through
        ``requests.post(proxies=...)`` so the legacy ``requests`` /
        ``urllib3`` HTTP proxy path is preserved untouched."""
        response = _FakeResponse(json.dumps({"ok": True}))
        settings = _settings(ollama_proxy_url="http://127.0.0.1:3128")
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ) as post:
            QueryLlm(settings=settings).request("hola")
        self.assertEqual(
            post.call_args.kwargs["proxies"],
            {"http": "http://127.0.0.1:3128", "https": "http://127.0.0.1:3128"},
        )

    def test_real_transport_routes_socks_proxy_through_observer_session(
        self,
    ):
        """A SOCKS proxy URL routes through a fresh private observer
        session; ``requests.post`` is not invoked so the legacy
        ``proxies=`` kwarg path stays out of the SOCKS branch.

        The session is constructed per call (``_post_requests`` does
        not cache it) so the patched constructor must be exercised
        exactly once and the response ``close`` path must close the
        patched session too."""
        response = _FakeResponse(json.dumps({"ok": True}))
        observer_session = mock.Mock()
        observer_session.post.return_value = response
        settings = _settings(ollama_proxy_url="socks5h://127.0.0.1:1055")
        with mock.patch(
            "backend.llm.query_llm._SocksPhaseObserverSession",
            return_value=observer_session,
        ) as session_factory:
            with mock.patch(
                "backend.llm.query_llm.requests.post"
            ) as legacy_post:
                QueryLlm(settings=settings).request("hola")
        session_factory.assert_called_once_with()
        observer_session.post.assert_called_once()
        legacy_post.assert_not_called()
        # The proxy URL is forwarded through the session so requests
        # can route through our adapter instead of direct traffic.
        self.assertEqual(
            observer_session.post.call_args.kwargs.get("proxies"),
            {
                "http": "socks5h://127.0.0.1:1055",
                "https": "socks5h://127.0.0.1:1055",
            },
        )
        self.assertEqual(
            observer_session.post.call_args.args[0], settings.llm_url
        )
        self.assertEqual(
            observer_session.post.call_args.kwargs.get("timeout"),
            settings.llm_timeout,
        )
        self.assertTrue(observer_session.post.call_args.kwargs.get("stream"))
        # The wrapper must close the patched session exactly once
        # when the surrounding ``finally`` block closes the response.
        observer_session.close.assert_called_once_with()

    def test_real_transport_socks_session_is_closed_with_response(
        self,
    ):
        """The private SOCKS session MUST be closed when the response
        is closed by the surrounding ``QueryLlm.request`` ``finally``
        block. The wrapper is idempotent so a second ``close`` call
        does NOT re-close the session."""
        response = _FakeResponse(json.dumps({"ok": True}))
        observer_session = mock.Mock()
        observer_session.post.return_value = response
        settings = _settings(ollama_proxy_url="socks5h://127.0.0.1:1055")
        with mock.patch(
            "backend.llm.query_llm._SocksPhaseObserverSession",
            return_value=observer_session,
        ):
            QueryLlm(settings=settings).request("hola")
            # Simulate a second close() pass on the response object
            # so the wrapper's idempotent guard is exercised.
            response.close()
        observer_session.close.assert_called_once_with()

    def test_real_transport_two_socks_calls_build_independent_sessions(
        self,
    ):
        """Two consecutive ``QueryLlm`` SOCKS requests MUST build
        independent session resources and MUST NOT share a session
        / pool / adapter / proxy manager / socket."""
        from backend.llm import query_llm as _query_llm_module

        response_a = _FakeResponse(json.dumps({"first": True}))
        response_b = _FakeResponse(json.dumps({"second": True}))
        session_a = mock.Mock()
        session_a.post.return_value = response_a
        session_b = mock.Mock()
        session_b.post.return_value = response_b
        constructor = mock.Mock(side_effect=[session_a, session_b])
        settings = _settings(ollama_proxy_url="socks5h://127.0.0.1:1055")
        with mock.patch.object(
            _query_llm_module, "_SocksPhaseObserverSession", constructor
        ):
            first = QueryLlm(settings=settings).request(
                "hola", correlation_id="SYN-SOCKS-DUP-A"
            )
            second = QueryLlm(settings=settings).request(
                "hola", correlation_id="SYN-SOCKS-DUP-B"
            )

        self.assertEqual(first, {"first": True})
        self.assertEqual(second, {"second": True})
        self.assertEqual(constructor.call_count, 2)
        self.assertIsNot(session_a, session_b)
        session_a.close.assert_called_once_with()
        session_b.close.assert_called_once_with()

    def test_real_transport_uses_loopback_http_proxy(self):
        response = _FakeResponse(json.dumps({"ok": True}))
        settings = _settings(ollama_proxy_url="http://127.0.0.1:1056")
        with mock.patch("backend.llm.query_llm.requests.post", return_value=response) as post:
            QueryLlm(settings=settings).request("hola")
        self.assertEqual(
            post.call_args.kwargs["proxies"],
            {"http": "http://127.0.0.1:1056", "https": "http://127.0.0.1:1056"},
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

    def test_injected_transport_does_not_receive_http_proxy_keyword(self):
        transport = mock.Mock(return_value=_FakeResponse(json.dumps({"ok": True})))
        QueryLlm(
            settings=_settings(ollama_proxy_url="http://127.0.0.1:1056"),
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
    PROMPT_SENTINEL = "PROMPT-SENTINEL-XYZZY-42"
    RESPONSE_SENTINEL = "RESPONSE-SENTINEL-QWERTY-99"

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

    def test_debug_logs_never_contain_prompt_or_response_content(self):
        response_body = json.dumps({"ok": self.RESPONSE_SENTINEL})

        client = QueryLlm(
            settings=_settings(llm_log_content=True),
            transport=mock.Mock(return_value=_FakeResponse(response_body)),
        )
        with self.assertLogs("backend.llm.query_llm", level="DEBUG") as captured:
            client.request(self.PROMPT_SENTINEL)
        joined = "\n".join(captured.output)
        self.assertNotIn(self.PROMPT_SENTINEL, joined)
        self.assertNotIn(self.RESPONSE_SENTINEL, joined)

        client_disabled = QueryLlm(
            settings=_settings(llm_log_content=False),
            transport=mock.Mock(return_value=_FakeResponse(response_body)),
        )
        with self.assertLogs("backend.llm.query_llm", level="DEBUG") as captured_disabled:
            client_disabled.request(self.PROMPT_SENTINEL)
        joined_disabled = "\n".join(captured_disabled.output)
        self.assertNotIn(self.PROMPT_SENTINEL, joined_disabled)
        self.assertNotIn(self.RESPONSE_SENTINEL, joined_disabled)

    def test_long_prompt_does_not_leak_through_any_log(self):
        long_prompt = "x" * 500
        client = self._make_client(llm_log_content=True, llm_log_max_chars=10)
        with self.assertLogs("backend.llm.query_llm", level="DEBUG") as captured:
            client.request(long_prompt)
        joined = "\n".join(captured.output)
        self.assertNotIn("x" * 100, joined)
        self.assertNotIn("…", joined)

    def test_debug_logs_do_not_leak_url_proxy_or_credentials(self):
        client = self._make_client(
            llm_url="http://secret-host.invalid/api/generate",
            ollama_proxy_url="socks5h://user:pass@127.0.0.1:9050",
            llm_log_content=True,
        )
        with self.assertLogs("backend.llm.query_llm", level="DEBUG") as captured:
            client.request("hola")
        joined = "\n".join(captured.output)
        for forbidden in (
            "secret-host.invalid",
            "socks5h",
            "127.0.0.1",
            "user:pass",
            "9050",
            "/api/generate",
        ):
            self.assertNotIn(forbidden, joined)

    def test_safe_metadata_remains_logged_when_log_content_enabled(self):
        client = self._make_client(llm_log_content=True)
        with self.assertLogs("backend.llm.query_llm", level="DEBUG") as captured:
            client.request("hola")
        joined = "\n".join(captured.output)
        self.assertIn("test-model", joined)
        self.assertIn("duration=", joined)
        self.assertIn("status=", joined)
        self.assertIn("response_length=", joined)

    def test_failure_logs_carry_duration_without_exception_message(self):
        def _boom(url, json=None, timeout=None):
            raise requests.exceptions.ConnectionError("secret-detail-leaked")

        client = QueryLlm(settings=_settings(llm_log_content=True), transport=_boom)
        with self.assertLogs("backend.llm.query_llm", level="DEBUG") as captured:
            with self.assertRaises(QueryLlmConnectionError):
                client.request("hola")
        joined = "\n".join(captured.output)
        self.assertIn("llm request failure", joined)
        self.assertIn("duration=", joined)
        self.assertNotIn("secret-detail-leaked", joined)

    def test_module_does_not_configure_global_logging(self):
        root_handlers_before = list(logging.getLogger().handlers)
        # Importing should not register new root handlers.
        from backend.llm import query_llm as _reimport  # noqa: F401

        root_handlers_after = list(logging.getLogger().handlers)
        self.assertEqual(root_handlers_before, root_handlers_after)


class QueryLlmProviderCorrelationTest(unittest.TestCase):
    """The provider coordinator installs the safe synthetic
    inbound correlation value via :func:`install_llm_timing_recorder`
    so every ``llm_request`` event emitted from the same thread
    carries the same opaque identifier.

    Direct non-provider callers that do NOT install a recorder
    MUST continue to emit uncorrelated ``llm_request`` events
    so the bounded production-log parser can separate provider
    turns from background probes.
    """

    def setUp(self) -> None:
        reset_llm_timing_recorder()

    def tearDown(self) -> None:
        reset_llm_timing_recorder()

    def _capture_emit_events(self) -> list[dict]:
        captured: list[dict] = []

        def _capture(*, event: str, **kwargs: object) -> bool:
            from backend.observability.events import build_event

            payload = build_event(event=event, **kwargs)
            captured.append(payload)
            return True

        return captured, _capture

    def test_llm_request_emits_correlation_id_when_recorder_installed(
        self,
    ) -> None:
        captured, capture_fn = self._capture_emit_events()
        transport = mock.Mock(
            return_value=_FakeResponse(json.dumps({"ok": True}))
        )
        client = QueryLlm(settings=_settings(), transport=transport)
        install_llm_timing_recorder(
            mock.Mock(), correlation_id="SYN-PROV-1"
        )
        try:
            with mock.patch(
                "backend.llm.query_llm.emit_event",
                side_effect=capture_fn,
            ):
                client.request("hola")
        finally:
            reset_llm_timing_recorder()

        lifecycle_events = [
            ev for ev in captured if ev.get("event") == "llm_request"
        ]
        self.assertEqual(len(lifecycle_events), 2)
        self.assertEqual(lifecycle_events[0]["outcome"], "started")
        self.assertEqual(
            lifecycle_events[0]["correlation_id"], "SYN-PROV-1"
        )
        self.assertEqual(lifecycle_events[1]["outcome"], "completed")
        self.assertEqual(
            lifecycle_events[1]["correlation_id"], "SYN-PROV-1"
        )

    def test_direct_call_emits_no_correlation_id(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        transport = mock.Mock(
            return_value=_FakeResponse(json.dumps({"ok": True}))
        )
        client = QueryLlm(settings=_settings(), transport=transport)
        with mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            client.request("hola")

        lifecycle_events = [
            ev for ev in captured if ev.get("event") == "llm_request"
        ]
        self.assertEqual(len(lifecycle_events), 2)
        self.assertNotIn("correlation_id", lifecycle_events[0])
        self.assertNotIn("correlation_id", lifecycle_events[1])

    def test_correlation_id_cleared_after_reset(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        transport = mock.Mock(
            return_value=_FakeResponse(json.dumps({"ok": True}))
        )
        client = QueryLlm(settings=_settings(), transport=transport)
        install_llm_timing_recorder(
            mock.Mock(), correlation_id="SYN-PROV-2"
        )
        with mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            client.request("hola")
        reset_llm_timing_recorder()
        with mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            client.request("hola")
        # Only the FIRST pair must carry the correlation value.
        # The direct call after reset MUST be uncorrelated.
        lifecycle_events = [
            ev for ev in captured if ev.get("event") == "llm_request"
        ]
        self.assertEqual(len(lifecycle_events), 4)
        self.assertEqual(
            lifecycle_events[0]["correlation_id"], "SYN-PROV-2"
        )
        self.assertEqual(
            lifecycle_events[1]["correlation_id"], "SYN-PROV-2"
        )
        self.assertNotIn("correlation_id", lifecycle_events[2])
        self.assertNotIn("correlation_id", lifecycle_events[3])

    def test_correlation_id_truncated_to_max_length(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        transport = mock.Mock(
            return_value=_FakeResponse(json.dumps({"ok": True}))
        )
        client = QueryLlm(settings=_settings(), transport=transport)
        install_llm_timing_recorder(
            mock.Mock(), correlation_id="x" * 200
        )
        try:
            with mock.patch(
                "backend.llm.query_llm.emit_event",
                side_effect=capture_fn,
            ):
                client.request("hola")
        finally:
            reset_llm_timing_recorder()

        lifecycle_events = [
            ev for ev in captured if ev.get("event") == "llm_request"
        ]
        self.assertEqual(
            len(lifecycle_events[0]["correlation_id"]), 64
        )
        self.assertEqual(
            len(lifecycle_events[1]["correlation_id"]), 64
        )

    def test_current_llm_correlation_id_returns_none_when_unset(self):
        reset_llm_timing_recorder()
        self.assertIsNone(current_llm_correlation_id())

    def test_explicit_correlation_id_overrides_thread_local(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        transport = mock.Mock(
            return_value=_FakeResponse(json.dumps({"ok": True}))
        )
        client = QueryLlm(settings=_settings(), transport=transport)
        install_llm_timing_recorder(
            mock.Mock(), correlation_id="SYN-THREAD"
        )
        try:
            with mock.patch(
                "backend.llm.query_llm.emit_event",
                side_effect=capture_fn,
            ):
                client.request("hola", correlation_id="SYN-OVERRIDE")
        finally:
            reset_llm_timing_recorder()

        lifecycle_events = [
            ev for ev in captured if ev.get("event") == "llm_request"
        ]
        self.assertEqual(
            lifecycle_events[0]["correlation_id"], "SYN-OVERRIDE"
        )
        self.assertEqual(
            lifecycle_events[1]["correlation_id"], "SYN-OVERRIDE"
        )


class QueryLlmProviderBaseExceptionCleanupTest(unittest.TestCase):
    """``BaseException`` raised inside the provider scope MUST NOT
    leave the opaque synthetic inbound correlation installed on
    the worker thread.

    The provider coordinator wraps the leased inbound flow in a
    ``try/finally`` that calls
    :func:`install_llm_timing_recorder` with ``None`` whenever
    the flow exits — success, ``Exception`` or ``BaseException``
    such as :class:`KeyboardInterrupt` and :class:`SystemExit`.
    The unit-level contract is verified here against the
    ``query_llm`` thread-local helper so the LLM boundary cannot
    ever be polluted by a stale provider correlation. The full
    coordinator flow is verified separately in
    ``test_provider_message_receipt_core_integration``.
    """

    def setUp(self) -> None:
        reset_llm_timing_recorder()

    def tearDown(self) -> None:
        reset_llm_timing_recorder()

    def test_base_exception_inside_provider_scope_clears_correlation(
        self,
    ) -> None:
        """A ``BaseException`` raised inside the provider-scoped
        ``try/finally`` MUST clear the thread-local correlation so a
        later direct ``QueryLlm`` call from the same thread cannot
        inherit a stale opaque synthetic inbound identifier."""
        self.assertIsNone(current_llm_correlation_id())

        class _WorkerInterrupt(KeyboardInterrupt):
            pass

        # Simulate the coordinator's provider-scoped body: install
        # correlation, attempt work that raises a
        # ``BaseException``, then the ``finally`` block clears it
        # before the exception escapes.
        install_llm_timing_recorder(
            mock.Mock(), correlation_id="SYN-PROV-BASE"
        )
        self.assertEqual(
            current_llm_correlation_id(), "SYN-PROV-BASE"
        )
        with self.assertRaises(KeyboardInterrupt):
            try:
                raise _WorkerInterrupt("interrupted by operator")
            finally:
                install_llm_timing_recorder(None)

        # The BaseException escapes this scope but the thread
        # state is now clean.
        self.assertIsNone(current_llm_correlation_id())

        # A direct ``QueryLlm`` call MUST NOT carry the stale
        # provider correlation_id.
        captured, capture_fn = self._capture_emit_events()
        transport = mock.Mock(
            return_value=_FakeResponse(json.dumps({"ok": True}))
        )
        client = QueryLlm(settings=_settings(), transport=transport)
        with mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            client.request("hola")

        lifecycle_events = [
            ev for ev in captured if ev.get("event") == "llm_request"
        ]
        self.assertEqual(len(lifecycle_events), 2)
        self.assertNotIn("correlation_id", lifecycle_events[0])
        self.assertNotIn("correlation_id", lifecycle_events[1])

    def test_system_exit_inside_provider_scope_clears_correlation(
        self,
    ) -> None:
        """``SystemExit`` is also a ``BaseException`` and MUST be
        cleaned up exactly like ``KeyboardInterrupt``. A subsequent
        direct ``QueryLlm`` call must remain uncorrelated."""
        self.assertIsNone(current_llm_correlation_id())

        class _WorkerExit(SystemExit):
            pass

        install_llm_timing_recorder(
            mock.Mock(), correlation_id="SYN-PROV-EXIT"
        )
        self.assertEqual(
            current_llm_correlation_id(), "SYN-PROV-EXIT"
        )
        with self.assertRaises(SystemExit):
            try:
                raise _WorkerExit("interrupted by systemd")
            finally:
                install_llm_timing_recorder(None)

        self.assertIsNone(current_llm_correlation_id())

        captured, capture_fn = self._capture_emit_events()
        transport = mock.Mock(
            return_value=_FakeResponse(json.dumps({"ok": True}))
        )
        client = QueryLlm(settings=_settings(), transport=transport)
        with mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            client.request("hola")

        lifecycle_events = [
            ev for ev in captured if ev.get("event") == "llm_request"
        ]
        self.assertEqual(len(lifecycle_events), 2)
        self.assertNotIn("correlation_id", lifecycle_events[0])
        self.assertNotIn("correlation_id", lifecycle_events[1])

    def _capture_emit_events(self) -> tuple[list[dict], object]:
        captured: list[dict] = []

        def _capture(*, event: str, **kwargs: object) -> bool:
            from backend.observability.events import build_event

            payload = build_event(event=event, **kwargs)
            captured.append(payload)
            return True

        return captured, _capture


class QueryLlmTransportPhaseTest(unittest.TestCase):
    """The :class:`QueryLlm` boundary MUST emit bounded
    ``llm_request_transport_phase`` observations at the seven
    transport seams so the Railway operator can correlate the
    ``llm_request`` outcome with the local Ollama access log
    timestamp.

    Coverage:

    * successful request emits the seven phases in order
      (``request_started`` -> ``response_headers_received`` ->
      ``first_body_chunk`` -> ``body_completed`` ->
      ``response_received`` -> ``json_extracted`` ->
      ``result_parsed``) and preserves the existing
      ``llm_request`` lifecycle;
    * transport timeout before response receipt emits only
      ``request_started`` (no false ``response_headers_received`` /
      ``first_body_chunk`` / ``body_completed`` / ``json_extracted``
      / ``result_parsed``);
    * HTTP, malformed-response and empty-response behaviour remain
      unchanged: the existing failure ``llm_request`` event is
      emitted and only the phases the boundary actually reached are
      surfaced;
    * ``response_bytes``, ``elapsed_ms`` and ``http_status`` honour
      the closed catalogue bounds;
    * the opaque correlation identifier is preserved across phases;
    * the contract rejects any sensitive free-form field;
    * an emitter failure does NOT change the
      :class:`QueryLlm.request()` result or exception.
    """

    def setUp(self) -> None:
        reset_llm_timing_recorder()

    def tearDown(self) -> None:
        reset_llm_timing_recorder()

    def _capture_emit_events(self) -> tuple[list[dict], object]:
        captured: list[dict] = []

        def _capture(*, event: str, **kwargs: object) -> bool:
            from backend.observability.events import build_event

            payload = build_event(event=event, **kwargs)
            captured.append(payload)
            return True

        return captured, _capture

    def _phases(self, captured: list[dict]) -> list[str]:
        return [
            ev["phase"]
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
        ]

    def test_successful_request_emits_seven_phases_in_order(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        transport = mock.Mock(
            return_value=_FakeResponse(json.dumps({"ok": True}))
        )
        client = QueryLlm(settings=_settings(), transport=transport)
        with mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            result = client.request(
                "hola", correlation_id="SYN-PHASE-OK"
            )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(
            self._phases(captured),
            [
                "request_started",
                "response_headers_received",
                "first_body_chunk",
                "body_completed",
                "response_received",
                "json_extracted",
                "result_parsed",
            ],
        )

        phase_events = [
            ev
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
        ]
        for ev in phase_events:
            self.assertEqual(ev.get("component"), "query_llm")
            self.assertEqual(ev.get("correlation_id"), "SYN-PHASE-OK")
            self.assertNotIn("prompt", ev)
            self.assertNotIn("response", ev)
            self.assertNotIn("url", ev)
            self.assertNotIn("proxy", ev)
            self.assertNotIn("headers", ev)

        lifecycle_events = [
            ev
            for ev in captured
            if ev.get("event") == "llm_request"
        ]
        self.assertEqual(len(lifecycle_events), 2)
        self.assertEqual(lifecycle_events[0]["outcome"], "started")
        self.assertEqual(lifecycle_events[1]["outcome"], "completed")

    def test_historical_response_received_phase_remains_accepted(self) -> None:
        from backend.observability import (
            COMPONENT_LLM,
            EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            build_event,
        )

        payload = build_event(
            event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            component=COMPONENT_LLM,
            phase="response_received",
            elapsed_ms=10,
            http_status=200,
        )
        self.assertEqual(payload["phase"], "response_received")
        self.assertEqual(payload["http_status"], 200)

    def test_response_received_emitted_after_body_completed(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        transport = mock.Mock(
            return_value=_FakeResponse(json.dumps({"ok": True}))
        )
        client = QueryLlm(settings=_settings(), transport=transport)
        with mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            client.request("hola", correlation_id="SYN-PHASE-RR")

        phase_events = [
            ev
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
        ]
        order = [ev["phase"] for ev in phase_events]
        self.assertIn("response_received", order)
        body_completed_idx = order.index("body_completed")
        response_received_idx = order.index("response_received")
        json_extracted_idx = order.index("json_extracted")
        result_parsed_idx = order.index("result_parsed")
        self.assertLess(body_completed_idx, response_received_idx)
        self.assertLess(response_received_idx, json_extracted_idx)
        self.assertLess(json_extracted_idx, result_parsed_idx)

        response_received_event = phase_events[response_received_idx]
        body_completed_event = phase_events[body_completed_idx]
        self.assertEqual(
            response_received_event["response_bytes"],
            body_completed_event["response_bytes"],
        )
        self.assertEqual(
            response_received_event["http_status"],
            body_completed_event["http_status"],
        )
        self.assertEqual(
            response_received_event["correlation_id"], "SYN-PHASE-RR"
        )

    def test_partial_body_does_not_emit_response_received(self) -> None:
        class _PartialBodyStreamingResponse(_FakeStreamingResponse):
            def iter_content(self, chunk_size: int = 8192):
                self.iter_calls += 1
                data = self._envelope.encode("utf-8")
                half = len(data) // 2
                yield data[:half]
                raise requests.exceptions.Timeout("read deadline")

        captured, capture_fn = self._capture_emit_events()
        response = _PartialBodyStreamingResponse(
            json.dumps({"ok": True})
        )
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            with mock.patch(
                "backend.llm.query_llm.emit_event",
                side_effect=capture_fn,
            ):
                with self.assertRaises(QueryLlmTimeoutError):
                    QueryLlm(settings=_settings()).request(
                        "hola", correlation_id="SYN-PHASE-PARTIAL"
                    )

        phases = self._phases(captured)
        self.assertNotIn("response_received", phases)
        self.assertNotIn("body_completed", phases)
        self.assertIn("first_body_chunk", phases)
        self.assertIn("response_headers_received", phases)

    def test_header_only_timeout_does_not_emit_response_received(self) -> None:
        class _HeaderOnlyStreamingResponse(_FakeStreamingResponse):
            def iter_content(self, chunk_size: int = 8192):
                self.iter_calls += 1
                raise requests.exceptions.Timeout("read deadline")

        captured, capture_fn = self._capture_emit_events()
        response = _HeaderOnlyStreamingResponse(
            json.dumps({"ok": True})
        )
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            with mock.patch(
                "backend.llm.query_llm.emit_event",
                side_effect=capture_fn,
            ):
                with self.assertRaises(QueryLlmTimeoutError):
                    QueryLlm(settings=_settings()).request(
                        "hola", correlation_id="SYN-PHASE-HEADONLY"
                    )

        phases = self._phases(captured)
        self.assertNotIn("response_received", phases)
        self.assertNotIn("body_completed", phases)
        self.assertNotIn("first_body_chunk", phases)

    def test_response_headers_received_includes_http_status(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        transport = mock.Mock(
            return_value=_FakeResponse(json.dumps({"ok": True}), status_code=201)
        )
        client = QueryLlm(settings=_settings(), transport=transport)
        with mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            client.request("hola")

        phase_events = [
            ev
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
        ]
        headers_event = next(
            ev
            for ev in phase_events
            if ev["phase"] == "response_headers_received"
        )
        self.assertEqual(headers_event["http_status"], 201)

    def test_json_extracted_and_result_parsed_include_response_bytes(
        self,
    ) -> None:
        captured, capture_fn = self._capture_emit_events()
        body = json.dumps({"intents": ["a", "b"]})
        transport = mock.Mock(return_value=_FakeResponse(body))
        client = QueryLlm(settings=_settings(), transport=transport)
        with mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            client.request("hola")

        phase_events = [
            ev
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
        ]
        json_extracted = next(
            ev for ev in phase_events if ev["phase"] == "json_extracted"
        )
        result_parsed = next(
            ev for ev in phase_events if ev["phase"] == "result_parsed"
        )
        self.assertEqual(
            json_extracted["response_bytes"],
            len(body.encode("utf-8")),
        )
        self.assertEqual(
            result_parsed["response_bytes"],
            len(body.encode("utf-8")),
        )

    def test_elapsed_ms_is_non_negative_and_bounded(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        transport = mock.Mock(
            return_value=_FakeResponse(json.dumps({"ok": True}))
        )
        client = QueryLlm(settings=_settings(), transport=transport)
        with mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            client.request("hola")

        phase_events = [
            ev
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
        ]
        for ev in phase_events:
            self.assertIsInstance(ev["elapsed_ms"], int)
            self.assertGreaterEqual(ev["elapsed_ms"], 0)
        self.assertEqual(phase_events[0]["elapsed_ms"], 0)

    def test_timeout_before_response_emits_only_request_started(
        self,
    ) -> None:
        captured, capture_fn = self._capture_emit_events()

        def transport(url, json=None, timeout=None):
            raise requests.exceptions.Timeout("slow")

        client = QueryLlm(settings=_settings(), transport=transport)
        with mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            with self.assertRaises(QueryLlmTimeoutError):
                client.request("hola", correlation_id="SYN-PHASE-TO")

        self.assertEqual(self._phases(captured), ["request_started"])

        lifecycle_events = [
            ev
            for ev in captured
            if ev.get("event") == "llm_request"
        ]
        self.assertEqual(len(lifecycle_events), 2)
        self.assertEqual(lifecycle_events[0]["outcome"], "started")
        self.assertEqual(lifecycle_events[1]["failure_category"], "timeout")
        self.assertEqual(
            lifecycle_events[1]["correlation_id"], "SYN-PHASE-TO"
        )

    def test_http_error_stops_after_response_headers_received(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        transport = mock.Mock(
            return_value=_FakeResponse("boom", status_code=503)
        )
        client = QueryLlm(settings=_settings(), transport=transport)
        with mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            with self.assertRaises(QueryLlmHttpError):
                client.request("hola", correlation_id="SYN-PHASE-HTTP")

        self.assertEqual(
            self._phases(captured),
            ["request_started", "response_headers_received"],
        )

        lifecycle_events = [
            ev
            for ev in captured
            if ev.get("event") == "llm_request"
        ]
        self.assertEqual(len(lifecycle_events), 2)
        self.assertEqual(
            lifecycle_events[1]["failure_category"], "http_error"
        )
        self.assertEqual(lifecycle_events[1]["http_status"], 503)

    def test_empty_response_stops_after_json_extracted(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        transport = mock.Mock(return_value=_FakeResponse(""))
        client = QueryLlm(settings=_settings(), transport=transport)
        with mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            with self.assertRaises(QueryLlmResponseError):
                client.request("hola", correlation_id="SYN-PHASE-EMPTY")

        self.assertEqual(
            self._phases(captured),
            [
                "request_started",
                "response_headers_received",
                "body_completed",
                "response_received",
                "json_extracted",
            ],
        )

        lifecycle_events = [
            ev
            for ev in captured
            if ev.get("event") == "llm_request"
        ]
        self.assertEqual(
            lifecycle_events[1]["failure_category"], "response_error"
        )

    def test_malformed_json_stops_after_json_extracted(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        transport = mock.Mock(return_value=_FakeResponse("not-json"))
        client = QueryLlm(settings=_settings(), transport=transport)
        with mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            with self.assertRaises(QueryLlmResponseError):
                client.request("hola")

        self.assertEqual(
            self._phases(captured),
            [
                "request_started",
                "response_headers_received",
                "first_body_chunk",
                "body_completed",
                "response_received",
                "json_extracted",
            ],
        )

    def test_correlation_id_preserved_across_phases(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        transport = mock.Mock(
            return_value=_FakeResponse(json.dumps({"ok": True}))
        )
        client = QueryLlm(settings=_settings(), transport=transport)
        install_llm_timing_recorder(
            mock.Mock(), correlation_id="SYN-PROV-PHASE"
        )
        try:
            with mock.patch(
                "backend.llm.query_llm.emit_event",
                side_effect=capture_fn,
            ):
                client.request("hola")
        finally:
            reset_llm_timing_recorder()

        phase_events = [
            ev
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
        ]
        for ev in phase_events:
            self.assertEqual(ev["correlation_id"], "SYN-PROV-PHASE")

    def test_correlation_id_truncated_across_phases(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        transport = mock.Mock(
            return_value=_FakeResponse(json.dumps({"ok": True}))
        )
        client = QueryLlm(settings=_settings(), transport=transport)
        install_llm_timing_recorder(
            mock.Mock(), correlation_id="x" * 200
        )
        try:
            with mock.patch(
                "backend.llm.query_llm.emit_event",
                side_effect=capture_fn,
            ):
                client.request("hola")
        finally:
            reset_llm_timing_recorder()

        phase_events = [
            ev
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
        ]
        for ev in phase_events:
            self.assertEqual(len(ev["correlation_id"]), 64)

    def test_response_bytes_matches_utf8_body_length(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        body = "   \n  "
        transport = mock.Mock(return_value=_FakeResponse(body))
        client = QueryLlm(settings=_settings(), transport=transport)
        with mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            with self.assertRaises(QueryLlmResponseError):
                client.request("hola")

        json_extracted = next(
            ev
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
            and ev["phase"] == "json_extracted"
        )
        self.assertEqual(
            json_extracted["response_bytes"],
            len(body.encode("utf-8")),
        )

    def test_no_sensitive_field_in_any_phase_event(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        body = json.dumps({"intents": ["x"]})
        transport = mock.Mock(return_value=_FakeResponse(body))
        client = QueryLlm(settings=_settings(), transport=transport)
        with mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            client.request("super-secret-prompt")

        phase_events = [
            ev
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
        ]
        for ev in phase_events:
            serialized = json.dumps(ev, sort_keys=True)
            self.assertNotIn("super-secret-prompt", serialized)
            self.assertNotIn("intents", serialized)
            self.assertNotIn("super-secret-url", serialized)
            self.assertNotIn("super-secret-proxy", serialized)
            self.assertNotIn("socks5h", serialized)
            self.assertNotIn("127.0.0.1", serialized)
            self.assertNotIn("user:pass", serialized)
            self.assertNotIn("Bearer", serialized)
            self.assertNotIn("X-Secret", serialized)
            self.assertNotIn("X-Twilio-Signature", serialized)
            self.assertNotIn("AC000000000000000000000000000000", serialized)
            self.assertNotIn("+5491100000000", serialized)
            self.assertNotIn("SM-ABC-XYZ", serialized)
            self.assertNotIn("Exception message", serialized)
            self.assertNotIn("Traceback", serialized)

    def test_phase_field_rejects_sensitive_payload_via_validator(
        self,
    ) -> None:
        from backend.observability import (
            COMPONENT_LLM,
            EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            build_event,
            emit_event,
        )

        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            component=COMPONENT_LLM,
            phase="request_started",
            correlation_id="SYN-PHASE-VAL",
            stream=sink,
        )
        self.assertTrue(ok)
        line = sink.getvalue()
        self.assertNotIn("super-secret-prompt", line)
        self.assertNotIn("user:pass", line)
        self.assertNotIn("Bearer", line)

        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
                phase="request_started",
                correlation_id="x" * 200,
            )

    def test_emission_failure_does_not_break_query_llm(self) -> None:
        def _explode_transport_phase_only(**kwargs):
            if kwargs.get("event") == "llm_request_transport_phase":
                raise RuntimeError("phase emitter boom")
            return True

        transport = mock.Mock(
            return_value=_FakeResponse(json.dumps({"ok": True}))
        )
        client = QueryLlm(settings=_settings(), transport=transport)
        with mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=_explode_transport_phase_only,
        ):
            result = client.request("hola", correlation_id="SYN-PHASE-EX")

        self.assertEqual(result, {"ok": True})

    def test_emission_failure_does_not_swallow_timeout_exception(self) -> None:
        def _explode_transport_phase_only(**kwargs):
            if kwargs.get("event") == "llm_request_transport_phase":
                raise RuntimeError("phase emitter boom")
            return True

        def transport(url, json=None, timeout=None):
            raise requests.exceptions.Timeout("slow")

        client = QueryLlm(settings=_settings(), transport=transport)
        with mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=_explode_transport_phase_only,
        ):
            with self.assertRaises(QueryLlmTimeoutError):
                client.request("hola")

    def test_emission_failure_does_not_swallow_http_exception(self) -> None:
        def _explode_transport_phase_only(**kwargs):
            if kwargs.get("event") == "llm_request_transport_phase":
                raise RuntimeError("phase emitter boom")
            return True

        transport = mock.Mock(
            return_value=_FakeResponse("boom", status_code=502)
        )
        client = QueryLlm(settings=_settings(), transport=transport)
        with mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=_explode_transport_phase_only,
        ):
            with self.assertRaises(QueryLlmHttpError) as ctx:
                client.request("hola")
            self.assertEqual(ctx.exception.status_code, 502)

    def test_request_started_emitted_with_zero_elapsed(self) -> None:
        captured, capture_fn = self._capture_emit_events()

        def transport(url, json=None, timeout=None):
            raise requests.exceptions.Timeout("slow")

        client = QueryLlm(settings=_settings(), transport=transport)
        with mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            with self.assertRaises(QueryLlmTimeoutError):
                client.request("hola")

        request_started = next(
            ev
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
            and ev["phase"] == "request_started"
        )
        self.assertEqual(request_started["elapsed_ms"], 0)
        self.assertNotIn("http_status", request_started)
        self.assertNotIn("response_bytes", request_started)


class QueryLlmStreamingResponseTest(unittest.TestCase):
    """``QueryLlm.request`` MUST observe the real HTTP body receipt
    boundary through ``requests.post(..., stream=True)`` while
    keeping the Ollama payload ``stream: false`` unchanged.

    Coverage:

    * ``requests.post`` is called with ``stream=True`` and the
      payload keeps ``stream: false``;
    * the streaming fake response emits
      ``response_headers_received`` -> ``first_body_chunk`` ->
      ``body_completed`` -> ``json_extracted`` -> ``result_parsed``
      in order;
    * ``first_body_chunk`` and ``body_completed`` carry a bounded
      ``chunk_count`` and ``response_bytes`` while the rest of the
      phase events stay free of headers / URLs / proxies / prompt /
      response fragments;
    * a read timeout during body iteration never fabricates
      ``body_completed``;
    * a partial body (one chunk then read timeout) keeps
      ``first_body_chunk`` and never emits ``body_completed``;
    * the response is closed on success and on every error path
      (read timeout, HTTP error, parse failure);
    * complete body reconstructs the exact same parsed result the
      previous non-streaming path produced;
    * existing non-streaming ``_FakeResponse`` stubs still pass
      through the eager adapter seam without producing a second
      business path.
    """

    def setUp(self) -> None:
        reset_llm_timing_recorder()

    def tearDown(self) -> None:
        reset_llm_timing_recorder()

    def _capture_emit_events(self) -> tuple[list[dict], object]:
        captured: list[dict] = []

        def _capture(*, event: str, **kwargs: object) -> bool:
            from backend.observability.events import build_event

            payload = build_event(event=event, **kwargs)
            captured.append(payload)
            return True

        return captured, _capture

    def _phases(self, captured: list[dict]) -> list[str]:
        return [
            ev["phase"]
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
        ]

    def _phase(self, captured: list[dict], name: str) -> dict:
        return next(
            ev
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
            and ev["phase"] == name
        )

    def test_requests_post_uses_stream_true_and_keeps_payload_stream_false(
        self,
    ) -> None:
        response = _FakeStreamingResponse(json.dumps({"ok": True}))
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ) as post:
            QueryLlm(settings=_settings()).request("hola")

        self.assertTrue(post.call_args.kwargs.get("stream"))
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["stream"], False)

    def test_streaming_response_emits_seven_phases_with_chunk_count(
        self,
    ) -> None:
        captured, capture_fn = self._capture_emit_events()
        response = _FakeStreamingResponse(
            json.dumps({"ok": True}), chunk_size=4
        )
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            with mock.patch(
                "backend.llm.query_llm.emit_event",
                side_effect=capture_fn,
            ):
                result = QueryLlm(settings=_settings()).request(
                    "hola", correlation_id="SYN-STREAM-OK"
                )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(
            self._phases(captured),
            [
                "request_started",
                "response_headers_received",
                "first_body_chunk",
                "body_completed",
                "response_received",
                "json_extracted",
                "result_parsed",
            ],
        )

        first_chunk = self._phase(captured, "first_body_chunk")
        body_completed = self._phase(captured, "body_completed")
        self.assertEqual(first_chunk["chunk_count"], 1)
        self.assertIsInstance(first_chunk["chunk_count"], int)
        self.assertGreaterEqual(first_chunk["chunk_count"], 0)
        self.assertIsInstance(body_completed["chunk_count"], int)
        self.assertGreaterEqual(body_completed["chunk_count"], first_chunk["chunk_count"])
        self.assertEqual(body_completed["response_bytes"], len(response.text.encode("utf-8")))
        self.assertEqual(body_completed["http_status"], 200)

        for ev in (
            first_chunk,
            body_completed,
            self._phase(captured, "response_headers_received"),
        ):
            self.assertEqual(ev["correlation_id"], "SYN-STREAM-OK")
            self.assertNotIn("prompt", ev)
            self.assertNotIn("response", ev)
            self.assertNotIn("url", ev)
            self.assertNotIn("proxy", ev)
            self.assertNotIn("headers", ev)

    def test_streaming_response_chunk_count_matches_received_chunks(
        self,
    ) -> None:
        captured, capture_fn = self._capture_emit_events()
        response = _FakeStreamingResponse(
            json.dumps({"intents": ["a", "b"]}),
            chunk_size=4,
        )
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            with mock.patch(
                "backend.llm.query_llm.emit_event",
                side_effect=capture_fn,
            ):
                QueryLlm(settings=_settings()).request("hola")

        body_completed = self._phase(captured, "body_completed")
        expected_chunks = (len(response.text.encode("utf-8")) + 3) // 4
        self.assertEqual(body_completed["chunk_count"], expected_chunks)
        self.assertGreater(body_completed["chunk_count"], 1)

    def test_streaming_response_closed_on_success(self) -> None:
        response = _FakeStreamingResponse(json.dumps({"ok": True}))
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            QueryLlm(settings=_settings()).request("hola")
        self.assertTrue(response.closed)

    def test_streaming_response_closed_on_http_error(self) -> None:
        response = _FakeStreamingResponse(
            json.dumps({"ok": True}), status_code=502
        )
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            with self.assertRaises(QueryLlmHttpError):
                QueryLlm(settings=_settings()).request("hola")
        self.assertTrue(response.closed)

    def test_streaming_response_closed_on_read_timeout(self) -> None:
        class _TimeoutStreamingResponse(_FakeStreamingResponse):
            def iter_content(self, chunk_size: int = 8192):
                self.iter_calls += 1
                yield b'{"response":'
                raise requests.exceptions.Timeout("read deadline")

        response = _TimeoutStreamingResponse(
            json.dumps({"ok": True}), chunk_size=8
        )
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            with self.assertRaises(QueryLlmTimeoutError):
                QueryLlm(settings=_settings()).request("hola")
        self.assertTrue(response.closed)

    def test_streaming_read_timeout_does_not_fabricate_body_completed(
        self,
    ) -> None:
        class _ImmediateTimeoutStreamingResponse(_FakeStreamingResponse):
            def iter_content(self, chunk_size: int = 8192):
                self.iter_calls += 1
                raise requests.exceptions.Timeout("read deadline")

        captured, capture_fn = self._capture_emit_events()
        response = _ImmediateTimeoutStreamingResponse(
            json.dumps({"ok": True})
        )
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            with mock.patch(
                "backend.llm.query_llm.emit_event",
                side_effect=capture_fn,
            ):
                with self.assertRaises(QueryLlmTimeoutError):
                    QueryLlm(settings=_settings()).request(
                        "hola", correlation_id="SYN-STREAM-HEAD"
                    )

        self.assertEqual(
            self._phases(captured),
            [
                "request_started",
                "response_headers_received",
            ],
        )

    def test_streaming_partial_body_keeps_first_chunk_no_completed(
        self,
    ) -> None:
        class _PartialBodyStreamingResponse(_FakeStreamingResponse):
            def iter_content(self, chunk_size: int = 8192):
                self.iter_calls += 1
                data = self._envelope.encode("utf-8")
                half = len(data) // 2
                yield data[:half]
                raise requests.exceptions.Timeout("read deadline")

        captured, capture_fn = self._capture_emit_events()
        response = _PartialBodyStreamingResponse(
            json.dumps({"ok": True})
        )
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            with mock.patch(
                "backend.llm.query_llm.emit_event",
                side_effect=capture_fn,
            ):
                with self.assertRaises(QueryLlmTimeoutError):
                    QueryLlm(settings=_settings()).request("hola")

        self.assertEqual(
            self._phases(captured),
            [
                "request_started",
                "response_headers_received",
                "first_body_chunk",
            ],
        )
        first_chunk = self._phase(captured, "first_body_chunk")
        self.assertEqual(first_chunk["chunk_count"], 1)

    def test_streaming_complete_body_matches_previous_parsed_result(
        self,
    ) -> None:
        inner_body = json.dumps(
            {"intents": [{"name": "agregar_producto", "qty": 1}]}
        )
        streaming_response = _FakeStreamingResponse(inner_body, chunk_size=4)
        eager_response = _FakeResponse(inner_body)

        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=streaming_response
        ):
            streaming_result = QueryLlm(settings=_settings()).request("hola")

        transport = mock.Mock(return_value=eager_response)
        eager_result = QueryLlm(settings=_settings(), transport=transport).request(
            "hola"
        )

        self.assertEqual(streaming_result, eager_result)

    def test_streaming_empty_body_raises_response_error_and_completes_body_phase(
        self,
    ) -> None:
        class _EmptyStreamingResponse(_FakeStreamingResponse):
            def __init__(self) -> None:
                super().__init__("", chunk_size=4)
                self._envelope = ""

        captured, capture_fn = self._capture_emit_events()
        response = _EmptyStreamingResponse()
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            with mock.patch(
                "backend.llm.query_llm.emit_event",
                side_effect=capture_fn,
            ):
                with self.assertRaises(QueryLlmResponseError):
                    QueryLlm(settings=_settings()).request("hola")

        self.assertEqual(
            self._phases(captured),
            [
                "request_started",
                "response_headers_received",
                "body_completed",
                "response_received",
                "json_extracted",
            ],
        )
        body_completed = self._phase(captured, "body_completed")
        self.assertEqual(body_completed["chunk_count"], 0)
        self.assertEqual(body_completed["response_bytes"], 0)
        self.assertTrue(response.closed)

    def test_chunk_count_validator_rejects_negative(self) -> None:
        from backend.observability.events import build_event
        with self.assertRaises(EventValidationError):
            build_event(
                event="llm_request_transport_phase",
                component="query_llm",
                phase="first_body_chunk",
                chunk_count=-1,
            )

    def test_chunk_count_validator_rejects_oversized(self) -> None:
        from backend.observability.events import build_event
        with self.assertRaises(EventValidationError):
            build_event(
                event="llm_request_transport_phase",
                component="query_llm",
                phase="body_completed",
                chunk_count=10**9,
            )

    def test_chunk_count_validator_rejects_non_integer(self) -> None:
        from backend.observability.events import build_event
        with self.assertRaises(EventValidationError):
            build_event(
                event="llm_request_transport_phase",
                component="query_llm",
                phase="first_body_chunk",
                chunk_count="1",
            )

    def test_phase_emitter_failure_does_not_swallow_streaming_read_timeout(
        self,
    ) -> None:
        class _BoomStreamingResponse(_FakeStreamingResponse):
            def iter_content(self, chunk_size: int = 8192):
                self.iter_calls += 1
                raise requests.exceptions.Timeout("read deadline")

        def _boom_transport_phase_only(**kwargs):
            if kwargs.get("event") == "llm_request_transport_phase":
                raise RuntimeError("phase emitter boom")
            return True

        response = _BoomStreamingResponse(json.dumps({"ok": True}))
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            with mock.patch(
                "backend.llm.query_llm.emit_event",
                side_effect=_boom_transport_phase_only,
            ):
                with self.assertRaises(QueryLlmTimeoutError):
                    QueryLlm(settings=_settings()).request("hola")
        self.assertTrue(response.closed)


class QueryLlmNonDictEnvelopeRegressionTest(unittest.TestCase):
    """The streaming branch must preserve the previous
    ``response.json()`` semantics: a JSON-decodable envelope that
    is NOT an object (``[]``, ``null``, number, string) must
    surface as an empty body that ``_parse`` rejects with
    ``QueryLlmResponseError``. A non-JSON envelope must still
    fall back to the raw envelope text so ``_parse`` can recover
    the first balanced JSON object.

    Both the streaming (``iter_content``) and eager adapter
    (``response.json()``) seams must honour the same contract.
    """

    def setUp(self) -> None:
        reset_llm_timing_recorder()

    def tearDown(self) -> None:
        reset_llm_timing_recorder()

    def _streaming_response_with_envelope(
        self, envelope_text: str
    ) -> _FakeStreamingResponse:
        """Build a streaming response whose ``iter_content``
        yields exactly ``envelope_text`` (not wrapped in the
        Ollama ``{"response": ...}`` envelope)."""

        class _RawEnvelopeStreamingResponse(_FakeStreamingResponse):
            def __init__(self) -> None:
                super().__init__("", chunk_size=4)
                self._envelope = envelope_text

        return _RawEnvelopeStreamingResponse()

    def test_streaming_empty_array_envelope_is_rejected(
        self,
    ) -> None:
        response = self._streaming_response_with_envelope("[]")
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            with self.assertRaises(QueryLlmResponseError):
                QueryLlm(settings=_settings()).request("hola")
        self.assertTrue(response.closed)

    def test_streaming_null_envelope_is_rejected(self) -> None:
        response = self._streaming_response_with_envelope("null")
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            with self.assertRaises(QueryLlmResponseError):
                QueryLlm(settings=_settings()).request("hola")
        self.assertTrue(response.closed)

    def test_streaming_number_envelope_is_rejected(self) -> None:
        response = self._streaming_response_with_envelope("42")
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            with self.assertRaises(QueryLlmResponseError):
                QueryLlm(settings=_settings()).request("hola")
        self.assertTrue(response.closed)

    def test_streaming_string_envelope_is_rejected(self) -> None:
        response = self._streaming_response_with_envelope('"hello"')
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            with self.assertRaises(QueryLlmResponseError):
                QueryLlm(settings=_settings()).request("hola")
        self.assertTrue(response.closed)

    def test_eager_empty_array_envelope_is_rejected(self) -> None:
        class _RawJsonArrayResponse(_FakeResponse):
            def json(self):
                return []

        response = _RawJsonArrayResponse("[]")
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            with self.assertRaises(QueryLlmResponseError):
                QueryLlm(settings=_settings()).request("hola")
        self.assertTrue(response.closed)

    def test_eager_null_envelope_is_rejected(self) -> None:
        class _RawJsonNullResponse(_FakeResponse):
            def json(self):
                return None

        response = _RawJsonNullResponse("null")
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            with self.assertRaises(QueryLlmResponseError):
                QueryLlm(settings=_settings()).request("hola")
        self.assertTrue(response.closed)

    def test_streaming_non_json_envelope_falls_back_to_parse(
        self,
    ) -> None:
        response = self._streaming_response_with_envelope(
            'prelude {"intents": []} postlude'
        )
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            result = QueryLlm(settings=_settings()).request("hola")
        self.assertEqual(result, {"intents": []})
        self.assertTrue(response.closed)


class QueryLlmStreamingExceptionMappingTest(unittest.TestCase):
    """The streaming ``iter_content`` reading must classify the
    same Requests failure modes as the initial ``requests.post``
    call: ``Timeout`` → ``QueryLlmTimeoutError`` and
    ``ConnectionError`` → ``QueryLlmConnectionError``.

    Coverage:

    * ``requests.exceptions.Timeout`` raised mid-iteration keeps
      ``QueryLlmTimeoutError`` (does not fall through to the
      generic ``QueryLlmError``).
    * ``requests.exceptions.ConnectionError`` raised mid-iteration
      keeps ``QueryLlmConnectionError`` (does not fall through to
      the generic ``QueryLlmError``).
    * ``requests.exceptions.ChunkedEncodingError`` (a
      ``ConnectionError`` subclass Requests sometimes uses for a
      read-timeout during streaming) classifies as
      ``QueryLlmConnectionError`` so the contract stays
      consistent with the previous non-streaming seam.
    * The response is closed in every error path; no retry or
      second request is performed.
    """

    def setUp(self) -> None:
        reset_llm_timing_recorder()

    def tearDown(self) -> None:
        reset_llm_timing_recorder()

    def _capture_emit_events(self) -> tuple[list[dict], object]:
        captured: list[dict] = []

        def _capture(*, event: str, **kwargs: object) -> bool:
            from backend.observability.events import build_event

            payload = build_event(event=event, **kwargs)
            captured.append(payload)
            return True

        return captured, _capture

    def _phases(self, captured: list[dict]) -> list[str]:
        return [
            ev["phase"]
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
        ]

    def test_streaming_timeout_preserves_query_llm_timeout_error(
        self,
    ) -> None:
        class _StreamingTimeoutResponse(_FakeStreamingResponse):
            def iter_content(self, chunk_size: int = 8192):
                self.iter_calls += 1
                yield b'{"response":'
                raise requests.exceptions.Timeout("read deadline")

        response = _StreamingTimeoutResponse(json.dumps({"ok": True}))
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            with self.assertRaises(QueryLlmTimeoutError):
                QueryLlm(settings=_settings()).request("hola")
        self.assertTrue(response.closed)

    def test_streaming_connection_error_preserves_query_llm_connection_error(
        self,
    ) -> None:
        class _StreamingConnectionErrorResponse(_FakeStreamingResponse):
            def iter_content(self, chunk_size: int = 8192):
                self.iter_calls += 1
                yield b'{"response":'
                raise requests.exceptions.ConnectionError(
                    "stream connection lost"
                )

        captured, capture_fn = self._capture_emit_events()
        response = _StreamingConnectionErrorResponse(
            json.dumps({"ok": True})
        )
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            with mock.patch(
                "backend.llm.query_llm.emit_event",
                side_effect=capture_fn,
            ):
                with self.assertRaises(QueryLlmConnectionError):
                    QueryLlm(settings=_settings()).request(
                        "hola", correlation_id="SYN-STREAM-CE"
                    )

        self.assertEqual(
            self._phases(captured),
            [
                "request_started",
                "response_headers_received",
                "first_body_chunk",
            ],
        )
        self.assertTrue(response.closed)

    def test_streaming_chunked_encoding_error_classifies_as_connection_error(
        self,
    ) -> None:
        class _StreamingChunkedEncodingResponse(_FakeStreamingResponse):
            def iter_content(self, chunk_size: int = 8192):
                self.iter_calls += 1
                yield b'{"response":'
                raise requests.exceptions.ChunkedEncodingError(
                    "stream cut mid-response"
                )

        response = _StreamingChunkedEncodingResponse(
            json.dumps({"ok": True})
        )
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            with self.assertRaises(QueryLlmConnectionError):
                QueryLlm(settings=_settings()).request("hola")
        self.assertTrue(response.closed)

    def test_streaming_read_timeout_subclass_preserves_timeout_error(
        self,
    ) -> None:
        class _StreamingReadTimeoutResponse(_FakeStreamingResponse):
            def iter_content(self, chunk_size: int = 8192):
                self.iter_calls += 1
                raise requests.exceptions.ReadTimeout("read deadline")

        response = _StreamingReadTimeoutResponse(
            json.dumps({"ok": True})
        )
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            with self.assertRaises(QueryLlmTimeoutError):
                QueryLlm(settings=_settings()).request("hola")
        self.assertTrue(response.closed)

    def test_streaming_unexpected_exception_still_wraps_into_query_llm_error(
        self,
    ) -> None:
        class _StreamingRuntimeErrorResponse(_FakeStreamingResponse):
            def iter_content(self, chunk_size: int = 8192):
                self.iter_calls += 1
                raise RuntimeError("non-requests exception")

        response = _StreamingRuntimeErrorResponse(
            json.dumps({"ok": True})
        )
        with mock.patch(
            "backend.llm.query_llm.requests.post", return_value=response
        ):
            with self.assertRaises(QueryLlmError) as ctx:
                QueryLlm(settings=_settings()).request("hola")
        self.assertNotIsInstance(ctx.exception, QueryLlmTimeoutError)
        self.assertNotIsInstance(ctx.exception, QueryLlmConnectionError)
        self.assertTrue(response.closed)


class QueryLlmHttpxTransportTest(unittest.TestCase):
    """Closed HTTPX experiment for the QueryLlm boundary.

    The transport is opt-in via ``LLM_HTTP_CLIENT=httpx``; the
    Requests path remains the production default. The test suite
    exercises the HTTPX branch without any real network: every
    :class:`httpx.Client` instance is replaced with a recording
    fake that captures the URL, payload, timeout, proxy and body
    iterator, mirrors a synthetic :class:`httpx.Response`-shaped
    object, and asserts the equivalence contract:

    * the existing :class:`QueryLlm` injected-test seam keeps
      winning over the configuration selector so legacy tests stay
      green;
    * the HTTPX path forwards the URL, payload, total timeout and
      optional ``OLLAMA_PROXY_URL`` verbatim;
    * a successful turn emits the seven closed transport phases
      in the same order and closes the response;
    * timeout, connection / proxy and stream errors map to the
      existing :class:`QueryLlmTimeoutError` /
      :class:`QueryLlmConnectionError` categories without invoking
      :mod:`requests` as a fallback;
    * HTTP status errors keep the existing :class:`QueryLlmHttpError`
      contract;
    * the closed ``socks5://`` and ``socks5h://`` schemes are both
      accepted by the proxy argument without downgrading to direct
      traffic;
    * the privacy contract remains intact — no URL, proxy,
      credential or prompt text is logged or surfaced through the
      phase events.
    """

    def setUp(self) -> None:
        reset_llm_timing_recorder()

    def tearDown(self) -> None:
        reset_llm_timing_recorder()

    def _capture_emit_events(self) -> tuple[list[dict], object]:
        captured: list[dict] = []

        def _capture(*, event: str, **kwargs: object) -> bool:
            from backend.observability.events import build_event

            payload = build_event(event=event, **kwargs)
            captured.append(payload)
            return True

        return captured, _capture

    def _phases(self, captured: list[dict]) -> list[str]:
        return [
            ev["phase"]
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
        ]

    def _phase(self, captured: list[dict], name: str) -> dict:
        return next(
            ev
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
            and ev["phase"] == name
        )

    def test_default_settings_select_requests_transport(self) -> None:
        settings = _settings()
        self.assertEqual(settings.llm_http_client, "requests")

    def test_injected_transport_wins_over_httpx_selector(self) -> None:
        transport = mock.Mock(
            return_value=_FakeResponse(json.dumps({"ok": True}))
        )
        settings = _settings(llm_http_client="httpx")
        with mock.patch(
            "backend.llm.query_llm.httpx.Client"
        ) as fake_client:
            QueryLlm(settings=settings, transport=transport).request("hola")
        fake_client.assert_not_called()

    def test_httpx_selector_invokes_httpx_client_with_proxy_url(
        self,
    ) -> None:
        captured_client_kwargs: dict = {}
        captured_send_kwargs: dict = {}
        captured_request: dict = {}

        class _RecordingClient:
            def __init__(self, *args, **kwargs):
                captured_client_kwargs.update(kwargs)

            def build_request(self, method, url, json=None, **kw):
                captured_request["method"] = method
                captured_request["url"] = url
                captured_request["json"] = json
                return mock.Mock(name="built-request")

            def send(self, request, stream=False):
                captured_send_kwargs["stream"] = stream
                return _FakeHttpxStreamingResponse(
                    json.dumps({"ok": True})
                )

            def close(self):
                pass

        with mock.patch(
            "backend.llm.query_llm.httpx.Client",
            side_effect=_RecordingClient,
        ):
            QueryLlm(
                settings=_settings(
                    llm_http_client="httpx",
                    ollama_proxy_url="socks5h://127.0.0.1:1055",
                ),
            ).request("hola")

        self.assertEqual(
            captured_client_kwargs.get("proxy"),
            "socks5h://127.0.0.1:1055",
        )
        self.assertEqual(captured_client_kwargs.get("timeout"), 30)
        self.assertEqual(captured_request["url"], "http://llm.test/api/generate")
        self.assertEqual(captured_request["method"], "POST")
        payload = captured_request["json"]
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["prompt"], "hola")
        self.assertEqual(payload["stream"], False)
        self.assertEqual(payload["think"], False)
        self.assertEqual(payload["format"], "json")
        self.assertEqual(payload["options"]["temperature"], 0)
        self.assertEqual(payload["options"]["num_predict"], 256)
        self.assertEqual(payload["options"]["num_ctx"], 2048)
        self.assertTrue(captured_send_kwargs["stream"])

    def test_httpx_selector_without_proxy_omits_proxy_kwarg(self) -> None:
        captured_client_kwargs: dict = {}

        class _RecordingClient:
            def __init__(self, *args, **kwargs):
                captured_client_kwargs.update(kwargs)

            def build_request(self, method, url, json=None, **kw):
                return mock.Mock(name="built-request")

            def send(self, request, stream=False):
                return _FakeHttpxStreamingResponse(
                    json.dumps({"ok": True})
                )

            def close(self):
                pass

        with mock.patch(
            "backend.llm.query_llm.httpx.Client",
            side_effect=_RecordingClient,
        ):
            QueryLlm(
                settings=_settings(llm_http_client="httpx"),
            ).request("hola")

        self.assertNotIn("proxy", captured_client_kwargs)
        self.assertEqual(captured_client_kwargs.get("timeout"), 30)

    def test_httpx_success_emits_seven_phases_and_closes(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        response = _FakeHttpxStreamingResponse(
            json.dumps({"intents": ["a", "b"]}), chunk_size=4
        )
        with mock.patch(
            "backend.llm.query_llm.httpx.Client"
        ) as client_factory:
            client_instance = mock.Mock()
            client_instance.build_request.return_value = mock.Mock()
            client_instance.send.return_value = response
            client_factory.return_value = client_instance
            with mock.patch(
                "backend.llm.query_llm.emit_event",
                side_effect=capture_fn,
            ):
                result = QueryLlm(
                    settings=_settings(llm_http_client="httpx"),
                ).request("hola", correlation_id="SYN-HTTPX-OK")

        self.assertEqual(result, {"intents": ["a", "b"]})
        self.assertEqual(
            self._phases(captured),
            [
                "request_started",
                "response_headers_received",
                "first_body_chunk",
                "body_completed",
                "response_received",
                "json_extracted",
                "result_parsed",
            ],
        )
        self.assertTrue(response.closed)
        for ev in (
            self._phase(captured, "response_headers_received"),
            self._phase(captured, "first_body_chunk"),
            self._phase(captured, "body_completed"),
        ):
            self.assertEqual(ev["correlation_id"], "SYN-HTTPX-OK")

    def test_httpx_success_matches_requests_parsed_result(self) -> None:
        inner_body = json.dumps({"intents": [{"name": "agregar"}]})

        class _StreamingHttpxClient:
            def __init__(self, *args, **kwargs):
                pass

            def build_request(self, method, url, json=None, **kw):
                return mock.Mock()

            def send(self, request, stream=False):
                return _FakeHttpxStreamingResponse(
                    inner_body, chunk_size=4
                )

            def close(self):
                pass

        with mock.patch(
            "backend.llm.query_llm.httpx.Client",
            side_effect=_StreamingHttpxClient,
        ):
            httpx_result = QueryLlm(
                settings=_settings(llm_http_client="httpx"),
            ).request("hola")

        requests_result = QueryLlm(
            settings=_settings(llm_http_client="requests"),
            transport=mock.Mock(
                return_value=_FakeResponse(inner_body)
            ),
        ).request("hola")

        self.assertEqual(httpx_result, requests_result)

    def test_httpx_request_does_not_call_requests_post(self) -> None:
        class _StreamingHttpxClient:
            def __init__(self, *args, **kwargs):
                pass

            def build_request(self, method, url, json=None, **kw):
                return mock.Mock()

            def send(self, request, stream=False):
                return _FakeHttpxStreamingResponse(
                    json.dumps({"ok": True})
                )

            def close(self):
                pass

        with mock.patch(
            "backend.llm.query_llm.httpx.Client",
            side_effect=_StreamingHttpxClient,
        ):
            with mock.patch(
                "backend.llm.query_llm.requests.post"
            ) as requests_post:
                QueryLlm(
                    settings=_settings(llm_http_client="httpx"),
                ).request("hola")
        requests_post.assert_not_called()

    def test_httpx_initial_timeout_maps_to_query_llm_timeout_error(
        self,
    ) -> None:
        class _TimeoutHttpxClient:
            def __init__(self, *args, **kwargs):
                pass

            def build_request(self, method, url, json=None, **kw):
                raise httpx.ConnectTimeout("connect timeout")

            def send(self, request, stream=False):
                return mock.Mock()

            def close(self):
                pass

        with mock.patch(
            "backend.llm.query_llm.httpx.Client",
            side_effect=_TimeoutHttpxClient,
        ):
            with mock.patch(
                "backend.llm.query_llm.requests.post"
            ) as requests_post:
                with self.assertRaises(QueryLlmTimeoutError):
                    QueryLlm(
                        settings=_settings(llm_http_client="httpx"),
                    ).request("hola")
        requests_post.assert_not_called()

    def test_httpx_initial_read_timeout_maps_to_query_llm_timeout_error(
        self,
    ) -> None:
        class _ReadTimeoutHttpxClient:
            def __init__(self, *args, **kwargs):
                pass

            def build_request(self, method, url, json=None, **kw):
                return mock.Mock()

            def send(self, request, stream=False):
                raise httpx.ReadTimeout("read deadline")

            def close(self):
                pass

        with mock.patch(
            "backend.llm.query_llm.httpx.Client",
            side_effect=_ReadTimeoutHttpxClient,
        ):
            with mock.patch(
                "backend.llm.query_llm.requests.post"
            ) as requests_post:
                with self.assertRaises(QueryLlmTimeoutError):
                    QueryLlm(
                        settings=_settings(llm_http_client="httpx"),
                    ).request("hola")
        requests_post.assert_not_called()

    def test_httpx_connect_error_maps_to_query_llm_connection_error(
        self,
    ) -> None:
        class _ConnectErrorHttpxClient:
            def __init__(self, *args, **kwargs):
                pass

            def build_request(self, method, url, json=None, **kw):
                raise httpx.ConnectError("connection refused")

            def send(self, request, stream=False):
                return mock.Mock()

            def close(self):
                pass

        with mock.patch(
            "backend.llm.query_llm.httpx.Client",
            side_effect=_ConnectErrorHttpxClient,
        ):
            with mock.patch(
                "backend.llm.query_llm.requests.post"
            ) as requests_post:
                with self.assertRaises(QueryLlmConnectionError):
                    QueryLlm(
                        settings=_settings(llm_http_client="httpx"),
                    ).request("hola")
        requests_post.assert_not_called()

    def test_httpx_proxy_error_maps_to_query_llm_connection_error(
        self,
    ) -> None:
        class _ProxyErrorHttpxClient:
            def __init__(self, *args, **kwargs):
                pass

            def build_request(self, method, url, json=None, **kw):
                raise httpx.ProxyError("proxy refused connection")

            def send(self, request, stream=False):
                return mock.Mock()

            def close(self):
                pass

        with mock.patch(
            "backend.llm.query_llm.httpx.Client",
            side_effect=_ProxyErrorHttpxClient,
        ):
            with mock.patch(
                "backend.llm.query_llm.requests.post"
            ) as requests_post:
                with self.assertRaises(QueryLlmConnectionError):
                    QueryLlm(
                        settings=_settings(
                            llm_http_client="httpx",
                            ollama_proxy_url="socks5h://127.0.0.1:1055",
                        ),
                    ).request("hola")
        requests_post.assert_not_called()

    def test_httpx_stream_iteration_error_maps_to_connection_error(
        self,
    ) -> None:
        class _StreamErrorStreamingResponse(_FakeHttpxStreamingResponse):
            def iter_bytes(self, chunk_size: int = 8192):
                self.iter_calls += 1
                yield b'{"response":'
                raise httpx.StreamError("stream cut mid-response")

        class _StreamingStreamErrorClient:
            def __init__(self, *args, **kwargs):
                pass

            def build_request(self, method, url, json=None, **kw):
                return mock.Mock()

            def send(self, request, stream=False):
                return _StreamErrorStreamingResponse(
                    json.dumps({"ok": True})
                )

            def close(self):
                pass

        captured, capture_fn = self._capture_emit_events()
        with mock.patch(
            "backend.llm.query_llm.httpx.Client",
            side_effect=_StreamingStreamErrorClient,
        ):
            with mock.patch(
                "backend.llm.query_llm.emit_event",
                side_effect=capture_fn,
            ):
                with self.assertRaises(QueryLlmConnectionError):
                    QueryLlm(
                        settings=_settings(llm_http_client="httpx"),
                    ).request(
                        "hola", correlation_id="SYN-HTTPX-STREAM"
                    )

        self.assertIn("first_body_chunk", self._phases(captured))
        self.assertNotIn("body_completed", self._phases(captured))
        self.assertNotIn("response_received", self._phases(captured))

    def test_httpx_stream_read_timeout_maps_to_query_llm_timeout_error(
        self,
    ) -> None:
        class _ReadTimeoutStreamingResponse(_FakeHttpxStreamingResponse):
            def iter_bytes(self, chunk_size: int = 8192):
                self.iter_calls += 1
                yield b'{"response":'
                raise httpx.ReadTimeout("read deadline")

        class _StreamingReadTimeoutClient:
            def __init__(self, *args, **kwargs):
                pass

            def build_request(self, method, url, json=None, **kw):
                return mock.Mock()

            def send(self, request, stream=False):
                return _ReadTimeoutStreamingResponse(
                    json.dumps({"ok": True})
                )

            def close(self):
                pass

        with mock.patch(
            "backend.llm.query_llm.httpx.Client",
            side_effect=_StreamingReadTimeoutClient,
        ):
            with self.assertRaises(QueryLlmTimeoutError):
                QueryLlm(
                    settings=_settings(llm_http_client="httpx"),
                ).request("hola")

    def test_httpx_http_status_error_raises_query_llm_http_error(
        self,
    ) -> None:
        class _HttpErrorHttpxClient:
            def __init__(self, *args, **kwargs):
                pass

            def build_request(self, method, url, json=None, **kw):
                return mock.Mock()

            def send(self, request, stream=False):
                return _FakeHttpxStreamingResponse(
                    json.dumps({"ok": True}), status_code=503
                )

            def close(self):
                pass

        with mock.patch(
            "backend.llm.query_llm.httpx.Client",
            side_effect=_HttpErrorHttpxClient,
        ):
            with self.assertRaises(QueryLlmHttpError) as ctx:
                QueryLlm(
                    settings=_settings(llm_http_client="httpx"),
                ).request("hola")
        self.assertEqual(ctx.exception.status_code, 503)

    def test_httpx_invalid_envelope_raises_response_error(self) -> None:
        class _InvalidEnvelopeHttpxClient:
            def __init__(self, *args, **kwargs):
                pass

            def build_request(self, method, url, json=None, **kw):
                return mock.Mock()

            def send(self, request, stream=False):
                return _FakeHttpxStreamingResponse("not-json")

            def close(self):
                pass

        with mock.patch(
            "backend.llm.query_llm.httpx.Client",
            side_effect=_InvalidEnvelopeHttpxClient,
        ):
            with self.assertRaises(QueryLlmResponseError):
                QueryLlm(
                    settings=_settings(llm_http_client="httpx"),
                ).request("hola")

    def test_httpx_failure_does_not_invoke_requests_as_fallback(self) -> None:
        class _FailingHttpxClient:
            def __init__(self, *args, **kwargs):
                pass

            def build_request(self, method, url, json=None, **kw):
                raise httpx.ConnectError("connection refused")

            def send(self, request, stream=False):
                return mock.Mock()

            def close(self):
                pass

        with mock.patch(
            "backend.llm.query_llm.httpx.Client",
            side_effect=_FailingHttpxClient,
        ):
            with mock.patch(
                "backend.llm.query_llm.requests.post"
            ) as requests_post:
                with self.assertRaises(QueryLlmConnectionError):
                    QueryLlm(
                        settings=_settings(llm_http_client="httpx"),
                    ).request("hola")
        self.assertEqual(requests_post.call_count, 0)

    def test_httpx_phase_events_omit_url_proxy_and_secrets(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        settings = _settings(
            llm_http_client="httpx",
            llm_url="http://secret-host.invalid/api/generate",
            ollama_proxy_url="socks5h://user:pass@127.0.0.1:9050",
            llm_log_content=True,
        )

        class _StreamingHttpxClient:
            def __init__(self, *args, **kwargs):
                pass

            def build_request(self, method, url, json=None, **kw):
                return mock.Mock()

            def send(self, request, stream=False):
                return _FakeHttpxStreamingResponse(
                    json.dumps({"intents": ["x"]})
                )

            def close(self):
                pass

        with mock.patch(
            "backend.llm.query_llm.httpx.Client",
            side_effect=_StreamingHttpxClient,
        ):
            with mock.patch(
                "backend.llm.query_llm.emit_event",
                side_effect=capture_fn,
            ):
                QueryLlm(settings=settings).request("super-secret-prompt")

        phase_events = [
            ev
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
        ]
        self.assertGreater(len(phase_events), 0)
        for ev in phase_events:
            serialized = json.dumps(ev, sort_keys=True)
            self.assertNotIn("super-secret-prompt", serialized)
            self.assertNotIn("intents", serialized)
            self.assertNotIn("super-secret-url", serialized)
            self.assertNotIn("socks5h", serialized)
            self.assertNotIn("secret-host.invalid", serialized)
            self.assertNotIn("user:pass", serialized)
            self.assertNotIn("Bearer", serialized)
            self.assertNotIn("Authorization", serialized)
            self.assertNotIn("api/generate", serialized)

    def test_httpx_accepts_both_socks5_and_socks5h_schemes(self) -> None:
        for scheme in ("socks5", "socks5h"):
            with self.subTest(scheme=scheme):
                captured_client_kwargs: dict = {}

                class _RecordingClient:
                    def __init__(
                        self,
                        *args,
                        _sink=captured_client_kwargs,
                        **kwargs,
                    ):
                        _sink.update(kwargs)

                    def build_request(self, method, url, json=None, **kw):
                        return mock.Mock()

                    def send(self, request, stream=False):
                        return _FakeHttpxStreamingResponse(
                            json.dumps({"ok": True})
                        )

                    def close(self):
                        pass

                proxy_url = f"{scheme}://127.0.0.1:1055"
                with mock.patch(
                    "backend.llm.query_llm.httpx.Client",
                    side_effect=_RecordingClient,
                ):
                    QueryLlm(
                        settings=_settings(
                            llm_http_client="httpx",
                            ollama_proxy_url=proxy_url,
                        ),
                    ).request("hola")
                self.assertEqual(
                    captured_client_kwargs.get("proxy"), proxy_url
                )

    def test_httpx_proxy_url_is_forwarded_verbatim(self) -> None:
        captured_client_kwargs: dict = {}

        class _RecordingClient:
            def __init__(self, *args, **kwargs):
                captured_client_kwargs.update(kwargs)

            def build_request(self, method, url, json=None, **kw):
                return mock.Mock()

            def send(self, request, stream=False):
                return _FakeHttpxStreamingResponse(
                    json.dumps({"ok": True})
                )

            def close(self):
                pass

        proxy_url = "socks5h://127.0.0.1:1055"
        with mock.patch(
            "backend.llm.query_llm.httpx.Client",
            side_effect=_RecordingClient,
        ):
            QueryLlm(
                settings=_settings(
                    llm_http_client="httpx",
                    ollama_proxy_url=proxy_url,
                ),
            ).request("hola")
        self.assertEqual(captured_client_kwargs.get("proxy"), proxy_url)

    def test_httpx_does_not_set_process_wide_proxy(self) -> None:
        import os as _os

        class _RecordingClient:
            def __init__(self, *args, **kwargs):
                self.kwargs = kwargs

            def build_request(self, method, url, json=None, **kw):
                return mock.Mock()

            def send(self, request, stream=False):
                return _FakeHttpxStreamingResponse(
                    json.dumps({"ok": True})
                )

            def close(self):
                pass

        with mock.patch.dict(
            _os.environ, {}, clear=True
        ), mock.patch(
            "backend.llm.query_llm.httpx.Client",
            side_effect=_RecordingClient,
        ):
            QueryLlm(
                settings=_settings(
                    llm_http_client="httpx",
                    ollama_proxy_url="socks5h://127.0.0.1:1055",
                ),
            ).request("hola")
        self.assertNotIn("HTTP_PROXY", _os.environ)
        self.assertNotIn("HTTPS_PROXY", _os.environ)
        self.assertNotIn("ALL_PROXY", _os.environ)

    def test_httpx_client_is_closed_on_uncaught_exception(self) -> None:
        close_calls = {"count": 0}

        class _StreamingHttpxClient:
            def __init__(self, *args, **kwargs):
                pass

            def build_request(self, method, url, json=None, **kw):
                raise httpx.ConnectError("connection refused")

            def send(self, request, stream=False):
                return mock.Mock()

            def close(self):
                close_calls["count"] += 1

        with mock.patch(
            "backend.llm.query_llm.httpx.Client",
            side_effect=_StreamingHttpxClient,
        ):
            with self.assertRaises(QueryLlmConnectionError):
                QueryLlm(
                    settings=_settings(llm_http_client="httpx"),
                ).request("hola")
        self.assertEqual(close_calls["count"], 1)

    def test_httpx_http_status_error_does_not_double_request(self) -> None:
        send_calls = {"count": 0}

        class _HttpErrorHttpxClient:
            def __init__(self, *args, **kwargs):
                pass

            def build_request(self, method, url, json=None, **kw):
                return mock.Mock()

            def send(self, request, stream=False):
                send_calls["count"] += 1
                return _FakeHttpxStreamingResponse(
                    json.dumps({"ok": True}), status_code=502
                )

            def close(self):
                pass

        with mock.patch(
            "backend.llm.query_llm.httpx.Client",
            side_effect=_HttpErrorHttpxClient,
        ):
            with self.assertRaises(QueryLlmHttpError):
                QueryLlm(
                    settings=_settings(llm_http_client="httpx"),
                ).request("hola")
        self.assertEqual(send_calls["count"], 1)


class QueryLlmHttpxLoggingTest(unittest.TestCase):
    """Privacy contract for the HTTPX QueryLlm transport path.

    The HTTPX branch MUST honour the same log-content contract the
    Requests branch has enforced since the historical seam: no
    prompt, response, URL, proxy, header, credential or raw
    exception message may appear in any log line.
    """

    def setUp(self) -> None:
        reset_llm_timing_recorder()

    def tearDown(self) -> None:
        reset_llm_timing_recorder()

    def _make_client(self, **setting_overrides) -> QueryLlm:
        settings = _settings(llm_http_client="httpx", **setting_overrides)
        return QueryLlm(settings=settings)

    def test_httpx_debug_logs_never_contain_prompt_or_response(self) -> None:
        class _StreamingHttpxClient:
            def __init__(self, *args, **kwargs):
                pass

            def build_request(self, method, url, json=None, **kw):
                return mock.Mock()

            def send(self, request, stream=False):
                return _FakeHttpxStreamingResponse(
                    json.dumps({"ok": "RESPONSE-SENTINEL-QWERTY-99"})
                )

            def close(self):
                pass

        client = self._make_client(llm_log_content=True)
        with mock.patch(
            "backend.llm.query_llm.httpx.Client",
            side_effect=_StreamingHttpxClient,
        ):
            with self.assertLogs(
                "backend.llm.query_llm", level="DEBUG"
            ) as captured:
                client.request("PROMPT-SENTINEL-XYZZY-42")
        joined = "\n".join(captured.output)
        self.assertNotIn("PROMPT-SENTINEL-XYZZY-42", joined)
        self.assertNotIn("RESPONSE-SENTINEL-QWERTY-99", joined)

    def test_httpx_failure_logs_carry_duration_without_exception_message(
        self,
    ) -> None:
        class _ConnectErrorHttpxClient:
            def __init__(self, *args, **kwargs):
                pass

            def build_request(self, method, url, json=None, **kw):
                raise httpx.ConnectError("secret-detail-leaked")

            def send(self, request, stream=False):
                return mock.Mock()

            def close(self):
                pass

        client = self._make_client(llm_log_content=True)
        with mock.patch(
            "backend.llm.query_llm.httpx.Client",
            side_effect=_ConnectErrorHttpxClient,
        ):
            with self.assertLogs(
                "backend.llm.query_llm", level="DEBUG"
            ) as captured:
                with self.assertRaises(QueryLlmConnectionError):
                    client.request("hola")
        joined = "\n".join(captured.output)
        self.assertIn("llm request failure", joined)
        self.assertIn("duration=", joined)
        self.assertNotIn("secret-detail-leaked", joined)

    def test_httpx_logs_do_not_leak_url_proxy_or_credentials(self) -> None:
        class _StreamingHttpxClient:
            def __init__(self, *args, **kwargs):
                pass

            def build_request(self, method, url, json=None, **kw):
                return mock.Mock()

            def send(self, request, stream=False):
                return _FakeHttpxStreamingResponse(
                    json.dumps({"ok": True})
                )

            def close(self):
                pass

        client = self._make_client(
            llm_url="http://secret-host.invalid/api/generate",
            ollama_proxy_url="socks5h://user:pass@127.0.0.1:9050",
            llm_log_content=True,
        )
        with mock.patch(
            "backend.llm.query_llm.httpx.Client",
            side_effect=_StreamingHttpxClient,
        ):
            with self.assertLogs(
                "backend.llm.query_llm", level="DEBUG"
            ) as captured:
                client.request("hola")
        joined = "\n".join(captured.output)
        for forbidden in (
            "secret-host.invalid",
            "socks5h",
            "127.0.0.1",
            "user:pass",
            "9050",
            "/api/generate",
        ):
            self.assertNotIn(forbidden, joined)


class _SocksPhaseObserverSeamTests(unittest.TestCase):
    """Direct tests for the private ``_SocksPhaseObserverMixin`` used by
    :class:`backend.llm.query_llm._ObservingSocksHTTPConnection` and
    :class:`_ObservingSocksHTTPSConnection`.

    The tests patch the underlying ``urllib3.contrib.socks`` and
    ``urllib3.connection`` seams (the supported, pinned extension
    points the design adopted) so the observer logic can be exercised
    without a real SOCKS server or any open socket. The session is
    constructed per call (no process-local cache), so there is no
    cached observer session to reset between tests.
    """

    def setUp(self) -> None:
        reset_llm_timing_recorder()
        from backend.llm import query_llm as _query_llm_module

        self._query_llm_module = _query_llm_module

    def tearDown(self) -> None:
        reset_llm_timing_recorder()

    def _capture_emit_events(self) -> tuple[list[dict], object]:
        captured: list[dict] = []

        def _capture(*, event: str, **kwargs: object) -> bool:
            from backend.observability.events import build_event

            payload = build_event(event=event, **kwargs)
            captured.append(payload)
            return True

        return captured, _capture

    def _phases(self, captured: list[dict]) -> list[str]:
        return [
            ev["phase"]
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
        ]

    def _phase_payloads(self, captured: list[dict]) -> dict[str, dict]:
        return {
            ev["phase"]: ev
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
        }

    def test_socks_connect_started_emitted_with_zero_elapsed(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        with mock.patch(
            "urllib3.contrib.socks.SOCKSConnection._new_conn",
            return_value=mock.Mock(),
        ), mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            from backend.llm.query_llm import _ObservingSocksHTTPConnection

            conn = _ObservingSocksHTTPConnection(
                host="127.0.0.1",
                port=11434,
                _socks_options={
                    "socks_version": 2,
                    "proxy_host": "127.0.0.1",
                    "proxy_port": "1055",
                    "username": None,
                    "password": None,
                    "rdns": True,
                },
            )
            conn._new_conn()
        started = next(
            ev
            for ev in captured
            if ev["phase"] == "socks_connect_started"
        )
        self.assertEqual(started["elapsed_ms"], 0)
        self.assertNotIn("http_status", started)
        self.assertNotIn("response_bytes", started)
        self.assertNotIn("chunk_count", started)

    def test_socks_connect_completed_emitted_with_non_negative_elapsed(
        self,
    ) -> None:
        captured, capture_fn = self._capture_emit_events()
        with mock.patch(
            "urllib3.contrib.socks.SOCKSConnection._new_conn",
            return_value=mock.Mock(),
        ), mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            from backend.llm.query_llm import _ObservingSocksHTTPConnection

            conn = _ObservingSocksHTTPConnection(
                host="127.0.0.1",
                port=11434,
                _socks_options={
                    "socks_version": 2,
                    "proxy_host": "127.0.0.1",
                    "proxy_port": "1055",
                    "username": None,
                    "password": None,
                    "rdns": True,
                },
            )
            conn._new_conn()
        completed = next(
            ev
            for ev in captured
            if ev["phase"] == "socks_connect_completed"
        )
        self.assertIsInstance(completed["elapsed_ms"], int)
        self.assertGreaterEqual(completed["elapsed_ms"], 0)
        self.assertNotIn("http_status", completed)
        self.assertNotIn("response_bytes", completed)
        self.assertNotIn("chunk_count", completed)

    def test_socks_seam_failure_does_not_emit_completion(self) -> None:
        """When the SOCKS connect seam raises, the completion / writer /
        header evidence must never be fabricated."""
        captured, capture_fn = self._capture_emit_events()

        def _boom_new_conn(self):
            raise requests.exceptions.ProxyError("proxy refused")

        with mock.patch(
            "urllib3.contrib.socks.SOCKSConnection._new_conn",
            _boom_new_conn,
        ), mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            from backend.llm.query_llm import _ObservingSocksHTTPConnection

            conn = _ObservingSocksHTTPConnection(
                host="127.0.0.1",
                port=11434,
                _socks_options={
                    "socks_version": 2,
                    "proxy_host": "127.0.0.1",
                    "proxy_port": "1055",
                    "username": None,
                    "password": None,
                    "rdns": True,
                },
            )
            with self.assertRaises(requests.exceptions.ProxyError):
                conn._new_conn()

        phases = self._phases(captured)
        self.assertEqual(phases, ["socks_connect_started"])
        self.assertNotIn("socks_connect_completed", phases)
        self.assertNotIn("request_write_started", phases)
        self.assertNotIn("request_write_completed", phases)
        self.assertNotIn("response_headers_received", phases)

    def test_request_write_started_emitted_with_zero_elapsed(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        with mock.patch(
            "urllib3.connection.HTTPConnection.request",
            return_value=None,
        ), mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            from backend.llm.query_llm import _ObservingSocksHTTPConnection

            conn = _ObservingSocksHTTPConnection(
                host="127.0.0.1",
                port=11434,
                _socks_options={
                    "socks_version": 2,
                    "proxy_host": "127.0.0.1",
                    "proxy_port": "1055",
                    "username": None,
                    "password": None,
                    "rdns": True,
                },
            )
            conn.sock = mock.Mock()
            conn.request("POST", "/api/generate", body=b"{}", headers={})
        started = next(
            ev
            for ev in captured
            if ev["phase"] == "request_write_started"
        )
        self.assertEqual(started["elapsed_ms"], 0)
        self.assertNotIn("http_status", started)
        self.assertNotIn("response_bytes", started)
        self.assertNotIn("chunk_count", started)

    def test_request_write_completed_emitted_with_non_negative_elapsed(
        self,
    ) -> None:
        captured, capture_fn = self._capture_emit_events()
        with mock.patch(
            "urllib3.connection.HTTPConnection.request",
            return_value=None,
        ), mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            from backend.llm.query_llm import _ObservingSocksHTTPConnection

            conn = _ObservingSocksHTTPConnection(
                host="127.0.0.1",
                port=11434,
                _socks_options={
                    "socks_version": 2,
                    "proxy_host": "127.0.0.1",
                    "proxy_port": "1055",
                    "username": None,
                    "password": None,
                    "rdns": True,
                },
            )
            conn.sock = mock.Mock()
            conn.request("POST", "/api/generate", body=b"{}", headers={})
        completed = next(
            ev
            for ev in captured
            if ev["phase"] == "request_write_completed"
        )
        self.assertIsInstance(completed["elapsed_ms"], int)
        self.assertGreaterEqual(completed["elapsed_ms"], 0)
        self.assertNotIn("http_status", completed)
        self.assertNotIn("response_bytes", completed)
        self.assertNotIn("chunk_count", completed)

    def test_request_writer_failure_does_not_emit_completion(self) -> None:
        captured, capture_fn = self._capture_emit_events()

        def _boom_request(self, *args, **kwargs):
            raise requests.exceptions.ConnectionError("writer failed")

        with mock.patch(
            "urllib3.connection.HTTPConnection.request",
            _boom_request,
        ), mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            from backend.llm.query_llm import _ObservingSocksHTTPConnection

            conn = _ObservingSocksHTTPConnection(
                host="127.0.0.1",
                port=11434,
                _socks_options={
                    "socks_version": 2,
                    "proxy_host": "127.0.0.1",
                    "proxy_port": "1055",
                    "username": None,
                    "password": None,
                    "rdns": True,
                },
            )
            conn.sock = mock.Mock()
            with self.assertRaises(requests.exceptions.ConnectionError):
                conn.request("POST", "/api/generate", body=b"{}", headers={})

        phases = self._phases(captured)
        self.assertEqual(phases, ["request_write_started"])
        self.assertNotIn("request_write_completed", phases)
        self.assertNotIn("response_headers_received", phases)


class QueryLlmSocksProxyIntegrationTest(unittest.TestCase):
    """End-to-end ``QueryLlm`` coverage for the SOCKS observer path.

    The tests pin the documented strict-order guarantee:
    ``request_started`` → ``request_write_started`` → SOCKS start /
    completed → ``request_write_completed`` → ``response_headers_received``
    (and the rest of the legacy phase envelope), and the
    no-proxy / injected-transport / blocked-SOCKS / writer-failure /
    emission-failure contracts. The private session is built per
    request so two consecutive calls never share a session, an
    adapter, a manager or a socket.
    """

    def setUp(self) -> None:
        reset_llm_timing_recorder()
        from backend.llm import query_llm as _query_llm_module

        self._query_llm_module = _query_llm_module

    def tearDown(self) -> None:
        reset_llm_timing_recorder()

    def _capture_emit_events(self) -> tuple[list[dict], object]:
        captured: list[dict] = []

        def _capture(*, event: str, **kwargs: object) -> bool:
            from backend.observability.events import build_event

            payload = build_event(event=event, **kwargs)
            captured.append(payload)
            return True

        return captured, _capture

    def _phases(self, captured: list[dict]) -> list[str]:
        return [
            ev["phase"]
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
        ]

    def _patch_urllib3_for_socks(
        self,
        *,
        body_bytes: bytes,
        new_conn_side_effect=None,
        getresponse_status: int = 200,
    ) -> object:
        """Build the urllib3 mock context manager required to drive the
        observer end-to-end without opening a real socket.

        ``new_conn_side_effect`` lets the test raise from the patched
        SOCKS connect seam to exercise the blocked-failure contract.
        The default returns a ``Mock`` socket so the writer seam can
        run.
        """
        fake_socket = mock.Mock()
        if new_conn_side_effect is None:
            new_conn_return = fake_socket
        else:
            new_conn_return = mock.Mock(side_effect=new_conn_side_effect)

        fake_response = mock.Mock()
        fake_response.status = getresponse_status
        fake_response.headers = {"Content-Type": "application/json"}
        fake_response.chunked = False
        fake_response.length_remaining = len(body_bytes)
        fake_response.read_chunked = mock.Mock(return_value=[body_bytes])
        fake_response.release_conn = mock.Mock()
        return mock.patch.multiple(
            "urllib3.contrib.socks.SOCKSConnection",
            _new_conn=new_conn_return,
        ), mock.patch(
            "urllib3.connection.HTTPConnection.getresponse",
            return_value=fake_response,
        )

    def test_socks_success_emits_strict_phase_order(self) -> None:
        import io

        import urllib3

        inner_body = json.dumps({"ok": True})
        body_bytes = json.dumps({"response": inner_body}).encode("utf-8")
        real_response = urllib3.HTTPResponse(
            body=io.BytesIO(body_bytes),
            headers={"Content-Type": "application/json"},
            status=200,
            preload_content=False,
        )
        fake_socket = mock.Mock()

        captured, capture_fn = self._capture_emit_events()
        settings = _settings(ollama_proxy_url="socks5h://127.0.0.1:1055")
        new_conn_patch = mock.patch(
            "urllib3.contrib.socks.SOCKSConnection._new_conn",
            return_value=fake_socket,
        )
        getresponse_patch = mock.patch(
            "urllib3.connection.HTTPConnection.getresponse",
            return_value=real_response,
        )
        with new_conn_patch, getresponse_patch, mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            install_llm_timing_recorder(
                mock.Mock(), correlation_id="SYN-SOCKS-OK"
            )
            try:
                result = QueryLlm(settings=settings).request(
                    "hola", correlation_id="SYN-SOCKS-OK"
                )
            finally:
                reset_llm_timing_recorder()

        self.assertEqual(result, {"ok": True})
        self.assertEqual(
            self._phases(captured),
            [
                "request_started",
                "request_write_started",
                "socks_connect_started",
                "socks_connect_completed",
                "request_write_completed",
                "response_headers_received",
                "first_body_chunk",
                "body_completed",
                "response_received",
                "json_extracted",
                "result_parsed",
            ],
        )

        phase_payloads = {
            ev["phase"]: ev
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
        }
        socks_started = phase_payloads["socks_connect_started"]
        socks_completed = phase_payloads["socks_connect_completed"]
        writer_started = phase_payloads["request_write_started"]
        writer_completed = phase_payloads["request_write_completed"]

        # elapsed_ms is integer / non-negative on every SOCKS / writer phase
        for ev in (
            socks_started,
            socks_completed,
            writer_started,
            writer_completed,
        ):
            self.assertEqual(ev["correlation_id"], "SYN-SOCKS-OK")
            self.assertIsInstance(ev["elapsed_ms"], int)
            self.assertGreaterEqual(ev["elapsed_ms"], 0)
            self.assertNotIn("http_status", ev)
            self.assertNotIn("response_bytes", ev)
            self.assertNotIn("chunk_count", ev)

        self.assertEqual(socks_started["elapsed_ms"], 0)
        self.assertEqual(writer_started["elapsed_ms"], 0)
        self.assertGreaterEqual(socks_completed["elapsed_ms"], 0)
        self.assertGreaterEqual(writer_completed["elapsed_ms"], 0)

    def test_socks_seam_blocked_does_not_fabricate_subsequent_phases(
        self,
    ) -> None:
        """When the SOCKS seam does not return, the trace stops at
        ``socks_connect_started`` and no completion / writer / header
        evidence is fabricated. The exception classification the
        surrounding ``QueryLlm.request`` already performs remains
        authoritative."""

        def _boom_new_conn(*args, **kwargs):
            raise requests.exceptions.ProxyError("proxy refused")

        captured, capture_fn = self._capture_emit_events()
        settings = _settings(ollama_proxy_url="socks5h://127.0.0.1:1055")
        with mock.patch(
            "urllib3.contrib.socks.SOCKSConnection._new_conn",
            side_effect=_boom_new_conn,
        ), mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            install_llm_timing_recorder(
                mock.Mock(), correlation_id="SYN-SOCKS-BLOCK"
            )
            try:
                with self.assertRaises(QueryLlmConnectionError):
                    QueryLlm(settings=settings).request(
                        "hola", correlation_id="SYN-SOCKS-BLOCK"
                    )
            finally:
                reset_llm_timing_recorder()

        phases = self._phases(captured)
        self.assertEqual(
            phases,
            [
                "request_started",
                "request_write_started",
                "socks_connect_started",
            ],
        )
        self.assertNotIn("socks_connect_completed", phases)
        self.assertNotIn("request_write_completed", phases)
        self.assertNotIn("response_headers_received", phases)

        lifecycle_events = [
            ev
            for ev in captured
            if ev.get("event") == "llm_request"
        ]
        self.assertEqual(len(lifecycle_events), 2)
        self.assertEqual(
            lifecycle_events[1]["failure_category"], "connection"
        )
        self.assertEqual(
            lifecycle_events[1]["correlation_id"], "SYN-SOCKS-BLOCK"
        )

    def test_writer_failure_does_not_fabricate_completion_or_headers(
        self,
    ) -> None:
        """A writer failure BEFORE the lazy SOCKS connect runs leaves
        the trace at ``request_write_started``. No SOCKS evidence is
        emitted because the lazy connect step was never reached; no
        completion, no header evidence, no second request."""

        import io

        import urllib3

        body_bytes = json.dumps({"response": json.dumps({"ok": True})}).encode(
            "utf-8"
        )
        real_response = urllib3.HTTPResponse(
            body=io.BytesIO(body_bytes),
            headers={"Content-Type": "application/json"},
            status=200,
            preload_content=False,
        )
        fake_socket = mock.Mock()

        def _boom_request(self, *args, **kwargs):
            raise requests.exceptions.ConnectionError("writer failed")

        captured, capture_fn = self._capture_emit_events()
        settings = _settings(ollama_proxy_url="socks5h://127.0.0.1:1055")
        with mock.patch(
            "urllib3.contrib.socks.SOCKSConnection._new_conn",
            return_value=fake_socket,
        ), mock.patch(
            "urllib3.connection.HTTPConnection.request",
            side_effect=_boom_request,
        ), mock.patch(
            "urllib3.connection.HTTPConnection.getresponse",
            return_value=real_response,
        ), mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            install_llm_timing_recorder(
                mock.Mock(), correlation_id="SYN-SOCKS-WRITER"
            )
            try:
                with self.assertRaises(QueryLlmConnectionError):
                    QueryLlm(settings=settings).request(
                        "hola", correlation_id="SYN-SOCKS-WRITER"
                    )
            finally:
                reset_llm_timing_recorder()

        phases = self._phases(captured)
        self.assertEqual(
            phases,
            [
                "request_started",
                "request_write_started",
            ],
        )
        self.assertNotIn("socks_connect_started", phases)
        self.assertNotIn("socks_connect_completed", phases)
        self.assertNotIn("request_write_completed", phases)
        self.assertNotIn("response_headers_received", phases)
        self.assertNotIn("first_body_chunk", phases)

    def test_no_proxy_does_not_emit_socks_phases(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        captured_post = mock.Mock(return_value=_FakeStreamingResponse(
            json.dumps({"ok": True}), chunk_size=4
        ))
        with mock.patch(
            "backend.llm.query_llm.requests.post", new=captured_post
        ), mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            QueryLlm(settings=_settings()).request(
                "hola", correlation_id="SYN-NOPROXY"
            )

        phases = self._phases(captured)
        self.assertNotIn("socks_connect_started", phases)
        self.assertNotIn("socks_connect_completed", phases)
        self.assertNotIn("request_write_started", phases)
        self.assertNotIn("request_write_completed", phases)
        self.assertEqual(phases[0], "request_started")

    def test_injected_transport_does_not_emit_socks_phases(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        transport = mock.Mock(
            return_value=_FakeStreamingResponse(
                json.dumps({"ok": True}), chunk_size=4
            )
        )
        with mock.patch(
            "backend.llm.query_llm.requests.post"
        ) as legacy_post, mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            QueryLlm(
                settings=_settings(
                    ollama_proxy_url="socks5h://127.0.0.1:1055"
                ),
                transport=transport,
            ).request("hola", correlation_id="SYN-INJ")

        phases = self._phases(captured)
        self.assertNotIn("socks_connect_started", phases)
        self.assertNotIn("socks_connect_completed", phases)
        self.assertNotIn("request_write_started", phases)
        self.assertNotIn("request_write_completed", phases)
        transport.assert_called_once()
        legacy_post.assert_not_called()

    def test_httpx_does_not_emit_socks_phases(self) -> None:
        """The HTTPX branch MUST NOT emit the SOCKS-boundary phases
        because the diagnostic only observes the default Requests +
        SOCKS path."""
        captured, capture_fn = self._capture_emit_events()

        class _StreamingHttpxClient:
            def __init__(self, *args, **kwargs):
                pass

            def build_request(self, method, url, json=None, **kw):
                return mock.Mock()

            def send(self, request, stream=False):
                return _FakeHttpxStreamingResponse(
                    json.dumps({"ok": True}), chunk_size=4
                )

            def close(self):
                pass

        settings = _settings(
            llm_http_client="httpx",
            ollama_proxy_url="socks5h://127.0.0.1:1055",
        )
        with mock.patch(
            "backend.llm.query_llm.httpx.Client",
            side_effect=_StreamingHttpxClient,
        ), mock.patch(
            "backend.llm.query_llm.requests.post"
        ) as legacy_post, mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            QueryLlm(settings=settings).request(
                "hola", correlation_id="SYN-HTTPX-SOCKS"
            )

        phases = self._phases(captured)
        self.assertNotIn("socks_connect_started", phases)
        self.assertNotIn("socks_connect_completed", phases)
        self.assertNotIn("request_write_started", phases)
        self.assertNotIn("request_write_completed", phases)
        legacy_post.assert_not_called()

    def test_socks_request_does_not_duplicate_connection_writer_or_request(
        self,
    ) -> None:
        """A single SOCKS ``QueryLlm.request`` MUST NOT duplicate the
        connection, the writer, or the request. The SOCKS connect
        seam and the inherited writer seam MUST each fire exactly
        once; no fabricated phase pair is allowed."""
        import io

        import urllib3

        body_bytes = json.dumps({"response": json.dumps({"ok": True})}).encode(
            "utf-8"
        )
        real_response = urllib3.HTTPResponse(
            body=io.BytesIO(body_bytes),
            headers={"Content-Type": "application/json"},
            status=200,
            preload_content=False,
        )
        fake_socket = mock.Mock()
        captured, capture_fn = self._capture_emit_events()
        settings = _settings(ollama_proxy_url="socks5h://127.0.0.1:1055")
        new_conn_spy = mock.Mock(return_value=fake_socket)
        with mock.patch(
            "urllib3.contrib.socks.SOCKSConnection._new_conn",
            new=new_conn_spy,
        ), mock.patch(
            "urllib3.connection.HTTPConnection.getresponse",
            return_value=real_response,
        ), mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            install_llm_timing_recorder(
                mock.Mock(), correlation_id="SYN-SOCKS-1X"
            )
            try:
                result = QueryLlm(settings=settings).request(
                    "hola", correlation_id="SYN-SOCKS-1X"
                )
            finally:
                reset_llm_timing_recorder()

        self.assertEqual(result, {"ok": True})
        # The connect seam fires exactly once: the previous forced
        # ``self.connect()`` pre-allocated a socket that the writer
        # would otherwise open lazily and could double-count on a
        # reused socket.
        self.assertEqual(new_conn_spy.call_count, 1)
        # Each SOCKS / writer phase fires exactly once. The SOCKS
        # pair is emitted after the writer entry, never before, and
        # no duplicate emission is allowed.
        phases = self._phases(captured)
        self.assertEqual(
            phases.count("socks_connect_started"),
            1,
        )
        self.assertEqual(
            phases.count("socks_connect_completed"),
            1,
        )
        self.assertEqual(
            phases.count("request_write_started"),
            1,
        )
        self.assertEqual(
            phases.count("request_write_completed"),
            1,
        )

    def test_socks_response_wrapper_close_is_idempotent(self) -> None:
        """Calling :meth:`close` on the response wrapper twice MUST
        close the underlying session exactly once. The wrapper is
        fail-soft so the surrounding business flow cannot crash
        because the SOCKS observer is reused."""
        from backend.llm import query_llm as _query_llm_module

        response = mock.Mock()
        session = mock.Mock()
        wrapper = _query_llm_module._SocksResponseSessionCloser(
            response=response, session=session
        )
        wrapper.close()
        wrapper.close()
        wrapper.close()
        self.assertEqual(session.close.call_count, 1)
        self.assertEqual(response.close.call_count, 1)

    def test_socks_response_wrapper_close_swallows_session_error(
        self,
    ) -> None:
        """A session close() error MUST NOT propagate through the
        wrapper; the wrapper is intentionally fail-soft so an
        observability seam cannot crash the surrounding
        ``QueryLlm.request`` flow."""
        from backend.llm import query_llm as _query_llm_module

        response = mock.Mock()
        session = mock.Mock()
        session.close.side_effect = RuntimeError("session close boom")
        wrapper = _query_llm_module._SocksResponseSessionCloser(
            response=response, session=session
        )
        wrapper.close()
        # Response close must still have run regardless of the
        # session close failure.
        response.close.assert_called_once_with()

    def test_socks_observer_emission_failure_does_not_break_request(
        self,
    ) -> None:
        """An emission failure on the SOCKS / writer helper MUST NOT
        change the invocation count, payload, timeout, exception
        mapping or parsed result."""
        import io

        import urllib3

        body_bytes = json.dumps({"response": json.dumps({"ok": True})}).encode(
            "utf-8"
        )
        real_response = urllib3.HTTPResponse(
            body=io.BytesIO(body_bytes),
            headers={"Content-Type": "application/json"},
            status=200,
            preload_content=False,
        )
        fake_socket = mock.Mock()

        def _explode_socks_phase_only(*, event: str, **kwargs):
            if (
                event == "llm_request_transport_phase"
                and kwargs.get("phase", "").startswith(
                    ("socks_", "request_write_")
                )
            ):
                raise RuntimeError("socks phase emitter boom")
            from backend.observability.events import build_event

            build_event(event=event, **kwargs)
            return True

        captured = mock.Mock()
        captured.attach_mock(mock.Mock(), "_")
        settings = _settings(ollama_proxy_url="socks5h://127.0.0.1:1055")
        with mock.patch(
            "urllib3.contrib.socks.SOCKSConnection._new_conn",
            return_value=fake_socket,
        ), mock.patch(
            "urllib3.connection.HTTPConnection.getresponse",
            return_value=real_response,
        ), mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=_explode_socks_phase_only,
        ):
            result = QueryLlm(settings=settings).request("hola")

        self.assertEqual(result, {"ok": True})

    def test_socks_observer_does_not_log_sensitive_values(self) -> None:
        import io

        import urllib3

        body_bytes = json.dumps({"response": json.dumps({"ok": True})}).encode(
            "utf-8"
        )
        real_response = urllib3.HTTPResponse(
            body=io.BytesIO(body_bytes),
            headers={"Content-Type": "application/json"},
            status=200,
            preload_content=False,
        )
        fake_socket = mock.Mock()
        settings = _settings(
            ollama_proxy_url="socks5h://user:pass@127.0.0.1:1055",
            llm_url="http://secret-host.invalid/api/generate",
        )
        with mock.patch(
            "urllib3.contrib.socks.SOCKSConnection._new_conn",
            return_value=fake_socket,
        ), mock.patch(
            "urllib3.connection.HTTPConnection.getresponse",
            return_value=real_response,
        ):
            with self.assertLogs("backend.llm.query_llm", level="DEBUG") as captured:
                QueryLlm(settings=settings).request("hola")
        joined = "\n".join(captured.output)
        for forbidden in (
            "user:pass",
            "127.0.0.1",
            "1055",
            "secret-host.invalid",
            "socks5h",
            "/api/generate",
        ):
            self.assertNotIn(forbidden, joined)

    def test_socks_observer_session_mounts_observing_adapter(self) -> None:
        from backend.llm.query_llm import (
            _ObservingSocksAdapter,
            _SocksPhaseObserverSession,
        )

        session = _SocksPhaseObserverSession()
        try:
            http_adapter = session.get_adapter("http://example.test")
            https_adapter = session.get_adapter("https://example.test")
            self.assertIsInstance(http_adapter, _ObservingSocksAdapter)
            self.assertIsInstance(https_adapter, _ObservingSocksAdapter)
        finally:
            session.close()

    def test_socks_observer_sessions_are_constructed_per_call(self) -> None:
        """Two consecutive ``_SocksPhaseObserverSession`` constructions
        MUST produce independent session / adapter / proxy manager
        resources. There is no process-local cache."""
        from backend.llm.query_llm import (
            _ObservingSocksAdapter,
            _SocksPhaseObserverSession,
        )

        first = _SocksPhaseObserverSession()
        second = _SocksPhaseObserverSession()
        try:
            self.assertIsNot(first, second)
            self.assertIsInstance(first, _SocksPhaseObserverSession)
            self.assertIsInstance(second, _SocksPhaseObserverSession)
            # The adapter instance MUST differ between the two
            # sessions — the cache the diagnostic removed was the one
            # that previously pinned a single adapter across calls.
            first_adapter = first.get_adapter("http://example.test")
            second_adapter = second.get_adapter("http://example.test")
            self.assertIsInstance(first_adapter, _ObservingSocksAdapter)
            self.assertIsInstance(second_adapter, _ObservingSocksAdapter)
            self.assertIsNot(first_adapter, second_adapter)
        finally:
            first.close()
            second.close()

    def test_is_socks_proxy_url_only_matches_socks_schemes(self) -> None:
        from backend.llm.query_llm import _is_socks_proxy_url

        self.assertTrue(_is_socks_proxy_url("socks5h://127.0.0.1:1055"))
        self.assertTrue(_is_socks_proxy_url("socks5://127.0.0.1:1055"))
        self.assertTrue(_is_socks_proxy_url("socks4a://127.0.0.1:1055"))
        self.assertTrue(_is_socks_proxy_url("socks4://127.0.0.1:1055"))
        self.assertTrue(_is_socks_proxy_url("SOCKS5H://127.0.0.1:1055"))
        self.assertFalse(_is_socks_proxy_url(None))
        self.assertFalse(_is_socks_proxy_url(""))
        self.assertFalse(_is_socks_proxy_url("http://127.0.0.1:3128"))
        self.assertFalse(_is_socks_proxy_url("https://127.0.0.1:3128"))
        self.assertFalse(_is_socks_proxy_url(123))
        self.assertFalse(_is_socks_proxy_url([]))


class QueryLlmSocksSessionFailureTest(unittest.TestCase):
    """Focused coverage for the SOCKS observer session lifecycle when
    :meth:`_SocksPhaseObserverSession.post` raises before a response
    object exists to drive :meth:`_SocksResponseSessionCloser.close`.

    Each scenario proves that:

    * the private observer session is closed exactly once,
    * no :class:`_SocksResponseSessionCloser` wrapper is produced,
    * the original :mod:`requests.exceptions.RequestException`
      subclass is preserved and re-raised so the
      :func:`_classify_post_exception` mapper keeps producing the
      canonical :class:`QueryLlmTimeoutError` /
      :class:`QueryLlmConnectionError` subtype,
    * no second request, no fabricated completion / header phases
      and no SOCKS pair completion are emitted by the failure,
    * no traceback, exception text or sensitive payload leaks into
      the logging channel.
    """

    _PROXY_URL = "socks5h://127.0.0.1:1055"
    _LLM_URL = "http://llm.test/api/generate"
    _SENTINEL = "SOCKS-SESSION-CLOSE-LEAK-SENTINEL-XYZ-99"

    def setUp(self) -> None:
        reset_llm_timing_recorder()

    def tearDown(self) -> None:
        reset_llm_timing_recorder()

    def _capture_emit_events(self) -> tuple[list[dict], object]:
        captured: list[dict] = []

        def _capture(*, event: str, **kwargs: object) -> bool:
            from backend.observability.events import build_event

            payload = build_event(event=event, **kwargs)
            captured.append(payload)
            return True

        return captured, _capture

    def _phases(self, captured: list[dict]) -> list[str]:
        return [
            ev["phase"]
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
        ]

    def _build_post_mock(
        self, *, side_effect: BaseException
    ) -> tuple[mock.Mock, mock.Mock]:
        """Return a ``(session_factory_mock, post_mock)`` pair that
        mimics the private observer session contract used by
        :meth:`QueryLlm._post_requests` so the failure path of
        ``session.post(...)`` is exercised without opening a real
        socket. ``post_mock.call_count`` doubles as a no-second-
        request guard for the assertions below.
        """
        session = mock.Mock()
        session.post.side_effect = side_effect
        return session, session.post

    def test_socks_session_post_timeout_closes_session_once(self) -> None:
        """``requests.exceptions.Timeout`` raised by
        ``session.post`` MUST close the observer session exactly
        once and re-raise the original exception so the surrounding
        mapper produces ``QueryLlmTimeoutError``. No response
        wrapper is produced and the trace stops before any
        fabricated SOCKS completion / writer completion / response
        header evidence.
        """
        captured, capture_fn = self._capture_emit_events()
        session, post_mock = self._build_post_mock(
            side_effect=requests.exceptions.Timeout(
                f"{self._SENTINEL} timeout-detail"
            )
        )
        settings = _settings(ollama_proxy_url=self._PROXY_URL)
        with mock.patch(
            "backend.llm.query_llm._SocksPhaseObserverSession",
            return_value=session,
        ), mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            with self.assertRaises(QueryLlmTimeoutError):
                QueryLlm(settings=settings).request("hola")

        # ``session.post`` was invoked exactly once and no response
        # wrapper ever existed for the surrounding ``finally`` block
        # to close, so the session MUST have been closed by the
        # per-call helper exactly once.
        self.assertEqual(post_mock.call_count, 1)
        self.assertEqual(session.close.call_count, 1)

        phases = self._phases(captured)
        # ``request_started`` is the QueryLlm boundary observation
        # emitted before ``_post_requests`` runs. ``session.post``
        # failed before the writer / SOCKS seams were entered, so no
        # additional phase may be fabricated.
        self.assertEqual(phases, ["request_started"])
        self.assertNotIn("request_write_started", phases)
        self.assertNotIn("request_write_completed", phases)
        self.assertNotIn("socks_connect_started", phases)
        self.assertNotIn("socks_connect_completed", phases)
        self.assertNotIn("response_headers_received", phases)

    def test_socks_session_post_connection_error_closes_session_once(
        self,
    ) -> None:
        """``requests.exceptions.ConnectionError`` raised by
        ``session.post`` MUST close the observer session exactly
        once and re-raise the original exception so the surrounding
        mapper produces ``QueryLlmConnectionError``."""
        captured, capture_fn = self._capture_emit_events()
        session, post_mock = self._build_post_mock(
            side_effect=requests.exceptions.ConnectionError(
                f"{self._SENTINEL} connection-detail"
            )
        )
        settings = _settings(ollama_proxy_url=self._PROXY_URL)
        with mock.patch(
            "backend.llm.query_llm._SocksPhaseObserverSession",
            return_value=session,
        ), mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            with self.assertRaises(QueryLlmConnectionError):
                QueryLlm(settings=settings).request("hola")

        self.assertEqual(post_mock.call_count, 1)
        self.assertEqual(session.close.call_count, 1)
        phases = self._phases(captured)
        self.assertEqual(phases, ["request_started"])
        self.assertNotIn("request_write_started", phases)
        self.assertNotIn("request_write_completed", phases)
        self.assertNotIn("socks_connect_started", phases)
        self.assertNotIn("socks_connect_completed", phases)
        self.assertNotIn("response_headers_received", phases)

    def test_socks_session_post_proxy_error_closes_session_once(
        self,
    ) -> None:
        """``requests.exceptions.ProxyError`` is a
        :class:`ConnectionError` sibling; the change MUST preserve the
        existing classification into ``QueryLlmConnectionError``
        instead of swallowing it. ``ProxyError`` carries the
        sentinel-bearing text that would leak through any
        ``logger.exception`` call — the test verifies the session
        is closed once and the exception type is authoritative.
        """
        captured, capture_fn = self._capture_emit_events()
        session, post_mock = self._build_post_mock(
            side_effect=requests.exceptions.ProxyError(
                f"{self._SENTINEL} proxy-detail"
            )
        )
        settings = _settings(ollama_proxy_url=self._PROXY_URL)
        with mock.patch(
            "backend.llm.query_llm._SocksPhaseObserverSession",
            return_value=session,
        ), mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            with self.assertRaises(QueryLlmConnectionError):
                QueryLlm(settings=settings).request("hola")

        self.assertEqual(post_mock.call_count, 1)
        self.assertEqual(session.close.call_count, 1)
        phases = self._phases(captured)
        self.assertEqual(phases, ["request_started"])

    def test_socks_session_post_failure_does_not_leak_sensitive_text(
        self,
    ) -> None:
        """The failure path MUST NOT log the ``Timeout`` /
        ``ConnectionError`` / ``ProxyError`` exception text, its
        arguments, the proxy URL, the proxy host or port. The
        contract forbids ``logger.exception`` and any interpolation
        of the exception on the SOCKS observer code path.
        """
        session, _ = self._build_post_mock(
            side_effect=requests.exceptions.Timeout(
                f"{self._SENTINEL} must-not-appear-anywhere"
            )
        )
        settings = _settings(
            ollama_proxy_url=self._PROXY_URL,
            llm_url="http://secret-host.invalid/api/generate",
        )
        with mock.patch(
            "backend.llm.query_llm._SocksPhaseObserverSession",
            return_value=session,
        ):
            with self.assertLogs(
                "backend.llm.query_llm", level="DEBUG"
            ) as captured:
                with self.assertRaises(QueryLlmTimeoutError):
                    QueryLlm(settings=settings).request("hola")
        joined = "\n".join(captured.output)
        for forbidden in (
            self._SENTINEL,
            "must-not-appear-anywhere",
            "secret-host.invalid",
            "/api/generate",
            "socks5h",
            "127.0.0.1",
            "1055",
            "Traceback",
        ):
            self.assertNotIn(forbidden, joined)

    def test_two_consecutive_socks_post_failures_have_independent_sessions(
        self,
    ) -> None:
        """Two consecutive ``QueryLlm`` SOCKS requests whose
        ``session.post`` raises MUST each build an independent observer
        session. Both calls close their own session exactly once;
        closing one MUST NOT bleed into the other; both calls
        MUST re-raise the original exception so the existing
        mapper keeps producing the canonical ``QueryLlm*Error``
        subtype."""
        from backend.llm import query_llm as _query_llm_module

        captured, capture_fn = self._capture_emit_events()
        session_a = mock.Mock()
        session_a.post.side_effect = requests.exceptions.Timeout("a")
        session_b = mock.Mock()
        session_b.post.side_effect = requests.exceptions.ConnectionError(
            "b"
        )
        constructor = mock.Mock(side_effect=[session_a, session_b])
        settings = _settings(ollama_proxy_url=self._PROXY_URL)
        with mock.patch.object(
            _query_llm_module,
            "_SocksPhaseObserverSession",
            constructor,
        ), mock.patch(
            "backend.llm.query_llm.emit_event",
            side_effect=capture_fn,
        ):
            with self.assertRaises(QueryLlmTimeoutError):
                QueryLlm(settings=settings).request(
                    "hola", correlation_id="SYN-SOCKS-FAIL-A"
                )
            with self.assertRaises(QueryLlmConnectionError):
                QueryLlm(settings=settings).request(
                    "hola", correlation_id="SYN-SOCKS-FAIL-B"
                )

        self.assertEqual(constructor.call_count, 2)
        self.assertIsNot(session_a, session_b)
        # Both sessions were closed exactly once. The per-call
        # helper honoured the lifecycle on each request, never
        # reused and never skipped a session.
        self.assertEqual(session_a.close.call_count, 1)
        self.assertEqual(session_b.close.call_count, 1)
        # No second ``session.post`` invocation leaked across the
        # two failures.
        self.assertEqual(session_a.post.call_count, 1)
        self.assertEqual(session_b.post.call_count, 1)
        # Each request kept the original exception: ``Timeout`` mapped
        # to ``QueryLlmTimeoutError`` on the first call and
        # ``ConnectionError`` mapped to ``QueryLlmConnectionError``
        # on the second call.
        phases_a = [
            ev
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
            and ev.get("correlation_id") == "SYN-SOCKS-FAIL-A"
        ]
        phases_b = [
            ev
            for ev in captured
            if ev.get("event") == "llm_request_transport_phase"
            and ev.get("correlation_id") == "SYN-SOCKS-FAIL-B"
        ]
        self.assertEqual([ev["phase"] for ev in phases_a], ["request_started"])
        self.assertEqual([ev["phase"] for ev in phases_b], ["request_started"])

    def test_socks_observer_session_close_failure_does_not_log_sentinel(
        self,
    ) -> None:
        """The per-call helper that closes a SOCKS observer session
        when ``session.post`` itself raises MUST NOT leak the
        sentinel exception text or a traceback through the
        ``backend.llm.query_llm`` logger. The helper is
        intentionally fail-soft and silent.

        The test exercises the helper directly (rather than through
        ``QueryLlm.request``) so the assertion focuses on the
        observer close path instead of the surrounding business
        flow's failure-classification branch.
        """
        from backend.llm import query_llm as _query_llm_module

        captured_records: list[logging.LogRecord] = []
        handler = self._RecordingHandler(captured_records)
        observer_logger = logging.getLogger("backend.llm.query_llm")
        previous_level = observer_logger.level
        observer_logger.setLevel(logging.DEBUG)
        observer_logger.addHandler(handler)
        try:
            sentinel_exc = RuntimeError(self._SENTINEL)
            session = mock.Mock()
            session.close.side_effect = sentinel_exc
            # MUST NOT raise, MUST NOT log.
            _query_llm_module._close_socks_session_safely(session)
        finally:
            observer_logger.removeHandler(handler)
            observer_logger.setLevel(previous_level)

        self.assertEqual(session.close.call_count, 1)
        joined = self._join_records(captured_records)
        for forbidden in (
            self._SENTINEL,
            "RuntimeError",
            "Traceback",
            "close boom",
            "llm_socks_session_close_failed",
        ):
            self.assertNotIn(forbidden, joined)

    def test_socks_response_wrapper_close_failure_does_not_log_sentinel(
        self,
    ) -> None:
        """A ``response.close()`` failure on the wrapper MUST NOT
        leak the sentinel exception text or a traceback through the
        ``backend.llm.query_llm`` logger. The wrapper is
        intentionally fail-soft and silent so the surrounding
        business flow keeps running and the privacy contract holds.
        """
        from backend.llm import query_llm as _query_llm_module

        captured_records: list[logging.LogRecord] = []
        handler = self._RecordingHandler(captured_records)
        observer_logger = logging.getLogger("backend.llm.query_llm")
        previous_level = observer_logger.level
        observer_logger.setLevel(logging.DEBUG)
        observer_logger.addHandler(handler)
        try:
            response = mock.Mock()
            response.status_code = 200
            response.text = json.dumps({"ok": True})
            response.raise_for_status = mock.Mock()
            response.close.side_effect = RuntimeError(self._SENTINEL)
            session = mock.Mock()
            session.close.side_effect = RuntimeError(
                f"{self._SENTINEL} session"
            )
            wrapper = _query_llm_module._SocksResponseSessionCloser(
                response=response, session=session
            )
            wrapper.close()
        finally:
            observer_logger.removeHandler(handler)
            observer_logger.setLevel(previous_level)

        # The idempotency guard still holds: the wrapper closed the
        # response and the session exactly once each, regardless of
        # both close failures.
        self.assertEqual(response.close.call_count, 1)
        self.assertEqual(session.close.call_count, 1)
        joined = self._join_records(captured_records)
        for forbidden in (
            self._SENTINEL,
            "RuntimeError",
            "Traceback",
            "llm_socks_response_close_failed",
            "llm_socks_session_close_failed",
        ):
            self.assertNotIn(forbidden, joined)

    def test_socks_phase_observation_failure_does_not_log_sentinel(
        self,
    ) -> None:
        """A failure raised by ``emit_event`` from inside the new
        SOCKS / writer observation helper MUST NOT leak the
        sentinel exception text or a traceback through the
        ``backend.llm.query_llm`` logger. The helper is
        intentionally fail-soft and silent.
        """
        from backend.llm.query_llm import _emit_socks_phase_observation

        captured_records: list[logging.LogRecord] = []
        handler = self._RecordingHandler(captured_records)
        observer_logger = logging.getLogger("backend.llm.query_llm")
        previous_level = observer_logger.level
        observer_logger.setLevel(logging.DEBUG)
        observer_logger.addHandler(handler)
        try:

            def _explode(*, event: str, **kwargs: object) -> bool:
                if (
                    event == "llm_request_transport_phase"
                    and kwargs.get("phase") == "socks_connect_started"
                ):
                    raise RuntimeError(self._SENTINEL)
                return True

            with mock.patch(
                "backend.llm.query_llm.emit_event",
                side_effect=_explode,
            ):
                # MUST NOT raise and MUST NOT leak the sentinel.
                _emit_socks_phase_observation(
                    "socks_connect_started", elapsed_ms=0
                )
        finally:
            observer_logger.removeHandler(handler)
            observer_logger.setLevel(previous_level)

        joined = self._join_records(captured_records)
        for forbidden in (
            self._SENTINEL,
            "RuntimeError",
            "Traceback",
            "llm_socks_phase_observation_failed",
        ):
            self.assertNotIn(forbidden, joined)

    class _RecordingHandler(logging.Handler):
        """Minimal log handler that captures every record emitted on
        ``backend.llm.query_llm`` while the observer close /
        emission path runs.

        ``unittest.TestCase.assertLogs`` requires at least one log
        record to succeed, so it cannot be used to prove that no
        record was emitted. The handler records every record verbatim
        and the assertions scan the formatted output for any leaked
        sentinel, exception text or traceback.
        """

        def __init__(self, sink: list[logging.LogRecord]) -> None:
            super().__init__(level=logging.DEBUG)
            self._sink = sink

        def emit(self, record: logging.LogRecord) -> None:
            self._sink.append(record)

    def _join_records(
        self, records: list[logging.LogRecord]
    ) -> str:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )
        return "\n".join(
            formatter.format(record) for record in records
        )


if __name__ == "__main__":
    unittest.main()
