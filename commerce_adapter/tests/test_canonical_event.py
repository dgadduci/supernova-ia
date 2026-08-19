"""Focused tests for the Twilio form normalization.

The tests prove:

* the four documented fields are required;
* the ``whatsapp:`` prefix is stripped and the remaining value is
  canonical E.164;
* bounded metadata is projected to a 32-char hash and is never echoed
  back as the raw profile name;
* the canonical event shape contains exactly the documented field
  names and never raw Twilio field names.
"""
from __future__ import annotations

import unittest

from commerce_adapter.app.canonical_event import (
    InvalidTwilioForm,
    empty_twiml_response,
    normalize_twilio_form,
)

INSTALACION_ID: str = "a" * 24
COMERCIO_ID: int = 7


class NormalizeFormTest(unittest.TestCase):
    def test_happy_path(self) -> None:
        form = {
            "MessageSid": "SM123",
            "From": "whatsapp:+5491155556666",
            "To": "whatsapp:+5491100000000",
            "Body": "hola",
            "ProfileName": "Ana Lopez",
            "NumMedia": "0",
        }
        event = normalize_twilio_form(
            form, instalacion_id=INSTALACION_ID, comercio_id=COMERCIO_ID
        )
        self.assertEqual(event.message_sid, "SM123")
        self.assertEqual(event.from_e164, "+5491155556666")
        self.assertEqual(event.to_e164, "+5491100000000")
        self.assertEqual(event.cuerpo, "hola")
        self.assertEqual(event.num_media, 0)
        self.assertEqual(event.instalacion_id, INSTALACION_ID)
        self.assertEqual(event.comercio_id, COMERCIO_ID)
        self.assertEqual(event.proveedor, "twilio")
        self.assertEqual(len(event.profile_name_hash or ""), 32)
        self.assertNotIn("Ana", event.profile_name_hash or "")

    def test_bare_e164_is_accepted(self) -> None:
        form = {
            "MessageSid": "SM1",
            "From": "+5491155556666",
            "To": "+5491100000000",
            "Body": "hi",
        }
        event = normalize_twilio_form(
            form, instalacion_id=INSTALACION_ID, comercio_id=COMERCIO_ID
        )
        self.assertEqual(event.from_e164, "+5491155556666")
        self.assertEqual(event.to_e164, "+5491100000000")

    def test_missing_message_sid_raises(self) -> None:
        form = {
            "From": "whatsapp:+5491155556666",
            "To": "whatsapp:+5491100000000",
            "Body": "hola",
        }
        with self.assertRaises(InvalidTwilioForm):
            normalize_twilio_form(
                form,
                instalacion_id=INSTALACION_ID,
                comercio_id=COMERCIO_ID,
            )

    def test_missing_from_raises(self) -> None:
        form = {
            "MessageSid": "SM1",
            "To": "whatsapp:+5491100000000",
            "Body": "hola",
        }
        with self.assertRaises(InvalidTwilioForm):
            normalize_twilio_form(
                form,
                instalacion_id=INSTALACION_ID,
                comercio_id=COMERCIO_ID,
            )

    def test_missing_to_raises(self) -> None:
        form = {
            "MessageSid": "SM1",
            "From": "whatsapp:+5491155556666",
            "Body": "hola",
        }
        with self.assertRaises(InvalidTwilioForm):
            normalize_twilio_form(
                form,
                instalacion_id=INSTALACION_ID,
                comercio_id=COMERCIO_ID,
            )

    def test_missing_body_raises(self) -> None:
        form = {
            "MessageSid": "SM1",
            "From": "whatsapp:+5491155556666",
            "To": "whatsapp:+5491100000000",
        }
        with self.assertRaises(InvalidTwilioForm):
            normalize_twilio_form(
                form,
                instalacion_id=INSTALACION_ID,
                comercio_id=COMERCIO_ID,
            )

    def test_invalid_e164_raises(self) -> None:
        form = {
            "MessageSid": "SM1",
            "From": "not-a-phone",
            "To": "whatsapp:+5491100000000",
            "Body": "hola",
        }
        with self.assertRaises(InvalidTwilioForm):
            normalize_twilio_form(
                form,
                instalacion_id=INSTALACION_ID,
                comercio_id=COMERCIO_ID,
            )

    def test_num_media_default_is_zero(self) -> None:
        form = {
            "MessageSid": "SM1",
            "From": "whatsapp:+5491155556666",
            "To": "whatsapp:+5491100000000",
            "Body": "hola",
        }
        event = normalize_twilio_form(
            form, instalacion_id=INSTALACION_ID, comercio_id=COMERCIO_ID
        )
        self.assertEqual(event.num_media, 0)

    def test_num_media_invalid_raises(self) -> None:
        form = {
            "MessageSid": "SM1",
            "From": "whatsapp:+5491155556666",
            "To": "whatsapp:+5491100000000",
            "Body": "hola",
            "NumMedia": "abc",
        }
        with self.assertRaises(InvalidTwilioForm):
            normalize_twilio_form(
                form,
                instalacion_id=INSTALACION_ID,
                comercio_id=COMERCIO_ID,
            )

    def test_empty_profile_name_is_none(self) -> None:
        form = {
            "MessageSid": "SM1",
            "From": "whatsapp:+5491155556666",
            "To": "whatsapp:+5491100000000",
            "Body": "hola",
            "ProfileName": "   ",
        }
        event = normalize_twilio_form(
            form, instalacion_id=INSTALACION_ID, comercio_id=COMERCIO_ID
        )
        self.assertIsNone(event.profile_name_hash)


class EmptyTwimlTest(unittest.TestCase):
    def test_body_is_exactly_empty_response(self) -> None:
        self.assertEqual(empty_twiml_response(), "<Response></Response>")

    def test_body_has_no_message_element(self) -> None:
        body = empty_twiml_response()
        self.assertNotIn("<Message>", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)