"""Focused tests for the Fernet-based installation secret envelope.

The tests cover the documented envelope contract:

* the master key bundle resolves the current and the previous key
  with no protocol-level coupling;
* the master key env vars fail closed when missing, malformed or
  not exactly 32 base64 bytes;
* encrypt/decrypt round-trips for the current key;
* rotation: an envelope made with the previous key is decrypted
  with the previous key and the key id is preserved;
* an envelope with an unknown key id is rejected;
* the plain secret is never persisted in the envelope columns;
* the typed ``InvalidInstallationMasterKey`` and
  ``InvalidInstallationSecretEnvelope`` exceptions are the only
  failure surfaces the callers see.
"""
from __future__ import annotations

import base64
import os
import unittest

from cryptography.fernet import Fernet

from backend.services.exceptions import (
    InvalidInstallationMasterKey,
    InvalidInstallationSecretEnvelope,
)
from backend.services.instalacion_secret_envelope import (
    decrypt_secret,
    encrypt_secret,
    generate_installation_secret,
    resolve_master_keys,
    resolve_master_keys_from_env,
)


def _make_fernet_key() -> str:
    return Fernet.generate_key().decode("ascii")


class MasterKeyBundleTest(unittest.TestCase):
    def test_current_only_happy_path(self) -> None:
        current = _make_fernet_key()
        bundle = resolve_master_keys(current_env=current, previous_env=None)
        self.assertIsNotNone(bundle.current)
        self.assertIsNone(bundle.previous)

    def test_current_and_previous_happy_path(self) -> None:
        current = _make_fernet_key()
        previous = _make_fernet_key()
        bundle = resolve_master_keys(
            current_env=current, previous_env=previous
        )
        self.assertIsNotNone(bundle.current)
        self.assertIsNotNone(bundle.previous)

    def test_blank_previous_is_treated_as_none(self) -> None:
        current = _make_fernet_key()
        bundle = resolve_master_keys(current_env=current, previous_env="   ")
        self.assertIsNotNone(bundle.current)
        self.assertIsNone(bundle.previous)

    def test_missing_current_raises_typed(self) -> None:
        with self.assertRaises(InvalidInstallationMasterKey):
            resolve_master_keys(current_env=None, previous_env=None)

    def test_blank_current_raises_typed(self) -> None:
        with self.assertRaises(InvalidInstallationMasterKey):
            resolve_master_keys(current_env="   ", previous_env=None)

    def test_non_base64_current_raises_typed(self) -> None:
        with self.assertRaises(InvalidInstallationMasterKey):
            resolve_master_keys(
                current_env="!@#$%^&*()", previous_env=None
            )

    def test_short_current_raises_typed(self) -> None:
        short = base64.urlsafe_b64encode(b"x" * 16).decode("ascii")
        with self.assertRaises(InvalidInstallationMasterKey):
            resolve_master_keys(current_env=short, previous_env=None)

    def test_long_current_raises_typed(self) -> None:
        long = base64.urlsafe_b64encode(b"x" * 64).decode("ascii")
        with self.assertRaises(InvalidInstallationMasterKey):
            resolve_master_keys(current_env=long, previous_env=None)

    def test_non_fernet_current_raises_typed(self) -> None:
        bad = base64.urlsafe_b64encode(b"x" * 32).decode("ascii") + "garbage"
        with self.assertRaises(InvalidInstallationMasterKey):
            resolve_master_keys(current_env=bad, previous_env=None)

    def test_missing_previous_raises_typed(self) -> None:
        current = _make_fernet_key()
        with self.assertRaises(InvalidInstallationMasterKey):
            resolve_master_keys(current_env=current, previous_env="!@#$%")

    def test_resolve_from_env_reads_both_vars(self) -> None:
        saved = os.environ.copy()
        try:
            os.environ["COMMERCE_INSTALLATION_MASTER_KEY"] = _make_fernet_key()
            os.environ["COMMERCE_INSTALLATION_MASTER_KEY_PREVIOUS"] = (
                _make_fernet_key()
            )
            bundle = resolve_master_keys_from_env()
            self.assertIsNotNone(bundle.current)
            self.assertIsNotNone(bundle.previous)
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def test_resolve_from_env_missing_current_fails_closed(self) -> None:
        saved = os.environ.copy()
        try:
            os.environ.pop("COMMERCE_INSTALLATION_MASTER_KEY", None)
            with self.assertRaises(InvalidInstallationMasterKey):
                resolve_master_keys_from_env()
        finally:
            os.environ.clear()
            os.environ.update(saved)


class EncryptDecryptTest(unittest.TestCase):
    def test_round_trip_returns_plain_secret(self) -> None:
        current = _make_fernet_key()
        bundle = resolve_master_keys(current_env=current, previous_env=None)
        plain = generate_installation_secret()
        envelope, key_id = encrypt_secret(
            plain_secret=plain, bundle=bundle
        )
        self.assertNotEqual(envelope, plain)
        self.assertEqual(key_id, "current")
        decrypted = decrypt_secret(
            envelope=envelope, key_id=key_id, bundle=bundle
        )
        self.assertEqual(decrypted, plain)

    def test_plain_secret_never_appears_in_envelope(self) -> None:
        current = _make_fernet_key()
        bundle = resolve_master_keys(current_env=current, previous_env=None)
        plain = "the-very-secret-shared-value"
        envelope, _ = encrypt_secret(
            plain_secret=plain, bundle=bundle
        )
        self.assertNotIn(plain, envelope)

    def test_rotation_with_previous_key(self) -> None:
        previous = _make_fernet_key()
        current = _make_fernet_key()
        previous_bundle = resolve_master_keys(
            current_env=previous, previous_env=None
        )
        plain = generate_installation_secret()
        envelope, key_id = encrypt_secret(
            plain_secret=plain, bundle=previous_bundle
        )
        self.assertEqual(key_id, "current")

        rotated_bundle = resolve_master_keys(
            current_env=current, previous_env=previous
        )
        decrypted = decrypt_secret(
            envelope=envelope, key_id=key_id, bundle=rotated_bundle
        )
        self.assertEqual(decrypted, plain)

    def test_previous_only_envelope_decrypts(self) -> None:
        previous = _make_fernet_key()
        current = _make_fernet_key()
        previous_bundle = resolve_master_keys(
            current_env=previous, previous_env=None
        )
        plain = generate_installation_secret()
        envelope, _ = encrypt_secret(
            plain_secret=plain, bundle=previous_bundle
        )

        rotated_bundle = resolve_master_keys(
            current_env=current, previous_env=previous
        )
        decrypted = decrypt_secret(
            envelope=envelope, key_id="previous", bundle=rotated_bundle
        )
        self.assertEqual(decrypted, plain)

    def test_unknown_key_id_raises_typed(self) -> None:
        current = _make_fernet_key()
        bundle = resolve_master_keys(current_env=current, previous_env=None)
        plain = generate_installation_secret()
        envelope, _ = encrypt_secret(
            plain_secret=plain, bundle=bundle
        )
        with self.assertRaises(InvalidInstallationSecretEnvelope):
            decrypt_secret(
                envelope=envelope, key_id="ancient", bundle=bundle
            )

    def test_previous_key_without_bundle_raises_typed(self) -> None:
        current = _make_fernet_key()
        bundle = resolve_master_keys(current_env=current, previous_env=None)
        with self.assertRaises(InvalidInstallationSecretEnvelope):
            decrypt_secret(
                envelope="gAAAAA-payload", key_id="previous", bundle=bundle
            )

    def test_tampered_envelope_raises_typed(self) -> None:
        current = _make_fernet_key()
        bundle = resolve_master_keys(current_env=current, previous_env=None)
        with self.assertRaises(InvalidInstallationSecretEnvelope):
            decrypt_secret(
                envelope="totally-not-a-real-fernet-envelope",
                key_id="current",
                bundle=bundle,
            )

    def test_empty_envelope_raises_typed(self) -> None:
        current = _make_fernet_key()
        bundle = resolve_master_keys(current_env=current, previous_env=None)
        with self.assertRaises(InvalidInstallationSecretEnvelope):
            decrypt_secret(
                envelope="", key_id="current", bundle=bundle
            )

    def test_empty_plain_secret_raises_typed(self) -> None:
        current = _make_fernet_key()
        bundle = resolve_master_keys(current_env=current, previous_env=None)
        with self.assertRaises(InvalidInstallationSecretEnvelope):
            encrypt_secret(plain_secret="", bundle=bundle)

    def test_generate_returns_urlsafe_token(self) -> None:
        plain = generate_installation_secret()
        self.assertIsInstance(plain, str)
        self.assertGreater(len(plain), 30)
        self.assertNotIn("=", plain)
        self.assertNotIn("+", plain)
        self.assertNotIn("/", plain)

    def test_two_generated_secrets_are_distinct(self) -> None:
        self.assertNotEqual(
            generate_installation_secret(),
            generate_installation_secret(),
        )


class TypedErrorsTest(unittest.TestCase):
    def test_missing_master_key_is_value_error(self) -> None:
        self.assertTrue(
            issubclass(InvalidInstallationMasterKey, ValueError)
        )

    def test_invalid_envelope_is_value_error(self) -> None:
        self.assertTrue(
            issubclass(InvalidInstallationSecretEnvelope, ValueError)
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
