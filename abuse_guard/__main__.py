"""Operator entry point for the ``abuse_guard`` service.

Running ``python -m abuse_guard`` loads the fail-closed configuration
from the environment, builds the Redis client and serves the FastAPI
app on the host configured by ``PORT`` (defaulting to ``8000``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from abuse_guard.app import build_runtime_redis_client, create_app
from abuse_guard.config import ConfigError, GuardConfig, load_config

logger = logging.getLogger("abuse_guard")


def build_app(
    *,
    redis_client_factory: Callable[[str], object] | None = None,
):
    """Build a fully-wired FastAPI app for production use.

    ``redis_client_factory`` defaults to
    :func:`abuse_guard.app.build_runtime_redis_client` and exists so
    tests can inject a deterministic fake transport. Production code
    must keep the default.

    The factory never silently downgrades the gate: when configuration
    is invalid or the Redis client cannot be built the returned app
    serves ``/health`` and ``/ready`` but its ``/check`` endpoint
    returns the bounded 503 response. Failures are logged through
    :func:`abuse_guard.app.create_app` with the ``guard_config_invalid``
    or ``guard_redis_unavailable`` event.
    """

    factory = redis_client_factory or build_runtime_redis_client
    try:
        config = load_config()
    except (ConfigError, ValueError, TypeError) as exc:
        logger.info(
            "event=guard_config_invalid code=%s", getattr(exc, "code", "config_invalid")
        )
        return create_app(config=None, redis_client=None)

    try:
        redis_client = factory(config.redis_url)
    except (RuntimeError, ValueError, TypeError, OSError) as exc:
        logger.info(
            "event=guard_redis_unavailable reason=%s",
            exc.__class__.__name__,
        )
        return create_app(config=config, redis_client=None)

    return create_app(config=config, redis_client=redis_client)


if __name__ == "__main__":  # pragma: no cover - operator entry point
    import os

    import uvicorn
    from fastapi import FastAPI

    configured: FastAPI = build_app()
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(configured, host="0.0.0.0", port=port)


__all__ = ["GuardConfig", "build_app"]
