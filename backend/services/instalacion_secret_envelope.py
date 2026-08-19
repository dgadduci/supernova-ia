"""Fernet-based encryption envelope for the per-installation shared secret.

The bounded installation provisioning CLI generates a fresh
``secrets.token_urlsafe(32)`` shared secret for each commerce and stores
only the Fernet envelope of that secret on the ``InstalacionTwilioComercio``
row. The plain secret is exposed exactly once on the provisioning seam
stdout and never appears in any HTTP response, log record or database
column.

The envelope service is the only component that knows how to:

* build a Fernet instance list from ``COMMERCE_INSTALLATION_MASTER_KEY`` and
  the optional ``COMMERCE_INSTALLATION_MASTER_KEY_PREVIOUS`` (rotation
  support);
* encrypt a plain secret with the current master key;
* decrypt an envelope by trying every configured master key in order;
* raise the typed ``InvalidInstallationMasterKey`` /
  ``InvalidInstallationSecretEnvelope`` errors instead of leaking
  ``cryptography`` exceptions or raw key material to the caller.

The module deliberately has no NovaOrders business imports: it is a small,
self-contained cryptography boundary that the bounded provisioning seam,
the internal ingress dependency and the bounded CLI all call into.

The envelope service is a pure module-level utility — there is no
state, no session, no logger. All values pass through ``secrets`` and
``Fernet`` from the standard ``cryptography`` package, which is already
on the project dependency list.
"""
from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken

from backend.services.exceptions import (
    InvalidInstallationMasterKey,
    InvalidInstallationSecretEnvelope,
)


_CURRENT_KEY_ID: str = "current"
_PREVIOUS_KEY_ID: str = "previous"

_ENV_VAR_CURRENT: str = "COMMERCE_INSTALLATION_MASTER_KEY"
_ENV_VAR_PREVIOUS: str = "COMMERCE_INSTALLATION_MASTER_KEY_PREVIOUS"

_FERNET_KEY_LENGTH: int = 44


@dataclass(frozen=True)
class MasterKeyBundle:
    """Resolved Fernet master-key bundle used by the envelope service.

    ``current`` is mandatory and must be a valid Fernet URL-safe
    base64-encoded 32-byte key. ``previous`` is optional and exists for
    rotation only; decryption tries ``previous`` first when the
    ``current`` key cannot decrypt the envelope.
    """

    current: Fernet
    previous: Fernet | None


def _coerce_master_key_env(name: str, raw: str | None) -> Fernet:
    """Resolve one master-key env value into a ``Fernet`` instance.

    Missing or empty values raise ``InvalidInstallationMasterKey`` with
    a clear operator-facing message. Non-Fernet values are rejected at
    process start with the same typed exception.
    """
    if raw is None or not raw.strip():
        raise InvalidInstallationMasterKey(
            f"{name} is required for the commerce-isolated Twilio edge"
        )
    cleaned = raw.strip()
    if not cleaned:
        raise InvalidInstallationMasterKey(
            f"{name} must be a non-empty stripped string"
        )
    try:
        decoded = base64.urlsafe_b64decode(cleaned.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise InvalidInstallationMasterKey(
            f"{name} must be a URL-safe base64 string"
        ) from exc
    if len(decoded) != 32:
        raise InvalidInstallationMasterKey(
            f"{name} must decode to exactly 32 bytes (got {len(decoded)})"
        )
    if len(cleaned) != _FERNET_KEY_LENGTH:
        raise InvalidInstallationMasterKey(
            f"{name} must be a canonical 44-character Fernet key"
        )
    try:
        return Fernet(cleaned.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise InvalidInstallationMasterKey(
            f"{name} is not a valid Fernet key"
        ) from exc


def resolve_master_keys(
    *,
    current_env: str | None,
    previous_env: str | None,
) -> MasterKeyBundle:
    """Build the bundle from the two supplied env values.

    The function is the single entry point for the bounded provisioning
    CLI and the bounded ingress dependency. Both callers pass the env
    values they read so the module never imports ``os`` and never reads
    the environment directly — keeping the envelope service pure and
    easy to test.
    """
    current = _coerce_master_key_env(_ENV_VAR_CURRENT, current_env)
    previous_value: str | None = (
        previous_env.strip() if isinstance(previous_env, str) else None
    )
    if previous_value == "":
        previous_value = None
    previous: Fernet | None = None
    if previous_value is not None:
        previous = _coerce_master_key_env(_ENV_VAR_PREVIOUS, previous_value)
    return MasterKeyBundle(current=current, previous=previous)


def resolve_master_keys_from_env() -> MasterKeyBundle:
    """Convenience entry point that reads the two env values directly.

    Use this from the bounded provisioning CLI and from the bounded
    ingress dependency. Tests pass explicit values through
    :func:`resolve_master_keys` instead.
    """
    import os

    return resolve_master_keys(
        current_env=os.environ.get(_ENV_VAR_CURRENT),
        previous_env=os.environ.get(_ENV_VAR_PREVIOUS),
    )


def generate_installation_secret() -> str:
    """Generate a fresh, 32-byte URL-safe shared secret.

    The bounded provisioning seam calls this exactly once per installation
    and stores the result only as a Fernet envelope. The plain value
    never reaches the database or any log.
    """
    return secrets.token_urlsafe(32)


def encrypt_secret(
    *, plain_secret: str, bundle: MasterKeyBundle
) -> tuple[str, str]:
    """Encrypt ``plain_secret`` with the current master key.

    Returns ``(envelope, key_id)`` where ``key_id`` is the literal
    ``"current"`` until a future rotation flips it. The bounded
    provisioning seam persists both fields on the installation row.
    """
    if not isinstance(plain_secret, str) or not plain_secret:
        raise InvalidInstallationSecretEnvelope(
            "plain_secret must be a non-empty string"
        )
    envelope = bundle.current.encrypt(plain_secret.encode("utf-8"))
    return envelope.decode("ascii"), _CURRENT_KEY_ID


def decrypt_secret(
    *, envelope: str, key_id: str, bundle: MasterKeyBundle
) -> str:
    """Decrypt ``envelope`` by trying every key in the bundle.

    The function returns the plain secret exactly once; the bounded
    ingress dependency holds it only in memory and uses it to recompute
    the HMAC signature. A bad envelope raises the typed
    ``InvalidInstallationSecretEnvelope`` so the ingress dependency can
    return a typed ``502`` and let Twilio retry.
    """
    if not isinstance(envelope, str) or not envelope:
        raise InvalidInstallationSecretEnvelope(
            "envelope must be a non-empty string"
        )
    candidates: list[tuple[str, Fernet]] = []
    if key_id == _CURRENT_KEY_ID:
        candidates.append((_CURRENT_KEY_ID, bundle.current))
        if bundle.previous is not None:
            candidates.append((_PREVIOUS_KEY_ID, bundle.previous))
    elif key_id == _PREVIOUS_KEY_ID:
        if bundle.previous is None:
            raise InvalidInstallationSecretEnvelope(
                "envelope was encrypted with the previous master key "
                "but no previous key is configured"
            )
        candidates.append((_PREVIOUS_KEY_ID, bundle.previous))
        candidates.append((_CURRENT_KEY_ID, bundle.current))
    else:
        raise InvalidInstallationSecretEnvelope(
            f"unknown installation envelope key_id {key_id!r}"
        )
    last_error: Exception | None = None
    for candidate_key_id, fernet in candidates:
        try:
            plain = fernet.decrypt(envelope.encode("ascii"))
            return plain.decode("utf-8")
        except InvalidToken as exc:
            last_error = exc
            continue
    raise InvalidInstallationSecretEnvelope(
        "envelope cannot be decrypted with any configured master key"
    ) from last_error


__all__ = [
    "MasterKeyBundle",
    "decrypt_secret",
    "encrypt_secret",
    "generate_installation_secret",
    "resolve_master_keys",
    "resolve_master_keys_from_env",
]