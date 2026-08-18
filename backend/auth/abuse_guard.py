"""Verifiable abuse guard for Phase 2 Supabase magic-link issuance.

The Phase 2 design mandates that magic-link issuance is gated by an
external, operator-pinned dependency so an in-process permissive
fallback cannot silently bypass the production rate-limit layer.
The helper is the single boundary that satisfies the contract:

* When the operator has not configured an abuse guard URL/token the
  helper refuses to authorise the issuance; the call short-circuits
  with :class:`AbuseGuardUnavailable` so the router can render the
  bounded service-unavailable view.
* When the guard is configured the helper performs a signed HTTPS
  ``POST`` to the configured URL with a bounded timeout and
  consumes the response. A network failure, timeout, non-2xx
  response, missing token or missing identifier in the response is
  collapsed into :class:`AbuseGuardUnavailable` so the operator can
  never silently downgrade the gate.
* The helper never persists the request body, the token, the
  remote IP, the email address or the upstream response. The
  helper never opens a database session.

The helper is the only outbound surface that may contact the abuse
guard; tests can inject a fake transport by monkey-patching
:func:`_post_json` so the production URL is never touched in
tests.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib import error as url_error
from urllib import request as url_request

from backend.auth.settings import SupabaseAuthSettings


class AbuseGuardUnavailable(Exception):
    """Raised when the abuse guard is missing or not authoritative.

    The router converts this signal into the bounded
    service-unavailable view. The exception detail is intentionally
    generic; the visitor never learns why the issuance was refused.
    """

    reason: str

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class AbuseGuardDecision:
    """The documented response from the abuse guard.

    Attributes:
        allowed: Whether the issuance is authorised.
        decision_id: Bounded decision identifier the guard returned
            so the application can correlate logs without echoing
            the underlying payload.
    """

    allowed: bool
    decision_id: str


def _post_json(
    *, url: str, token: str, body: Mapping[str, Any], timeout: int
) -> Mapping[str, Any]:
    """POST ``body`` to ``url`` and return the JSON-decoded response.

    The helper is intentionally minimal: a 2xx response is decoded
    as JSON and returned; any other outcome is propagated as
    :class:`AbuseGuardUnavailable` so the router can fail closed.
    """
    encoded = json.dumps(body, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    request = url_request.Request(
        url,
        data=encoded,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "novaorders-public-onboarding-abuse-guard",
        },
        method="POST",
    )
    try:
        with url_request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", None) or response.getcode()
            raw = response.read()
    except url_error.HTTPError as exc:
        raise AbuseGuardUnavailable("guard_status_error") from exc
    except url_error.URLError as exc:
        raise AbuseGuardUnavailable("guard_unreachable") from exc
    except TimeoutError as exc:
        raise AbuseGuardUnavailable("guard_timeout") from exc
    if status < 200 or status >= 300:
        raise AbuseGuardUnavailable("guard_status_error")
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise AbuseGuardUnavailable("guard_malformed_response") from exc
    if not isinstance(decoded, Mapping):
        raise AbuseGuardUnavailable("guard_malformed_response")
    return decoded


def request_magic_link_authorization(
    *,
    email: str,
    settings: SupabaseAuthSettings,
    remote_ip: str | None = None,
    transport: Any = None,
) -> AbuseGuardDecision:
    """Return the abuse-guard decision for a magic-link issuance.

    When ``transport`` is ``None`` the helper uses the production
    :func:`urllib.request`-based transport; tests inject a stub that
    mirrors the same return contract so the boundary stays
    verifiable.
    """
    if not settings.enabled:
        raise AbuseGuardUnavailable("feature_disabled")
    if not settings.abuse_guard_url or not settings.abuse_guard_token:
        raise AbuseGuardUnavailable("abuse_guard_missing")

    cleaned_email = email.strip().lower()
    if not cleaned_email:
        raise AbuseGuardUnavailable("email_missing")

    body: dict[str, Any] = {"email": cleaned_email, "action": "magic_link"}
    if isinstance(remote_ip, str) and remote_ip.strip():
        body["remote_ip"] = remote_ip.strip()

    post = transport if transport is not None else _post_json
    response = post(
        url=settings.abuse_guard_url,
        token=settings.abuse_guard_token,
        body=body,
        timeout=settings.request_timeout_seconds,
    )
    allowed = response.get("allowed")
    decision_id = response.get("decision_id")
    if not isinstance(allowed, bool):
        raise AbuseGuardUnavailable("guard_malformed_response")
    if not isinstance(decision_id, str) or not decision_id.strip():
        raise AbuseGuardUnavailable("guard_malformed_response")
    return AbuseGuardDecision(allowed=allowed, decision_id=decision_id.strip())


__all__ = [
    "AbuseGuardDecision",
    "AbuseGuardUnavailable",
    "request_magic_link_authorization",
]