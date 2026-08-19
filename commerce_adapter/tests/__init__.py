"""T-C adapter test package marker.

The tests exercise the adapter in isolation; they never call
NovaOrders and never call the real Twilio SDK. They inject a fake
``TwilioMessagesClient`` and a stubbed HTTP client so the surface is
deterministic.
"""
__all__: list[str] = []