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
    InvalidShadowHybridMinScoreGap,
    InvalidShadowVectorTopK,
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


def _product_recognizer_mode_env(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None:
        raw = default
    if raw in _RECOGNIZER_MODES:
        return raw
    fallback = "fuzzy"
    logger.warning(
        "product_recognizer_mode_invalid",
        extra={
            "configured_mode": raw,
            "effective_mode": fallback,
            "reason": "invalid_mode",
        },
    )
    return fallback


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


def _ollama_http_proxy_env(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        raise ValueError(f"{name} must be a non-empty absolute http URL when provided")
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() != "http" or not parsed.netloc:
        raise ValueError(f"{name} must be an absolute http URL when provided")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(
            f"{name} must be an absolute http URL without credentials, query, or fragment"
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
    ollama_http_proxy: str | None = None
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION
    embedding_url: str = DEFAULT_EMBEDDING_URL
    embedding_timeout_seconds: int = DEFAULT_EMBEDDING_TIMEOUT_SECONDS
    embedding_batch_size: int = DEFAULT_EMBEDDING_BATCH_SIZE
    enable_local_admin_endpoints: bool = False
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


def load_settings() -> Settings:
    effective_mode = _product_recognizer_mode_env(
        "PRODUCT_RECOGNIZER_MODE",
        DEFAULT_PRODUCT_RECOGNIZER_MODE,
    )
    return Settings(
        llm_url=_str_env("LLM_URL", "http://localhost:11434/api/generate"),
        llm_model=_str_env("LLM_MODEL", "qwen-27b-coding:latest"),
        llm_timeout=_int_env("LLM_TIMEOUT", 180),
        llm_keep_alive=_str_env("LLM_KEEP_ALIVE", "2h"),
        llm_num_ctx=_int_env("LLM_NUM_CTX", 8192),
        llm_num_predict=_int_env("LLM_NUM_PREDICT", 1500),
        llm_log_content=_bool_env("LLM_LOG_CONTENT", False),
        llm_log_max_chars=_int_env("LLM_LOG_MAX_CHARS", 1000),
        ollama_http_proxy=_ollama_http_proxy_env("OLLAMA_HTTP_PROXY"),
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
    )


__all__ = [
    "DEFAULT_EMBEDDING_BATCH_SIZE",
    "DEFAULT_EMBEDDING_DIMENSION",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_EMBEDDING_TIMEOUT_SECONDS",
    "DEFAULT_EMBEDDING_URL",
    "DEFAULT_HYBRID_AUTHORITATIVE_POLICY_PATH",
    "DEFAULT_PRODUCT_RECOGNIZER_MODE",
    "DEFAULT_SHADOW_HYBRID_MIN_SCORE_GAP",
    "DEFAULT_SHADOW_VECTOR_TOP_K",
    "DEFAULT_TWILIO_CALLBACK_STATUS_URL",
    "DEFAULT_TWILIO_OUTBOUND_INITIAL_BACKOFF_SECONDS",
    "DEFAULT_TWILIO_OUTBOUND_LEASE_SECONDS",
    "DEFAULT_TWILIO_OUTBOUND_MAX_ATTEMPTS",
    "DEFAULT_TWILIO_OUTBOUND_MAX_BACKOFF_SECONDS",
    "DEFAULT_TWILIO_OUTBOUND_SENDER_E164",
    "Settings",
    "load_settings",
]
