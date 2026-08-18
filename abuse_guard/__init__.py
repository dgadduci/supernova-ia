"""Standalone abuse-guard service for NovaOrders magic-link issuance.

This package is intentionally independent of the NovaOrders backend. It
implements the external guard contract expected by
``backend.auth.abuse_guard.request_magic_link_authorization`` and is
intended to be deployed as a separate Railway service with its own
private Redis.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
