"""Standalone test-only Twilio emulator.

The package implements a bounded provider-shaped transport service
that the admin/pilot panel can drive in lieu of the real Twilio
provider. The package owns no NovaOrders database and no
business processing: it exposes two narrow surfaces — a server-to-server
authenticated inbound driver and a Twilio-shaped outbound Messages API —
that let the existing T-C/NovaOrders pipeline run end-to-end without
contacting ``api.twilio.com`` or instantiating ``twilio.rest.Client``.

Generated Twilio-shaped credentials live inside this process only; they
are never returned to a browser, never embedded in a log line and never
sent to the real Twilio service. Every cross-service call is
authenticated by the configured control token or by the emulator's own
generated HTTP Basic credentials.
"""
from __future__ import annotations

__all__: list[str] = []