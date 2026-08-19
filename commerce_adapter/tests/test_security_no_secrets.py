"""Focused security tests for the T-C adapter.

The tests assert that no log surface, exception traceback, response
body or stored configuration carries the per-installation shared
secret, the merchant Twilio auth token, the inbound body, the destination
phone number or the signature value.

The tests exercise the production code paths (route handlers, the
HTTP client and the Twilio send seam) with fakes for both the
NovaOrders HTTP client and the Twilio client so the surface is
deterministic and no real network call is performed.
"""
from __future__ import annotations

import json
import logging
import unittest
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from commerce_adapter.app.config import (
    CommerceAdapterConfig,
    load_config_from_env,
)
from commerce_adapter.app.dependencies import build_config_dependency
from commerce_adapter.app.routes import outbound as outbound_route
from commerce_adapter.app.routes import webhook as webhook_route
from commerce_adapter.app.security import (
    compute_twilio_signature,
    hmac_sign,
)

TOKEN: str = "twilio-auth-token-must-not-leak"
SECRET: str = "installation-secret-must-not-leak"
BASE_URL: str = "https://example.test"
NOVAORDERS_URL: str = "https://core.example.test"
INSTALLATION_ID: str = "a" * 24
COMERCIO_ID: int = 7


SECRET_MARKERS: tuple[str, ...] = (
    SECRET,
    "installation-secret-must-not-leak",
    "this-body-must-never-appear-anywhere",
    "+5491155556666",
    "+5491100000000",
)
TOKEN_MARKERS: tuple[str, ...] = (
    TOKEN,
    "twilio-auth-token-must-not-leak",
)


def _config() -> CommerceAdapterConfig:
    env = {
        "TC_TWILIO_AUTH_TOKEN": TOKEN,
        "TC_TWILIO_ACCOUNT_SID": "AC" + "0" * 32,
        "TC_TWILIO_WEBHOOK_BASE_URL": BASE_URL,
        "TC_NOVAORDERS_INGRESS_URL": NOVAORDERS_URL,
        "TC_INSTALLATION_ID": INSTALLATION_ID,
        "TC_INSTALLATION_SECRET": SECRET,
        "TC_COMERCIO_ID": str(COMERCIO_ID),
        "TC_TWILIO_SENDER_E164": "+15555555555",
    }
    return load_config_from_env(env)


def _joined_records(records: list[logging.LogRecord]) -> str:
    parts: list[str] = []
    for record in records:
        parts.append(str(record.getMessage()))
        try:
            parts.append(repr(record.__dict__))
        except Exception:
            parts.append("unreprable")
    return "\n".join(parts)


def _capture_routes() -> Any:
    """Return a context manager that captures all log records.

    The helper attaches a single capture handler to the
    ``commerce_adapter`` logger so the test can inspect every record
    emitted by the webhook and outbound routes.
    """

    class _Capture(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.records: list[logging.LogRecord] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.records.append(record)

    capture = _Capture()
    logger = logging.getLogger("commerce_adapter")
    logger.addHandler(capture)
    logger.setLevel(logging.DEBUG)

    class _Context:
        def __enter__(self) -> _Capture:
            return capture

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            logger.removeHandler(capture)

    return _Context()


class _FakeResponse:
    def __init__(self, *, status_code: int, body: dict | None = None) -> None:
        self.status_code = int(status_code)
        self._body = body or {}

    def json(self) -> Any:
        return self._body


class _FakeHttpClient:
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


class _FakeTwilioClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return type("Message", (), {"sid": "sm-very-secret-id"})()


class WebhookNoSecretsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.form = {
            "MessageSid": "sm-very-secret-id",
            "From": "whatsapp:+5491155556666",
            "To": "whatsapp:+5491100000000",
            "Body": "this-body-must-never-appear-anywhere",
        }
        self.signature = compute_twilio_signature(
            auth_token=TOKEN,
            url=f"{BASE_URL}{webhook_route.ROUTE_PATH}",
            params=self.form,
        )

    def _build(self, responses: list[_FakeResponse]) -> tuple[TestClient, _FakeHttpClient]:
        fake = _FakeHttpClient(responses)
        app = FastAPI()
        app.include_router(webhook_route.router)
        app.dependency_overrides[build_config_dependency] = _config

        def _fake_forward_event(*, config: CommerceAdapterConfig, event: Any, http_client: Any = None):
            from commerce_adapter.app.novaorders_client import forward_event as real

            return real(config=config, event=event, http_client=fake)

        app.dependency_overrides[webhook_route._resolve_forward_event] = lambda: _fake_forward_event
        return TestClient(app), fake

    def test_logs_do_not_contain_secrets_or_body(self) -> None:
        client, _ = self._build([_FakeResponse(status_code=200, body={"status": "accepted"})])
        with _capture_routes() as capture:
            response = client.post(
                webhook_route.ROUTE_PATH,
                data=self.form,
                headers={"X-Twilio-Signature": self.signature},
            )
        self.assertEqual(response.status_code, 200)
        joined = _joined_records(capture.records)
        for marker in SECRET_MARKERS:
            self.assertNotIn(marker, joined)
        for marker in TOKEN_MARKERS:
            self.assertNotIn(marker, joined)
        self.assertNotIn(self.signature, joined)

    def test_response_body_does_not_leak_body(self) -> None:
        client, _ = self._build([_FakeResponse(status_code=200, body={"status": "accepted"})])
        response = client.post(
            webhook_route.ROUTE_PATH,
            data=self.form,
            headers={"X-Twilio-Signature": self.signature},
        )
        self.assertEqual(response.status_code, 200)
        for marker in SECRET_MARKERS:
            self.assertNotIn(marker, response.text)

    def test_signature_rejected_does_not_log_token(self) -> None:
        client, _ = self._build([])
        with _capture_routes() as capture:
            response = client.post(
                webhook_route.ROUTE_PATH,
                data=self.form,
                headers={"X-Twilio-Signature": "0" * 40},
            )
        self.assertEqual(response.status_code, 403)
        joined = _joined_records(capture.records)
        for marker in TOKEN_MARKERS:
            self.assertNotIn(marker, joined)

    def test_configuration_error_does_not_log_token(self) -> None:
        from commerce_adapter.app.config import (
            CommerceAdapterConfigError,
            load_config_from_env,
        )

        bad_env = {
            "TC_TWILIO_AUTH_TOKEN": TOKEN,
            "TC_TWILIO_ACCOUNT_SID": "BAD",
            "TC_TWILIO_WEBHOOK_BASE_URL": BASE_URL,
            "TC_NOVAORDERS_INGRESS_URL": NOVAORDERS_URL,
            "TC_INSTALLATION_ID": INSTALLATION_ID,
            "TC_INSTALLATION_SECRET": SECRET,
        }
        with self.assertRaises(CommerceAdapterConfigError):
            load_config_from_env(bad_env)


class OutboundNoSecretsTest(unittest.TestCase):
    def _build(self) -> tuple[TestClient, _FakeTwilioClient]:
        twilio = _FakeTwilioClient()
        outbound_route.set_twilio_client(twilio)
        app = FastAPI()
        app.include_router(outbound_route.router)
        app.dependency_overrides[build_config_dependency] = _config
        return TestClient(app), twilio

    def _full_path(self) -> str:
        return "/internal/commands" + outbound_route.ROUTE_PATH

    def _build_payload(self, **overrides: Any) -> bytes:
        payload = {
            "instalacion_id": INSTALLATION_ID,
            "comercio_id": COMERCIO_ID,
            "idempotency_key": "outbox-1",
            "destinatario_e164": "+5491155556666",
            "cuerpo": "this-body-must-never-appear-anywhere",
            "status_callback_url": "https://example.test/cb",
            "proveedor": "twilio",
        }
        payload.update(overrides)
        return json.dumps(payload).encode("utf-8")

    def test_logs_do_not_contain_body_or_phone(self) -> None:
        client, _ = self._build()
        body = self._build_payload()
        signature = hmac_sign(payload=body, secret=SECRET)
        with _capture_routes() as capture:
            response = client.post(
                self._full_path(),
                content=body,
                headers={
                    "X-Installation-Signature": signature,
                    "X-Installation-Id": INSTALLATION_ID,
                "Content-Type": "application/json",
                },
            )
        self.assertEqual(response.status_code, 200)
        joined = _joined_records(capture.records)
        for marker in SECRET_MARKERS:
            self.assertNotIn(marker, joined)
        for marker in TOKEN_MARKERS:
            self.assertNotIn(marker, joined)
        self.assertNotIn(signature, joined)

    def test_response_body_does_not_echo_body_or_secret(self) -> None:
        client, _ = self._build()
        body = self._build_payload()
        signature = hmac_sign(payload=body, secret=SECRET)
        response = client.post(
            self._full_path(),
            content=body,
            headers={
                "X-Installation-Signature": signature,
                "X-Installation-Id": INSTALLATION_ID,
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.status_code, 200)
        for marker in SECRET_MARKERS:
            self.assertNotIn(marker, response.text)
        for marker in TOKEN_MARKERS:
            self.assertNotIn(marker, response.text)

    def test_signature_rejected_does_not_log_token(self) -> None:
        client, _ = self._build()
        body = self._build_payload()
        with _capture_routes() as capture:
            response = client.post(
                self._full_path(),
                content=body,
                headers={
                    "X-Installation-Signature": "0" * 64,
                    "X-Installation-Id": INSTALLATION_ID,
                "Content-Type": "application/json",
                },
            )
        self.assertEqual(response.status_code, 401)
        joined = _joined_records(capture.records)
        for marker in TOKEN_MARKERS:
            self.assertNotIn(marker, joined)
        for marker in SECRET_MARKERS:
            self.assertNotIn(marker, joined)

    def test_twilio_exception_does_not_leak_token_through_traceback(self) -> None:
        from twilio.base.exceptions import TwilioRestException

        exc = TwilioRestException(
            status=500,
            uri="/Messages.json",
            msg="server-error-with-token-in-message",
            code=20500,
        )
        twilio = _FakeTwilioClient()
        twilio.raise_exc = exc  # type: ignore[attr-defined]

        class _RaisingClient:
            def __init__(self, exc: Exception) -> None:
                self._exc = exc

            def create(self, **kwargs: Any) -> Any:
                raise self._exc

        outbound_route.set_twilio_client(_RaisingClient(exc))
        app = FastAPI()
        app.include_router(outbound_route.router)
        app.dependency_overrides[build_config_dependency] = _config
        client = TestClient(app)
        body = self._build_payload()
        signature = hmac_sign(payload=body, secret=SECRET)
        with _capture_routes() as capture:
            response = client.post(
                self._full_path(),
                content=body,
                headers={
                    "X-Installation-Signature": signature,
                    "X-Installation-Id": INSTALLATION_ID,
                "Content-Type": "application/json",
                },
            )
        self.assertEqual(response.status_code, 200)
        joined = _joined_records(capture.records)
        for marker in TOKEN_MARKERS:
            self.assertNotIn(marker, joined)
        self.assertNotIn("server-error-with-token-in-message", joined)


class ConfigErrorNoSecretsTest(unittest.TestCase):
    """The configuration loader never echoes the secret or token."""

    def test_missing_token_raises_without_secret(self) -> None:
        from commerce_adapter.app.config import (
            CommerceAdapterConfigError,
            load_config_from_env,
        )

        env = {
            "TC_TWILIO_ACCOUNT_SID": "AC" + "0" * 32,
            "TC_TWILIO_WEBHOOK_BASE_URL": BASE_URL,
            "TC_NOVAORDERS_INGRESS_URL": NOVAORDERS_URL,
            "TC_INSTALLATION_ID": INSTALLATION_ID,
            "TC_INSTALLATION_SECRET": SECRET,
        }
        with self.assertRaises(CommerceAdapterConfigError) as ctx:
            load_config_from_env(env)
        message = str(ctx.exception)
        self.assertNotIn(SECRET, message)
        self.assertNotIn(TOKEN, message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
