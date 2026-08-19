"""Focused tests for the T-C adapter security primitives.

The tests cover:

* HMAC sign/verify round-trip.
* HMAC verify rejects missing, malformed, wrong and tampered
  signatures.
* Twilio signature URL building rejects malformed paths and includes
  the actual query string.
* Twilio SDK signature verification accepts valid signatures and
  rejects tampered bodies.
"""
from __future__ import annotations

import unittest

from commerce_adapter.app.security import (
    assert_validation_path_safe,
    build_twilio_validation_url,
    compute_twilio_signature,
    hmac_sign,
    hmac_verify,
    validate_twilio_signature,
)

SECRET: str = "shhh"
PAYLOAD: bytes = b'{"hello":"world"}'


class HmacRoundTripTest(unittest.TestCase):
    def test_sign_returns_lowercase_hex_digest(self) -> None:
        signature = hmac_sign(payload=PAYLOAD, secret=SECRET)
        self.assertEqual(len(signature), 64)
        self.assertTrue(all(ch in "0123456789abcdef" for ch in signature))

    def test_verify_accepts_matching_signature(self) -> None:
        signature = hmac_sign(payload=PAYLOAD, secret=SECRET)
        self.assertTrue(
            hmac_verify(
                payload=PAYLOAD, secret=SECRET, presented=signature
            )
        )

    def test_verify_rejects_missing_signature(self) -> None:
        self.assertFalse(
            hmac_verify(payload=PAYLOAD, secret=SECRET, presented=None)
        )

    def test_verify_rejects_empty_signature(self) -> None:
        self.assertFalse(
            hmac_verify(payload=PAYLOAD, secret=SECRET, presented="")
        )

    def test_verify_rejects_wrong_signature(self) -> None:
        wrong = "0" * 64
        self.assertFalse(
            hmac_verify(payload=PAYLOAD, secret=SECRET, presented=wrong)
        )

    def test_verify_rejects_tampered_payload(self) -> None:
        signature = hmac_sign(payload=PAYLOAD, secret=SECRET)
        tampered = PAYLOAD + b" "
        self.assertFalse(
            hmac_verify(
                payload=tampered, secret=SECRET, presented=signature
            )
        )

    def test_sign_rejects_non_bytes_payload(self) -> None:
        with self.assertRaises(TypeError):
            hmac_sign(payload="not-bytes", secret=SECRET)  # type: ignore[arg-type]

    def test_sign_rejects_empty_secret(self) -> None:
        with self.assertRaises(ValueError):
            hmac_sign(payload=PAYLOAD, secret="")


class ValidationUrlTest(unittest.TestCase):
    def test_includes_path(self) -> None:
        url = build_twilio_validation_url(
            base_url="https://example.test",
            path="/webhooks/twilio/whatsapp/inbound",
            query_string="",
        )
        self.assertEqual(
            url, "https://example.test/webhooks/twilio/whatsapp/inbound"
        )

    def test_includes_query_string(self) -> None:
        url = build_twilio_validation_url(
            base_url="https://example.test",
            path="/webhooks/twilio/whatsapp/inbound",
            query_string="foo=bar&baz=1",
        )
        self.assertEqual(
            url,
            "https://example.test/webhooks/twilio/whatsapp/inbound?foo=bar&baz=1",
        )

    def test_rejects_malformed_path(self) -> None:
        with self.assertRaises(ValueError):
            build_twilio_validation_url(
                base_url="https://example.test",
                path="not/absolute",
                query_string="",
            )

    def test_rejects_query_in_path(self) -> None:
        with self.assertRaises(ValueError):
            build_twilio_validation_url(
                base_url="https://example.test",
                path="/webhook?foo=bar",
                query_string="",
            )

    def test_rejects_fragment_in_path(self) -> None:
        with self.assertRaises(ValueError):
            build_twilio_validation_url(
                base_url="https://example.test",
                path="/webhook#frag",
                query_string="",
            )

    def test_assert_path_safe_helper(self) -> None:
        with self.assertRaises(ValueError):
            assert_validation_path_safe("/webhook?x=1")


class TwilioSignatureTest(unittest.TestCase):
    def test_sdk_validate_accepts_valid_signature(self) -> None:
        token = "test-token"
        url = "https://example.test/webhooks/twilio/whatsapp/inbound"
        form = {"MessageSid": "SM-ABC", "Body": "hola"}
        signature = compute_twilio_signature(
            auth_token=token, url=url, params=form
        )
        self.assertTrue(
            validate_twilio_signature(
                auth_token=token,
                url=url,
                params=form,
                signature=signature,
            )
        )

    def test_sdk_validate_rejects_tampered_form(self) -> None:
        token = "test-token"
        url = "https://example.test/webhooks/twilio/whatsapp/inbound"
        form = {"MessageSid": "SM-ABC", "Body": "hola"}
        signature = compute_twilio_signature(
            auth_token=token, url=url, params=form
        )
        tampered = dict(form)
        tampered["Body"] = "adulterado"
        self.assertFalse(
            validate_twilio_signature(
                auth_token=token,
                url=url,
                params=tampered,
                signature=signature,
            )
        )

    def test_sdk_validate_rejects_missing_signature(self) -> None:
        token = "test-token"
        url = "https://example.test/webhooks/twilio/whatsapp/inbound"
        form = {"MessageSid": "SM-ABC"}
        self.assertFalse(
            validate_twilio_signature(
                auth_token=token,
                url=url,
                params=form,
                signature=None,
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)