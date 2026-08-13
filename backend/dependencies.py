import os
import secrets
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config.database_url import normalize_database_url
from backend.config.settings import load_settings

DEFAULT_URL = "postgresql+psycopg:///supernova_test"

_engine = create_engine(
    normalize_database_url(os.environ.get("SUPERNOVA_DATABASE_URL", DEFAULT_URL))
)
_SessionLocal = sessionmaker(
    bind=_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_session() -> Iterator[Session]:
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()


ADMIN_TOKEN_HEADER = "X-Admin-Token"

_ADMIN_TOKEN_MISSING_DETAIL = "Administrative credential required"
_ADMIN_TOKEN_MISCONFIGURED_DETAIL = (
    "Administrative credential authentication is unavailable"
)


def _coerce_admin_token_header(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned


def require_admin_token(
    x_admin_token: str | None = Header(default=None, alias=ADMIN_TOKEN_HEADER),
) -> None:
    raw_configured = load_settings().order_management_admin_token
    configured_token = (
        raw_configured.strip() if isinstance(raw_configured, str) else None
    )
    if not configured_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_ADMIN_TOKEN_MISCONFIGURED_DETAIL,
        )

    presented_token = _coerce_admin_token_header(x_admin_token)
    if presented_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_ADMIN_TOKEN_MISSING_DETAIL,
        )

    if not secrets.compare_digest(presented_token, configured_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_ADMIN_TOKEN_MISSING_DETAIL,
        )


_pilot_basic_security = HTTPBasic(auto_error=False)


def require_admin_pilot_basic(
    credentials: Annotated[
        HTTPBasicCredentials | None, Depends(_pilot_basic_security)
    ],
) -> None:
    """Validate the panel-only HTTP Basic credential.

    The username is ignored; the password must match the configured
    ``order_management_admin_token`` with a constant-time comparison.
    The header name and the configured token are never echoed back:
    failures reuse the same generic administrative detail used by the
    JSON API dependency, so the panel cannot be used to probe the
    token. The dependency never opens a database session and never
    logs the credential. It is intended for the
    ``/admin/pilot/orders`` route family only; every other JSON route
    keeps the ``X-Admin-Token`` contract unchanged.
    """
    raw_configured = load_settings().order_management_admin_token
    configured_token = (
        raw_configured.strip() if isinstance(raw_configured, str) else None
    )
    if not configured_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_ADMIN_TOKEN_MISCONFIGURED_DETAIL,
            headers={"WWW-Authenticate": "Basic"},
        )

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_ADMIN_TOKEN_MISSING_DETAIL,
            headers={"WWW-Authenticate": "Basic"},
        )

    presented_password = credentials.password or ""
    if not secrets.compare_digest(presented_password, configured_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_ADMIN_TOKEN_MISSING_DETAIL,
            headers={"WWW-Authenticate": "Basic"},
        )


__all__ = [
    "ADMIN_TOKEN_HEADER",
    "get_session",
    "require_admin_pilot_basic",
    "require_admin_token",
]
