"""Security primitives for the T-C adapter.

The module centralizes three narrowly-scoped helpers:

* :func:`hmac_sign` / :func:`hmac_verify` over an exact byte payload;
* :func:`build_twilio_validation_url` for the canonical signature URL;
* :func:`compute_twilio_signature` for tests that need a signature
  value computed by the same code path the adapter uses.

The module never logs the secret, the raw payload or the signature. It
has no state and no dependencies on NovaOrders, the merchant Twilio
account or any environment variable.
"""
from __future__ import annotations

import hashlib
import hmac
import re

_VALIDATION_PATH_RE: re.Pattern[str] = re.compile(r"^/[\w./\-]*$")


def hmac_sign(*, payload: bytes, secret: str) -> str:
    """Return the lowercase hex HMAC-SHA256 signature of ``payload``.

    The function uses ``hmac.new(secret, payload, hashlib.sha256)`` with
    a UTF-8 encoded secret so non-ASCII secrets never raise
    ``UnicodeEncodeError`` at the call site.
    """
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("payload must be bytes")
    if not isinstance(secret, str) or not secret:
        raise ValueError("secret must be a non-empty string")
    digest = hmac.new(
        secret.encode("utf-8"),
        bytes(payload),
        hashlib.sha256,
    ).hexdigest()
    return digest


def hmac_verify(*, payload: bytes, secret: str, presented: str | None) -> bool:
    """Constant-time HMAC signature verification.

    Returns ``True`` only when ``presented`` is a non-empty string and
    matches the recomputed signature. Comparison uses
    :func:`hmac.compare_digest` so a timing side-channel cannot leak
    any byte of the secret.
    """
    if not isinstance(presented, str) or not presented:
        return False
    expected = hmac_sign(payload=payload, secret=secret)
    return hmac.compare_digest(expected, presented)


def assert_validation_path_safe(path: str) -> None:
    """Reject a validation URL path that is not a literal HTTP path.

    The route always passes a literal path; the guard exists so a
    future refactor cannot smuggle attacker-controlled data into the
    canonical Twilio signature URL.
    """
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or "?" in path
        or "#" in path
        or not _VALIDATION_PATH_RE.match(path)
    ):
        raise ValueError("twilio webhook path is malformed")


def build_twilio_validation_url(
    *, base_url: str, path: str, query_string: str | None
) -> str:
    """Compose the canonical Twilio signature URL.

    Twilio signs the exact URL the request reached
    (``scheme + host + path + query``). The configured
    ``TC_TWILIO_WEBHOOK_BASE_URL`` pins scheme + host; the adapter owns
    the path and the query string so signature validation cannot be
    tricked by attacker-supplied headers.
    """
    if not isinstance(base_url, str) or not base_url:
        raise ValueError("base_url is required")
    assert_validation_path_safe(path)
    cleaned = f"{base_url.rstrip('/')}{path}"
    if query_string:
        cleaned = f"{cleaned}?{query_string}"
    return cleaned


def compute_twilio_signature(
    *, auth_token: str, url: str, params: dict[str, str]
) -> str:
    """Compute a Twilio signature using the SDK ``RequestValidator``.

    Tests use this helper to build a real signature for the exact
    canonical URL + form they then submit. Production code uses the
    SDK ``RequestValidator.validate`` directly; this helper exists
    solely to keep tests in one place.
    """
    from twilio.request_validator import RequestValidator

    validator = RequestValidator(auth_token)
    return validator.compute_signature(url, params)


def validate_twilio_signature(
    *,
    auth_token: str,
    url: str,
    params: dict[str, str],
    signature: str | None,
) -> bool:
    """Verify a Twilio signature using the SDK ``RequestValidator``.

    A missing or empty ``signature`` is rejected without invoking the
    SDK so the helper stays free of exceptions. The SDK raises on a
    ``None`` signature; the helper guards that branch itself.
    """
    if not isinstance(signature, str) or not signature:
        return False
    from twilio.request_validator import RequestValidator

    validator = RequestValidator(auth_token)
    return bool(validator.validate(url, params, signature))


__all__ = [
    "assert_validation_path_safe",
    "build_twilio_validation_url",
    "compute_twilio_signature",
    "hmac_sign",
    "hmac_verify",
    "validate_twilio_signature",
]