"""Focused tests for the emulator FastAPI application."""
from __future__ import annotations

import base64
import unittest
from typing import Any, Self
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from twilio_emulator.app import create_app
from twilio_emulator.config import EmulatorConfig


def _config() -> EmulatorConfig:
    return EmulatorConfig(
        control_token="control-token",
        tc_webhook_url="https://tc.example.test/webhook",
        account_sid="AC" + "0" * 32,
        auth_token="auth-token-1234567890",
        public_base_url=None,
        http_port=9090,
        capture_retention=8,
    )


class _RecordingPoster:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *, url: str, form: dict[str, str], signature: str) -> None:
        self.calls.append({"url": url, "form": dict(form), "signature": signature})


def _build_app(
    *,
    http_post: Any = None,
) -> tuple[FastAPI, TestClient, _RecordingPoster]:
    poster = http_post or _RecordingPoster()
    app = create_app(config=_config(), http_post=poster)
    return app, TestClient(app), poster


def _basic_auth_header(account_sid: str, auth_token: str) -> str:
    raw = f"{account_sid}:{auth_token}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


class EmulatorHealthTest(unittest.TestCase):
    def test_health_does_not_expose_secrets(self) -> None:
        _app, client, _poster = _build_app()
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        emulator_section = body["emulator"]
        self.assertNotIn("control_token", emulator_section)
        self.assertNotIn("auth_token", emulator_section)
        self.assertEqual(emulator_section["account_sid"], "AC" + "0" * 32)


class EmulatorInboundRouteTest(unittest.TestCase):
    def test_happy_path_signs_and_posts_complete_form(self) -> None:
        _app, client, poster = _build_app()
        response = client.post(
            "/internal/emulator/inbound",
            headers={"X-Emulator-Token": "control-token"},
            json={
                "source_e164": "+5491100000000",
                "destination_e164": "+5491155556666",
                "body": "hola",
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "accepted")
        self.assertEqual(len(poster.calls), 1)
        call = poster.calls[0]
        self.assertEqual(call["url"], "https://tc.example.test/webhook")
        self.assertEqual(call["form"]["Body"], "hola")
        self.assertEqual(call["form"]["From"], "whatsapp:+5491100000000")
        self.assertEqual(call["form"]["To"], "whatsapp:+5491155556666")
        self.assertTrue(call["signature"])

    def test_target_url_cannot_be_overridden_by_request(self) -> None:
        _app, client, poster = _build_app()
        response = client.post(
            "/internal/emulator/inbound",
            headers={"X-Emulator-Token": "control-token"},
            json={
                "source_e164": "+5491100000000",
                "destination_e164": "+5491155556666",
                "body": "hola",
                "tc_webhook_url": "https://attacker.example/webhook",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(poster.calls[0]["url"], "https://tc.example.test/webhook")

    def test_missing_control_token_returns_401(self) -> None:
        _app, client, poster = _build_app()
        response = client.post(
            "/internal/emulator/inbound",
            json={
                "source_e164": "+5491100000000",
                "destination_e164": "+5491155556666",
                "body": "hola",
            },
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(poster.calls, [])

    def test_invalid_address_returns_400(self) -> None:
        _app, client, poster = _build_app()
        response = client.post(
            "/internal/emulator/inbound",
            headers={"X-Emulator-Token": "control-token"},
            json={
                "source_e164": "not-a-phone",
                "destination_e164": "+5491155556666",
                "body": "hola",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(poster.calls, [])

    def test_transport_failure_returns_502(self) -> None:
        def _broken(**_kwargs: object) -> None:
            raise RuntimeError("connection refused")

        _app, client, _poster = _build_app(http_post=_broken)
        response = client.post(
            "/internal/emulator/inbound",
            headers={"X-Emulator-Token": "control-token"},
            json={
                "source_e164": "+5491100000000",
                "destination_e164": "+5491155556666",
                "body": "hola",
            },
        )
        self.assertEqual(response.status_code, 502)


class EmulatorInboundTransportHttpStatusTest(unittest.TestCase):
    """The default ``_http_post`` treats every non-2xx HTTP response
    from the T-C webhook as a transport failure: it raises
    :class:`EmulatorUnavailable` so the inbound control surface
    returns a bounded ``502`` and never reports ``accepted``."""

    def _build_client(self, status_code: int) -> tuple[TestClient, list[dict[str, Any]]]:
        from twilio_emulator.service import EmulatorUnavailable

        captured: list[dict[str, Any]] = []

        def _status_aware_post(
            url: str, *, form: dict[str, str], signature: str
        ) -> None:
            captured.append(
                {"url": url, "form": dict(form), "signature": signature}
            )
            if status_code < 200 or status_code >= 300:
                raise EmulatorUnavailable(
                    "t-c webhook did not accept the signed form"
                )

        app = create_app(config=_config(), http_post=_status_aware_post)
        return TestClient(app), captured

    def test_403_response_returns_502_and_never_accepted(self) -> None:
        client, _captured = self._build_client(403)
        response = client.post(
            "/internal/emulator/inbound",
            headers={"X-Emulator-Token": "control-token"},
            json={
                "source_e164": "+5491100000000",
                "destination_e164": "+5491155556666",
                "body": "hola",
            },
        )
        self.assertEqual(response.status_code, 502)
        body = response.json()
        self.assertNotEqual(body.get("detail"), "accepted")
        self.assertNotEqual(body.get("status"), "accepted")

    def test_500_response_returns_502_and_never_accepted(self) -> None:
        client, _captured = self._build_client(500)
        response = client.post(
            "/internal/emulator/inbound",
            headers={"X-Emulator-Token": "control-token"},
            json={
                "source_e164": "+5491100000000",
                "destination_e164": "+5491155556666",
                "body": "hola",
            },
        )
        self.assertEqual(response.status_code, 502)
        body = response.json()
        self.assertNotEqual(body.get("detail"), "accepted")
        self.assertNotEqual(body.get("status"), "accepted")

    def test_2xx_response_is_still_accepted(self) -> None:
        client, _captured = self._build_client(200)
        response = client.post(
            "/internal/emulator/inbound",
            headers={"X-Emulator-Token": "control-token"},
            json={
                "source_e164": "+5491100000000",
                "destination_e164": "+5491155556666",
                "body": "hola",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "accepted")

    def test_default_http_post_treats_non_2xx_as_unavailable(self) -> None:
        """The default ``_http_post`` helper itself must raise
        :class:`EmulatorUnavailable` for a non-2xx response and for a
        transport failure. The test stubs ``httpx.Client`` so no real
        network call is made.
        """

        from twilio_emulator.app import _http_post
        from twilio_emulator.service import EmulatorUnavailable

        class _FakeResponse:
            def __init__(self, code: int) -> None:
                self.status_code = int(code)

        class _FakeClient:
            def __init__(self, code: int) -> None:
                self._code = int(code)

            def __enter__(self) -> Self:
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def post(self, *args: Any, **kwargs: Any) -> _FakeResponse:
                return _FakeResponse(self._code)

        for code in (403, 500, 502, 504):
            with self.subTest(status_code=code):
                fake = _FakeClient(code)
                with patch("httpx.Client", return_value=fake):
                    with self.assertRaises(EmulatorUnavailable):
                        _http_post(
                            "https://tc.example.test/webhook",
                            form={"Body": "x"},
                            signature="sig",
                        )

        fake = _FakeClient(200)
        with patch("httpx.Client", return_value=fake):
            try:
                _http_post(
                    "https://tc.example.test/webhook",
                    form={"Body": "x"},
                    signature="sig",
                )
            except EmulatorUnavailable:
                self.fail("2xx response should not raise")


class EmulatorOutboundRouteTest(unittest.TestCase):
    def _build(self):
        config = _config()
        app = create_app(config=config, http_post=_RecordingPoster())
        client = TestClient(app)
        return app, client, config

    def test_valid_credentials_return_synthetic_message_sid(self) -> None:
        _app, client, config = self._build()
        response = client.post(
            f"/2010-04-01/Accounts/{config.account_sid}/Messages.json",
            headers={
                "Authorization": _basic_auth_header(
                    config.account_sid, config.auth_token
                )
            },
            json={
                "To": "whatsapp:+5491155556666",
                "From": "whatsapp:+5491100000000",
                "Body": "hola",
            },
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body["sid"].startswith("SM"))
        self.assertEqual(body["account_sid"], config.account_sid)
        self.assertNotIn("auth_token", body)
        self.assertNotIn("Body", body)

    def test_wrong_auth_token_returns_401(self) -> None:
        _app, client, config = self._build()
        response = client.post(
            f"/2010-04-01/Accounts/{config.account_sid}/Messages.json",
            headers={
                "Authorization": _basic_auth_header(config.account_sid, "wrong")
            },
            json={
                "To": "whatsapp:+5491155556666",
                "From": "whatsapp:+5491100000000",
            },
        )
        self.assertEqual(response.status_code, 401)

    def test_invalid_destination_returns_400(self) -> None:
        _app, client, config = self._build()
        response = client.post(
            f"/2010-04-01/Accounts/{config.account_sid}/Messages.json",
            headers={
                "Authorization": _basic_auth_header(
                    config.account_sid, config.auth_token
                )
            },
            json={
                "To": "not-a-phone",
                "From": "whatsapp:+5491100000000",
            },
        )
        self.assertEqual(response.status_code, 400)


class EmulatorCapturesInspectionTest(unittest.TestCase):
    def test_inspection_requires_control_token(self) -> None:
        _app, client, _config = _build_app()
        response = client.get("/internal/emulator/captures")
        self.assertEqual(response.status_code, 401)

    def test_inspection_returns_bounded_projection(self) -> None:
        config = _config()
        app = create_app(config=config, http_post=_RecordingPoster())
        client = TestClient(app)
        for _ in range(2):
            client.post(
                f"/2010-04-01/Accounts/{config.account_sid}/Messages.json",
                headers={
                    "Authorization": _basic_auth_header(
                        config.account_sid, config.auth_token
                    )
                },
                json={
                    "To": "whatsapp:+5491155556666",
                    "From": "whatsapp:+5491100000000",
                },
            )
        response = client.get(
            "/internal/emulator/captures",
            headers={"X-Emulator-Token": "control-token"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(len(body["captures"]), 2)
        capture = body["captures"][0]
        self.assertNotIn("body", capture)
        self.assertNotIn("Body", capture)
        self.assertNotIn(config.auth_token, response.text)


__all__ = []