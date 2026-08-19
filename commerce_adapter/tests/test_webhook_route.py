"""Focused tests for the T-C adapter webhook route.

The tests cover:

* valid signature → 200 empty TwiML and one forward call to NovaOrders;
* tampered signature → 403, no forward call;
* missing signature → 403, no forward call;
* missing Twilio required field → 200 empty TwiML, no forward call;
* NovaOrders unreachable → 502, no TwiML;
* NovaOrders acceptance → 200 empty TwiML;
* NovaOrders rejection → 200 empty TwiML (durable no-op);
* duplicate ``MessageSid`` → 200 empty TwiML;
* the canonical contract sent to NovaOrders has no raw Twilio field
  names;
* the logs never contain the body, phone, signature or token.

The tests inject a fake HTTP client (the production
``forward_event`` accepts an ``http_client`` argument) so no real
network call is performed.
"""
from __future__ import annotations

import json
import logging
import unittest
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from commerce_adapter.app.config import (
    CommerceAdapterConfig,
    CommerceAdapterConfigError,
    load_config_from_env,
)
from commerce_adapter.app.routes import webhook as webhook_route
from commerce_adapter.app.security import compute_twilio_signature

TOKEN: str = "test-auth-token"
BASE_URL: str = "https://example.test"
WEBHOOK_PATH: str = webhook_route.ROUTE_PATH
INSTALLATION_ID: str = "a" * 24
COMERCIO_ID: int = 7
INSTALLATION_SECRET: str = "shared-secret-1234"
NOVAORDERS_URL: str = "https://core.example.test"


def _config() -> CommerceAdapterConfig:
    env = {
        "TC_TWILIO_AUTH_TOKEN": TOKEN,
        "TC_TWILIO_ACCOUNT_SID": "AC" + "0" * 32,
        "TC_TWILIO_WEBHOOK_BASE_URL": BASE_URL,
        "TC_NOVAORDERS_INGRESS_URL": NOVAORDERS_URL,
        "TC_INSTALLATION_ID": INSTALLATION_ID,
        "TC_INSTALLATION_SECRET": INSTALLATION_SECRET,
        "TC_COMERCIO_ID": str(COMERCIO_ID),
        "TC_TWILIO_SENDER_E164": "+15555555555",
    }
    return load_config_from_env(env)


class _FakeResponse:
    def __init__(self, *, status_code: int, body: dict | None = None) -> None:
        self.status_code = int(status_code)
        self._body = body or {}

    def json(self) -> Any:
        return self._body


class _FakeHttpClient:
    """Stub ``httpx.Client`` that records every call."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, content: bytes, headers: dict[str, str]) -> _FakeResponse:
        self.calls.append({"url": url, "content": bytes(content), "headers": dict(headers)})
        if not self._responses:
            raise AssertionError("no stub response configured")
        return self._responses.pop(0)

    def close(self) -> None:
        pass


def _build_client(
    *,
    responses: list[_FakeResponse] | None = None,
) -> tuple[TestClient, _FakeHttpClient]:
    fake = _FakeHttpClient(responses or [_FakeResponse(status_code=200, body={"status": "accepted", "receipt_id": 42})])
    app = FastAPI()
    app.include_router(webhook_route.router)

    from commerce_adapter.app.dependencies import build_config_dependency
    app.dependency_overrides[build_config_dependency] = _config

    def _fake_forward_event(*, config: CommerceAdapterConfig, event: Any, http_client: httpx.Client | None = None):
        from commerce_adapter.app.novaorders_client import forward_event as real_forward

        return real_forward(config=config, event=event, http_client=fake)

    from commerce_adapter.app.routes import webhook as wh_mod
    app.dependency_overrides[wh_mod._resolve_forward_event] = lambda: _fake_forward_event

    return TestClient(app), fake


def _sign(form: dict[str, str]) -> str:
    return compute_twilio_signature(
        auth_token=TOKEN,
        url=f"{BASE_URL}{WEBHOOK_PATH}",
        params=form,
    )


class WebhookHappyPathTest(unittest.TestCase):
    def setUp(self) -> None:
        self.form = {
            "MessageSid": "SM-ABC",
            "From": "whatsapp:+5491155556666",
            "To": "whatsapp:+5491100000000",
            "Body": "hola",
            "NumMedia": "0",
            "ProfileName": "Ana",
        }
        self.signature = _sign(self.form)
        self.client, self.fake = _build_client()

    def test_first_delivery_returns_empty_twiml(self) -> None:
        response = self.client.post(
            WEBHOOK_PATH,
            data=self.form,
            headers={"X-Twilio-Signature": self.signature},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/xml", response.headers["content-type"])
        self.assertIn("<Response></Response>", response.text)
        self.assertNotIn("<Message>", response.text)
        self.assertEqual(len(self.fake.calls), 1)
        call = self.fake.calls[0]
        self.assertNotEqual(call["headers"]["X-Installation-Signature"], "")
        body = json.loads(call["content"].decode("utf-8"))
        self.assertEqual(body["instalacion_id"], INSTALLATION_ID)
        self.assertEqual(body["comercio_id"], COMERCIO_ID)
        self.assertEqual(body["proveedor"], "twilio")
        self.assertEqual(body["message_sid"], "SM-ABC")
        self.assertEqual(body["from_e164"], "+5491155556666")
        self.assertEqual(body["to_e164"], "+5491100000000")
        self.assertEqual(body["cuerpo"], "hola")
        self.assertEqual(body["num_media"], 0)
        self.assertEqual(len(body["profile_name_hash"]), 32)
        self.assertNotIn("Ana", body["profile_name_hash"])

    def test_query_string_is_forwarded_to_signature(self) -> None:
        signature = compute_twilio_signature(
            auth_token=TOKEN,
            url=f"{BASE_URL}{WEBHOOK_PATH}?hub=1",
            params=self.form,
        )
        response = self.client.post(
            f"{WEBHOOK_PATH}?hub=1",
            data=self.form,
            headers={"X-Twilio-Signature": signature},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("<Response></Response>", response.text)


class WebhookSignatureFailureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.form = {
            "MessageSid": "SM-ABC",
            "From": "whatsapp:+5491155556666",
            "To": "whatsapp:+5491100000000",
            "Body": "hola",
        }
        self.signature = _sign(self.form)
        self.client, self.fake = _build_client()

    def test_missing_signature_returns_403(self) -> None:
        response = self.client.post(WEBHOOK_PATH, data=self.form)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.text, "")
        self.assertEqual(self.fake.calls, [])

    def test_tampered_body_returns_403(self) -> None:
        tampered = dict(self.form)
        tampered["Body"] = "adulterado"
        response = self.client.post(
            WEBHOOK_PATH,
            data=tampered,
            headers={"X-Twilio-Signature": self.signature},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.fake.calls, [])

    def test_wrong_signature_returns_403(self) -> None:
        wrong = "0" * 40
        response = self.client.post(
            WEBHOOK_PATH,
            data=self.form,
            headers={"X-Twilio-Signature": wrong},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.fake.calls, [])


class WebhookFormRejectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self.fake = _build_client()

    def test_missing_required_field_returns_empty_twiml(self) -> None:
        form = {
            "From": "whatsapp:+5491155556666",
            "To": "whatsapp:+5491100000000",
            "Body": "hola",
        }
        signature = _sign(form)
        response = self.client.post(
            WEBHOOK_PATH,
            data=form,
            headers={"X-Twilio-Signature": signature},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("<Response></Response>", response.text)
        self.assertEqual(self.fake.calls, [])

    def test_invalid_e164_returns_empty_twiml(self) -> None:
        form = {
            "MessageSid": "SM-ABC",
            "From": "not-a-phone",
            "To": "whatsapp:+5491100000000",
            "Body": "hola",
        }
        signature = _sign(form)
        response = self.client.post(
            WEBHOOK_PATH,
            data=form,
            headers={"X-Twilio-Signature": signature},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("<Response></Response>", response.text)
        self.assertEqual(self.fake.calls, [])


class WebhookNovaOrdersRejectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.form = {
            "MessageSid": "SM-ABC",
            "From": "whatsapp:+5491155556666",
            "To": "whatsapp:+5491100000000",
            "Body": "hola",
        }
        self.signature = _sign(self.form)

    def _build_with_response(self, body: dict, status_code: int = 200) -> tuple[TestClient, _FakeHttpClient]:
        return _build_client(responses=[_FakeResponse(status_code=status_code, body=body)])

    def test_novaorders_rejected_returns_empty_twiml(self) -> None:
        client, fake = self._build_with_response(
            {"status": "rejected", "reason": "unknown_destination"}
        )
        response = client.post(
            WEBHOOK_PATH,
            data=self.form,
            headers={"X-Twilio-Signature": self.signature},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("<Response></Response>", response.text)
        self.assertEqual(len(fake.calls), 1)

    def test_novaorders_duplicate_returns_empty_twiml(self) -> None:
        client, _ = self._build_with_response({"status": "duplicate"})
        response = client.post(
            WEBHOOK_PATH,
            data=self.form,
            headers={"X-Twilio-Signature": self.signature},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("<Response></Response>", response.text)


class WebhookNovaOrdersUnreachableTest(unittest.TestCase):
    def setUp(self) -> None:
        self.form = {
            "MessageSid": "SM-ABC",
            "From": "whatsapp:+5491155556666",
            "To": "whatsapp:+5491100000000",
            "Body": "hola",
        }
        self.signature = _sign(self.form)
        self.client, _ = _build_client(
            responses=[_FakeResponse(status_code=500, body={})]
        )

    def test_5xx_returns_502_without_twiml(self) -> None:
        response = self.client.post(
            WEBHOOK_PATH,
            data=self.form,
            headers={"X-Twilio-Signature": self.signature},
        )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.text, "")


class WebhookCanonicalContractTest(unittest.TestCase):
    def test_no_twilio_field_names_in_payload(self) -> None:
        form = {
            "MessageSid": "SM-ABC",
            "From": "whatsapp:+5491155556666",
            "To": "whatsapp:+5491100000000",
            "Body": "hola",
            "AccountSid": "AC-EXTRA",
            "ApiVersion": "2010-04-01",
        }
        signature = _sign(form)
        client, fake = _build_client()
        response = client.post(
            WEBHOOK_PATH,
            data=form,
            headers={"X-Twilio-Signature": signature},
        )
        self.assertEqual(response.status_code, 200)
        body = json.loads(fake.calls[0]["content"].decode("utf-8"))
        forbidden = {
            "MessageSid",
            "From",
            "To",
            "Body",
            "AccountSid",
            "ApiVersion",
            "SmsMessageSid",
            "NumMedia",
            "ProfileName",
            "SmsStatus",
            "MessagingServiceSid",
            "WaId",
            "SmsSid",
            "MediaContentType0",
        }
        for key in forbidden:
            self.assertNotIn(key, body)


class WebhookSecurityLogTest(unittest.TestCase):
    def test_logs_do_not_contain_body_phone_token(self) -> None:
        form = {
            "MessageSid": "SM-SECRET",
            "From": "whatsapp:+5491155556666",
            "To": "whatsapp:+5491100000000",
            "Body": "this-body-must-never-appear-in-logs",
        }
        signature = _sign(form)
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
                WEBHOOK_PATH,
                data=form,
                headers={"X-Twilio-Signature": signature},
            )
        finally:
            logger.removeHandler(capture)

        joined = "\n".join(
            str(rec.getMessage()) + " " + repr(rec.__dict__) for rec in handler_records
        )
        self.assertNotIn("this-body-must-never-appear-in-logs", joined)
        self.assertNotIn("+5491155556666", joined)
        self.assertNotIn("shared-secret-1234", joined)
        self.assertNotIn(signature, joined)
        self.assertNotIn(INSTALLATION_SECRET, joined)


class ConfigLoaderTest(unittest.TestCase):
    def test_missing_token_raises(self) -> None:
        env = {
            "TC_TWILIO_ACCOUNT_SID": "AC" + "0" * 32,
            "TC_TWILIO_WEBHOOK_BASE_URL": BASE_URL,
            "TC_NOVAORDERS_INGRESS_URL": NOVAORDERS_URL,
            "TC_INSTALLATION_ID": INSTALLATION_ID,
            "TC_INSTALLATION_SECRET": INSTALLATION_SECRET,
        }
        with self.assertRaises(CommerceAdapterConfigError):
            load_config_from_env(env)

    def test_invalid_account_sid_raises(self) -> None:
        env = {
            "TC_TWILIO_AUTH_TOKEN": TOKEN,
            "TC_TWILIO_ACCOUNT_SID": "BAD",
            "TC_TWILIO_WEBHOOK_BASE_URL": BASE_URL,
            "TC_NOVAORDERS_INGRESS_URL": NOVAORDERS_URL,
            "TC_INSTALLATION_ID": INSTALLATION_ID,
            "TC_INSTALLATION_SECRET": INSTALLATION_SECRET,
        }
        with self.assertRaises(CommerceAdapterConfigError):
            load_config_from_env(env)

    def test_invalid_installation_id_raises(self) -> None:
        env = {
            "TC_TWILIO_AUTH_TOKEN": TOKEN,
            "TC_TWILIO_ACCOUNT_SID": "AC" + "0" * 32,
            "TC_TWILIO_WEBHOOK_BASE_URL": BASE_URL,
            "TC_NOVAORDERS_INGRESS_URL": NOVAORDERS_URL,
            "TC_INSTALLATION_ID": "ZZZ",
            "TC_INSTALLATION_SECRET": INSTALLATION_SECRET,
        }
        with self.assertRaises(CommerceAdapterConfigError):
            load_config_from_env(env)

    def test_http_url_required(self) -> None:
        env = {
            "TC_TWILIO_AUTH_TOKEN": TOKEN,
            "TC_TWILIO_ACCOUNT_SID": "AC" + "0" * 32,
            "TC_TWILIO_WEBHOOK_BASE_URL": "http://example.test",
            "TC_NOVAORDERS_INGRESS_URL": NOVAORDERS_URL,
            "TC_INSTALLATION_ID": INSTALLATION_ID,
            "TC_INSTALLATION_SECRET": INSTALLATION_SECRET,
        }
        with self.assertRaises(CommerceAdapterConfigError):
            load_config_from_env(env)


if __name__ == "__main__":
    unittest.main(verbosity=2)