import io
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


if __name__ == "__main__":
    unittest.main()
