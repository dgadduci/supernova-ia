"""Commerce adapter runtime configuration.

The adapter reads its configuration from environment variables at
startup. Any missing or malformed required value raises a typed
``CommerceAdapterConfigError`` so the application fails closed before
the first request is served. The settings object is immutable after
construction; tests build their own via :func:`load_config_from_env`.

The adapter does not import the NovaOrders backend module. The Twilio
account SID and auth token are merchant-owned secrets that never leave
the adapter process; the shared installation secret is rotated by the
NovaOrders provisioning seam and is held in memory only.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse


class CommerceAdapterConfigError(ValueError):
    """Raised when one or more required environment variables are
    missing or malformed.

    The application refuses to start when this exception propagates out
    of :func:`load_config_from_env`. The message is operator-facing and
    intentionally does not echo the secret values.
    """


_REQUIRED_ENVS: tuple[str, ...] = (
    "TC_TWILIO_AUTH_TOKEN",
    "TC_TWILIO_ACCOUNT_SID",
    "TC_TWILIO_WEBHOOK_BASE_URL",
    "TC_NOVAORDERS_INGRESS_URL",
    "TC_INSTALLATION_ID",
    "TC_INSTALLATION_SECRET",
    "TC_COMERCIO_ID",
    "TC_TWILIO_SENDER_E164",
)


_INSTALLATION_ID_PATTERN: re.Pattern[str] = re.compile(r"^[a-z0-9]{24}$")


def _require_env(name: str) -> str:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        raise CommerceAdapterConfigError(
            f"{name} is required for the T-C adapter"
        )
    return raw.strip()


def _require_https_url(name: str, value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme.lower() != "https":
        raise CommerceAdapterConfigError(
            f"{name} must use the https scheme"
        )
    if not parsed.netloc:
        raise CommerceAdapterConfigError(
            f"{name} must be an absolute https URL"
        )
    if parsed.query or parsed.fragment:
        raise CommerceAdapterConfigError(
            f"{name} must not contain query string or fragment"
        )
    return value


def _require_twilio_account_sid(name: str, value: str) -> str:
    if not value.startswith("AC") or len(value) != 34:
        raise CommerceAdapterConfigError(
            f"{name} must be a canonical Twilio account SID"
        )
    tail = value[2:]
    if not all(ch in "0123456789abcdefABCDEF" for ch in tail):
        raise CommerceAdapterConfigError(
            f"{name} must be a canonical Twilio account SID"
        )
    return value


def _require_installation_id(name: str, value: str) -> str:
    if not _INSTALLATION_ID_PATTERN.match(value):
        raise CommerceAdapterConfigError(
            f"{name} must be a 24-character lowercase alphanumeric string"
        )
    return value


def _require_positive_int(name: str, raw: str | None) -> int:
    if raw is None or str(raw).strip() == "":
        raise CommerceAdapterConfigError(f"{name} is required")
    try:
        value = int(str(raw).strip())
    except ValueError as exc:
        raise CommerceAdapterConfigError(
            f"{name} must be a positive integer"
        ) from exc
    if value <= 0:
        raise CommerceAdapterConfigError(
            f"{name} must be a positive integer"
        )
    return value


def _require_e164(name: str, raw: str | None) -> str:
    if raw is None or not str(raw).strip():
        raise CommerceAdapterConfigError(f"{name} is required")
    cleaned = str(raw).strip()
    if not cleaned.startswith("+"):
        raise CommerceAdapterConfigError(
            f"{name} must be a canonical E.164 number starting with '+'"
        )
    digits = cleaned[1:]
    if not digits.isdigit() or not digits:
        raise CommerceAdapterConfigError(
            f"{name} must be a canonical E.164 number with digits only after '+'"
        )
    return cleaned


@dataclass(frozen=True)
class CommerceAdapterConfig:
    """Immutable adapter configuration snapshot."""

    twilio_auth_token: str
    twilio_account_sid: str
    twilio_webhook_base_url: str
    novaorders_ingress_url: str
    installation_id: str
    installation_secret: str
    comercio_id: int
    twilio_sender_e164: str
    http_timeout_seconds: int = 5


def load_config_from_env(env: dict[str, str] | None = None) -> CommerceAdapterConfig:
    """Build the configuration snapshot from environment variables.

    The optional ``env`` argument is the test seam: tests pass a
    dictionary of values so they can exercise the validation paths
    without mutating ``os.environ``.
    """
    if env is None:
        env = {name: _require_env(name) for name in _REQUIRED_ENVS}
    else:
        env = {name: str(env.get(name, "")).strip() for name in _REQUIRED_ENVS}
        missing = [
            name
            for name in _REQUIRED_ENVS
            if not env.get(name)
        ]
        if missing:
            raise CommerceAdapterConfigError(
                f"missing T-C adapter env values: {', '.join(missing)}"
            )

    base_url = _require_https_url(
        "TC_TWILIO_WEBHOOK_BASE_URL", env["TC_TWILIO_WEBHOOK_BASE_URL"]
    )
    ingress_url = _require_https_url(
        "TC_NOVAORDERS_INGRESS_URL", env["TC_NOVAORDERS_INGRESS_URL"]
    )
    account_sid = _require_twilio_account_sid(
        "TC_TWILIO_ACCOUNT_SID", env["TC_TWILIO_ACCOUNT_SID"]
    )
    installation_id = _require_installation_id(
        "TC_INSTALLATION_ID", env["TC_INSTALLATION_ID"]
    )
    installation_secret = env["TC_INSTALLATION_SECRET"]
    if not installation_secret:
        raise CommerceAdapterConfigError(
            "TC_INSTALLATION_SECRET must be a non-empty string"
        )

    comercio_id = _require_positive_int(
        "TC_COMERCIO_ID", env.get("TC_COMERCIO_ID")
    )
    sender_e164 = _require_e164(
        "TC_TWILIO_SENDER_E164", env.get("TC_TWILIO_SENDER_E164")
    )

    raw_timeout = env.get("TC_HTTP_TIMEOUT_SECONDS") or os.environ.get(
        "TC_HTTP_TIMEOUT_SECONDS"
    )
    if raw_timeout is None or raw_timeout == "":
        timeout = 5
    else:
        try:
            timeout = int(str(raw_timeout).strip())
        except ValueError as exc:
            raise CommerceAdapterConfigError(
                "TC_HTTP_TIMEOUT_SECONDS must be an integer"
            ) from exc
        if timeout <= 0:
            raise CommerceAdapterConfigError(
                "TC_HTTP_TIMEOUT_SECONDS must be greater than zero"
            )

    return CommerceAdapterConfig(
        twilio_auth_token=str(env["TC_TWILIO_AUTH_TOKEN"]),
        twilio_account_sid=account_sid,
        twilio_webhook_base_url=base_url,
        novaorders_ingress_url=ingress_url,
        installation_id=installation_id,
        installation_secret=installation_secret,
        comercio_id=int(comercio_id),
        twilio_sender_e164=str(sender_e164),
        http_timeout_seconds=int(timeout),
    )


__all__ = [
    "CommerceAdapterConfig",
    "CommerceAdapterConfigError",
    "load_config_from_env",
]