"""Focused tests for the emulator configuration helpers.

The tests cover the documented fail-closed behaviour:

* missing control token / T-C webhook URL → :class:`EmulatorConfigError`;
* generated ``AC`` account SID is canonical and unique per process;
* generated ``auth token`` is opaque, non-empty and never logged;
* ``to_public_dict`` never exposes the control token or the auth
  token;
* the configuration loads successfully from a complete environment.
"""
from __future__ import annotations

import unittest

from twilio_emulator.config import (
    EmulatorConfigError,
    load_config_from_env,
)


def _full_env(**overrides: str) -> dict[str, str]:
    env = {
        "EMULATOR_CONTROL_TOKEN": "control-token-xyz",
        "EMULATOR_TC_WEBHOOK_URL": "https://tc.example.test/webhook",
        "EMULATOR_TWILIO_ACCOUNT_SID": "AC" + "a" * 32,
        "EMULATOR_TWILIO_AUTH_TOKEN": "shared-emulator-auth-token-xyz",
        "EMULATOR_PUBLIC_BASE_URL": "https://emulator.example.test",
        "EMULATOR_HTTP_PORT": "9090",
        "EMULATOR_CAPTURE_RETENTION": "16",
    }
    env.update({key: value for key, value in overrides.items() if value is not None})
    return env


class EmulatorConfigMissingTokensTest(unittest.TestCase):
    def test_missing_control_token_raises(self) -> None:
        env = _full_env()
        env.pop("EMULATOR_CONTROL_TOKEN")
        with self.assertRaises(EmulatorConfigError):
            load_config_from_env(env)

    def test_missing_tc_webhook_url_raises(self) -> None:
        env = _full_env()
        env.pop("EMULATOR_TC_WEBHOOK_URL")
        with self.assertRaises(EmulatorConfigError):
            load_config_from_env(env)

    def test_non_https_webhook_url_raises(self) -> None:
        env = _full_env(EMULATOR_TC_WEBHOOK_URL="http://tc.example.test/webhook")
        with self.assertRaises(EmulatorConfigError):
            load_config_from_env(env)

    def test_webhook_url_with_query_raises(self) -> None:
        env = _full_env(EMULATOR_TC_WEBHOOK_URL="https://tc.example.test/webhook?x=1")
        with self.assertRaises(EmulatorConfigError):
            load_config_from_env(env)

    def test_invalid_http_port_raises(self) -> None:
        env = _full_env(EMULATOR_HTTP_PORT="abc")
        with self.assertRaises(EmulatorConfigError):
            load_config_from_env(env)

    def test_zero_http_port_raises(self) -> None:
        env = _full_env(EMULATOR_HTTP_PORT="0")
        with self.assertRaises(EmulatorConfigError):
            load_config_from_env(env)


class EmulatorConfigGenerationTest(unittest.TestCase):
    def test_generated_account_sid_matches_canonical_shape(self) -> None:
        env = _full_env()
        env.pop("EMULATOR_TWILIO_ACCOUNT_SID")
        config = load_config_from_env(
            env, allow_generated_credentials=True
        )
        self.assertTrue(config.account_sid.startswith("AC"))
        self.assertEqual(len(config.account_sid), 34)
        tail = config.account_sid[2:]
        self.assertTrue(all(ch in "0123456789abcdef" for ch in tail))

    def test_generated_auth_token_is_non_empty_and_unique(self) -> None:
        env_a = _full_env()
        env_a.pop("EMULATOR_TWILIO_AUTH_TOKEN")
        env_b = _full_env()
        env_b.pop("EMULATOR_TWILIO_AUTH_TOKEN")
        config_a = load_config_from_env(
            env_a, allow_generated_credentials=True
        )
        config_b = load_config_from_env(
            env_b, allow_generated_credentials=True
        )
        self.assertTrue(config_a.auth_token)
        self.assertTrue(config_b.auth_token)
        self.assertNotEqual(config_a.auth_token, config_b.auth_token)

    def test_supplied_canonical_account_sid_is_preserved(self) -> None:
        sid = "AC" + "0" * 32
        config = load_config_from_env(
            _full_env(EMULATOR_TWILIO_ACCOUNT_SID=sid),
            allow_generated_credentials=True,
        )
        self.assertEqual(config.account_sid, sid)

    def test_supplied_invalid_account_sid_raises(self) -> None:
        env = _full_env(EMULATOR_TWILIO_ACCOUNT_SID="not-canonical")
        with self.assertRaises(EmulatorConfigError):
            load_config_from_env(
                env, allow_generated_credentials=True
            )

    def test_to_public_dict_never_exposes_tokens(self) -> None:
        env = _full_env()
        env.pop("EMULATOR_TWILIO_AUTH_TOKEN")
        config = load_config_from_env(
            env, allow_generated_credentials=True
        )
        projection = config.to_public_dict()
        self.assertNotIn("control_token", projection)
        self.assertNotIn("auth_token", projection)
        self.assertNotIn(config.control_token, str(projection))
        self.assertNotIn(config.auth_token, str(projection))


class EmulatorConfigSharedCredentialsTest(unittest.TestCase):
    """The emulator fails closed when ``EMULATOR_TWILIO_ACCOUNT_SID``
    or ``EMULATOR_TWILIO_AUTH_TOKEN`` is not explicitly pinned, so the
    emulator, T-C adapter and central dispatcher always agree on the
    same Twilio-shaped pair."""

    def test_missing_account_sid_raises(self) -> None:
        env = _full_env()
        env.pop("EMULATOR_TWILIO_ACCOUNT_SID")
        with self.assertRaises(EmulatorConfigError):
            load_config_from_env(env)

    def test_missing_auth_token_raises(self) -> None:
        env = _full_env()
        env.pop("EMULATOR_TWILIO_AUTH_TOKEN")
        with self.assertRaises(EmulatorConfigError):
            load_config_from_env(env)

    def test_blank_account_sid_raises(self) -> None:
        env = _full_env(EMULATOR_TWILIO_ACCOUNT_SID="   ")
        with self.assertRaises(EmulatorConfigError):
            load_config_from_env(env)

    def test_blank_auth_token_raises(self) -> None:
        env = _full_env(EMULATOR_TWILIO_AUTH_TOKEN="   ")
        with self.assertRaises(EmulatorConfigError):
            load_config_from_env(env)

    def test_supplied_credentials_are_preserved(self) -> None:
        sid = "AC" + "a" * 32
        token = "shared-emulator-auth-token-xyz"
        env = _full_env(
            EMULATOR_TWILIO_ACCOUNT_SID=sid,
            EMULATOR_TWILIO_AUTH_TOKEN=token,
        )
        config = load_config_from_env(env)
        self.assertEqual(config.account_sid, sid)
        self.assertEqual(config.auth_token, token)


class EmulatorConfigLoggingPrivacyTest(unittest.TestCase):
    def test_load_config_does_not_log_secrets(self) -> None:
        captured: list[str] = []

        class _Sink:
            def write(self, message: str) -> None:
                captured.append(message)

        import logging

        logger = logging.getLogger("twilio_emulator.config")
        previous_level = logger.level
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler(_Sink())
        logger.addHandler(handler)
        try:
            config = load_config_from_env(
                _full_env(), allow_generated_credentials=True
            )
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous_level)
        joined = "\n".join(captured)
        self.assertNotIn("control-token-xyz", joined)
        self.assertNotIn(config.auth_token, joined)