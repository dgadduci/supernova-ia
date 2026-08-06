"""Phase-5.6 Twilio delivery callback adapter.

The adapter is the only place that knows the Twilio status-callback
contract:

1. ``validate_request`` — verifies ``X-Twilio-Signature`` against the
   externally configured public base URL plus the supplied route path
   and query string, and the submitted form parameters, before any
   database lookup or state mutation.
2. ``extract_envelope`` — normalizes the two required callback fields
   (``MessageSid``, ``MessageStatus``) into the canonical callback
   envelope consumed by the callback service.

The adapter owns no SQLAlchemy ``Session``, never imports the
repository, the dispatcher, the coordinator, the resolver or any
FastAPI surface. It MUST NOT call ``commit``, ``rollback``,
``begin``, ``flush``, ``close``, ``expire``, ``refresh`` or any
SQLAlchemy transaction-control method. It MUST NOT issue any Twilio
delivery call: the callback is the inbound side of the round trip,
not a sender.

The adapter accepts a validator seam so tests can inject a
``RequestValidator`` substitute without depending on the real SDK
``HMAC`` machinery or a real token. The URL composition reuses the
Phase-5.5 ``build_validation_url`` helper so the inbound webhook and
the callback route share the exact canonical-URL discipline.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from backend.services.exceptions import (
    InvalidTwilioDeliveryCallbackForm,
    TwilioSignatureUnavailable,
)
from backend.services.twilio_inbound_adapter import (
    TwilioRequestValidator,
    build_validation_url,
)
from backend.services.twilio_inbound_adapter import (
    validate_request as validate_inbound_request,
)

_CALLBACK_REQUIRED_FIELDS: tuple[str, ...] = (
    "MessageSid",
    "MessageStatus",
)

_ALLOWED_PROVIDER_STATUSES: frozenset[str] = frozenset(
    {
        "delivered",
        "failed",
        "undelivered",
        "sent",
    }
)


@dataclass(frozen=True)
class TwilioDeliveryCallbackEnvelope:
    """Validated Twilio status callback envelope.

    Every field is a non-empty canonical value produced by the
    adapter. The router passes the two ids to the callback service
    unchanged; the router never re-parses the raw form.
    """

    message_sid: str
    message_status: str


def _non_empty_string(form: Mapping[str, str], name: str) -> str:
    raw = form.get(name)
    if not isinstance(raw, str):
        raise InvalidTwilioDeliveryCallbackForm(
            f"{name} must be a non-empty string"
        )
    cleaned = raw.strip()
    if not cleaned:
        raise InvalidTwilioDeliveryCallbackForm(
            f"{name} must be a non-empty string"
        )
    return cleaned


def validate_request(
    *,
    validator: TwilioRequestValidator,
    base_url: str | None,
    path: str,
    query_string: str,
    form: Mapping[str, str],
    signature: str | None,
) -> bool:
    """Reuse the Phase-5.5 inbound signature validator.

    The two routes share the exact canonical URL discipline; the
    adapter never trusts host/proto forwarding headers and never
    bypasses the SDK validator.
    """
    return validate_inbound_request(
        validator=validator,
        base_url=base_url,
        path=path,
        query_string=query_string,
        form=form,
        signature=signature,
    )


def build_validation_url_or_raise(
    base_url: str | None,
    path: str,
    query_string: str,
) -> str:
    """Compose the canonical signature URL.

    Wraps :func:`build_validation_url` so the callback route can
    catch the configuration-missing exception consistently with the
    inbound webhook.
    """
    try:
        return build_validation_url(base_url or "", path, query_string)
    except TwilioSignatureUnavailable as exc:
        raise TwilioSignatureUnavailable(str(exc)) from exc


def extract_envelope(form: Mapping[str, str]) -> TwilioDeliveryCallbackEnvelope:
    """Normalize the two required callback fields.

    A missing or malformed required field, or a status outside the
    closed set the service knows how to apply, is a validly-signed
    business rejection: the router translates it into a safe no-op
    ``204`` reply without invoking the callback service and without
    touching the database.
    """
    message_sid = _non_empty_string(form, "MessageSid")
    message_status_raw = _non_empty_string(form, "MessageStatus")
    normalized = message_status_raw.strip().lower()
    if normalized not in _ALLOWED_PROVIDER_STATUSES:
        raise InvalidTwilioDeliveryCallbackForm(
            f"MessageStatus must be one of "
            f"{sorted(_ALLOWED_PROVIDER_STATUSES)} "
            f"(got {message_status_raw!r})"
        )
    return TwilioDeliveryCallbackEnvelope(
        message_sid=message_sid,
        message_status=normalized,
    )


__all__ = [
    "TwilioDeliveryCallbackEnvelope",
    "build_validation_url_or_raise",
    "extract_envelope",
    "validate_request",
]