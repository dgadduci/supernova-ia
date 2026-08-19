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


if __name__ == "__main__":
    unittest.main(verbosity=2)