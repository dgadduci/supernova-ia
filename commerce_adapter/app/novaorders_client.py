"""HTTP client used by the T-C adapter to forward canonical events to
NovaOrders and to receive the bounded typed outcome.

The client is intentionally small: one ``forward_event`` entry point
that POSTs the canonical event bytes with the HMAC signature header
and maps the response into :class:`NovaOrdersIngressResult`. It never
logs body, phone, token or signature.

The client uses ``httpx.Client`` so it can be reused across requests
and so the bounded CLI can inject a custom ``httpx.Client`` for
testing without touching the real network.
"""
from __future__ import annotations

from typing import Any

import httpx

from commerce_adapter.app.config import CommerceAdapterConfig
from commerce_adapter.app.schemas import CanonicalInboundEvent, NovaOrdersIngressResult
from commerce_adapter.app.security import hmac_sign


class NovaOrdersUnreachable(Exception):
    """Raised when the bounded NovaOrders HTTP forward cannot complete.

    The webhook route translates this exception into a ``502`` so
    Twilio retries. The bounded CLI never translates this exception
    into a business outcome.
    """


def _build_payload_bytes(event: CanonicalInboundEvent) -> bytes:
    return event.model_dump_json().encode("utf-8")


def forward_event(
    *,
    config: CommerceAdapterConfig,
    event: CanonicalInboundEvent,
    http_client: httpx.Client | None = None,
) -> NovaOrdersIngressResult:
    """Forward the canonical event to NovaOrders and return the typed
    result.

    The function never logs body, phone, token or signature; it only
    surfaces the typed outcome so the webhook route can branch on the
    status. A non-200 response or a network error raises
    :class:`NovaOrdersUnreachable` so the route returns a ``502``.
    """
    payload = _build_payload_bytes(event)
    signature = hmac_sign(
        payload=payload, secret=config.installation_secret
    )
    url = (
        config.novaorders_ingress_url.rstrip("/")
        + "/"
        + str(config.installation_id)
        + "/accept-event"
    )
    headers = {
        "Content-Type": "application/json",
        "X-Installation-Signature": signature,
    }
    client_is_local = http_client is not None
    client = http_client or httpx.Client(
        timeout=float(config.http_timeout_seconds)
    )
    try:
        response = client.post(
            url,
            content=payload,
            headers=headers,
        )
    except httpx.HTTPError as exc:
        raise NovaOrdersUnreachable(str(type(exc).__name__)) from exc
    finally:
        if not client_is_local:
            client.close()

    if response.status_code != 200:
        return NovaOrdersIngressResult(
            status="unreachable",
            http_status=int(response.status_code),
        )

    try:
        body: Any = response.json()
    except ValueError as exc:
        raise NovaOrdersUnreachable("invalid_response") from exc

    if not isinstance(body, dict):
        return NovaOrdersIngressResult(
            status="unreachable",
            http_status=int(response.status_code),
        )

    status = str(body.get("status") or "")
    reason = body.get("reason")
    receipt_id = body.get("receipt_id")
    return NovaOrdersIngressResult(
        status=status,
        receipt_id=int(receipt_id) if isinstance(receipt_id, int) else None,
        reason=str(reason) if reason is not None else None,
        http_status=int(response.status_code),
    )


__all__ = [
    "NovaOrdersUnreachable",
    "forward_event",
]