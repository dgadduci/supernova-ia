"""Commerce adapter runtime package.

The runtime module owns the FastAPI application, the configuration
loader, the security primitives, the canonical event mapper, the
Twilio client seam, the NovaOrders HTTP client and the three routes
(health, Twilio webhook, outbound command). Each module is a small,
self-contained boundary so unit tests can exercise them in isolation.
"""

__all__: list[str] = []