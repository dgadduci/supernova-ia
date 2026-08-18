"""Phase 2 authenticated principal.

The principal is the only data the Phase 2 router exposes to
business code after a Supabase JWT has been verified. It carries the
validated external subject and nothing else so a later phase can
extend the principal without changing the cookie contract.

The principal is immutable and frozen so a route handler cannot
accidentally rewrite it. It is intentionally not a SQLAlchemy
model: Phase 2 must not persist any identity row.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """The single subject carried by a Phase 2 local session.

    Attributes:
        subject: The validated, immutable external subject claim
            extracted from the provider JWT. The value is a
            non-empty stripped string by construction; the validator
            rejects tokens with a missing or empty subject.
        issuer: The exact issuer claim that was verified. The
            router only ever constructs the principal after a
            successful match against the configured issuer.
        audience: The exact audience claim that was verified.
    """

    subject: str
    issuer: str
    audience: str

    def __post_init__(self) -> None:
        if not isinstance(self.subject, str) or not self.subject.strip():
            raise TypeError(
                "AuthenticatedPrincipal.subject must be a non-empty string"
            )
        if not isinstance(self.issuer, str) or not self.issuer.strip():
            raise TypeError(
                "AuthenticatedPrincipal.issuer must be a non-empty string"
            )
        if not isinstance(self.audience, str) or not self.audience.strip():
            raise TypeError(
                "AuthenticatedPrincipal.audience must be a non-empty string"
            )


__all__ = ["AuthenticatedPrincipal"]
