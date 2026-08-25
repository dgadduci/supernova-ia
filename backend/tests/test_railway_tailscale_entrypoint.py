import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests

_ROOT = Path(__file__).resolve().parents[2]


class RailwayTailscaleEntrypointTest(unittest.TestCase):
    def test_entrypoint_is_valid_shell_and_keeps_proxy_loopback_only(self):
        script = _ROOT / "docker-entrypoint.sh"
        subprocess.run(["sh", "-n", str(script)], check=True)
        source = script.read_text()
        self.assertIn("--tun=userspace-networking", source)
        self.assertIn("--state=mem:", source)
        self.assertIn("--socks5-server=127.0.0.1:1055", source)
        self.assertIn("--outbound-http-proxy-listen=127.0.0.1:1056", source)
        self.assertIn("json.load(sys.stdin).get", source)
        self.assertNotIn("socket.create_connection", source)
        self.assertNotIn("HTTP_PROXY=", source)
        self.assertNotIn("HTTPS_PROXY=", source)
        self.assertNotIn("ALL_PROXY=", source)
        self.assertIn("required_var OLLAMA_PROXY_URL", source)

    def test_entrypoint_starts_both_loopback_listeners(self):
        """Both the SOCKS5 and HTTP Tailscale userspace listeners
        MUST be loopback-only, on the same ``tailscaled`` invocation,
        and remain after the existing SOCKS5 listener so the
        application can pick either transport via ``OLLAMA_PROXY_URL``.
        """
        source = (_ROOT / "docker-entrypoint.sh").read_text()
        self.assertIn("--socks5-server=127.0.0.1:1055", source)
        self.assertIn("--outbound-http-proxy-listen=127.0.0.1:1056", source)
        self.assertNotIn("--socks5-server=0.0.0.0:1055", source)
        self.assertNotIn("--outbound-http-proxy-listen=0.0.0.0:1056", source)
        socks_idx = source.index("--socks5-server=127.0.0.1:1055")
        http_idx = source.index(
            "--outbound-http-proxy-listen=127.0.0.1:1056"
        )
        self.assertLess(
            socks_idx,
            http_idx,
            "HTTP listener must be declared alongside the existing SOCKS5 listener",
        )
        self.assertIn("tailscaled_pid=$!", source)

    def test_railway_manifest_has_no_pre_deploy_command(self):
        railway_toml = (_ROOT / "railway.toml").read_text()
        self.assertIn('builder = "DOCKERFILE"', railway_toml)
        self.assertIn('startCommand = "./docker-entrypoint.sh"', railway_toml)
        self.assertIn('healthcheckPath = "/health"', railway_toml)
        self.assertNotIn("preDeployCommand", railway_toml)
        self.assertNotIn("pre_deploy", railway_toml)
        self.assertNotIn("python -m alembic", railway_toml)

    def test_railway_manifest_healthcheck_and_restart_policy_intact(self):
        railway_toml = (_ROOT / "railway.toml").read_text()
        self.assertIn("healthcheckTimeout = 100", railway_toml)
        self.assertIn('restartPolicyType = "ON_FAILURE"', railway_toml)
        self.assertIn("restartPolicyMaxRetries = 3", railway_toml)

    def test_transport_diagnostic_reports_received_bytes_without_response_body(self):
        from backend.scripts.check_railway_ollama_contracts import (
            run_transport_diagnostic,
        )

        response = SimpleNamespace(
            status_code=200,
            iter_content=lambda chunk_size: [b"abc", b"de"],
            close=lambda: None,
        )
        settings = SimpleNamespace(
            ollama_proxy_url="socks5h://127.0.0.1:1055",
            embedding_url="http://100.113.65.40:11434/api/embed",
            embedding_model="all-minilm:latest",
            embedding_timeout_seconds=30,
        )
        output = io.StringIO()
        with patch(
            "backend.scripts.check_railway_ollama_contracts.requests.post",
            return_value=response,
        ) as post, contextlib.redirect_stdout(output):
            result = run_transport_diagnostic(settings)

        self.assertEqual(result, 0)
        self.assertIn("connection=connected", output.getvalue())
        self.assertIn("http_status=200", output.getvalue())
        self.assertIn("received_bytes=5", output.getvalue())
        self.assertIn("category=response_bytes_received", output.getvalue())
        self.assertNotIn("abc", output.getvalue())
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs["stream"], True)

    def test_transport_diagnostic_keeps_zero_byte_response_failed(self):
        from backend.scripts.check_railway_ollama_contracts import (
            run_transport_diagnostic,
        )

        response = SimpleNamespace(
            status_code=200,
            iter_content=lambda chunk_size: [],
            close=lambda: None,
        )
        settings = SimpleNamespace(
            ollama_proxy_url="socks5h://127.0.0.1:1055",
            embedding_url="http://100.113.65.40:11434/api/embed",
            embedding_model="all-minilm:latest",
            embedding_timeout_seconds=30,
        )
        output = io.StringIO()
        with patch(
            "backend.scripts.check_railway_ollama_contracts.requests.post",
            return_value=response,
        ), contextlib.redirect_stdout(output):
            result = run_transport_diagnostic(settings)

        self.assertEqual(result, 1)
        self.assertIn("connection=connected", output.getvalue())
        self.assertIn("http_status=200", output.getvalue())
        self.assertIn("received_bytes=0", output.getvalue())
        self.assertIn("category=empty_response", output.getvalue())

    def test_embed_target_accepts_loopback_http_proxy(self):
        from backend.scripts.check_railway_ollama_contracts import (
            run_transport_diagnostic,
        )

        response = SimpleNamespace(
            status_code=200,
            iter_content=lambda chunk_size: [b"ok"],
            close=lambda: None,
        )
        settings = SimpleNamespace(
            ollama_proxy_url="http://127.0.0.1:1056",
            embedding_url="http://100.113.65.40:11434/api/embed",
            embedding_model="all-minilm:latest",
            embedding_timeout_seconds=30,
        )
        output = io.StringIO()
        with patch(
            "backend.scripts.check_railway_ollama_contracts.requests.post",
            return_value=response,
        ) as post, contextlib.redirect_stdout(output):
            result = run_transport_diagnostic(settings)

        self.assertEqual(result, 0)
        rendered = output.getvalue()
        self.assertIn("transport=embed", rendered)
        self.assertIn("category=response_bytes_received", rendered)
        self.assertEqual(
            post.call_args.kwargs["proxies"]["http"],
            "http://127.0.0.1:1056",
        )
        self.assertEqual(
            post.call_args.kwargs["proxies"]["https"],
            "http://127.0.0.1:1056",
        )

    def test_embed_target_rejects_unsupported_proxy_scheme(self):
        from backend.scripts.check_railway_ollama_contracts import (
            run_transport_diagnostic,
        )

        settings = SimpleNamespace(
            ollama_proxy_url="ftp://127.0.0.1:1055",
            embedding_url="http://100.113.65.40:11434/api/embed",
            embedding_model="all-minilm:latest",
            embedding_timeout_seconds=30,
        )
        output = io.StringIO()
        with patch(
            "backend.scripts.check_railway_ollama_contracts.requests.post"
        ) as post, contextlib.redirect_stdout(output):
            result = run_transport_diagnostic(settings)

        self.assertEqual(result, 1)
        self.assertIn(
            "category=invalid_proxy_configuration", output.getvalue()
        )
        post.assert_not_called()

    def test_embed_target_rejects_remote_http_proxy(self):
        """A remote HTTP proxy host is not a supported loopback
        transport, so the embed diagnostic must report
        ``invalid_proxy_configuration`` and never invoke
        ``requests.post``.
        """
        from backend.scripts.check_railway_ollama_contracts import (
            run_transport_diagnostic,
        )

        settings = SimpleNamespace(
            ollama_proxy_url="http://100.113.65.40:1056",
            embedding_url="http://100.113.65.40:11434/api/embed",
            embedding_model="all-minilm:latest",
            embedding_timeout_seconds=30,
        )
        output = io.StringIO()
        with patch(
            "backend.scripts.check_railway_ollama_contracts.requests.post"
        ) as post, contextlib.redirect_stdout(output):
            result = run_transport_diagnostic(settings)

        self.assertEqual(result, 1)
        rendered = output.getvalue()
        self.assertIn("transport=embed", rendered)
        self.assertIn("connection=not_attempted", rendered)
        self.assertIn(
            "category=invalid_proxy_configuration", rendered
        )
        self.assertIn("http_status=none", rendered)
        self.assertIn("received_bytes=0", rendered)
        self.assertNotIn("100.113.65.40:1056", rendered)
        post.assert_not_called()


class RailwayGenerateTransportDiagnosticTest(unittest.TestCase):
    """Sanitized operator-run generate transport diagnostic.

    The diagnostic must report only ``target``, ``connection``,
    ``category``, ``http_status``, ``elapsed_seconds`` and
    ``received_bytes``. It must never print the probe prompt, the
    response body, the URL, the proxy value, credentials, headers,
    exception text or tracebacks. The ``requests`` boundary is reused
    unchanged with ``stream=True`` and ``iter_content`` to count bytes.
    """

    _PROXY_URL = "socks5h://127.0.0.1:1055"
    _LLM_URL = "http://100.113.65.40:11434/api/generate"
    _LLM_MODEL = "qwen2.5-coder:7b-ctx8192"

    def _settings(self, **overrides):
        return SimpleNamespace(
            ollama_proxy_url=self._PROXY_URL,
            embedding_url="http://100.113.65.40:11434/api/embed",
            embedding_model="all-minilm:latest",
            embedding_timeout_seconds=30,
            llm_url=self._LLM_URL,
            llm_model=self._LLM_MODEL,
            llm_timeout=180,
            **overrides,
        )

    def test_generate_reports_received_bytes_without_response_body(self):
        from backend.scripts.check_railway_ollama_contracts import (
            run_transport_diagnostic,
        )

        response = SimpleNamespace(
            status_code=200,
            iter_content=lambda chunk_size: [b"abc", b"de"],
            close=lambda: None,
        )
        output = io.StringIO()
        with patch(
            "backend.scripts.check_railway_ollama_contracts.requests.post",
            return_value=response,
        ) as post, contextlib.redirect_stdout(output):
            result = run_transport_diagnostic(
                self._settings(), target="generate"
            )

        self.assertEqual(result, 0)
        rendered = output.getvalue()
        self.assertIn("target=generate", rendered)
        self.assertIn("connection=connected", rendered)
        self.assertIn("http_status=200", rendered)
        self.assertIn("received_bytes=5", rendered)
        self.assertIn("category=response_bytes_received", rendered)
        self.assertNotIn("abc", rendered)
        self.assertNotIn("de", rendered)
        post.assert_called_once()
        self.assertEqual(post.call_args.args[0], self._LLM_URL)
        self.assertEqual(post.call_args.kwargs["stream"], True)
        self.assertEqual(post.call_args.kwargs["timeout"], 180)
        self.assertEqual(
            post.call_args.kwargs["proxies"]["http"],
            self._PROXY_URL,
        )
        self.assertEqual(
            post.call_args.kwargs["json"]["model"], self._LLM_MODEL
        )
        self.assertEqual(post.call_args.kwargs["json"]["stream"], False)
        self.assertEqual(
            post.call_args.kwargs["json"]["prompt"], "ok"
        )

    def test_generate_keeps_zero_byte_response_failed(self):
        from backend.scripts.check_railway_ollama_contracts import (
            run_transport_diagnostic,
        )

        response = SimpleNamespace(
            status_code=200,
            iter_content=lambda chunk_size: [],
            close=lambda: None,
        )
        output = io.StringIO()
        with patch(
            "backend.scripts.check_railway_ollama_contracts.requests.post",
            return_value=response,
        ), contextlib.redirect_stdout(output):
            result = run_transport_diagnostic(
                self._settings(), target="generate"
            )

        self.assertEqual(result, 1)
        rendered = output.getvalue()
        self.assertIn("target=generate", rendered)
        self.assertIn("connection=connected", rendered)
        self.assertIn("http_status=200", rendered)
        self.assertIn("received_bytes=0", rendered)
        self.assertIn("category=empty_response", rendered)

    def test_generate_reports_non_two_xx_as_http_status(self):
        from backend.scripts.check_railway_ollama_contracts import (
            run_transport_diagnostic,
        )

        response = SimpleNamespace(
            status_code=503,
            iter_content=lambda chunk_size: [b"server-error-body"],
            close=lambda: None,
        )
        output = io.StringIO()
        with patch(
            "backend.scripts.check_railway_ollama_contracts.requests.post",
            return_value=response,
        ), contextlib.redirect_stdout(output):
            result = run_transport_diagnostic(
                self._settings(), target="generate"
            )

        self.assertEqual(result, 1)
        rendered = output.getvalue()
        self.assertIn("target=generate", rendered)
        self.assertIn("connection=connected", rendered)
        self.assertIn("http_status=503", rendered)
        self.assertIn("category=http_status", rendered)
        self.assertNotIn("server-error-body", rendered)

    def test_generate_reports_timeout(self):
        from backend.scripts.check_railway_ollama_contracts import (
            run_transport_diagnostic,
        )

        def _raise_timeout(*args, **kwargs):
            raise requests.exceptions.Timeout("super-secret-leak")

        output = io.StringIO()
        with patch(
            "backend.scripts.check_railway_ollama_contracts.requests.post",
            side_effect=_raise_timeout,
        ), contextlib.redirect_stdout(output):
            result = run_transport_diagnostic(
                self._settings(), target="generate"
            )

        self.assertEqual(result, 1)
        rendered = output.getvalue()
        self.assertIn("target=generate", rendered)
        self.assertIn("connection=failed", rendered)
        self.assertIn("http_status=none", rendered)
        self.assertIn("category=timeout", rendered)
        self.assertNotIn("super-secret-leak", rendered)

    def test_generate_reports_connection_error(self):
        from backend.scripts.check_railway_ollama_contracts import (
            run_transport_diagnostic,
        )

        def _raise_conn(*args, **kwargs):
            raise requests.exceptions.ConnectionError("nope-detail-leak")

        output = io.StringIO()
        with patch(
            "backend.scripts.check_railway_ollama_contracts.requests.post",
            side_effect=_raise_conn,
        ), contextlib.redirect_stdout(output):
            result = run_transport_diagnostic(
                self._settings(), target="generate"
            )

        self.assertEqual(result, 1)
        rendered = output.getvalue()
        self.assertIn("target=generate", rendered)
        self.assertIn("connection=failed", rendered)
        self.assertIn("http_status=none", rendered)
        self.assertIn("category=connection_error", rendered)
        self.assertNotIn("nope-detail-leak", rendered)

    def test_generate_reports_invalid_proxy_configuration(self):
        from backend.scripts.check_railway_ollama_contracts import (
            run_transport_diagnostic,
        )

        settings = SimpleNamespace(
            ollama_proxy_url="https://127.0.0.1:9050",
            embedding_url="http://100.113.65.40:11434/api/embed",
            embedding_model="all-minilm:latest",
            embedding_timeout_seconds=30,
            llm_url=self._LLM_URL,
            llm_model=self._LLM_MODEL,
            llm_timeout=180,
        )
        output = io.StringIO()
        with patch(
            "backend.scripts.check_railway_ollama_contracts.requests.post"
        ) as post, contextlib.redirect_stdout(output):
            result = run_transport_diagnostic(settings, target="generate")

        self.assertEqual(result, 1)
        rendered = output.getvalue()
        self.assertIn("target=generate", rendered)
        self.assertIn("connection=not_attempted", rendered)
        self.assertIn("category=invalid_proxy_configuration", rendered)
        self.assertIn("http_status=none", rendered)
        self.assertIn("received_bytes=0", rendered)
        post.assert_not_called()

    def test_generate_accepts_loopback_http_proxy(self):
        from backend.scripts.check_railway_ollama_contracts import (
            run_transport_diagnostic,
        )

        response = SimpleNamespace(
            status_code=200,
            iter_content=lambda chunk_size: [b"ok"],
            close=lambda: None,
        )
        settings = SimpleNamespace(
            ollama_proxy_url="http://127.0.0.1:1056",
            embedding_url="http://100.113.65.40:11434/api/embed",
            embedding_model="all-minilm:latest",
            embedding_timeout_seconds=30,
            llm_url=self._LLM_URL,
            llm_model=self._LLM_MODEL,
            llm_timeout=180,
        )
        output = io.StringIO()
        with patch(
            "backend.scripts.check_railway_ollama_contracts.requests.post",
            return_value=response,
        ) as post, contextlib.redirect_stdout(output):
            result = run_transport_diagnostic(settings, target="generate")

        self.assertEqual(result, 0)
        rendered = output.getvalue()
        self.assertIn("target=generate", rendered)
        self.assertIn("connection=connected", rendered)
        self.assertIn("category=response_bytes_received", rendered)
        self.assertNotIn("127.0.0.1:1056", rendered)
        self.assertNotIn("http://127.0.0.1:1056", rendered)
        self.assertEqual(
            post.call_args.kwargs["proxies"]["http"],
            "http://127.0.0.1:1056",
        )
        self.assertEqual(
            post.call_args.kwargs["proxies"]["https"],
            "http://127.0.0.1:1056",
        )

    def test_generate_accepts_socks5_proxy(self):
        from backend.scripts.check_railway_ollama_contracts import (
            run_transport_diagnostic,
        )

        response = SimpleNamespace(
            status_code=200,
            iter_content=lambda chunk_size: [b"ok"],
            close=lambda: None,
        )
        settings = SimpleNamespace(
            ollama_proxy_url="socks5://127.0.0.1:1055",
            embedding_url="http://100.113.65.40:11434/api/embed",
            embedding_model="all-minilm:latest",
            embedding_timeout_seconds=30,
            llm_url=self._LLM_URL,
            llm_model=self._LLM_MODEL,
            llm_timeout=180,
        )
        output = io.StringIO()
        with patch(
            "backend.scripts.check_railway_ollama_contracts.requests.post",
            return_value=response,
        ) as post, contextlib.redirect_stdout(output):
            result = run_transport_diagnostic(settings, target="generate")

        self.assertEqual(result, 0)
        self.assertEqual(
            post.call_args.kwargs["proxies"]["http"],
            "socks5://127.0.0.1:1055",
        )

    def test_generate_rejects_unsupported_proxy_scheme(self):
        from backend.scripts.check_railway_ollama_contracts import (
            run_transport_diagnostic,
        )

        settings = SimpleNamespace(
            ollama_proxy_url="ftp://127.0.0.1:1055",
            embedding_url="http://100.113.65.40:11434/api/embed",
            embedding_model="all-minilm:latest",
            embedding_timeout_seconds=30,
            llm_url=self._LLM_URL,
            llm_model=self._LLM_MODEL,
            llm_timeout=180,
        )
        output = io.StringIO()
        with patch(
            "backend.scripts.check_railway_ollama_contracts.requests.post"
        ) as post, contextlib.redirect_stdout(output):
            result = run_transport_diagnostic(settings, target="generate")

        self.assertEqual(result, 1)
        self.assertIn(
            "category=invalid_proxy_configuration", output.getvalue()
        )
        post.assert_not_called()

    def test_generate_rejects_remote_http_proxy(self):
        """A remote HTTP proxy host is not a supported loopback
        transport, so the generate diagnostic must report
        ``invalid_proxy_configuration`` and never invoke
        ``requests.post``.
        """
        from backend.scripts.check_railway_ollama_contracts import (
            run_transport_diagnostic,
        )

        settings = SimpleNamespace(
            ollama_proxy_url="http://100.113.65.40:1056",
            embedding_url="http://100.113.65.40:11434/api/embed",
            embedding_model="all-minilm:latest",
            embedding_timeout_seconds=30,
            llm_url=self._LLM_URL,
            llm_model=self._LLM_MODEL,
            llm_timeout=180,
        )
        output = io.StringIO()
        with patch(
            "backend.scripts.check_railway_ollama_contracts.requests.post"
        ) as post, contextlib.redirect_stdout(output):
            result = run_transport_diagnostic(settings, target="generate")

        self.assertEqual(result, 1)
        rendered = output.getvalue()
        self.assertIn("target=generate", rendered)
        self.assertIn("connection=not_attempted", rendered)
        self.assertIn(
            "category=invalid_proxy_configuration", rendered
        )
        self.assertIn("http_status=none", rendered)
        self.assertIn("received_bytes=0", rendered)
        self.assertNotIn("100.113.65.40:1056", rendered)
        post.assert_not_called()

    def test_generate_rejects_proxy_with_credentials(self):
        from backend.scripts.check_railway_ollama_contracts import (
            run_transport_diagnostic,
        )

        settings = SimpleNamespace(
            ollama_proxy_url="http://user:pass@127.0.0.1:1056",
            embedding_url="http://100.113.65.40:11434/api/embed",
            embedding_model="all-minilm:latest",
            embedding_timeout_seconds=30,
            llm_url=self._LLM_URL,
            llm_model=self._LLM_MODEL,
            llm_timeout=180,
        )
        output = io.StringIO()
        with patch(
            "backend.scripts.check_railway_ollama_contracts.requests.post"
        ) as post, contextlib.redirect_stdout(output):
            result = run_transport_diagnostic(settings, target="generate")

        self.assertEqual(result, 1)
        self.assertIn(
            "category=invalid_proxy_configuration", output.getvalue()
        )
        self.assertNotIn("user:pass", output.getvalue())
        post.assert_not_called()

    def test_generate_closes_response_after_iteration(self):
        from backend.scripts.check_railway_ollama_contracts import (
            run_transport_diagnostic,
        )

        closed = {"called": False}

        def _close():
            closed["called"] = True

        response = SimpleNamespace(
            status_code=200,
            iter_content=lambda chunk_size: [b"x"],
            close=_close,
        )
        with patch(
            "backend.scripts.check_railway_ollama_contracts.requests.post",
            return_value=response,
        ), contextlib.redirect_stdout(io.StringIO()):
            run_transport_diagnostic(self._settings(), target="generate")
        self.assertTrue(closed["called"])

    def test_generate_closes_response_on_exception(self):
        from backend.scripts.check_railway_ollama_contracts import (
            run_transport_diagnostic,
        )

        closed = {"called": False}

        def _close():
            closed["called"] = True

        def _iter_content(chunk_size):
            raise OSError("super-secret-iter-leak")
            yield b""  # pragma: no cover - unreachable generator marker

        response = SimpleNamespace(
            status_code=200,
            iter_content=_iter_content,
            close=_close,
        )
        with patch(
            "backend.scripts.check_railway_ollama_contracts.requests.post",
            return_value=response,
        ), contextlib.redirect_stdout(io.StringIO()):
            run_transport_diagnostic(self._settings(), target="generate")
        self.assertTrue(closed["called"])

    def test_generate_output_omits_prompt_response_url_proxy_secrets(
        self,
    ):
        from backend.scripts.check_railway_ollama_contracts import (
            _OLLAMA_GENERATE_TRANSPORT_PROBE_PROMPT,
            run_transport_diagnostic,
        )

        response_body = b"PROMPT-SENTINEL-LEAK RESPONSE-SENTINEL-LEAK"
        response = SimpleNamespace(
            status_code=200,
            iter_content=lambda chunk_size: [response_body],
            close=lambda: None,
        )
        settings = self._settings()
        output = io.StringIO()
        with patch(
            "backend.scripts.check_railway_ollama_contracts.requests.post",
            return_value=response,
        ), contextlib.redirect_stdout(output):
            run_transport_diagnostic(settings, target="generate")

        rendered = output.getvalue()
        for forbidden in (
            _OLLAMA_GENERATE_TRANSPORT_PROBE_PROMPT,
            "PROMPT-SENTINEL-LEAK",
            "RESPONSE-SENTINEL-LEAK",
            self._LLM_URL,
            "100.113.65.40",
            self._PROXY_URL,
            "127.0.0.1:1055",
            "Authorization",
            "Bearer",
            "api_key",
            "Traceback",
            "socks5h",
        ):
            self.assertNotIn(forbidden, rendered)
        self.assertIn("target=generate", rendered)
        self.assertIn("received_bytes=43", rendered)

    def test_generate_unknown_target_raises_value_error(self):
        from backend.scripts.check_railway_ollama_contracts import (
            run_transport_diagnostic,
        )

        with self.assertRaises(ValueError):
            run_transport_diagnostic(self._settings(), target="bogus")

    def test_generate_target_keeps_proxy_passthrough(self):
        from backend.scripts.check_railway_ollama_contracts import (
            run_transport_diagnostic,
        )

        response = SimpleNamespace(
            status_code=200,
            iter_content=lambda chunk_size: [b"{}"],
            close=lambda: None,
        )
        with patch(
            "backend.scripts.check_railway_ollama_contracts.requests.post",
            return_value=response,
        ) as post, contextlib.redirect_stdout(io.StringIO()):
            run_transport_diagnostic(self._settings(), target="generate")
        call_kwargs = post.call_args.kwargs
        self.assertEqual(
            call_kwargs["proxies"]["http"], self._PROXY_URL
        )
        self.assertEqual(
            call_kwargs["proxies"]["https"], self._PROXY_URL
        )
        self.assertTrue(call_kwargs["stream"])

    def test_generate_maps_diagnostic_error_to_request_error(self):
        from backend.scripts.check_railway_ollama_contracts import (
            run_transport_diagnostic,
        )

        for exc_cls in (TypeError, ValueError, OSError):
            sentinel = f"super-secret-{exc_cls.__name__}-leak"

            def _raise(*args, _exc=exc_cls, _msg=sentinel, **kwargs):
                raise _exc(_msg)

            output = io.StringIO()
            with patch(
                "backend.scripts.check_railway_ollama_contracts.requests.post",
                side_effect=_raise,
            ), contextlib.redirect_stdout(output):
                with self.subTest(exception=exc_cls.__name__):
                    result = run_transport_diagnostic(
                        self._settings(), target="generate"
                    )
                    rendered = output.getvalue()

            self.assertEqual(result, 1)
            self.assertIn("target=generate", rendered)
            self.assertIn("connection=failed", rendered)
            self.assertIn("http_status=none", rendered)
            self.assertIn("category=request_error", rendered)
            self.assertNotIn("diagnostic_error", rendered)
            self.assertNotIn(sentinel, rendered)
            output.truncate(0)
            output.seek(0)

    def test_embed_default_target_remains_compatible(self):
        from backend.scripts.check_railway_ollama_contracts import (
            run_transport_diagnostic,
        )

        response = SimpleNamespace(
            status_code=200,
            iter_content=lambda chunk_size: [b"abc"],
            close=lambda: None,
        )
        settings = SimpleNamespace(
            ollama_proxy_url="socks5h://127.0.0.1:1055",
            embedding_url="http://100.113.65.40:11434/api/embed",
            embedding_model="all-minilm:latest",
            embedding_timeout_seconds=30,
        )
        output = io.StringIO()
        with patch(
            "backend.scripts.check_railway_ollama_contracts.requests.post",
            return_value=response,
        ) as post, contextlib.redirect_stdout(output):
            result = run_transport_diagnostic(settings)

        self.assertEqual(result, 0)
        rendered = output.getvalue()
        self.assertIn("transport=embed", rendered)
        self.assertIn("category=response_bytes_received", rendered)
        self.assertEqual(
            post.call_args.args[0],
            "http://100.113.65.40:11434/api/embed",
        )


class EntrypointMigrationGateTest(unittest.TestCase):
    """The Docker entrypoint is the sole repository-managed migration
    authority. Alembic MUST run after SUPERNOVA_DATABASE_URL is validated
    and before any Tailscale or Uvicorn process is launched. A failed or
    absent migration MUST abort the entrypoint with a safe lifecycle
    marker; the worker supervision contract remains unchanged."""

    @staticmethod
    def _entrypoint_source() -> str:
        return (_ROOT / "docker-entrypoint.sh").read_text()

    def test_entrypoint_runs_alembic_after_database_url_validation(self):
        source = self._entrypoint_source()
        url_check = source.index("required_var SUPERNOVA_DATABASE_URL")
        alembic_call = source.index("python -m alembic upgrade head")
        self.assertLess(
            url_check,
            alembic_call,
            "Alembic must run after SUPERNOVA_DATABASE_URL validation",
        )

    def test_entrypoint_runs_alembic_before_tailscaled(self):
        source = self._entrypoint_source()
        alembic_call = source.index("python -m alembic upgrade head")
        tailscaled_call = source.index("tailscaled \\")
        self.assertLess(
            alembic_call,
            tailscaled_call,
            "Alembic must complete before tailscaled is launched",
        )

    def test_entrypoint_runs_alembic_before_uvicorn(self):
        source = self._entrypoint_source()
        alembic_call = source.index("python -m alembic upgrade head")
        uvicorn_call = source.index("uvicorn backend.main:app")
        self.assertLess(
            alembic_call,
            uvicorn_call,
            "Alembic must complete before Uvicorn accepts traffic",
        )

    def test_entrypoint_emits_safe_lifecycle_markers(self):
        source = self._entrypoint_source()
        self.assertIn("migration=starting", source)
        self.assertIn("migration=completed", source)
        self.assertIn("startup_error migration_failed", source)

    def test_entrypoint_migration_gate_omits_secret_leaks(self):
        source = self._entrypoint_source()
        gate_start = source.index("migration=starting")
        gate_end = source.index("migration=completed") + len(
            "migration=completed"
        )
        gate = source[gate_start:gate_end]
        for forbidden in (
            "printenv",
            "env |",
            "echo \"$SUPERNOVA_DATABASE_URL\"",
            "alembic --sql",
            "alembic --pg",
        ):
            self.assertNotIn(forbidden, gate)

    def test_entrypoint_preserves_worker_supervision(self):
        source = self._entrypoint_source()
        self.assertIn("stop_processes()", source)
        self.assertIn('kill "$worker_pid"', source)
        self.assertIn('kill "$app_pid"', source)
        self.assertIn("startup_error provider_worker_exited", source)
        alembic_idx = source.index("python -m alembic upgrade head")
        worker_validate_idx = source.index(
            "validate_worker_startup_or_exit"
        )
        self.assertLess(
            alembic_idx,
            worker_validate_idx,
            (
                "Provider worker validation must remain after the "
                "migration gate"
            ),
        )

    def test_migration_failure_aborts_before_any_traffic(self):
        """With ``PROVIDER_PROCESSING_WORKER_ENABLED=false`` (so the
        flag check passes) and a ``python`` shim that fails
        ``python -m alembic``, the entrypoint MUST exit 1, emit the
        safe ``startup_error migration_failed`` marker, and MUST NOT
        start Tailscale or Uvicorn."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shim = tmp_path / "python"
            shim.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = \"-m\" ] && [ \"$2\" = \"alembic\" ]\n"
                "then\n"
                "    exit 1\n"
                "fi\n"
                "exec /usr/bin/env python \"$@\"\n"
            )
            shim.chmod(0o755)
            env = {
                "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}",
                "SUPERNOVA_DATABASE_URL": "postgresql://x/y",
                "TS_AUTHKEY": "test-authkey",
                "TS_HOSTNAME": "test-host",
                "OLLAMA_PROXY_URL": "socks5h://127.0.0.1:1055",
                "PORT": "8000",
                "PROVIDER_PROCESSING_WORKER_ENABLED": "false",
            }
            proc = subprocess.run(
                ["sh", str(_ROOT / "docker-entrypoint.sh")],
                capture_output=True,
                text=True,
                env=env,
                check=False,
                timeout=15,
            )

        self.assertEqual(
            proc.returncode,
            1,
            msg=(
                f"expected exit 1, got {proc.returncode}: "
                f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
            ),
        )
        self.assertIn("migration=starting", proc.stdout)
        self.assertNotIn("migration=completed", proc.stdout)
        self.assertIn("startup_error migration_failed", proc.stderr)
        self.assertNotIn("tailscale_ready", proc.stdout)
        self.assertNotIn("uvicorn", proc.stdout)
        self.assertNotIn(
            "test-authkey", proc.stdout + proc.stderr,
        )
        self.assertNotIn(
            "postgresql://x/y", proc.stdout + proc.stderr,
        )
