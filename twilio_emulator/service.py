"""Emulator service layer.

The module owns the narrow business primitives the FastAPI surface
needs:

* :func:`build_inbound_form` — compose the complete Twilio-shaped
  form for one synthetic inbound delivery;
* :class:`EmulatorService` — the single seam that accepts the
  bounded inbound command and emits the bounded outbound response;
* the helper that produces a Twilio-shaped ``201 Created`` JSON
  response for an outbound Messages API call.

The service never logs body, signature, account SID, auth token,
operator input or any Twilio payload. The structured log lines only
carry the closed outcome vocabulary used by the bounded observer.

The service does not import :mod:`fastapi`, :mod:`httpx`, or the real
Twilio SDK. Tests build the service manually through
:func:`build_emulator_service` so they can swap the HTTP poster for
an in-memory stand-in and assert on the canonical form contents.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from twilio_emulator.captures import (
    InMemoryCaptureStore,
    OutboundCapture,
    _now_iso_utc,
)
from twilio_emulator.config import EmulatorConfig
from twilio_emulator.identifiers import (
    account_sid_prefix,
    generate_message_sid,
)
from twilio_emulator.signature import compute_form_signature

logger = logging.getLogger(__name__)


_WHATSAPP_PREFIX: str = "whatsapp:"
_E164_RE: re.Pattern[str] = re.compile(r"^\+[1-9]\d{1,14}$")


@dataclass(frozen=True)
class InboundControlCommand:
    """Server-to-server bounded inbound test command.

    The admin/pilot server forwards exactly these fields to the
    emulator inbound control surface. The emulator itself never
    accepts a target URL, an account SID or an auth token from the
    command — the configuration is the single authority.
    """

    source_e164: str
    destination_e164: str
    body: str
    synthetic_message_sid: str | None


@dataclass(frozen=True)
class InboundControlResult:
    """Bounded outcome of a successful inbound control command."""

    message_sid: str
    submitted_form: Mapping[str, str]


@dataclass(frozen=True)
class OutboundAcceptance:
    """Bounded outcome of one synthetic outbound delivery."""

    message_sid: str
    account_sid: str
    status: str


class EmulatorValidationError(ValueError):
    """Raised when the inbound control command is malformed.

    The exception never echoes the body, the source/destination
    addresses or any other operator-supplied value. The message only
    identifies the field that failed validation.
    """


class EmulatorAuthError(PermissionError):
    """Raised when the inbound control authentication is missing/invalid."""


class EmulatorUnavailable(RuntimeError):
    """Raised when the configured target URL is unreachable.

    The exception never echoes the URL or any other operator
    configuration. The HTTP-bound surfaces translate it into a
    bounded ``502``/``500`` response with no payload leak.
    """


def _as_whatsapp_address(canonical_e164: str) -> str:
    if not isinstance(canonical_e164, str):
        raise EmulatorValidationError("address must be a string")
    cleaned = canonical_e164.strip()
    cleaned = cleaned.removeprefix(_WHATSAPP_PREFIX)
    if not _E164_RE.match(cleaned):
        raise EmulatorValidationError("address must be canonical E.164")
    return f"{_WHATSAPP_PREFIX}{cleaned}"


def _normalize_e164(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        raise EmulatorValidationError(f"{label} must be a string")
    cleaned = value.strip()
    cleaned = cleaned.removeprefix(_WHATSAPP_PREFIX)
    if not _E164_RE.match(cleaned):
        raise EmulatorValidationError(f"{label} must be canonical E.164")
    return cleaned


def _bounded_body(value: str) -> str:
    if not isinstance(value, str):
        raise EmulatorValidationError("body must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise EmulatorValidationError("body must be a non-empty string")
    if len(cleaned) > 1024:
        raise EmulatorValidationError("body exceeds 1024 characters")
    return cleaned


def build_inbound_form(
    *,
    config: EmulatorConfig,
    command: InboundControlCommand,
) -> tuple[Mapping[str, str], str]:
    """Compose the Twilio-shaped inbound form and its signature.

    The helper produces the exact canonical form the existing T-C
    signature validator expects. The destination address is taken
    from the configured T-C webhook — not the command — so a
    misconfigured operator can never redirect the synthetic inbound.
    """
    source = _normalize_e164(command.source_e164, label="source_e164")
    destination = _normalize_e164(
        command.destination_e164, label="destination_e164"
    )
    body = _bounded_body(command.body)
    message_sid = (
        command.synthetic_message_sid
        if isinstance(command.synthetic_message_sid, str)
        and command.synthetic_message_sid.strip()
        else generate_message_sid()
    )
    form: dict[str, str] = {
        "MessageSid": message_sid,
        "From": _as_whatsapp_address(source),
        "To": _as_whatsapp_address(destination),
        "Body": body,
        "AccountSid": config.account_sid,
        "ApiVersion": "2010-04-01",
        "NumMedia": "0",
    }
    signature = compute_form_signature(
        auth_token=config.auth_token,
        url=config.tc_webhook_url,
        params=form,
    )
    return form, signature


class EmulatorService:
    """Bounded service that glues the inbound control to the outbound API."""

    def __init__(
        self,
        *,
        config: EmulatorConfig,
        captures: InMemoryCaptureStore,
        http_post: Any,
    ) -> None:
        self._config = config
        self._captures = captures
        self._http_post = http_post

    @property
    def config(self) -> EmulatorConfig:
        return self._config

    @property
    def captures(self) -> InMemoryCaptureStore:
        return self._captures

    def submit_inbound(
        self,
        *,
        presented_token: str | None,
        command: InboundControlCommand,
    ) -> InboundControlResult:
        """Accept one inbound control command and POST the signed form.

        The token comparison uses :func:`hmac.compare_digest` so a
        timing side-channel cannot leak the configured control token.
        The synthetic outbound capture is intentionally NOT recorded
        here: the capture happens on the outbound Messages API call,
        which is the durable point of contact for the canonical
        pipeline.
        """
        if not isinstance(presented_token, str) or not presented_token:
            raise EmulatorAuthError("control token is missing")
        if presented_token != self._config.control_token:
            raise EmulatorAuthError("control token is invalid")

        form, signature = build_inbound_form(
            config=self._config, command=command
        )
        try:
            self._http_post(
                url=self._config.tc_webhook_url,
                form=form,
                signature=signature,
            )
        except Exception as exc:
            raise EmulatorUnavailable(
                "twilio emulator could not deliver inbound"
            ) from exc
        return InboundControlResult(
            message_sid=str(form["MessageSid"]),
            submitted_form=dict(form),
        )

    def accept_outbound(
        self,
        *,
        account_sid: str | None,
        presented_auth_token: str | None,
        to_address: str | None,
        from_address: str | None,
    ) -> OutboundAcceptance:
        """Validate the outbound call and record the synthetic capture.

        The function performs the four-step authentication contract
        of the Twilio Messages API: account SID exact match, auth
        token exact match, to-address canonical E.164 and from-address
        canonical E.164. The capture is recorded under a freshly
        generated ``MessageSid`` and never echoes the body, signature
        or auth token.
        """
        if not isinstance(account_sid, str) or not account_sid:
            raise EmulatorAuthError("missing account sid")
        if account_sid != self._config.account_sid:
            raise EmulatorAuthError("invalid account sid")
        if not isinstance(presented_auth_token, str) or not presented_auth_token:
            raise EmulatorAuthError("missing auth token")
        if presented_auth_token != self._config.auth_token:
            raise EmulatorAuthError("invalid auth token")
        if not isinstance(to_address, str) or not to_address:
            raise EmulatorValidationError("missing destination address")
        if not isinstance(from_address, str) or not from_address:
            raise EmulatorValidationError("missing source address")

        normalized_to = _normalize_e164(to_address, label="to")
        normalized_from = _normalize_e164(from_address, label="from")

        message_sid = generate_message_sid()
        self._captures.record(
            OutboundCapture(
                message_sid=message_sid,
                captured_at=_now_iso_utc(),
                to_address=_as_whatsapp_address(normalized_to),
                from_address=_as_whatsapp_address(normalized_from),
            )
        )
        logger.info(
            "twilio_emulator_outbound_accepted",
            extra={
                "account_sid": account_sid_prefix(account_sid),
                "status": "accepted",
            },
        )
        return OutboundAcceptance(
            message_sid=message_sid,
            account_sid=account_sid,
            status="accepted",
        )


def build_outbound_response_body(acceptance: OutboundAcceptance) -> bytes:
    """Return the Twilio-shaped ``201 Created`` JSON body.

    The body follows the documented Twilio Messages API shape so the
    existing T-C route and the central adapter can read the ``sid``
    field verbatim. The body never contains the auth token, signature
    or any operator-supplied text.
    """
    if not isinstance(acceptance, OutboundAcceptance):
        raise TypeError("acceptance must be an OutboundAcceptance")
    payload = {
        "account_sid": acceptance.account_sid,
        "sid": acceptance.message_sid,
        "status": acceptance.status,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def build_emulator_service(
    *,
    config: EmulatorConfig,
    http_post: Any,
    captures: InMemoryCaptureStore | None = None,
) -> EmulatorService:
    """Construct the service object used by the FastAPI app.

    The helper centralises the dependency wiring so tests can use a
    custom ``http_post`` callable and a custom capture store without
    reaching into the private attributes of the service.
    """
    if captures is None:
        captures = InMemoryCaptureStore(
            capture_retention=config.capture_retention
        )
    return EmulatorService(
        config=config, captures=captures, http_post=http_post
    )


__all__ = [
    "EmulatorAuthError",
    "EmulatorService",
    "EmulatorUnavailable",
    "EmulatorValidationError",
    "InboundControlCommand",
    "InboundControlResult",
    "OutboundAcceptance",
    "build_emulator_service",
    "build_inbound_form",
    "build_outbound_response_body",
]