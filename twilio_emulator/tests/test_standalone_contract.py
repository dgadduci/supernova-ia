"""Focused tests for the standalone Twilio emulator service contract.

The tests pin the minimal guarantees the Railway `core/test` service
depends on:

* :func:`twilio_emulator.app.create_app` is importable and returns a
  :class:`fastapi.FastAPI` instance;
* the factory never transitively imports NovaOrders database code or
  ``alembic``;
* the app exposes a single ``GET /health`` route that returns ``200``
  with a non-secret projection.

These tests do not exercise the inbound/outbound behaviour — that
behaviour is already covered by ``test_app.py`` and ``test_service.py``.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

_FORBIDDEN_PACKAGE_PREFIXES: tuple[str, ...] = (
    "backend",
    "alembic",
    "sqlalchemy",
    "psycopg",
)


def _probe_subprocess_imports() -> list[str]:
    """Return any forbidden top-level packages imported by the emulator.

    The probe runs in a fresh interpreter so the test runner's own
    ``sys.modules`` does not pollute the assertion. Only the
    ``twilio_emulator.app`` module is imported; the helper then prints
    the sorted list of forbidden modules it pulled in transitively.
    """
    script = (
        "import json, sys\n"
        "import twilio_emulator.app\n"
        "forbidden = ('backend', 'alembic', 'sqlalchemy', 'psycopg')\n"
        "hits = sorted(\n"
        "    name.split('.')[0]\n"
        "    for name in sys.modules\n"
        "    if name.split('.')[0] in forbidden\n"
        ")\n"
        "sys.stdout.write(json.dumps(hits))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        cwd=".",
    )
    if result.returncode != 0:
        raise AssertionError(
            f"subprocess import probe failed: {result.stderr.strip()}"
        )
    return json.loads(result.stdout or "[]")


class EmulatorFactoryImportTest(unittest.TestCase):
    def test_factory_module_path_is_importable(self) -> None:
        module = importlib.import_module("twilio_emulator.app")
        self.assertTrue(callable(getattr(module, "create_app", None)))

    def test_factory_returns_fastapi_instance_without_env(self) -> None:
        from twilio_emulator.app import create_app
        from twilio_emulator.config import EmulatorConfig

        config = EmulatorConfig(
            control_token="control-token",
            tc_webhook_url="https://tc.example.test/webhook",
            account_sid="AC" + "0" * 32,
            auth_token="auth-token-1234567890",
            public_base_url=None,
            http_port=9090,
            capture_retention=8,
        )
        app = create_app(config=config)
        self.assertIsInstance(app, FastAPI)


class EmulatorStandaloneImportBoundaryTest(unittest.TestCase):
    def test_factory_does_not_transitively_import_novaorders(self) -> None:
        offenders = _probe_subprocess_imports()
        self.assertEqual(
            offenders,
            [],
            f"emulator imports must not include NovaOrders packages: {offenders}",
        )


class EmulatorStandaloneHealthRouteTest(unittest.TestCase):
    def _build_client(self) -> TestClient:
        from twilio_emulator.app import create_app
        from twilio_emulator.config import EmulatorConfig

        config = EmulatorConfig(
            control_token="control-token-shared",
            tc_webhook_url="https://tc.example.test/webhook",
            account_sid="AC" + "a" * 32,
            auth_token="shared-emulator-auth-token",
            public_base_url=None,
            http_port=9090,
            capture_retention=8,
        )
        return TestClient(create_app(config=config))

    def test_health_route_is_registered(self) -> None:
        client = self._build_client()
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)

    def test_health_payload_does_not_expose_secrets(self) -> None:
        client = self._build_client()
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body.get("status"), "ok")
        emulator_section = body.get("emulator")
        self.assertIsInstance(emulator_section, dict)
        self.assertNotIn("control_token", emulator_section)
        self.assertNotIn("auth_token", emulator_section)
        self.assertNotIn("tc_webhook_url", emulator_section)
        self.assertNotIn("control-token-shared", response.text)
        self.assertNotIn("shared-emulator-auth-token", response.text)


__all__: list[str] = []