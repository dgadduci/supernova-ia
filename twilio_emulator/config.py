"""Emulator configuration with bounded fail-closed behaviour.

The module owns the small surface required to bring the emulator
process up:

* the operator-pinned control token used by the admin/pilot server to
  call the inbound control endpoint;
* the operator-pinned URL of the T-C webhook the emulator posts the
  signed form to;
* the operator-pinned Twilio-shaped account SID and auth token used to
  (a) sign inbound forms so the existing T-C signature validator
  accepts them and (b) authenticate outbound Messages API calls.

The credentials are pinned by the operator and shared verbatim by
the T-C adapter and the central dispatcher so the three services
agree on the same ``account_sid`` / ``auth_token`` pair. Generating
the credentials at process start would produce incompatible pairs
per service and silently break the canonical pipeline; the
emulator therefore refuses to start without an explicit
``EMULATOR_TWILIO_ACCOUNT_SID`` and ``EMULATOR_TWILIO_AUTH_TOKEN``
pair. The values live only inside :class:`EmulatorConfig`; they
are never echoed back by the JSON sinks, never logged and never
serialized by the inbound/outbound responses.

A missing or malformed required value raises
:class:`EmulatorConfigError` so the FastAPI startup hook can refuse
to accept traffic when the test-only configuration is incomplete.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
from dataclasses import dataclass
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class EmulatorConfigError(ValueError):
    """Raised when the emulator configuration is missing or invalid.

    The error is propagated by :func:`load_config_from_env` so the
    FastAPI startup hook fails closed before the first request is
    served. The message is operator-facing and intentionally does not
    echo generated credentials.
    """


_CONTROL_TOKEN_ENVS: tuple[str, ...] = (
    "EMULATOR_CONTROL_TOKEN",
    "TWILIO_EMULATOR_CONTROL_TOKEN",
)
_TC_WEBHOOK_URL_ENVS: tuple[str, ...] = (
    "EMULATOR_TC_WEBHOOK_URL",
    "TWILIO_EMULATOR_TC_WEBHOOK_URL",
)
_ACCOUNT_SID_ENVS: tuple[str, ...] = (
    "EMULATOR_TWILIO_ACCOUNT_SID",
    "TWILIO_EMULATOR_ACCOUNT_SID",
)
_AUTH_TOKEN_ENVS: tuple[str, ...] = (
    "EMULATOR_TWILIO_AUTH_TOKEN",
    "TWILIO_EMULATOR_AUTH_TOKEN",
)
_HTTP_PORT_ENVS: tuple[str, ...] = (
    "EMULATOR_HTTP_PORT",
    "TWILIO_EMULATOR_HTTP_PORT",
)
_RETENTION_ENVS: tuple[str, ...] = (
    "EMULATOR_CAPTURE_RETENTION",
    "TWILIO_EMULATOR_CAPTURE_RETENTION",
)
_PUBLIC_BASE_URL_ENVS: tuple[str, ...] = (
    "EMULATOR_PUBLIC_BASE_URL",
    "TWILIO_EMULATOR_PUBLIC_BASE_URL",
)

_ACCOUNT_SID_PATTERN: re.Pattern[str] = re.compile(r"^AC[0-9a-fA-F]{32}$")


def _read_first_env(names: tuple[str, ...]) -> str | None:
    for name in names:
        raw = os.environ.get(name)
        if raw is None:
            continue
        cleaned = str(raw).strip()
        if cleaned:
            return cleaned
    return None


def _require_env(names: tuple[str, ...], *, label: str) -> str:
    raw = _read_first_env(names)
    if raw is None:
        raise EmulatorConfigError(
            f"{label} is required for the twilio emulator"
        )
    return raw


def _require_https_url(names: tuple[str, ...], *, label: str) -> str:
    raw = _require_env(names, label=label)
    parsed = urlparse(raw)
    if parsed.scheme.lower() != "https":
        raise EmulatorConfigError(f"{label} must use the https scheme")
    if not parsed.netloc:
        raise EmulatorConfigError(f"{label} must be an absolute https URL")
    if parsed.query or parsed.fragment:
        raise EmulatorConfigError(
            f"{label} must not contain a query string or fragment"
        )
    return raw


def _require_account_sid(value: str | None, *, label: str) -> str:
    if value is None or not value:
        raise EmulatorConfigError(
            f"{label} is required for the twilio emulator "
            "and must be shared with the T-C adapter and central "
            "dispatcher so the three services authenticate the same "
            "Twilio-shaped credentials"
        )
    if not _ACCOUNT_SID_PATTERN.match(value):
        raise EmulatorConfigError(
            f"{label} must be a canonical Twilio account SID"
        )
    return value


def _require_auth_token(value: str | None, *, label: str) -> str:
    if value is None or not value:
        raise EmulatorConfigError(
            f"{label} is required for the twilio emulator "
            "and must be shared with the T-C adapter and central "
            "dispatcher so the three services authenticate the same "
            "Twilio-shaped credentials"
        )
    return value


def _generate_account_sid() -> str:
    """Return a freshly generated canonical Twilio account SID.

    The SID follows the documented Twilio shape (``AC`` followed by
    exactly 32 hexadecimal characters) so the existing T-C signature
    validator can accept a signed form. The value is unique per
    process and never logged.

    The helper is only used in test seams that explicitly opt out of
    the shared-credentials contract. Production configuration must
    always pin the credentials explicitly so the emulator, the T-C
    adapter and the central dispatcher agree on the same pair.
    """
    return "AC" + secrets.token_hex(16)


def _generate_auth_token() -> str:
    """Return a freshly generated opaque Twilio auth token.

    The token is 32 bytes of random material rendered as hex; the
    value is opaque to the Twilio validator and never appears in
    a log line. The helper is only used in test seams that
    explicitly opt out of the shared-credentials contract.
    """
    return secrets.token_hex(32)


def _coerce_positive_int(
    names: tuple[str, ...], *, default: int, label: str
) -> int:
    raw = _read_first_env(names)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise EmulatorConfigError(
            f"{label} must be a positive integer"
        ) from exc
    if value <= 0:
        raise EmulatorConfigError(f"{label} must be a positive integer")
    return value


@dataclass(frozen=True)
class EmulatorConfig:
    """Immutable emulator configuration snapshot.

    The credentials and tokens live only inside this object. They are
    never exposed by :class:`to_public_dict` and never serialised by
    the bounded JSON sinks; the helper exists solely so logging
    systems can confirm the emulator is up without leaking secrets.
    """

    control_token: str
    tc_webhook_url: str
    account_sid: str
    auth_token: str
    public_base_url: str | None
    http_port: int
    capture_retention: int

    def to_public_dict(self) -> dict[str, object]:
        """Return a non-secret projection of the configuration.

        The projection is the only public surface of the emulator
        configuration; the generated Twilio auth token and the control
        token are never included so the JSON sinks can use it to
        advertise the running mode without leaking credentials.
        """
        return {
            "account_sid": self.account_sid,
            "public_base_url": self.public_base_url,
            "http_port": int(self.http_port),
            "capture_retention": int(self.capture_retention),
        }


def load_config_from_env(
    env: dict[str, str] | None = None,
    *,
    allow_generated_credentials: bool = False,
) -> EmulatorConfig:
    """Build the emulator configuration snapshot.

    The optional ``env`` argument is the test seam: tests pass a
    dictionary of values so they can exercise validation paths
    without mutating ``os.environ``. Missing required URLs / control
    tokens raise :class:`EmulatorConfigError` so the process refuses
    to start.

    The emulator ``account_sid`` and ``auth_token`` MUST be pinned
    by the operator and shared with the T-C adapter and central
    dispatcher. The default behaviour fails closed when the
    credentials are missing. ``allow_generated_credentials=True``
    exists solely so the focused tests can exercise the credential
    validator; production callers must NEVER opt in because the
    generated pair would differ per process and silently break the
    canonical pipeline.
    """
    if env is None:
        control_token = _require_env(
            _CONTROL_TOKEN_ENVS, label="EMULATOR_CONTROL_TOKEN"
        )
        tc_webhook_url = _require_https_url(
            _TC_WEBHOOK_URL_ENVS, label="EMULATOR_TC_WEBHOOK_URL"
        )
        supplied_sid = _read_first_env(_ACCOUNT_SID_ENVS)
        supplied_token = _read_first_env(_AUTH_TOKEN_ENVS)
        public_base_url = _read_first_env(_PUBLIC_BASE_URL_ENVS)
        http_port = _coerce_positive_int(
            _HTTP_PORT_ENVS,
            default=9090,
            label="EMULATOR_HTTP_PORT",
        )
        retention = _coerce_positive_int(
            _RETENTION_ENVS,
            default=32,
            label="EMULATOR_CAPTURE_RETENTION",
        )
    else:
        control_token = str(env.get("EMULATOR_CONTROL_TOKEN", "")).strip()
        if not control_token:
            raise EmulatorConfigError(
                "EMULATOR_CONTROL_TOKEN is required for the twilio emulator"
            )
        tc_webhook_url = str(env.get("EMULATOR_TC_WEBHOOK_URL", "")).strip()
        parsed_url = urlparse(tc_webhook_url)
        if parsed_url.scheme.lower() != "https" or not parsed_url.netloc:
            raise EmulatorConfigError(
                "EMULATOR_TC_WEBHOOK_URL must be an absolute https URL"
            )
        if parsed_url.query or parsed_url.fragment:
            raise EmulatorConfigError(
                "EMULATOR_TC_WEBHOOK_URL must not contain a query string or fragment"
            )
        supplied_sid = str(env.get("EMULATOR_TWILIO_ACCOUNT_SID", "")).strip()
        supplied_token = str(env.get("EMULATOR_TWILIO_AUTH_TOKEN", "")).strip()
        raw_public = str(env.get("EMULATOR_PUBLIC_BASE_URL", "")).strip()
        public_base_url = raw_public or None
        try:
            http_port = int(env.get("EMULATOR_HTTP_PORT", "9090"))
        except ValueError as exc:
            raise EmulatorConfigError(
                "EMULATOR_HTTP_PORT must be a positive integer"
            ) from exc
        try:
            retention = int(env.get("EMULATOR_CAPTURE_RETENTION", "32"))
        except ValueError as exc:
            raise EmulatorConfigError(
                "EMULATOR_CAPTURE_RETENTION must be a positive integer"
            ) from exc

    if http_port <= 0:
        raise EmulatorConfigError("EMULATOR_HTTP_PORT must be greater than zero")
    if retention <= 0:
        raise EmulatorConfigError(
            "EMULATOR_CAPTURE_RETENTION must be greater than zero"
        )

    if supplied_sid:
        account_sid = _require_account_sid(
            supplied_sid, label="EMULATOR_TWILIO_ACCOUNT_SID"
        )
    elif allow_generated_credentials:
        account_sid = _generate_account_sid()
    else:
        raise EmulatorConfigError(
            "EMULATOR_TWILIO_ACCOUNT_SID is required for the twilio "
            "emulator and must be pinned to the exact Twilio-shaped "
            "value shared with the T-C adapter and central dispatcher"
        )

    if supplied_token:
        auth_token = _require_auth_token(
            supplied_token, label="EMULATOR_TWILIO_AUTH_TOKEN"
        )
    elif allow_generated_credentials:
        auth_token = _generate_auth_token()
    else:
        raise EmulatorConfigError(
            "EMULATOR_TWILIO_AUTH_TOKEN is required for the twilio "
            "emulator and must be pinned to the exact opaque token "
            "shared with the T-C adapter and central dispatcher"
        )

    return EmulatorConfig(
        control_token=control_token,
        tc_webhook_url=tc_webhook_url,
        account_sid=account_sid,
        auth_token=auth_token,
        public_base_url=public_base_url,
        http_port=http_port,
        capture_retention=retention,
    )


__all__ = [
    "EmulatorConfig",
    "EmulatorConfigError",
    "load_config_from_env",
]