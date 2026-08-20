"""Twilio-shaped signature generation.

The emulator signs the complete inbound Twilio form using the
standard Twilio algorithm: HMAC-SHA256 over the concatenation of the
canonical validation URL, every parameter key/value pair (sorted by
key) and finally appending each value. The output is base64-encoded so
the T-C :func:`commerce_adapter.app.security.validate_twilio_signature`
helper accepts it via the pinned ``twilio==9.x`` SDK.

The helper mirrors the SDK contract exactly: the ``Url`` placeholder
is the validation URL computed by the T-C adapter
(``scheme://host + path + query``); the query string is preserved; the
form parameters must be a ``dict[str, str]`` with no lists, files or
non-string values.

The helper is intentionally narrow: it does not import the Twilio SDK
to avoid loading the real provider at runtime, and it never logs the
auth token, the URL or the parameter values. The caller passes the
auth token explicitly so the function stays pure and stateless.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping


class SignatureValidationError(ValueError):
    """Raised when the signature inputs are malformed.

    The exception exists so the bounded inbound driver fails closed
    before any HTTP request is sent. The T-C adapter itself uses the
    pinned SDK ``RequestValidator``; the emulator must be able to
    match the same contract without importing the SDK.
    """


def _sorted_kv_pairs(params: Mapping[str, str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for raw_key, raw_value in params.items():
        if not isinstance(raw_key, str):
            raise SignatureValidationError(
                f"form key must be a string (got {type(raw_key).__name__})"
            )
        if not isinstance(raw_value, str):
            raise SignatureValidationError(
                f"form value for {raw_key!r} must be a string "
                f"(got {type(raw_value).__name__})"
            )
        pairs.append((raw_key, raw_value))
    pairs.sort(key=lambda item: item[0])
    return pairs


def compute_form_signature(
    *, auth_token: str, url: str, params: Mapping[str, str]
) -> str:
    """Return the Twilio-shaped HMAC-SHA1 signature for the form.

    The algorithm matches the SDK ``RequestValidator`` exactly so the
    T-C adapter signature validator accepts the value via the same
    pinned SDK. The output is base64-encoded.

    The function NEVER logs the auth token, the URL or the parameter
    values. The caller is responsible for keeping the auth token in
    process and for discarding the returned signature after use.
    """
    if not isinstance(auth_token, str) or not auth_token:
        raise SignatureValidationError("auth_token is required")
    if not isinstance(url, str) or not url:
        raise SignatureValidationError("url is required")

    pieces: list[str] = [url]
    for key, value in _sorted_kv_pairs(params):
        pieces.append(key)
        pieces.append(value)
    payload = "".join(pieces).encode("utf-8")
    digest = hmac.new(
        auth_token.encode("utf-8"),
        payload,
        hashlib.sha1,
    ).digest()
    return base64.b64encode(digest).decode("ascii")


__all__ = [
    "SignatureValidationError",
    "compute_form_signature",
]