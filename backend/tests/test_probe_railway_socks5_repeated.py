import io
import math
import sys
import unittest
from unittest import mock

import requests

from backend.config.settings import Settings
from backend.scripts import probe_railway_socks5_repeated as probe


def _settings(**overrides) -> Settings:
    base = {
        "llm_url": "http://llm.test/api/generate",
        "llm_model": "test-model",
        "llm_timeout": 30,
        "llm_keep_alive": "1h",
        "llm_num_ctx": 2048,
        "llm_num_predict": 256,
        "llm_log_content": False,
        "llm_log_max_chars": 50,
        "ollama_proxy_url": "socks5h://127.0.0.1:1055",
    }
    base.update(overrides)
    return Settings(**base)


class _FakeResponse:
    def __init__(
        self,
        body: bytes = b"ok",
        status_code: int = 200,
    ) -> None:
        self._body = body
        self.status_code = status_code
        self.content = body
        self.text = body.decode("utf-8") if body else ""
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def iter_content(self, chunk_size: int = 8192):
        yield self._body


class ProbeConstantsTest(unittest.TestCase):
    def test_modes_and_defaults_match_spec(self):
        self.assertEqual(probe._MODE_FRESH, "fresh")
        self.assertEqual(probe._MODE_SESSION, "session")
        self.assertEqual(probe._DEFAULT_COUNT, 10)
        self.assertEqual(probe._DEFAULT_CONNECT_TIMEOUT_SECONDS, 5)
        self.assertEqual(probe._DEFAULT_READ_TIMEOUT_SECONDS, 20)
        self.assertEqual(probe._ALLOWED_MODES, ("fresh", "session"))


class ProbeArgumentValidationTest(unittest.TestCase):
    def test_default_parser_values(self):
        args = probe._build_parser().parse_args([])
        self.assertEqual(args.mode, "fresh")
        self.assertEqual(args.count, 10)
        self.assertEqual(args.connect_timeout_seconds, 5.0)
        self.assertEqual(args.read_timeout_seconds, 20.0)

    def test_count_zero_or_negative_exits_with_two(self):
        for value in ("0", "-1"):
            with self.subTest(value=value):
                with mock.patch("sys.stderr", io.StringIO()):
                    with self.assertRaises(SystemExit) as ctx:
                        probe._build_parser().parse_args(["--count", value])
                self.assertEqual(ctx.exception.code, 2)

    def test_count_non_integer_exits_with_two(self):
        with mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                probe._build_parser().parse_args(["--count", "abc"])
        self.assertEqual(ctx.exception.code, 2)

    def test_connect_timeout_must_be_positive_finite(self):
        for value in ("0", "-1", "nan", "inf", "-inf"):
            with self.subTest(value=value):
                with mock.patch("sys.stderr", io.StringIO()):
                    with self.assertRaises(SystemExit) as ctx:
                        probe._build_parser().parse_args(
                            ["--connect-timeout-seconds", value]
                        )
                self.assertEqual(ctx.exception.code, 2)

    def test_read_timeout_must_be_positive_finite(self):
        for value in ("0", "-1", "nan", "inf"):
            with self.subTest(value=value):
                with mock.patch("sys.stderr", io.StringIO()):
                    with self.assertRaises(SystemExit) as ctx:
                        probe._build_parser().parse_args(
                            ["--read-timeout-seconds", value]
                        )
                self.assertEqual(ctx.exception.code, 2)

    def test_mode_invalid_value_exits_with_two(self):
        with mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                probe._build_parser().parse_args(["--mode", "bogus"])
        self.assertEqual(ctx.exception.code, 2)

    def test_invalid_arguments_do_not_create_requests_or_session(self):
        with mock.patch("sys.stderr", io.StringIO()):
            with mock.patch.object(
                probe.requests, "post"
            ) as post_mock, mock.patch.object(
                probe.requests, "Session"
            ) as session_mock:
                with self.assertRaises(SystemExit):
                    probe._build_parser().parse_args(["--count", "-1"])
        post_mock.assert_not_called()
        session_mock.assert_not_called()


class ProbeRunProbeValidationTest(unittest.TestCase):
    def test_run_probe_validates_arguments_before_any_call(self):
        with self.assertRaises(ValueError):
            probe.run_probe(
                mode="fresh",
                count=0,
                connect_timeout_seconds=5,
                read_timeout_seconds=20,
                settings_factory=lambda: _settings(),
            )

    def test_run_probe_rejects_negative_connect_timeout(self):
        with self.assertRaises(ValueError):
            probe.run_probe(
                mode="fresh",
                count=1,
                connect_timeout_seconds=-1,
                read_timeout_seconds=20,
                settings_factory=lambda: _settings(),
            )

    def test_run_probe_rejects_non_finite_read_timeout(self):
        with self.assertRaises(ValueError):
            probe.run_probe(
                mode="fresh",
                count=1,
                connect_timeout_seconds=5,
                read_timeout_seconds=math.nan,
                settings_factory=lambda: _settings(),
            )


class ProbeFreshModeTest(unittest.TestCase):
    def test_fresh_mode_invokes_top_level_post_for_every_attempt(self):
        calls: list[dict] = []

        def _post(url, **kwargs):
            calls.append({"url": url, **kwargs})
            return _FakeResponse()

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests, "post", side_effect=_post
        ):
            exit_code, records = probe.run_probe(
                mode="fresh",
                count=3,
                connect_timeout_seconds=2,
                read_timeout_seconds=4,
                settings_factory=lambda: _settings(),
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(records), 3)
        for call in calls:
            self.assertEqual(call["url"], "http://llm.test/api/generate")
            self.assertEqual(call["timeout"], (2.0, 4.0))
            self.assertEqual(
                call["proxies"],
                {
                    "http": "socks5h://127.0.0.1:1055",
                    "https": "socks5h://127.0.0.1:1055",
                },
            )
            self.assertIn("json", call)

    def test_fresh_mode_does_not_create_session(self):
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests, "post", return_value=_FakeResponse()
        ), mock.patch.object(
            probe.requests, "Session"
        ) as session_mock:
            probe.run_probe(
                mode="fresh",
                count=2,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: _settings(),
            )
        session_mock.assert_not_called()


class ProbeSessionModeTest(unittest.TestCase):
    def test_session_mode_uses_one_session_for_all_attempts(self):
        session = mock.Mock()
        session.post.return_value = _FakeResponse()

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests, "Session", return_value=session
        ):
            exit_code, records = probe.run_probe(
                mode="session",
                count=4,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: _settings(),
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(records and len(records), 4)
        self.assertEqual(session.post.call_count, 4)
        self.assertEqual(session.close.call_count, 1)
        session.close.assert_called_once()

    def test_session_mode_closes_each_response(self):
        session = mock.Mock()
        responses = [_FakeResponse(), _FakeResponse(), _FakeResponse()]
        session.post.side_effect = responses

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests, "Session", return_value=session
        ):
            probe.run_probe(
                mode="session",
                count=3,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: _settings(),
            )
        for response in responses:
            self.assertTrue(response.closed)

    def test_session_mode_does_not_use_top_level_post(self):
        session = mock.Mock()
        session.post.return_value = _FakeResponse()

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests, "Session", return_value=session
        ), mock.patch.object(
            probe.requests, "post"
        ) as post_mock:
            probe.run_probe(
                mode="session",
                count=2,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: _settings(),
            )
        post_mock.assert_not_called()


class ProbeProxyPropagationTest(unittest.TestCase):
    def test_fresh_mode_propagates_configured_proxy(self):
        captured: dict = {}

        def _post(url, **kwargs):
            captured.update(kwargs)
            return _FakeResponse()

        settings = _settings(ollama_proxy_url="socks5h://user:pwd@127.0.0.1:1055")
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests, "post", side_effect=_post
        ):
            probe.run_probe(
                mode="fresh",
                count=1,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: settings,
            )
        self.assertEqual(
            captured["proxies"],
            {
                "http": "socks5h://user:pwd@127.0.0.1:1055",
                "https": "socks5h://user:pwd@127.0.0.1:1055",
            },
        )

    def test_session_mode_propagates_configured_proxy(self):
        session = mock.Mock()
        session.post.return_value = _FakeResponse()
        settings = _settings(ollama_proxy_url="socks5h://user:pwd@127.0.0.1:1055")

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests, "Session", return_value=session
        ):
            probe.run_probe(
                mode="session",
                count=1,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: settings,
            )
        self.assertEqual(
            session.post.call_args.kwargs["proxies"],
            {
                "http": "socks5h://user:pwd@127.0.0.1:1055",
                "https": "socks5h://user:pwd@127.0.0.1:1055",
            },
        )


class ProbeTimeoutTupleTest(unittest.TestCase):
    def test_timeout_is_passed_as_tuple(self):
        captured: list[tuple] = []

        def _post(url, **kwargs):
            captured.append(kwargs["timeout"])
            return _FakeResponse()

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests, "post", side_effect=_post
        ):
            probe.run_probe(
                mode="fresh",
                count=2,
                connect_timeout_seconds=3,
                read_timeout_seconds=7,
                settings_factory=lambda: _settings(),
            )
        for value in captured:
            self.assertIsInstance(value, tuple)
            self.assertEqual(len(value), 2)
            self.assertEqual(value, (3.0, 7.0))


class ProbeSequentialCallsTest(unittest.TestCase):
    def test_attempts_are_sequential(self):
        order: list[int] = []

        def _post(url, **kwargs):
            order.append(len(order) + 1)
            return _FakeResponse()

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests, "post", side_effect=_post
        ):
            probe.run_probe(
                mode="fresh",
                count=5,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: _settings(),
            )
        self.assertEqual(order, [1, 2, 3, 4, 5])

    def test_session_mode_sequential_attempts(self):
        order: list[int] = []
        session = mock.Mock()

        def _post(url, **kwargs):
            order.append(len(order) + 1)
            return _FakeResponse()

        session.post.side_effect = _post
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests, "Session", return_value=session
        ):
            probe.run_probe(
                mode="session",
                count=3,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: _settings(),
            )
        self.assertEqual(order, [1, 2, 3])


class ProbeOutcomeTest(unittest.TestCase):
    def test_success_outcome_when_http_ok_and_bytes_received(self):
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests, "post", return_value=_FakeResponse(body=b"hello")
        ):
            exit_code, records = probe.run_probe(
                mode="fresh",
                count=1,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: _settings(),
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(records[0]["outcome"], probe._OUTCOME_SUCCESS)
        self.assertEqual(records[0]["received_bytes"], 5)
        self.assertEqual(records[0]["http_status"], 200)
        self.assertEqual(records[0]["phase"], probe._PHASE_RETURNED)

    def test_empty_response_outcome_when_zero_bytes(self):
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests, "post", return_value=_FakeResponse(body=b"")
        ):
            exit_code, records = probe.run_probe(
                mode="fresh",
                count=1,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: _settings(),
            )
        self.assertEqual(exit_code, 1)
        self.assertEqual(records[0]["outcome"], probe._OUTCOME_EMPTY_RESPONSE)

    def test_http_status_outcome_when_non_2xx(self):
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests,
            "post",
            return_value=_FakeResponse(body=b"err", status_code=503),
        ):
            exit_code, records = probe.run_probe(
                mode="fresh",
                count=1,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: _settings(),
            )
        self.assertEqual(exit_code, 1)
        self.assertEqual(records[0]["outcome"], probe._OUTCOME_HTTP_STATUS)
        self.assertEqual(records[0]["http_status"], 503)

    def test_connect_timeout_classification(self):
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests,
            "post",
            side_effect=requests.exceptions.ConnectTimeout("super-secret-leak"),
        ):
            exit_code, records = probe.run_probe(
                mode="fresh",
                count=1,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: _settings(),
            )
        self.assertEqual(exit_code, 1)
        record = records[0]
        self.assertEqual(record["outcome"], probe._OUTCOME_CONNECT_TIMEOUT)
        self.assertEqual(record["exception_class"], "ConnectTimeout")
        self.assertEqual(record["phase"], probe._PHASE_EXCEPTION)
        self.assertNotIn("super-secret-leak", stdout.getvalue())

    def test_read_timeout_classification(self):
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests,
            "post",
            side_effect=requests.exceptions.ReadTimeout("super-secret-leak"),
        ):
            exit_code, records = probe.run_probe(
                mode="fresh",
                count=1,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: _settings(),
            )
        self.assertEqual(exit_code, 1)
        record = records[0]
        self.assertEqual(record["outcome"], probe._OUTCOME_READ_TIMEOUT)
        self.assertEqual(record["exception_class"], "ReadTimeout")
        self.assertNotIn("super-secret-leak", stdout.getvalue())

    def test_proxy_error_classification(self):
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests,
            "post",
            side_effect=requests.exceptions.ProxyError("super-secret-leak"),
        ):
            exit_code, records = probe.run_probe(
                mode="fresh",
                count=1,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: _settings(),
            )
        self.assertEqual(exit_code, 1)
        record = records[0]
        self.assertEqual(record["outcome"], probe._OUTCOME_PROXY_ERROR)
        self.assertEqual(record["exception_class"], "ProxyError")
        self.assertNotIn("super-secret-leak", stdout.getvalue())

    def test_connection_error_classification(self):
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests,
            "post",
            side_effect=requests.exceptions.ConnectionError("super-secret-leak"),
        ):
            exit_code, records = probe.run_probe(
                mode="fresh",
                count=1,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: _settings(),
            )
        self.assertEqual(exit_code, 1)
        record = records[0]
        self.assertEqual(record["outcome"], probe._OUTCOME_CONNECTION_ERROR)
        self.assertEqual(record["exception_class"], "ConnectionError")
        self.assertNotIn("super-secret-leak", stdout.getvalue())

    def test_request_error_classification_for_generic_request_exception(self):
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests,
            "post",
            side_effect=requests.exceptions.RequestException("super-secret-leak"),
        ):
            exit_code, records = probe.run_probe(
                mode="fresh",
                count=1,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: _settings(),
            )
        self.assertEqual(exit_code, 1)
        record = records[0]
        self.assertEqual(record["outcome"], probe._OUTCOME_REQUEST_ERROR)
        self.assertIn(record["exception_class"], ("RequestException",))
        self.assertNotIn("super-secret-leak", stdout.getvalue())

    def test_continues_after_failure(self):
        responses = [
            _FakeResponse(body=b"ok"),
            requests.exceptions.ConnectTimeout("super-secret-leak"),
            _FakeResponse(body=b"ok"),
            requests.exceptions.ReadTimeout("super-secret-leak"),
            _FakeResponse(body=b"ok"),
        ]
        indices: list[int] = []

        def _post(url, **kwargs):
            indices.append(len(indices))
            item = responses[len(indices) - 1]
            if isinstance(item, BaseException):
                raise item
            return item

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests, "post", side_effect=_post
        ):
            exit_code, records = probe.run_probe(
                mode="fresh",
                count=5,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: _settings(),
            )
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(records), 5)
        self.assertEqual(indices, [0, 1, 2, 3, 4])
        self.assertEqual(records[0]["outcome"], probe._OUTCOME_SUCCESS)
        self.assertEqual(records[1]["outcome"], probe._OUTCOME_CONNECT_TIMEOUT)
        self.assertEqual(records[2]["outcome"], probe._OUTCOME_SUCCESS)
        self.assertEqual(records[3]["outcome"], probe._OUTCOME_READ_TIMEOUT)
        self.assertEqual(records[4]["outcome"], probe._OUTCOME_SUCCESS)


class ProbeExitCodeTest(unittest.TestCase):
    def test_all_attempts_succeed_returns_zero(self):
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests, "post", return_value=_FakeResponse(body=b"ok")
        ):
            exit_code, _ = probe.run_probe(
                mode="fresh",
                count=3,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: _settings(),
            )
        self.assertEqual(exit_code, 0)

    def test_any_failure_returns_one(self):
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests,
            "post",
            side_effect=[
                _FakeResponse(body=b"ok"),
                requests.exceptions.ConnectTimeout("super-secret-leak"),
                _FakeResponse(body=b"ok"),
            ],
        ):
            exit_code, _ = probe.run_probe(
                mode="fresh",
                count=3,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: _settings(),
            )
        self.assertEqual(exit_code, 1)


class ProbeOutputSafetyTest(unittest.TestCase):
    def test_output_excludes_url_proxy_payload_response_headers_and_exception_text(
        self,
    ):
        def _post(url, **kwargs):
            return _FakeResponse(body=b"super-secret-body-payload")

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests, "post", side_effect=_post
        ):
            probe.run_probe(
                mode="fresh",
                count=1,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: _settings(
                    llm_url="http://super-secret-host.invalid/api/generate",
                    ollama_proxy_url="socks5h://user:pwd@127.0.0.1:1055",
                ),
            )
        out = stdout.getvalue()
        forbidden = (
            "super-secret-body-payload",
            "super-secret-host",
            "127.0.0.1",
            "1055",
            "/api/generate",
            "user:pwd",
            "socks5h",
            "ok",  # response body token
            "Traceback",
        )
        for token in forbidden:
            self.assertNotIn(token, out)

    def test_output_excludes_traceback_and_exception_text_on_failure(self):
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests,
            "post",
            side_effect=requests.exceptions.ConnectTimeout(
                "super-secret-leak-text"
            ),
        ):
            probe.run_probe(
                mode="fresh",
                count=1,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: _settings(
                    llm_url="http://super-secret-host.invalid/api/generate",
                    ollama_proxy_url="socks5h://user:pwd@127.0.0.1:1055",
                ),
            )
        out = stdout.getvalue()
        self.assertNotIn("super-secret-leak-text", out)
        self.assertNotIn("super-secret-host", out)
        self.assertNotIn("user:pwd", out)
        self.assertNotIn("Traceback", out)
        self.assertIn("ConnectTimeout", out)
        self.assertIn("outcome=connect_timeout", out)

    def test_records_do_not_carry_url_proxy_payload_or_exception_text(self):
        def _post(url, **kwargs):
            raise requests.exceptions.ConnectTimeout("super-secret-leak-text")

        records: list[dict] = []
        with mock.patch.object(probe.requests, "post", side_effect=_post):
            _exit_code, records = probe.run_probe(
                mode="fresh",
                count=1,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: _settings(
                    llm_url="http://super-secret-host.invalid/api/generate",
                    ollama_proxy_url="socks5h://user:pwd@127.0.0.1:1055",
                ),
            )
        for record in records:
            serialized = repr(record)
            self.assertNotIn("super-secret-leak-text", serialized)
            self.assertNotIn("super-secret-host", serialized)
            self.assertNotIn("user:pwd", serialized)


class ProbeImportIsolationTest(unittest.TestCase):
    def test_module_does_not_import_banned_backends(self):
        forbidden_prefixes = (
            "backend.llm",
            "backend.routers",
            "backend.services",
            "backend.repositories",
            "backend.intents",
            "backend.models",
            "backend.alembic",
            "backend.dependencies",
            "backend.worker",
            "backend.coordinator",
            "backend.db",
            "backend.sessions",
            "backend.auth",
            "backend.admin",
            "backend.twilio",
            "backend.tailscale",
            "backend.ollama",
            "backend.diagnostics",
            "backend.observability",
            "backend.embeddings",
            "backend.cli",
            "backend.recognizers",
            "backend.abuse_guard",
            "backend.commerce_adapter",
            "backend.schemas",
            "backend.templates",
        )
        violations: list[str] = []
        for value in vars(probe).values():
            mod_name = getattr(value, "__name__", None)
            if not mod_name:
                continue
            for prefix in forbidden_prefixes:
                if mod_name == prefix or mod_name.startswith(prefix + "."):
                    violations.append(mod_name)
                    break
        self.assertEqual(
            violations,
            [],
            f"probe imports banned modules: {violations}",
        )


class ProbeClassifyExceptionTest(unittest.TestCase):
    def test_unknown_exception_maps_to_request_error(self):
        outcome, label = probe._classify_exception(RuntimeError("secret"))
        self.assertEqual(outcome, probe._OUTCOME_REQUEST_ERROR)
        self.assertEqual(label, "RuntimeError")


class ProbeMainEntryPointTest(unittest.TestCase):
    def test_main_returns_zero_when_all_succeed(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            sys, "stderr", stderr
        ), mock.patch.object(
            sys,
            "argv",
            [
                "probe_railway_socks5_repeated",
                "--mode", "fresh",
                "--count", "2",
            ],
        ), mock.patch.object(
            probe.requests, "post", return_value=_FakeResponse(body=b"ok")
        ), mock.patch(
            "backend.scripts.probe_railway_socks5_repeated.load_settings",
            return_value=_settings(),
        ):
            exit_code = probe.main()
        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().count("outcome=success"), 2)

    def test_main_returns_one_when_any_attempt_fails(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            sys, "stderr", stderr
        ), mock.patch.object(
            sys,
            "argv",
            [
                "probe_railway_socks5_repeated",
                "--mode", "session",
                "--count", "2",
            ],
        ), mock.patch.object(
            probe.requests,
            "Session",
            return_value=mock.Mock(post=mock.Mock(side_effect=requests.exceptions.ReadTimeout("super-secret-leak"))),
        ), mock.patch(
            "backend.scripts.probe_railway_socks5_repeated.load_settings",
            return_value=_settings(),
        ):
            exit_code = probe.main()
        self.assertEqual(exit_code, 1)
        self.assertNotIn("super-secret-leak", stdout.getvalue())

    def test_main_returns_two_on_invalid_arguments(self):
        stderr = io.StringIO()
        with mock.patch.object(sys, "stderr", stderr), mock.patch.object(
            sys,
            "argv",
            [
                "probe_railway_socks5_repeated",
                "--count", "-1",
            ],
        ):
            with self.assertRaises(SystemExit) as ctx:
                probe.main()
        self.assertEqual(ctx.exception.code, 2)


class ProbeValidateProxyUrlTest(unittest.TestCase):
    def test_valid_socks5h_url(self):
        self.assertTrue(probe._validate_proxy_url("socks5h://127.0.0.1:1055"))

    def test_valid_socks5h_url_with_credentials(self):
        self.assertTrue(
            probe._validate_proxy_url("socks5h://user:pwd@127.0.0.1:1055")
        )

    def test_valid_http_url(self):
        self.assertTrue(probe._validate_proxy_url("http://proxy.example.com:8080"))

    def test_valid_https_url(self):
        self.assertTrue(probe._validate_proxy_url("https://proxy.example.com:443"))

    def test_none_is_invalid(self):
        self.assertFalse(probe._validate_proxy_url(None))

    def test_empty_string_is_invalid(self):
        self.assertFalse(probe._validate_proxy_url(""))

    def test_whitespace_only_is_invalid(self):
        self.assertFalse(probe._validate_proxy_url("   "))

    def test_invalid_url_is_invalid(self):
        self.assertFalse(probe._validate_proxy_url("not-a-url"))

    def test_unsupported_scheme_is_invalid(self):
        self.assertFalse(probe._validate_proxy_url("ftp://proxy.example.com:21"))

    def test_scheme_only_is_invalid(self):
        self.assertFalse(probe._validate_proxy_url("socks5h://"))

    def test_non_string_is_invalid(self):
        self.assertFalse(probe._validate_proxy_url(12345))
        self.assertFalse(probe._validate_proxy_url(["socks5h://127.0.0.1:1055"]))


class ProbePayloadModelTest(unittest.TestCase):
    def test_payload_uses_settings_llm_model(self):
        captured: list[dict] = []

        def _post(url, **kwargs):
            payload = kwargs.get("json")
            if isinstance(payload, dict):
                captured.append(payload)
            return _FakeResponse()

        settings = _settings(llm_model="custom-llm-model-x")
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests, "post", side_effect=_post
        ):
            exit_code, _ = probe.run_probe(
                mode="fresh",
                count=1,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: settings,
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["model"], "custom-llm-model-x")
        self.assertEqual(captured[0]["prompt"], "ok")
        self.assertEqual(captured[0]["stream"], False)

    def test_payload_model_is_not_printed(self):
        captured: list[dict] = []

        def _post(url, **kwargs):
            payload = kwargs.get("json")
            if isinstance(payload, dict):
                captured.append(payload)
            return _FakeResponse()

        settings = _settings(llm_model="super-secret-model-name")
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests, "post", side_effect=_post
        ):
            probe.run_probe(
                mode="fresh",
                count=2,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: settings,
            )
        self.assertEqual(captured[0]["model"], "super-secret-model-name")
        self.assertNotIn("super-secret-model-name", stdout.getvalue())

    def test_session_mode_payload_uses_settings_llm_model(self):
        captured: list[dict] = []
        session = mock.Mock()

        def _post(url, **kwargs):
            payload = kwargs.get("json")
            if isinstance(payload, dict):
                captured.append(payload)
            return _FakeResponse()

        session.post.side_effect = _post
        settings = _settings(llm_model="custom-llm-model-y")
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests, "Session", return_value=session
        ):
            exit_code, _ = probe.run_probe(
                mode="session",
                count=1,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: settings,
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["model"], "custom-llm-model-y")


class ProbeConfigurationErrorTest(unittest.TestCase):
    def _assert_configuration_error(self, *, settings_value, expected_count=1):
        stdout = io.StringIO()
        settings = _settings(ollama_proxy_url=settings_value)
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests, "post"
        ) as post_mock, mock.patch.object(
            probe.requests, "Session"
        ) as session_mock:
            exit_code, records = probe.run_probe(
                mode="fresh",
                count=2,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: settings,
            )
        self.assertEqual(exit_code, 1)
        post_mock.assert_not_called()
        session_mock.assert_not_called()
        self.assertEqual(len(records), expected_count)
        record = records[0]
        self.assertEqual(record["outcome"], probe._OUTCOME_CONFIGURATION_ERROR)
        self.assertEqual(record["phase"], probe._PHASE_EXCEPTION)
        return stdout.getvalue(), record

    def test_proxy_none_returns_configuration_error_without_http_or_session(self):
        out, record = self._assert_configuration_error(settings_value=None)
        self.assertIn("configuration_error", out)
        self.assertNotIn("Traceback", out)
        self.assertNotIn("llm.test", out)
        self.assertNotIn("api/generate", out)
        self.assertNotIn("127.0.0.1", out)
        self.assertNotIn("socks5h", out)
        self.assertEqual(record["attempt"], probe._CONFIGURATION_ERROR_ATTEMPT)

    def test_proxy_empty_string_returns_configuration_error(self):
        out, _ = self._assert_configuration_error(settings_value="")
        self.assertIn("configuration_error", out)
        self.assertNotIn("Traceback", out)

    def test_proxy_whitespace_returns_configuration_error(self):
        self._assert_configuration_error(settings_value="   ")

    def test_proxy_invalid_url_returns_configuration_error(self):
        self._assert_configuration_error(settings_value="not-a-url")

    def test_proxy_unsupported_scheme_returns_configuration_error(self):
        self._assert_configuration_error(
            settings_value="ftp://proxy.example.com:21"
        )

    def test_proxy_scheme_only_returns_configuration_error(self):
        self._assert_configuration_error(settings_value="socks5h://")

    def test_session_mode_proxy_none_does_not_create_session_or_post(self):
        stdout = io.StringIO()
        settings = _settings(ollama_proxy_url=None)
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests, "post"
        ) as post_mock, mock.patch.object(
            probe.requests, "Session"
        ) as session_mock:
            exit_code, records = probe.run_probe(
                mode="session",
                count=2,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: settings,
            )
        self.assertEqual(exit_code, 1)
        post_mock.assert_not_called()
        session_mock.assert_not_called()
        self.assertEqual(records[0]["outcome"], probe._OUTCOME_CONFIGURATION_ERROR)

    def test_configuration_error_output_excludes_url_proxy_and_secrets(self):
        out, _ = self._assert_configuration_error(
            settings_value=None,
        )
        forbidden = (
            "Traceback",
            "llm.test",
            "api/generate",
            "127.0.0.1",
            "1055",
            "socks5h",
            "user:pwd",
            "secret",
            "error:",
            "Exception",
        )
        for token in forbidden:
            self.assertNotIn(token, out)

    def test_configuration_error_does_not_carry_url_or_exception_text(self):
        settings = _settings(
            ollama_proxy_url=None,
            llm_url="http://super-secret-host.invalid/api/generate",
        )
        with mock.patch.object(probe.requests, "post") as post_mock, mock.patch.object(
            probe.requests, "Session"
        ) as session_mock:
            _exit_code, records = probe.run_probe(
                mode="fresh",
                count=1,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=lambda: settings,
            )
        post_mock.assert_not_called()
        session_mock.assert_not_called()
        for record in records:
            serialized = repr(record)
            self.assertNotIn("super-secret-host", serialized)
            self.assertNotIn("api/generate", serialized)
            self.assertNotIn("127.0.0.1", serialized)


class ProbeLoadSettingsFailureTest(unittest.TestCase):
    def test_load_settings_failure_becomes_configuration_error(self):
        stdout = io.StringIO()

        def _bad_factory():
            raise RuntimeError("super-secret-settings-leak")

        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests, "post"
        ) as post_mock, mock.patch.object(
            probe.requests, "Session"
        ) as session_mock:
            exit_code, records = probe.run_probe(
                mode="fresh",
                count=2,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=_bad_factory,
            )
        self.assertEqual(exit_code, 1)
        post_mock.assert_not_called()
        session_mock.assert_not_called()
        self.assertEqual(records[0]["outcome"], probe._OUTCOME_CONFIGURATION_ERROR)
        self.assertIn("configuration_error", stdout.getvalue())
        self.assertNotIn("super-secret-settings-leak", stdout.getvalue())
        self.assertNotIn("RuntimeError", stdout.getvalue())
        self.assertNotIn("Traceback", stdout.getvalue())

    def test_load_settings_failure_session_mode_does_not_create_session(self):
        stdout = io.StringIO()

        def _bad_factory():
            raise ValueError("super-secret-settings-leak")

        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.requests, "post"
        ) as post_mock, mock.patch.object(
            probe.requests, "Session"
        ) as session_mock:
            exit_code, records = probe.run_probe(
                mode="session",
                count=2,
                connect_timeout_seconds=1,
                read_timeout_seconds=1,
                settings_factory=_bad_factory,
            )
        self.assertEqual(exit_code, 1)
        post_mock.assert_not_called()
        session_mock.assert_not_called()
        self.assertEqual(records[0]["outcome"], probe._OUTCOME_CONFIGURATION_ERROR)
        self.assertNotIn("super-secret-settings-leak", stdout.getvalue())
        self.assertNotIn("Traceback", stdout.getvalue())


class ProbeRecordConfigurationErrorTest(unittest.TestCase):
    def test_record_configuration_error_contains_no_sensitive_fields(self):
        _line, record = probe._record_configuration_error(mode="fresh")
        self.assertEqual(record["mode"], "fresh")
        self.assertEqual(record["attempt"], probe._CONFIGURATION_ERROR_ATTEMPT)
        self.assertEqual(record["phase"], probe._PHASE_EXCEPTION)
        self.assertEqual(record["outcome"], probe._OUTCOME_CONFIGURATION_ERROR)
        self.assertEqual(record["duracion_ms"], probe._CONFIGURATION_ERROR_DURATION_MS)
        self.assertNotIn("http_status", record)
        self.assertNotIn("received_bytes", record)
        self.assertNotIn("exception_class", record)
        serialized = repr(record).lower()
        for forbidden in ("127.0.0.1", "1055", "socks5h", "user:pwd", "secret"):
            self.assertNotIn(forbidden, serialized)

    def test_record_configuration_error_preserves_requested_mode(self):
        for mode_value in ("fresh", "session"):
            with self.subTest(mode=mode_value):
                _line, record = probe._record_configuration_error(mode=mode_value)
                self.assertEqual(record["mode"], mode_value)


class ProbeBuildPayloadTest(unittest.TestCase):
    def test_build_payload_uses_configured_model(self):
        settings = _settings(llm_model="configured-model-name")
        payload = probe._build_payload(settings)
        self.assertEqual(payload["model"], "configured-model-name")
        self.assertEqual(payload["prompt"], "ok")
        self.assertEqual(payload["stream"], False)


if __name__ == "__main__":
    unittest.main()