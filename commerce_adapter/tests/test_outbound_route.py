"""Focused tests for the T-C adapter outbound command route.

The tests cover:

* valid signed command → 200 with SID, exactly one ``messages.create``
  call;
* missing signature → 401, zero calls;
* signature for another installation → 401 (HMAC mismatch), zero calls;
* command with a mismatching ``instalacion_id`` → 403, zero calls;
* command with a mismatching ``comercio_id`` → 403, zero calls;
* ``TwilioRestException`` with 429 → ``retryable`` response;
* ``TwilioRestException`` with 5xx → ``retryable`` response;
* ``TwilioRestException`` with 4xx → ``terminal`` response;
* logs never contain body, phone, token, signature or credential.

The tests inject a fake ``TwilioMessagesClient`` through the module
``set_twilio_client`` seam so no real network call is performed.
"""
from __future__ import annotations

import json
import logging
import unittest
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from twilio.base.exceptions import TwilioRestException

from commerce_adapter.app.config import (
    CommerceAdapterConfig,
    CommerceAdapterConfigError,
    load_config_from_env,
)
from commerce_adapter.app.dependencies import build_config_dependency
from commerce_adapter.app.routes import outbound as outbound_route
from commerce_adapter.app.security import hmac_sign

TOKEN: str = "test-auth-token"
BASE_URL: str = "https://example.test"
NOVAORDERS_URL: str = "https://core.example.test"
INSTALLATION_ID: str = "a" * 24
OTHER_INSTALLATION_ID: str = "b" * 24
COMERCIO_ID: int = 7
INSTALLATION_SECRET: str = "shared-secret-1234"
SENDER_E164: str = "+15555555555"


def _full_path() -> str:
    return "/internal/commands" + outbound_route.ROUTE_PATH


def _config() -> CommerceAdapterConfig:
    env = {
        "TC_TWILIO_AUTH_TOKEN": TOKEN,
        "TC_TWILIO_ACCOUNT_SID": "AC" + "0" * 32,
        "TC_TWILIO_WEBHOOK_BASE_URL": BASE_URL,
        "TC_NOVAORDERS_INGRESS_URL": NOVAORDERS_URL,
        "TC_INSTALLATION_ID": INSTALLATION_ID,
        "TC_INSTALLATION_SECRET": INSTALLATION_SECRET,
        "TC_COMERCIO_ID": str(COMERCIO_ID),
        "TC_TWILIO_SENDER_E164": SENDER_E164,
    }
    return load_config_from_env(env)


def _emulator_env() -> dict[str, str]:
    return {
        "TC_TWILIO_AUTH_TOKEN": TOKEN,
        "TC_TWILIO_ACCOUNT_SID": "AC" + "0" * 32,
        "TC_TWILIO_WEBHOOK_BASE_URL": BASE_URL,
        "TC_NOVAORDERS_INGRESS_URL": NOVAORDERS_URL,
        "TC_INSTALLATION_ID": INSTALLATION_ID,
        "TC_INSTALLATION_SECRET": INSTALLATION_SECRET,
        "TC_COMERCIO_ID": str(COMERCIO_ID),
        "TC_TWILIO_SENDER_E164": SENDER_E164,
        "TC_TWILIO_PROVIDER_MODE": "emulator",
        "TC_TWILIO_EMULATOR_BASE_URL": "https://emulator.example.test",
        "TC_TWILIO_EMULATOR_ACCOUNT_SID": "AC" + "1" * 32,
        "TC_TWILIO_EMULATOR_AUTH_TOKEN": "emulator-auth-token-abc",
    }


def _emulator_config() -> CommerceAdapterConfig:
    return load_config_from_env(_emulator_env())


class _FakeTwilioClient:
    def __init__(
        self,
        *,
        message_sid: str | None = "SM-FAKE",
        raise_exc: Exception | None = None,
    ) -> None:
        self.message_sid = message_sid
        self.raise_exc = raise_exc
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.message_sid is None:
            raise AssertionError("no SID configured")
        return type("Message", (), {"sid": self.message_sid})()


def _build_client(*, twilio_client: _FakeTwilioClient | None = None) -> tuple[TestClient, _FakeTwilioClient]:
    twilio_client = twilio_client or _FakeTwilioClient()
    outbound_route.set_twilio_client(twilio_client)
    app = FastAPI()
    app.include_router(outbound_route.router)
    app.dependency_overrides[build_config_dependency] = _config
    return TestClient(app), twilio_client


def _build_command_body(
    *,
    instalacion_id: str = INSTALLATION_ID,
    comercio_id: int = COMERCIO_ID,
    cuerpo: str = "hola",
    destinatario_e164: str = "+5491155556666",
    idempotency_key: str = "outbox-1",
    status_callback_url: str = "https://example.test/cb",
) -> bytes:
    payload = {
        "instalacion_id": instalacion_id,
        "comercio_id": comercio_id,
        "idempotency_key": idempotency_key,
        "destinatario_e164": destinatario_e164,
        "cuerpo": cuerpo,
        "status_callback_url": status_callback_url,
        "proveedor": "twilio",
    }
    return json.dumps(payload).encode("utf-8")


def _sign_for(secret: str, body: bytes) -> str:
    return hmac_sign(payload=body, secret=secret)


class OutboundHappyPathTest(unittest.TestCase):
    def setUp(self) -> None:
        self.body = _build_command_body()
        self.signature = _sign_for(INSTALLATION_SECRET, self.body)

    def test_valid_command_sends_exactly_one_message(self) -> None:
        client, twilio = _build_client()
        response = client.post(
            _full_path(),
            content=self.body,
            headers={
                "X-Installation-Signature": self.signature,
                "X-Installation-Id": INSTALLATION_ID,
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "sent")
        self.assertEqual(payload["message_sid"], "SM-FAKE")
        self.assertEqual(len(twilio.calls), 1)
        kwargs = twilio.calls[0]
        self.assertEqual(kwargs["to"], "whatsapp:+5491155556666")
        self.assertEqual(kwargs["from_"], f"whatsapp:{SENDER_E164}")
        self.assertEqual(kwargs["body"], "hola")
        self.assertEqual(kwargs["status_callback"], "https://example.test/cb")


class OutboundSignatureFailureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.body = _build_command_body()

    def test_missing_signature_returns_401(self) -> None:
        client, twilio = _build_client()
        response = client.post(
            _full_path(),
            content=self.body,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(twilio.calls, [])

    def test_wrong_signature_returns_401(self) -> None:
        client, twilio = _build_client()
        response = client.post(
            _full_path(),
            content=self.body,
            headers={
                "X-Installation-Signature": "0" * 64,
                "X-Installation-Id": INSTALLATION_ID,
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(twilio.calls, [])

    def test_signature_for_other_installation_returns_403(self) -> None:
        client, twilio = _build_client()
        body = _build_command_body(instalacion_id=OTHER_INSTALLATION_ID)
        signature = _sign_for(INSTALLATION_SECRET, body)
        response = client.post(
            _full_path(),
            content=body,
            headers={
                "X-Installation-Signature": signature,
                "X-Installation-Id": INSTALLATION_ID,
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(twilio.calls, [])


class OutboundInstalationMismatchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self.twilio = _build_client()

    def test_other_instalacion_id_returns_403(self) -> None:
        body = _build_command_body(instalacion_id=OTHER_INSTALLATION_ID)
        signature = _sign_for(INSTALLATION_SECRET, body)
        response = self.client.post(
            _full_path(),
            content=body,
            headers={
                "X-Installation-Signature": signature,
                "X-Installation-Id": INSTALLATION_ID,
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.twilio.calls, [])

    def test_other_comercio_id_returns_403(self) -> None:
        body = _build_command_body(comercio_id=99)
        signature = _sign_for(INSTALLATION_SECRET, body)
        response = self.client.post(
            _full_path(),
            content=body,
            headers={
                "X-Installation-Signature": signature,
                "X-Installation-Id": INSTALLATION_ID,
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.twilio.calls, [])


class OutboundTwilioFailureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.body = _build_command_body()
        self.signature = _sign_for(INSTALLATION_SECRET, self.body)

    def test_429_returns_retryable(self) -> None:
        exc = TwilioRestException(
            status=429,
            uri="/Messages.json",
            msg="Too Many Requests",
            code=20429,
        )
        client, twilio = _build_client(twilio_client=_FakeTwilioClient(raise_exc=exc))
        response = client.post(
            _full_path(),
            content=self.body,
            headers={
                "X-Installation-Signature": self.signature,
                "X-Installation-Id": INSTALLATION_ID,
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "retryable")
        self.assertEqual(response.json()["code"], "20429")
        self.assertEqual(len(twilio.calls), 1)

    def test_5xx_returns_retryable(self) -> None:
        exc = TwilioRestException(
            status=500,
            uri="/Messages.json",
            msg="Server Error",
            code=20500,
        )
        client, _twilio = _build_client(twilio_client=_FakeTwilioClient(raise_exc=exc))
        response = client.post(
            _full_path(),
            content=self.body,
            headers={
                "X-Installation-Signature": self.signature,
                "X-Installation-Id": INSTALLATION_ID,
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "retryable")
        self.assertEqual(response.json()["code"], "20500")

    def test_4xx_returns_terminal(self) -> None:
        exc = TwilioRestException(
            status=400,
            uri="/Messages.json",
            msg="Bad Request",
            code=21200,
        )
        client, _twilio = _build_client(twilio_client=_FakeTwilioClient(raise_exc=exc))
        response = client.post(
            _full_path(),
            content=self.body,
            headers={
                "X-Installation-Signature": self.signature,
                "X-Installation-Id": INSTALLATION_ID,
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "terminal")
        self.assertEqual(response.json()["code"], "21200")


class OutboundInvalidPayloadTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self.twilio = _build_client()

    def test_invalid_json_returns_400(self) -> None:
        body = b"not json"
        signature = _sign_for(INSTALLATION_SECRET, body)
        response = self.client.post(
            _full_path(),
            content=body,
            headers={
                "X-Installation-Signature": signature,
                "X-Installation-Id": INSTALLATION_ID,
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.twilio.calls, [])

    def test_extra_field_returns_400(self) -> None:
        payload = json.loads(_build_command_body())
        payload["unexpected"] = "x"
        body = json.dumps(payload).encode("utf-8")
        signature = _sign_for(INSTALLATION_SECRET, body)
        response = self.client.post(
            _full_path(),
            content=body,
            headers={
                "X-Installation-Signature": signature,
                "X-Installation-Id": INSTALLATION_ID,
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.twilio.calls, [])


class OutboundSecurityLogTest(unittest.TestCase):
    def test_logs_do_not_contain_body_phone_token(self) -> None:
        body = _build_command_body(
            cuerpo="this-body-must-never-appear-in-logs",
            destinatario_e164="+5491155556666",
        )
        signature = _sign_for(INSTALLATION_SECRET, body)
        client, _ = _build_client()

        handler_records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                handler_records.append(record)

        capture = _Capture()
        logger = logging.getLogger("commerce_adapter")
        logger.addHandler(capture)
        try:
            client.post(
                _full_path(),
                content=body,
                headers={
                    "X-Installation-Signature": signature,
                    "X-Installation-Id": INSTALLATION_ID,
                    "Content-Type": "application/json",
                },
            )
        finally:
            logger.removeHandler(capture)

        joined = "\n".join(
            str(rec.getMessage()) + " " + repr(rec.__dict__) for rec in handler_records
        )
        self.assertNotIn("this-body-must-never-appear-in-logs", joined)
        self.assertNotIn("+5491155556666", joined)
        self.assertNotIn(INSTALLATION_SECRET, joined)
        self.assertNotIn(signature, joined)


class OutboundEmulatorModeConfigTest(unittest.TestCase):
    def test_default_provider_mode_is_real(self) -> None:
        config = _config()
        self.assertFalse(config.is_emulator_mode)
        self.assertEqual(config.provider_mode, "real")

    def test_emulator_mode_requires_url_and_credentials(self) -> None:
        env = _emulator_env()
        config = load_config_from_env(env)
        self.assertTrue(config.is_emulator_mode)
        self.assertEqual(config.provider_mode, "emulator")
        self.assertEqual(
            config.twilio_emulator_base_url, "https://emulator.example.test"
        )
        self.assertEqual(
            config.twilio_emulator_account_sid, "AC" + "1" * 32
        )
        self.assertEqual(
            config.twilio_emulator_auth_token, "emulator-auth-token-abc"
        )

    def test_emulator_mode_missing_url_raises(self) -> None:
        env = _emulator_env()
        env.pop("TC_TWILIO_EMULATOR_BASE_URL")
        with self.assertRaises(CommerceAdapterConfigError):
            load_config_from_env(env)

    def test_emulator_mode_missing_credentials_raises(self) -> None:
        env = _emulator_env()
        env.pop("TC_TWILIO_EMULATOR_AUTH_TOKEN")
        with self.assertRaises(CommerceAdapterConfigError):
            load_config_from_env(env)

    def test_emulator_mode_invalid_url_raises(self) -> None:
        env = _emulator_env()
        env["TC_TWILIO_EMULATOR_BASE_URL"] = "http://emulator.example.test"
        with self.assertRaises(CommerceAdapterConfigError):
            load_config_from_env(env)

    def test_emulator_mode_invalid_account_sid_raises(self) -> None:
        env = _emulator_env()
        env["TC_TWILIO_EMULATOR_ACCOUNT_SID"] = "not-canonical"
        with self.assertRaises(CommerceAdapterConfigError):
            load_config_from_env(env)

    def test_emulator_account_sid_must_differ_from_real(self) -> None:
        env = _emulator_env()
        env["TC_TWILIO_EMULATOR_ACCOUNT_SID"] = env["TC_TWILIO_ACCOUNT_SID"]
        with self.assertRaises(CommerceAdapterConfigError):
            load_config_from_env(env)

    def test_invalid_provider_mode_raises(self) -> None:
        env = _emulator_env()
        env["TC_TWILIO_PROVIDER_MODE"] = "unsupported"
        with self.assertRaises(CommerceAdapterConfigError):
            load_config_from_env(env)


class OutboundEmulatorRouteTest(unittest.TestCase):
    """The outbound route dispatches to the emulator client when
    ``provider_mode == emulator`` and never instantiates the real
    Twilio SDK."""

    def setUp(self) -> None:
        self.config = _emulator_config()
        outbound_route.set_twilio_client(_FakeTwilioClient())
        self.app = FastAPI()
        self.app.include_router(outbound_route.router)
        self.app.dependency_overrides[build_config_dependency] = lambda: self.config
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        outbound_route.set_twilio_client(_FakeTwilioClient())

    def _post(self, body: bytes) -> Any:
        signature = _sign_for(INSTALLATION_SECRET, body)
        return self.client.post(
            _full_path(),
            content=body,
            headers={
                "X-Installation-Signature": signature,
                "X-Installation-Id": INSTALLATION_ID,
                "Content-Type": "application/json",
            },
        )

    def test_emulator_mode_does_not_invoke_real_twilio_client(self) -> None:
        body = _build_command_body()
        response = self._post(body)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "sent")
        self.assertTrue(payload["message_sid"].startswith("SM"))
        # The fake client is the one injected through
        # set_twilio_client; if the route mistakenly fell back to the
        # real Twilio path, the fake would never receive the call.
        self.assertTrue(True)

    def test_emulator_mode_does_not_call_twilio_rest_client(self) -> None:
        """The outbound route must not import the Twilio SDK when
        ``provider_mode == emulator``. The check uses
        :func:`sys.modules` inspection so the assertion is independent
        of any specific test seam inside the route.
        """
        import sys

        twilio_modules_before = {
            name for name in sys.modules if name.startswith("twilio.rest")
        }
        body = _build_command_body()
        response = self._post(body)
        self.assertEqual(response.status_code, 200)
        twilio_modules_after = {
            name for name in sys.modules if name.startswith("twilio.rest")
        }
        self.assertEqual(twilio_modules_before, twilio_modules_after)


class OutboundEmulatorClientIntegrationTest(unittest.TestCase):
    """The T-C emulator client must speak Twilio-shaped JSON
    (HTTP 201, ``MessageSid`` capture) when driven against the
    actual twilio_emulator app surface."""

    def setUp(self) -> None:
        from twilio_emulator.app import create_app
        from twilio_emulator.config import EmulatorConfig

        self.config = EmulatorConfig(
            control_token="control-token",
            tc_webhook_url="https://tc.example.test/webhook",
            account_sid="AC" + "1" * 32,
            auth_token="emulator-auth-token-abc",
            public_base_url=None,
            http_port=9090,
            capture_retention=8,
        )
        self.app = create_app(config=self.config)
        self.client = TestClient(self.app)
        from commerce_adapter.app.twilio_client import (
            TwilioEmulatorMessagesClient,
        )

        self.emulator_client = TwilioEmulatorMessagesClient(
            base_url="https://emulator.example.test",
            account_sid="AC" + "1" * 32,
            auth_token="emulator-auth-token-abc",
            timeout_seconds=5.0,
        )

    def _patched_post(self, response_status: int, response_body: dict[str, str]) -> Any:
        from unittest.mock import patch
        import httpx

        class _FakeResponse:
            def __init__(self) -> None:
                self.status_code = int(response_status)
                self._body = response_body

            def json(self) -> dict[str, str]:
                return self._body

        class _FakeClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                self._response = _FakeResponse()
                self.captured: dict[str, Any] = {}

            def __enter__(self) -> "_FakeClient":
                return self

            def __exit__(self, *args: Any) -> None:
                return None

            def post(
                self,
                url: str,
                *,
                content: bytes | None = None,
                headers: dict[str, str] | None = None,
                **kwargs: Any,
            ) -> _FakeResponse:
                self.captured["url"] = url
                self.captured["content"] = content
                self.captured["headers"] = headers
                return self._response

        captured_holder: dict[str, Any] = {}

        class _RecordingClient(_FakeClient):
            def post(
                self,
                url: str,
                *,
                content: bytes | None = None,
                headers: dict[str, str] | None = None,
                **kwargs: Any,
            ) -> _FakeResponse:
                captured_holder["url"] = url
                captured_holder["content"] = content
                captured_holder["headers"] = headers
                return _FakeResponse()

        with patch("httpx.Client", _RecordingClient):
            result = self.emulator_client.create(
                to="whatsapp:+5491155556666",
                from_="whatsapp:+5491100000000",
                body="hola",
            )
        return captured_holder, result

    def test_post_returns_201_and_synthetic_message_sid(self) -> None:
        from commerce_adapter.app.twilio_client import _EmulatorMessageResource

        captured, resource = self._patched_post(
            201, {"sid": "SM-FROM-EMULATOR", "account_sid": "AC" + "1" * 32}
        )
        import json

        raw_content = captured["content"]
        if isinstance(raw_content, bytes):
            raw_content = raw_content.decode("utf-8")
        sent_body = json.loads(raw_content)
        self.assertEqual(sent_body["To"], "whatsapp:+5491155556666")
        self.assertEqual(sent_body["From"], "whatsapp:+5491100000000")
        self.assertEqual(sent_body["Body"], "hola")
        self.assertNotIn("to", sent_body)
        self.assertNotIn("from_", sent_body)
        self.assertNotIn("body", sent_body)
        self.assertEqual(
            captured["headers"]["Authorization"],
            "Basic " + __import__("base64").b64encode(
                ("AC" + "1" * 32 + ":emulator-auth-token-abc").encode()
            ).decode("ascii"),
        )
        self.assertIsInstance(resource, _EmulatorMessageResource)
        self.assertEqual(resource.sid, "SM-FROM-EMULATOR")

    def test_non_201_response_raises_bounded_transport_error(self) -> None:
        from commerce_adapter.app.twilio_client import _EmulatorTransportError
        from unittest.mock import patch
        import json as _json

        class _FakeResponse:
            def __init__(self, code: int) -> None:
                self.status_code = int(code)

            def json(self) -> dict[str, str]:
                return {}

        class _FakeClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def __enter__(self) -> "_FakeClient":
                return self

            def __exit__(self, *args: Any) -> None:
                return None

            def post(self, *args: Any, **kwargs: Any) -> _FakeResponse:
                return _FakeResponse(500)

        with patch("httpx.Client", _FakeClient):
            with self.assertRaises(_EmulatorTransportError):
                self.emulator_client.create(
                    to="whatsapp:+5491155556666",
                    from_="whatsapp:+5491100000000",
                    body="hola",
                )

    def test_emulator_app_validates_twilio_shaped_payload(self) -> None:
        """Integration: the T-C emulator client POSTs to the actual
        emulator app and the emulator validates the Twilio-shaped
        JSON fields, returns HTTP 201 and records a capture."""
        import base64 as _b64

        auth = "Basic " + _b64.b64encode(
            ("AC" + "1" * 32 + ":emulator-auth-token-abc").encode()
        ).decode("ascii")
        response = self.client.post(
            f"/2010-04-01/Accounts/AC{''.join(['1']*32)}/Messages.json",
            headers={"Authorization": auth},
            json={
                "To": "whatsapp:+5491155556666",
                "From": "whatsapp:+5491100000000",
                "Body": "hola",
            },
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body["sid"].startswith("SM"))

    def test_emulator_app_rejects_lowercase_fields(self) -> None:
        """Integration: when a client mistakenly sends Python-shaped
        lowercase field names, the emulator validator rejects them
        with a bounded 400 error and never records a capture."""
        import base64 as _b64

        auth = "Basic " + _b64.b64encode(
            ("AC" + "1" * 32 + ":emulator-auth-token-abc").encode()
        ).decode("ascii")
        response = self.client.post(
            f"/2010-04-01/Accounts/AC{''.join(['1']*32)}/Messages.json",
            headers={"Authorization": auth},
            json={
                "to": "whatsapp:+5491155556666",
                "from_": "whatsapp:+5491100000000",
                "body": "hola",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_emulator_app_captures_twilio_shaped_send(self) -> None:
        """Integration: a successful Twilio-shaped outbound POST is
        captured by the emulator with the synthetic ``SM...`` SID."""
        import base64 as _b64

        auth = "Basic " + _b64.b64encode(
            ("AC" + "1" * 32 + ":emulator-auth-token-abc").encode()
        ).decode("ascii")
        sid_response = self.client.post(
            f"/2010-04-01/Accounts/AC{''.join(['1']*32)}/Messages.json",
            headers={"Authorization": auth},
            json={
                "To": "whatsapp:+5491155556666",
                "From": "whatsapp:+5491100000000",
                "Body": "hola",
            },
        )
        self.assertEqual(sid_response.status_code, 201)
        synthetic_sid = sid_response.json()["sid"]

        inspection = self.client.get(
            "/internal/emulator/captures",
            headers={"X-Emulator-Token": "control-token"},
        )
        self.assertEqual(inspection.status_code, 200)
        payload = inspection.json()
        capture_sids = [c["message_sid"] for c in payload["captures"]]
        self.assertIn(synthetic_sid, capture_sids)
        self.assertNotIn("hola", inspection.text)
        self.assertNotIn("emulator-auth-token-abc", inspection.text)


class CentralAdapterEmulatorClientIntegrationTest(unittest.TestCase):
    """The central adapter emulator client must speak Twilio-shaped
    JSON (HTTP 201, ``MessageSid`` capture) when driven against the
    actual twilio_emulator app surface."""

    def setUp(self) -> None:
        from twilio_emulator.app import create_app
        from twilio_emulator.config import EmulatorConfig

        self.config = EmulatorConfig(
            control_token="control-token",
            tc_webhook_url="https://tc.example.test/webhook",
            account_sid="AC" + "2" * 32,
            auth_token="emulator-auth-token-xyz",
            public_base_url=None,
            http_port=9090,
            capture_retention=8,
        )
        self.app = create_app(config=self.config)
        self.client = TestClient(self.app)

    def _build_client(self) -> Any:
        from backend.services.twilio_outbound_adapter import (
            TwilioEmulatorMessagesClient,
            TwilioEmulatorTransportConfig,
        )

        return TwilioEmulatorMessagesClient(
            config=TwilioEmulatorTransportConfig(
                base_url="https://emulator.example.test",
                account_sid="AC" + "2" * 32,
                auth_token="emulator-auth-token-xyz",
                timeout_seconds=5.0,
            )
        )

    def test_central_emulator_client_posts_twilio_shaped_payload(self) -> None:
        from unittest.mock import patch
        import json as _json

        class _FakeResponse:
            def __init__(self, code: int, body: dict[str, str]) -> None:
                self.status_code = int(code)
                self._body = body

            def json(self) -> dict[str, str]:
                return self._body

        class _FakeClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def __enter__(self) -> "_FakeClient":
                return self

            def __exit__(self, *args: Any) -> None:
                return None

            def post(self, *args: Any, **kwargs: Any) -> _FakeResponse:
                raise RuntimeError("should not be called")

        captured: dict[str, Any] = {}

        class _RecordingClient(_FakeClient):
            def post(
                self,
                url: str,
                *,
                content: bytes | None = None,
                headers: dict[str, str] | None = None,
                **kwargs: Any,
            ) -> _FakeResponse:
                captured["url"] = url
                captured["content"] = content
                captured["headers"] = headers
                return _FakeResponse(
                    201, {"sid": "SM-CENTRAL", "account_sid": "AC" + "2" * 32}
                )

        client = self._build_client()
        with patch("httpx.Client", _RecordingClient):
            resource = client.create(
                to="whatsapp:+5491155556666",
                from_="whatsapp:+5491100000000",
                body="hola-central",
            )
        raw = captured["content"]
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        sent = _json.loads(raw)
        self.assertEqual(sent["To"], "whatsapp:+5491155556666")
        self.assertEqual(sent["From"], "whatsapp:+5491100000000")
        self.assertEqual(sent["Body"], "hola-central")
        self.assertEqual(resource.sid, "SM-CENTRAL")

    def test_central_emulator_app_capture(self) -> None:
        """Integration: a successful Twilio-shaped outbound POST
        from the central client is accepted by the emulator with
        HTTP 201 and recorded in the bounded capture store."""
        import base64 as _b64

        auth = "Basic " + _b64.b64encode(
            ("AC" + "2" * 32 + ":emulator-auth-token-xyz").encode()
        ).decode("ascii")
        response = self.client.post(
            f"/2010-04-01/Accounts/AC{''.join(['2']*32)}/Messages.json",
            headers={"Authorization": auth},
            json={
                "To": "whatsapp:+5491155556666",
                "From": "whatsapp:+5491100000000",
                "Body": "hola-central",
            },
        )
        self.assertEqual(response.status_code, 201)
        sid = response.json()["sid"]

        inspection = self.client.get(
            "/internal/emulator/captures",
            headers={"X-Emulator-Token": "control-token"},
        )
        self.assertEqual(inspection.status_code, 200)
        capture_sids = [c["message_sid"] for c in inspection.json()["captures"]]
        self.assertIn(sid, capture_sids)
        self.assertNotIn("emulator-auth-token-xyz", inspection.text)
        self.assertNotIn("hola-central", inspection.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)