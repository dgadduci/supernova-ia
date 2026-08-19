import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlparse

from dotenv import load_dotenv

from backend.services.exceptions import (
    InvalidHybridAuthoritativePolicyPath,
    InvalidProviderProcessingWorkerConfig,
    InvalidShadowHybridMinScoreGap,
    InvalidShadowVectorTopK,
    InvalidSupabaseAuthConfig,
    InvalidTwilioOutboundDispatchConfig,
    InvalidTwilioWebhookAuthToken,
    InvalidTwilioWebhookBaseUrl,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)


def _str_env(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer (got {raw!r})") from exc


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    truthy = {"1", "true", "yes", "on"}
    falsy = {"0", "false", "no", "off"}
    lowered = raw.lower()
    if lowered in truthy:
        return True
    if lowered in falsy:
        return False
    raise ValueError(f"{name} must be a boolean (got {raw!r})")


def _positive_int_env(name: str, default: int) -> int:
    value = _int_env(name, default)
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero (got {value})")
    return value


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a float (got {raw!r})") from exc


_RECOGNIZER_MODES = ("fuzzy", "shadow", "hybrid_authoritative")


def _product_recognizer_mode_env(name: str, default: str) -> tuple[str, str]:
    """Resolve ``PRODUCT_RECOGNIZER_MODE``.

    Returns a ``(configured_mode, effective_mode)`` tuple. The
    configured mode is the raw operator-supplied env value (or the
    default when the env var is unset). The effective mode is the
    value the runtime actually applies (the configured literal when
    valid, ``"fuzzy"`` when the configured literal falls outside the
    documented set — with a single sanitized structured warning
    carrying the configured literal, the effective mode, and the
    sanitized reason category ``"invalid_mode"``).
    """
    raw = os.environ.get(name)
    configured = raw if raw is not None else default
    if configured in _RECOGNIZER_MODES:
        return configured, configured
    fallback = "fuzzy"
    logger.warning(
        "product_recognizer_mode_invalid",
        extra={
            "configured_mode": configured,
            "effective_mode": fallback,
            "reason": "invalid_mode",
        },
    )
    return configured, fallback


def _shadow_vector_top_k_env(name: str, default: int) -> int:
    value = _int_env(name, default)
    if value <= 0:
        raise InvalidShadowVectorTopK(
            f"{name} must be greater than zero (got {value})"
        )
    return value


def _shadow_hybrid_min_score_gap_env(name: str, default: float) -> float:
    value = _float_env(name, default)
    if math.isnan(value) or value < 0.0 or value > 1.0:
        raise InvalidShadowHybridMinScoreGap(
            f"{name} must be a float in [0.0, 1.0] (got {value!r})"
        )
    return value


def _hybrid_authoritative_policy_path_env(
    name: str, default: str | None, effective_mode: str
) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        raw = default
    if effective_mode != "hybrid_authoritative":
        return raw
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise InvalidHybridAuthoritativePolicyPath(
            f"{name} must be a non-empty string or None "
            f"when product_recognizer_mode == 'hybrid_authoritative' "
            f"(got {raw!r})"
        )
    if raw == "":
        raise InvalidHybridAuthoritativePolicyPath(
            f"{name} must be a non-empty string or None "
            f"when product_recognizer_mode == 'hybrid_authoritative' "
            f"(got {raw!r})"
        )
    return raw


def _optional_str_env(name: str, default: str | None) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return default
    if not isinstance(raw, str):
        raise InvalidTwilioWebhookAuthToken(
            f"{name} must be a string when provided (got {type(raw).__name__})"
        )
    return raw


def _ollama_proxy_url_env(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        raise ValueError(
            f"{name} must be a non-empty absolute socks5 or socks5h URL when provided"
        )
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() not in {"socks5", "socks5h"} or not parsed.netloc:
        raise ValueError(
            f"{name} must be an absolute socks5 or socks5h URL when provided"
        )
    if (
        parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            f"{name} must not contain credentials, path, query, or fragment"
        )
    return cleaned


def _twilio_auth_token_env(name: str) -> str | None:
    raw = _optional_str_env(name, None)
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        raise InvalidTwilioWebhookAuthToken(
            f"{name} must be a non-empty stripped string when provided "
            f"(got {raw!r})"
        )
    return cleaned


def _twilio_account_sid_env(name: str) -> str | None:
    raw = _optional_str_env(name, None)
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        raise InvalidTwilioWebhookAuthToken(
            f"{name} must be a non-empty stripped string when provided "
            f"(got {raw!r})"
        )
    if not cleaned.startswith("AC") or len(cleaned) != 34:
        raise InvalidTwilioWebhookAuthToken(
            f"{name} must be a canonical Twilio account SID starting "
            f"with 'AC' and 34 characters total (got {cleaned!r})"
        )
    tail = cleaned[2:]
    if not all(ch in "0123456789abcdefABCDEF" for ch in tail):
        raise InvalidTwilioWebhookAuthToken(
            f"{name} must be a canonical Twilio account SID whose 32 "
            f"characters after 'AC' are hexadecimal (got {cleaned!r})"
        )
    return cleaned


def _order_management_admin_token_env(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise TypeError(
            f"{name} must be a string when provided "
            f"(got {type(raw).__name__})"
        )
    cleaned = raw.strip()
    if not cleaned:
        return None
    return cleaned


def _admin_panel_csrf_secret_env(name: str) -> str | None:
    """Resolve the optional panel CSRF signing secret.

    The secret is optional: when missing or blank the panel reuses
    the configured administrative token so the boundary works without
    a new deployment setting. A non-blank value is the only way to
    decouple the panel CSRF secret from the credential.
    """
    raw = os.environ.get(name)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise TypeError(
            f"{name} must be a string when provided "
            f"(got {type(raw).__name__})"
        )
    cleaned = raw.strip()
    if not cleaned:
        return None
    return cleaned


def _admin_panel_allowed_origin_env(name: str) -> str | None:
    """Resolve the optional panel allowed-origin pin.

    When the value is missing or blank the dependency falls back to
    the ``scheme://host[:port]`` the server sees for the request —
    the same-origin check stays active by default. A non-blank value
    pins the dependency to an exact origin string so reverse-proxy
    deployments that rewrite ``Host`` / ``X-Forwarded-*`` can still
    validate the request origin against a trusted value. The helper
    performs no URL parsing because the dependency compares the
    raw string verbatim — exact-string match prevents trivial
    subdomain or trailing-slash bypasses.
    """
    raw = os.environ.get(name)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise TypeError(
            f"{name} must be a string when provided "
            f"(got {type(raw).__name__})"
        )
    cleaned = raw.strip()
    if not cleaned:
        return None
    return cleaned


def _https_absolute_url_env(
    name: str, error_cls: type[Exception]
) -> str | None:
    """Resolve an absolute ``https://`` URL without query or fragment.

    The helper centralises the contract used by the Phase 2 Supabase
    configuration: missing / blank values stay ``None`` so the
    feature remains off by default, while a non-empty value must be
    a canonical ``https://`` URL. The helper rejects URLs that carry
    query strings or fragments because the configured callback and
    JWKS URLs are pinned values — anything appended to them would
    be a configuration drift that the runtime cannot safely accept.
    """
    raw = _optional_str_env(name, None)
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() != "https":
        raise error_cls(
            f"{name} must use the https scheme (got {cleaned!r})"
        )
    if not parsed.netloc:
        raise error_cls(
            f"{name} must be an absolute https URL (got {cleaned!r})"
        )
    if parsed.query or parsed.fragment:
        raise error_cls(
            f"{name} must not contain a query string or fragment "
            f"(got {cleaned!r})"
        )
    return cleaned


def _supabase_publishable_key_env(name: str) -> str | None:
    """Resolve the optional Supabase publishable / anon key.

    The helper enforces the publishable-only contract: any key that
    looks like a service-role key, an admin token, or a JWT is
    rejected at process start. The Phase 2 link-request path uses
    the publishable key only to call Supabase Auth; it must never
    carry enough privilege to mint arbitrary sessions.
    """
    raw = _optional_str_env(name, None)
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    lowered = cleaned.lower()
    forbidden_markers = (
        "service_role",
        "service-role",
        "service role",
        "sb_secret",
        "sbp_",
    )
    for marker in forbidden_markers:
        if marker in lowered:
            raise InvalidSupabaseAuthConfig(
                f"{name} must not contain a service-role key "
                f"(got a redacted marker)"
            )
    if not cleaned.startswith("eyJ"):
        raise InvalidSupabaseAuthConfig(
            f"{name} must be a publishable JWT-shaped key "
            f"starting with 'eyJ'"
        )
    return cleaned


def _twilio_webhook_base_url_env(name: str) -> str | None:
    raw = _optional_str_env(name, None)
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        raise InvalidTwilioWebhookBaseUrl(
            f"{name} must be a non-empty stripped string when provided "
            f"(got {raw!r})"
        )
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() != "https":
        raise InvalidTwilioWebhookBaseUrl(
            f"{name} must use the https scheme (got {cleaned!r})"
        )
    if not parsed.netloc:
        raise InvalidTwilioWebhookBaseUrl(
            f"{name} must be an absolute https URL (got {cleaned!r})"
        )
    if parsed.query or parsed.fragment:
        raise InvalidTwilioWebhookBaseUrl(
            f"{name} must not contain a query string or fragment "
            f"(got {cleaned!r})"
        )
    return cleaned


def _twilio_outbound_sender_e164_env(name: str) -> str | None:
    raw = _optional_str_env(name, None)
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        raise InvalidTwilioOutboundDispatchConfig(
            f"{name} must be a non-empty stripped string when provided "
            f"(got {raw!r})"
        )
    if not cleaned.startswith("+"):
        raise InvalidTwilioOutboundDispatchConfig(
            f"{name} must be a canonical E.164 number starting with '+' "
            f"(got {cleaned!r})"
        )
    digits = cleaned[1:]
    if not digits.isdigit() or not digits:
        raise InvalidTwilioOutboundDispatchConfig(
            f"{name} must be a canonical E.164 number with digits only "
            f"after '+' (got {cleaned!r})"
        )
    return cleaned


def _twilio_callback_status_url_env(name: str) -> str | None:
    raw = _optional_str_env(name, None)
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        raise InvalidTwilioOutboundDispatchConfig(
            f"{name} must be a non-empty stripped string when provided "
            f"(got {raw!r})"
        )
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() != "https":
        raise InvalidTwilioOutboundDispatchConfig(
            f"{name} must use the https scheme (got {cleaned!r})"
        )
    if not parsed.netloc:
        raise InvalidTwilioOutboundDispatchConfig(
            f"{name} must be an absolute https URL (got {cleaned!r})"
        )
    if parsed.fragment:
        raise InvalidTwilioOutboundDispatchConfig(
            f"{name} must not contain a fragment (got {cleaned!r})"
        )
    return cleaned


def _positive_int_env_strict(name: str, default: int) -> int:
    value = _int_env(name, default)
    if value <= 0:
        raise InvalidTwilioOutboundDispatchConfig(
            f"{name} must be greater than zero (got {value})"
        )
    return value


def _non_negative_int_env(name: str, default: int) -> int:
    value = _int_env(name, default)
    if value < 0:
        raise InvalidTwilioOutboundDispatchConfig(
            f"{name} must be non-negative (got {value})"
        )
    return value


DEFAULT_EMBEDDING_MODEL = "all-minilm:latest"
DEFAULT_EMBEDDING_DIMENSION = 384
DEFAULT_EMBEDDING_URL = "http://localhost:11434/api/embed"
DEFAULT_EMBEDDING_TIMEOUT_SECONDS = 30
DEFAULT_EMBEDDING_BATCH_SIZE = 32
DEFAULT_PRODUCT_RECOGNIZER_MODE: Literal["fuzzy", "shadow", "hybrid_authoritative"] = "fuzzy"
DEFAULT_SHADOW_VECTOR_TOP_K = 5
DEFAULT_SHADOW_HYBRID_MIN_SCORE_GAP = 0.05
DEFAULT_HYBRID_AUTHORITATIVE_POLICY_PATH: str | None = None
DEFAULT_TWILIO_OUTBOUND_SENDER_E164: str | None = None
DEFAULT_TWILIO_CALLBACK_STATUS_URL: str | None = None
DEFAULT_TWILIO_OUTBOUND_LEASE_SECONDS = 30
DEFAULT_TWILIO_OUTBOUND_INITIAL_BACKOFF_SECONDS = 30
DEFAULT_TWILIO_OUTBOUND_MAX_BACKOFF_SECONDS = 300
DEFAULT_TWILIO_OUTBOUND_MAX_ATTEMPTS = 5
DEFAULT_PROVIDER_PROCESSING_WORKER_ENABLED = False
DEFAULT_PROVIDER_PROCESSING_WORKER_POLL_INTERVAL_SECONDS = 5
DEFAULT_PROVIDER_PROCESSING_WORKER_INBOUND_MAX_ITEMS_PER_PASS = 1
DEFAULT_PROVIDER_PROCESSING_WORKER_OUTBOUND_MAX_ATTEMPTS_PER_PASS = 16
DEFAULT_SUPABASE_AUTH_ENABLED = False
DEFAULT_SUPABASE_PROJECT_URL: str | None = None
DEFAULT_SUPABASE_JWT_ISSUER: str | None = None
DEFAULT_SUPABASE_JWT_AUDIENCE = "authenticated"
DEFAULT_SUPABASE_CALLBACK_URL: str | None = None
DEFAULT_SUPABASE_JWKS_URL: str | None = None
DEFAULT_SUPABASE_PUBLISHABLE_KEY: str | None = None
DEFAULT_SUPABASE_SESSION_SECRET: str | None = None
DEFAULT_SUPABASE_PKCE_COOKIE_MAX_AGE_SECONDS = 60 * 5
DEFAULT_SUPABASE_SESSION_MAX_AGE_SECONDS = 60 * 30
DEFAULT_SUPABASE_ALLOWED_ALGORITHMS = ("ES256", "RS256", "PS256", "EdDSA")
DEFAULT_SUPABASE_ABUSE_GUARD_URL: str | None = None
DEFAULT_SUPABASE_ABUSE_GUARD_TOKEN: str | None = None
DEFAULT_SUPABASE_REQUEST_TIMEOUT_SECONDS = 10
DEFAULT_COMMERCE_ISOLATED_OUTBOUND_ENABLED = False
DEFAULT_COMMERCE_ISOLATED_TC_BASE_URL: str | None = None
DEFAULT_COMMERCE_ISOLATED_HTTP_TIMEOUT_SECONDS = 5


def _provider_processing_worker_positive_int_env(
    name: str, default: int
) -> int:
    value = _int_env(name, default)
    if value <= 0:
        raise InvalidProviderProcessingWorkerConfig(
            f"{name} must be greater than zero (got {value})"
        )
    return value


def _supabase_session_max_age_env(name: str, default: int) -> int:
    """Resolve the bounded local-session max-age in seconds.

    Phase 2 uses a short-lived local session that expires well
    before the provider JWT so a revoked Supabase session cannot
    outlive its underlying token. The bound is positive to keep the
    cookie header consistent across the router.
    """
    value = _int_env(name, default)
    if value <= 0:
        raise InvalidSupabaseAuthConfig(
            f"{name} must be greater than zero (got {value})"
        )
    return value


def _supabase_session_secret_env(name: str) -> str | None:
    """Resolve the optional local-session signing secret.

    The secret signs the short-lived local session cookie. It must
    be a non-empty stripped string when Supabase auth is enabled;
    an unset value keeps the feature off. Service-role markers and
    JWT-shaped strings are rejected to keep the secret distinct
    from any provider-issued credential.
    """
    raw = _optional_str_env(name, None)
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if (
        "service_role" in lowered
        or "service-role" in lowered
        or cleaned.startswith("eyJ")
    ):
        raise InvalidSupabaseAuthConfig(
            f"{name} must not be a JWT-shaped or service-role value"
        )
    return cleaned


def _supabase_abuse_guard_token_env(name: str) -> str | None:
    """Resolve the optional edge/hosting abuse-guard token.

    The token is the operator-pinned shared secret the edge/hosting
    layer uses to authenticate its rate-limit gate. It is not a
    Supabase credential and must remain a non-empty stripped string.
    When the operator enables the feature without configuring the
    guard the application refuses to issue or resend a magic link.
    """
    raw = _optional_str_env(name, None)
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    return cleaned


def _supabase_request_timeout_env(name: str, default: int) -> int:
    value = _int_env(name, default)
    if value <= 0:
        raise InvalidSupabaseAuthConfig(
            f"{name} must be greater than zero (got {value})"
        )
    return value


def _supabase_pkce_cookie_max_age_env(name: str, default: int) -> int:
    """Resolve the bounded PKCE temp-cookie max-age in seconds.

    The PKCE temp cookie carries the server-issued ``code_verifier``
    between the link-request and the callback. It is intentionally
    short-lived so a replay cannot outlive the email link it pairs
    with; the bound must remain positive so the cookie header is
    always emitted with a finite lifetime.
    """
    value = _int_env(name, default)
    if value <= 0:
        raise InvalidSupabaseAuthConfig(
            f"{name} must be greater than zero (got {value})"
        )
    return value


@dataclass(frozen=True)
class Settings:
    llm_url: str
    llm_model: str
    llm_timeout: int
    llm_keep_alive: str
    llm_num_ctx: int
    llm_num_predict: int
    llm_log_content: bool
    llm_log_max_chars: int
    ollama_proxy_url: str | None = None
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION
    embedding_url: str = DEFAULT_EMBEDDING_URL
    embedding_timeout_seconds: int = DEFAULT_EMBEDDING_TIMEOUT_SECONDS
    embedding_batch_size: int = DEFAULT_EMBEDDING_BATCH_SIZE
    enable_local_admin_endpoints: bool = False
    product_recognizer_configured_mode: str = DEFAULT_PRODUCT_RECOGNIZER_MODE
    product_recognizer_mode: Literal["fuzzy", "shadow", "hybrid_authoritative"] = (
        DEFAULT_PRODUCT_RECOGNIZER_MODE
    )
    shadow_vector_top_k: int = DEFAULT_SHADOW_VECTOR_TOP_K
    shadow_hybrid_min_score_gap: float = DEFAULT_SHADOW_HYBRID_MIN_SCORE_GAP
    hybrid_authoritative_policy_path: str | None = DEFAULT_HYBRID_AUTHORITATIVE_POLICY_PATH
    twilio_auth_token: str | None = None
    twilio_account_sid: str | None = None
    twilio_webhook_base_url: str | None = None
    twilio_outbound_sender_e164: str | None = (
        DEFAULT_TWILIO_OUTBOUND_SENDER_E164
    )
    twilio_callback_status_url: str | None = (
        DEFAULT_TWILIO_CALLBACK_STATUS_URL
    )
    twilio_outbound_lease_seconds: int = (
        DEFAULT_TWILIO_OUTBOUND_LEASE_SECONDS
    )
    twilio_outbound_initial_backoff_seconds: int = (
        DEFAULT_TWILIO_OUTBOUND_INITIAL_BACKOFF_SECONDS
    )
    twilio_outbound_max_backoff_seconds: int = (
        DEFAULT_TWILIO_OUTBOUND_MAX_BACKOFF_SECONDS
    )
    twilio_outbound_max_attempts: int = (
        DEFAULT_TWILIO_OUTBOUND_MAX_ATTEMPTS
    )
    provider_processing_worker_enabled: bool = (
        DEFAULT_PROVIDER_PROCESSING_WORKER_ENABLED
    )
    provider_processing_worker_poll_interval_seconds: int = (
        DEFAULT_PROVIDER_PROCESSING_WORKER_POLL_INTERVAL_SECONDS
    )
    provider_processing_worker_inbound_max_items_per_pass: int = (
        DEFAULT_PROVIDER_PROCESSING_WORKER_INBOUND_MAX_ITEMS_PER_PASS
    )
    provider_processing_worker_outbound_max_attempts_per_pass: int = (
        DEFAULT_PROVIDER_PROCESSING_WORKER_OUTBOUND_MAX_ATTEMPTS_PER_PASS
    )
    order_management_admin_token: str | None = None
    admin_panel_csrf_secret: str | None = None
    admin_panel_allowed_origin: str | None = None
    owner_onboarding_csrf_secret: str | None = None
    owner_onboarding_allowed_origin: str | None = None
    supabase_auth_enabled: bool = DEFAULT_SUPABASE_AUTH_ENABLED
    supabase_project_url: str | None = DEFAULT_SUPABASE_PROJECT_URL
    supabase_jwt_issuer: str | None = DEFAULT_SUPABASE_JWT_ISSUER
    supabase_jwt_audience: str = DEFAULT_SUPABASE_JWT_AUDIENCE
    supabase_callback_url: str | None = DEFAULT_SUPABASE_CALLBACK_URL
    supabase_jwks_url: str | None = DEFAULT_SUPABASE_JWKS_URL
    supabase_publishable_key: str | None = DEFAULT_SUPABASE_PUBLISHABLE_KEY
    supabase_session_secret: str | None = DEFAULT_SUPABASE_SESSION_SECRET
    supabase_pkce_cookie_max_age_seconds: int = (
        DEFAULT_SUPABASE_PKCE_COOKIE_MAX_AGE_SECONDS
    )
    supabase_session_max_age_seconds: int = (
        DEFAULT_SUPABASE_SESSION_MAX_AGE_SECONDS
    )
    supabase_allowed_algorithms: tuple[str, ...] = (
        DEFAULT_SUPABASE_ALLOWED_ALGORITHMS
    )
    supabase_abuse_guard_url: str | None = DEFAULT_SUPABASE_ABUSE_GUARD_URL
    supabase_abuse_guard_token: str | None = DEFAULT_SUPABASE_ABUSE_GUARD_TOKEN
    supabase_request_timeout_seconds: int = (
        DEFAULT_SUPABASE_REQUEST_TIMEOUT_SECONDS
    )
    commerce_isolated_outbound_enabled: bool = (
        DEFAULT_COMMERCE_ISOLATED_OUTBOUND_ENABLED
    )
    commerce_isolated_tc_base_url_legacy: str | None = (
        DEFAULT_COMMERCE_ISOLATED_TC_BASE_URL
    )
    commerce_isolated_http_timeout_seconds: int = (
        DEFAULT_COMMERCE_ISOLATED_HTTP_TIMEOUT_SECONDS
    )


def load_settings() -> Settings:
    configured_mode, effective_mode = _product_recognizer_mode_env(
        "PRODUCT_RECOGNIZER_MODE",
        DEFAULT_PRODUCT_RECOGNIZER_MODE,
    )
    return Settings(
        llm_url=_str_env("LLM_URL", "http://localhost:11434/api/generate"),
        llm_model=_str_env("LLM_MODEL", "qwen2.5-coder:7b-ctx8192"),
        llm_timeout=_int_env("LLM_TIMEOUT", 180),
        llm_keep_alive=_str_env("LLM_KEEP_ALIVE", "2h"),
        llm_num_ctx=_int_env("LLM_NUM_CTX", 8192),
        llm_num_predict=_int_env("LLM_NUM_PREDICT", 1500),
        llm_log_content=_bool_env("LLM_LOG_CONTENT", False),
        llm_log_max_chars=_int_env("LLM_LOG_MAX_CHARS", 1000),
        ollama_proxy_url=_ollama_proxy_url_env("OLLAMA_PROXY_URL"),
        embedding_model=_str_env("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        embedding_dimension=_positive_int_env(
            "EMBEDDING_DIMENSION",
            DEFAULT_EMBEDDING_DIMENSION,
        ),
        embedding_url=_str_env("EMBEDDING_URL", DEFAULT_EMBEDDING_URL),
        embedding_timeout_seconds=_positive_int_env(
            "EMBEDDING_TIMEOUT_SECONDS",
            DEFAULT_EMBEDDING_TIMEOUT_SECONDS,
        ),
        embedding_batch_size=_positive_int_env(
            "EMBEDDING_BATCH_SIZE",
            DEFAULT_EMBEDDING_BATCH_SIZE,
        ),
        enable_local_admin_endpoints=_bool_env(
            "ENABLE_LOCAL_ADMIN_ENDPOINTS", False
        ),
        product_recognizer_configured_mode=configured_mode,
        product_recognizer_mode=cast(
            Literal["fuzzy", "shadow", "hybrid_authoritative"],
            effective_mode,
        ),
        shadow_vector_top_k=_shadow_vector_top_k_env(
            "SHADOW_VECTOR_TOP_K",
            DEFAULT_SHADOW_VECTOR_TOP_K,
        ),
        shadow_hybrid_min_score_gap=_shadow_hybrid_min_score_gap_env(
            "SHADOW_HYBRID_MIN_SCORE_GAP",
            DEFAULT_SHADOW_HYBRID_MIN_SCORE_GAP,
        ),
        hybrid_authoritative_policy_path=_hybrid_authoritative_policy_path_env(
            "HYBRID_AUTHORITATIVE_POLICY_PATH",
            DEFAULT_HYBRID_AUTHORITATIVE_POLICY_PATH,
            effective_mode,
        ),
        twilio_auth_token=_twilio_auth_token_env("TWILIO_AUTH_TOKEN"),
        twilio_account_sid=_twilio_account_sid_env("TWILIO_ACCOUNT_SID"),
        twilio_webhook_base_url=_twilio_webhook_base_url_env(
            "TWILIO_WEBHOOK_BASE_URL"
        ),
        twilio_outbound_sender_e164=_twilio_outbound_sender_e164_env(
            "TWILIO_OUTBOUND_SENDER_E164"
        ),
        twilio_callback_status_url=_twilio_callback_status_url_env(
            "TWILIO_CALLBACK_STATUS_URL"
        ),
        twilio_outbound_lease_seconds=_positive_int_env_strict(
            "TWILIO_OUTBOUND_LEASE_SECONDS",
            DEFAULT_TWILIO_OUTBOUND_LEASE_SECONDS,
        ),
        twilio_outbound_initial_backoff_seconds=_positive_int_env_strict(
            "TWILIO_OUTBOUND_INITIAL_BACKOFF_SECONDS",
            DEFAULT_TWILIO_OUTBOUND_INITIAL_BACKOFF_SECONDS,
        ),
        twilio_outbound_max_backoff_seconds=_positive_int_env_strict(
            "TWILIO_OUTBOUND_MAX_BACKOFF_SECONDS",
            DEFAULT_TWILIO_OUTBOUND_MAX_BACKOFF_SECONDS,
        ),
        twilio_outbound_max_attempts=_positive_int_env_strict(
            "TWILIO_OUTBOUND_MAX_ATTEMPTS",
            DEFAULT_TWILIO_OUTBOUND_MAX_ATTEMPTS,
        ),
        provider_processing_worker_enabled=_bool_env(
            "PROVIDER_PROCESSING_WORKER_ENABLED",
            DEFAULT_PROVIDER_PROCESSING_WORKER_ENABLED,
        ),
        provider_processing_worker_poll_interval_seconds=(
            _provider_processing_worker_positive_int_env(
                "PROVIDER_PROCESSING_WORKER_POLL_INTERVAL_SECONDS",
                DEFAULT_PROVIDER_PROCESSING_WORKER_POLL_INTERVAL_SECONDS,
            )
        ),
        provider_processing_worker_inbound_max_items_per_pass=(
            _provider_processing_worker_positive_int_env(
                "PROVIDER_PROCESSING_WORKER_INBOUND_MAX_ITEMS_PER_PASS",
                DEFAULT_PROVIDER_PROCESSING_WORKER_INBOUND_MAX_ITEMS_PER_PASS,
            )
        ),
        provider_processing_worker_outbound_max_attempts_per_pass=(
            _provider_processing_worker_positive_int_env(
                "PROVIDER_PROCESSING_WORKER_OUTBOUND_MAX_ATTEMPTS_PER_PASS",
                DEFAULT_PROVIDER_PROCESSING_WORKER_OUTBOUND_MAX_ATTEMPTS_PER_PASS,
            )
        ),
        order_management_admin_token=_order_management_admin_token_env(
            "ORDER_MANAGEMENT_ADMIN_TOKEN"
        ),
        admin_panel_csrf_secret=_admin_panel_csrf_secret_env(
            "ADMIN_PANEL_CSRF_SECRET"
        ),
        admin_panel_allowed_origin=_admin_panel_allowed_origin_env(
            "ADMIN_PANEL_ALLOWED_ORIGIN"
        ),
        owner_onboarding_csrf_secret=_admin_panel_csrf_secret_env(
            "OWNER_ONBOARDING_CSRF_SECRET"
        ),
        owner_onboarding_allowed_origin=_admin_panel_allowed_origin_env(
            "OWNER_ONBOARDING_ALLOWED_ORIGIN"
        ),
        supabase_auth_enabled=_bool_env(
            "SUPABASE_AUTH_ENABLED", DEFAULT_SUPABASE_AUTH_ENABLED
        ),
        supabase_project_url=_https_absolute_url_env(
            "SUPABASE_PROJECT_URL", InvalidSupabaseAuthConfig
        ),
        supabase_jwt_issuer=_optional_str_env(
            "SUPABASE_JWT_ISSUER", DEFAULT_SUPABASE_JWT_ISSUER
        ),
        supabase_jwt_audience=_str_env(
            "SUPABASE_JWT_AUDIENCE", DEFAULT_SUPABASE_JWT_AUDIENCE
        ),
        supabase_callback_url=_https_absolute_url_env(
            "SUPABASE_CALLBACK_URL", InvalidSupabaseAuthConfig
        ),
        supabase_jwks_url=_https_absolute_url_env(
            "SUPABASE_JWKS_URL", InvalidSupabaseAuthConfig
        ),
        supabase_publishable_key=_supabase_publishable_key_env(
            "SUPABASE_PUBLISHABLE_KEY"
        ),
        supabase_session_secret=_supabase_session_secret_env(
            "SUPABASE_SESSION_SECRET"
        ),
        supabase_pkce_cookie_max_age_seconds=_supabase_pkce_cookie_max_age_env(
            "SUPABASE_PKCE_COOKIE_MAX_AGE_SECONDS",
            DEFAULT_SUPABASE_PKCE_COOKIE_MAX_AGE_SECONDS,
        ),
        supabase_session_max_age_seconds=_supabase_session_max_age_env(
            "SUPABASE_SESSION_MAX_AGE_SECONDS",
            DEFAULT_SUPABASE_SESSION_MAX_AGE_SECONDS,
        ),
        supabase_allowed_algorithms=DEFAULT_SUPABASE_ALLOWED_ALGORITHMS,
        supabase_abuse_guard_url=_https_absolute_url_env(
            "SUPABASE_ABUSE_GUARD_URL", InvalidSupabaseAuthConfig
        ),
        supabase_abuse_guard_token=_supabase_abuse_guard_token_env(
            "SUPABASE_ABUSE_GUARD_TOKEN"
        ),
        supabase_request_timeout_seconds=_supabase_request_timeout_env(
            "SUPABASE_REQUEST_TIMEOUT_SECONDS",
            DEFAULT_SUPABASE_REQUEST_TIMEOUT_SECONDS,
        ),
        commerce_isolated_outbound_enabled=_bool_env(
            "COMMERCE_ISOLATED_OUTBOUND_ENABLED",
            DEFAULT_COMMERCE_ISOLATED_OUTBOUND_ENABLED,
        ),
        commerce_isolated_tc_base_url_legacy=_optional_str_env(
            "COMMERCE_ISOLATED_TC_BASE_URL",
            DEFAULT_COMMERCE_ISOLATED_TC_BASE_URL,
        ),
        commerce_isolated_http_timeout_seconds=_supabase_request_timeout_env(
            "COMMERCE_ISOLATED_HTTP_TIMEOUT_SECONDS",
            DEFAULT_COMMERCE_ISOLATED_HTTP_TIMEOUT_SECONDS,
        ),
    )


__all__ = [
    "DEFAULT_EMBEDDING_BATCH_SIZE",
    "DEFAULT_EMBEDDING_DIMENSION",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_EMBEDDING_TIMEOUT_SECONDS",
    "DEFAULT_EMBEDDING_URL",
    "DEFAULT_HYBRID_AUTHORITATIVE_POLICY_PATH",
    "DEFAULT_PRODUCT_RECOGNIZER_MODE",
    "DEFAULT_PROVIDER_PROCESSING_WORKER_ENABLED",
    "DEFAULT_PROVIDER_PROCESSING_WORKER_INBOUND_MAX_ITEMS_PER_PASS",
    "DEFAULT_PROVIDER_PROCESSING_WORKER_OUTBOUND_MAX_ATTEMPTS_PER_PASS",
    "DEFAULT_PROVIDER_PROCESSING_WORKER_POLL_INTERVAL_SECONDS",
    "DEFAULT_SHADOW_HYBRID_MIN_SCORE_GAP",
    "DEFAULT_SHADOW_VECTOR_TOP_K",
    "DEFAULT_SUPABASE_ABUSE_GUARD_TOKEN",
    "DEFAULT_SUPABASE_ABUSE_GUARD_URL",
    "DEFAULT_SUPABASE_ALLOWED_ALGORITHMS",
    "DEFAULT_SUPABASE_AUTH_ENABLED",
    "DEFAULT_SUPABASE_CALLBACK_URL",
    "DEFAULT_SUPABASE_JWKS_URL",
    "DEFAULT_SUPABASE_JWT_AUDIENCE",
    "DEFAULT_SUPABASE_JWT_ISSUER",
    "DEFAULT_SUPABASE_PKCE_COOKIE_MAX_AGE_SECONDS",
    "DEFAULT_SUPABASE_PROJECT_URL",
    "DEFAULT_SUPABASE_PUBLISHABLE_KEY",
    "DEFAULT_SUPABASE_REQUEST_TIMEOUT_SECONDS",
    "DEFAULT_SUPABASE_SESSION_MAX_AGE_SECONDS",
    "DEFAULT_SUPABASE_SESSION_SECRET",
    "DEFAULT_TWILIO_CALLBACK_STATUS_URL",
    "DEFAULT_TWILIO_OUTBOUND_INITIAL_BACKOFF_SECONDS",
    "DEFAULT_TWILIO_OUTBOUND_LEASE_SECONDS",
    "DEFAULT_TWILIO_OUTBOUND_MAX_ATTEMPTS",
    "DEFAULT_TWILIO_OUTBOUND_MAX_BACKOFF_SECONDS",
    "DEFAULT_TWILIO_OUTBOUND_SENDER_E164",
    "Settings",
    "load_settings",
]
