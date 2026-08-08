import contextlib
import io
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[2]


class RailwayTailscaleEntrypointTest(unittest.TestCase):
    def test_entrypoint_is_valid_shell_and_keeps_proxy_loopback_only(self):
        script = _ROOT / "docker-entrypoint.sh"
        subprocess.run(["sh", "-n", str(script)], check=True)
        source = script.read_text()
        self.assertIn("--tun=userspace-networking", source)
        self.assertIn("--state=mem:", source)
        self.assertIn("--socks5-server=127.0.0.1:1055", source)
        self.assertIn("json.load(sys.stdin).get", source)
        self.assertNotIn("socket.create_connection", source)
        self.assertNotIn("HTTP_PROXY=", source)
        self.assertNotIn("HTTPS_PROXY=", source)
        self.assertNotIn("ALL_PROXY=", source)
        self.assertIn("required_var OLLAMA_PROXY_URL", source)

    def test_railway_predeploy_does_not_enter_tailscale_lifecycle(self):
        railway_toml = (_ROOT / "railway.toml").read_text()
        self.assertIn('builder = "DOCKERFILE"', railway_toml)
        self.assertIn("python -m alembic upgrade head", railway_toml)
        self.assertIn('startCommand = "./docker-entrypoint.sh"', railway_toml)

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
