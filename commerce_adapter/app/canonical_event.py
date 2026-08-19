"""Twilio-native form normalization and TwiML response helpers.

The adapter reads the four documented Twilio fields (``MessageSid``,
``From``, ``To``, ``Body``) plus a bounded set of extra fields that
Twilio always sends (``AccountSid``, ``ApiVersion``, ``NumMedia``,
``ProfileName``). The adapter maps them to the canonical names
expected by NovaOrders so the core never sees raw Twilio field names.

The helpers are pure functions: they never call the Twilio SDK and
never call NovaOrders. They never log body, phone, token, signature or
profile names.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_E164_RE: re.Pattern[str] = re.compile(r"^\+[1-9]\d{1,14}$")
_WHATSAPP_PREFIX: str = "whatsapp:"


@dataclass(frozen=True)
class CanonicalTwilioEvent:
    """Normalized Twilio event ready to be sent to NovaOrders.

    The four documented fields are normalized to canonical E.164; the
    bounded metadata fields are projected to a 32-char hash so a
    profile name never reaches a log.
    """

    instalacion_id: str
    comercio_id: int
    proveedor: str
    message_sid: str
    from_e164: str
    to_e164: str
    cuerpo: str
    profile_name_hash: str | None
    num_media: int


class InvalidTwilioForm(ValueError):
    """Raised when the inbound form is missing one of the required
    Twilio fields or carries an unparsable E.164 address.

    The webhook route translates this exception into the empty TwiML
    acknowledgement without calling NovaOrders because the event is
    durably classified as a no-op for this commerce.
    """


def _normalize_address(raw: str) -> str:
    """Normalize a Twilio ``From`` / ``To`` value to canonical E.164.

    Twilio uses ``whatsapp:+E.164`` envelopes; the helper strips the
    prefix and rejects anything that does not collapse to a canonical
    E.164 number.
    """
    if not isinstance(raw, str):
        raise InvalidTwilioForm("address must be a string")
    cleaned = raw.strip()
    cleaned = cleaned.removeprefix(_WHATSAPP_PREFIX)
    if not _E164_RE.match(cleaned):
        raise InvalidTwilioForm("address must be canonical E.164")
    return cleaned


def _non_empty_string(form: dict[str, str], name: str) -> str:
    raw = form.get(name)
    if not isinstance(raw, str):
        raise InvalidTwilioForm(f"{name} must be a non-empty string")
    cleaned = raw.strip()
    if not cleaned:
        raise InvalidTwilioForm(f"{name} must be a non-empty string")
    return cleaned


def _bounded_int(form: dict[str, str], name: str, default: int) -> int:
    raw = form.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise InvalidTwilioForm(f"{name} must be an integer") from exc
    if value < 0:
        raise InvalidTwilioForm(f"{name} must be non-negative")
    return value


def _profile_hash(form: dict[str, str]) -> str | None:
    raw = form.get("ProfileName")
    if not raw:
        return None
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:32]


def normalize_twilio_form(
    form: dict[str, str],
    *,
    instalacion_id: str,
    comercio_id: int,
) -> CanonicalTwilioEvent:
    """Build the canonical event from the complete Twilio form.

    The four documented fields are required; the bounded extras
    (``NumMedia``, ``ProfileName``) are projected to the documented
    surrogate fields and never reach a log.
    """
    message_sid = _non_empty_string(form, "MessageSid")
    from_raw = _non_empty_string(form, "From")
    to_raw = _non_empty_string(form, "To")
    body = _non_empty_string(form, "Body")
    return CanonicalTwilioEvent(
        instalacion_id=str(instalacion_id),
        comercio_id=int(comercio_id),
        proveedor="twilio",
        message_sid=message_sid,
        from_e164=_normalize_address(from_raw),
        to_e164=_normalize_address(to_raw),
        cuerpo=body,
        profile_name_hash=_profile_hash(form),
        num_media=_bounded_int(form, "NumMedia", 0),
    )


def empty_twiml_response() -> str:
    """Return the empty TwiML acknowledgement body.

    The body is exactly ``<Response></Response>`` and contains no
    ``<Message>``. The webhook route returns this body only after
    NovaOrders confirms acceptance or rejection of the canonical
    event.
    """
    return "<Response></Response>"


__all__ = [
    "CanonicalTwilioEvent",
    "InvalidTwilioForm",
    "empty_twiml_response",
    "normalize_twilio_form",
]