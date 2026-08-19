"""FastAPI dependencies shared across the T-C adapter routes.

The module owns the configuration-loading dependency so the routes can
import it without creating a circular dependency on
:mod:`commerce_adapter.app.main`. Tests override
:func:`build_config_dependency` to inject a custom configuration
without touching the global environment.
"""
from __future__ import annotations

import logging

from fastapi import Depends

from commerce_adapter.app.config import (
    CommerceAdapterConfig,
    CommerceAdapterConfigError,
    load_config_from_env,
)

logger = logging.getLogger(__name__)


def build_config_dependency() -> CommerceAdapterConfig:
    """Load the configuration from environment variables.

    The dependency is a plain function so ``app.dependency_overrides``
    can substitute it in tests. A missing or malformed value raises
    :class:`CommerceAdapterConfigError` and the application refuses to
    start the first request.
    """
    try:
        return load_config_from_env()
    except CommerceAdapterConfigError as exc:
        logger.error(
            "commerce_adapter_configuration_failure",
            extra={"reason": type(exc).__name__},
        )
        raise


def get_config(
    config: CommerceAdapterConfig = Depends(build_config_dependency),  # noqa: B008
) -> CommerceAdapterConfig:
    return config


__all__ = [
    "build_config_dependency",
    "get_config",
]