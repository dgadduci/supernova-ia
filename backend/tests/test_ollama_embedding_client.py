import logging
import unittest
from typing import Any
from unittest import mock

import requests

from backend.config.settings import Settings
from backend.llm.embedding_client import (
    EmbeddingClientProtocol,
    EmbeddingConnectionError,
    EmbeddingDimensionError,
    EmbeddingResponseError,
    EmbeddingTimeoutError,
    OllamaEmbeddingClient,
)
from backend.llm.query_llm import (
    install_llm_timing_recorder,
    reset_llm_timing_recorder,
)


def _vector(value: float) -> list[float]:
    return [float(value)] * 4


def _settings(**overrides) -> Settings:
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
        "embedding_model": "test-embed-model",
        "embedding_timeout_seconds": 15,
        "embedding_batch_size": 2,
        "embedding_dimension": 4,
    }
    base.update(overrides)
    return Settings(**base)


def _ok_response(vectors: list[list[float]], status_code: int = 200) -> mock.Mock:
    response = mock.Mock()
    response.status_code = status_code
    response.json.return_value = {"embeddings": vectors}
    response.raise_for_status.return_value = None
    return response


class EmbeddingClientProtocolConformanceTest(unittest.TestCase):
    def test_ollama_client_satisfies_protocol_methods(self):
        client = OllamaEmbeddingClient(settings=_settings())
        embed_query = getattr(EmbeddingClientProtocol, "embed_query", None)
        embed_documents = getattr(EmbeddingClientProtocol, "embed_documents", None)
        self.assertTrue(callable(embed_query))
        self.assertTrue(callable(embed_documents))
        self.assertTrue(hasattr(client, "embed_query"))
        self.assertTrue(hasattr(client, "embed_documents"))


class OllamaEmbeddingClientPayloadTest(unittest.TestCase):
    def test_embed_query_payload_uses_configured_settings(self):
        captured: dict[str, object] = {}

        def transport(url, **kwargs):
            captured["url"] = url
            captured["payload"] = kwargs.get("json")
            captured["timeout"] = kwargs.get("timeout")
            return _ok_response([_vector(1.0)])

        settings = _settings()
        client = OllamaEmbeddingClient(settings=settings, transport=transport)
        result = client.embed_query("hola")

        self.assertEqual(captured["url"], settings.embedding_url)
        self.assertEqual(captured["timeout"], settings.embedding_timeout_seconds)
        payload = captured["payload"]
        assert isinstance(payload, dict)
        self.assertEqual(payload["model"], settings.embedding_model)
        assert isinstance(payload["input"], list)
        self.assertEqual(payload["input"], ["hola"])
        self.assertEqual(result, _vector(1.0))

    def test_real_transport_uses_configured_proxy(self):
        settings = _settings(ollama_proxy_url="socks5h://127.0.0.1:1055")
        with mock.patch(
            "requests.post", return_value=_ok_response([_vector(1.0)])
        ) as post:
            OllamaEmbeddingClient(settings=settings).embed_query("hola")
        self.assertEqual(
            post.call_args.kwargs["proxies"],
            {"http": "socks5h://127.0.0.1:1055", "https": "socks5h://127.0.0.1:1055"},
        )

    def test_real_transport_uses_loopback_http_proxy(self):
        settings = _settings(ollama_proxy_url="http://127.0.0.1:1056")
        with mock.patch(
            "requests.post", return_value=_ok_response([_vector(1.0)])
        ) as post:
            OllamaEmbeddingClient(settings=settings).embed_query("hola")
        self.assertEqual(
            post.call_args.kwargs["proxies"],
            {"http": "http://127.0.0.1:1056", "https": "http://127.0.0.1:1056"},
        )

    def test_real_transport_has_no_proxy_when_unset(self):
        with mock.patch(
            "requests.post", return_value=_ok_response([_vector(1.0)])
        ) as post:
            OllamaEmbeddingClient(settings=_settings()).embed_query("hola")
        self.assertNotIn("proxies", post.call_args.kwargs)

    def test_injected_transport_does_not_receive_proxy_keyword(self):
        transport = mock.Mock(return_value=_ok_response([_vector(1.0)]))
        OllamaEmbeddingClient(
            settings=_settings(ollama_proxy_url="socks5h://127.0.0.1:1055"),
            transport=transport,
        ).embed_query("hola")
        self.assertNotIn("proxies", transport.call_args.kwargs)

    def test_injected_transport_does_not_receive_http_proxy_keyword(self):
        transport = mock.Mock(return_value=_ok_response([_vector(1.0)]))
        OllamaEmbeddingClient(
            settings=_settings(ollama_proxy_url="http://127.0.0.1:1056"),
            transport=transport,
        ).embed_query("hola")
        self.assertNotIn("proxies", transport.call_args.kwargs)

    def test_request_does_not_mutate_settings(self):
        settings = _settings()
        transport = mock.Mock(return_value=_ok_response([_vector(1.0)]))
        client = OllamaEmbeddingClient(settings=settings, transport=transport)
        before_model = settings.embedding_model
        client.embed_query("uno")
        client.embed_query("dos")
        self.assertEqual(settings.embedding_model, before_model)
        self.assertEqual(transport.call_count, 2)
        first_payload = transport.call_args_list[0].kwargs["json"]
        second_payload = transport.call_args_list[1].kwargs["json"]
        self.assertIsNot(first_payload, second_payload)

    def test_embed_documents_payload_shape(self):
        captured: list[dict[str, object]] = []

        def transport(url, **kwargs):
            captured.append(
                {
                    "url": url,
                    "payload": kwargs.get("json"),
                    "timeout": kwargs.get("timeout"),
                }
            )
            submitted = kwargs["json"]["input"]
            return _ok_response([_vector(float(i)) for i in range(len(submitted))])

        settings = _settings(embedding_batch_size=3)
        client = OllamaEmbeddingClient(settings=settings, transport=transport)
        result = client.embed_documents(["a", "b", "c"])

        first_capture = captured[0]
        self.assertEqual(first_capture["url"], settings.embedding_url)
        self.assertEqual(first_capture["timeout"], settings.embedding_timeout_seconds)
        first_payload = first_capture["payload"]
        assert isinstance(first_payload, dict)
        self.assertEqual(first_payload["model"], settings.embedding_model)
        assert isinstance(first_payload["input"], list)
        self.assertEqual(first_payload["input"], ["a", "b", "c"])
        self.assertEqual(
            result,
            [_vector(0.0), _vector(1.0), _vector(2.0)],
        )


class OllamaEmbeddingClientBatchTest(unittest.TestCase):
    def test_documents_are_chunked_by_batch_size(self):
        calls: list[list[str]] = []

        def transport(url, **kwargs):
            payload = kwargs["json"]
            chunk = list(payload["input"])
            calls.append(chunk)
            return _ok_response([_vector(float(i)) for i in range(len(chunk))])

        settings = _settings(embedding_batch_size=2)
        client = OllamaEmbeddingClient(settings=settings, transport=transport)
        result = client.embed_documents(["a", "b", "c", "d", "e"])

        self.assertEqual(calls, [["a", "b"], ["c", "d"], ["e"]])
        self.assertEqual(len(result), 5)
        expected = [
            _vector(0.0),  # a
            _vector(1.0),  # b
            _vector(0.0),  # c (chunk re-indexed within second request)
            _vector(1.0),  # d
            _vector(0.0),  # e
        ]
        self.assertEqual(result, expected)

    def test_documents_returned_in_original_order_across_batches(self):
        def transport(url, **kwargs):
            payload = kwargs["json"]
            chunk = list(payload["input"])
            # Force shuffling in the per-chunk order to ensure client re-orders.
            return _ok_response(
                [_vector(100.0 + float(i)) for i in range(len(chunk))]
            )

        settings = _settings(embedding_batch_size=2)
        client = OllamaEmbeddingClient(settings=settings, transport=transport)
        result = client.embed_documents(["a", "b", "c", "d"])

        # Order follows input order, not per-chunk response order.
        self.assertEqual(result[0], _vector(100.0))
        self.assertEqual(result[1], _vector(101.0))
        self.assertEqual(result[2], _vector(100.0))
        self.assertEqual(result[3], _vector(101.0))

    def test_batch_failure_raises_without_partial_results(self):
        def transport(url, **kwargs):
            payload = kwargs["json"]
            chunk = list(payload["input"])
            if len(chunk) == 2:
                raise requests.exceptions.ConnectionError("nope")
            return _ok_response([_vector(float(i)) for i in range(len(chunk))])

        settings = _settings(embedding_batch_size=2)
        client = OllamaEmbeddingClient(settings=settings, transport=transport)
        with self.assertRaises(EmbeddingConnectionError):
            client.embed_documents(["a", "b", "c", "d"])


class OllamaEmbeddingClientInputValidationTest(unittest.TestCase):
    def test_empty_query_raises_value_error_without_calling_transport(self):
        transport = mock.Mock()
        client = OllamaEmbeddingClient(settings=_settings(), transport=transport)
        with self.assertRaises(ValueError):
            client.embed_query("")
        transport.assert_not_called()

    def test_whitespace_only_query_raises_value_error(self):
        transport = mock.Mock()
        client = OllamaEmbeddingClient(settings=_settings(), transport=transport)
        with self.assertRaises(ValueError):
            client.embed_query("   \n")
        transport.assert_not_called()

    def test_non_string_query_raises_value_error(self):
        transport = mock.Mock()
        client = OllamaEmbeddingClient(settings=_settings(), transport=transport)
        with self.assertRaises(ValueError):
            client.embed_query(None)  # type: ignore[arg-type]
        transport.assert_not_called()

    def test_empty_documents_returns_empty_list_without_calling_transport(self):
        transport = mock.Mock()
        client = OllamaEmbeddingClient(settings=_settings(), transport=transport)
        self.assertEqual(client.embed_documents([]), [])
        transport.assert_not_called()

    def test_non_list_documents_raises_value_error_without_calling_transport(self):
        transport = mock.Mock()
        client = OllamaEmbeddingClient(settings=_settings(), transport=transport)
        with self.assertRaises(ValueError):
            client.embed_documents("a")  # type: ignore[arg-type]
        transport.assert_not_called()

    def test_empty_document_in_collection_raises_indexed_value_error(self):
        transport = mock.Mock()
        client = OllamaEmbeddingClient(settings=_settings(), transport=transport)
        with self.assertRaises(ValueError) as ctx:
            client.embed_documents(["ok", "", "ok2"])
        self.assertIn("index 1", str(ctx.exception))
        transport.assert_not_called()

    def test_whitespace_document_in_collection_raises_indexed_value_error(self):
        transport = mock.Mock()
        client = OllamaEmbeddingClient(settings=_settings(), transport=transport)
        with self.assertRaises(ValueError) as ctx:
            client.embed_documents(["ok", "   \n", "ok2"])
        self.assertIn("index 1", str(ctx.exception))
        transport.assert_not_called()

    def test_non_string_document_raises_indexed_value_error(self):
        transport = mock.Mock()
        client = OllamaEmbeddingClient(settings=_settings(), transport=transport)
        with self.assertRaises(ValueError) as ctx:
            client.embed_documents(["ok", 123, "ok2"])  # type: ignore[list-item]
        self.assertIn("(index=1)", str(ctx.exception))
        transport.assert_not_called()


class OllamaEmbeddingClientResponseValidationTest(unittest.TestCase):
    def _client(self, transport, **overrides):
        return OllamaEmbeddingClient(settings=_settings(**overrides), transport=transport)

    def test_malformed_json_raises_response_error(self):
        response = mock.Mock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.side_effect = ValueError("nope")
        transport = mock.Mock(return_value=response)
        with self.assertRaises(EmbeddingResponseError) as ctx:
            self._client(transport).embed_query("hola")
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_response_without_embeddings_list_raises_response_error(self):
        transport = mock.Mock(return_value=_ok_response_obj({"foo": "bar"}))
        with self.assertRaises(EmbeddingResponseError) as ctx:
            self._client(transport).embed_query("hola")
        self.assertIn("embeddings", str(ctx.exception))

    def test_response_with_wrong_count_raises_response_error(self):
        transport = mock.Mock(return_value=_ok_response_obj({"embeddings": [_vector(1.0)]}))
        with self.assertRaises(EmbeddingResponseError) as ctx:
            self._client(transport).embed_documents(["a", "b"])
        self.assertIn("count mismatch", str(ctx.exception))

    def test_empty_vector_entry_raises_response_error(self):
        transport = mock.Mock(
            return_value=_ok_response_obj({"embeddings": [[]]})
        )
        with self.assertRaises(EmbeddingDimensionError):
            self._client(transport).embed_query("hola")

    def test_non_list_vector_entry_raises_response_error(self):
        transport = mock.Mock(
            return_value=_ok_response_obj({"embeddings": ["not-a-list"]})
        )
        with self.assertRaises(EmbeddingResponseError) as ctx:
            self._client(transport).embed_query("hola")
        self.assertIn("must be a list", str(ctx.exception))

    def test_wrong_vector_length_raises_dimension_error(self):
        transport = mock.Mock(
            return_value=_ok_response_obj({"embeddings": [[1.0, 2.0, 3.0]]})
        )
        with self.assertRaises(EmbeddingDimensionError) as ctx:
            self._client(transport).embed_query("hola")
        self.assertEqual(ctx.exception.expected_dimension, 4)
        self.assertEqual(ctx.exception.actual_dimension, 3)

    def test_non_numeric_vector_value_raises_response_error(self):
        transport = mock.Mock(
            return_value=_ok_response_obj({"embeddings": [[1.0, "x", 3.0, 4.0]]})
        )
        with self.assertRaises(EmbeddingResponseError) as ctx:
            self._client(transport).embed_query("hola")
        self.assertIn("invalid value", str(ctx.exception))

    def test_boolean_vector_value_raises_response_error(self):
        transport = mock.Mock(
            return_value=_ok_response_obj(
                {"embeddings": [[True, False, True, False]]}
            )
        )
        with self.assertRaises(EmbeddingResponseError):
            self._client(transport).embed_query("hola")

    def test_nan_vector_value_raises_response_error(self):
        transport = mock.Mock(
            return_value=_ok_response_obj(
                {"embeddings": [[float("nan"), 1.0, 2.0, 3.0]]}
            )
        )
        with self.assertRaises(EmbeddingResponseError):
            self._client(transport).embed_query("hola")

    def test_infinite_vector_value_raises_response_error(self):
        transport = mock.Mock(
            return_value=_ok_response_obj(
                {"embeddings": [[float("inf"), 1.0, 2.0, 3.0]]}
            )
        )
        with self.assertRaises(EmbeddingResponseError):
            self._client(transport).embed_query("hola")


class OllamaEmbeddingClientExceptionMappingTest(unittest.TestCase):
    def _client(self, transport, **overrides):
        return OllamaEmbeddingClient(settings=_settings(**overrides), transport=transport)

    def test_timeout_raises_timeout_error(self):
        def transport(url, **kwargs):
            raise requests.exceptions.Timeout("slow")

        with self.assertRaises(EmbeddingTimeoutError):
            self._client(transport).embed_query("hola")

    def test_connection_error_raises_connection_error(self):
        def transport(url, **kwargs):
            raise requests.exceptions.ConnectionError("nope")

        with self.assertRaises(EmbeddingConnectionError):
            self._client(transport).embed_query("hola")

    def test_http_error_raises_response_error_with_status(self):
        response = mock.Mock()
        response.status_code = 503
        err = requests.exceptions.HTTPError("503 error")
        err.response = response
        response.raise_for_status.side_effect = err
        transport = mock.Mock(return_value=response)
        with self.assertRaises(EmbeddingResponseError) as ctx:
            self._client(transport).embed_query("hola")
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("non-success", str(ctx.exception))

    def test_unexpected_request_failure_is_wrapped(self):
        def transport(url, **kwargs):
            raise RuntimeError("transport exploded")

        with self.assertRaises(EmbeddingResponseError) as ctx:
            self._client(transport).embed_query("hola")
        self.assertIn("unexpected", str(ctx.exception))

    def test_subclass_relationships(self):
        self.assertTrue(
            issubclass(EmbeddingConnectionError, Exception)
        )
        from backend.llm.embedding_client import EmbeddingClientError

        self.assertTrue(issubclass(EmbeddingConnectionError, EmbeddingClientError))
        self.assertTrue(issubclass(EmbeddingTimeoutError, EmbeddingClientError))
        self.assertTrue(issubclass(EmbeddingResponseError, EmbeddingClientError))
        self.assertTrue(issubclass(EmbeddingDimensionError, EmbeddingClientError))

    def test_error_messages_omit_input_texts_and_vectors(self):
        def transport(url, **kwargs):
            raise requests.exceptions.ConnectionError("super-secret-text")

        client = self._client(transport)
        try:
            client.embed_query("super-secret-text")
        except EmbeddingConnectionError as exc:
            message = str(exc)
            self.assertNotIn("super-secret-text", message)
            self.assertNotIn("super-secret", message)


class OllamaEmbeddingClientLoggingTest(unittest.TestCase):
    def test_info_logs_carry_metadata_without_input_text(self):
        settings = _settings()
        transport = mock.Mock(return_value=_ok_response([_vector(1.0)]))
        client = OllamaEmbeddingClient(settings=settings, transport=transport)
        with self.assertLogs("backend.llm.embedding_client", level="INFO") as captured:
            client.embed_query("super-secret-query")
        joined = "\n".join(captured.output)
        self.assertIn("embedding query start", joined)
        self.assertIn(settings.embedding_model, joined)
        self.assertIn("embedding query success", joined)
        self.assertNotIn("super-secret-query", joined)

    def test_module_does_not_configure_global_logging(self):
        before = list(logging.getLogger().handlers)
        from backend.llm import embedding_client as _reimport  # noqa: F401

        after = list(logging.getLogger().handlers)
        self.assertEqual(before, after)


class OllamaEmbeddingClientRealServerSmokeTest(unittest.TestCase):
    """Opt-in smoke test against a real local Ollama server.

    Skipped unless ``RUN_OLLAMA_SMOKE=1`` is set in the environment so the
    unit-test run remains deterministic and offline. Always asserts that the
    configured dimension matches the returned vector length.
    """

    def test_real_ollama_returns_configured_dimension(self):
        import os

        if os.environ.get("RUN_OLLAMA_SMOKE") != "1":
            self.skipTest("set RUN_OLLAMA_SMOKE=1 to run the real-Ollama smoke test")

        client = OllamaEmbeddingClient()
        try:
            vector = client.embed_query("hello world")
        except EmbeddingResponseError as exc:
            self.skipTest(f"local Ollama unavailable: {exc}")
        except EmbeddingConnectionError as exc:
            self.skipTest(f"local Ollama unavailable: {exc}")
        except EmbeddingTimeoutError as exc:
            self.skipTest(f"local Ollama unavailable: {exc}")
        self.assertEqual(len(vector), client._settings.embedding_dimension)


def _ok_response_obj(payload, status_code: int = 200) -> mock.Mock:
    response = mock.Mock()
    response.status_code = status_code
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


class EmbeddingProviderCorrelationTest(unittest.TestCase):
    """When the provider coordinator installs the safe synthetic
    inbound correlation value, every ``embedding_request`` event
    emitted from the same thread MUST carry the same opaque
    identifier.

    Direct non-provider callers that do NOT install a recorder
    MUST continue to emit uncorrelated ``embedding_request``
    events so the bounded production-log parser can separate
    provider turns from background probes.
    """

    def setUp(self) -> None:
        reset_llm_timing_recorder()

    def tearDown(self) -> None:
        reset_llm_timing_recorder()

    def _capture_emit_events(self) -> tuple[list[dict], Any]:
        captured: list[dict] = []

        def _capture(*, event: str, **kwargs: object) -> bool:
            from backend.observability.events import build_event

            payload = build_event(event=event, **kwargs)
            captured.append(payload)
            return True

        return captured, _capture

    def test_embed_query_emits_correlation_id_when_recorder_installed(
        self,
    ) -> None:
        captured, capture_fn = self._capture_emit_events()
        client = OllamaEmbeddingClient(
            settings=_settings(),
            transport=mock.Mock(return_value=_ok_response([_vector(1.0)])),
        )
        install_llm_timing_recorder(
            mock.Mock(), correlation_id="SYN-EMB-1"
        )
        try:
            with mock.patch(
                "backend.llm.embedding_client.emit_event",
                side_effect=capture_fn,
            ):
                client.embed_query("hola")
        finally:
            reset_llm_timing_recorder()

        self.assertEqual(len(captured), 2)
        self.assertEqual(captured[0]["event"], "embedding_request")
        self.assertEqual(captured[0]["outcome"], "started")
        self.assertEqual(
            captured[0]["correlation_id"], "SYN-EMB-1"
        )
        self.assertEqual(captured[1]["event"], "embedding_request")
        self.assertEqual(captured[1]["outcome"], "completed")
        self.assertEqual(
            captured[1]["correlation_id"], "SYN-EMB-1"
        )

    def test_embed_query_emits_no_correlation_when_recorder_unset(
        self,
    ) -> None:
        captured, capture_fn = self._capture_emit_events()
        client = OllamaEmbeddingClient(
            settings=_settings(),
            transport=mock.Mock(return_value=_ok_response([_vector(1.0)])),
        )
        with mock.patch(
            "backend.llm.embedding_client.emit_event",
            side_effect=capture_fn,
        ):
            client.embed_query("hola")

        self.assertEqual(len(captured), 2)
        self.assertNotIn("correlation_id", captured[0])
        self.assertNotIn("correlation_id", captured[1])

    def test_embedding_failure_emits_correlation_id(self) -> None:
        captured, capture_fn = self._capture_emit_events()

        def _boom(url, **kwargs):
            raise requests.exceptions.Timeout("slow")

        client = OllamaEmbeddingClient(
            settings=_settings(), transport=_boom
        )
        install_llm_timing_recorder(
            mock.Mock(), correlation_id="SYN-EMB-2"
        )
        try:
            with mock.patch(
                "backend.llm.embedding_client.emit_event",
                side_effect=capture_fn,
            ):
                with self.assertRaises(EmbeddingTimeoutError):
                    client.embed_query("hola")
        finally:
            reset_llm_timing_recorder()

        self.assertEqual(len(captured), 2)
        self.assertEqual(captured[0]["correlation_id"], "SYN-EMB-2")
        self.assertEqual(captured[1]["correlation_id"], "SYN-EMB-2")
        self.assertEqual(captured[1]["failure_category"], "timeout")

    def test_embed_documents_propagates_correlation_per_batch(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        client = OllamaEmbeddingClient(
            settings=_settings(embedding_batch_size=1),
            transport=mock.Mock(
                side_effect=[
                    _ok_response([_vector(1.0)]),
                    _ok_response([_vector(2.0)]),
                ]
            ),
        )
        install_llm_timing_recorder(
            mock.Mock(), correlation_id="SYN-EMB-3"
        )
        try:
            with mock.patch(
                "backend.llm.embedding_client.emit_event",
                side_effect=capture_fn,
            ):
                client.embed_documents(["a", "b"])
        finally:
            reset_llm_timing_recorder()

        self.assertEqual(len(captured), 4)
        for event in captured:
            self.assertEqual(event["correlation_id"], "SYN-EMB-3")

    def test_correlation_id_cleared_after_reset(self) -> None:
        captured, capture_fn = self._capture_emit_events()
        client = OllamaEmbeddingClient(
            settings=_settings(),
            transport=mock.Mock(return_value=_ok_response([_vector(1.0)])),
        )
        install_llm_timing_recorder(
            mock.Mock(), correlation_id="SYN-EMB-4"
        )
        with mock.patch(
            "backend.llm.embedding_client.emit_event",
            side_effect=capture_fn,
        ):
            client.embed_query("hola")
        reset_llm_timing_recorder()
        with mock.patch(
            "backend.llm.embedding_client.emit_event",
            side_effect=capture_fn,
        ):
            client.embed_query("hola")
        # First call: correlation_id present.
        self.assertEqual(
            captured[0]["correlation_id"], "SYN-EMB-4"
        )
        self.assertEqual(
            captured[1]["correlation_id"], "SYN-EMB-4"
        )
        # Second call (after reset): correlation_id absent.
        self.assertNotIn("correlation_id", captured[2])
        self.assertNotIn("correlation_id", captured[3])


if __name__ == "__main__":
    unittest.main()
