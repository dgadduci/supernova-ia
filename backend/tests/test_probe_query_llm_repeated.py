import io
import json
import sys
import unittest
from unittest import mock

import requests

from backend.config.settings import Settings
from backend.llm.query_llm import (
    QueryLlm,
    QueryLlmConnectionError,
    QueryLlmHttpError,
    QueryLlmTimeoutError,
)
from backend.scripts import probe_query_llm_repeated as probe


class _FakeResponse:
    def __init__(self, body: str, status_code: int = 200) -> None:
        self._body = body
        self.status_code = status_code
        self.text = body

    def json(self) -> dict:
        return {"response": self._body}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            err = requests.exceptions.HTTPError(f"{self.status_code} error")
            err.response = self  # type: ignore[attr-defined]
            raise err


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
    }
    base.update(overrides)
    return Settings(**base)


class ProbeDefaultsTest(unittest.TestCase):
    def test_module_defaults_match_spec(self):
        self.assertEqual(probe._DEFAULT_COUNT, 10)
        self.assertEqual(probe._DEFAULT_DELAY_SECONDS, 0.0)
        self.assertIn("empanadas", probe._DEFAULT_PROMPT)
        self.assertIn("pizzas", probe._DEFAULT_PROMPT)
        self.assertIn("cocas", probe._DEFAULT_PROMPT)

    def test_resolve_count_rejects_non_positive(self):
        with self.assertRaises(SystemExit):
            with mock.patch("sys.stderr", io.StringIO()):
                probe._build_parser().parse_args(["--count", "0"])
        with self.assertRaises(SystemExit):
            with mock.patch("sys.stderr", io.StringIO()):
                probe._build_parser().parse_args(["--count", "-1"])
        with self.assertRaises(SystemExit):
            with mock.patch("sys.stderr", io.StringIO()):
                probe._build_parser().parse_args(["--count", "abc"])

    def test_resolve_delay_must_be_finite_non_negative(self):
        with self.assertRaises(SystemExit):
            with mock.patch("sys.stderr", io.StringIO()):
                probe._build_parser().parse_args(["--delay-seconds", "-1"])
        with self.assertRaises(SystemExit):
            with mock.patch("sys.stderr", io.StringIO()):
                probe._build_parser().parse_args(["--delay-seconds", "nan"])
        with self.assertRaises(SystemExit):
            with mock.patch("sys.stderr", io.StringIO()):
                probe._build_parser().parse_args(["--delay-seconds", "inf"])

    def test_resolve_prompt_rejects_empty(self):
        with self.assertRaises(SystemExit):
            with mock.patch("sys.stderr", io.StringIO()):
                probe._build_parser().parse_args(["--prompt", "  "])

    def test_default_parser_values(self):
        args = probe._build_parser().parse_args([])
        self.assertEqual(args.count, 10)
        self.assertEqual(args.delay_seconds, 0.0)
        self.assertEqual(args.prompt, probe._DEFAULT_PROMPT)

    def test_custom_count_and_prompt(self):
        args = probe._build_parser().parse_args([
            "--count", "3",
            "--prompt", "diagnostic message",
            "--delay-seconds", "2.5",
        ])
        self.assertEqual(args.count, 3)
        self.assertEqual(args.prompt, "diagnostic message")
        self.assertEqual(args.delay_seconds, 2.5)


class ProbeRunnerDefaultsTest(unittest.TestCase):
    def test_defaults_perform_ten_calls_with_zero_delay(self):
        sleep_mock = mock.Mock()
        captured_prompts: list[str] = []

        def _transport(url, **kwargs):
            captured_prompts.append(kwargs["json"]["prompt"])
            return _FakeResponse(json.dumps({"ok": True}))

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.time, "sleep", sleep_mock
        ):
            exit_code, statuses = probe.run_probe(
                count=probe._DEFAULT_COUNT,
                delay_seconds=probe._DEFAULT_DELAY_SECONDS,
                prompt=probe._DEFAULT_PROMPT,
                sleep=sleep_mock,
                settings_factory=lambda: _settings(),
                client_factory=lambda settings: QueryLlm(
                    settings=settings, transport=_transport
                ),
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(captured_prompts), 10)
        for value in captured_prompts:
            self.assertEqual(value, probe._DEFAULT_PROMPT)
        self.assertEqual(len(statuses), 10)
        sleep_mock.assert_not_called()


class ProbeRunnerCustomArgsTest(unittest.TestCase):
    def test_custom_count_and_prompt_propagate(self):
        sleep_mock = mock.Mock()
        captured_prompts: list[str] = []

        def _transport(url, **kwargs):
            captured_prompts.append(kwargs["json"]["prompt"])
            return _FakeResponse(json.dumps({"answer": 42}))

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.time, "sleep", sleep_mock
        ):
            exit_code, statuses = probe.run_probe(
                count=3,
                delay_seconds=0,
                prompt="hola diag",
                sleep=sleep_mock,
                settings_factory=lambda: _settings(),
                client_factory=lambda settings: QueryLlm(
                    settings=settings, transport=_transport
                ),
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(captured_prompts, ["hola diag"] * 3)
        self.assertEqual(len(statuses), 3)
        for status in statuses:
            self.assertIn("outcome=success", status)


class ProbeSequentialCallsTest(unittest.TestCase):
    def test_calls_are_sequential(self):
        sleep_mock = mock.Mock()
        order: list[int] = []

        def _transport(url, **kwargs):
            order.append(len(order) + 1)
            return _FakeResponse(json.dumps({"step": len(order)}))

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.time, "sleep", sleep_mock
        ):
            probe.run_probe(
                count=5,
                delay_seconds=0,
                prompt="x",
                sleep=sleep_mock,
                settings_factory=lambda: _settings(),
                client_factory=lambda settings: QueryLlm(
                    settings=settings, transport=_transport
                ),
            )
        self.assertEqual(order, [1, 2, 3, 4, 5])

    def test_delay_is_applied_only_between_calls(self):
        sleep_mock = mock.Mock()

        def _transport(url, **kwargs):
            return _FakeResponse(json.dumps({"ok": True}))

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.time, "sleep", sleep_mock
        ):
            probe.run_probe(
                count=5,
                delay_seconds=2,
                prompt="x",
                sleep=sleep_mock,
                settings_factory=lambda: _settings(),
                client_factory=lambda settings: QueryLlm(
                    settings=settings, transport=_transport
                ),
            )
        # 5 calls => 4 sleeps in between, none before the first or after the last.
        self.assertEqual(sleep_mock.call_count, 4)
        for call in sleep_mock.call_args_list:
            self.assertEqual(call.args[0], 2)
            self.assertEqual(call.kwargs, {})

    def test_zero_delay_does_not_invoke_sleep(self):
        sleep_mock = mock.Mock()

        def _transport(url, **kwargs):
            return _FakeResponse(json.dumps({"ok": True}))

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.time, "sleep", sleep_mock
        ):
            probe.run_probe(
                count=4,
                delay_seconds=0,
                prompt="x",
                sleep=sleep_mock,
                settings_factory=lambda: _settings(),
                client_factory=lambda settings: QueryLlm(
                    settings=settings, transport=_transport
                ),
            )
        sleep_mock.assert_not_called()


class ProbeOutputTest(unittest.TestCase):
    def test_prints_message_and_response_for_each_call(self):
        sleep_mock = mock.Mock()

        def _transport(url, **kwargs):
            return _FakeResponse(json.dumps({"intents": ["a", "b"]}))

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.time, "sleep", sleep_mock
        ):
            probe.run_probe(
                count=2,
                delay_seconds=0,
                prompt="hola probe",
                sleep=sleep_mock,
                settings_factory=lambda: _settings(),
                client_factory=lambda settings: QueryLlm(
                    settings=settings, transport=_transport
                ),
            )
        out = stdout.getvalue()
        self.assertEqual(out.count("Mensaje enviado: hola probe"), 2)
        self.assertEqual(out.count("Respuesta recibida: "), 2)
        self.assertIn("intents", out)
        self.assertEqual(out.count("outcome=success"), 2)
        self.assertEqual(out.count("inicio_utc="), 2)
        self.assertEqual(out.count("fin_utc="), 2)
        self.assertEqual(out.count("duracion_ms="), 2)

    def test_per_attempt_correlation_ids_are_distinct_and_safe(self):
        sleep_mock = mock.Mock()

        def _transport(url, **kwargs):
            return _FakeResponse(json.dumps({"ok": True}))

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.time, "sleep", sleep_mock
        ):
            probe.run_probe(
                count=4,
                delay_seconds=0,
                prompt="x",
                sleep=sleep_mock,
                settings_factory=lambda: _settings(),
                client_factory=lambda settings: QueryLlm(
                    settings=settings, transport=_transport
                ),
            )
        out = stdout.getvalue()
        ids = [
            line.split("=", 1)[1]
            for line in out.splitlines()
            if line.startswith("correlation_id=")
        ]
        self.assertEqual(len(ids), 4)
        self.assertEqual(len(set(ids)), 4)
        for value in ids:
            self.assertTrue(value.startswith("probe-"))
            # Safe: no prompt/response/credential/url content embedded.
            self.assertNotIn("http", value)
            self.assertNotIn("proxy", value)
            self.assertNotIn("secret", value)


class ProbeErrorHandlingTest(unittest.TestCase):
    def test_known_error_prints_only_class_name_and_continues(self):
        sleep_mock = mock.Mock()
        results = [
            _FakeResponse(json.dumps({"ok": True})),
            QueryLlmTimeoutError("super-secret-timeout-detail"),
            _FakeResponse(json.dumps({"ok": True})),
        ]
        seen_prompts: list[str] = []

        def _transport(url, **kwargs):
            seen_prompts.append(kwargs["json"]["prompt"])
            item = results.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.time, "sleep", sleep_mock
        ):
            exit_code, _statuses = probe.run_probe(
                count=3,
                delay_seconds=0,
                prompt="retry me",
                sleep=sleep_mock,
                settings_factory=lambda: _settings(),
                client_factory=lambda settings: QueryLlm(
                    settings=settings, transport=_transport
                ),
            )
        # All three attempts are exercised even though the middle one fails.
        self.assertEqual(len(seen_prompts), 3)
        self.assertEqual(exit_code, 1)
        out = stdout.getvalue()
        self.assertEqual(out.count("Mensaje enviado: retry me"), 3)
        self.assertIn("QueryLlmTimeoutError", out)
        self.assertIn("outcome=error", out)
        # Exception text MUST NOT leak into operator output.
        self.assertNotIn("super-secret-timeout-detail", out)
        # Tracebacks must NOT appear in stdout.
        self.assertNotIn("Traceback", out)

    def test_unexpected_error_is_classified_by_class_name(self):
        sleep_mock = mock.Mock()

        class _BoomError(RuntimeError):
            pass

        results = [
            _FakeResponse(json.dumps({"ok": True})),
            _BoomError("super-secret-unexpected-detail"),
            _FakeResponse(json.dumps({"ok": True})),
        ]

        def _transport(url, **kwargs):
            item = results.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.time, "sleep", sleep_mock
        ):
            probe.run_probe(
                count=3,
                delay_seconds=0,
                prompt="x",
                sleep=sleep_mock,
                settings_factory=lambda: _settings(),
                client_factory=lambda settings: QueryLlm(
                    settings=settings, transport=_transport
                ),
            )
        out = stdout.getvalue()
        self.assertIn("_BoomError", out)
        self.assertIn("outcome=error", out)
        self.assertNotIn("super-secret-unexpected-detail", out)
        self.assertNotIn("Traceback", out)


class ProbeExitCodeTest(unittest.TestCase):
    def test_all_attempts_succeed_returns_zero(self):
        sleep_mock = mock.Mock()

        def _transport(url, **kwargs):
            return _FakeResponse(json.dumps({"ok": True}))

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.time, "sleep", sleep_mock
        ):
            exit_code, _ = probe.run_probe(
                count=3,
                delay_seconds=0,
                prompt="ok",
                sleep=sleep_mock,
                settings_factory=lambda: _settings(),
                client_factory=lambda settings: QueryLlm(
                    settings=settings, transport=_transport
                ),
            )
        self.assertEqual(exit_code, 0)

    def test_mixed_outcomes_return_one(self):
        sleep_mock = mock.Mock()
        results = [
            _FakeResponse(json.dumps({"ok": True})),
            QueryLlmConnectionError("secret-conn-detail"),
            _FakeResponse(json.dumps({"ok": True})),
        ]

        def _transport(url, **kwargs):
            item = results.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.time, "sleep", sleep_mock
        ):
            exit_code, statuses = probe.run_probe(
                count=3,
                delay_seconds=0,
                prompt="ok",
                sleep=sleep_mock,
                settings_factory=lambda: _settings(),
                client_factory=lambda settings: QueryLlm(
                    settings=settings, transport=_transport
                ),
            )
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(statuses), 3)
        self.assertIn("outcome=success", statuses[0])
        self.assertIn("outcome=error", statuses[1])
        self.assertIn("QueryLlmConnectionError", statuses[1])
        self.assertIn("outcome=success", statuses[2])
        for status in statuses:
            self.assertNotIn("secret-conn-detail", status)
            self.assertNotIn("Traceback", status)


class ProbeSafetyTest(unittest.TestCase):
    def test_does_not_print_url_proxy_or_exception_text(self):
        sleep_mock = mock.Mock()
        results = [
            QueryLlmTimeoutError("super-secret-leak-value"),
            QueryLlmHttpError(503, "another super-secret-leak-value"),
            _FakeResponse(json.dumps({"answer": 7})),
        ]

        def _transport(url, **kwargs):
            item = results.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            probe.time, "sleep", sleep_mock
        ):
            probe.run_probe(
                count=3,
                delay_seconds=0,
                prompt="diagnostic",
                sleep=sleep_mock,
                settings_factory=lambda: _settings(
                    llm_url="http://llm-secret-host.invalid/api/generate",
                    ollama_proxy_url="socks5h://user:pass@127.0.0.1:9050",
                ),
                client_factory=lambda settings: QueryLlm(
                    settings=settings, transport=_transport
                ),
            )
        out = stdout.getvalue()
        for forbidden in (
            "super-secret-leak-value",
            "another super-secret-leak-value",
            "user:pass",
            "127.0.0.1",
            "9050",
            "/api/generate",
            "Traceback",
        ):
            self.assertNotIn(forbidden, out)
        # Only the safe class names should appear in the output.
        self.assertIn("QueryLlmTimeoutError", out)
        self.assertIn("QueryLlmHttpError", out)


class ProbeCliEntryPointTest(unittest.TestCase):
    def test_main_invokes_run_probe_and_returns_exit_code_zero(self):
        sleep_mock = mock.Mock()
        success_response = _FakeResponse(json.dumps({"ok": True}))

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            sys,
            "argv",
            [
                "probe_query_llm_repeated",
                "--count", "2",
                "--prompt", "cli probe",
            ],
        ), mock.patch.object(probe.time, "sleep", sleep_mock), mock.patch(
            "backend.scripts.probe_query_llm_repeated.load_settings",
            return_value=_settings(),
        ), mock.patch(
            "backend.llm.query_llm.requests.post",
            return_value=success_response,
        ) as post_mock:
            exit_code = probe.main()
        self.assertEqual(exit_code, 0)
        self.assertEqual(post_mock.call_count, 2)
        self.assertEqual(sleep_mock.call_count, 0)
        out = stdout.getvalue()
        self.assertEqual(out.count("Mensaje enviado: cli probe"), 2)
        self.assertEqual(out.count("outcome=success"), 2)

    def test_main_invokes_run_probe_and_returns_exit_code_one(self):
        sleep_mock = mock.Mock()
        timeout_response = _FakeResponse("super-secret-leak")

        def _raise_timeout(url, json=None, timeout=None):
            raise requests.exceptions.Timeout("super-secret-leak")

        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            sys,
            "argv",
            ["probe_query_llm_repeated", "--count", "2"],
        ), mock.patch.object(probe.time, "sleep", sleep_mock), mock.patch(
            "backend.scripts.probe_query_llm_repeated.load_settings",
            return_value=_settings(),
        ), mock.patch(
            "backend.llm.query_llm.requests.post",
            side_effect=_raise_timeout,
        ):
            exit_code = probe.main()
        self.assertEqual(exit_code, 1)
        out = stdout.getvalue()
        self.assertNotIn("super-secret-leak", out)
        self.assertEqual(out.count("outcome=error"), 2)
        del timeout_response


class ProbeIsolationTest(unittest.TestCase):
    def test_module_does_not_import_banned_backends(self):
        forbidden = {
            "fastapi",
            "sqlalchemy",
            "uvicorn",
            "requests",
            "httpx",
            "aiohttp",
            "websockets",
        }
        forbidden_prefixes = (
            "backend.routers",
            "backend.services",
            "backend.repositories",
            "backend.intents",
            "backend.models",
            "backend.alembic",
            "backend.dependencies",
            "backend.worker",
            "backend.coordinator",
        )
        violations: list[str] = []
        for value in vars(probe).values():
            mod_name = getattr(value, "__name__", None)
            if not mod_name:
                continue
            if mod_name in forbidden or mod_name.split(".")[0] in forbidden:
                violations.append(mod_name)
                continue
            if any(
                mod_name == prefix or mod_name.startswith(prefix + ".")
                for prefix in forbidden_prefixes
            ):
                violations.append(mod_name)
        self.assertEqual(
            violations,
            [],
            f"probe imports banned modules: {violations}",
        )


if __name__ == "__main__":
    unittest.main()
