"""Fail-closed configuration for the abuse guard service.

The service intentionally loads every value from the environment and
refuses to start when any required value is missing, blank, malformed
or outside the allowed bounded range. There is no in-memory fallback
limiter; an invalid configuration means the service is "not ready"
and the ``/check`` endpoint returns HTTP 503.

Kept intentionally dependency-free so the module can be imported by
the unit tests without FastAPI or Redis available.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

MAX_BOUNDED_INTEGER = 1000
MAX_BOUNDED_WINDOW_SECONDS = 86400

DEFAULT_EMAIL_WINDOW_SECONDS = 60
DEFAULT_EMAIL_MAX = 1
DEFAULT_IP_WINDOW_SECONDS = 900
DEFAULT_IP_MAX = 5
DEFAULT_PAIR_WINDOW_SECONDS = 3600
DEFAULT_PAIR_MAX = 3
DEFAULT_PORT = 8000


@dataclass(frozen=True)
class GuardConfig:
    """Validated guard configuration loaded from the environment."""

    redis_url: str
    bearer_token: str
    hash_secret: str
    email_window_seconds: int
    email_max: int
    ip_window_seconds: int
    ip_max: int
    pair_window_seconds: int
    pair_max: int
    port: int

    def is_auth_secret_sufficient(self) -> bool:
        """Indicate the bearer token has enough entropy to be safe.

        The token is a configured secret; we only require a minimum
        length so the operator cannot accidentally pin an empty value.
        """

        return len(self.bearer_token.strip()) >= 8


class ConfigError(ValueError):
    """Raised when the environment does not yield a valid configuration."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _read_required(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ConfigError(f"missing:{name}")
    return value


def _read_optional(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value


def _read_bounded_int(name: str, default: int, *, lo: int, hi: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        parsed = int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"invalid:{name}") from exc
    if parsed < lo or parsed > hi:
        raise ConfigError(f"out_of_range:{name}")
    return parsed


def _read_port(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        parsed = int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"invalid:{name}") from exc
    if parsed < 1 or parsed > 65535:
        raise ConfigError(f"out_of_range:{name}")
    return parsed


def load_config(env: Mapping[str, str] | None = None) -> GuardConfig:
    """Build a :class:`GuardConfig` from ``env`` or ``os.environ``.

    When ``env`` is provided it is used as a flat mapping of variable
    name to raw string value, otherwise the function reads from
    ``os.environ``. Missing required values, malformed integers and
    out-of-range limits raise :class:`ConfigError`.
    """

    if env is None:
        env = os.environ

    env_is_real = env is os.environ
    saved = {key: os.environ.get(key) for key in list(env.keys())}
    try:
        if not env_is_real:
            for key, value in env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        redis_url = _read_required("REDIS_URL")
        bearer_token = _read_required("ABUSE_GUARD_TOKEN")
        hash_secret = _read_required("ABUSE_GUARD_HASH_SECRET")
        email_window = _read_bounded_int(
            "ABUSE_EMAIL_WINDOW_SECONDS",
            DEFAULT_EMAIL_WINDOW_SECONDS,
            lo=1,
            hi=MAX_BOUNDED_WINDOW_SECONDS,
        )
        email_max = _read_bounded_int(
            "ABUSE_EMAIL_MAX",
            DEFAULT_EMAIL_MAX,
            lo=1,
            hi=MAX_BOUNDED_INTEGER,
        )
        ip_window = _read_bounded_int(
            "ABUSE_IP_WINDOW_SECONDS",
            DEFAULT_IP_WINDOW_SECONDS,
            lo=1,
            hi=MAX_BOUNDED_WINDOW_SECONDS,
        )
        ip_max = _read_bounded_int(
            "ABUSE_IP_MAX",
            DEFAULT_IP_MAX,
            lo=1,
            hi=MAX_BOUNDED_INTEGER,
        )
        pair_window = _read_bounded_int(
            "ABUSE_PAIR_WINDOW_SECONDS",
            DEFAULT_PAIR_WINDOW_SECONDS,
            lo=1,
            hi=MAX_BOUNDED_WINDOW_SECONDS,
        )
        pair_max = _read_bounded_int(
            "ABUSE_PAIR_MAX",
            DEFAULT_PAIR_MAX,
            lo=1,
            hi=MAX_BOUNDED_INTEGER,
        )
        port = _read_port("PORT", DEFAULT_PORT)
    finally:
        if not env_is_real:
            for key in list(env.keys()):
                previous = saved.get(key)
                if previous is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = previous

    config = GuardConfig(
        redis_url=redis_url,
        bearer_token=bearer_token,
        hash_secret=hash_secret,
        email_window_seconds=email_window,
        email_max=email_max,
        ip_window_seconds=ip_window,
        ip_max=ip_max,
        pair_window_seconds=pair_window,
        pair_max=pair_max,
        port=port,
    )
    if not config.is_auth_secret_sufficient():
        raise ConfigError("invalid:ABUSE_GUARD_TOKEN")
    return config


def is_valid_email(value: object) -> bool:
    """Return ``True`` iff ``value`` is a non-empty, bounded email.

    The guard accepts a narrow, locally-checked format. The full RFC
    5322 grammar is intentionally avoided; Supabase performs the
    authoritative validation later. The guard only enforces that the
    value is a string, contains a single ``@`` and has at least one
    character on each side.
    """

    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if not candidate or len(candidate) > 254:
        return False
    if candidate.count("@") != 1:
        return False
    local, _, domain = candidate.partition("@")
    if not local or not domain:
        return False
    if "." not in domain:
        return False
    return not any(char.isspace() for char in candidate)


def normalize_email(value: str) -> str:
    """Trim and lowercase ``value`` for limiter key derivation."""

    return value.strip().lower()


def normalize_remote_ip(value: object) -> str | None:
    """Return a bounded remote IP or ``None`` when the input is missing.

    The guard does not parse IP structure; it only normalizes the
    surface that becomes part of the limiter key. The returned value is
    limited to a hard length to avoid pathological key material.
    """

    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if len(candidate) > 64:
        return None
    if any(char.isspace() for char in candidate):
        return None
    return candidate


__all__ = [
    "DEFAULT_EMAIL_MAX",
    "DEFAULT_EMAIL_WINDOW_SECONDS",
    "DEFAULT_IP_MAX",
    "DEFAULT_IP_WINDOW_SECONDS",
    "DEFAULT_PAIR_MAX",
    "DEFAULT_PAIR_WINDOW_SECONDS",
    "DEFAULT_PORT",
    "MAX_BOUNDED_INTEGER",
    "MAX_BOUNDED_WINDOW_SECONDS",
    "ConfigError",
    "GuardConfig",
    "is_valid_email",
    "load_config",
    "normalize_email",
    "normalize_remote_ip",
]
