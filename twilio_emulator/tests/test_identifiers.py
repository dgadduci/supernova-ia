"""Focused tests for the emulator synthetic identifiers."""
from __future__ import annotations

import unittest

from twilio_emulator.identifiers import (
    account_sid_prefix,
    generate_message_sid,
    is_well_formed_account_sid,
)


class IdentifierShapeTest(unittest.TestCase):
    def test_message_sid_matches_canonical_shape(self) -> None:
        sid = generate_message_sid()
        self.assertTrue(sid.startswith("SM"))
        self.assertEqual(len(sid), 34)
        tail = sid[2:]
        self.assertTrue(all(ch in "0123456789abcdef" for ch in tail))

    def test_message_sids_are_unique(self) -> None:
        a = generate_message_sid()
        b = generate_message_sid()
        self.assertNotEqual(a, b)

    def test_well_formed_account_sid_accepts_canonical(self) -> None:
        self.assertTrue(is_well_formed_account_sid("AC" + "0" * 32))

    def test_well_formed_account_sid_rejects_other(self) -> None:
        self.assertFalse(is_well_formed_account_sid("not-canonical"))
        self.assertFalse(is_well_formed_account_sid("AC" + "Z" * 32))
        self.assertFalse(is_well_formed_account_sid("AC" + "0" * 31))
        self.assertFalse(is_well_formed_account_sid(None))  # type: ignore[arg-type]

    def test_account_sid_prefix_is_safe(self) -> None:
        sid = "AC" + "abcdef0123456789" * 2
        self.assertEqual(account_sid_prefix(sid), "tail-456789")

    def test_account_sid_prefix_handles_short_values(self) -> None:
        self.assertEqual(account_sid_prefix(""), "short")
        self.assertEqual(account_sid_prefix("AC12"), "short")
        self.assertEqual(account_sid_prefix("BC" + "0" * 32), "short")


__all__ = []