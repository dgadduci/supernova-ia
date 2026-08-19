"""Health route.

The endpoint is a plain ping and never touches any external service.
The bounded observability tooling can poll it without exposing any
sensitive state.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> JSONResponse:
    return JSONResponse(status_code=200, content={"status": "ok"})


__all__ = ["router"]