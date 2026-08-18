"""Phase 2 Supabase magic-link identity boundary.

The package is the smallest viable surface for passwordless
authentication of commerce-owner principals in NovaOrders. The
package exposes:

* :class:`SupabaseAuthSettings` — the resolved, fail-closed
  configuration consumed by every other helper. Loading it requires
  the operator to publish a complete identity contract before the
  router can issue or accept sessions.
* :mod:`backend.auth.jwt_validator` — server-side JWT verification
  via JWKS with allowlisted asymmetric algorithms, exact issuer /
  audience match, expiry enforcement and a non-empty immutable
  subject.
* :mod:`backend.auth.session` — short-lived local session cookie
  management with ``Secure``, ``HttpOnly`` and ``SameSite=Lax``
  flags.
* :mod:`backend.auth.pkce` — server-side PKCE verifier / challenge
  generation and short-lived signed temp-cookie management used to
  bind the magic-link request to its callback.
* :mod:`backend.auth.abuse_guard` — verifiable dependency / adapter
  that calls the edge/hosting rate-limit gate before any Supabase
  OTP request. The helper fails closed when the gate is unavailable.
* :mod:`backend.auth.supabase_client` — outbound magic-link request
  client (the documented Supabase ``/auth/v1/otp`` endpoint) and
  the bounded code-exchange client used by the callback.
* :mod:`backend.auth.principal` — the request principal exposed by
  :func:`backend.dependencies.get_authenticated_principal` once the
  Phase 2 verification chain succeeds.

Phase 2 creates no ``CuentaUsuario``, ``ComercioUsuario`` or draft
row. The principal carries only the validated external subject so a
later phase can extend it without changing the cookie contract.
"""

from backend.auth.pkce import PKCE_COOKIE_NAME
from backend.auth.principal import AuthenticatedPrincipal
from backend.auth.session import SESSION_COOKIE_NAME
from backend.auth.settings import (
    SupabaseAuthSettings,
    resolve_supabase_auth_settings,
)

__all__ = [
    "PKCE_COOKIE_NAME",
    "SESSION_COOKIE_NAME",
    "AuthenticatedPrincipal",
    "SupabaseAuthSettings",
    "resolve_supabase_auth_settings",
]