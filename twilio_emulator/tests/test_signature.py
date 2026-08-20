"""Focused tests for the emulator signature helpers."""
from __future__ import annotations

import base64
import hashlib
import hmac
import unittest

from twilio_emulator.signature import (
    SignatureValidationError,
    compute_form_signature,
)


def _twilio_reference_signature(
    *, auth_token: str, url: str, params: dict[str, str]
) -> str:
    """Compute the canonical Twilio signature using the same algorithm
    the pinned SDK uses.

    The helper exists solely so the test can independently validate
    the emulator's output without importing the Twilio SDK.
    """
    pieces = [url]
    for key in sorted(params.keys()):
        pieces.append(key)
        pieces.append(params[key])
    payload = "".join(pieces).encode("utf-8")
    digest = hmac.new(auth_token.encode("utf-8"), payload, hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


class SignatureContractTest(unittest.TestCase):
    def test_signature_matches_canonical_algorithm(self) -> None:
        auth_token = "secret-token"
        url = "https://tc.example.test/webhook"
        params = {
            "MessageSid": "SM-AAA",
            "From": "whatsapp:+5491100000000",
            "To": "whatsapp:+5491155556666",
            "Body": "hola",
        }
        produced = compute_form_signature(
            auth_token=auth_token, url=url, params=params
        )
        expected = _twilio_reference_signature(
            auth_token=auth_token, url=url, params=params
        )
        self.assertEqual(produced, expected)

    def test_signature_is_base64_encoded(self) -> None:
        signature = compute_form_signature(
            auth_token="t",
            url="https://example.test/path",
            params={"From": "a", "To": "b", "Body": "c"},
        )
        decoded = base64.b64decode(signature.encode("ascii"), validate=True)
        self.assertEqual(len(decoded), 20)

    def test_signature_changes_when_form_changes(self) -> None:
        params_a = {"From": "a", "To": "b", "Body": "first"}
        params_b = {"From": "a", "To": "b", "Body": "second"}
        auth_token = "shared"
        url = "https://example.test/path"
        self.assertNotEqual(
            compute_form_signature(
                auth_token=auth_token, url=url, params=params_a
            ),
            compute_form_signature(
                auth_token=auth_token, url=url, params=params_b
            ),
        )

    def test_missing_auth_token_raises(self) -> None:
        with self.assertRaises(SignatureValidationError):
            compute_form_signature(
                auth_token="", url="https://example.test", params={}
            )

    def test_non_string_param_raises(self) -> None:
        with self.assertRaises(SignatureValidationError):
            compute_form_signature(
                auth_token="t",
                url="https://example.test",
                params={"From": 1},  # type: ignore[typeddict-item]
            )


__all__ = []