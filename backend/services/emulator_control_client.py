"""Twilio emulator HTTP client used by the admin/pilot route.

The client is the single seam between the admin/pilot server and the
standalone twilio emulator process. It only carries:

* the operator-pinned emulator URL;
* the operator-pinned control token used for the
  ``X-Emulator-Token`` header.

The client never accepts a target URL, an account SID or an auth
token from the caller: the configuration is the only authority.
The client never logs body, signature, token, URL or arbitrary
operator input.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


class EmulatorClientError(RuntimeError):
    """Bounded error raised by the emulator HTTP client.

    The exception type is opaque to the caller: the route translates
    every branch into a generic rejection.
    """


@dataclass(frozen=True)
class EmulatorControlConfig:
    """Bounded configuration for the admin emulator client."""

    base_url: str
    control_token: str
    timeout_seconds: float = 5.0


@dataclass(frozen=True)
class EmulatorControlResponse:
    """Bounded outcome of one emulator control call."""

    status: str
    message_sid: str
    synthetic_inbound_id: str


class EmulatorControlClient:
    """HTTP-based client that drives the emulator inbound control."""

    def __init__(self, *, config: EmulatorControlConfig) -> None:
        from urllib.parse import urlparse

        if not isinstance(config, EmulatorControlConfig):
            raise TypeError("config is required")
        parsed = urlparse(config.base_url)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise ValueError("emulator base_url must be an absolute https URL")
        if not config.control_token:
            raise ValueError("emulator control_token is required")
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self._config = config
        self._last_http_status: int = 0

    @property
    def config(self) -> EmulatorControlConfig:
        return self._config

    def submit_inbound(
        self,
        *,
        source_e164: str,
        destination_e164: str,
        body: str,
        synthetic_message_sid: str | None = None,
    ) -> EmulatorControlResponse:
        """Submit one bounded inbound to the emulator control surface.

        The function composes the bounded payload, POSTs it to the
        configured URL with the ``X-Emulator-Token`` header and
        returns the synthetic inbound identifier. The function never
        logs body, address, signature or arbitrary input.
        """
        url = f"{self._config.base_url.rstrip('/')}/internal/emulator/inbound"
        payload: dict[str, Any] = {
            "source_e164": source_e164,
            "destination_e164": destination_e164,
            "body": body,
        }
        if synthetic_message_sid:
            payload["synthetic_message_sid"] = synthetic_message_sid
        body_bytes = json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        headers = {
            "X-Emulator-Token": self._config.control_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            import httpx

            with httpx.Client(timeout=self._config.timeout_seconds) as client:
                response = client.post(url, content=body_bytes, headers=headers)
        except Exception as exc:
            raise EmulatorClientError(type(exc).__name__) from exc
        self._last_http_status = int(response.status_code)
        if response.status_code not in (200, 201):
            raise EmulatorClientError(
                f"emulator_http_status_{int(response.status_code)}"
            )
        try:
            decoded = response.json()
        except ValueError as exc:
            raise EmulatorClientError("invalid_payload") from exc
        if not isinstance(decoded, dict):
            raise EmulatorClientError("invalid_payload_shape")
        synthetic_inbound_id = str(
            decoded.get("synthetic_inbound_id", "")
        )
        message_sid = str(decoded.get("message_sid", ""))
        status = str(decoded.get("status", ""))
        if not status or not synthetic_inbound_id or not message_sid:
            raise EmulatorClientError("missing_fields")
        return EmulatorControlResponse(
            status=status,
            message_sid=message_sid,
            synthetic_inbound_id=synthetic_inbound_id,
        )


def build_emulator_control_client(
    *,
    base_url: str | None,
    control_token: str | None,
    timeout_seconds: float = 5.0,
) -> EmulatorControlClient | None:
    """Return the emulator control client when fully configured.

    The helper returns ``None`` when the operator did not configure
    the test-only emulator so the admin route can reject the action
    without invoking a fallback path.
    """
    if not isinstance(base_url, str) or not base_url:
        return None
    if not isinstance(control_token, str) or not control_token:
        return None
    return EmulatorControlClient(
        config=EmulatorControlConfig(
            base_url=base_url,
            control_token=control_token,
            timeout_seconds=float(timeout_seconds),
        )
    )


__all__ = [
    "EmulatorClientError",
    "EmulatorControlClient",
    "EmulatorControlConfig",
    "EmulatorControlResponse",
    "build_emulator_control_client",
]