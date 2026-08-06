"""Focused tests for the Phase-5.5 Twilio inbound adapter.

The adapter owns the only Twilio-specific contract in the project:
signature validation URL composition and the four-field envelope
extraction. These tests use a stand-in ``RequestValidator`` so the
project does not depend on a real Twilio token or the SDK HMAC
machinery; the production wiring still goes through the SDK
``RequestValidator`` constructed by the router.
"""
from __future__ import annotations

import unittest
from collections.abc import Mapping
from typing import ClassVar

from backend.services.exceptions import (
    InvalidTwilioInboundForm,
)
from backend.services.twilio_inbound_adapter import (
    TwilioInboundEnvelope,
    assert_path_is_safe,
    build_validation_url,
    extract_envelope,
    validate_request,
)


class _StubValidator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str], str]] = []
        self.result = True

    def validate(
        self,
        uri: str,
        params: Mapping[str, str],
        signature: str,
    ) -> bool:
        self.calls.append((uri, dict(params), signature))
        return self.result


class BuildValidationUrlTest(unittest.TestCase):
    def test_composes_absolute_url_without_query(self):
        url = build_validation_url(
            "https://example.com", "/webhooks/twilio/whatsapp/inbound", ""
        )
        self.assertEqual(
            url,
            "https://example.com/webhooks/twilio/whatsapp/inbound",
        )

    def test_strips_trailing_slash_from_base(self):
        url = build_validation_url(
            "https://example.com/", "/webhooks/twilio/whatsapp/inbound", ""
        )
        self.assertEqual(
            url,
            "https://example.com/webhooks/twilio/whatsapp/inbound",
        )

    def test_appends_query_string_when_provided(self):
        url = build_validation_url(
            "https://example.com",
            "/webhooks/twilio/whatsapp/inbound",
            "hub=1",
        )
        self.assertEqual(
            url,
            "https://example.com/webhooks/twilio/whatsapp/inbound?hub=1",
        )

    def test_empty_base_raises(self):
        from backend.services.exceptions import (
            TwilioSignatureUnavailable,
        )

        with self.assertRaises(TwilioSignatureUnavailable):
            build_validation_url("", "/x", "")

    def test_invalid_path_raises(self):
        from backend.services.exceptions import (
            TwilioSignatureUnavailable,
        )

        with self.assertRaises(TwilioSignatureUnavailable):
            build_validation_url("https://example.com", "no-leading-slash", "")


class AssertPathIsSafeTest(unittest.TestCase):
    def test_accepts_relative_path(self):
        assert_path_is_safe("/webhooks/twilio/whatsapp/inbound")

    def test_rejects_query_string(self):
        from backend.services.exceptions import (
            TwilioSignatureUnavailable,
        )

        with self.assertRaises(TwilioSignatureUnavailable):
            assert_path_is_safe("/x?hub=1")

    def test_rejects_fragment(self):
        from backend.services.exceptions import (
            TwilioSignatureUnavailable,
        )

        with self.assertRaises(TwilioSignatureUnavailable):
            assert_path_is_safe("/x#frag")

    def test_rejects_non_leading_slash(self):
        from backend.services.exceptions import (
            TwilioSignatureUnavailable,
        )

        with self.assertRaises(TwilioSignatureUnavailable):
            assert_path_is_safe("webhooks/twilio")

    def test_rejects_whitespace(self):
        from backend.services.exceptions import (
            TwilioSignatureUnavailable,
        )

        with self.assertRaises(TwilioSignatureUnavailable):
            assert_path_is_safe("/x y")


class ValidateRequestTest(unittest.TestCase):
    BASE: ClassVar[str] = "https://example.com"
    PATH: ClassVar[str] = "/webhooks/twilio/whatsapp/inbound"
    FORM: ClassVar[Mapping[str, str]] = {
        "MessageSid": "SM123",
        "From": "whatsapp:+5491155556666",
        "To": "whatsapp:+5491100000000",
        "Body": "hola",
    }

    def test_returns_false_when_base_url_missing(self):
        validator = _StubValidator()
        self.assertFalse(
            validate_request(
                validator=validator,
                base_url=None,
                path=self.PATH,
                query_string="",
                form=self.FORM,
                signature="sig",
            )
        )
        self.assertEqual(validator.calls, [])

    def test_returns_false_when_signature_missing(self):
        validator = _StubValidator()
        self.assertFalse(
            validate_request(
                validator=validator,
                base_url=self.BASE,
                path=self.PATH,
                query_string="",
                form=self.FORM,
                signature=None,
            )
        )
        self.assertEqual(validator.calls, [])

    def test_returns_false_when_signature_empty(self):
        validator = _StubValidator()
        self.assertFalse(
            validate_request(
                validator=validator,
                base_url=self.BASE,
                path=self.PATH,
                query_string="",
                form=self.FORM,
                signature="",
            )
        )
        self.assertEqual(validator.calls, [])

    def test_returns_validator_result_when_inputs_valid(self):
        validator = _StubValidator()
        validator.result = True
        self.assertTrue(
            validate_request(
                validator=validator,
                base_url=self.BASE,
                path=self.PATH,
                query_string="",
                form=self.FORM,
                signature="valid-sig",
            )
        )
        self.assertEqual(len(validator.calls), 1)
        uri, params, signature = validator.calls[0]
        self.assertEqual(
            uri,
            "https://example.com/webhooks/twilio/whatsapp/inbound",
        )
        self.assertEqual(params, self.FORM)
        self.assertEqual(signature, "valid-sig")

    def test_returns_false_when_validator_rejects(self):
        validator = _StubValidator()
        validator.result = False
        self.assertFalse(
            validate_request(
                validator=validator,
                base_url=self.BASE,
                path=self.PATH,
                query_string="hub=1",
                form=self.FORM,
                signature="bad-sig",
            )
        )
        self.assertEqual(len(validator.calls), 1)
        uri, params, _ = validator.calls[0]
        self.assertIn("hub=1", uri)
        self.assertEqual(params, self.FORM)


class ExtractEnvelopeTest(unittest.TestCase):
    def test_canonicalizes_whatsapp_envelope(self):
        envelope = extract_envelope(
            {
                "MessageSid": "SM123",
                "From": "whatsapp:+5491155556666",
                "To": "whatsapp:+5491100000000",
                "Body": "hola",
            }
        )
        self.assertEqual(envelope, TwilioInboundEnvelope(
            message_sid="SM123",
            from_e164="+5491155556666",
            to_e164="+5491100000000",
            body="hola",
        ))

    def test_canonicalizes_bare_e164(self):
        envelope = extract_envelope(
            {
                "MessageSid": "SM124",
                "From": "+5491155556667",
                "To": "+5491100000000",
                "Body": "hola",
            }
        )
        self.assertEqual(envelope.from_e164, "+5491155556667")

    def test_strips_internal_whitespace(self):
        envelope = extract_envelope(
            {
                "MessageSid": "SM125",
                "From": "whatsapp:+5491155556668",
                "To": "  +5491100000000  ",
                "Body": "hola",
            }
        )
        self.assertEqual(envelope.to_e164, "+5491100000000")

    def test_missing_message_sid_rejected(self):
        with self.assertRaises(InvalidTwilioInboundForm):
            extract_envelope(
                {
                    "From": "whatsapp:+5491155556666",
                    "To": "whatsapp:+5491100000000",
                    "Body": "hola",
                }
            )

    def test_empty_body_rejected(self):
        with self.assertRaises(InvalidTwilioInboundForm):
            extract_envelope(
                {
                    "MessageSid": "SM126",
                    "From": "whatsapp:+5491155556666",
                    "To": "whatsapp:+5491100000000",
                    "Body": "   ",
                }
            )

    def test_invalid_from_rejected(self):
        with self.assertRaises(InvalidTwilioInboundForm):
            extract_envelope(
                {
                    "MessageSid": "SM127",
                    "From": "not-a-phone",
                    "To": "whatsapp:+5491100000000",
                    "Body": "hola",
                }
            )

    def test_invalid_to_rejected(self):
        with self.assertRaises(InvalidTwilioInboundForm):
            extract_envelope(
                {
                    "MessageSid": "SM128",
                    "From": "whatsapp:+5491155556666",
                    "To": "not-a-phone",
                    "Body": "hola",
                }
            )


class AdapterModuleBoundaryTest(unittest.TestCase):
    def test_adapter_does_not_import_sqlalchemy(self):
        import inspect

        from backend.services import twilio_inbound_adapter as adapter_mod

        source = inspect.getsource(adapter_mod)
        for forbidden in (
            "sqlalchemy",
            "commit(",
            "rollback(",
            "begin(",
            "flush(",
            "expire(",
            "refresh(",
            "close(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(
                    forbidden,
                    source,
                    f"adapter must not touch SQLAlchemy transaction control: {forbidden}",
                )

    def test_adapter_does_not_call_coordinator_or_resolver(self):
        import inspect

        from backend.services import twilio_inbound_adapter as adapter_mod

        source = inspect.getsource(adapter_mod)
        for forbidden in (
            "ProviderInboundMessageCoordinator",
            "CommerceChannelResolver",
            "ClienteService",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(
                    forbidden,
                    source,
                    f"adapter must not call downstream services: {forbidden}",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
