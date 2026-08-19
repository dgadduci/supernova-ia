"""Startup fail-closed tests for the NovaOrders core process.

The :func:`_validate_startup_configuration` guard in
:mod:`backend.main` must refuse to start the FastAPI process when the
documented invariants are violated. A missing or invalid
``COMMERCE_INSTALLATION_MASTER_KEY`` must raise the typed
:class:`backend.services.exceptions.InvalidInstallationMasterKey`
exception before ``uvicorn`` accepts any traffic.

The validator runs at import time. Tests assert the import-time
contract via subprocess so the cached module in the parent interpreter
does not mask the failure.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest

from cryptography.fernet import Fernet

VALID_KEY: str = Fernet.generate_key().decode("ascii")


def _subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.abspath(".")
    if extra:
        env.update(extra)
    return env


class StartupValidationTest(unittest.TestCase):
    """The NovaOrders core refuses to import when the master key
    is missing or invalid.

    The subprocess invocation drives the real :mod:`backend.main`
    import path so the cached module in the parent interpreter does
    not mask the failure.
    """

    def setUp(self) -> None:
        self._saved_env = os.environ.copy()

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._saved_env)

    def _run_subprocess_import(self) -> subprocess.CompletedProcess[str]:
        env = _subprocess_env()
        return subprocess.run(
            [sys.executable, "-c", "import backend.main"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def test_missing_master_key_fails_closed_when_ingress_mounted(
        self,
    ) -> None:
        os.environ.pop("COMMERCE_INSTALLATION_MASTER_KEY", None)
        os.environ["COMMERCE_ISOLATED_OUTBOUND_ENABLED"] = "false"
        result = self._run_subprocess_import()
        self.assertNotEqual(result.returncode, 0)
        combined = (result.stderr or "") + (result.stdout or "")
        self.assertIn("InvalidInstallationMasterKey", combined)
        self.assertIn("COMMERCE_INSTALLATION_MASTER_KEY", combined)

    def test_missing_master_key_fails_closed_when_flag_is_on(
        self,
    ) -> None:
        os.environ.pop("COMMERCE_INSTALLATION_MASTER_KEY", None)
        os.environ["COMMERCE_ISOLATED_OUTBOUND_ENABLED"] = "true"
        result = self._run_subprocess_import()
        self.assertNotEqual(result.returncode, 0)
        combined = (result.stderr or "") + (result.stdout or "")
        self.assertIn("InvalidInstallationMasterKey", combined)

    def test_invalid_master_key_fails_closed(self) -> None:
        os.environ["COMMERCE_INSTALLATION_MASTER_KEY"] = "not-a-valid-fernet-key"
        os.environ["COMMERCE_ISOLATED_OUTBOUND_ENABLED"] = "false"
        result = self._run_subprocess_import()
        self.assertNotEqual(result.returncode, 0)
        combined = (result.stderr or "") + (result.stdout or "")
        self.assertIn("InvalidInstallationMasterKey", combined)

    def test_valid_master_key_starts_cleanly(self) -> None:
        os.environ["COMMERCE_INSTALLATION_MASTER_KEY"] = VALID_KEY
        os.environ["COMMERCE_ISOLATED_OUTBOUND_ENABLED"] = "false"
        result = self._run_subprocess_import()
        self.assertEqual(result.returncode, 0)
        combined = (result.stderr or "") + (result.stdout or "")
        self.assertNotIn("InvalidInstallationMasterKey", combined)


if __name__ == "__main__":
    unittest.main(verbosity=2)