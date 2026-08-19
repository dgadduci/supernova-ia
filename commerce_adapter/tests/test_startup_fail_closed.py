"""Startup fail-closed tests for the T-C adapter.

The adapter must refuse to start the FastAPI app at import time when
any required environment value is missing or malformed. A typed
:class:`CommerceAdapterConfigError` is the single signal so the
operator gets one actionable message instead of a 5xx on the first
request.

Tests cover:

* the global ``app`` instance refuses to import when the env is
  missing the documented values;
* the production entry point :func:`create_app` rejects a missing or
  malformed ``TC_TWILIO_AUTH_TOKEN``, ``TC_TWILIO_ACCOUNT_SID``,
  ``TC_TWILIO_WEBHOOK_BASE_URL``, ``TC_NOVAORDERS_INGRESS_URL``,
  ``TC_INSTALLATION_ID``, ``TC_INSTALLATION_SECRET``,
  ``TC_COMERCIO_ID`` or ``TC_TWILIO_SENDER_E164``;
* a successful configuration still yields a usable ``/health``
  endpoint (the bounded liveness probe is preserved);
* the error message never echoes any secret value.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest

from fastapi.testclient import TestClient

from commerce_adapter.app.config import (
    CommerceAdapterConfigError,
    load_config_from_env,
)

TOKEN: str = "twilio-auth-token-must-not-leak"
SECRET: str = "installation-secret-must-not-leak"
BASE_URL: str = "https://example.test"
NOVAORDERS_URL: str = "https://core.example.test"
INSTALLATION_ID: str = "a" * 24
COMERCIO_ID: int = 7
SENDER_E164: str = "+15555555555"


_REQUIRED_TC_KEYS: tuple[str, ...] = (
    "TC_TWILIO_AUTH_TOKEN",
    "TC_TWILIO_ACCOUNT_SID",
    "TC_TWILIO_WEBHOOK_BASE_URL",
    "TC_NOVAORDERS_INGRESS_URL",
    "TC_INSTALLATION_ID",
    "TC_INSTALLATION_SECRET",
    "TC_COMERCIO_ID",
    "TC_TWILIO_SENDER_E164",
)


def _full_env() -> dict[str, str]:
    return {
        "TC_TWILIO_AUTH_TOKEN": TOKEN,
        "TC_TWILIO_ACCOUNT_SID": "AC" + "0" * 32,
        "TC_TWILIO_WEBHOOK_BASE_URL": BASE_URL,
        "TC_NOVAORDERS_INGRESS_URL": NOVAORDERS_URL,
        "TC_INSTALLATION_ID": INSTALLATION_ID,
        "TC_INSTALLATION_SECRET": SECRET,
        "TC_COMERCIO_ID": str(COMERCIO_ID),
        "TC_TWILIO_SENDER_E164": SENDER_E164,
    }


# Pre-populate the env so the module-level ``app = create_app()`` succeeds
# for the tests that import ``commerce_adapter.app.main``. The subprocess
# test strips the env deliberately to assert the import-time fail-closed
# contract.
for _key in _REQUIRED_TC_KEYS:
    os.environ.setdefault(_key, _full_env()[_key])


class LoadConfigRejectsMissingOrInvalidValuesTest(unittest.TestCase):
    """Every required env value must fail closed individually."""

    def _assert_missing(self, key: str) -> None:
        env = _full_env()
        env.pop(key, None)
        with self.assertRaises(CommerceAdapterConfigError) as ctx:
            load_config_from_env(env)
        message = str(ctx.exception)
        self.assertNotIn(TOKEN, message)
        self.assertNotIn(SECRET, message)

    def test_missing_twilio_auth_token(self) -> None:
        self._assert_missing("TC_TWILIO_AUTH_TOKEN")

    def test_missing_twilio_account_sid(self) -> None:
        self._assert_missing("TC_TWILIO_ACCOUNT_SID")

    def test_missing_webhook_base_url(self) -> None:
        self._assert_missing("TC_TWILIO_WEBHOOK_BASE_URL")

    def test_missing_novaorders_ingress_url(self) -> None:
        self._assert_missing("TC_NOVAORDERS_INGRESS_URL")

    def test_missing_installation_id(self) -> None:
        self._assert_missing("TC_INSTALLATION_ID")

    def test_missing_installation_secret(self) -> None:
        self._assert_missing("TC_INSTALLATION_SECRET")

    def test_missing_comercio_id(self) -> None:
        self._assert_missing("TC_COMERCIO_ID")

    def test_missing_sender_e164(self) -> None:
        self._assert_missing("TC_TWILIO_SENDER_E164")

    def test_invalid_account_sid_rejected(self) -> None:
        env = _full_env()
        env["TC_TWILIO_ACCOUNT_SID"] = "NOT-A-SID"
        with self.assertRaises(CommerceAdapterConfigError):
            load_config_from_env(env)

    def test_http_webhook_base_url_rejected(self) -> None:
        env = _full_env()
        env["TC_TWILIO_WEBHOOK_BASE_URL"] = "http://insecure.test"
        with self.assertRaises(CommerceAdapterConfigError):
            load_config_from_env(env)

    def test_invalid_installation_id_rejected(self) -> None:
        env = _full_env()
        env["TC_INSTALLATION_ID"] = "short"
        with self.assertRaises(CommerceAdapterConfigError):
            load_config_from_env(env)


class CreateAppStartupTest(unittest.TestCase):
    """The production ``create_app`` factory fails closed at startup."""

    def test_create_app_with_explicit_config_succeeds(self) -> None:
        from commerce_adapter.app.main import create_app

        config = load_config_from_env(_full_env())
        app = create_app(config=config)
        self.assertIsNotNone(app)

    def test_create_app_without_config_loads_at_startup(self) -> None:
        from commerce_adapter.app.main import create_app

        saved = os.environ.copy()
        try:
            for key in _full_env():
                os.environ[key] = _full_env()[key]
            app = create_app()
            self.assertIsNotNone(app)
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def test_create_app_without_config_fails_closed_on_missing_env(
        self,
    ) -> None:
        from commerce_adapter.app.main import create_app

        saved = os.environ.copy()
        try:
            for key in _REQUIRED_TC_KEYS:
                os.environ.pop(key, None)
            with self.assertRaises(CommerceAdapterConfigError):
                create_app()
        finally:
            os.environ.clear()
            os.environ.update(saved)


class GlobalAppImportTest(unittest.TestCase):
    """Importing the production ``app`` instance must fail closed.

    The ``app`` symbol in :mod:`commerce_adapter.app.main` is the
    uvicorn entry point. The module loads the configuration at
    import time so a missing or malformed value raises before
    ``uvicorn`` accepts traffic.
    """

    def test_module_import_fails_closed_when_env_is_missing(self) -> None:
        """Subprocess-import the module with no env vars.

        Running a fresh interpreter is the only way to assert the
        import-time contract because the module is cached in the
        parent process. The subprocess must exit non-zero with a
        ``CommerceAdapterConfigError`` in the stderr trace.
        """
        env_overrides = {
            "PYTHONPATH": os.path.abspath("."),
            "PATH": os.environ.get("PATH", ""),
        }
        for key in _REQUIRED_TC_KEYS:
            env_overrides.pop(key, None)
        env_overrides.update(
            {key: "" for key in _REQUIRED_TC_KEYS if key not in env_overrides}
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import commerce_adapter.app.main as m",
            ],
            env=env_overrides,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        combined = (result.stderr or "") + (result.stdout or "")
        self.assertIn("CommerceAdapterConfigError", combined)
        self.assertNotIn(TOKEN, combined)
        self.assertNotIn(SECRET, combined)


class HealthEndpointTest(unittest.TestCase):
    """The ``/health`` liveness probe is preserved under valid config."""

    def test_health_returns_200(self) -> None:
        from commerce_adapter.app.main import create_app

        config = load_config_from_env(_full_env())
        app = create_app(config=config)
        client = TestClient(app)
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main(verbosity=2)