"""Supabase OTP request and PKCE token exchange clients.

The module exposes two narrow outbound adapters:

* :func:`request_magic_link_otp` — POSTs to the documented Supabase
  ``/auth/v1/otp`` endpoint with the magic-link envelope, the
  pinned redirect URL and the PKCE challenge parameters.
* :func:`exchange_magic_link_code` — POSTs to the documented
  Supabase ``/auth/v1/token`` endpoint with
  ``grant_type=pkce`` to redeem the one-time ``code`` returned in
  the email link and the matching server-side ``code_verifier``.

Both adapters share the fail-closed contract:

* The request bodies are stripped of any value the application does not
    own (the email is lower-cased and trimmed, the verifier is
    passed through verbatim).
* The response body and full request URL are never logged; the
    helpers only emit bounded event markers.
* The adapters are feature-gated by :class:`SupabaseAuthSettings`;
    when the operator disables the feature the helpers short-circuit
    and raise a typed :class:`SupabaseAuthError` so the router can
    fall back to the ``comenzar`` placeholder without contacting the
    provider.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib import error as url_error
from urllib import request as url_request
from urllib.parse import urlencode

from backend.auth.settings import SupabaseAuthSettings

PKCE_CHALLENGE_METHOD_PAYLOAD = "s256"


class SupabaseAuthError(Exception):
    """Raised when a Supabase Auth call fails.

    The router converts this signal into a generic
    service-unavailable view. The exception detail is intentionally
    generic; the visitor never learns why the request failed.
    """

    reason: str

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class OtpRequest:
    """The validated payload sent to ``/auth/v1/otp``.

    Attributes:
        email: Sanitised email address.
        callback_url: Pinned HTTPS callback URL.
        challenge: PKCE challenge associated with the temp cookie.
        challenge_method: Always ``S256`` for Supabase OTP flows.
        should_create_user: Always ``False`` to honour the
            ``should_create_user=False`` invariant required by the
            Phase 2 contract.
    """

    email: str
    callback_url: str
    challenge: str
    challenge_method: str
    should_create_user: bool


@dataclass(frozen=True)
class MagicLinkRequest:
    """Compatibility alias preserved for the Phase 2 router tests."""

    email: str
    callback_url: str
    publishable_key: str


def build_otp_request(
    *,
    email: str,
    challenge: str,
    settings: SupabaseAuthSettings,
) -> OtpRequest:
    """Build the outbound OTP request payload.

    The helper is intentionally pure so a test can verify the exact
    shape of the payload without stubbing the HTTP layer.
    """
    if not settings.enabled:
        raise SupabaseAuthError("feature_disabled")
    cleaned_email = email.strip().lower()
    if not cleaned_email:
        raise SupabaseAuthError("email_missing")
    if not challenge:
        raise SupabaseAuthError("pkce_missing")
    return OtpRequest(
        email=cleaned_email,
        callback_url=settings.callback_url,
        challenge=challenge,
        challenge_method="S256",
        should_create_user=False,
    )


def _publishable_headers(publishable_key: str) -> Mapping[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "apikey": publishable_key,
        "Authorization": f"Bearer {publishable_key}",
        "User-Agent": "novaorders-public-onboarding",
    }


def _post_json(
    *,
    url: str,
    headers: Mapping[str, str],
    body: Mapping[str, Any],
    timeout: int,
) -> bytes:
    encoded = json.dumps(body, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    request = url_request.Request(
        url,
        data=encoded,
        headers=dict(headers),
        method="POST",
    )
    try:
        with url_request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", None) or response.getcode()
            raw = response.read()
    except url_error.HTTPError as exc:
        raise SupabaseAuthError("provider_status_error") from exc
    except url_error.URLError as exc:
        raise SupabaseAuthError("provider_unreachable") from exc
    except TimeoutError as exc:
        raise SupabaseAuthError("provider_timeout") from exc
    if status < 200 or status >= 300:
        raise SupabaseAuthError("provider_status_error")
    return raw


def request_magic_link_otp(
    *,
    email: str,
    challenge: str,
    settings: SupabaseAuthSettings,
) -> MagicLinkRequest:
    """Request a magic-link OTP from Supabase.

    Wire contract (documented Supabase OTP endpoint):

    * ``POST https://<project>.supabase.co/auth/v1/otp?redirect_to=<URL_CALLBACK_URLENCODED>``
    * Headers: ``apikey`` + ``Authorization: Bearer <publishable>`` and
      ``Content-Type: application/json``.
    * JSON body (root level only):
      ``{"email": ..., "create_user": false, "code_challenge": ...,
      "code_challenge_method": "s256"}``.

    The body MUST NOT contain ``options``, ``email_redirect_to`` or
    ``redirect_to``; those keys belong to the URL or are forbidden
    by the documented Supabase OTP envelope.

    The helper enforces the fail-closed contract:

    * When the feature is disabled the helper short-circuits with
      ``feature_disabled``.
    * When the request payload cannot be built the helper raises a
      typed error before contacting the provider.
    * A network failure, timeout or non-2xx response is collapsed
      into :class:`SupabaseAuthError` so the router can render the
      generic service-unavailable view.

    The helper never logs the request body, the email, the challenge
    or the callback URL.
    """
    if not settings.enabled:
        raise SupabaseAuthError("feature_disabled")
    payload = build_otp_request(
        email=email, challenge=challenge, settings=settings
    )
    otp_url = (
        f"{settings.otp_endpoint}?"
        f"{urlencode({'redirect_to': payload.callback_url})}"
    )
    body = {
        "email": payload.email,
        "create_user": payload.should_create_user,
        "code_challenge": payload.challenge,
        "code_challenge_method": PKCE_CHALLENGE_METHOD_PAYLOAD,
    }
    _post_json(
        url=otp_url,
        headers=_publishable_headers(settings.publishable_key),
        body=body,
        timeout=settings.request_timeout_seconds,
    )
    return MagicLinkRequest(
        email=payload.email,
        callback_url=payload.callback_url,
        publishable_key=settings.publishable_key,
    )


def exchange_magic_link_code(
    *,
    code: str,
    code_verifier: str,
    settings: SupabaseAuthSettings,
) -> str:
    """Exchange the magic-link ``code`` for an access JWT.

    Wire contract (documented Supabase PKCE token endpoint):

    * ``POST https://<project>.supabase.co/auth/v1/token?grant_type=pkce``
    * JSON body (root level only):
      ``{"auth_code": "<received code>", "code_verifier": "<verifier>"}``.

    The body field is ``auth_code``; the application MUST NOT send a
    generic ``code`` key because Supabase rejects the request
    otherwise. ``grant_type`` is supplied only via the URL query.

    The helper returns the JWT string so the JWT validator can
    verify it through the JWKS path; the helper itself does not
    inspect the JWT contents — it only consumes the provider
    response and surfaces a typed error for every failure mode so
    the router can render the bounded service-unavailable view.
    """
    if not settings.enabled:
        raise SupabaseAuthError("feature_disabled")
    if not code or not code.strip():
        raise SupabaseAuthError("code_missing")
    if not code_verifier or not code_verifier.strip():
        raise SupabaseAuthError("verifier_missing")
    body = {
        "auth_code": code.strip(),
        "code_verifier": code_verifier.strip(),
    }
    raw = _post_json(
        url=f"{settings.token_endpoint}?grant_type=pkce",
        headers=_publishable_headers(settings.publishable_key),
        body=body,
        timeout=settings.request_timeout_seconds,
    )
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise SupabaseAuthError("provider_malformed_response") from exc
    if not isinstance(decoded, Mapping):
        raise SupabaseAuthError("provider_malformed_response")
    access_token = decoded.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise SupabaseAuthError("provider_malformed_response")
    return access_token.strip()


def is_valid_email_shape(email: str) -> bool:
    """Return ``True`` when ``email`` is a syntactically valid address.

    The helper accepts the documented Supabase envelope: a single
    ``@`` separating non-empty local and domain parts with at least
    one dot in the domain. The helper is intentionally permissive —
    the real validation happens server-side at Supabase — but it
    rejects obviously malformed values so the application never
    issues a magic link for an invalid envelope.
    """
    if not isinstance(email, str):
        return False
    cleaned = email.strip()
    if not cleaned:
        return False
    if cleaned.count("@") != 1:
        return False
    local, _, domain = cleaned.partition("@")
    if not local or not domain:
        return False
    if "." not in domain:
        return False
    return not any(ch.isspace() for ch in cleaned)


__all__ = [
    "MagicLinkRequest",
    "OtpRequest",
    "SupabaseAuthError",
    "build_otp_request",
    "exchange_magic_link_code",
    "is_valid_email_shape",
    "request_magic_link_otp",
]