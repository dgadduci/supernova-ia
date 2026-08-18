"""Focused tests for the Phase 2 Supabase magic-link identity boundary.

The change ``add-commerce-self-service-onboarding`` introduces a
small identity surface in Phase 2. The tests in this file cover
the boundary's full contract:

* Settings — the feature is disabled by default; enabling it
  without a complete configuration raises a typed
  ``InvalidSupabaseAuthConfig`` so the router never reaches the
  link request / callback path. Service-role markers are rejected
  for the publishable key.
* Algorithm allowlist — the helper refuses HMAC algorithms so an
  operator cannot silently downgrade the asymmetric JWKS
  contract.
* Email validation — the email request helper accepts only
  syntactically valid addresses.
* Link request — the magic-link POST is enumeration-safe (same
  response for known and unknown emails) and never contacts the
  provider when the abuse guard is missing or when the input is
  invalid.
* PKCE — the server-side verifier / challenge pair is generated
  with a documented length and method; the temp cookie is signed
  with the configured secret and rejected on every tampering /
  expiry / shape failure.
* JWKS-only JWT validation — the validator rejects missing /
  expired / malformed tokens, refuses every algorithm outside the
  asymmetric allowlist, enforces exact issuer / audience / expiry /
  subject match, and collapses JWKS errors into
  ``jwks_unavailable`` so the router fails closed.
* Session cookie — the encoded cookie carries the documented
  flags (``Secure``, ``HttpOnly``, ``SameSite=Lax``, ``Max-``), is
  signed with the configured secret, is rejected on every
  tampering / expiry / shape failure, and refuses to be issued
  over plain HTTP.
* Routes — ``POST /comenzar`` is enumeration-safe; ``GET
  /auth/callback`` accepts only the documented ``code`` parameter,
  exchanges it server-side, validates the resulting JWT via JWKS
  and redirects to a clean URL without leaking the code, the
  token, the error description or the verifier. ``POST
  /auth/logout`` clears the cookies; ``GET /auth/verificado``
  shows the bounded verified view only when the cookie is valid.
* Persistence isolation — none of the routes touch the database
  session, the commerce models or the lifecycle services.
* Existing surface preservation — ``/admin`` keeps its credential
  gate; ``/health`` keeps the documented payload; the Twilio
  webhook still rejects unsigned POSTs.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import unittest
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import (
    PKCE_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    resolve_supabase_auth_settings,
)
from backend.auth.abuse_guard import AbuseGuardDecision, AbuseGuardUnavailable
from backend.auth.jwt_validator import (
    JwtValidationError,
    validate_supabase_jwt,
)
from backend.auth.pkce import (
    PkceValidationError,
    build_clear_pkce_cookie_header,
    build_pkce_cookie_header,
    decode_pkce_cookie,
    encode_pkce_cookie,
    generate_pkce_pair,
    parse_pkce_cookie,
)
from backend.auth.session import (
    InsecureCookieDeliveryError,
    SessionValidationError,
    build_clear_cookie_header,
    build_cookie_header,
    decode_session,
    encode_session,
    parse_session_cookie,
)
from backend.auth.supabase_client import (
    SupabaseAuthError,
    build_otp_request,
    exchange_magic_link_code,
    is_valid_email_shape,
    request_magic_link_otp,
)
from backend.config.settings import Settings
from backend.dependencies import get_session
from backend.services.exceptions import InvalidSupabaseAuthConfig


def _build_test_settings(**overrides: Any) -> Settings:
    """Build a :class:`Settings` instance with safe test defaults.

    The helper pins the documented Phase 2 contract: every value
    that must be configured when the feature is enabled is
    provided; values that must remain unset stay ``None``. Tests
    can override individual fields without rebuilding the whole
    dataclass.
    """
    base = Settings(
        llm_url="http://localhost:11434/api/generate",
        llm_model="qwen2.5-coder:7b-ctx8192",
        llm_timeout=180,
        llm_keep_alive="2h",
        llm_num_ctx=8192,
        llm_num_predict=0,
        llm_log_content=False,
        llm_log_max_chars=1000,
    )
    for field_name, value in overrides.items():
        object.__setattr__(base, field_name, value)
    return base


def _enabled_settings(**overrides: Any) -> Any:
    """Return a fully-enabled :class:`SupabaseAuthSettings` instance.

    Tests can override any individual field (algorithm allowlist,
    callback URL, issuer, etc.) without rebuilding the rest of the
    contract. The publishable key is a JWT-shaped string so it
    survives the publishable-key validator; the abuse guard URL
    and token are pinned so the issuance path can call the guard.
    """
    base = {
        "supabase_auth_enabled": True,
        "supabase_project_url": "https://abc.supabase.co",
        "supabase_jwt_issuer": "https://abc.supabase.co/auth/v1",
        "supabase_jwt_audience": "authenticated",
        "supabase_callback_url": "https://nova.example.com/auth/callback",
        "supabase_jwks_url": "https://abc.supabase.co/auth/v1/jwks",
        "supabase_publishable_key": (
            "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.sig"
        ),
        "supabase_session_secret": "local-session-secret-for-tests-32b",
        "supabase_session_max_age_seconds": 1800,
        "supabase_pkce_cookie_max_age_seconds": 300,
        "supabase_allowed_algorithms": ("RS256",),
        "supabase_abuse_guard_url": "https://guard.example.com/check",
        "supabase_abuse_guard_token": "guard-token",
        "supabase_request_timeout_seconds": 10,
    }
    base.update(overrides)
    settings = _build_test_settings(**base)
    return resolve_supabase_auth_settings(settings=settings)


def _disabled_settings(**overrides: Any) -> Any:
    """Return a disabled :class:`SupabaseAuthSettings` instance."""
    base: dict[str, Any] = {"supabase_auth_enabled": False}
    base.update(overrides)
    settings = _build_test_settings(**base)
    return resolve_supabase_auth_settings(settings=settings)


def _mint_token(
    *,
    settings: Any,
    subject: str = "user-123",
    issuer: str | None = None,
    audience: str | None = None,
    expires_in: int = 3600,
    secret: str | None = None,
    algorithm: str = "RS256",
    private_key: Any | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Mint a synthetic JWT against ``settings``.

    ``settings`` may be either a :class:`Settings` or a
    :class:`SupabaseAuthSettings` instance. The helper accepts
    both so test cases can mint a token before resolving the
    auth settings.
    """
    if hasattr(settings, "jwt_issuer"):
        resolved_issuer = settings.jwt_issuer
        resolved_audience = settings.jwt_audience
    else:
        resolved_issuer = settings.supabase_jwt_issuer
        resolved_audience = settings.supabase_jwt_audience
    payload: dict[str, Any] = {
        "sub": subject,
        "iss": issuer if issuer is not None else resolved_issuer,
        "aud": audience if audience is not None else resolved_audience,
        "exp": int(time.time()) + expires_in,
    }
    if extra_claims:
        payload.update(extra_claims)
    if private_key is not None:
        signing_key = private_key
    elif secret is not None:
        signing_key = secret
    else:
        signing_key = "unused"
    return jwt.encode(payload, signing_key, algorithm=algorithm)


def _build_public_onboarding_app() -> FastAPI:
    """Build a FastAPI app with only the public onboarding router."""
    app = FastAPI()
    import backend.routers.public_onboarding as router_module
    app.include_router(router_module.router)
    return app


def _rsa_keypair():
    """Generate a fresh RSA keypair for ES/RS256 signing in tests."""
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048
    )
    return private_key, private_key.public_key()


class _SessionOverride:
    """Test double that ``s how many times ``get_session`` ran."""

    def __init__(self, return_value: object) -> None:
        self._return_value = return_value
        self.call_count = 0

    def __call__(self) -> object:
        self.call_count += 1
        return self._return_value

    def assert_not_called(self) -> None:
        if self.call_count != 0:
            raise AssertionError(
                f"session override was called {self.call_count} time(s)"
            )


def _install_session_override(
    test: unittest.TestCase, app: FastAPI, session: object
) -> _SessionOverride:
    override = _SessionOverride(session)

    def _dependency() -> object:
        return override()

    app.dependency_overrides[get_session] = _dependency
    test.addCleanup(lambda: app.dependency_overrides.pop(get_session, None))
    return override


def _with_settings(
    test: unittest.TestCase, **overrides: Any
) -> tuple[Any, dict[str, Any]]:
    """Patch :func:`resolve_supabase_auth_settings` for ``test``.

    Returns the resolved :class:`SupabaseAuthSettings` instance
    together with the overrides applied.
    """
    base = {
        "supabase_auth_enabled": True,
        "supabase_project_url": "https://abc.supabase.co",
        "supabase_jwt_issuer": "https://abc.supabase.co/auth/v1",
        "supabase_jwt_audience": "authenticated",
        "supabase_callback_url": "https://nova.example.com/auth/callback",
        "supabase_jwks_url": "https://abc.supabase.co/auth/v1/jwks",
        "supabase_publishable_key": (
            "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.sig"
        ),
        "supabase_session_secret": "local-session-secret-for-tests-32b",
        "supabase_session_max_age_seconds": 1800,
        "supabase_pkce_cookie_max_age_seconds": 300,
        "supabase_allowed_algorithms": ("RS256",),
        "supabase_abuse_guard_url": "https://guard.example.com/check",
        "supabase_abuse_guard_token": "guard-token",
        "supabase_request_timeout_seconds": 10,
    }
    base.update(overrides)
    settings = _build_test_settings(**base)
    auth_settings = resolve_supabase_auth_settings(settings=settings)
    patches = [
        patch(
            "backend.auth.resolve_supabase_auth_settings",
            return_value=auth_settings,
        ),
        patch(
            "backend.routers.public_onboarding.resolve_supabase_auth_settings",
            return_value=auth_settings,
        ),
        patch(
            "backend.dependencies.resolve_supabase_auth_settings",
            return_value=auth_settings,
        ),
    ]
    for patcher in patches:
        patcher.start()
        test.addCleanup(patcher.stop)
    return auth_settings, overrides


class SupabaseSettingsDisabledTest(unittest.TestCase):
    """The feature stays off by default."""

    def test_feature_disabled_when_env_var_is_unset(self) -> None:
        saved = {key: os.environ.pop(key, None) for key in (
            "SUPABASE_AUTH_ENABLED",
            "SUPABASE_PROJECT_URL",
            "SUPABASE_JWT_ISSUER",
            "SUPABASE_CALLBACK_URL",
            "SUPABASE_PUBLISHABLE_KEY",
            "SUPABASE_JWKS_URL",
            "SUPABASE_SESSION_SECRET",
            "SUPABASE_ABUSE_GUARD_URL",
            "SUPABASE_ABUSE_GUARD_TOKEN",
        )}
        try:
            settings = resolve_supabase_auth_settings()
            self.assertFalse(settings.enabled)
            self.assertEqual(settings.callback_path, "/auth/callback")
            self.assertEqual(settings.jwt_audience, "authenticated")
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value

    def test_enabled_settings_requires_complete_configuration(self) -> None:
        with self.assertRaises(InvalidSupabaseAuthConfig):
            resolve_supabase_auth_settings(
                settings=_build_test_settings(supabase_auth_enabled=True)
            )

    def test_publishable_key_must_be_jwt_shaped(self) -> None:
        with patch.dict(
            os.environ,
            {"SUPABASE_PUBLISHABLE_KEY": "not-a-jwt-shape"},
            clear=False,
        ):
            with self.assertRaises(InvalidSupabaseAuthConfig):
                from backend.config.settings import (
                    _supabase_publishable_key_env,
                )
                _supabase_publishable_key_env("SUPABASE_PUBLISHABLE_KEY")

    def test_callback_must_anchor_at_callback_path(self) -> None:
        with self.assertRaises(InvalidSupabaseAuthConfig):
            resolve_supabase_auth_settings(
                settings=_build_test_settings(
                    supabase_auth_enabled=True,
                    supabase_project_url="https://abc.supabase.co",
                    supabase_jwt_issuer="https://abc.supabase.co/auth/v1",
                    supabase_jwt_audience="authenticated",
                    supabase_callback_url=(
                        "https://nova.example.com/onboarding"
                    ),
                    supabase_jwks_url="https://abc.supabase.co/auth/v1/jwks",
                    supabase_publishable_key=(
                        "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.sig"
                    ),
                    supabase_session_secret="local-session-secret-for-tests-32b",
                    supabase_abuse_guard_url="https://guard.example.com/check",
                    supabase_abuse_guard_token="guard",
                )
            )

    def test_project_url_must_be_https(self) -> None:
        with self.assertRaises(InvalidSupabaseAuthConfig):
            resolve_supabase_auth_settings(
                settings=_build_test_settings(
                    supabase_auth_enabled=True,
                    supabase_project_url="http://abc.supabase.co",
                )
            )

    def test_audience_must_equal_authenticated(self) -> None:
        with self.assertRaises(InvalidSupabaseAuthConfig):
            resolve_supabase_auth_settings(
                settings=_build_test_settings(
                    supabase_auth_enabled=True,
                    supabase_jwt_audience="other-audience",
                )
            )

    def test_jwks_must_be_configured_when_enabled(self) -> None:
        with self.assertRaises(InvalidSupabaseAuthConfig):
            resolve_supabase_auth_settings(
                settings=_build_test_settings(
                    supabase_auth_enabled=True,
                    supabase_project_url="https://abc.supabase.co",
                    supabase_jwt_issuer="https://abc.supabase.co/auth/v1",
                    supabase_callback_url="https://nova.example.com/auth/callback",
                    supabase_publishable_key=(
                        "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.sig"
                    ),
                    supabase_session_secret="local-session-secret-for-tests-32b",
                    supabase_jwks_url=None,
                    supabase_abuse_guard_url="https://guard.example.com/check",
                    supabase_abuse_guard_token="guard",
                )
            )

    def test_hmac_algorithm_is_rejected_in_allowlist(self) -> None:
        with self.assertRaises(InvalidSupabaseAuthConfig):
            resolve_supabase_auth_settings(
                settings=_build_test_settings(
                    supabase_auth_enabled=True,
                    supabase_project_url="https://abc.supabase.co",
                    supabase_jwt_issuer="https://abc.supabase.co/auth/v1",
                    supabase_callback_url="https://nova.example.com/auth/callback",
                    supabase_jwks_url="https://abc.supabase.co/auth/v1/jwks",
                    supabase_publishable_key=(
                        "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.sig"
                    ),
                    supabase_session_secret="local-session-secret-for-tests-32b",
                    supabase_allowed_algorithms=("HS256",),
                    supabase_abuse_guard_url="https://guard.example.com/check",
                    supabase_abuse_guard_token="guard",
                )
            )

    def test_abuse_guard_url_and_token_must_be_paired(self) -> None:
        with self.assertRaises(InvalidSupabaseAuthConfig):
            resolve_supabase_auth_settings(
                settings=_build_test_settings(
                    supabase_auth_enabled=True,
                    supabase_project_url="https://abc.supabase.co",
                    supabase_jwt_issuer="https://abc.supabase.co/auth/v1",
                    supabase_callback_url="https://nova.example.com/auth/callback",
                    supabase_jwks_url="https://abc.supabase.co/auth/v1/jwks",
                    supabase_publishable_key=(
                        "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.sig"
                    ),
                    supabase_session_secret="local-session-secret-for-tests-32b",
                    supabase_abuse_guard_url="https://guard.example.com/check",
                    supabase_abuse_guard_token=None,
                )
            )


class EmailValidationTest(unittest.TestCase):
    """The email helper accepts only syntactically valid envelopes."""

    def test_accepts_canonical_addresses(self) -> None:
        self.assertTrue(is_valid_email_shape("owner@example.com"))
        self.assertTrue(is_valid_email_shape("a.b+c@sub.example.co"))

    def test_rejects_empty_or_whitespace(self) -> None:
        self.assertFalse(is_valid_email_shape(""))
        self.assertFalse(is_valid_email_shape("   "))
        self.assertFalse(is_valid_email_shape(None))  # type: ignore[arg-type]

    def test_rejects_missing_or_extra_at_signs(self) -> None:
        self.assertFalse(is_valid_email_shape("owner.example.com"))
        self.assertFalse(is_valid_email_shape("a@b@c.example.com"))

    def test_rejects_missing_local_or_domain(self) -> None:
        self.assertFalse(is_valid_email_shape("@example.com"))
        self.assertFalse(is_valid_email_shape("owner@"))

    def test_rejects_domain_without_dot(self) -> None:
        self.assertFalse(is_valid_email_shape("owner@example"))

    def test_rejects_internal_whitespace(self) -> None:
        self.assertFalse(is_valid_email_shape("own er@example.com"))


class OtpRequestTest(unittest.TestCase):
    """The OTP helper builds the documented Supabase envelope."""

    def test_request_uses_documented_endpoint(self) -> None:
        settings = _enabled_settings()
        self.assertEqual(
            settings.otp_endpoint, "https://abc.supabase.co/auth/v1/otp"
        )

    def test_request_envelope_pins_should_create_user_false(self) -> None:
        settings = _enabled_settings()
        request = build_otp_request(
            email="owner@example.com",
            challenge="challenge-value",
            settings=settings,
        )
        self.assertEqual(request.email, "owner@example.com")
        self.assertEqual(request.callback_url, settings.callback_url)
        self.assertEqual(request.challenge, "challenge-value")
        self.assertEqual(request.challenge_method, "S256")
        self.assertFalse(request.should_create_user)

    def test_request_rejects_empty_email(self) -> None:
        settings = _enabled_settings()
        with self.assertRaises(SupabaseAuthError):
            build_otp_request(
                email="", challenge="x", settings=settings
            )

    def test_request_rejects_empty_challenge(self) -> None:
        settings = _enabled_settings()
        with self.assertRaises(SupabaseAuthError):
            build_otp_request(
                email="owner@example.com", challenge="", settings=settings
            )


class PkceTest(unittest.TestCase):
    """The PKCE helper owns the verifier / challenge pair and temp cookie."""

    def test_pair_has_documented_method(self) -> None:
        pair = generate_pkce_pair()
        self.assertTrue(pair.verifier)
        self.assertTrue(pair.challenge)
        self.assertEqual(pair.method, "S256")
        digest = hashlib.sha256(pair.verifier.encode("ascii")).digest()
        expected = (
            base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        )
        self.assertEqual(pair.challenge, expected)

    def test_pair_uses_secrets_token_urlsafe(self) -> None:
        first = generate_pkce_pair()
        second = generate_pkce_pair()
        self.assertNotEqual(first.verifier, second.verifier)
        self.assertNotEqual(first.challenge, second.challenge)

    def test_cookie_round_trip(self) -> None:
        settings = _enabled_settings()
        pair = generate_pkce_pair()
        encoded = encode_pkce_cookie(pair=pair, settings=settings)
        decoded = decode_pkce_cookie(encoded, settings=settings)
        self.assertEqual(decoded.verifier, pair.verifier)
        self.assertFalse(decoded.is_expired)

    def test_tampered_cookie_signature_is_rejected(self) -> None:
        settings = _enabled_settings()
        pair = generate_pkce_pair()
        encoded = encode_pkce_cookie(pair=pair, settings=settings)
        payload, _, signature = encoded.rpartition(".")
        forged = ".".join((payload, "0" * len(signature)))
        with self.assertRaises(PkceValidationError):
            decode_pkce_cookie(forged, settings=settings)

    def test_expired_cookie_is_rejected(self) -> None:
        settings = _enabled_settings(supabase_pkce_cookie_max_age_seconds=-1)
        pair = generate_pkce_pair()
        encoded = encode_pkce_cookie(pair=pair, settings=settings)
        with self.assertRaises(PkceValidationError):
            decode_pkce_cookie(encoded, settings=settings)

    def test_pkce_cookie_header_carries_secure_flag(self) -> None:
        settings = _enabled_settings()
        header = build_pkce_cookie_header(
            value="encoded",
            settings=settings,
            request_is_secure=True,
        )
        self.assertIn("HttpOnly", header)
        self.assertIn("SameSite=Lax", header)
        self.assertIn("Secure", header)
        self.assertIn(
            f"Max-Age={settings.pkce_cookie_max_age_seconds}", header
        )
        self.assertIn("Path=/auth/callback", header)
        self.assertTrue(header.startswith(f"{PKCE_COOKIE_NAME}="))

    def test_clear_pkce_cookie_uses_max_age_zero(self) -> None:
        header = build_clear_pkce_cookie_header(request_is_secure=True)
        self.assertIn("Max-Age=0", header)
        self.assertIn("Secure", header)

    def test_missing_cookie_returns_none(self) -> None:
        settings = _enabled_settings()
        self.assertIsNone(parse_pkce_cookie({}, settings=settings))

    def test_present_but_tampered_cookie_raises(self) -> None:
        settings = _enabled_settings()
        headers = {"cookie": f"{PKCE_COOKIE_NAME}=garbage"}
        with self.assertRaises(PkceValidationError):
            parse_pkce_cookie(headers, settings=settings)


class JwtValidatorTest(unittest.TestCase):
    """Server-side JWT validation enforces every Phase 2 contract."""

    def setUp(self) -> None:
        self.settings = _enabled_settings(
            supabase_allowed_algorithms=("RS256",)
        )
        self.private_key, self.public_key = _rsa_keypair()

    def _mint_valid_token(self, **overrides: Any) -> str:
        return _mint_token(
            settings=self.settings,
            algorithm="RS256",
            private_key=self.private_key,
            **overrides,
        )

    def test_valid_token_returns_principal(self) -> None:
        token = self._mint_valid_token()
        with patch(
            "backend.auth.jwt_validator.PyJWKClient.get_signing_key_from_jwt",
            return_value=MagicMock(key=self.public_key),
        ):
            principal = validate_supabase_jwt(
                token, settings=self.settings
            )
        self.assertEqual(principal.subject, "user-123")
        self.assertEqual(principal.issuer, self.settings.jwt_issuer)
        self.assertEqual(principal.audience, self.settings.jwt_audience)

    def test_missing_token_is_rejected(self) -> None:
        with self.assertRaises(JwtValidationError):
            validate_supabase_jwt("", settings=self.settings)
        with self.assertRaises(JwtValidationError):
            validate_supabase_jwt("   ", settings=self.settings)

    def test_malformed_token_is_rejected(self) -> None:
        with self.assertRaises(JwtValidationError):
            validate_supabase_jwt("not-a-jwt", settings=self.settings)

    def test_expired_token_is_rejected(self) -> None:
        token = self._mint_valid_token(expires_in=-3600)
        with patch(
            "backend.auth.jwt_validator.PyJWKClient.get_signing_key_from_jwt",
            return_value=MagicMock(key=self.public_key),
        ):
            with self.assertRaises(JwtValidationError) as ctx:
                validate_supabase_jwt(token, settings=self.settings)
        self.assertEqual(ctx.exception.reason, "token_expired")

    def test_unexpected_issuer_is_rejected(self) -> None:
        token = self._mint_valid_token(
            issuer="https://attacker.example.com/auth/v1"
        )
        with patch(
            "backend.auth.jwt_validator.PyJWKClient.get_signing_key_from_jwt",
            return_value=MagicMock(key=self.public_key),
        ):
            with self.assertRaises(JwtValidationError) as ctx:
                validate_supabase_jwt(token, settings=self.settings)
        self.assertEqual(ctx.exception.reason, "issuer_invalid")

    def test_unexpected_audience_is_rejected(self) -> None:
        token = self._mint_valid_token(audience="service_role")
        with patch(
            "backend.auth.jwt_validator.PyJWKClient.get_signing_key_from_jwt",
            return_value=MagicMock(key=self.public_key),
        ):
            with self.assertRaises(JwtValidationError) as ctx:
                validate_supabase_jwt(token, settings=self.settings)
        self.assertEqual(ctx.exception.reason, "audience_invalid")

    def test_invalid_signature_is_rejected(self) -> None:
        other_private, _ = _rsa_keypair()
        token = _mint_token(
            settings=self.settings,
            algorithm="RS256",
            private_key=other_private,
        )
        with patch(
            "backend.auth.jwt_validator.PyJWKClient.get_signing_key_from_jwt",
            return_value=MagicMock(key=self.public_key),
        ):
            with self.assertRaises(JwtValidationError) as ctx:
                validate_supabase_jwt(token, settings=self.settings)
        self.assertEqual(ctx.exception.reason, "signature_invalid")

    def test_disallowed_algorithm_is_rejected(self) -> None:
        token = self._mint_valid_token()
        # The forged header trick: change the alg to HS256 (HMAC).
        # The asymmetric allowlist refuses to accept the token.
        import json as json_lib

        header_b64 = token.split(".")[0]
        padded = header_b64 + "=" * (-len(header_b64) % 4)
        header = json_lib.loads(base64.urlsafe_b64decode(padded))
        header["alg"] = "HS256"
        forged_header = base64.urlsafe_b64encode(
            json_lib.dumps(header, separators=(",", ":")).encode("utf-8")
        ).rstrip(b"=").decode("ascii")
        forged_token = f"{forged_header}.{token.split('.', 1)[1]}"
        with self.assertRaises(JwtValidationError) as ctx:
            validate_supabase_jwt(forged_token, settings=self.settings)
        self.assertIn(
            ctx.exception.reason,
            ("algorithm_not_allowed", "signature_invalid", "token_malformed"),
        )

    def test_missing_subject_is_rejected(self) -> None:
        token = jwt.encode(
            {
                "iss": self.settings.jwt_issuer,
                "aud": self.settings.jwt_audience,
                "exp": int(time.time()) + 3600,
            },
            self.private_key,
            algorithm="RS256",
        )
        with patch(
            "backend.auth.jwt_validator.PyJWKClient.get_signing_key_from_jwt",
            return_value=MagicMock(key=self.public_key),
        ):
            with self.assertRaises(JwtValidationError) as ctx:
                validate_supabase_jwt(token, settings=self.settings)
        self.assertEqual(ctx.exception.reason, "subject_missing")

    def test_empty_subject_is_rejected(self) -> None:
        token = jwt.encode(
            {
                "sub": "   ",
                "iss": self.settings.jwt_issuer,
                "aud": self.settings.jwt_audience,
                "exp": int(time.time()) + 3600,
            },
            self.private_key,
            algorithm="RS256",
        )
        with patch(
            "backend.auth.jwt_validator.PyJWKClient.get_signing_key_from_jwt",
            return_value=MagicMock(key=self.public_key),
        ):
            with self.assertRaises(JwtValidationError) as ctx:
                validate_supabase_jwt(token, settings=self.settings)
        self.assertEqual(ctx.exception.reason, "subject_missing")

    def test_jwks_unavailable_fails_closed(self) -> None:
        settings = _enabled_settings(supabase_allowed_algorithms=("RS256",))
        token = self._mint_valid_token()
        with patch(
            "backend.auth.jwt_validator.PyJWKClient",
            side_effect=Exception("network unreachable"),
        ):
            with self.assertRaises(JwtValidationError) as ctx:
                validate_supabase_jwt(token, settings=settings)
        self.assertEqual(ctx.exception.reason, "jwks_unavailable")

    def test_jwks_unknown_kid_fails_closed(self) -> None:
        settings = _enabled_settings(supabase_allowed_algorithms=("RS256",))
        token = self._mint_valid_token()
        other_private, _ = _rsa_keypair()
        with patch(
            "backend.auth.jwt_validator.PyJWKClient.get_signing_key_from_jwt",
            return_value=MagicMock(key=other_private.public_key()),
        ):
            with self.assertRaises(JwtValidationError) as ctx:
                validate_supabase_jwt(token, settings=settings)
        self.assertEqual(ctx.exception.reason, "signature_invalid")

    def test_jwks_empty_key_fails_closed(self) -> None:
        settings = _enabled_settings(supabase_allowed_algorithms=("RS256",))
        token = self._mint_valid_token()
        with patch(
            "backend.auth.jwt_validator.PyJWKClient.get_signing_key_from_jwt",
            return_value=MagicMock(key=""),
        ):
            with self.assertRaises(JwtValidationError) as ctx:
                validate_supabase_jwt(token, settings=settings)
        self.assertEqual(ctx.exception.reason, "jwks_key_empty")


class SessionCookieTest(unittest.TestCase):
    """The local session cookie carries every documented flag."""

    def setUp(self) -> None:
        self.settings = _enabled_settings()
        from backend.auth.principal import AuthenticatedPrincipal

        self.principal = AuthenticatedPrincipal(
            subject="user-123",
            issuer=self.settings.jwt_issuer,
            audience=self.settings.jwt_audience,
        )

    def test_round_trip_preserves_subject(self) -> None:
        value = encode_session(self.principal, settings=self.settings)
        decoded = decode_session(value, settings=self.settings)
        self.assertEqual(decoded.subject, self.principal.subject)
        self.assertEqual(decoded.issuer, self.principal.issuer)
        self.assertEqual(decoded.audience, self.principal.audience)

    def test_cookie_header_carries_secure_over_https(self) -> None:
        value = encode_session(self.principal, settings=self.settings)
        header = build_cookie_header(
            value=value,
            settings=self.settings,
            request_is_secure=True,
        )
        self.assertIn("HttpOnly", header)
        self.assertIn("SameSite=lax", header)
        self.assertIn("Secure", header)
        self.assertIn("Path=/", header)
        self.assertIn(
            f"Max-Age={self.settings.session_max_age_seconds}", header
        )
        self.assertTrue(header.startswith(f"{SESSION_COOKIE_NAME}="))

    def test_cookie_header_refuses_to_be_issued_over_http(self) -> None:
        value = encode_session(self.principal, settings=self.settings)
        with self.assertRaises(InsecureCookieDeliveryError):
            build_cookie_header(
                value=value,
                settings=self.settings,
                request_is_secure=False,
            )

    def test_clear_cookie_header_removes_session(self) -> None:
        header = build_clear_cookie_header(request_is_secure=True)
        self.assertIn("Max-Age=0", header)
        self.assertIn("HttpOnly", header)
        self.assertIn("SameSite=lax", header)
        self.assertIn("Secure", header)

    def test_tampered_signature_is_rejected(self) -> None:
        value = encode_session(self.principal, settings=self.settings)
        payload, _, signature = value.rpartition(".")
        forged = ".".join((payload, "0" * len(signature)))
        with self.assertRaises(SessionValidationError):
            decode_session(forged, settings=self.settings)

    def test_expired_session_is_rejected(self) -> None:
        expired_settings = _enabled_settings(
            supabase_session_max_age_seconds=-1
        )
        value = encode_session(self.principal, settings=expired_settings)
        with self.assertRaises(SessionValidationError):
            decode_session(value, settings=expired_settings)

    def test_missing_cookie_returns_none(self) -> None:
        self.assertIsNone(
            parse_session_cookie({}, settings=self.settings)
        )

    def test_present_but_tampered_cookie_raises(self) -> None:
        bad_headers = {"cookie": f"{SESSION_COOKIE_NAME}=garbage"}
        with self.assertRaises(SessionValidationError):
            parse_session_cookie(bad_headers, settings=self.settings)


class AbuseGuardTest(unittest.TestCase):
    """The abuse guard contract is verifiable and fail-closed."""

    def setUp(self) -> None:
        from backend.auth.abuse_guard import request_magic_link_authorization

        self._call = request_magic_link_authorization

    def test_missing_abuse_guard_blocks_issuance(self) -> None:
        settings = _enabled_settings(
            supabase_abuse_guard_url=None,
            supabase_abuse_guard_token=None,
        )
        with self.assertRaises(AbuseGuardUnavailable) as ctx:
            self._call(
                email="owner@example.com", settings=settings
            )
        self.assertEqual(ctx.exception.reason, "abuse_guard_missing")

    def test_untrusted_transport_blocks_issuance(self) -> None:
        def _untrusted_transport(**kwargs: Any) -> dict[str, Any]:
            raise AbuseGuardUnavailable("guard_unreachable")

        settings = _enabled_settings()
        with self.assertRaises(AbuseGuardUnavailable) as ctx:
            self._call(
                email="owner@example.com",
                settings=settings,
                transport=_untrusted_transport,
            )
        self.assertEqual(ctx.exception.reason, "guard_unreachable")

    def test_trusted_transport_authorises_issuance(self) -> None:
        def _trusted_transport(**kwargs: Any) -> dict[str, Any]:
            return {"allowed": True, "decision_id": "abc-123"}

        settings = _enabled_settings()
        decision = self._call(
            email="owner@example.com",
            settings=settings,
            transport=_trusted_transport,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.decision_id, "abc-123")

    def test_trusted_transport_denial_blocks_issuance(self) -> None:
        def _denying_transport(**kwargs: Any) -> dict[str, Any]:
            return {"allowed": False, "decision_id": "denied-1"}

        settings = _enabled_settings()
        decision = self._call(
            email="owner@example.com",
            settings=settings,
            transport=_denying_transport,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.decision_id, "denied-1")

    def test_missing_decision_id_fails_closed(self) -> None:
        def _bad_transport(**kwargs: Any) -> dict[str, Any]:
            return {"allowed": True}

        settings = _enabled_settings()
        with self.assertRaises(AbuseGuardUnavailable):
            self._call(
                email="owner@example.com",
                settings=settings,
                transport=_bad_transport,
            )

    def test_malformed_response_fails_closed(self) -> None:
        def _bad_transport(**kwargs: Any) -> dict[str, Any]:
            return {"unexpected": True}

        settings = _enabled_settings()
        with self.assertRaises(AbuseGuardUnavailable):
            self._call(
                email="owner@example.com",
                settings=settings,
                transport=_bad_transport,
            )


class LinkRequestRouteTest(unittest.TestCase):
    """``POST /comenzar`` enforces the enumeration-safe contract."""

    def setUp(self) -> None:
        self.session_double = _new_session_double()
        self.app = _build_public_onboarding_app()
        self.override = _install_session_override(
            self, self.app, self.session_double
        )
        self.client = TestClient(
            self.app, raise_server_exceptions=False, follow_redirects=False
        )

    def test_known_and_unknown_emails_return_indistinguishable_pages(
        self,
    ) -> None:
        _with_settings(self)
        with patch(
            "backend.routers.public_onboarding.request_magic_link_otp"
        ) as issue, patch(
            "backend.routers.public_onboarding.request_magic_link_authorization",
            return_value=MagicMock(allowed=True, decision_id="d-1"),
        ):
            known = self.client.post(
                "/comenzar",
                data={"email": "owner@example.com"},
                headers={"x-forwarded-proto": "https"},
            )
            unknown = self.client.post(
                "/comenzar",
                data={"email": "ghost@example.com"},
                headers={"x-forwarded-proto": "https"},
            )
            self.assertEqual(issue.call_count, 2)
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertIn(
            "Si el email está registrado", known.text
        )
        self.assertIn(
            "Si el email está registrado", unknown.text
        )
        self.assertEqual(
            len(known.text), len(unknown.text),
            "Response bodies must be byte-identical",
        )

    def test_invalid_input_does_not_call_provider(self) -> None:
        _with_settings(self)
        with patch(
            "backend.routers.public_onboarding.request_magic_link_otp"
        ) as issue, patch(
            "backend.routers.public_onboarding.request_magic_link_authorization"
        ) as guard:
            response = self.client.post(
                "/comenzar",
                data={"email": "not-an-email"},
                headers={"x-forwarded-proto": "https"},
            )
            self.assertEqual(response.status_code, 200)
            issue.assert_not_called()
            guard.assert_not_called()

    def test_missing_abuse_guard_returns_503(self) -> None:
        _with_settings(
            self,
            supabase_abuse_guard_url=None,
            supabase_abuse_guard_token=None,
        )
        response = self.client.post(
            "/comenzar",
            data={"email": "owner@example.com"},
            headers={"x-forwarded-proto": "https"},
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("No pudimos", response.text)
        self.assertNotIn("owner@example.com", response.text)

    def test_untrusted_abuse_guard_returns_503(self) -> None:
        _with_settings(self)
        with patch(
            "backend.routers.public_onboarding.request_magic_link_authorization",
            side_effect=AbuseGuardUnavailable("guard_unreachable"),
        ):
            response = self.client.post(
                "/comenzar",
                data={"email": "owner@example.com"},
                headers={"x-forwarded-proto": "https"},
            )
        self.assertEqual(response.status_code, 503)

    def test_abuse_guard_denial_fails_closed(self) -> None:
        """A ``denied`` decision must never reach the Supabase provider
        and must never mint the PKCE temp cookie.

        The abuse guard is the documented anti-abuse boundary for
        magic-link issuance. When the guard explicitly denies the
        request the route must:

        * render the bounded ``503`` service-unavailable view,
        * skip the Supabase ``request_magic_link_otp`` call,
        * skip the ``novaorders_owner_pkce`` ``Set-Cookie`` emission,
        * never echo the email, the decision identifier or any
          other guard detail in the response body.
        """
        _with_settings(self)
        with patch(
            "backend.routers.public_onboarding.request_magic_link_authorization",
            return_value=AbuseGuardDecision(
                allowed=False, decision_id="denied-1"
            ),
        ) as guard, patch(
            "backend.routers.public_onboarding.request_magic_link_otp"
        ) as issue:
            response = self.client.post(
                "/comenzar",
                data={"email": "owner@example.com"},
                headers={"x-forwarded-proto": "https"},
            )
        self.assertEqual(response.status_code, 503)
        self.assertIn("No pudimos", response.text)
        self.assertNotIn("owner@example.com", response.text)
        self.assertNotIn("denied-1", response.text)
        issue.assert_not_called()
        self.assertEqual(guard.call_count, 1)
        cookies = response.headers.get_list("set-cookie")
        for cookie_header in cookies:
            self.assertNotIn(PKCE_COOKIE_NAME, cookie_header)
        self.override.assert_not_called()

    def test_provider_timeout_returns_503(self) -> None:
        _with_settings(self)
        with patch(
            "backend.routers.public_onboarding.request_magic_link_authorization",
            return_value=MagicMock(allowed=True, decision_id="d-1"),
        ), patch(
            "backend.routers.public_onboarding.request_magic_link_otp",
            side_effect=SupabaseAuthError("provider_timeout"),
        ):
            response = self.client.post(
                "/comenzar",
                data={"email": "owner@example.com"},
                headers={"x-forwarded-proto": "https"},
            )
        self.assertEqual(response.status_code, 503)

    def test_provider_connection_error_returns_503(self) -> None:
        _with_settings(self)
        with patch(
            "backend.routers.public_onboarding.request_magic_link_authorization",
            return_value=MagicMock(allowed=True, decision_id="d-1"),
        ), patch(
            "backend.routers.public_onboarding.request_magic_link_otp",
            side_effect=SupabaseAuthError("provider_unreachable"),
        ):
            response = self.client.post(
                "/comenzar",
                data={"email": "owner@example.com"},
                headers={"x-forwarded-proto": "https"},
            )
        self.assertEqual(response.status_code, 503)

    def test_get_renders_form_when_enabled(self) -> None:
        _with_settings(self)
        response = self.client.get("/comenzar")
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="email"', response.text)
        self.assertIn('action="/comenzar"', response.text)
        self.assertIn("Pedí tu enlace", response.text)

    def test_post_does_not_open_database_session(self) -> None:
        _with_settings(self)
        with patch(
            "backend.routers.public_onboarding.request_magic_link_authorization",
            return_value=MagicMock(allowed=True, decision_id="d-1"),
        ), patch(
            "backend.routers.public_onboarding.request_magic_link_otp"
        ):
            self.client.post(
                "/comenzar",
                data={"email": "owner@example.com"},
                headers={"x-forwarded-proto": "https"},
            )
        self.override.assert_not_called()

    def test_response_does_not_leak_email_value(self) -> None:
        _with_settings(self)
        response = self.client.post(
            "/comenzar",
            data={"email": "owner@example.com"},
            headers={"x-forwarded-proto": "https"},
        )
        self.assertNotIn("owner@example.com", response.text)

    def test_otp_request_carries_pkce_challenge(self) -> None:
        _with_settings(self)
        with patch(
            "backend.routers.public_onboarding.request_magic_link_authorization",
            return_value=MagicMock(allowed=True, decision_id="d-1"),
        ), patch(
            "backend.routers.public_onboarding.request_magic_link_otp"
        ) as issue:
            self.client.post(
                "/comenzar",
                data={"email": "owner@example.com"},
                headers={"x-forwarded-proto": "https"},
            )
        self.assertEqual(issue.call_count, 1)
        kwargs = issue.call_args.kwargs
        self.assertIn("challenge", kwargs)
        self.assertTrue(kwargs["challenge"])


class CallbackRouteTest(unittest.TestCase):
    """``GET /auth/callback`` exchanges the code and redirects cleanly."""

    def setUp(self) -> None:
        self.session_double = _new_session_double()
        self.app = _build_public_onboarding_app()
        self.override = _install_session_override(
            self, self.app, self.session_double
        )
        self.client = TestClient(
            self.app, raise_server_exceptions=False, follow_redirects=False
        )

    def _pair_cookie(self, settings: Any) -> str:
        pair = generate_pkce_pair()
        return encode_pkce_cookie(pair=pair, settings=settings)

    def test_valid_code_redirects_to_verified(self) -> None:
        settings, _ = _with_settings(self)
        token = _mint_token(
            settings=settings,
            algorithm="RS256",
            private_key=_rsa_keypair()[0],
        )
        with patch(
            "backend.routers.public_onboarding.exchange_magic_link_code",
            return_value=token,
        ), patch(
            "backend.routers.public_onboarding.validate_supabase_jwt"
        ) as validate:
            from backend.auth.principal import AuthenticatedPrincipal

            validate.return_value = AuthenticatedPrincipal(
                subject="user-123",
                issuer=settings.jwt_issuer,
                audience=settings.jwt_audience,
            )
            response = self.client.get(
                "/auth/callback",
                params={"code": "code-123"},
                headers={
                    "cookie": (
                        f"{PKCE_COOKIE_NAME}="
                        f"{self._pair_cookie(settings)}"
                    ),
                    "x-forwarded-proto": "https",
                },
            )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers.get("location"), "/auth/verificado"
        )
        cookies = response.headers.get_list("set-cookie")
        session_cookie = next(
            (c for c in cookies if c.startswith(f"{SESSION_COOKIE_NAME}=")),
            None,
        )
        self.assertIsNotNone(session_cookie)
        self.assertIn("HttpOnly", session_cookie)
        self.assertIn("SameSite=lax", session_cookie)
        self.assertIn("Secure", session_cookie)

    def test_redirect_does_not_carry_code_token_or_error(self) -> None:
        settings, _ = _with_settings(self)
        token = _mint_token(
            settings=settings,
            algorithm="RS256",
            private_key=_rsa_keypair()[0],
        )
        with patch(
            "backend.routers.public_onboarding.exchange_magic_link_code",
            return_value=token,
        ), patch(
            "backend.routers.public_onboarding.validate_supabase_jwt"
        ) as validate:
            from backend.auth.principal import AuthenticatedPrincipal

            validate.return_value = AuthenticatedPrincipal(
                subject="user-123",
                issuer=settings.jwt_issuer,
                audience=settings.jwt_audience,
            )
            response = self.client.get(
                "/auth/callback",
                params={"code": "code-123", "error_description": "leak"},
                headers={
                    "cookie": (
                        f"{PKCE_COOKIE_NAME}="
                        f"{self._pair_cookie(settings)}"
                    ),
                    "x-forwarded-proto": "https",
                },
            )
        location = response.headers.get("location", "")
        self.assertNotIn("code=", location)
        self.assertNotIn("error_description", location)
        self.assertNotIn("leak", location)
        self.assertNotIn("access_token=", location)
        self.assertNotIn("token=", location)

    def test_raw_jwt_in_query_is_rejected(self) -> None:
        settings, _ = _with_settings(self)
        token = _mint_token(
            settings=settings,
            algorithm="RS256",
            private_key=_rsa_keypair()[0],
        )
        response = self.client.get(
            "/auth/callback",
            params={"token": token},
            headers={
                "cookie": (
                    f"{PKCE_COOKIE_NAME}="
                    f"{self._pair_cookie(settings)}"
                ),
                "x-forwarded-proto": "https",
            },
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers.get("location"), "/auth/verificado"
        )

    def test_provider_error_in_query_is_rejected(self) -> None:
        settings, _ = _with_settings(self)
        response = self.client.get(
            "/auth/callback",
            params={"error": "access_denied", "error_description": "leak"},
            headers={
                "cookie": (
                    f"{PKCE_COOKIE_NAME}="
                    f"{self._pair_cookie(settings)}"
                ),
                "x-forwarded-proto": "https",
            },
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers.get("location"), "/auth/verificado"
        )
        cookies = response.headers.get_list("set-cookie")
        session_cookie = next(
            (c for c in cookies if c.startswith(f"{SESSION_COOKIE_NAME}=")),
            None,
        )
        self.assertIsNone(session_cookie)

    def test_missing_code_redirects_without_session(self) -> None:
        settings, _ = _with_settings(self)
        response = self.client.get(
            "/auth/callback",
            headers={
                "cookie": (
                    f"{PKCE_COOKIE_NAME}="
                    f"{self._pair_cookie(settings)}"
                ),
                "x-forwarded-proto": "https",
            },
        )
        self.assertEqual(response.status_code, 303)
        cookies = response.headers.get_list("set-cookie")
        session_cookie = next(
            (c for c in cookies if c.startswith(f"{SESSION_COOKIE_NAME}=")),
            None,
        )
        self.assertIsNone(session_cookie)

    def test_missing_pkce_cookie_redirects_without_session(self) -> None:
        _with_settings(self)
        response = self.client.get(
            "/auth/callback",
            params={"code": "code-123"},
            headers={"x-forwarded-proto": "https"},
        )
        self.assertEqual(response.status_code, 303)
        cookies = response.headers.get_list("set-cookie")
        session_cookie = next(
            (c for c in cookies if c.startswith(f"{SESSION_COOKIE_NAME}=")),
            None,
        )
        self.assertIsNone(session_cookie)

    def test_code_exchange_failure_redirects_without_session(self) -> None:
        settings, _ = _with_settings(self)
        with patch(
            "backend.routers.public_onboarding.exchange_magic_link_code",
            side_effect=SupabaseAuthError("provider_malformed_response"),
        ):
            response = self.client.get(
                "/auth/callback",
                params={"code": "code-123"},
                headers={
                    "cookie": (
                        f"{PKCE_COOKIE_NAME}="
                        f"{self._pair_cookie(settings)}"
                    ),
                    "x-forwarded-proto": "https",
                },
            )
        self.assertEqual(response.status_code, 303)
        cookies = response.headers.get_list("set-cookie")
        session_cookie = next(
            (c for c in cookies if c.startswith(f"{SESSION_COOKIE_NAME}=")),
            None,
        )
        self.assertIsNone(session_cookie)

    def test_jwt_validation_failure_redirects_without_session(self) -> None:
        settings, _ = _with_settings(self)
        with patch(
            "backend.routers.public_onboarding.exchange_magic_link_code",
            return_value="bad-token",
        ), patch(
            "backend.routers.public_onboarding.validate_supabase_jwt",
            side_effect=JwtValidationError("signature_invalid"),
        ):
            response = self.client.get(
                "/auth/callback",
                params={"code": "code-123"},
                headers={
                    "cookie": (
                        f"{PKCE_COOKIE_NAME}="
                        f"{self._pair_cookie(settings)}"
                    ),
                    "x-forwarded-proto": "https",
                },
            )
        self.assertEqual(response.status_code, 303)
        cookies = response.headers.get_list("set-cookie")
        session_cookie = next(
            (c for c in cookies if c.startswith(f"{SESSION_COOKIE_NAME}=")),
            None,
        )
        self.assertIsNone(session_cookie)

    def test_http_request_does_not_mint_session_cookie(self) -> None:
        settings, _ = _with_settings(self)
        token = _mint_token(
            settings=settings,
            algorithm="RS256",
            private_key=_rsa_keypair()[0],
        )
        with patch(
            "backend.routers.public_onboarding.exchange_magic_link_code",
            return_value=token,
        ), patch(
            "backend.routers.public_onboarding.validate_supabase_jwt"
        ) as validate:
            from backend.auth.principal import AuthenticatedPrincipal

            validate.return_value = AuthenticatedPrincipal(
                subject="user-123",
                issuer=settings.jwt_issuer,
                audience=settings.jwt_audience,
            )
            response = self.client.get(
                "/auth/callback",
                params={"code": "code-123"},
                headers={
                    "cookie": (
                        f"{PKCE_COOKIE_NAME}="
                        f"{self._pair_cookie(settings)}"
                    ),
                },
            )
        self.assertEqual(response.status_code, 303)
        cookies = response.headers.get_list("set-cookie")
        session_cookie = next(
            (c for c in cookies if c.startswith(f"{SESSION_COOKIE_NAME}=")),
            None,
        )
        self.assertIsNone(session_cookie)

    def test_callback_does_not_open_database_session(self) -> None:
        settings, _ = _with_settings(self)
        token = _mint_token(
            settings=settings,
            algorithm="RS256",
            private_key=_rsa_keypair()[0],
        )
        with patch(
            "backend.routers.public_onboarding.exchange_magic_link_code",
            return_value=token,
        ), patch(
            "backend.routers.public_onboarding.validate_supabase_jwt"
        ) as validate:
            from backend.auth.principal import AuthenticatedPrincipal

            validate.return_value = AuthenticatedPrincipal(
                subject="user-123",
                issuer=settings.jwt_issuer,
                audience=settings.jwt_audience,
            )
            self.client.get(
                "/auth/callback",
                params={"code": "code-123"},
                headers={
                    "cookie": (
                        f"{PKCE_COOKIE_NAME}="
                        f"{self._pair_cookie(settings)}"
                    ),
                    "x-forwarded-proto": "https",
                },
            )
        self.override.assert_not_called()


class VerifiedRouteTest(unittest.TestCase):
    """``GET /auth/verificado`` shows the bounded verified view."""

    def setUp(self) -> None:
        self.session_double = _new_session_double()
        self.app = _build_public_onboarding_app()
        self.override = _install_session_override(
            self, self.app, self.session_double
        )
        self.client = TestClient(
            self.app, raise_server_exceptions=False, follow_redirects=False
        )

    def test_missing_cookie_renders_sign_in_view(self) -> None:
        _with_settings(self)
        response = self.client.get("/auth/verificado")
        self.assertEqual(response.status_code, 401)
        self.assertIn(
            "Necesitamos confirmar tu identidad", response.text
        )

    def test_valid_cookie_renders_verified_view(self) -> None:
        settings, _ = _with_settings(self)
        from backend.auth.principal import AuthenticatedPrincipal

        principal = AuthenticatedPrincipal(
            subject="user-123",
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
        cookie_value = encode_session(
            principal, settings=settings
        )
        response = self.client.get(
            "/auth/verificado",
            headers={
                "cookie": (
                    f"{SESSION_COOKIE_NAME}={cookie_value}"
                ),
                "x-forwarded-proto": "https",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Identidad verificada; onboarding aún no habilitado",
            response.text,
        )
        self.assertNotIn("Configurá tu comercio", response.text)
        self.assertNotIn("Catálogo", response.text)
        self.assertNotIn("Aceptar pedidos", response.text)

    def test_verified_route_does_not_open_database_session(self) -> None:
        settings, _ = _with_settings(self)
        from backend.auth.principal import AuthenticatedPrincipal

        principal = AuthenticatedPrincipal(
            subject="user-123",
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
        cookie_value = encode_session(
            principal, settings=settings
        )
        self.client.get(
            "/auth/verificado",
            headers={
                "cookie": f"{SESSION_COOKIE_NAME}={cookie_value}",
                "x-forwarded-proto": "https",
            },
        )
        self.override.assert_not_called()


class LogoutRouteTest(unittest.TestCase):
    """``POST /auth/logout`` clears the local session cookie."""

    def setUp(self) -> None:
        self.session_double = _new_session_double()
        self.app = _build_public_onboarding_app()
        self.override = _install_session_override(
            self, self.app, self.session_double
        )
        self.client = TestClient(
            self.app, raise_server_exceptions=False, follow_redirects=False
        )

    def test_logout_redirects_to_comenzar(self) -> None:
        _with_settings(self)
        response = self.client.post("/auth/logout")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers.get("location"), "/comenzar"
        )
        cookies = response.headers.get_list("set-cookie")
        session_cookie = next(
            (c for c in cookies if c.startswith(f"{SESSION_COOKIE_NAME}=")),
            None,
        )
        self.assertIsNotNone(session_cookie)
        self.assertIn("Max-Age=0", session_cookie)
        self.assertIn("HttpOnly", session_cookie)

    def test_logout_does_not_open_database_session(self) -> None:
        _with_settings(self)
        self.client.post("/auth/logout")
        self.override.assert_not_called()


class ConfigInvalidRouteTest(unittest.TestCase):
    """Invalid configuration surfaces a bounded 503 across Phase 2 routes."""

    def setUp(self) -> None:
        self.session_double = _new_session_double()
        self.app = _build_public_onboarding_app()
        self.override = _install_session_override(
            self, self.app, self.session_double
        )
        self.client = TestClient(
            self.app, raise_server_exceptions=False, follow_redirects=False
        )

    def test_comenzar_get_returns_bounded_503(self) -> None:
        with patch(
            "backend.routers.public_onboarding.resolve_supabase_auth_settings",
            side_effect=InvalidSupabaseAuthConfig("broken"),
        ):
            response = self.client.get("/comenzar")
        self.assertEqual(response.status_code, 503)

    def test_comenzar_post_returns_bounded_503(self) -> None:
        with patch(
            "backend.routers.public_onboarding.resolve_supabase_auth_settings",
            side_effect=InvalidSupabaseAuthConfig("broken"),
        ):
            response = self.client.post(
                "/comenzar",
                data={"email": "owner@example.com"},
            )
        self.assertEqual(response.status_code, 503)

    def test_callback_returns_bounded_503(self) -> None:
        with patch(
            "backend.routers.public_onboarding.resolve_supabase_auth_settings",
            side_effect=InvalidSupabaseAuthConfig("broken"),
        ):
            response = self.client.get(
                "/auth/callback", params={"code": "code-1"}
            )
        self.assertEqual(response.status_code, 503)

    def test_verified_returns_bounded_503(self) -> None:
        with patch(
            "backend.routers.public_onboarding.resolve_supabase_auth_settings",
            side_effect=InvalidSupabaseAuthConfig("broken"),
        ):
            response = self.client.get("/auth/verificado")
        self.assertEqual(response.status_code, 503)

    def test_dependency_503_returns_503(self) -> None:
        from backend.dependencies import (
            require_authenticated_owner_principal,
        )

        with patch(
            "backend.dependencies.resolve_supabase_auth_settings",
            side_effect=InvalidSupabaseAuthConfig("broken"),
        ):
            with self.assertRaises(Exception) as ctx:
                require_authenticated_owner_principal(
                    request=MagicMock(headers={})
                )
        self.assertEqual(ctx.exception.status_code, 503)


class PersistenceIsolationTest(unittest.TestCase):
    """Phase 2 never opens the database session or any repository."""

    def test_routes_do_not_open_session(self) -> None:
        session = MagicMock(name="DatabaseSession")
        override = _SessionOverride(session)
        from backend.main import app as production_app

        production_app.dependency_overrides[get_session] = override
        try:
            public_client = TestClient(
                production_app,
                raise_server_exceptions=False,
                follow_redirects=False,
            )
            for path in ("/", "/comenzar", "/health"):
                with self.subTest(path=path):
                    public_client.get(path)
        finally:
            production_app.dependency_overrides.pop(get_session, None)
        override.assert_not_called()


class ExistingSurfacePreservationTest(unittest.TestCase):
    """Phase 2 keeps the documented boundaries untouched."""

    def setUp(self) -> None:
        from backend.main import app as production_app

        self.app = production_app
        self.session = _new_session_double()
        self.override = _install_session_override(
            self, self.app, self.session
        )
        self.client = TestClient(
            self.app, raise_server_exceptions=False, follow_redirects=False
        )

    def test_admin_route_still_requires_credentials(self) -> None:
        response = self.client.get("/admin")
        self.assertIn(response.status_code, (401, 503))

    def test_health_endpoint_is_unchanged(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_twilio_webhook_rejects_unsigned_post(self) -> None:
        response = self.client.post(
            "/webhooks/twilio/whatsapp/inbound", data={}
        )
        self.assertEqual(response.status_code, 403)

    def test_landing_is_unchanged(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Recibí y administrá", response.text)


class _StubUrlopenResponse:
    """Minimal stub that mimics ``urllib.request.urlopen``'s context API."""

    def __init__(self, body: bytes, status_code: int) -> None:
        self._body = body
        self._status_code = status_code

    def __enter__(self) -> object:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> bool:
        return False

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self._status_code


class SupabaseWireProtocolTest(unittest.TestCase):
    """Verifies the exact outbound HTTP contract against Supabase.

    The tests intercept :func:`urllib.request.urlopen` so the
    assertions inspect the real URL, query, headers and JSON body
    the application emits against the documented Supabase
    ``/auth/v1/otp`` and ``/auth/v1/token`` endpoints. The test
    double returns an immediate stub response so no network
    traffic is generated.
    """

    def _install_urlopen_stub(
        self, body: bytes, status_code: int = 200
    ) -> dict[str, Any]:
        """Patch ``urlopen`` inside the supabase client and return
        a dict that the caller can inspect to assert the outbound
        contract.
        """
        captured: dict[str, Any] = {}

        def fake_urlopen(request: Any, timeout: Any = None) -> Any:
            captured["full_url"] = request.full_url
            captured["method"] = request.get_method()
            header_items: list[tuple[str, str]] = list(request.header_items())
            captured["headers"] = {
                key: value for key, value in header_items
            }
            captured["data"] = request.data
            captured["timeout"] = timeout
            return _StubUrlopenResponse(body, status_code)

        patcher = patch(
            "backend.auth.supabase_client.url_request.urlopen", fake_urlopen
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return captured

    def test_otp_url_uses_url_encoded_redirect_to_query(self) -> None:
        settings = _enabled_settings()
        captured = self._install_urlopen_stub(b"{}")
        pair = generate_pkce_pair()
        request_magic_link_otp(
            email="owner@example.com",
            challenge=pair.challenge,
            settings=settings,
        )
        full_url = captured["full_url"]
        parsed_url = urlparse(full_url)
        self.assertEqual(parsed_url.scheme, "https")
        self.assertEqual(parsed_url.netloc, "abc.supabase.co")
        self.assertEqual(parsed_url.path, "/auth/v1/otp")
        query = parse_qs(parsed_url.query)
        self.assertIn("redirect_to", query)
        self.assertEqual(
            query["redirect_to"][0], settings.callback_url
        )
        encoded_query = raw_query(full_url)
        self.assertIn(
            "redirect_to=", encoded_query
        )
        encoded_value = encoded_query.split("redirect_to=", 1)[1].split(
            "&", 1
        )[0]
        self.assertNotEqual(encoded_value, settings.callback_url)
        self.assertIn("%3A", encoded_value)
        self.assertIn("%2F", encoded_value)

    def test_otp_body_uses_root_level_fields_with_lowercase_s256(
        self,
    ) -> None:
        settings = _enabled_settings()
        captured = self._install_urlopen_stub(b"{}")
        pair = generate_pkce_pair()
        request_magic_link_otp(
            email="Owner@Example.COM",
            challenge=pair.challenge,
            settings=settings,
        )
        body = json.loads(captured["data"].decode("utf-8"))
        self.assertEqual(body["email"], "owner@example.com")
        self.assertFalse(body["create_user"])
        self.assertEqual(body["code_challenge"], pair.challenge)
        self.assertEqual(body["code_challenge_method"], "s256")
        self.assertNotIn("options", body)
        self.assertNotIn("email_redirect_to", body)
        self.assertNotIn("redirect_to", body)

    def test_otp_headers_carry_publishable_key_and_bearer(self) -> None:
        settings = _enabled_settings()
        captured = self._install_urlopen_stub(b"{}")
        pair = generate_pkce_pair()
        request_magic_link_otp(
            email="owner@example.com",
            challenge=pair.challenge,
            settings=settings,
        )
        headers = _lowercase_headers(captured["headers"])
        self.assertEqual(headers["apikey"], settings.publishable_key)
        self.assertEqual(
            headers["authorization"],
            f"Bearer {settings.publishable_key}",
        )
        self.assertEqual(headers["content-type"], "application/json")

    def test_token_exchange_uses_auth_code_not_code(self) -> None:
        settings = _enabled_settings()
        token_body = (
            b'{"access_token":"stub-token","token_type":"bearer",'
            b'"expires_in":3600}'
        )
        captured = self._install_urlopen_stub(token_body)
        access_token = exchange_magic_link_code(
            code="magic-code-abc",
            code_verifier="verifier-xyz",
            settings=settings,
        )
        self.assertEqual(access_token, "stub-token")
        parsed_url = urlparse(captured["full_url"])
        self.assertEqual(parsed_url.scheme, "https")
        self.assertEqual(parsed_url.netloc, "abc.supabase.co")
        self.assertEqual(parsed_url.path, "/auth/v1/token")
        query = parse_qs(parsed_url.query)
        self.assertEqual(query["grant_type"][0], "pkce")
        body = json.loads(captured["data"].decode("utf-8"))
        self.assertEqual(body["auth_code"], "magic-code-abc")
        self.assertNotIn("code", body)
        self.assertEqual(body["code_verifier"], "verifier-xyz")
        self.assertNotIn("grant_type", body)

    def test_token_exchange_headers_carry_publishable_key(self) -> None:
        settings = _enabled_settings()
        token_body = (
            b'{"access_token":"stub-token","token_type":"bearer",'
            b'"expires_in":3600}'
        )
        captured = self._install_urlopen_stub(token_body)
        exchange_magic_link_code(
            code="magic-code-abc",
            code_verifier="verifier-xyz",
            settings=settings,
        )
        headers = _lowercase_headers(captured["headers"])
        self.assertEqual(headers["apikey"], settings.publishable_key)
        self.assertEqual(
            headers["authorization"],
            f"Bearer {settings.publishable_key}",
        )
        self.assertEqual(headers["content-type"], "application/json")


class CookieSecurityTest(unittest.TestCase):
    """``POST /comenzar`` must fail closed over plain HTTP.

    The route must not emit the ``novaorders_owner_pkce`` cookie,
    must not call the abuse guard and must not call the Supabase
    provider when the inbound request is not served over HTTPS.
    The bounded ``503`` view is the only response.
    """

    def setUp(self) -> None:
        self.session_double = _new_session_double()
        self.app = _build_public_onboarding_app()
        self.override = _install_session_override(
            self, self.app, self.session_double
        )
        self.client = TestClient(
            self.app, raise_server_exceptions=False, follow_redirects=False
        )

    def test_post_over_plain_http_does_not_emit_pkce_cookie(self) -> None:
        _with_settings(self)
        with patch(
            "backend.routers.public_onboarding.request_magic_link_otp"
        ) as issue, patch(
            "backend.routers.public_onboarding.request_magic_link_authorization",
        ) as guard:
            response = self.client.post(
                "/comenzar",
                data={"email": "owner@example.com"},
            )
        self.assertEqual(response.status_code, 503)
        cookies = response.headers.get_list("set-cookie")
        for c in cookies:
            self.assertNotIn(PKCE_COOKIE_NAME, c)
        issue.assert_not_called()
        guard.assert_not_called()
        self.override.assert_not_called()
        self.assertNotIn("owner@example.com", response.text)
        self.assertIn("No pudimos", response.text)

    def test_post_with_http_forwarded_proto_does_not_emit_pkce_cookie(
        self,
    ) -> None:
        _with_settings(self)
        with patch(
            "backend.routers.public_onboarding.request_magic_link_otp"
        ) as issue, patch(
            "backend.routers.public_onboarding.request_magic_link_authorization",
        ) as guard:
            response = self.client.post(
                "/comenzar",
                data={"email": "owner@example.com"},
                headers={"x-forwarded-proto": "http"},
            )
        self.assertEqual(response.status_code, 503)
        cookies = response.headers.get_list("set-cookie")
        for c in cookies:
            self.assertNotIn(PKCE_COOKIE_NAME, c)
        issue.assert_not_called()
        guard.assert_not_called()
        self.override.assert_not_called()

    def test_post_over_https_still_emits_pkce_cookie(self) -> None:
        _with_settings(self)
        with patch(
            "backend.routers.public_onboarding.request_magic_link_authorization",
            return_value=MagicMock(allowed=True, decision_id="d-1"),
        ), patch(
            "backend.routers.public_onboarding.request_magic_link_otp"
        ):
            response = self.client.post(
                "/comenzar",
                data={"email": "owner@example.com"},
                headers={"x-forwarded-proto": "https"},
            )
        self.assertEqual(response.status_code, 200)
        cookies = response.headers.get_list("set-cookie")
        pkce_cookie = next(
            (c for c in cookies if c.startswith(f"{PKCE_COOKIE_NAME}=")),
            None,
        )
        self.assertIsNotNone(pkce_cookie)
        self.assertIn("Secure", pkce_cookie)


def _lowercase_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return ``headers`` keyed by lowercase names."""
    return {key.lower(): value for key, value in headers.items()}


def raw_query(full_url: str) -> str:
    """Return the raw query string for ``full_url`` (no URL decoding)."""
    return full_url.split("?", 1)[1] if "?" in full_url else ""


def _new_session_double() -> MagicMock:
    """Return a MagicMock double for the database session dependency.

    The Phase 2 router is a pure rendering + validation adapter so
    the mock is only used to assert the session is never opened.
    """
    return MagicMock(name="DatabaseSession")


if __name__ == "__main__":
    unittest.main()