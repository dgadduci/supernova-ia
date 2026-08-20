"""Bounded in-memory capture store.

The store keeps exactly one entry per simulated outbound delivery.
The retention is bounded by :data:`capture_retention` so a long-lived
emulator cannot leak unbounded memory while the admin status
projection reads it. The store is fully in-memory; the emulator
deliberately persists nothing so the durable provider receipt/outbox
remains the source of truth for the admin status projection.

The store enforces a closed ``InMemoryCaptureStore`` API so the
HTTP-bound surfaces (inbound control + outbound Messages API) cannot
build their own alternative storage path. The store emits no logs:
captures never contain message bodies, signatures or credentials, and
the keys are synthetic ``MessageSid`` identifiers that are safe to
project.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock


@dataclass(frozen=True)
class OutboundCapture:
    """Bounded projection of one simulated outbound delivery.

    The capture deliberately carries only the synthetic provider
    identifier and the receiving channel destination. The message
    body, signature, auth token, account SID and operator input are
    intentionally absent so a misconfigured sink cannot leak
    sensitive values through the structured output.
    """

    message_sid: str
    captured_at: str
    to_address: str
    from_address: str


class InMemoryCaptureStore:
    """FIFO bounded store for synthetic outbound captures.

    The store is thread-safe through a single ``OrderedDict`` guarded
    by :class:`threading.RLock`; the lock is exposed through
    :attr:`lock` so the FastAPI app can serialise the inbound control
    surface and the outbound Messages API surface across the same
    store. Tests build their own ``InMemoryCaptureStore`` and pass
    it to :class:`EmulatorService` directly.
    """

    def __init__(self, *, capture_retention: int) -> None:
        if not isinstance(capture_retention, int) or capture_retention <= 0:
            raise ValueError("capture_retention must be a positive integer")
        self._capture_retention = int(capture_retention)
        self._captures: OrderedDict[str, OutboundCapture] = OrderedDict()
        self._lock = RLock()

    @property
    def lock(self) -> RLock:
        return self._lock

    @property
    def retention(self) -> int:
        return self._capture_retention

    def record(self, capture: OutboundCapture) -> None:
        """Record one capture, evicting the oldest when over retention."""
        if not isinstance(capture, OutboundCapture):
            raise TypeError("capture must be an OutboundCapture")
        with self._lock:
            self._captures[capture.message_sid] = capture
            while len(self._captures) > self._capture_retention:
                self._captures.popitem(last=False)

    def get(self, message_sid: str) -> OutboundCapture | None:
        with self._lock:
            value = self._captures.get(message_sid)
            if value is None:
                return None
            return OutboundCapture(
                message_sid=value.message_sid,
                captured_at=value.captured_at,
                to_address=value.to_address,
                from_address=value.from_address,
            )

    def snapshot(self) -> list[OutboundCapture]:
        with self._lock:
            return [
                OutboundCapture(
                    message_sid=item.message_sid,
                    captured_at=item.captured_at,
                    to_address=item.to_address,
                    from_address=item.from_address,
                )
                for item in self._captures.values()
            ]

    def clear(self) -> None:
        with self._lock:
            self._captures.clear()


def _now_iso_utc() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


__all__ = [
    "InMemoryCaptureStore",
    "OutboundCapture",
]