"""Focused tests for the emulator service."""
from __future__ import annotations

import unittest

from twilio_emulator.captures import InMemoryCaptureStore
from twilio_emulator.config import EmulatorConfig
from twilio_emulator.service import (
    EmulatorAuthError,
    EmulatorService,
    EmulatorUnavailable,
    EmulatorValidationError,
    InboundControlCommand,
    build_emulator_service,
    build_outbound_response_body,
)
from twilio_emulator.signature import compute_form_signature


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
        self.calls: list[dict[str, object]] = []

    def __call__(self, *, url: str, form: dict[str, str], signature: str) -> None:
        self.calls.append({"url": url, "form": form, "signature": signature})


class InboundControlAuthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = _config()
        self.poster = _RecordingPoster()
        self.service = build_emulator_service(
            config=self.config, http_post=self.poster
        )

    def test_missing_control_token_rejects(self) -> None:
        with self.assertRaises(EmulatorAuthError):
            self.service.submit_inbound(
                presented_token=None,
                command=InboundControlCommand(
                    source_e164="+5491100000000",
                    destination_e164="+5491155556666",
                    body="hola",
                    synthetic_message_sid=None,
                ),
            )

    def test_wrong_control_token_rejects(self) -> None:
        with self.assertRaises(EmulatorAuthError):
            self.service.submit_inbound(
                presented_token="wrong",
                command=InboundControlCommand(
                    source_e164="+5491100000000",
                    destination_e164="+5491155556666",
                    body="hola",
                    synthetic_message_sid=None,
                ),
            )

    def test_valid_command_signs_complete_form(self) -> None:
        result = self.service.submit_inbound(
            presented_token="control-token",
            command=InboundControlCommand(
                source_e164="+5491100000000",
                destination_e164="+5491155556666",
                body="hola",
                synthetic_message_sid="SM-FIXED",
            ),
        )
        self.assertEqual(result.message_sid, "SM-FIXED")
        self.assertEqual(len(self.poster.calls), 1)
        call = self.poster.calls[0]
        self.assertEqual(call["url"], "https://tc.example.test/webhook")
        form = call["form"]
        assert isinstance(form, dict)
        self.assertEqual(form["MessageSid"], "SM-FIXED")
        self.assertEqual(form["From"], "whatsapp:+5491100000000")
        self.assertEqual(form["To"], "whatsapp:+5491155556666")
        self.assertEqual(form["Body"], "hola")
        self.assertEqual(form["AccountSid"], self.config.account_sid)
        expected_signature = compute_form_signature(
            auth_token=self.config.auth_token,
            url=self.config.tc_webhook_url,
            params=form,
        )
        self.assertEqual(call["signature"], expected_signature)

    def test_invalid_address_rejects(self) -> None:
        with self.assertRaises(EmulatorValidationError):
            self.service.submit_inbound(
                presented_token="control-token",
                command=InboundControlCommand(
                    source_e164="not-a-phone",
                    destination_e164="+5491155556666",
                    body="hola",
                    synthetic_message_sid=None,
                ),
            )

    def test_oversized_body_rejects(self) -> None:
        with self.assertRaises(EmulatorValidationError):
            self.service.submit_inbound(
                presented_token="control-token",
                command=InboundControlCommand(
                    source_e164="+5491100000000",
                    destination_e164="+5491155556666",
                    body="a" * 1025,
                    synthetic_message_sid=None,
                ),
            )

    def test_target_url_cannot_be_overridden(self) -> None:
        result = self.service.submit_inbound(
            presented_token="control-token",
            command=InboundControlCommand(
                source_e164="+5491100000000",
                destination_e164="+5491155556666",
                body="hola",
                synthetic_message_sid=None,
            ),
        )
        self.assertEqual(
            self.poster.calls[0]["url"],
            self.config.tc_webhook_url,
        )
        self.assertIn("MessageSid", result.submitted_form)


class InboundControlTransportTest(unittest.TestCase):
    def test_transport_failure_raises_bounded_exception(self) -> None:
        def _broken(**_kwargs: object) -> None:
            raise RuntimeError("connection refused")

        service = build_emulator_service(
            config=_config(), http_post=_broken
        )
        with self.assertRaises(EmulatorUnavailable):
            service.submit_inbound(
                presented_token="control-token",
                command=InboundControlCommand(
                    source_e164="+5491100000000",
                    destination_e164="+5491155556666",
                    body="hola",
                    synthetic_message_sid=None,
                ),
            )


class OutboundAcceptanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = _config()
        self.captures = InMemoryCaptureStore(capture_retention=4)
        self.service = build_emulator_service(
            config=self.config,
            http_post=_RecordingPoster(),
            captures=self.captures,
        )

    def test_returns_synthetic_message_sid(self) -> None:
        acceptance = self.service.accept_outbound(
            account_sid=self.config.account_sid,
            presented_auth_token=self.config.auth_token,
            to_address="whatsapp:+5491155556666",
            from_address="whatsapp:+5491100000000",
        )
        self.assertTrue(acceptance.message_sid.startswith("SM"))
        self.assertEqual(acceptance.account_sid, self.config.account_sid)

    def test_records_bounded_capture(self) -> None:
        self.service.accept_outbound(
            account_sid=self.config.account_sid,
            presented_auth_token=self.config.auth_token,
            to_address="whatsapp:+5491155556666",
            from_address="whatsapp:+5491100000000",
        )
        snapshot = self.captures.snapshot()
        self.assertEqual(len(snapshot), 1)
        capture = snapshot[0]
        self.assertEqual(capture.to_address, "whatsapp:+5491155556666")
        self.assertEqual(capture.from_address, "whatsapp:+5491100000000")
        self.assertNotIn("Body", capture.message_sid)
        self.assertNotIn("Body", capture.captured_at)

    def test_wrong_account_sid_rejects(self) -> None:
        with self.assertRaises(EmulatorAuthError):
            self.service.accept_outbound(
                account_sid="AC" + "1" * 32,
                presented_auth_token=self.config.auth_token,
                to_address="whatsapp:+5491155556666",
                from_address="whatsapp:+5491100000000",
            )

    def test_wrong_auth_token_rejects(self) -> None:
        with self.assertRaises(EmulatorAuthError):
            self.service.accept_outbound(
                account_sid=self.config.account_sid,
                presented_auth_token="wrong",
                to_address="whatsapp:+5491155556666",
                from_address="whatsapp:+5491100000000",
            )

    def test_missing_to_address_rejects(self) -> None:
        with self.assertRaises(EmulatorValidationError):
            self.service.accept_outbound(
                account_sid=self.config.account_sid,
                presented_auth_token=self.config.auth_token,
                to_address=None,
                from_address="whatsapp:+5491100000000",
            )

    def test_invalid_to_address_rejects(self) -> None:
        with self.assertRaises(EmulatorValidationError):
            self.service.accept_outbound(
                account_sid=self.config.account_sid,
                presented_auth_token=self.config.auth_token,
                to_address="not-a-phone",
                from_address="whatsapp:+5491100000000",
            )

    def test_capture_retention_is_bounded(self) -> None:
        for _ in range(8):
            self.service.accept_outbound(
                account_sid=self.config.account_sid,
                presented_auth_token=self.config.auth_token,
                to_address="whatsapp:+5491155556666",
                from_address="whatsapp:+5491100000000",
            )
        self.assertLessEqual(len(self.captures.snapshot()), 4)

    def test_response_body_never_contains_secrets(self) -> None:
        acceptance = self.service.accept_outbound(
            account_sid=self.config.account_sid,
            presented_auth_token=self.config.auth_token,
            to_address="whatsapp:+5491155556666",
            from_address="whatsapp:+5491100000000",
        )
        body = build_outbound_response_body(acceptance).decode("utf-8")
        self.assertNotIn(self.config.auth_token, body)
        self.assertNotIn(self.config.control_token, body)
        self.assertIn(acceptance.message_sid, body)


class InboundFormLoggingPrivacyTest(unittest.TestCase):
    def test_inbound_does_not_log_secrets(self) -> None:
        config = _config()
        poster = _RecordingPoster()
        service = build_emulator_service(
            config=config, http_post=poster
        )
        captured: list[str] = []

        class _Sink:
            def write(self, message: str) -> None:
                captured.append(message)

        import logging

        logger = logging.getLogger("twilio_emulator.service")
        previous_level = logger.level
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler(_Sink())
        logger.addHandler(handler)
        try:
            service.submit_inbound(
                presented_token="control-token",
                command=InboundControlCommand(
                    source_e164="+5491100000000",
                    destination_e164="+5491155556666",
                    body="hola",
                    synthetic_message_sid=None,
                ),
            )
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous_level)
        joined = "\n".join(captured)
        self.assertNotIn(config.auth_token, joined)
        self.assertNotIn("control-token", joined)
        self.assertNotIn("hola", joined)


__all__ = ["EmulatorService"]