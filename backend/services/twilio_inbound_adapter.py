"""Phase-5.5 Twilio provider-edge adapter.

The adapter is the only place that knows about Twilio's signature
contract, the ``whatsapp:`` transport envelope and the SDK
``RequestValidator``. It performs two responsibilities:

1. ``validate_request`` — verifies ``X-Twilio-Signature`` against the
   externally configured public base URL plus the supplied route path
   and query string, and the submitted form parameters, before any
   database, routing or processing operation.
2. ``extract_envelope`` — normalizes the four accepted Twilio form
   fields (``MessageSid``, ``From``, ``To``, ``Body``) into the
   existing canonical WhatsApp contract consumed by the resolver and
   the Phase-5.4 coordinator.

The adapter owns no SQLAlchemy ``Session``, never imports the
coordinator, the resolver, the client service, the channel service,
or any repository. It MUST NOT call ``commit``, ``rollback``,
``begin``, ``flush``, ``close``, ``expire``, ``refresh`` or any
SQLAlchemy transaction-control method; it also MUST NOT issue any
HTTP, FastAPI, TwiML or delivery callback call. TwiML rendering is
performed by the router, not by the adapter.

The adapter accepts a validator seam so tests can inject a
``RequestValidator`` substitute without depending on the real SDK
``HMAC`` machinery or a real token.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from backend.services.canal_whatsapp_service import (
    InvalidCanalWhatsappDestination,
    normalize_destination,
)
from backend.services.cliente_service import (
    InvalidWhatsApp,
    normalize_whatsapp,
)
from backend.services.exceptions import (
    InvalidTwilioInboundForm,
    TwilioSignatureUnavailable,
)


class TwilioRequestValidator(Protocol):
    """Structural typing seam for the Twilio SDK ``RequestValidator``.

    The adapter only depends on the ``validate(uri, params, signature)``
    contract. Tests inject a substitute; production code passes the
    SDK ``RequestValidator(auth_token)`` instance.
    """

    def validate(
        self,
        uri: str,
        params: Mapping[str, str],
        signature: str,
    ) -> bool: ...


_REQUIRED_FIELDS: tuple[str, ...] = (
    "MessageSid",
    "From",
    "To",
    "Body",
)


def _non_empty_string(form: Mapping[str, str], name: str) -> str:
    raw = form.get(name)
    if not isinstance(raw, str):
        raise InvalidTwilioInboundForm(
            f"{name} must be a non-empty string"
        )
    cleaned = raw.strip()
    if not cleaned:
        raise InvalidTwilioInboundForm(
            f"{name} must be a non-empty string"
        )
    return cleaned


def _canonicalize_address(raw: str) -> str:
    """Normalize a Twilio ``From``/``To`` value to canonical E.164.

    Twilio uses ``whatsapp:+E.164`` envelopes; the existing
    ``normalize_destination`` already strips the prefix and rejects
    non-canonical numbers. ``normalize_whatsapp`` from the client
    service performs the same role for client-supplied values.
    """
    try:
        return normalize_destination(raw)
    except InvalidCanalWhatsappDestination:
        # Fall back to the WhatsApp client normalizer so providers
        # that send the bare E.164 (without the ``whatsapp:`` prefix)
        # collapse to the same canonical form. If that also fails the
        # inbound form is genuinely malformed.
        try:
            return normalize_whatsapp(raw)
        except InvalidWhatsApp as exc:
            raise InvalidTwilioInboundForm(str(exc)) from exc


def build_validation_url(base_url: str, path: str, query_string: str) -> str:
    """Compose the canonical signature URL.

    Twilio signs the absolute URL the request actually reached
    (scheme + host + path + query). The configured
    ``TWILIO_WEBHOOK_BASE_URL`` already pins scheme + host; the
    adapter owns the path and query so signature validation cannot
    be tricked by attacker-supplied headers.
    """
    if not isinstance(base_url, str) or not base_url:
        raise TwilioSignatureUnavailable(
            "twilio_webhook_base_url is not configured"
        )
    if not isinstance(path, str) or not path.startswith("/"):
        raise TwilioSignatureUnavailable(
            "twilio webhook path must start with '/'"
        )
    cleaned_path = path
    if query_string:
        if not isinstance(query_string, str):
            raise TwilioSignatureUnavailable(
                "twilio webhook query string must be a string"
            )
        cleaned_path = f"{cleaned_path}?{query_string}"
    return f"{base_url.rstrip('/')}{cleaned_path}"


@dataclass(frozen=True)
class TwilioInboundEnvelope:
    """Validated Twilio WhatsApp inbound envelope.

    Every field is a non-empty canonical value produced by the
    adapter. The router passes the four ids/texts to the existing
    5.1 / 5.4 boundaries unchanged; the router never re-parses the
    raw form.
    """

    message_sid: str
    from_e164: str
    to_e164: str
    body: str


def validate_request(
    *,
    validator: TwilioRequestValidator,
    base_url: str | None,
    path: str,
    query_string: str,
    form: Mapping[str, str],
    signature: str | None,
) -> bool:
    """Verify the Twilio signature against the canonical URL and form.

    The endpoint MUST fail closed when ``base_url`` is missing or the
    signature is missing/malformed, so this helper returns ``True``
    only when every precondition is satisfied AND the SDK validator
    confirms the signature.
    """
    if not base_url:
        return False
    if not isinstance(signature, str) or not signature:
        return False
    if not isinstance(form, Mapping):
        return False
    uri = build_validation_url(base_url, path, query_string)
    str_params: dict[str, str] = {}
    for key, value in form.items():
        if isinstance(value, str):
            str_params[str(key)] = value
        elif isinstance(value, bytes):
            try:
                str_params[str(key)] = value.decode("utf-8")
            except UnicodeDecodeError:
                return False
    return bool(validator.validate(uri, str_params, signature))


_NORMALIZE_PATH_RE = re.compile(r"^/[\w./\-]*$")


def assert_path_is_safe(path: str) -> None:
    """Defensive sanity check: the route path must be a relative
    HTTP path that contains no whitespace or query/fragment. The
    router always passes a literal path; this guard exists so the
    adapter cannot be reused with attacker-controlled routing data.
    """
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or "?" in path
        or "#" in path
        or not _NORMALIZE_PATH_RE.match(path)
    ):
        raise TwilioSignatureUnavailable(
            "twilio webhook path is malformed"
        )


def extract_envelope(form: Mapping[str, str]) -> TwilioInboundEnvelope:
    """Normalize the four required Twilio fields into the
    Phase-5.5 ``TwilioInboundEnvelope``.

    A missing or malformed required field is a validly-signed
    business rejection, never a partial processing path. The
    adapter raises :class:`InvalidTwilioInboundForm`; the router
    translates it into a safe control TwiML reply without invoking
    the coordinator.
    """
    message_sid = _non_empty_string(form, "MessageSid")
    from_value = _non_empty_string(form, "From")
    to_value = _non_empty_string(form, "To")
    body = _non_empty_string(form, "Body")
    return TwilioInboundEnvelope(
        message_sid=message_sid,
        from_e164=_canonicalize_address(from_value),
        to_e164=_canonicalize_address(to_value),
        body=body,
    )


__all__ = [
    "TwilioInboundEnvelope",
    "TwilioRequestValidator",
    "assert_path_is_safe",
    "build_validation_url",
    "extract_envelope",
    "validate_request",
]
