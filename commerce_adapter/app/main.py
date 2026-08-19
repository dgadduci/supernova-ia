"""FastAPI application factory for the T-C adapter.

The module owns the FastAPI instance, the lifespan and the dependency
that exposes the immutable :class:`CommerceAdapterConfig` to the
routes.

Startup fail-closed:

* the production entry point (``app = create_app()`` below) loads the
  configuration from environment variables at import time. A missing
  or malformed value raises :class:`CommerceAdapterConfigError`
  before ``uvicorn`` accepts traffic so the operator gets a single
  typed error instead of a 5xx on the first request;
* tests build their own app via :func:`create_app` so they can mount
  the application against a controlled configuration without
  touching the global environment. Tests must therefore use
  ``create_app(config=...)`` and never import the module-level
  ``app`` instance.

The health endpoint, the webhook route and the outbound route are
mounted in the documented order so the production behaviour matches
the approved architecture (the empty ``/health`` ping is preserved as
a plain liveness probe).
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from commerce_adapter.app.config import (
    CommerceAdapterConfig,
    CommerceAdapterConfigError,
    load_config_from_env,
)
from commerce_adapter.app.dependencies import build_config_dependency
from commerce_adapter.app.routes import health, outbound, webhook

logger = logging.getLogger(__name__)


def create_app(
    *,
    config: CommerceAdapterConfig | None = None,
) -> FastAPI:
    """Build the FastAPI app.

    When ``config`` is ``None`` the app loads the configuration from
    environment variables at construction time. A missing or
    malformed value raises :class:`CommerceAdapterConfigError` so the
    application refuses to start before ``uvicorn`` accepts traffic.
    Tests pass an explicit configuration so they can mount the app
    without environment variables.
    """
    if config is None:
        config = load_config_from_env()

    app = FastAPI(title="commerce-adapter", version="0.1.0")

    def _override_config() -> CommerceAdapterConfig:
        return config

    app.dependency_overrides[build_config_dependency] = _override_config

    app.include_router(health.router)
    app.include_router(webhook.router)
    app.include_router(outbound.router)
    return app


try:
    app = create_app()
except CommerceAdapterConfigError as exc:
    logger.error(
        "commerce_adapter_configuration_failure",
        extra={"reason": type(exc).__name__},
    )
    raise


__all__ = [
    "create_app",
]